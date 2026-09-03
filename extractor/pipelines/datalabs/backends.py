"""
LLM backends for the Datalabs multi-stage pipeline.

Three focused extractors — one per LLM call — each with its own prompt
and a shared Pydantic output schema (see :mod:`schemas`):

* **TransactionExtractor** — reads HTML tables, returns transactions
  with ``is_check`` flag.
* **SummaryExtractor** — reads text/markdown, returns control totals.
* **CheckImageExtractor** — reads Marker HTML of check-image pages and
  returns payee / memo / date per check number.

Each extractor has a Claude variant (tool-use structured output) and a
Gemini variant (``response_schema`` structured output).  Swap by changing
the import in ``pipeline.py``.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from account.models import MonthlyAccountingDocument
from extractor.claude_service import ClaudeMixin
from extractor.gemini_service import GeminiMixin
from extractor.pipelines.datalabs.schemas import (
    CheckList,
    StatementSummary,
    TransactionList,
)

logger = logging.getLogger(__name__)


# ======================================================================
# Prompts
# ======================================================================

TRANSACTION_SYSTEM_PROMPT = """\
You are an expert bank-statement table parser.

You will receive a JSON map of page numbers to HTML tables extracted from a
PDF bank statement. Each table entry includes a ``section_header`` field
containing the nearest preceding heading on the page (e.g. "Deposits",
"Withdrawals", "Checks Paid", "Other Debits", "Credits"). Your ONLY job
is to read every transaction row and return them through the structured
output tool / schema.

RULES:
- Read EVERY transaction row across ALL pages.
- Normalize dates to MM/DD/YYYY.
- ``amount`` must always be a positive number; use ``type`` for direction.
- Determine direction (debit vs credit) in this priority order:
    1. If the table has an explicit debit/credit column, use that.
    2. Else, if ``section_header`` is non-empty, use it: headers like
       "Deposits", "Credits", "Additions", "Electronic Credits" ⇒ credit;
       "Withdrawals", "Debits", "Checks Paid", "Other Debits",
       "Electronic Debits", "Fees" ⇒ debit.
    3. Else, fall back to the sign convention in the amount column — a
       leading minus sign ⇒ debit; otherwise credit.
  ``section_header`` may be empty when no heading appears near the table;
  that's expected — move to the sign fallback in that case.
- ``is_check`` = true when:
  (a) the row is inside a "Checks Paid", "Checks Cleared", or similar
      dedicated checks table/section, OR
  (b) the row has an explicit check number column filled in, OR
  (c) the description clearly references a check (e.g. "Check #1234").
- For compact multi-column check grids where one row contains 2-5 checks
  side by side, split each check into its own transaction entry.
- When ``is_check`` is true, populate ``check_number`` with the check
  serial number from the table.
- Skip balance, summary, totals, and fee header rows.
- Do NOT extract summary / control-total information.
"""

SUMMARY_SYSTEM_PROMPT = """\
You are an expert at extracting bank statement summary data.

You will receive the text content (markdown) of a bank statement. Find
the ACCOUNT SUMMARY / STATEMENT SUMMARY section and return the control
totals through the structured output tool / schema.

RULES:
- Look for sections titled "Account Summary", "Statement Summary",
  "Account Overview", "Balance Summary", or similar.
- All amounts must be positive numbers.
- Counts should be integers.
- If a field is not found in the document, set it to 0.
- Do NOT extract individual transactions.
"""

CHECK_IMAGE_SYSTEM_PROMPT = """\
You are an expert at reading bank check images that have been OCR'd into HTML.

You will receive HTML for pages that contain printed check images. Each
page may contain multiple checks (commonly 3+ per page). Marker has
already OCR'd the visible text from each check into the HTML.

For EACH check on the pages, return its data through the structured
output tool / schema.

