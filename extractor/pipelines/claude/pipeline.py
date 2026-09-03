from __future__ import annotations

import os
import sys
import logging
from typing import Dict, List, Optional

from pydantic import ValidationError

from extractor.base import BaseDocumentProcessor
from extractor.claude_service import ClaudeMixin
from extractor.utils import split_pdf_to_pages
from account.models import MonthlyAccountingDocument
from extractor.persistence.bank_statement_saver import BankStatementSaver
from extractor.pipelines.claude.models import PageExtraction, PageTransaction, CheckImageData
from extractor.statement_models import (
    StatementTransaction,
    BankStatementExtraction,
    StatementSummaryTotals,
)

logger = logging.getLogger(__name__)


"""
Prompt sent to Claude for each page
"""
PAGE_EXTRACTION_PROMPT = """You are an expert financial document parser specializing in bank statements.

Analyze this SINGLE PAGE (page {page_number} of {total_pages}) of a bank statement and extract ALL data present.

**FORMAT DETECTION:**
Bank statements come in different layouts. Identify which format this page uses:
- **Unified table**: A single table with all transactions (debits and credits) together,
  often with separate Debit/Credit columns or a single Amount column with +/- signs.
- **Split tables**: Separate sections for "Deposits/Credits" and "Withdrawals/Debits"
  (or "Checks Paid" separate from "Other Withdrawals").
- **Compact checks table**: A dense multi-column table listing check numbers, dates, and amounts.
  A single row may contain 2-5 checks side by side — split each into a separate transaction.

Regardless of format, normalize all transactions into the unified schema with `type`
indicating "debit" or "credit".

**EXTRACT FOUR CATEGORIES:**

1. **transactions** — Every deposit and withdrawal transaction listed on this page.
   - Include check transactions that appear inline within deposit/withdrawal tables.
   - `local_id`: Sequential starting at 1 for this page.
   - `date`: In mm/dd/yyyy format.
   - `check_number`: The check number if this is a check transaction, otherwise empty string.
   - `description`: Full description/narration.
   - `amount`: Positive number (no currency symbols or commas).
   - `y_coord`: Approximate vertical position (0-1000, top=0).
   - `type`: "debit" (money out) or "credit" (money in).

2. **check_table** — Transactions from a SEPARATE checks-paid/checks-cleared table,
   ONLY if those checks are NOT already listed in the main transactions above.
   If checks are already part of the main transaction listing, leave this empty.
   Use the same field format as transactions.

3. **check_images** — Data from check images/stubs printed on this page:
   - `check_number`: The number on the check.
   - `amount`: Amount if readable.
   - `payee`: Pay-to-the-order-of name.
   - `memo`: Memo line text.
   - `date`: Date on the check in mm/dd/yyyy format if readable.

4. **summary** — Statement summary totals ONLY if they appear on THIS page:
   - `beginning_balance`, `ending_balance`, `total_deposits`, `total_withdrawals`
   - `total_credits_count`, `total_withdrawl_count`
   - Set to null if no summary is on this page.

**ORDERING:**
- Maintain document reading order (top to bottom) within each category on the page.
- For split tables, follow the top-to-bottom order as sections appear on the page.
- Assign `local_id` sequentially across all categories on the page
  (transactions first, then check_table if separate).

**CHECK TABLE vs TRANSACTIONS:**
- If checks appear as rows in the main transaction table (e.g., "Check #1234"
  in the description column), include them in `transactions` with `check_number` filled.
- If checks appear in a SEPARATE table (e.g., "Checks Paid", "Checks Cleared"),
  put them in `check_table`.
- NEVER include the same check in both `transactions` and `check_table`.

**IMPORTANT:**
- Extract ALL transactions — do not skip any.
- Amounts must be positive numbers regardless of debit/credit.
- Dates must be in mm/dd/yyyy format.
- Do not include summary rows, balance rows, or fee descriptions as transactions.
- If a page has no transactions (e.g. only check images), return empty transactions list.

Use the `save_page_extraction` tool to return the extracted data."""


