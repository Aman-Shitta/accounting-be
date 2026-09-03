import logging
import re
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Optional

from extractor.gemini_service import GeminiMixin

logger = logging.getLogger(__name__)


class AbstractDocumentProcessor(ABC):
    """
    Abstract base class defining the interface for all document processors.

    Concrete pipelines implement ``process_document`` to extract data from
    raw file bytes.
    """

    @abstractmethod
    def process_document(self, file_bytes: bytes, **kwargs) -> Dict[str, Any]:
        """
        Process a document and extract data.

        Returns a dict with at minimum:
            - ``"status"``: ``"success"`` | ``"error"``
            - ``"processing_stats"``: ``Dict[str, int]``
        """
        pass

    def set_debug_storage(self, debug_storage) -> None:
        """Attach a debug storage helper. Subclasses override to store the reference."""
        pass

    def validate_input(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            raise ValueError("Empty file provided")
        return True


class BaseDocumentProcessor(AbstractDocumentProcessor):
    """
    Base document processor with shared parsing utilities.

    No AI-provider coupling. Pipelines that need Gemini should inherit from
    ``GeminiDocumentProcessor`` instead.
    """

    def __init__(self, doc):
        self.document = doc
        self.debug_storage = None

    def set_debug_storage(self, debug_storage) -> None:
        self.debug_storage = debug_storage
        logger.info(f"Debug storage enabled for document {self.document.id}")

    @staticmethod
    def truncate_decimal_to_2_places(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    @staticmethod
    def parse_amount(amount_value) -> Optional[Decimal]:
        """
        Parse an amount value (int, float, str, or None) into a ``Decimal``
        truncated to two decimal places.

        Handles currency symbols, commas, parentheses for negatives, and
        common null sentinels (``"null"``, ``"none"``, ``"-"``).
        """
        if amount_value is None:
            return None

        if isinstance(amount_value, (int, float)):
            value = Decimal(str(amount_value))
            return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

        amount_str = str(amount_value).strip()
        if amount_str in ("", "null", "none", "-"):
            return None

        amount_str = re.sub(r"[^\d\.\-]", "", amount_str)

        try:
            value = Decimal(amount_str)
            return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_value}': {e}")
            return None

    @staticmethod
    def format_date(date_str: str) -> str:
        """
        Format a date string into standardised ``DD-Month-YYYY`` format.
        Returns the original string unchanged if parsing fails.
        """
        from dateutil import parser as dateutil_parser

        if not date_str or not str(date_str).strip():
            return date_str

        date_str = str(date_str).strip()

        month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December",
        }

        try:
            parsed_date = dateutil_parser.parse(date_str, dayfirst=False, fuzzy=True)
            day = parsed_date.day
            month_name = month_names[parsed_date.month]
            year = parsed_date.year
            return f"{day:02d}-{month_name}-{year}"
        except (ValueError, dateutil_parser.ParserError):
            match = re.match(r"(\d{1,2})[/-](\d{4})", date_str)
            if match:
                month, year = match.groups()
                month_num = int(month)
                if 1 <= month_num <= 12:
                    month_name = month_names[month_num]
                    return f"01-{month_name}-{year}"

            logger.warning(f"Could not parse date format: {date_str}")
            return date_str


class GeminiDocumentProcessor(GeminiMixin, BaseDocumentProcessor):
    """
    Base class for pipelines that need Gemini AI.

    Initializes the shared Gemini client and exposes ``ai_client`` for
    backward compatibility with existing pipeline code.
    """

    def __init__(self, doc):
        super().__init__(doc)
        self.init_gemini()
        self.ai_client = self.gemini_client

    def _generate_content_stream(self, **kwargs):
        """
        Generate content stream using the shared Gemini service.
        Kept for backward compatibility with existing pipeline code.
        """
        contents = kwargs.get("contents", [])
        config = kwargs.get("config", {})
        model = kwargs.get("model", None)

        final_config = self.get_gemini_config(
            max_output_tokens=config.get("max_output_tokens", 8000),
            top_p=config.get("top_p", 0.95),
            top_k=config.get("top_k", 25),
            temperature=config.get("temperature", 0.2),
        )
        final_config.update(config)

        return self.gemini_generate_stream(
            contents=contents,
            config=final_config,
            model=model,
        )