RULES:
- Extract data from every check present in the HTML.
- ``check_number`` — the pre-printed serial number, usually top-right.
- ``amount`` — the numeric amount (positive, no $ sign). Null if unreadable.
- ``payee`` — the "Pay to the order of" name.
- ``memo`` — the memo / "For" line.
- ``date`` — the date on the check in MM/DD/YYYY format.
- If a field is unreadable or missing, use an empty string (or null for amount).
- Ignore non-check content (logos, deposit slips, bank headers).
"""


# ======================================================================
# Abstract base
# ======================================================================

class ExtractorBackend(ABC):
    """Common interface for all Datalabs LLM backends."""

    def __init__(self, document: MonthlyAccountingDocument):
        self.document = document

    @abstractmethod
    def extract(self, data: Any) -> Any:
        ...


# ======================================================================
# Claude helpers
# ======================================================================

def _claude_tool(name: str, description: str, model_cls) -> Dict[str, Any]:
    """Build a Claude tool definition from a Pydantic model class."""
    from extractor.claude_service import ClaudeService

    return ClaudeService.build_tool_schema(
        name=name,
        description=description,
        input_schema=model_cls,
    )


# ======================================================================
# 1. Transaction Extractors
# ======================================================================

class ClaudeTransactionExtractor(ExtractorBackend, ClaudeMixin):
    """LLM Call 1 — extract transactions via Claude tool-use."""

    TOOL = _claude_tool(
        name="emit_transactions",
        description="Return the full list of extracted bank statement transactions.",
        model_cls=TransactionList,
    )

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_claude()

    def extract(
        self, tables_by_page: Dict[int, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        payload = json.dumps(tables_by_page, ensure_ascii=False)
        result = self.claude_stream_tool(
            messages=[
                {
                    "role": "user",
                    "content": [
                        self.claude.create_text_part(
                            "HTML tables from bank statement (JSON, keyed by page):\n\n"
                            + payload
                        ),
                    ],
                }
            ],
            tool=self.TOOL,
            system=TRANSACTION_SYSTEM_PROMPT,
            max_tokens=64_000,
        )
        return result.get("transactions", []) or []


class GeminiTransactionExtractor(ExtractorBackend, GeminiMixin):
    """LLM Call 1 — extract transactions via Gemini structured output."""

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_gemini()

    def extract(
        self, tables_by_page: Dict[int, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        payload = json.dumps(tables_by_page, ensure_ascii=False)
        parsed = self.gemini_generate_json(
            contents=[
                self.gemini.create_part_from_text(
                    "HTML tables from bank statement (JSON, keyed by page):\n\n"
                    + payload
                )
            ],
            schema=TransactionList,
            system_instruction=[TRANSACTION_SYSTEM_PROMPT],
            max_output_tokens=64_000,
        )
        return parsed.get("transactions", []) or []


# ======================================================================
# 2. Summary Extractors
# ======================================================================

class ClaudeSummaryExtractor(ExtractorBackend, ClaudeMixin):
    """LLM Call 2 — extract control totals via Claude tool-use."""

    TOOL = _claude_tool(
        name="emit_summary",
        description="Return the bank statement summary / control totals.",
        model_cls=StatementSummary,
    )

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_claude()

    def extract(self, text_content: str) -> Dict[str, Any]:
        if not text_content or not text_content.strip():
            logger.warning("No text content for summary extraction — returning zeros.")
            return _empty_summary()

        result = self.claude_stream_tool(
            messages=[
                {
                    "role": "user",
                    "content": [
                        self.claude.create_text_part(
                            "Bank statement text content:\n\n" + text_content
                        ),
                    ],
                }
            ],
            tool=self.TOOL,
            system=SUMMARY_SYSTEM_PROMPT,
            max_tokens=4_000,
        )
        return _coerce_summary(result)


class GeminiSummaryExtractor(ExtractorBackend, GeminiMixin):
    """LLM Call 2 — extract control totals via Gemini structured output."""

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_gemini()

    def extract(self, text_content: str) -> Dict[str, Any]:
        if not text_content or not text_content.strip():
            logger.warning("No text content for summary extraction — returning zeros.")
            return _empty_summary()

        parsed = self.gemini_generate_json(
            contents=[
                self.gemini.create_part_from_text(
                    "Bank statement text content:\n\n" + text_content
                )
            ],
            schema=StatementSummary,
            system_instruction=[SUMMARY_SYSTEM_PROMPT],
            max_output_tokens=4_000,
        )
        return _coerce_summary(parsed)


# ======================================================================
# 3. Check Image Extractors (Marker HTML input)
# ======================================================================

class ClaudeCheckImageExtractor(ExtractorBackend, ClaudeMixin):
    """LLM Call 3 — extract check data from Marker HTML via Claude tool-use."""

    TOOL = _claude_tool(
        name="emit_checks",
        description="Return extracted data for every check image on the pages.",
        model_cls=CheckList,
    )

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_claude()

    def extract(self, check_page_html: Dict[int, str]) -> List[Dict[str, Any]]:
        if not check_page_html:
            return []

        payload = json.dumps(check_page_html, ensure_ascii=False)
        result = self.claude_stream_tool(
            messages=[
                {
                    "role": "user",
                    "content": [
                        self.claude.create_text_part(
                            "HTML content from check-image pages "
                            "(JSON, keyed by 1-indexed page number):\n\n"
                            + payload
                        ),
                    ],
                }
            ],
            tool=self.TOOL,
            system=CHECK_IMAGE_SYSTEM_PROMPT,
            max_tokens=32_000,
        )
        return result.get("checks", []) or []


class GeminiCheckImageExtractor(ExtractorBackend, GeminiMixin):
    """LLM Call 3 — extract check data from Marker HTML via Gemini."""

    def __init__(self, document: MonthlyAccountingDocument):
        super().__init__(document)
        self.init_gemini()

    def extract(self, check_page_html: Dict[int, str]) -> List[Dict[str, Any]]:
        if not check_page_html:
            return []

        payload = json.dumps(check_page_html, ensure_ascii=False)
        parsed = self.gemini_generate_json(
            contents=[
                self.gemini.create_part_from_text(
                    "HTML content from check-image pages "
                    "(JSON, keyed by 1-indexed page number):\n\n"
                    + payload
                )
            ],
            schema=CheckList,
            system_instruction=[CHECK_IMAGE_SYSTEM_PROMPT],
            max_output_tokens=32_000,
        )
        return parsed.get("checks", []) or []


# ======================================================================
# Helpers
# ======================================================================

def _empty_summary() -> Dict[str, Any]:
    return {
        "beginning_balance": 0.0,
        "ending_balance": 0.0,
        "total_deposits": 0.0,
        "total_withdrawals": 0.0,
        "total_credits_count": 0,
        "total_withdrawl_count": 0,
    }


def _coerce_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all expected summary keys exist with sensible defaults."""
    defaults = _empty_summary()
    return {k: raw.get(k, v) for k, v in defaults.items()}
