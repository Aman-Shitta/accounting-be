from __future__ import annotations

import os
import sys
import logging
import tempfile
import re
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, List
from collections import defaultdict

from django.conf import settings

from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from extractor.base import BaseDocumentProcessor
from extractor.prompter import Configuration
from account.models import (
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
    MonthlyAccountingDocument
)
from django.db import transaction
from extractor.utils import split_pdf_to_pages

from extractor.banking.statement_models import (
    BankStatementExtraction
)

# from extractor.rectifier.rectify_v2 import DocumentAIProcessor

logger = logging.getLogger(__name__)


def convert_decimals_to_float(obj):
    """
    Recursively convert all Decimal objects to floats for JSON serialization.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    else:
        return obj


class DocumentProcessorV1(BaseDocumentProcessor):
    """
    Simplified document processor that processes the entire bank statement document
    at once using the BankStatementExtraction schema, then post-processes and saves
    the extracted data to the database.

    Supports debug storage for saving intermediate processing files to Azure for
    tracking and debugging purposes.
    """

    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.extracted_data: Optional[Dict] = None
        self.extracted_meta_data = None
        self.control_totals: Dict = {}
        self.markdown_content: Dict = {}
        self.landing_metadata: Dict = {}
        # Store page bytes for rectification
        self.page_bytes_list: List[bytes] = []
        # Store gemini output per page
        self.gemini_output: Dict[str, List] = {}
        self.rectified_data: Dict = {}

        # Debug storage for saving intermediate files (optional)
        self.debug_storage = None

        # Initialize rectifier
        self.transaction_rectifier = self._get_transactions_rectifier()

        # Initialize LandingAI client
        api_key = settings.LANDING_AI_API_KEY
        if not api_key:
            logger.error("LANDING_AI_API_KEY not found in settings or env.")

        self.client = LandingAIADE(apikey=api_key)
        # self.doc_ai = DocumentAIProcessor()

        # Prepare the unified extraction schema
        self.extraction_schema = pydantic_to_json_schema(
            BankStatementExtraction)

    def set_debug_storage(self, debug_storage):
        """
        Set the debug storage helper for saving intermediate files.

        Args:
            debug_storage: DocumentDebugStorage instance
        """
        self.debug_storage = debug_storage
        logger.info(f"Debug storage enabled for document {self.document.id}")

    def _get_transactions_rectifier(self):
        """Initialize and return the document rectifier."""
        # from extractor.rectifier.rectify import DocumentRectifier
        # return DocumentRectifier()
        # from extractor.rectifier.rectify_v2 import get_rectifier

        from extractor.rectifier.rectify_v4 import get_rectifier
        return get_rectifier()

    def _generate_temp_file(self, file_bytes: bytes) -> tempfile.NamedTemporaryFile:
        """Generate a temporary file from bytes for LandingAI processing."""
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_pdf.write(file_bytes)
        temp_pdf.flush()
        return temp_pdf

    def _clean_temp_file(self, temp_pdf: tempfile.NamedTemporaryFile):
        """Clean up temporary file."""
        try:
            temp_pdf.close()
            os.unlink(temp_pdf.name)
        except Exception:
            pass

    def _parse_document(self, pdf_path: str):
        """
        Parse the entire PDF document and return markdown content.
        """
        parse_response = self.client.parse(
            document=Path(pdf_path),
            model=settings.LANDING_AI_ADE_MODEL,
        )
        self.markdown_content = parse_response.markdown

    def _extract_data(self):
        """
        Extract structured data from markdown using the BankStatementExtraction schema.
        """
        # extract-20251024
        response = self.client.extract(
            schema=self.extraction_schema,
            markdown=BytesIO(self.markdown_content.encode('utf-8')),
        )

        self.extracted_data = response.extraction
        self.extracted_meta_data = response.extraction_metadata
        self.landing_metadata = response.metadata.to_dict()

    def brute_page_fix(self):
        """
        Update transaction page numbers using metadata references.
        References are formatted as "page_index-..." where page_index is 0-based.

        First sorts both transactions and metadata by their 'id' field to ensure alignment.
        """
        transactions = self.extracted_data.get('transactions', [])
        metadata_transactions = self.extracted_meta_data.get(
            'transactions', []) if self.extracted_meta_data else []

        # Sort transactions by 'id' field
        try:
            transactions.sort(key=lambda x: (
                x.get('grounding', {}).get('top'),))
            transactions.sort(
                key=lambda x: (
                    x.get('global_id'),
                    x.get('y_coord')
                ))

            metadata_transactions.sort(
                key=lambda x: (
                    x['global_id']['value'],
                    x['y_coord']['value']
                ))
        except Exception as e:
            logger.error(f"Error sorting transactions for page fix: {e}")

        logger.info(
            f"Sorted {len(transactions)} transactions and {len(metadata_transactions)} metadata entries by id")

        last_known_page_number = 1
        for i in range(len(transactions)):
            try:
                # Use loop index i to access both data and metadata (both are 0-indexed arrays)
                if i >= len(metadata_transactions):
                    continue

                actual_page_number_str = None

                # Look through all fields in the transaction to find a reference
                for field_item in ['amount', 'description']:
                    field_metadata = metadata_transactions[i].get(
                        field_item, {})
                    references = field_metadata.get('references', [])

                    if references:
                        # Sort references and get the first one
                        sorted_refs = sorted(references)
                        ref_str = sorted_refs[0]

                        # Extract page number from reference format "page_index-..."
                        parts = ref_str.split('-')
                        if parts and parts[0].strip().isdigit():
                            actual_page_number_str = parts[0].strip()
                            logger.debug(
                                f"Found page reference for transaction {i} (global_id={transactions[i].get('global_id')}): page {actual_page_number_str} from field '{field_item}'")
                            break

                # Update page number if we found a valid reference
                if actual_page_number_str is not None:
                    # Convert from 0-indexed to 1-indexed page number
                    actual_page_number = int(actual_page_number_str) + 1
                    transactions[i]['page_number'] = actual_page_number
                    transactions[i]['id'] = transactions[i]['local_id']
                    last_known_page_number = actual_page_number

                if not actual_page_number_str:
                    # If no reference found, use last known page number
                    transactions[i]['page_number'] = last_known_page_number
            except Exception as e:
                logger.error(
                    f"Error updating page number for transaction index {i}: {e}")

        logger.info(
            f"Transaction page numbers fixed for {len(transactions)} transactions")

        # Update self.extracted_data with sorted transactions (keep as dict structure)
        self.extracted_data['transactions'] = transactions

    def process_document(self, file_bytes: bytes, **kwargs) -> Dict:
        """
        Process the entire bank statement document at once.

        1. Split PDF into pages (for rectification)
        2. Parse the full PDF to markdown
        3. Extract all transactions and summary using the unified schema
        4. Rectify amounts page by page
        5. Post-process and save to database

        Saves debug files at each stage if debug_storage is configured:
        - Parsed markdown to _debug_files/02_parsed_markdown/
        - Extracted data to _debug_files/03_extracted_data/
        - Rectified data to _debug_files/04_rectified_data/
        """
        temp_file = None

        try:
            # Step 0: Split PDF into pages for later rectification
            # logger.info("Splitting PDF into pages...")
            # self.page_bytes_list = split_pdf_to_pages(file_bytes)
            # logger.info(f"Document has {len(self.page_bytes_list)} pages")

            # Step 1: Generate temp file and parse entire document
            logger.info("Parsing entire document to markdown...")
            temp_file = self._generate_temp_file(file_bytes)

            self._parse_document(temp_file.name)

            if not self.markdown_content:
                logger.error("No markdown extracted from document")
                return {"status": "error", "message": "Failed to extract markdown from document"}

            logger.info(
                f"Extracted {len(self.markdown_content)} characters of markdown")

            # Save parsed markdown to debug folder
            if self.debug_storage:
                self.debug_storage.save_parsed_markdown(
                    self.markdown_content, "full_document_markdown.md")
                logger.info("Saved parsed markdown to debug folder")

            # Step 2: Extract structured data using unified schema
            logger.info("Extracting transactions and summary from document...")
            self._extract_data()

            if not self.extracted_data:
                logger.error("No data extracted from document")
                return {"status": "error", "message": "Failed to extract data from document"}

            # Save extracted data to debug folder (before rectification)
            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    convert_decimals_to_float(self.extracted_data),
                    "landing_ai_extracted_data.json"
                )
                if self.extracted_meta_data:
                    self.debug_storage.save_extracted_metadata(
                        convert_decimals_to_float(self.extracted_meta_data),
                        "landing_ai_extraction_metadata.json"
                    )
                if self.landing_metadata:
                    self.debug_storage.save_extracted_data(
                        convert_decimals_to_float(self.landing_metadata),
                        "landing_ai_response_metadata.json"
                    )
                logger.info("Saved extracted data to debug folder")

            print("landing_metadata :: ", self.landing_metadata)
            self.brute_page_fix()

            # Save data after page fix
            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    convert_decimals_to_float(self.extracted_data),
                    "extracted_data_after_page_number_fix.json"
                )

            # Step 3: Rectify amounts page by page
            logger.info("Rectifying extracted amounts...")

            # raw_doc_data = self.doc_ai.process(
            #     page_bytes=file_bytes,
            #     mime_type="application/pdf"
            # )

            self._rectify(file_bytes)

            # Save rectified data to debug folder
            if self.debug_storage:
                self.debug_storage.save_rectified_data(
                    convert_decimals_to_float(self.rectified_data),
                    "rectified_transactions.json"
                )
                if self.rectified_data.get("rectifier_items"):
                    self.debug_storage.save_rectifier_items(
                        convert_decimals_to_float(
                            self.rectified_data.get("rectifier_items", []))
                    )
                logger.info("Saved rectified data to debug folder")

            # Step 4: Post-process and extract control totals
            self._process_control_totals()

            self._save_control_totals()
            processing_stats = self._save_extracted_data()

            return {
                "status": "success",
                "control_totals": self.control_totals,
                "processing_stats": processing_stats,
                "transaction_count": len(self.extracted_data.get("transactions", []))
            }

        except Exception as e:
            logger.error(f"Error processing document: {e}")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

            # Save error to debug folder
            if self.debug_storage:
                self.debug_storage.save_error_log(e, {
                    "stage": "process_document",
                    "has_markdown": bool(self.markdown_content),
                    "has_extracted_data": bool(self.extracted_data)
                })

            return {"status": "error", "message": str(e)}

        finally:
            if temp_file:
                self._clean_temp_file(temp_file)
            self._save_doc_metadata()

    def _process_control_totals(self):
        """Extract and process control totals from the summary."""
        summary = self.extracted_data.get("summary", {})

        self.control_totals = {
            "beginning_balance": summary.get("beginning_balance"),
            "ending_balance": summary.get("ending_balance"),
            "total_deposits": summary.get("total_deposits"),
            "total_withdrawals": summary.get("total_withdrawals"),
            "total_credits_count": summary.get("total_credits_count"),
            "total_withdrawl_count": summary.get("total_withdrawl_count"),
        }

        logger.info(f"Control totals extracted: {self.control_totals}")

    def _rectify(self, file_bytes):

        transactions = self.extracted_data.get("transactions", [])

        self.rectified_data = dict(
            {
                'transactions': [],
                'summary': self.extracted_data.get('summary', {}),
                'rectifier_items': []
            }
        )

        rectified_items, rectifier_items = self.transaction_rectifier.rectify_document(
            file_bytes,
            master_data=transactions,
            debug_storage=self.debug_storage
        )
        self.rectified_data['transactions'] = rectified_items
        self.rectified_data['rectifier_items'] = rectifier_items

    def _save_control_totals(self):
        """Save control totals to document."""
        try:
            self.document.control_item = convert_decimals_to_float(
                self.control_totals)
            self.document.save()
            logger.info("Control totals saved to document")
        except Exception as e:
            logger.error(f"Failed to save control totals: {e}")
            self.document.control_item = {}
            self.document.save()

    def _save_doc_metadata(self):
        """Save document-level metadata including gemini output."""
        try:
            metadata = {
                "markdown": self.markdown_content,
                "extracted_data": convert_decimals_to_float(self.extracted_data),
                "control_totals": convert_decimals_to_float(self.control_totals),
                "landing_metadata": convert_decimals_to_float(self.landing_metadata),
                "gemini_output": convert_decimals_to_float(self.gemini_output),
                "rectifier_items": convert_decimals_to_float(self.rectified_data.get("rectifier_items", []))
            }
            self.document.markdown_metadata = metadata
            self.document.save()
            logger.info("Document metadata saved")
        except Exception as e:
            logger.error(f"Failed to save markdown metadata: {e}")
            self.document.markdown_metadata = {}
            self.document.save()

    def _truncate_decimal_to_2_places(self, value: Decimal) -> Decimal:
        """Truncate Decimal to 2 decimal places without rounding."""
        # Use quantize with ROUND_DOWN to truncate
        from decimal import ROUND_DOWN
        return value.quantize(Decimal('0.01'), rounding=ROUND_DOWN)

    def _parse_amount(self, amount_value) -> Optional[Decimal]:
        """Parse amount to Decimal, truncated to 2 decimal places."""
        if amount_value is None:
            return None

        if isinstance(amount_value, (int, float)):
            value = Decimal(str(amount_value))
            return self._truncate_decimal_to_2_places(value)

        amount_str = str(amount_value).strip()
        if amount_str in ['', 'null', 'none', '-']:
            return None

        # Clean the amount string
        amount_str = re.sub(r'[^\d\.\-]', '', amount_str)

        try:
            value = Decimal(amount_str)
            return self._truncate_decimal_to_2_places(value)
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_value}': {e}")
            return None

    def _format_date(self, date_str: str) -> str:
        """
        Format date string to standard DD-Month-YYYY format.
        Handles formats like: Jun1, 2025 | 1 June 2025 | 06/01/2025 | 6-1-2025
        """
        from dateutil import parser

        if not date_str or not str(date_str).strip():
            return date_str

        date_str = str(date_str).strip()

        month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December"
        }

        try:
            parsed_date = parser.parse(date_str, dayfirst=False, fuzzy=True)
            day = parsed_date.day
            month_name = month_names[parsed_date.month]
            year = parsed_date.year
            return f"{day:02d}-{month_name}-{year}"
        except (ValueError, parser.ParserError) as e:
            # Try MM/YYYY pattern (assume day 01)
            match = re.match(r'(\d{1,2})[/-](\d{4})', date_str)
            if match:
                month, year = match.groups()
                month_num = int(month)
                if 1 <= month_num <= 12:
                    month_name = month_names[month_num]
                    return f"01-{month_name}-{year}"

            logger.warning(f"Could not parse date format: {date_str}")
            return date_str

    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Post-process and save extracted transactions to the database.
        """
        stats = {
            "line_items": 0,
            "check_items": 0,
            "pages_processed": set()
        }

        transactions = self.rectified_data.get("transactions", [])

        if not transactions:
            logger.warning("No transactions found in extracted data")
            return {"line_items": 0, "check_items": 0, "pages_processed": 0}

        logger.info(f"Processing {len(transactions)} transactions...")

        # Track checks for linking
        checks_by_number: Dict[str, MonthlyDocumentBankLineItem] = {}

        with transaction.atomic():
            for idx, txn in enumerate(transactions):

                line_item = self._save_transaction(idx + 1, txn)
                stats["line_items"] += 1
                stats["pages_processed"].add(txn.get("page_number", 1))

                # Track check transactions for potential linking
                if line_item.is_check_transaction and line_item.check_number:
                    checks_by_number[line_item.check_number] = line_item

        stats["pages_processed"] = len(stats["pages_processed"])
        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _save_transaction(self, line_number: int, txn_data: Dict) -> MonthlyDocumentBankLineItem:
        """
        Save a single transaction to the database.
        """
        # Extract and format date
        date = self._format_date(txn_data.get("date", ""))

        # Extract description
        description = txn_data.get("description", "")

        # Extract amount and type
        amount = self._parse_amount(txn_data.get("amount"))
        transaction_type = txn_data.get(
            "type", "").lower()  # 'debit' or 'credit'

        # Determine debit/credit amounts
        debit_amount = None
        credit_amount = None

        if transaction_type == "debit" and amount:
            debit_amount = str(amount)
        elif transaction_type == "credit" and amount:
            credit_amount = str(amount)

        # Check transaction detection
        check_number = txn_data.get("check_number", "")
        is_check_transaction = bool(check_number and str(check_number).strip())

        # Clean check number
        if check_number:
            check_number = str(check_number).lstrip('0').strip('*')
            check_number = re.sub(r'[^\d\.]', '', check_number)
            if not check_number:
                is_check_transaction = False
                check_number = None

        # Get page number
        page_number = txn_data.get("page_number", 1)

        # Extract rectification metadata
        is_rectified = txn_data.get("is_rectified", False)
        was_missing = txn_data.get("was_missing", False)
        was_compared = txn_data.get("was_compared", False)

        # Create line item
        line_item = MonthlyDocumentBankLineItem.objects.create(
            document=self.document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type if transaction_type in [
                'debit', 'credit'] else None,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            is_check_transaction=is_check_transaction,
            check_number=check_number if is_check_transaction else None,
            # Rectification fields
            is_rectified=is_rectified,
            was_missing=was_missing,
            was_compared=was_compared,
            gl_account=None,
            offset_gl_account=None
        )

        # If this is a check transaction, also create a check item
        if is_check_transaction:
            self._create_check_item_from_transaction(line_item, txn_data)

        return line_item

    def _create_check_item_from_transaction(self, line_item: MonthlyDocumentBankLineItem, txn_data: Dict):
        """
        Create a check item from a transaction if it's a check transaction.
        """
        check_written_date = txn_data.get("check_written_date", "")
        if check_written_date:
            check_written_date = self._format_date(check_written_date)

        # Extract payee and memo from description if present
        description = txn_data.get("description", "")
        payee = ""
        memo = ""

        # Try to extract payee from description patterns like "Check #123 to John Doe"
        payee_match = re.search(
            r'(?:to|payee[:\s]+)([^-]+)', description, re.IGNORECASE)
        if payee_match:
            payee = payee_match.group(1).strip()

        memo_match = re.search(
            r'(?:memo[:\s]+)(.+)', description, re.IGNORECASE)
        if memo_match:
            memo = memo_match.group(1).strip()

        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.document,
            page_number=line_item.page_number,
            amount=str(line_item.amount) if line_item.amount else "",
            payee=payee,
            memo=memo,
            clearing_date=line_item.date,
            passing_date=check_written_date,
            check_number=line_item.check_number,
            related_line_item=line_item
        )

        logger.debug(f"Created check item for check #{line_item.check_number}")
        return check_item
