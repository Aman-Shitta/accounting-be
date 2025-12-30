from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class PageClassification(BaseModel):
    page_types: List[str] = Field(
        ..., 
        description="List of page types detected. Options: 'transaction_table', 'check_images', 'deposit_slips_images', 'summary_table', 'other'. "
                    "transaction_table: Contains transaction listings with dates, descriptions, amounts. "
                    "check_images: Contains images or details of cleared checks. "
                    "deposit_slips_images: Contains images or details of deposit slips. "
                    "summary_table: Contains account summaries, beginning/ending balances. "
                    "other: Any other content."
    )

class Transaction(BaseModel):
    date: str = Field(..., description="The date when the transaction occurred.")
    description: str = Field(..., description="Description of the transaction.")
    debit_amount: Optional[str] = Field(None, description="The amount debited (money out).")
    credit_amount: Optional[str] = Field(None, description="The amount credited (money in).")
    is_check_transaction: bool = Field(False, description="True if this transaction appears to be a check.")
    check_number: Optional[str] = Field(None, description="Check number if identified in the description.")
    amount_confidence: Optional[float] = Field(None, description="Confidence score (0.0-1.0) for the extracted amount.")

class TransactionList(BaseModel):
    line_items: List[Transaction] = Field(..., description="List of all financial transactions extracted from the page.")
    type: str = Field(..., description="Type of transaction list, e.g., 'deposit', 'withdrawls', 'transaction_actvity', 'check'.")

class Check(BaseModel):
    amount: str = Field(..., description="Check amount.")
    payee: str = Field(..., description="Payee name.")
    memo: Optional[str] = Field(None, description="Memo line.")
    clearing_date: Optional[str] = Field(None, description="Date check cleared.")
    passing_date: Optional[str] = Field(None, description="Date check passed.")
    check_number: Optional[str] = Field(None, description="Check number.")

class CheckList(BaseModel):
    checks: List[Check] = Field(..., description="List of checks found in images on the page.")

class StatementSummary(BaseModel):
    beginning_balance: Optional[float] = Field(None, description="The opening balance at the start of the statement.")
    ending_balance: Optional[float] = Field(None, description="The final balance at the end of the statement.")
    total_deposits: Optional[float] = Field(None, description="The total amount of all deposit transactions.")
    total_withdrawals: Optional[float] = Field(None, description="The total amount of all withdrawal transactions.")
    beginning_balance_confidence: Optional[float] = Field(None, description="Confidence score for beginning balance.")
    ending_balance_confidence: Optional[float] = Field(None, description="Confidence score for ending balance.")
    total_deposits_confidence: Optional[float] = Field(None, description="Confidence score for total deposits.")
    total_withdrawals_confidence: Optional[float] = Field(None, description="Confidence score for total withdrawals.")