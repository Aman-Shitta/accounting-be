"""
Enhanced document processor specifically designed for MonthlyAccountingDocument.
This processor integrates directly with the database models and provides
better organization for bank statement and credit card processing.
"""

# System imports
import json
import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, List, Any

# Third-party imports
from django.conf import settings
from django.db import transaction

# Local imports
from .pipeline import DocumentProcessor
from account.models.monthly_accounting_document_model import MonthlyAccountingDocument
from account.models.monthly_document_line_models import (
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankCheckItem
)
from extractor.bank_statement.prompter import Configuration

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
        self.doc_processor = DocumentProcessor(config)
        self.logger = logging.getLogger(f"{__name__}.{monthly_document.doc_id}")
        
    def process_document(self, file_bytes: bytes, mime_type: str = "application/pdf") -> Dict[str, Any]:
        """
        Process the document and save results to database.
        
        Args:
            file_bytes: PDF file content as bytes
            mime_type: MIME type of the file
            
        Returns:
            Dict containing processing results and statistics
        """
        try:
            # Update document status
            self.monthly_document.upload_status = "processing"
            self.monthly_document.save()
            
            # Process using base processor
            self.doc_processor.process_document(file_bytes, mime_type)
            
            # Get results
            page_data = self.doc_processor.get_page_data()

            control_totals = self.doc_processor.get_control_totals()
            
            # Save control totals to document
            self.monthly_document.control_item = control_totals
            self.monthly_document.save()
            
            # Process and save extracted data
            processing_stats = self._save_extracted_data(page_data)
            
            # Update document status
            self.monthly_document.upload_status = "completed"
            self.monthly_document.save()
            
            self.logger.info(f"Document {self.monthly_document.doc_id} processed successfully")
            
            return {
                "status": "success",
                "control_totals": control_totals,
                "processing_stats": processing_stats,
                "page_count": len(page_data)
            }
            
        except Exception as e:
            self.monthly_document.upload_status = "failed"
            self.monthly_document.save()
            self.logger.error(f"Failed to process document {self.monthly_document.doc_id}: {str(e)}")
            raise
    
    def _save_extracted_data(self, page_data: List[Dict]) -> Dict[str, int]:
        """
        Save extracted data to database models.
        
        Args:
            page_data: List of page data from processor
            
        Returns:
            Dict with processing statistics
        """
        stats = {
            "key_items": 0,
            "line_items": 0,
            "check_items": 0,
            "pages_processed": 0
        }
        
        with transaction.atomic():
            # Clear existing data for reprocessing
            self._clear_existing_data()

            for page_idx, page_item in enumerate(page_data):
                page_key = f"page_{page_idx + 1}"
                page_content = page_item.get(page_key, {})
                
                # Process transactions
                transactions = page_content.get("transactions", {})
                
                # Save key items (summary data)
                key_items_data = transactions.get("key_items", {})
                if isinstance(key_items_data, dict):
                    for key, value in key_items_data.items():
                        MonthlyDocumentBankKeyItem.objects.create(
                            document=self.monthly_document,
                            page_number=page_idx + 1,
                            key=key,
                            value=str(value) if value is not None else ""
                        )
                        stats["key_items"] += 1
                
                # Save line items (transactions)
                line_items_data = transactions.get("line_items", [])
                for line_idx, line_item in enumerate(line_items_data):
                    self._save_line_item(page_idx + 1, line_idx + 1, line_item)
                    stats["line_items"] += 1
                
                # Save check data
                check_data = page_content.get("check_data", {})
                checks = check_data.get("checks", [])
                for check_item in checks:
                    check_obj = self._save_check_item(page_idx + 1, check_item)
                    stats["check_items"] += 1
                    
                    # Try to link check to line item
                    self._link_check_to_line_item(check_obj)
                
                stats["pages_processed"] += 1
                
        self.logger.info(f"Saved extracted data: {stats}")
        return stats
    
    def _clear_existing_data(self):
        """Clear existing extracted data for reprocessing."""
        MonthlyDocumentBankKeyItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankLineItem.objects.filter(document=self.monthly_document).delete()
        MonthlyDocumentBankCheckItem.objects.filter(document=self.monthly_document).delete()
    
    def _save_line_item(self, page_number: int, line_number: int, line_data: Dict) -> MonthlyDocumentBankLineItem:
        """
        Save a transaction line item to the database.
        
        Args:
            page_number: Page number
            line_number: Line number within page
            line_data: Raw line item data from extractor
            
        Returns:
            Created MonthlyDocumentBankLineItem instance
        """
        # Extract basic fields
        date = line_data.get("date", "")
        description = line_data.get("description", "")
        debit_amount_raw = line_data.get("debit_amount", "")
        credit_amount_raw = line_data.get("credit_amount", "")
        
        # Determine transaction type and amount
        transaction_type = None
        amount = None
        
        try:
            if debit_amount_raw and str(debit_amount_raw).strip() and str(debit_amount_raw).lower() not in ['', 'null', 'none', '-']:
                transaction_type = 'debit'
                amount = self._parse_amount(debit_amount_raw)
            elif credit_amount_raw and str(credit_amount_raw).strip() and str(credit_amount_raw).lower() not in ['', 'null', 'none', '-']:
                transaction_type = 'credit'
                amount = self._parse_amount(credit_amount_raw)
        except Exception as e:
            self.logger.warning(f"Failed to parse amounts for line {page_number}.{line_number}: {e}")
        
        # Check transaction detection
        is_check_transaction = line_data.get("is_check_transaction", False)
        check_number = line_data.get("check_number", "") if is_check_transaction else None
        
        # Create line item
        line_item = MonthlyDocumentBankLineItem.objects.create(
            document=self.monthly_document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
            debit_amount=str(debit_amount_raw) if debit_amount_raw else None,
            credit_amount=str(credit_amount_raw) if credit_amount_raw else None,
            is_check_transaction=is_check_transaction,
            check_number=check_number,
            # GL accounts will be set during classification
            gl_account=None,
            offset_gl_account=None
        )
        
        return line_item
    
    def _save_check_item(self, page_number: int, check_data: Dict) -> MonthlyDocumentBankCheckItem:
        """
        Save a check item to the database.
        
        Args:
            page_number: Page number
            check_data: Raw check data from extractor
            
        Returns:
            Created MonthlyDocumentBankCheckItem instance
        """
        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.monthly_document,
            page_number=page_number,
            amount=str(check_data.get("amount", "")),
            payee=check_data.get("payee", ""),
            memo=check_data.get("memo", ""),
            clearing_date=check_data.get("clearing_date", ""),
            passing_date=check_data.get("passing_date", ""),
            check_number=check_data.get("check_number", ""),
            related_line_item=None  # Will be set in _link_check_to_line_item
        )
        
        return check_item
    
    def _link_check_to_line_item(self, check_item: MonthlyDocumentBankCheckItem):
        """
        Try to link a check item to its corresponding line item.
        
        Args:
            check_item: MonthlyDocumentBankCheckItem to link
        """
        if not check_item.check_number:
            return
        
        # Look for line item with matching check number
        matching_line_item = MonthlyDocumentBankLineItem.objects.filter(
            document=self.monthly_document,
            check_number=check_item.check_number,
            is_check_transaction=True
        ).first()
        
        if matching_line_item:
            check_item.related_line_item = matching_line_item
            check_item.save()
            self.logger.debug(f"Linked check #{check_item.check_number} to line item {matching_line_item.id}")
    
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
            self.logger.warning(f"Failed to parse amount '{amount_str}': {e}")
            return None
    
    def get_processing_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the processed document.
        
        Returns:
            Dict containing processing summary
        """
        return {
            "document_id": str(self.monthly_document.doc_id),
            "document_type": self.monthly_document.doc_type,
            "status": self.monthly_document.upload_status,
            "control_totals": self.monthly_document.control_item,
            "key_items_count": MonthlyDocumentBankKeyItem.objects.filter(document=self.monthly_document).count(),
            "line_items_count": MonthlyDocumentBankLineItem.objects.filter(document=self.monthly_document).count(),
            "check_items_count": MonthlyDocumentBankCheckItem.objects.filter(document=self.monthly_document).count(),
            "created_at": self.monthly_document.created_at.isoformat(),
            "updated_at": self.monthly_document.updated_at.isoformat()
        }


class MonthlyDocumentBatchProcessor:
    """
    Batch processor for multiple MonthlyAccountingDocument instances.
    Useful for processing multiple documents in a monthly accounting session.
    """
    
    def __init__(self, config: Configuration):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
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
                    self.logger.warning(f"Document {document.doc_id} has no file attached")
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
                self.logger.error(f"Failed to process document {document.doc_id}: {str(e)}")
                results["failed"].append({
                    "document_id": str(document.doc_id),
                    "error": str(e)
                })
                results["total_failed"] += 1
        
        self.logger.info(f"Batch processing completed: {results['total_processed']} successful, {results['total_failed']} failed")
        return results
