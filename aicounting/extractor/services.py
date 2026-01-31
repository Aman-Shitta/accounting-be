"""
Document Processing Service

Facade service that orchestrates the document processing flow.
This moves business logic out of views and provides a clean API
for document processing operations.
"""

import logging
from typing import Optional, Dict, Any

from django.core.files.storage import default_storage

from account.models.monthly_accounting_document_model import MonthlyAccountingDocument
from extractor.config_factory import DocumentConfigFactory, DocumentConfig, DocumentType

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    """Base exception for document processing errors."""
    pass


class DocumentNotFoundError(DocumentProcessingError):
    """Raised when document cannot be found."""
    pass


class FileNotFoundError(DocumentProcessingError):
    """Raised when document file is not in storage."""
    pass


class UnsupportedDocTypeError(DocumentProcessingError):
    """Raised when document type is not supported."""
    pass


class DocumentProcessingService:
    """
    Service facade for document processing operations.
    
    This service:
    1. Creates appropriate configurations for document types
    2. Dispatches processing tasks to Celery
    3. Handles status management
    4. Provides a clean interface for views/APIs
    
    Usage:
        service = DocumentProcessingService(document)
        service.start_processing()  # Async via Celery
        
        # Or for sync processing (testing):
        result = service.process_sync()
    """
    
    def __init__(self, document: MonthlyAccountingDocument):
        """
        Initialize the service with a document.
        
        Args:
            document: MonthlyAccountingDocument to process
        """
        self.document = document
        self._config: Optional[DocumentConfig] = None
    
    @property
    def config(self) -> DocumentConfig:
        """Get or create the configuration for this document."""
        if self._config is None:
            self._config = DocumentConfigFactory.create_config(self.document)
        return self._config
    
    @classmethod
    def from_document_id(cls, document_id: str) -> "DocumentProcessingService":
        """
        Create service instance from document ID.
        
        Args:
            document_id: UUID string of the document
            
        Returns:
            DocumentProcessingService instance
            
        Raises:
            DocumentNotFoundError: If document not found
        """
        try:
            document = MonthlyAccountingDocument.objects.get(id=document_id)
            return cls(document)
        except MonthlyAccountingDocument.DoesNotExist:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
    
    def validate_for_processing(self) -> None:
        """
        Validate document is ready for processing.
        
        Raises:
            FileNotFoundError: If file not in storage
            UnsupportedDocTypeError: If doc type not supported
        """
        # Check file exists
        file_path = self.document.file.name if self.document.file else None
        if not file_path or not default_storage.exists(file_path):
            raise FileNotFoundError(f"File not found in storage: {file_path}")
        
        # Check doc type is supported
        valid_types = [e.value for e in DocumentType]
        if self.document.doc_type not in valid_types:
            raise UnsupportedDocTypeError(
                f"Unsupported document type: {self.document.doc_type}"
            )
    
    def start_processing(self) -> str:
        """
        Start processing with GL classification chain.
        
        For bank statements and credit cards, this chains the 
        extraction task with the classification task.
        
        Returns:
            Celery task/chain ID
        """
        self.validate_for_processing()
        
        from account.tasks import (
            process_uploaded_document,
            classify_document_gl_accounts_task
        )
        from celery import chain
        
        doc_id = str(self.document.id)
        config_dict = self.config.to_dict()
        
        if self.document.doc_type in DocumentType.transactional_types():
            # Chain extraction → classification for bank/credit card
            # process_uploaded_document.run(doc_id, config_dict)
            task_chain = chain(
                process_uploaded_document.s(doc_id, config_dict),
                classify_document_gl_accounts_task.s(doc_id)
            )
            result = task_chain.apply_async()
            logger.info(
                f"Started processing chain for document {doc_id}: "
                f"extraction → classification"
            )
        else:
            # Just extraction for other types
            result = process_uploaded_document.delay(doc_id, config_dict)
            logger.info(f"Started processing for document {doc_id}")
        
        return result.id
    
    def get_file_bytes(self) -> bytes:
        """
        Get document file content from storage.
        
        Returns:
            File content as bytes
            
        Raises:
            FileNotFoundError: If file not accessible
        """
        file_path = self.document.file.name if self.document.file else None
        if not file_path or not default_storage.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with default_storage.open(file_path, 'rb') as f:
            return f.read()
    
    # def process_sync(self) -> Dict[str, Any]:
    #     """
    #     Process document synchronously (for testing/debugging).
        
    #     Returns:
    #         Processing result dict
    #     """
    #     from extractor.processor import MonthlyAccountingDocumentProcessor
    #     from extractor.prompter import Configuration
        
    #     self.validate_for_processing()
        
    #     # Convert our config to the legacy Configuration class
    #     config = Configuration(**self.config.to_dict())
        
    #     processor = MonthlyAccountingDocumentProcessor(self.document, config)
    #     processor.set_doc_processor(self.document.doc_type)
        
    #     try:
    #         file_bytes = self.get_file_bytes()
    #         special_rules = (
    #             self.document.input_file_snapshot.description 
    #             if self.document.input_file_snapshot else ""
    #         )
    #         result = processor.start_process(file_bytes, md=True, special_rules=special_rules)
    #         return result
    #     finally:
    #         processor.__release_resources__()
    
    def update_status(self, status: str) -> None:
        """
        Update document status.
        
        Args:
            status: New status value
        """
        self.document.status = status
        self.document.save(update_fields=['status'])
        logger.debug(f"Document {self.document.id} status → {status}")
    
    @staticmethod
    def get_supported_doc_types() -> Dict[str, str]:
        """Get dict of supported document types and descriptions."""
        return {
            DocumentType.BANK_STATEMENT.value: "Bank statement with transactions",
            DocumentType.CREDIT_CARD.value: "Credit card statement with transactions",
            DocumentType.SALES.value: "Sales document with key-value attributes",
            DocumentType.PAYROLL.value: "Payroll document with key-value attributes",
            DocumentType.MISC.value: "Miscellaneous document with key-value attributes",
        }


