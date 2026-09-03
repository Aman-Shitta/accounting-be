"""
Persists field extraction results for field-configured document types
(payroll, sales, misc).

Every configured field gets a row, whether or not the extractor found it — a
missing value is information, and the UI shows the gap rather than the field
silently disappearing.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction as db_transaction

from v1.configuration.models import ExtractionField
from v1.periods.models import PeriodDocument, PeriodFieldValue

logger = logging.getLogger(__name__)


class AttributeSaver:
    """
    Persistence for key-value extraction.

        saver = AttributeSaver(document)
        stats = saver.save_attributes(page_data)
    """

    def __init__(self, document: PeriodDocument):
        self.document = document
        self._seen: set[str] = set()

    def save_attributes(self, page_data: list[dict]) -> dict[str, int]:
        """
        Write one ``PeriodFieldValue`` per configured field.

        ``page_data`` is a list of ``{"page_number": int, "key_items":
        [{"key": str, "value": str}]}``. Earlier pages win when the same key
        appears twice.

        The account references are resolved and copied onto each row, so the
        value keeps its meaning if the field is later edited or removed.
        """
        stats = {"field_values": 0, "not_found": 0, "duplicates_skipped": 0}

        fields = {
            field.key: field
            for field in ExtractionField.objects.filter(
                document_source=self.document.document_source
            ).select_related("ledger_account", "offset_ledger_account")
        }

        if not fields:
            logger.warning(
                f"No extraction fields configured for document {self.document.id}; "
                f"nothing to save"
            )
            return stats

        with db_transaction.atomic():
            for page in page_data:
                page_number = page.get("page_number", 1)

                for item in page.get("key_items", []):
                    key = self._normalise_key(item)
                    value = self._item_value(item)

                    if key in self._seen:
                        stats["duplicates_skipped"] += 1
                        continue

                    field = fields.get(key)
                    parsed = self._parse_amount(value)
                    if not field or parsed is None:
                        continue

                    self._create_value(field, page_number, parsed)
                    self._seen.add(key)
                    stats["field_values"] += 1

            for key, field in fields.items():
                if key not in self._seen:
                    logger.info(f"Field '{key}' not found in document; recording empty")
                    self._create_value(field, page_number=1, value="")
                    stats["not_found"] += 1

        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _create_value(self, field: ExtractionField, page_number: int, value: str):
        return PeriodFieldValue.objects.create(
            document=self.document,
            extraction_field=field,
            field_key=field.key,
            field_label=field.label,
            page_number=page_number,
            value=value,
            direction=field.direction,
            ledger_account=field.ledger_account,
            offset_ledger_account=field.offset_ledger_account,
        )

    @staticmethod
    def _normalise_key(item) -> str:
        raw = item.get("key", "") if isinstance(item, dict) else getattr(item, "key", "")
        return str(raw).lower().replace(" ", "_")

    @staticmethod
    def _item_value(item):
        return item.get("value", "") if isinstance(item, dict) else getattr(item, "value", "")

    @staticmethod
    def _parse_amount(raw) -> str | None:
        """
        Reduce an extracted amount to a plain numeric string.

        Returns ``None`` when there is nothing usable, and the original text
        when it is not a number at all — some configured fields are dates or
        reference codes, not amounts.
        """
        if raw is None or str(raw).strip().lower() in ("", "null", "none", "-"):
            return None

        text = str(raw).strip()
        negative = text.startswith("(") and text.endswith(")")
        cleaned = re.sub(r"[^\d.]", "", text)

        if not cleaned:
            return text

        try:
            Decimal(cleaned)
        except (InvalidOperation, ValueError):
            logger.warning(f"Could not parse '{raw}' as an amount; storing as text")
            return text

        return f"-{cleaned}" if negative else cleaned
