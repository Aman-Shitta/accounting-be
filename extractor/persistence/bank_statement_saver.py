"""
Persists transaction extraction results.

Single source of truth for turning a pipeline's transaction dicts into
``PeriodTransaction`` and ``PeriodCheckDetail`` rows.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from django.db import transaction as db_transaction

from extractor.base import BaseDocumentProcessor
from extractor.utils import convert_decimals_to_float
from v1.periods.models import PeriodCheckDetail, PeriodDocument, PeriodTransaction

logger = logging.getLogger(__name__)


def _clean_check_number(raw) -> Optional[str]:
    """
    Normalise a check number, or return ``None`` when there isn't one.

    Statements pad with zeros and asterisks, and sometimes put a word where the
    number should be.
    """
    if not raw or not str(raw).strip():
        return None
    cleaned = re.sub(r"[^\d.]", "", str(raw).lstrip("0").strip("*"))
    return cleaned or None


class BankStatementSaver:
    """
    Persistence for bank statement and credit card extraction.

        saver = BankStatementSaver(document)
        stats = saver.save_transactions(transactions)
        saver.save_control_totals(control_totals)
        saver.save_metadata(metadata)
    """

    def __init__(self, document: PeriodDocument):
        self.document = document

    # ---- transactions -----------------------------------------------------

    def save_transactions(self, transactions: List[Dict]) -> Dict[str, int]:
        """
        Persist transaction dicts, creating a check detail row for any
        transaction carrying a check number.

        Expected keys: ``date``, ``description``, ``amount``, ``type``, and
        optionally ``page_number``, ``check_number``, ``check_payee``,
        ``check_memo``, ``check_written_date``.

        Returns counts of what was written.
        """
        if not transactions:
            logger.warning("No transactions found in extracted data")
            return {"transactions": 0, "check_details": 0, "pages_processed": 0}

        logger.info(f"Saving {len(transactions)} transactions...")

        default_offset = self._default_offset_account()
        written, checks, pages = 0, 0, set()

        with db_transaction.atomic():
            for index, txn in enumerate(transactions, start=1):
                missing = {"date", "description", "amount", "type"} - set(txn)
                if missing:
                    logger.warning(f"Skipping transaction {index}, missing {missing}")
                    continue

                row = self._save_transaction(index, txn, default_offset)
                written += 1
                pages.add(row.page_number)

                if row.is_check:
                    self._save_check_detail(row, txn)
                    checks += 1

        stats = {
            "transactions": written,
            "check_details": checks,
            "pages_processed": len(pages),
        }
        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _default_offset_account(self):
        """
        The offset account configured on this document's source — the other
        side of every entry from this statement.
        """
        source = self.document.document_source
        return source.default_offset_account if source else None

    def _save_transaction(
        self, line_number: int, txn: Dict, default_offset
    ) -> PeriodTransaction:
        raw_date = str(txn.get("date") or "").strip()
        direction = str(txn.get("type") or "").lower()
        check_number = _clean_check_number(txn.get("check_number"))

        return PeriodTransaction.objects.create(
            document=self.document,
            page_number=txn.get("page_number", 1),
            line_number=line_number,
            transaction_date=BaseDocumentProcessor.parse_date(raw_date),
            raw_date=raw_date[:64],
            description=txn.get("description", ""),
            amount=BaseDocumentProcessor.parse_amount(txn.get("amount")),
            direction=(
                direction
                if direction in (PeriodTransaction.Direction.DEBIT, PeriodTransaction.Direction.CREDIT)
                else PeriodTransaction.Direction.DEBIT
            ),
            is_check=check_number is not None,
            check_number=check_number or "",
            offset_ledger_account=default_offset,
        )

    def _save_check_detail(self, row: PeriodTransaction, txn: Dict) -> PeriodCheckDetail:
        """
        Record payee and memo for a check.

        The check-image pass supplies these directly; when it has not run, fall
        back to pulling them out of the transaction description.
        """
        description = txn.get("description", "")
        payee = txn.get("check_payee") or self._extract(
            r"(?:to|payee[:\s]+)([^-|]+)", description
        )
        memo = txn.get("check_memo") or self._extract(
            r"(?:memo[:\s]+)(.+?)(?:\||$)", description
        )

        return PeriodCheckDetail.objects.create(
            document=self.document,
            transaction=row,
            page_number=row.page_number,
            check_number=row.check_number,
            amount=row.amount,
            payee=payee,
            memo=memo,
            cleared_on=row.transaction_date,
        )

    @staticmethod
    def _extract(pattern: str, text: str) -> str:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    # ---- document-level results -------------------------------------------

    def save_control_totals(self, control_totals: Dict) -> None:
        """Opening and closing balances, used to validate the extraction."""
        try:
            self.document.control_totals = convert_decimals_to_float(control_totals)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize control totals: {e}")
            self.document.control_totals = {}
        self.document.save(update_fields=["control_totals", "updated_at"])

    def save_metadata(self, metadata: Dict) -> None:
        """Per-page parsed markdown and artifact locations."""
        try:
            self.document.markdown_metadata = convert_decimals_to_float(metadata)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize markdown metadata: {e}")
            self.document.markdown_metadata = {}
        self.document.save(update_fields=["markdown_metadata", "updated_at"])