class GLClassificationService:
    """
    Service for GL account classification operations.
    
    Handles the classification of line items in processed documents.
    """
    
    def __init__(self, document: MonthlyAccountingDocument):
        self.document = document
    
    @classmethod
    def from_document_id(cls, document_id: str) -> "GLClassificationService":
        """Create service from document ID."""
        try:
            document = MonthlyAccountingDocument.objects.get(id=document_id)
            return cls(document)
        except MonthlyAccountingDocument.DoesNotExist:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
    
    def enrich_check_descriptions(self) -> int:
        """
        Enrich check transaction descriptions with payee/memo info.
        
        Returns:
            Number of descriptions enriched
        """
        from account.models.monthly_document_line_models import MonthlyDocumentBankCheckItem
        
        enriched_count = 0
        
        check_items = self.document.check_items.filter(
            related_line_item__isnull=False
        ).select_related('related_line_item')
        
        for check_item in check_items:
            line_item = check_item.related_line_item
            description_parts = [line_item.description or ""]
            
            # Add payee info
            if check_item.payee and check_item.payee.strip():
                raw_payee = check_item.payee.strip()
                if raw_payee.lower() != "null":
                    payee_info = f"Payee: {raw_payee}"
                    if payee_info not in description_parts[0]:
                        description_parts.append(payee_info)
            
            # Add memo info
            if check_item.memo and check_item.memo.strip():
                raw_memo = check_item.memo.strip()
                if raw_memo.lower() != "null":
                    memo_info = f"Memo: {raw_memo}"
                    if memo_info not in description_parts[0]:
                        description_parts.append(memo_info)
            
            # Update if enriched
            if len(description_parts) > 1:
                line_item.description = " | ".join(description_parts)
                line_item.save(update_fields=['description'])
                enriched_count += 1
        
        logger.info(f"Enriched {enriched_count} check descriptions for document {self.document.id}")
        return enriched_count
    
    def classify_line_items(self, batch_size: int = 10) -> int:
        """
        Classify GL accounts for line items in batches.
        
        Args:
            batch_size: Number of items per classification batch (default 10)
        
        Returns:
            Number of line items classified
        """
        from account.models.monthly_document_line_models import MonthlyDocumentBankLineItem
        from account.models import DimAICGLAcct
        from extractor.banking.classify import GLClassifier
        
        # Get classification rules
        input_file_rules = (
            self.document.input_file_snapshot.description
            if self.document.input_file_snapshot else ""
        )
        
        # First enrich check descriptions
        self.enrich_check_descriptions()
        
        # Get assistant info for classification
        client_assistant = getattr(self.document.monthly_accounting.client, 'assistant', None)
        assistant_id = (
            client_assistant.assistant_id 
            if client_assistant and client_assistant.assistant_id else None
        )
        vector_store_ids = (
            [client_assistant.vector_store_id]
            if client_assistant and client_assistant.vector_store_id else []
        )
        
        classified_count = 0
        
        if assistant_id:
            try:
                # Get all line items ordered by page and line number
                line_items_qs = MonthlyDocumentBankLineItem.objects.filter(
                    document=self.document
                ).select_related('gl_account', 'offset_gl_account').order_by('page_number', 'line_number')
                
                # Apply default offset GL
                default_offset_gl = self._get_default_offset_gl()
                line_items_qs.update(offset_gl_account=default_offset_gl)
                
                # Re-fetch after update
                line_items_list = list(line_items_qs)
                
                if not line_items_list:
                    logger.info(f"No line items to classify for document {self.document.id}")
                    return 0
                
                # Build batches of items (batch_size items at a time)
                batches = []
                for i in range(0, len(line_items_list), batch_size):
                    batch = line_items_list[i:i + batch_size]
                    batches.append(batch)
                
                logger.info(f"Processing {len(line_items_list)} items in {len(batches)} batches of {batch_size}")
                
                # Accumulate all classified results
                all_classified_pages = {}
                
                for batch_idx, batch in enumerate(batches):
                    try:
                        # Build extracted data structure for this batch
                        batch_extracted = self._build_batch_extracted_data(batch)
                        
                        # Create classifier for this batch
                        classifier = GLClassifier(
                            assistant_id=assistant_id,
                            vector_store_ids=vector_store_ids,
                            special_rules=input_file_rules
                        )
                        
                        # Classify the batch
                        batch_results = classifier.classify_extracted_data(batch_extracted)
                        
                        # Merge results into accumulated dict
                        for page_num, page_data in (batch_results or {}).items():
                            if page_num not in all_classified_pages:
                                all_classified_pages[page_num] = {}
                            if isinstance(page_data, dict):
                                all_classified_pages[page_num].update(page_data)
                            elif isinstance(page_data, list):
                                # Convert list to dict keyed by id
                                for item in page_data:
                                    item_id = item.get('id')
                                    if item_id:
                                        all_classified_pages[page_num][item_id] = item
                        
                        logger.info(f"Batch {batch_idx + 1}/{len(batches)} classified successfully")
                        
                    except Exception as e:
                        logger.error(f"Error classifying batch {batch_idx + 1}: {e}")
                        continue
                
                # Build lookup dict for line items
                line_items_by_page = {}
                for li in line_items_list:
                    line_items_by_page.setdefault(li.page_number, {})[li.line_number] = li
                
                # Apply accumulated classifications
                updated_items = []
                for page_num, page_data in all_classified_pages.items():
                    iterable = page_data.values() if isinstance(page_data, dict) else page_data
                    for cls_item in iterable:
                        try:
                            line_num = int(cls_item.get('id', 0))
                            target = line_items_by_page.get(int(page_num), {}).get(line_num)
                            
                            if not target or target.gl_account:
                                continue
                            
                            gl_identifier = cls_item.get('gl_account')
                            if gl_identifier:
                                resolved_gl = DimAICGLAcct.objects.filter(
                                    client_id=self.document.monthly_accounting.client,
                                    account_number=str(gl_identifier).strip()
                                ).first()
                                
                                if resolved_gl:
                                    target.gl_account = resolved_gl
                                    updated_items.append(target)
                        except Exception as e:
                            logger.warning(f"Skipping classification item: {e}")
                
                # Bulk update
                if updated_items:
                    MonthlyDocumentBankLineItem.objects.bulk_update(
                        updated_items, ['gl_account']
                    )
                    classified_count = len(updated_items)
                
            except Exception as e:
                logger.error(f"Classification failed for document {self.document.id}: {e}")
        
        logger.info(f"Classified {classified_count} line items for document {self.document.id}")
        return classified_count
    
    def _build_batch_extracted_data(self, line_items: list) -> dict:
        """
        Build extracted data structure for a batch of line items.
        
        Args:
            line_items: List of MonthlyDocumentBankLineItem objects
            
        Returns:
            Dict structured as {page_number: {"line_items": {line_number: {...}}}}
        """
        extracted = {}
        
        for li in line_items:
            page_dict = extracted.setdefault(li.page_number, {"line_items": {}})
            txn_type = li.transaction_type
            
            # Derive debit/credit raw fields for compatibility
            debit_amount = None
            credit_amount = None
            if txn_type == 'debit':
                debit_amount = float(li.amount) if li.amount is not None else None
            elif txn_type == 'credit':
                credit_amount = float(li.amount) if li.amount is not None else None
            else:
                if li.amount is not None:
                    debit_amount = float(li.amount)
            
            page_dict["line_items"][li.line_number] = {
                "id": li.line_number,
                "description": li.description or "",
                "debit_amount": debit_amount,
                "credit_amount": credit_amount,
                "transaction_type": txn_type or ("debit" if debit_amount else "credit")
            }
        
        return extracted
    
    def _get_default_offset_gl(self):
        """Get default offset GL account from input file snapshot."""
        if not self.document.input_file_snapshot:
            return None
        
        bank_attributes = self.document.input_file_snapshot.attribute_snapshots.all()
        if bank_attributes.count() == 1:
            return bank_attributes.first().offset_gl_account
        return None