class ExtractorPipeline(BaseDocumentProcessor, ClaudeMixin):
    """
    Document processor that uses Claude (Anthropic) to extract bank statement
    data page-by-page via the document API.
    """

    TOOL_NAME = "save_page_extraction"
    TOOL_DESCRIPTION = (
        "Save the extracted data from a single page of the bank statement "
        "including transactions, check table entries, check images, and summary."
    )

    def __init__(self, doc: MonthlyAccountingDocument):
        super().__init__(doc)
        self.init_claude()

        self.extracted_data: Optional[BankStatementExtraction] = None
        self.control_totals: Dict = {}
        self.rectified_data: Dict = {}
        self.claude_raw_responses: List[Dict] = []

        # Per-page validated extractions
        self.page_extractions: List[PageExtraction] = []

        # Initialize rectifier
        self.transaction_rectifier = self._get_transactions_rectifier()

        # Tool schema is derived from the page-level Pydantic model
        self.tool_schema = self.claude.build_tool_schema(
            name=self.TOOL_NAME,
            description=self.TOOL_DESCRIPTION,
            input_schema=PageExtraction,
        )

    def _get_transactions_rectifier(self):
        """Initialize and return the document rectifier."""
        from extractor.rectifier.rectify import get_rectifier
        return get_rectifier()

    def _extract_page(
        self, page_bytes: bytes, page_number: int, total_pages: int
    ) -> PageExtraction:
        """
        Send a single PDF page to Claude and get structured extraction.
        Returns a validated PageExtraction model instance.
        """
        prompt = PAGE_EXTRACTION_PROMPT.format(
            page_number=page_number, total_pages=total_pages
        )

        raw_data, meta = self.claude_stream_tool_with_meta(
            messages=[
                {
                    "role": "user",
                    "content": [
                        self.claude.create_pdf_part(page_bytes),
                        self.claude.create_text_part(prompt),
                    ],
                }
            ],
            tool=self.tool_schema,
            max_tokens=16000,
        )

        self.claude_raw_responses.append({"page_number": page_number, **meta})

        try:
            return PageExtraction.model_validate(raw_data)
        except ValidationError as ve:
            logger.warning(
                f"Validation issue on page {page_number}: {ve}. "
                "Attempting lenient parse."
            )
            return PageExtraction.model_validate(raw_data, strict=False)

    def _merge_page_extractions(
        self, page_results: List[PageExtraction]
    ) -> BankStatementExtraction:
        """
        Merge per-page extractions into a single BankStatementExtraction
        with validated StatementTransaction instances.
        """
        all_transactions: List[StatementTransaction] = []
        summary: Optional[StatementSummaryTotals] = None
        global_id = 1

        for page_num, page_data in enumerate(page_results, start=1):
            # Build check image lookup by check number
            check_image_map: Dict[str, CheckImageData] = {}
            for ci in page_data.check_images:
                cn = ci.check_number.strip()
                if cn:
                    check_image_map[cn] = ci

            # Collect page transactions and merge check_table entries
            page_txns: List[PageTransaction] = list(page_data.transactions)

            existing_check_nums = {
                t.check_number.strip() for t in page_txns if t.check_number
            }
            for ct in page_data.check_table:
                cn = ct.check_number.strip()
                if cn and cn not in existing_check_nums:
                    page_txns.append(ct)
                    existing_check_nums.add(cn)

            # Sort by document order
            page_txns.sort(key=lambda t: (t.local_id, t.y_coord))

            for txn in page_txns:
                enrichments: Dict = {}
                description = txn.description
                cn = txn.check_number.strip()

                if cn and cn in check_image_map:
                    ci_data = check_image_map[cn]
                    enrichments["check_payee"] = ci_data.payee
                    enrichments["check_memo"] = ci_data.memo
                    enrichments["check_written_date"] = ci_data.date

                    # Enrich description with payee/memo if not already present
                    parts = []
                    if ci_data.payee and ci_data.payee.lower() not in description.lower():
                        parts.append(f"Payee: {ci_data.payee}")
                    if ci_data.memo and ci_data.memo.lower() not in description.lower():
                        parts.append(f"Memo: {ci_data.memo}")
                    if parts:
                        description = description + " | " + " | ".join(parts)

                stmt_txn = StatementTransaction(
                    global_id=global_id,
                    date=txn.date,
                    check_number=txn.check_number,
                    description=description,
                    amount=txn.amount,
                    y_coord=txn.y_coord,
                    local_id=txn.local_id,
                    type=txn.type,
                    page_number=page_num,
                    **enrichments,
                )
                all_transactions.append(stmt_txn)
                global_id += 1

            # Capture first available summary
            if page_data.summary and summary is None:
                summary = page_data.summary

        if summary is None:
            summary = StatementSummaryTotals(
                beginning_balance=0,
                ending_balance=0,
                total_deposits=0,
                total_withdrawals=0,
                total_credits_count=0,
                total_withdrawl_count=0,
            )

        return BankStatementExtraction(transactions=all_transactions, summary=summary)

    def process_document(self, file_bytes: bytes, **kwargs) -> Dict:
        """
        Process the entire bank statement document.
        """
        saver = BankStatementSaver(self.document)
        processing_stats = {"line_items": 0, "check_items": 0, "pages_processed": 0}

        try:
            page_bytes_list = split_pdf_to_pages(file_bytes)
            total_pages = len(page_bytes_list)

            self.page_extractions = []
            for page_num, page_bytes in enumerate(page_bytes_list, start=1):
                page_data = self._extract_page(
                    page_bytes, page_num, total_pages
                )
                self.page_extractions.append(page_data)

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    [pe.model_dump() for pe in self.page_extractions],
                    "claude_page_extractions.json"
                )

            self.extracted_data = self._merge_page_extractions(self.page_extractions)

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    self.extracted_data.model_dump(),
                    "claude_extracted_data.json",
                )
                if self.claude_raw_responses:
                    self.debug_storage.save_extracted_data(
                        self.claude_raw_responses,
                        "claude_response_metadata.json",
                    )

            self._process_control_totals()

            # Save using centralized persistence — convert to dicts at boundary
            saver.save_control_totals(self.control_totals)
            transaction_dicts = [txn.model_dump() for txn in self.extracted_data.transactions]
            processing_stats = saver.save_transactions(transaction_dicts)

            return {
                "status": "success",
                "control_totals": self.control_totals,
                "processing_stats": processing_stats,
                "transaction_count": len(self.extracted_data.transactions),
                "pages_processed": total_pages,
            }

        except Exception as e:
            logger.error(f"Error processing document: {e}")
            exc_type, _, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}"
            )

            if self.debug_storage:
                self.debug_storage.save_error_log(e, {
                    "stage": "process_document",
                    "has_extracted_data": bool(self.extracted_data),
                    "pages_extracted": len(self.page_extractions),
                })

            return {"status": "error", "message": str(e)}

        finally:
            metadata = {
                "extracted_data": self.extracted_data.model_dump() if self.extracted_data else None,
                "control_totals": self.control_totals,
                "claude_responses": self.claude_raw_responses,
                "page_extractions": [pe.model_dump() for pe in self.page_extractions],
                "rectifier_items": self.rectified_data.get("rectifier_items", []),
            }
            saver.save_metadata(metadata)

    def _rectify(self, file_bytes: bytes):
        transaction_dicts = [t.model_dump() for t in self.extracted_data.transactions]
        self.rectified_data = {
            "transactions": [],
            "summary": self.extracted_data.summary.model_dump(),
            "rectifier_items": [],
        }

        rectified_items, rectifier_items = self.transaction_rectifier.rectify_document(
            file_bytes,
            master_data=transaction_dicts,
            debug_storage=self.debug_storage,
        )
        self.rectified_data["transactions"] = rectified_items
        self.rectified_data["rectifier_items"] = rectifier_items

    def _process_control_totals(self):
        """Extract and process control totals from the summary."""
        self.control_totals = self.extracted_data.summary.model_dump()