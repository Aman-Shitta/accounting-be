from pydantic import BaseModel, Field
from typing import List

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

class AmountGrounding(BaseModel):
    left: Annotated[Decimal, Field(..., description="left location coordinate of the amount on the page.")]
    top: Annotated[Decimal, Field(..., description="Top location coordinate of the amount on the page.")]
    right: Annotated[Decimal, Field(..., description="Right location coordinate of the amount amount on the page.")]
    bottom:  Annotated[Decimal, Field(..., description="Bottom location coordinate of the amount amount on the page.")]

class StatementTransaction(BaseModel):
    global_id: int = Field(..., description="Numerical unique identifier indicating the order as listed on the statement.")
    date: str = Field(..., description="Transaction or check Date in mm/dd/yyyy format.")
    check_number: str = Field(..., description="Check number if applicable, otherwise an empty string.")
    check_written_date: str = Field(..., description="Date when the check was written in mm/dd/yyyy format, if applicable, otherwise an empty string.")
    description: str = Field(..., description="Description of the transaction or check, with payee and memo information appended for checks if applicable. You must resolve this information for all checks.")
    amount: float = Field(..., gt=0, description="Amount of the transaction or check in positive value.")
    y_coord: float = Field(..., description="top left location coordinate of the amount.")
    # grounding: AmountGrounding = Field(..., description="Bounding box coordinates of the amount on the page.")
    local_id: int = Field(..., description="Numerical unique identifier indicating the order as listed on the page. Reset the counter to 1 at the beginning of each page.")
    type: str = Field(..., description="Indicates whether the transaction is a debit or credit. Use 'debit' or 'credit'.")



class StatementSummaryTotals(BaseModel):
    beginning_balance: float = Field(..., description="The starting balance at the beginning of the statement period.")
    ending_balance: float = Field(..., description="The ending balance at the end of the statement period.")
    total_deposits: float = Field(..., description="The total amount of all deposits/credits during the statement period.")
    total_withdrawals: float = Field(..., description="The total amount of all withdrawals/debits during the statement period.")
    total_credits_count: int = Field(..., description="The total number of credit transactions.")
    total_withdrawl_count: int = Field(..., description="The total number of withdrawal transactions.")


class BankStatementExtraction(BaseModel):
    transactions: List[StatementTransaction] = Field(..., description="An array of all transactions and checks listed in the statement, in the order they appear.")
    summary: StatementSummaryTotals = Field(..., description="Summary totals and balances from the bank statement.")
