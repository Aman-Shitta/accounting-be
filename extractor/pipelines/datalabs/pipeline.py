"""
Datalabs multi-stage extraction pipeline.

Flow
----
 0. **Datalabs pipeline** — single execution that runs both Marker parse
    (step 0) and page segmentation (step 1), saving one API call.
 1. **LLM Call 1** — extract transactions from ALL HTML tables.
 2. **LLM Call 2** — extract summary / control-totals from text.
 3. **LLM Call 3** *(conditional)* — OCR check images from pages
    identified by segmentation.
 4. **Deterministic merge** — enrich check transactions with OCR data.
 5. **Persist** — save via ``BankStatementSaver``.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from extractor.base import BaseDocumentProcessor
from extractor.persistence.bank_statement_saver import BankStatementSaver
from extractor.pipelines.datalabs.backends import resolve_backends
from extractor.pipelines.datalabs.parser import DatalabsParser
from extractor.utils import clean_temp_file, generate_temp_pdf
from v1.periods.models import PeriodDocument

logger = logging.getLogger(__name__)


class ExtractorPipeline(BaseDocumentProcessor):
    """Datalabs single-pipeline (parse + segment) → 3-stage LLM extract → merge → save."""

    def __init__(self, doc: PeriodDocument):
        super().__init__(doc)
        self.parser = DatalabsParser()

        # Three focused LLM backends. Which provider reads this document is
        # the owning firm's choice (Firm.extraction_provider), not a fixed
        # import — see backends.resolve_backends.
        provider = doc.client.firm.extraction_provider
        TransactionExtractor, SummaryExtractor, CheckImageExtractor = resolve_backends(provider)
        self.transaction_extractor = TransactionExtractor(doc)
        self.summary_extractor = SummaryExtractor(doc)
        self.check_image_extractor = CheckImageExtractor(doc)

        # Intermediate state for debugging
        self.segmentation_result: dict[str, Any] = {}
        self.tables_by_page: dict[int, Any] = {}
        self.text_content: str = ""
        self.transactions: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {}
        self.check_images: list[dict[str, Any]] = []
        self.check_pages: list[int] = []

    def process_document(self, file_bytes: bytes, **kwargs) -> dict[str, Any]:
        saver = BankStatementSaver(self.document)
        temp_file = None

        try:
            temp_file = generate_temp_pdf(file_bytes)

            # ── Stage 0: Single pipeline (Marker + Segmentation) ──
            logger.info("Running Datalabs pipeline (parse + segment)...")
            execution = self.parser.run_pipeline(temp_file.name)

            # Step 0 — Marker parse (full document)
            parse_json = self.parser.parse(execution)

            # Step 1 — Segmentation
            self.segmentation_result = self.parser.segment(execution)
            self.check_pages = DatalabsParser.resolve_check_pages(
                self.segmentation_result
            )
            logger.info(
                f"Pipeline complete. "
                f"Check pages (0-indexed): {self.check_pages}"
            )

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    self.segmentation_result, "datalabs_segmentation.json"
                )

            self.tables_by_page = DatalabsParser.extract_tables(parse_json)
            self.text_content = self.parser.parse_markdown(execution)

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    parse_json, "datalabs_raw.json"
                )
                self.debug_storage.save_extracted_data(
                    self.tables_by_page, "datalabs_tables.json"
                )
                self.debug_storage.save_parsed_markdown(
                    self.text_content, "datalabs_markdown.md"
                )

            # ── Stage 1: Transaction extraction (ALL tables) ──────
            logger.info(
                f"LLM Call 1: Extracting transactions from "
                f"{len(self.tables_by_page)} pages of tables..."
            )
            self.transactions = self.transaction_extractor.extract(
                self.tables_by_page
            )
            logger.info(
                f"Call 1 complete: {len(self.transactions)} transactions."
            )

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    self.transactions, "datalabs_llm_transactions.json"
                )

            # ── Stage 2: Summary extraction ───────────────────────
            logger.info("LLM Call 2: Extracting summary / control totals...")
            self.summary = self.summary_extractor.extract(self.text_content)
            logger.info(f"Call 2 complete: {self.summary}")

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    self.summary, "datalabs_llm_summary.json"
                )

            # ── Stage 3: Check image OCR (conditional) ────────────
            if self.check_pages:
                logger.info(
                    f"LLM Call 3: structuring check data from Marker HTML "
                    f"on pages {self.check_pages} (0-indexed)..."
                )
                # 1-indexed page numbers for Marker page extraction
                check_pages_1idx = {p + 1 for p in self.check_pages}
                check_page_html = DatalabsParser.extract_pages_html(
                    parse_json, pages=check_pages_1idx
                )

                self.check_images = self.check_image_extractor.extract(
                    check_page_html
                )
                logger.info(
                    f"Call 3 complete: {len(self.check_images)} checks OCR'd."
                )
            else:
                logger.info(
                    "No check pages found — skipping LLM Call 3."
                )
                self.check_images = []

            if self.debug_storage and self.check_images:
                self.debug_storage.save_extracted_data(
                    self.check_images, "datalabs_llm_check_images.json"
                )

            # ── Stage 4: Deterministic merge ──────────────────────
            logger.info("Merging check image data into transactions...")
            enriched = self._merge_check_data(
                self.transactions, self.check_images
            )

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    enriched, "datalabs_merged_transactions.json"
                )

            # ── Stage 5: Persist ──────────────────────────────────
            saver.save_control_totals(self.summary)
            stats = saver.save_transactions(enriched)

            return {
                "status": "success",
                "control_totals": self.summary,
                "processing_stats": stats,
                "transaction_count": len(enriched),
                "pages_processed": len(self.tables_by_page),
                "check_pages_ocrd": len(self.check_pages),
                "checks_enriched": len(self.check_images),
            }

        except Exception as e:
            exc_type, _, exc_tb = sys.exc_info()
            fname = (
                os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                if exc_tb
                else "?"
            )
            lineno = exc_tb.tb_lineno if exc_tb else "?"
            logger.error(
                f"Datalabs pipeline failed for doc {self.document.id}: {e} "
                f"({exc_type} @ {fname}:{lineno})"
            )
            if self.debug_storage:
                self.debug_storage.save_error_log(
                    e,
                    {
                        "stage": "datalabs_pipeline",
                        "pages_parsed": len(self.tables_by_page),
                        "transactions_extracted": len(self.transactions),
                        "check_pages": self.check_pages,
                        "has_summary": bool(self.summary),
                    },
                )
            return {"status": "error", "message": str(e)}

        finally:
            if temp_file:
                clean_temp_file(temp_file)

            # Always try to save metadata for debugging
            try:
                saver.save_metadata(
                    {
                        "segmentation": self.segmentation_result,
                        "check_pages": self.check_pages,
                        "datalabs_tables": self.tables_by_page,
                        "text_content_length": len(self.text_content),
                        "llm_transactions": self.transactions,
                        "llm_summary": self.summary,
                        "llm_check_images": self.check_images,
                    }
                )
            except Exception as meta_err:
                logger.warning(
                    f"Failed to save Datalabs metadata: {meta_err}"
                )


    # ------------------------------------------------------------------
    # Deterministic merge
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_check_data(
        transactions: list[dict[str, Any]],
        check_images: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Enrich check transactions with OCR data matched by check number.

        Enrichment format for description::

            "Original table text | Check #1234 | Payee: ABC Inc | Memo: Inv #789"

        Only appends fields that are present and non-empty.  If no matching
        OCR data is found, the original description is kept as-is.
        """
        # Build lookup: normalized check_number → OCR data
        check_map: dict[str, dict[str, Any]] = {}
        for ci in check_images:
            cn = _normalize_check_number(ci.get("check_number", ""))
            if cn:
                check_map[cn] = ci

        for txn in transactions:
            if not txn.get("is_check"):
                continue

            cn = _normalize_check_number(txn.get("check_number", ""))
            if not cn:
                continue

            if cn in check_map:
                ci = check_map[cn]
                txn["check_payee"] = ci.get("payee", "")
                txn["check_memo"] = ci.get("memo", "")
                txn["check_written_date"] = ci.get("date", "")

                # Build enriched description
                parts = [txn["description"]]
                if cn:
                    parts.append(f"Check #{cn}")
                if ci.get("payee"):
                    parts.append(f"Payee: {ci['payee']}")
                if ci.get("memo"):
                    parts.append(f"Memo: {ci['memo']}")
                txn["description"] = " | ".join(parts)
            else:
                # Check row in table but no matching image — keep original
                txn.setdefault("check_payee", "")
                txn.setdefault("check_memo", "")
                txn.setdefault("check_written_date", "")

        return transactions


def _normalize_check_number(raw: str) -> str:
    """Strip leading zeros and non-digit characters for matching."""
    cleaned = re.sub(r"[^\d]", "", str(raw).strip())
    return cleaned.lstrip("0")
