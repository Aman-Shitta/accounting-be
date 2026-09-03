"""
Pydantic models for the Datalabs multi-stage extraction pipeline.

Three separate schemas — one per LLM call — so each call has a focused,
minimal output contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Call 1 — Transaction Extraction
# ---------------------------------------------------------------------------

class DatalabsTransaction(BaseModel):
    """A single transaction row extracted from an HTML table."""

    date: str = Field(
        ...,
        description="Transaction date in MM/DD/YYYY format.",
    )
    description: str = Field(
        ...,
        description="Full description/narration text from the table row.",
    )
    amount: float = Field(
        ...,
        gt=0,
        description="Positive transaction amount (no currency symbols or commas).",
    )
    type: str = Field(
        ...,
        description="'debit' (money out) or 'credit' (money in).",
    )
    page_number: int = Field(
        ...,
        description="1-indexed page number where this row appears.",
    )
    check_number: str = Field(
        "",
        description=(
            "The check number if this is a check transaction "
            "(from a check column or 'Check #XXXX' in description), "
            "otherwise empty string."
        ),
    )
    is_check: bool = Field(
        False,
        description=(
            "True if this row is from a Checks Paid/Cleared table, "
            "or has a check number, or is clearly a check transaction."
        ),
    )


class TransactionExtractionResult(BaseModel):
    """Output schema for LLM Call 1."""

    transactions: list[DatalabsTransaction] = Field(
        default_factory=list,
        description="All transaction rows from the document, in document order.",
    )


# ---------------------------------------------------------------------------
# Call 2 — Summary / Control-Totals Extraction
# ---------------------------------------------------------------------------

class DatalabsSummary(BaseModel):
    """Account summary totals from the bank statement."""

    beginning_balance: float = Field(
        0.0, description="Starting balance at the beginning of the statement period."
    )
    ending_balance: float = Field(
        0.0, description="Ending balance at the end of the statement period."
    )
    total_deposits: float = Field(
        0.0, description="Total amount of all deposits/credits."
    )
    total_withdrawals: float = Field(
        0.0, description="Total amount of all withdrawals/debits."
    )
    total_credits_count: int = Field(
        0, description="Number of credit/deposit transactions."
    )
    total_withdrawl_count: int = Field(
        0, description="Number of withdrawal/debit transactions."
    )


# ---------------------------------------------------------------------------
# Call 3 — Check Image OCR
# ---------------------------------------------------------------------------

class CheckImageData(BaseModel):
    """Data extracted from a single check image."""

    check_number: str = Field(
        ...,
        description="The check number printed on the check.",
    )
    amount: float | None = Field(
        None,
        description="Dollar amount on the check, if readable.",
    )
    payee: str = Field(
        "",
        description="Pay-to-the-order-of name from the check.",
    )
    memo: str = Field(
        "",
        description="Memo line text from the check.",
    )
    date: str = Field(
        "",
        description="Date written on the check in MM/DD/YYYY format, if readable.",
    )


class CheckImageExtractionResult(BaseModel):
    """Output schema for LLM Call 3."""

    checks: list[CheckImageData] = Field(
        default_factory=list,
        description="All checks found across the provided check image pages.",
    )
