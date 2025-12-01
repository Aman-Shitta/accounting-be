"""
Enhanced document processor specifically designed for MonthlyAccountingDocument.
This processor integrates directly with the database models and provides
better organization for bank statement and credit card processing.
"""

# System imports
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Any

# Third-party imports
from django.conf import settings
from django.db import transaction

# Local imports

from account.models.monthly_accounting_document_model import MonthlyAccountingDocument
from account.models.monthly_document_line_models import (
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankCheckItem
)
from extractor.prompter import Configuration

logger = logging.getLogger(__name__)


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
        """Set the underlying DocumentProcessor instance."""
        if doc_type in ['bank_statement', 'credit_card']:
            # from extractor.bank_statement.pipeline import DocumentProcessor
            from extractor.bank_statement.pipeline_landing import DocumentProcessor as LandingDocumentProcessor
            self.doc_processor = LandingDocumentProcessor(self.config, self.monthly_document)
        elif doc_type in ['sales', 'payroll', 'misc']:
            from extractor.sales.pipeline import DocumentProcessor
            self.doc_processor = DocumentProcessor(self.config, self.monthly_document)
        else:
            raise ValueError(f"Unsupported document type: {doc_type}")

    def __release_resources__(self):
        """Release resources held by the processor."""
        if self.doc_processor:
            del self.doc_processor
            self.doc_processor = None

    def start_process(self, file_bytes: str, mime_type: str = "application/pdf", md=False) -> Dict[str, Any]:
        """
        Process the document and save results to database.
        
        Args:
            file_bytes: PDF file content as bytes
            mime_type: MIME type of the file
            
        Returns:
            Dict containing extracting results and statistics
        """
        try:
            # Update document status
            self.monthly_document.status = "extracting"
            self.monthly_document.save()
            
            # Clear existing data for reprocessing
            self._clear_existing_data()

            # Process using base processor
            return_data = self.doc_processor.process_document(file_bytes, mime_type, md)
            
            self.monthly_document.status = "extracted"
            self.monthly_document.save()
            
            logger.info(f"Document {self.monthly_document.doc_id} processed successfully")
            
            return return_data
            
        except Exception as e:
            self.monthly_document.status = "failed"
            self.monthly_document.save()
            logger.error(f"Failed to process document {self.monthly_document.doc_id}: {str(e)}")
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
        
        try:
            # Clean the amount string
            clean_amount = str(amount_str).replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            
            # Handle parentheses for negative amounts
            if clean_amount.startswith('-'):
                clean_amount = clean_amount[1:]
                return -Decimal(clean_amount)
            
            return Decimal(clean_amount)
            
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse amount '{amount_str}': {e}")
            return None
    
    def _clear_existing_data(self):
        """Clear existing extracted data for reprocessing."""
        MonthlyDocumentBankKeyItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankLineItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankCheckItem.objects.filter(document=self.monthly_document).delete()



    
class MonthlyDocumentBatchProcessor:
    """
    Batch processor for multiple MonthlyAccountingDocument instances.
    Useful for processing multiple documents in a monthly accounting session.
    """
    
    def __init__(self, config: Configuration):
        self.config = config
        logger = logging.getLogger(__name__)
    
    def process_documents(self, documents: List[MonthlyAccountingDocument]) -> Dict[str, Any]:
        """
        Process multiple documents in batch.
        
        Args:
            documents: List of MonthlyAccountingDocument instances
            
        Returns:
            Dict containing batch processing results
        """
        results = {
            "successful": [],
            "failed": [],
            "total_processed": 0,
            "total_failed": 0
        }
        
        for document in documents:
            try:
                if not document.file:
                    logger.warning(f"Document {document.doc_id} has no file attached")
                    results["failed"].append({
                        "document_id": str(document.doc_id),
                        "error": "No file attached"
                    })
                    continue
                
                # Read file content
                with document.file.open('rb') as f:
                    file_bytes = f.read()
                
                # Process document
                processor = MonthlyAccountingDocumentProcessor(document, self.config)
                result = processor.process_document(file_bytes)
                
                results["successful"].append({
                    "document_id": str(document.doc_id),
                    "result": result
                })
                results["total_processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed to process document {document.doc_id}: {str(e)}")
                results["failed"].append({
                    "document_id": str(document.doc_id),
                    "error": str(e)
                })
                results["total_failed"] += 1
        
        logger.info(f"Batch processing completed: {results['total_processed']} successful, {results['total_failed']} failed")
        return results
