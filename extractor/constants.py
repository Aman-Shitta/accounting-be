"""
Shared extractor constants.
"""

from enum import Enum
from typing import List


class DocumentType(str, Enum):
    """Supported document types for processing."""
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD = "credit_card"
    SALES = "sales"
    PAYROLL = "payroll"
    MISC = "misc"

    @classmethod
    def transactional_types(cls) -> List[str]:
        """Document types that extract line items (transactions)."""
        return [cls.BANK_STATEMENT.value, cls.CREDIT_CARD.value]

    @classmethod
    def attribute_types(cls) -> List[str]:
        """Document types that extract key-value attributes."""
        return [cls.SALES.value, cls.PAYROLL.value, cls.MISC.value]
