# System imports
import logging
import os
import sys, traceback
import time
import json
from datetime import datetime

# Third-party imports
from celery import shared_task, chain
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings

# Local imports
from extractor.banking.classify import GLClassifier
from extractor.processor import MonthlyAccountingDocumentProcessor
from extractor.config_factory import DocumentConfig, DocumentType

from .models.monthly_accounting_document_model import MonthlyAccountingDocument
from .models.monthly_document_line_models import (
    MonthlyDocumentBankLineItem,
)
from .models import DimAICGLAcct

from agentic_doc.parse import parse
from agentic_doc.config import ParseConfig
from extractor.utils import split_pdf_to_pages
from aicounting.file_upload_helper import DocumentDebugStorage

logger = logging.getLogger(__name__)


@shared_task
def preprocess_document_markdown(doc_id: str):
    """
    Pre-process document by generating markdown for all pages and storing in Azure.
    This runs before actual extraction to prepare markdown files.
    
    Args:
        doc_id: MonthlyAccountingDocument ID
    """
    
    
    doc = None
    try:
        doc = MonthlyAccountingDocument.objects.get(id=doc_id)
        
        # Only pre-process bank statements and credit cards
        if doc.doc_type not in ['bank_statement', 'credit_card']:
            logger.error(f"Document type {doc.doc_type} doesn't require markdown pre-processing")
            doc.status = 'uploaded'
            doc.save()
            return {"status": "skipped", "reason": "Document type doesn't require markdown"}
        
        logger.info(f"Starting markdown pre-processing for document {doc.id}")
        doc.status = 'pre_processing'
        doc.save()
        
        # Get file from Azure storage
        file_path = doc.file.name if doc.file else None
        if not file_path or not default_storage.exists(file_path):
            logger.error(f"File does not exist in Azure storage: {file_path}")
            doc.status = 'failed'
            doc.save()
            return {"status": "failed", "error": "File not found"}
        
        with default_storage.open(file_path, 'rb') as azure_file:
            file_bytes = azure_file.read()
        
        # Split PDF into pages
        page_bytes_list = split_pdf_to_pages(file_bytes)
        logger.info(f"Split PDF into {len(page_bytes_list)} pages")
        
        # Initialize Landing AI parser
        landing_ai_key = settings.LANDING_AI_API_KEY
        landing_ai_config = ParseConfig(
            api_key=landing_ai_key,
        )
        
        # Prepare storage paths
        doc_folder = f"monthly_accounting/{doc.monthly_accounting.client_id}/{doc.monthly_accounting.id}/documents/{doc.id}"
        markdown_folder = f"{doc_folder}/markdown"
        
        # Generate markdown for each page
        markdown_pages = []
        for i, page_bytes in enumerate(page_bytes_list):
            page_num = i + 1
            try:
                logger.info(f"Generating markdown for page {page_num}/{len(page_bytes_list)}")
                
                # Parse page with Landing AI
                result = parse(
                    documents=page_bytes,
                    config=landing_ai_config
                )
                page_markdown = result[0].markdown
                
                # Save markdown to Azure
                markdown_filename = f"page_{page_num}.md"
                markdown_path = f"{markdown_folder}/{markdown_filename}"
                
                markdown_content = ContentFile(page_markdown.encode("utf-8"))
                saved_path = default_storage.save(markdown_path, markdown_content)
                
                
                markdown_url = default_storage.url(saved_path, expire_minutes=10)
                
                markdown_pages.append({
                    "page_number": page_num,
                    "path": saved_path,
                    "url": markdown_url,
                    "size": len(page_markdown)
                })
                
                logger.info(f"Saved markdown for page {page_num} to {saved_path}")
                
            except Exception as e:
                logger.error(f"Failed to process page {page_num}: {str(e)}")
                markdown_pages.append({
                    "page_number": page_num,
                    "path": None,
                    "url": None,
                    "error": str(e)
                })
        
        # Save metadata
        markdown_metadata = {
            "total_pages": len(page_bytes_list),
            "processed_pages": len([p for p in markdown_pages if p.get("path")]),
            "markdown_folder": markdown_folder,
            "pages": markdown_pages,
            "generated_at": datetime.now().isoformat(),
            "sas_expiry_hours": 24
        }
        
        doc.markdown_metadata = markdown_metadata
        doc.status = 'pre_processed'
        doc.save()
        
        logger.info(f"Markdown pre-processing complete for document {doc.id}")
        return {
            "status": "success",
            "total_pages": len(page_bytes_list),
            "processed_pages": markdown_metadata["processed_pages"]
        }
        
    except Exception as e:
        logger.error(f"Error in markdown pre-processing for document {doc_id}: {str(e)}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        
        if doc:
            doc.status = 'failed'
            doc.save()
        
        return {
            "status": "error",
        } 


@shared_task
def process_uploaded_document(
    doc_id: str,
    config_params: dict
):
    """
    Process a document uploaded to Azure Blob Storage using the new MonthlyAccountingDocumentProcessor.
    
    This task handles extraction only. For bank statements and credit cards,
    use process_and_classify_document() to chain extraction with classification.
    
    Args:
        doc_id: MonthlyAccountingDocument ID (UUID string)
        config_params: Configuration dict for the document processor
        
    Returns:
        dict: Processing result with status and stats
    """
    doc = None
    try:
        # Convert dict to DocumentConfig, then to legacy Configuration for processor
        if isinstance(config_params, dict):
            doc_config = DocumentConfig.from_dict(config_params)
        else:
            doc_config = config_params
        
        # Convert to legacy Configuration (contains prompt-building logic)
        config = doc_config.to_configuration()
            
        doc = MonthlyAccountingDocument.objects.filter(id=doc_id).first()
        if not doc:
            logger.error(f"Document does not exist: {doc_id} invalid id")
            return {"status": "error", "error": "Document not found"}

        # Check if file exists
        file_path = doc.file.name if doc.file else None

        if not file_path or not default_storage.exists(file_path):
            logger.error(f"File does not exist in Azure storage: {file_path}")
            doc.status = "failed"
            doc.save()
            return {"status": "error", "error": "File not found"}

        # Get file content from Azure storage
        with default_storage.open(file_path, 'rb') as azure_file:
            file_bytes = azure_file.read()

        # Use the MonthlyAccountingDocumentProcessor
        processor = MonthlyAccountingDocumentProcessor(doc, config)
        processor.set_doc_processor(doc.doc_type)
        
        start_time = time.time()
        special_rules = doc.input_file_snapshot.description if doc.input_file_snapshot else ""
        result = processor.start_process(file_bytes, md=True, special_rules=special_rules)
        
        processing_time = time.time() - start_time
        logger.info(f"Document processing time: {processing_time} seconds")
        processor.__release_resources__()

        # # Handle post-processing based on document type
        # if doc.doc_type in DocumentType.transactional_types():
        #     # For bank/credit card: chain to classification
        #     doc.status = "classifying"
        #     doc.save()
        #     # Dispatch classification as separate task
        #     classify_document_gl_accounts_task.delay(str(doc.id))
        # else:
        #     # For sales/payroll/misc: mark as classified (no GL classification needed)
        #     doc.status = "classified"
        #     doc.save()
       
        # Save processing output
        debug_storage = DocumentDebugStorage(doc)
        debug_storage.save_final_output(result, "processing_result.json")
        
        logger.info(f"Document {doc.id} processed successfully: {result.get('processing_stats', {})}")
        
        return {
            "status": "success",
            "doc_id": str(doc.id),
            "processing_time": processing_time,
            "stats": result.get('processing_stats', {})
        }

    except Exception as e:
        if doc:
            doc.status = "failed"
            doc.save()
            logger.error(f"Error processing document {doc.id}: {str(e)}")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        return {"status": "error", "error": str(e)}


@shared_task
def classify_document_gl_accounts_task(_previous_result=None, document_id: str = None):
    """
    Celery task wrapper for GL account classification.
    
    Can be used standalone or chained after process_uploaded_document.
    The _previous_result parameter allows this to be used in a Celery chain.
    
    Args:
        _previous_result: Result from previous task in chain (ignored)
        document_id: UUID string of the MonthlyAccountingDocument
        
    Returns:
        dict: Classification result with status and count
    """
    try:
        from extractor.services import GLClassificationService
        
        service = GLClassificationService.from_document_id(document_id)
        classified_count = service.classify_line_items()
        
        # Update document status
        doc = service.document
        doc.status = "classified"
        doc.save()
        
        logger.info(f"GL classification completed for document {document_id}")
        
        return {
            "status": "success",
            "doc_id": document_id,
            "classified_count": classified_count
        }
        
    except Exception as e:
        logger.error(f"GL Classification failed for document {document_id}: {str(e)}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        return {"status": "error", "error": str(e)}


def process_and_classify_document(doc_id: str, config_params: dict):
    """
    Convenience function to process a document with classification.
    
    Creates a Celery chain: extraction → classification
    
    Args:
        doc_id: MonthlyAccountingDocument ID
        config_params: Configuration dict
        
    Returns:
        Celery AsyncResult for the chain
    """
    task_chain = chain(
        process_uploaded_document.s(doc_id, config_params),
        classify_document_gl_accounts_task.s(doc_id)
    )
    return task_chain.apply_async()

