from typing import List, Optional
from pydantic import BaseModel, Field

from extractor.statement_models import StatementSummaryTotals


class PageTransaction(BaseModel):
    local_id: int = Field(
        ..., description="Sequential number starting at 1 for this page.")
    date: str = Field(
        ..., description="Transaction date in mm/dd/yyyy format.")
    check_number: str = Field(
        "", description="Check number if applicable, otherwise an empty string.")
    description: str = Field(
        ..., description="Full description/narration of the transaction.")
    amount: float = Field(
        ..., gt=0, description="Transaction amount as a positive number.")
    y_coord: float = Field(
        ..., description="Approximate vertical position on the page (0-1000 scale, top=0).")
    type: str = Field(
        ..., description="Either 'debit' (withdrawal) or 'credit' (deposit).")


class CheckImageData(BaseModel):
    check_number: str = Field(
        ..., description="The check number printed on the check image.")
    amount: Optional[float] = Field(
        None, description="Amount on the check image, if readable.")
    payee: str = Field(
        "", description="Pay-to-the-order-of name from the check image.")
    memo: str = Field(
        "", description="Memo line from the check image.")
    date: str = Field(
        "", description="Date written on the check in mm/dd/yyyy format, if readable.")


class PageExtraction(BaseModel):
    transactions: List[PageTransaction] = Field(
        default_factory=list,
        description="All deposit and withdrawal transactions listed on this page.")
    check_table: List[PageTransaction] = Field(
        default_factory=list,
        description=(
            "Transactions from a separate checks table on this page, "
            "ONLY if they are NOT already included in the transactions list above. "
            "Leave empty if checks are already part of the main transactions."
        ),
    )
    check_images: List[CheckImageData] = Field(
        default_factory=list,
        description="Data extracted from check images/stubs on this page (payee, memo, etc.).")
    summary: Optional[StatementSummaryTotals] = Field(
        None,
        description=(
            "Statement summary totals if they appear on this page. "
            "Only fill this on the page where the summary is printed; leave null on other pages."
        ),
    )