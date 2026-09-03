"""
Pydantic schemas for Datalabs pipeline structured output.

Shared by both Claude (tool-use) and Gemini (response_schema) backends so
the two providers return the exact same shape.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    date: str = Field(description="Transaction date in MM/DD/YYYY format.")
    description: str = Field(description="Full text from the row.")
    amount: float = Field(description="Positive amount; direction encoded in 'type'.")
    type: Literal["debit", "credit"]
    page_number: int
    check_number: str = ""
    is_check: bool = False


class TransactionList(BaseModel):
    transactions: List[Transaction]


class StatementSummary(BaseModel):
    beginning_balance: float = 0.0
    ending_balance: float = 0.0
    total_deposits: float = 0.0
    total_withdrawals: float = 0.0
    total_credits_count: int = 0
    total_withdrawl_count: int = 0


class CheckItem(BaseModel):
    check_number: str
    amount: Optional[float] = None
    payee: str = ""
    memo: str = ""
    date: str = Field(default="", description="Date on the check in MM/DD/YYYY format.")


class CheckList(BaseModel):
    checks: List[CheckItem]
