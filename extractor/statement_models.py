from pydantic import BaseModel, Field
from typing import List

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field





class StatementTransaction(BaseModel):
    global_id: int = Field(
        ..., description="Strictly increasing numerical identifier (1, 2, 3...) representing the overall chronological order across the ENTIRE document. Do NOT reset this counter when encountering new tables, sections, or pages.")
    date: str = Field(
        ..., description="Transaction or check Date in mm/dd/yyyy format. Infer the year from the statement context if it is omitted.")
    check_number: str = Field(
        ..., description="The printed check number if the transaction is a check, otherwise an empty string.")
    description: str = Field(
        ..., description="Description of the transaction or check, with payee and memo information appended for checks if applicable. You must resolve this information for all checks from images if present.  This is very important")
    amount: float = Field(
        ..., gt=0, description="The absolute positive numerical value of the transaction or check amount.")

    local_id: int = Field(
        ..., description="Increasing numerical identifier (1, 2, 3...) representing the order within a SINGLE page. Reset to 1 ONLY at the beginning of a completely new page. Do NOT reset this counter when encountering new tables or sections on the same page.")
    type: str = Field(
        ..., description="Indicates whether the transaction is a 'debit' (money leaving account, e.g., checks, payments, fees) or 'credit' (money entering account, e.g., deposits).")
    page_number: int = Field(
        1, description="The integer page number (1, 2, 3...) where this specific transaction row is physically located.")
    check_payee: str = Field(
        "", description="Payee explicitly extracted from check image data, if available.")
    check_memo: str = Field(
        "", description="Memo explicitly extracted from check image data, if available.")
    check_written_date: str = Field(
        "", description="Date written on the check explicitly extracted from check image data, if available.")


class StatementSummaryTotals(BaseModel):
    beginning_balance: float = Field(
        ..., description="The starting balance at the beginning of the statement period.")
    ending_balance: float = Field(
        ..., description="The ending balance at the end of the statement period.")
    total_deposits: float = Field(
        ..., description="The total amount of all deposits/credits during the statement period.")
    total_withdrawals: float = Field(
        ..., description="The total amount of all withdrawals/debits during the statement period.")
    total_credits_count: int = Field(...,
                                     description="The total number of credit transactions.")
    total_withdrawl_count: int = Field(
        ..., description="The total number of withdrawal transactions.")


class BankStatementExtraction(BaseModel):
    transactions: List[StatementTransaction] = Field(
        ..., description="An array of all transactions(deposits, withdrawals, checks) listed in the statement, in the strict order they appear.")
    summary: StatementSummaryTotals = Field(
        ..., description="Summary totals and balances from the bank statement.")
