import io
import json
import logging
import os
import re
import sys
import tempfile
import unicodedata
from decimal import Decimal
from typing import Any

from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)


def split_pdf_to_pages(pdf_bytes: bytes):
    """Splits a PDF file into individual pages and returns a list of bytes for each page."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    page_bytes = []

    for page_num in range(num_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[page_num])

        with io.BytesIO() as output_stream:
            writer.write(output_stream)
            page_bytes.append(output_stream.getvalue())

    return page_bytes

def convert_decimals_to_float(obj):
    """
    Recursively convert all Decimal objects to floats for JSON serialization.

    This helper is used throughout the extraction pipeline to prepare data
    for JSON storage (debug artifacts, document metadata, etc.).
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    else:
        return obj

class JSONHelper:
    """
    Helper class for JSON parsing and cleaning of LLM outputs.

    This class provides robust JSON handling for potentially malformed
    responses from language models.
    """

    @staticmethod
    def clean(raw: str) -> str:
        """
        Clean raw LLM output for JSON parsing.

        Args:
            raw: Raw string from LLM

        Returns:
            Cleaned string ready for JSON parsing
        """
        try:
            # Remove markdown code blocks
            raw = re.sub(r'^```(?:json)?', '', raw)
            raw = raw.strip('` \n')

            # Normalize line endings
            raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')

            # Escape single quotes
            raw = raw.replace('\'', '\\\'')

            # Replace Python None with JSON null
            raw = raw.replace("None", "null")

            # Remove control characters except newline/tab
            raw = ''.join(
                c for c in raw
                if unicodedata.category(c)[0] != 'C' or c in '\n\t'
            )

            # Convert single quotes to double quotes (not escaped ones)
            raw = re.sub(r"(?<!\\)'", '"', raw)

            # Remove trailing commas
            raw = re.sub(r',(\s*[}\]])', r'\1', raw)

            # Find first brace and start there
            first_brace = raw.find('{')
            if first_brace > 0:
                raw = raw[first_brace:]

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"[{fname}:{exc_tb.tb_lineno}] Error cleaning JSON: {e}")

        return raw

    @staticmethod
    def extract_first_json(raw: str) -> str:
        """
        Extract the first complete JSON object from a string.

        Args:
            raw: String potentially containing JSON

        Returns:
            Extracted JSON string or original if not found
        """
        try:
            match = re.search(r'(\{[\s\S]*\})', raw)
            if match:
                return match.group(1)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"[{fname}:{exc_tb.tb_lineno}] Error extracting JSON: {e}")

        return raw

    @staticmethod
    def repair(raw: str) -> str:
        """
        Repair malformed JSON using json_repair library.

        Args:
            raw: Potentially malformed JSON string

        Returns:
            Repaired JSON string
        """
        from json_repair import repair_json
        try:
            return repair_json(raw)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"[{fname}:{exc_tb.tb_lineno}] JSON repair failed: {e}")
            return raw

    @staticmethod
    def parse_json(raw: str, default: dict | None = None) -> dict:
        """
        Parse JSON string with multiple fallback strategies.

        Args:
            raw: Raw string to parse
            default: Default value if all parsing fails

        Returns:
            Parsed JSON dict or default value
        """
        if default is None:
            default = {}

        # Try repair first (most robust)
        try:
            repaired = JSONHelper.repair(raw)
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # Try cleaning
        try:
            cleaned = JSONHelper.clean(raw)
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try extraction
        try:
            extracted = JSONHelper.extract_first_json(raw)
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

        logger.error(f"All JSON parsing strategies failed for: {raw[:500]}...")
        return default

    @staticmethod
    def validate_and_repair(
        raw: str,
        expected_keys: dict[str, Any] | None = None
    ) -> dict:
        """
        Parse JSON and ensure expected keys exist.

        Args:
            raw: Raw JSON string
            expected_keys: Dict of expected keys with default values

        Returns:
            Parsed and validated JSON dict
        """
        parsed = JSONHelper.parse_json(raw, default=expected_keys or {})

        if expected_keys:
            for key, default_value in expected_keys.items():
                if key not in parsed:
                    logger.warning(
                        f"Missing expected key '{key}', using default")
                    parsed[key] = default_value

        return parsed



"""
Shared helper functions
"""


def log_exception(logger_instance, message: str, exc: Exception = None):
    """Standard exception logging with file and line number info."""
    exc_type, exc_obj, exc_tb = sys.exc_info()
    if exc_tb:
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger_instance.error(
            f"[{fname}:{exc_tb.tb_lineno}] {message}: {exc or exc_obj}")
    else:
        logger_instance.error(f"{message}: {exc}")


def generate_temp_pdf(file_bytes: bytes) -> tempfile.NamedTemporaryFile:
    """Create a temporary PDF file from bytes."""
    temp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temp.write(file_bytes)
    temp.flush()
    return temp


def clean_temp_file(temp_file):
    """Clean up a temporary file safely."""
    try:
        temp_file.close()
        os.unlink(temp_file.name)
    except Exception:
        pass


def detect_check_transaction(description: str) -> dict:
    """
    Detect if a transaction description indicates a check/cheque
    and extract the check number if present.

    Returns:
        Dict with 'is_check_transaction' (bool) and 'check_number' (str).
    """
    desc_lower = description.lower()
    if "check" in desc_lower or "cheque" in desc_lower:
        match = re.search(r"check\s*#?\s*(\d+)", desc_lower)
        return {
            "is_check_transaction": True,
            "check_number": match.group(1) if match else "",
        }
    return {"is_check_transaction": False, "check_number": ""}
