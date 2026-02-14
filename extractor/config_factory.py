"""
Document Configuration Factory

Centralizes all document-type-specific configuration building logic.
This replaces the inline dict construction scattered across views.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


@dataclass
class DocumentConfig:
    """
    Immutable configuration for document processing.

    This dataclass replaces the dict-based config_params that was 
    being passed between views and tasks.
    """
    doc_type: str
    extract_key_items: bool = False
    key_items: List[str] = field(default_factory=list)
    key_items_formatted: List[str] = field(default_factory=list)
    extract_line_items: bool = False
    line_items: List[str] = field(default_factory=list)
    excluded_fields: List[str] = field(default_factory=list)
    base_prompt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for Celery task serialization."""
        return {
            "doc_type": self.doc_type,
            "extract_key_items": self.extract_key_items,
            "key_items": self.key_items,
            "key_items_formatted": self.key_items_formatted,
            "extract_line_items": self.extract_line_items,
            "line_items": self.line_items,
            "excluded_fields": self.excluded_fields,
            "base_prompt": self.base_prompt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentConfig":
        """Create from dict (e.g., from Celery task params)."""
        return cls(
            doc_type=data.get("doc_type"),
            extract_key_items=data.get("extract_key_items", False),
            key_items=data.get("key_items", []),
            key_items_formatted=data.get("key_items_formatted", []),
            extract_line_items=data.get("extract_line_items", False),
            line_items=data.get("line_items", []),
            excluded_fields=data.get("excluded_fields", []),
            base_prompt=data.get("base_prompt"),
        )

    def validate(self) -> None:
        """Validate configuration. Raises ValueError if invalid."""
        valid_types = [e.value for e in DocumentType]
        if self.doc_type not in valid_types:
            raise ValueError(
                f"Invalid doc_type: {self.doc_type}. Must be one of {valid_types}")

        if self.doc_type in DocumentType.transactional_types():
            if not self.extract_line_items:
                raise ValueError(
                    f"extract_line_items must be True for {self.doc_type}")

        if self.doc_type in DocumentType.attribute_types():
            if not self.extract_key_items:
                raise ValueError(
                    f"extract_key_items must be True for {self.doc_type}")

    def to_configuration(self):
        """
        Convert to legacy Configuration class for backward compatibility.

        The Configuration class in prompter.py contains prompt-building logic,
        so we need to convert to it for processing.

        Returns:
            Configuration instance from extractor.prompter
        """
        from extractor.prompter import Configuration
        return Configuration(**self.to_dict())


class DocumentConfigFactory:
    """
    Factory for creating document processing configurations.

    Centralizes the config-building logic that was previously scattered
    in MonthlyAccountingDocumentUploadView.

    Usage:
        config = DocumentConfigFactory.create_config(document)
        # or
        config = DocumentConfigFactory.for_bank_statement()
    """

    # Default line items for bank/credit card statements
    DEFAULT_TRANSACTION_LINE_ITEMS = [
        "date: The date of the transaction.",
        "description: A description of the transaction.",
        "debit amount: The debit amount of the transaction.",
        "credit amount: The credit amount of the transaction.",
    ]

    @classmethod
    def create_config(cls, document) -> DocumentConfig:
        """
        Create configuration based on document type and related data.

        Args:
            document: MonthlyAccountingDocument instance

        Returns:
            DocumentConfig instance ready for processing
        """
        doc_type = document.doc_type

        if doc_type in DocumentType.transactional_types():
            return cls.for_transactional(doc_type)
        elif doc_type in DocumentType.attribute_types():
            return cls.for_attribute_extraction(doc_type, document)
        else:
            raise ValueError(f"Unsupported document type: {doc_type}")

    @classmethod
    def for_transactional(cls, doc_type: str = DocumentType.BANK_STATEMENT.value) -> DocumentConfig:
        """
        Create config for bank statements and credit card documents.

        These document types extract line items (transactions) with 
        date, description, debit, and credit fields.
        """
        return DocumentConfig(
            doc_type=doc_type,
            extract_line_items=True,
            line_items=cls.DEFAULT_TRANSACTION_LINE_ITEMS.copy(),
            excluded_fields=[],
        )

    @classmethod
    def for_bank_statement(cls) -> DocumentConfig:
        """Convenience method for bank statement config."""
        return cls.for_transactional(DocumentType.BANK_STATEMENT.value)

    @classmethod
    def for_credit_card(cls) -> DocumentConfig:
        """Convenience method for credit card config."""
        return cls.for_transactional(DocumentType.CREDIT_CARD.value)

    @classmethod
    def for_attribute_extraction(cls, doc_type: str, document) -> DocumentConfig:
        """
        Create config for sales, payroll, and misc documents.

        These document types extract key-value attributes from the
        input_file_snapshot's attribute_snapshots.

        Args:
            doc_type: One of 'sales', 'payroll', 'misc'
            document: MonthlyAccountingDocument with input_file_snapshot
        """
        key_items = []
        key_items_formatted = []

        if document.input_file_snapshot:
            attributes = document.input_file_snapshot.attribute_snapshots.all()
            key_items = [attr.name for attr in attributes]
            key_items_formatted = [
                f"{attr.name}: {attr.comments}" if attr.comments else attr.name
                for attr in attributes
            ]

        return DocumentConfig(
            doc_type=doc_type,
            extract_key_items=True,
            key_items=key_items,
            key_items_formatted=key_items_formatted,
            excluded_fields=[],
        )

    @classmethod
    def for_sales(cls, document) -> DocumentConfig:
        """Convenience method for sales document config."""
        return cls.for_attribute_extraction(DocumentType.SALES.value, document)

    @classmethod
    def for_payroll(cls, document) -> DocumentConfig:
        """Convenience method for payroll document config."""
        return cls.for_attribute_extraction(DocumentType.PAYROLL.value, document)

    @classmethod
    def for_misc(cls, document) -> DocumentConfig:
        """Convenience method for misc document config."""
        return cls.for_attribute_extraction(DocumentType.MISC.value, document)
