"""
Shared extractor constants.
"""

from enum import Enum


class DocumentType(str, Enum):
    """Supported document types for processing."""
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD = "credit_card"
    CHECK_REGISTER = "check_register"
    SALES = "sales"
    PAYROLL = "payroll"
    MISC = "misc"

    @classmethod
    def transactional_types(cls) -> list[str]:
        """Document types that extract line items (transactions)."""
        return [
            cls.BANK_STATEMENT.value,
            cls.CREDIT_CARD.value,
            cls.CHECK_REGISTER.value,
        ]

    @classmethod
    def attribute_types(cls) -> list[str]:
        """Document types that extract key-value attributes."""
        return [cls.SALES.value, cls.PAYROLL.value, cls.MISC.value]
