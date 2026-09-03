"""
Attribute Saver

Single source of truth for persisting key-value attribute extraction
results (sales, payroll, misc documents) to the database.

Consolidates the ``_save_extracted_data`` method that was duplicated
between ``kv_processor/pipeline.py`` and ``kv_processor/pipeline_landing.py``.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Set

from django.db import transaction

from account.models import MonthlyAccountingDocument

logger = logging.getLogger(__name__)


class AttributeSaver:
    """
    Centralized persistence for key-value attribute extraction results.

    Usage::

        saver = AttributeSaver(document)
        stats = saver.save_attributes(page_data)
    """

    def __init__(self, document: MonthlyAccountingDocument):
        self.document = document
        self._extracted_attributes: Set[str] = set()

    def save_attributes(self, page_data: List[Dict]) -> Dict[str, int]:
        """
        Save extracted key-value attributes to the database.

        Handles:
            - Matching extracted keys to configured attributes.
            - De-duplicating across pages (first occurrence wins).
            - Creating empty records for attributes not found.

        Args:
            page_data: List of page result dicts, each with:
                ``{"page_number": int, "key_items": [{"key": str, "value": str}]}``

        Returns:
            Stats dict: ``{"key_items": int, "skipped_extracted_attributes": int,
                           "duplicate_attributes_skipped": int}``
        """
        from account.models import (
            MonthlyDocumentAttributeItem,
            FactAICInputFileAttributeSnapshot,
        )

        stats = {
            "key_items": 0,
            "skipped_extracted_attributes": 0,
            "duplicate_attributes_skipped": 0,
        }

        # Build lookup of configured attributes
        configured_attributes = {
            obj.name.lower().replace(" ", "_"): obj
            for obj in FactAICInputFileAttributeSnapshot.objects.only(
                "id", "name", "type", "gl_account", "offset_gl_account"
            ).filter(input_file_snapshot=self.document.input_file_snapshot)
        }

        with transaction.atomic():
            for page_result in page_data:
                page_number = page_result.get("page_number", 1)
                extracted_items = page_result.get("key_items", [])

                for item in extracted_items:
                    # Handle both dict and Pydantic model formats
                    if isinstance(item, dict):
                        key = item.get("key", "").lower().replace(" ", "_")
                        value = item.get("value", "")
                    else:
                        key = getattr(item, "key", "").lower().replace(" ", "_")
                        value = getattr(item, "value", "")

                    # Skip duplicates from earlier pages
                    if key in self._extracted_attributes:
                        stats["duplicate_attributes_skipped"] += 1
                        continue

                    attr_instance = configured_attributes.get(key)
                    parsed_value = self._parse_amount(value)

                    if attr_instance and parsed_value:
                        MonthlyDocumentAttributeItem.objects.create(
                            document=self.document,
                            attribute=attr_instance,
                            page_number=page_number,
                            value=parsed_value,
                            transaction_type=attr_instance.type,
                            gl_account=attr_instance.gl_account,
                            offset_gl_account=attr_instance.offset_gl_account,
                        )
                        self._extracted_attributes.add(key)
                        stats["key_items"] += 1

            # Create empty entries for attributes not found in any page
            for attr_name, attr_obj in configured_attributes.items():
                if attr_name not in self._extracted_attributes:
                    logger.info(f"Saving empty attribute for missing: {attr_name}")
                    MonthlyDocumentAttributeItem.objects.create(
                        document=self.document,
                        attribute=attr_obj,
                        page_number=1,
                        value="",
                        transaction_type=attr_obj.type,
                        gl_account=attr_obj.gl_account,
                        offset_gl_account=attr_obj.offset_gl_account,
                    )
                    stats["skipped_extracted_attributes"] += 1

        logger.info(f"Saved extracted data: {stats}")
        return stats

    @staticmethod
    def _parse_amount(amount_str) -> Optional[str]:
        """
        Parse and clean amount string.

        Returns the cleaned value as a string, or ``None`` if empty/invalid.
        """
        if not amount_str or str(amount_str).strip() in ("", "null", "none", "-"):
            return None

        cleaned = re.sub(r"[^\d\.]", "", str(amount_str))

        try:
            clean_amount = (
                str(cleaned)
                .replace(",", "")
                .replace("$", "")
                .replace("(", "-")
                .replace(")", "")
                .strip()
            )

            if clean_amount.startswith("-"):
                # Validate it's a real number
                Decimal(clean_amount[1:])
                return clean_amount
            else:
                Decimal(clean_amount)
                return clean_amount

        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_str}': {e}")

        return str(amount_str) if amount_str else None
