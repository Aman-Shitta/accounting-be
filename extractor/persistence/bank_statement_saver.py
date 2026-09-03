"""
Bank Statement Saver

Single source of truth for persisting bank statement and credit card
extraction results to the database.

Consolidates the ``_save_extracted_data``, ``_save_transaction``,
``_create_check_item_from_transaction``, ``_save_control_totals``,
and ``_save_doc_metadata`` methods that were previously duplicated
across ``pipeline_landing_v1.py``, ``pipeline_claude.py``, and ``pipeline.py``.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from django.db import transaction

from account.models import (
    MonthlyAccountingDocument,
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
)
from extractor.base import BaseDocumentProcessor
from extractor.utils import convert_decimals_to_float

logger = logging.getLogger(__name__)


class BankStatementSaver:
    """
    Centralized persistence for bank statement / credit card extraction results.

    Usage::

        saver = BankStatementSaver(document)
        stats = saver.save_transactions(transactions)
        saver.save_control_totals(control_totals)
        saver.save_metadata(metadata)
    """

    def __init__(self, document: MonthlyAccountingDocument):
        self.document = document


    def save_transactions(self, transactions: List[Dict]) -> Dict[str, int]:
        """
        Persist a list of transaction dicts to the database.

        Automatically creates ``MonthlyDocumentBankCheckItem`` records
        for any transaction flagged as a check.

        Args:
            transactions: List of transaction dicts.  Expected keys:
                ``date``, ``description``, ``amount``, ``type`` (debit/credit),
                ``page_number``, ``check_number``, and optional rectification
                flags (``is_rectified``, ``was_missing``, ``was_compared``).

        Returns:
            Stats dict: ``{"line_items": int, "check_items": int, "pages_processed": int}``
        """
        stats = {
            "line_items": 0,
            "check_items": 0,
            "pages_processed": set(),
        }

        if not transactions:
            logger.warning("No transactions found in extracted data")
            return {"line_items": 0, "check_items": 0, "pages_processed": 0}

        logger.info(f"Saving {len(transactions)} transactions to DB...")

        with transaction.atomic():
            for idx, txn in enumerate(transactions):
                assert "date" in txn and "description" in txn and "amount" in txn and "type" in txn, (
                    f"Transaction dict is missing required keys: {txn}"
                )
                line_item = self._save_transaction(idx + 1, txn)
                stats["line_items"] += 1
                stats["pages_processed"].add(txn.get("page_number", 1))

                if line_item.is_check_transaction:
                    stats["check_items"] += 1

        stats["pages_processed"] = len(stats["pages_processed"])
        logger.info(f"Saved extracted data: {stats}")
        return stats

    def save_control_totals(self, control_totals: Dict) -> None:
        """Save control totals to the document model."""
        try:
            self.document.control_item = convert_decimals_to_float(control_totals)
            self.document.save()
            logger.info("Control totals saved to document")
        except Exception as e:
            logger.error(f"Failed to save control totals: {e}")
            self.document.control_item = {}
            self.document.save()

    def save_metadata(self, metadata: Dict) -> None:
        """Save document-level metadata (markdown, extracted data, etc.)."""
        try:
            self.document.markdown_metadata = convert_decimals_to_float(metadata)
            self.document.save()
            logger.info("Document metadata saved")
        except Exception as e:
            logger.error(f"Failed to save markdown metadata: {e}")
            self.document.markdown_metadata = {}
            self.document.save()


    def _save_transaction(
        self, line_number: int, txn_data: Dict
    ) -> MonthlyDocumentBankLineItem:
        """Save a single transaction to the database."""
        date = BaseDocumentProcessor.format_date(txn_data.get("date", ""))
        description = txn_data.get("description", "")
        amount = BaseDocumentProcessor.parse_amount(txn_data.get("amount"))
        transaction_type = txn_data.get("type", "").lower()

        debit_amount = None
        credit_amount = None

        if transaction_type == "debit" and amount:
            debit_amount = str(amount)
        elif transaction_type == "credit" and amount:
            credit_amount = str(amount)

        check_number = txn_data.get("check_number", "")
        is_check_transaction = bool(check_number and str(check_number).strip())

        if check_number:
            check_number = str(check_number).lstrip("0").strip("*")
            check_number = re.sub(r"[^\d\.]", "", check_number)
            if not check_number:
                is_check_transaction = False
                check_number = None

        page_number = txn_data.get("page_number", 1)

        # Rectification metadata
        is_rectified = txn_data.get("is_rectified", False)
        was_missing = txn_data.get("was_missing", False)
        was_compared = txn_data.get("was_compared", False)

        line_item = MonthlyDocumentBankLineItem.objects.create(
            document=self.document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=(
                transaction_type if transaction_type in ("debit", "credit") else None
            ),
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            is_check_transaction=is_check_transaction,
            check_number=check_number if is_check_transaction else None,
            is_rectified=is_rectified,
            was_missing=was_missing,
            was_compared=was_compared,
            gl_account=None,
            offset_gl_account=None,
        )

        if is_check_transaction:
            self._create_check_item(line_item, txn_data)

        return line_item

    def _create_check_item(
        self, line_item: MonthlyDocumentBankLineItem, txn_data: Dict
    ) -> MonthlyDocumentBankCheckItem:
        """Create a check item record linked to a transaction line item."""
        check_written_date = txn_data.get("check_written_date", "")
        if check_written_date:
            check_written_date = BaseDocumentProcessor.format_date(check_written_date)

        # Use enriched payee/memo if available, 
        # otherwise fall back to regex parsing from description.
        payee = txn_data.get("check_payee", "")
        memo = txn_data.get("check_memo", "")

        if not payee:
            description = txn_data.get("description", "")
            payee_match = re.search(
                r"(?:to|payee[:\s]+)([^-|]+)", description, re.IGNORECASE
            )
            if payee_match:
                payee = payee_match.group(1).strip()

        if not memo:
            description = txn_data.get("description", "")
            memo_match = re.search(
                r"(?:memo[:\s]+)(.+?)(?:\||$)", description, re.IGNORECASE
            )
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
            related_line_item=line_item,
        )

        logger.debug(f"Created check item for check #{line_item.check_number}")
        return check_item
