"""
Enhanced document processor specifically designed for MonthlyAccountingDocument.
This processor integrates directly with the database models and provides
better organization for bank statement and credit card processing.
"""

# System imports
import re
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Any, Type

# Third-party imports
from django.conf import settings
from django.db import transaction

# Local imports

from aicounting.file_upload_helper import DocumentDebugStorage
from account.models.monthly_accounting_document_model import MonthlyAccountingDocument
from account.models.monthly_document_line_models import (
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankCheckItem
)
from extractor.prompter import Configuration
from extractor.config_factory import DocumentType

logger = logging.getLogger(__name__)


class ProcessorRegistry:
    """
    Registry for document processors.
    
    Uses a registry pattern instead of if/else chains for processor selection.
    New processor types can be registered without modifying existing code.
    
    Usage:
        # Register a processor
        @ProcessorRegistry.register('bank_statement', 'credit_card')
        class BankStatementProcessor:
            ...
        
        # Get a processor
        processor_class = ProcessorRegistry.get('bank_statement')
    """
    
    _registry: Dict[str, Type] = {}
    
    @classmethod
    def register(cls, *doc_types: str):
        """
        Decorator to register a processor class for document types.
        
        Args:
            *doc_types: Document type strings this processor handles
        """
        def decorator(processor_class: Type):
            for doc_type in doc_types:
                cls._registry[doc_type] = processor_class
                logger.debug(f"Registered {processor_class.__name__} for {doc_type}")
            return processor_class
        return decorator
    
    @classmethod
    def get(cls, doc_type: str) -> Type:
        """
        Get the processor class for a document type.
        
        Args:
            doc_type: Document type string
            
        Returns:
            Processor class
            
        Raises:
            ValueError: If no processor registered for doc_type
        """
        if doc_type not in cls._registry:
            available = list(cls._registry.keys())
            raise ValueError(
                f"No processor registered for '{doc_type}'. "
                f"Available: {available}"
            )
        return cls._registry[doc_type]
    
    @classmethod
    def get_all(cls) -> Dict[str, Type]:
        """Get all registered processors."""
        return cls._registry.copy()
    
    @classmethod
    def is_registered(cls, doc_type: str) -> bool:
        """Check if a processor is registered for doc_type."""
        return doc_type in cls._registry


# Register processors lazily to avoid circular imports
def _register_default_processors():
    """Register default processors. Called on first use."""
    if ProcessorRegistry._registry:
        return  # Already registered
    
    # Import and register bank/credit card processor
    from extractor.banking.pipeline_landing_v1 import DocumentProcessorV1
    ProcessorRegistry.register(
        DocumentType.BANK_STATEMENT.value,
        DocumentType.CREDIT_CARD.value
    )(DocumentProcessorV1)
    
    # Import and register KV processor for sales/payroll/misc
    from extractor.kv_processor.pipeline_landing import DocumentProcessor as KVProcessor
    ProcessorRegistry.register(
        DocumentType.SALES.value,
        DocumentType.PAYROLL.value,
        DocumentType.MISC.value
    )(KVProcessor)


class MonthlyAccountingDocumentProcessor:
    """
    Enhanced document processor for MonthlyAccountingDocument that:
    1. Processes bank statements and credit card documents
    2. Saves extracted data directly to the database
    3. Handles GL account classification
    4. Provides better error handling and logging
    """
    
    def __init__(self, monthly_document: MonthlyAccountingDocument, config: Configuration):
        self.monthly_document = monthly_document
        self.config = config
        self.doc_processor = None
    
    def set_doc_processor(self, doc_type: str):
        """
        Set the underlying DocumentProcessor instance using the registry.
        
        Args:
            doc_type: Document type string (e.g., 'bank_statement', 'sales')
        """
        # Ensure processors are registered
        _register_default_processors()
        
        # Get processor class from registry
        processor_class = ProcessorRegistry.get(doc_type)
        self.doc_processor = processor_class(self.config, self.monthly_document)

        # Initialize and set debug storage
        try:
            debug_storage = DocumentDebugStorage(self.monthly_document)
            if hasattr(self.doc_processor, 'set_debug_storage'):
                self.doc_processor.set_debug_storage(debug_storage)
        except Exception as e:
            logger.warning(f"Failed to initialize debug storage: {e}")

    def __release_resources__(self):
        """Release resources held by the processor."""
        if self.doc_processor:
            del self.doc_processor
            self.doc_processor = None

    def start_process(self, file_bytes: str, mime_type: str = "application/pdf", md=False, special_rules="") -> Dict[str, Any]:
        """
        Process the document and save results to database.
        
        Args:
            file_bytes: PDF file content as bytes
            mime_type: MIME type of the file
            
        Returns:
            Dict containing extracting results and statistics
        """
        try:            
            # Clear existing data for reprocessing
            self._clear_existing_data()

            # Process using base processor
            return_data = self.doc_processor.process_document(
                file_bytes,
                # mime_type,
                # md,
                # special_rules
            )
            
            self.monthly_document.status = "extracted"
            self.monthly_document.save()
            
            logger.info(f"Document {self.monthly_document.id} processed successfully")
            
            return return_data
            
        except Exception as e:
            self.monthly_document.status = "failed"
            self.monthly_document.save()
            logger.error(f"Failed to process document {self.monthly_document.id}: {str(e)}")
            raise
    
    def _parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """
        Parse amount string to Decimal.
        
        Args:
            amount_str: Amount string from extraction
            
        Returns:
            Parsed Decimal amount or None if parsing fails
        """
        if not amount_str or str(amount_str).strip() in ['', 'null', 'none', '-']:
            return None
        
        amount_str = re.sub(r'[^\d\.]', '', str(amount_str))

        try:
            # Clean the amount string
            clean_amount = str(amount_str).replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            
            # Handle parentheses for negative amounts
            if clean_amount.startswith('-'):
                clean_amount = clean_amount[1:]
                return -Decimal(clean_amount)
            
            return Decimal(clean_amount)
            
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_str}': {e}")
            return None
    
    def _clear_existing_data(self):
        """Clear existing extracted data for reprocessing."""
        MonthlyDocumentBankKeyItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankLineItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankCheckItem.objects.filter(document=self.monthly_document).delete()


