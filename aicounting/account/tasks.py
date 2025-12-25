# System imports
import logging
import os
import sys, traceback
import time
import json
from datetime import datetime

# Third-party imports
from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.conf import settings

# Local imports
from extractor.banking.classify import GLClassifier
from extractor.processor import MonthlyAccountingDocumentProcessor
from extractor.prompter import Configuration

from .models.monthly_accounting_document_model import MonthlyAccountingDocument
from .models.monthly_document_line_models import (
    MonthlyDocumentBankLineItem,
)
from .models import DimAICGLAcct

from agentic_doc.parse import parse
from agentic_doc.config import ParseConfig
from extractor.utils import split_pdf_to_pages

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
        
        logger.error(f"Starting markdown pre-processing for document {doc.id}")
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
        logger.error(f"Split PDF into {len(page_bytes_list)} pages")
        
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
                logger.error(f"Generating markdown for page {page_num}/{len(page_bytes_list)}")
                
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
                
                logger.error(f"Saved markdown for page {page_num} to {saved_path}")
                
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
        
        logger.error(f"Markdown pre-processing complete for document {doc.id}")
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
    Process a document uploaded to Azure Blob Storage using the new MonthlyAccountingDocumentProcessor
    
    Args:
        doc: MonthlyAccountingDocument instance to process
        config: Configuration for the document processor
    """
    try:
        config = Configuration(**config_params)
        doc = MonthlyAccountingDocument.objects.filter(id=doc_id).first()
        if not doc:
            logger.error(f"Document does not exist: {doc_id} invalid id")
            return 

        # Check if file exists
        file_path = doc.file.name if doc.file else None

        if not file_path or not default_storage.exists(file_path):
            logger.error(f"File does not exist in Azure storage: {file_path}")
            doc.status = "failed"
            doc.save()
            return

        # Get file content from Azure storage
        with default_storage.open(file_path, 'rb') as azure_file:
            file_bytes = azure_file.read()

        file_path = doc.file.name if doc.file else None

        # Use the new MonthlyAccountingDocumentProcessor
        processor = MonthlyAccountingDocumentProcessor(doc, config)
        processor.set_doc_processor(doc.doc_type)
        start_time = time.time()
        special_rules = doc.input_file_snapshot.description if doc.input_file_snapshot else ""
        result = processor.start_process(file_bytes, md=True, special_rules=special_rules)
        logger.error(f"Document processing time: {time.time() - start_time} seconds")
        processor.__release_resources__()

        if doc.doc_type in ['bank_statement', 'credit_card']:
            # Update document status
            doc.status = "classifying"
            doc.save()
            # Trigger GL account classification task
            classify_monthly_document_gl_accounts.delay(str(doc.id))
        else:
            doc.status = "classified"
            doc.save()
        
        
        
        output_json = json.dumps(result, indent=2, default=str)
        output_path = f"processed_output/{doc.id}/processing_result.json"
        default_storage.save(output_path, ContentFile(output_json.encode('utf-8')))
        
        logger.error(f"Document {doc.id} processed successfully: {result['processing_stats']}")


    except Exception as e:
        if doc:
            doc.status = "failed"
            doc.save()
            logger.error(f"Error processing document {doc.id}: {str(e)}")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        raise


def enrich_check_transaction_descriptions(document_id: str) -> int:
    """
    Enrich check transaction descriptions with payee and memo information from linked check items.
    This provides better context for GL classification.
    
    Args:
        document_id: UUID string of the MonthlyAccountingDocument
        
    Returns:
        Number of descriptions enriched
    """
    try:
        doc = MonthlyAccountingDocument.objects.get(id=document_id)
        enriched_count = 0
        
        # Get all check items with related line items
        check_items = doc.check_items.filter(
            related_line_item__isnull=False
        ).select_related('related_line_item')
        
        for check_item in check_items:
            line_item = check_item.related_line_item
            
            # Build enriched description
            description_parts = [line_item.description or ""]
            
            # Add payee information
            if check_item.payee and check_item.payee.strip():
                raw_payee = (check_item.payee or "").strip()
                payee_info = f"Payee: {raw_payee}" if raw_payee and raw_payee.lower() != "null" else ""
                if payee_info not in description_parts[0]:  # Avoid duplicates
                    description_parts.append(payee_info)
            
            # Add memo information
            if check_item.memo and check_item.memo.strip():
                raw_memo = (check_item.memo or "").strip()
                memo_info = f"Memo: {raw_memo}" if raw_memo and raw_memo.lower() != "null" else ""

                if memo_info not in description_parts[0]:  # Avoid duplicates
                    description_parts.append(memo_info)
            
            # Only update if we added new information
            if len(description_parts) > 1:
                original_desc = line_item.description
                enriched_description = " | ".join(description_parts)
                
                line_item.description = enriched_description
                line_item.save(update_fields=['description'])
                
                enriched_count += 1
                logger.error(
                    f"Enriched check #{check_item.check_number} description: "
                    f"'{original_desc}' -> '{enriched_description}'"
                )
        
        logger.error(f"Enriched {enriched_count} check transaction descriptions for document {document_id}")
        return enriched_count
        
    except Exception as e:
        logger.error(f"Error enriching check descriptions for document {document_id}: {str(e)}")
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        return 0


@shared_task
def classify_monthly_document_gl_accounts(document_id: str):
    """
    Classify GL accounts for line items in a MonthlyAccountingDocument.
    First enriches check transaction descriptions with payee/memo info.
    
    Args:
        document_id: UUID string of the MonthlyAccountingDocument
    """
    try:
        # Get the document
        doc = MonthlyAccountingDocument.objects.get(id=document_id)
        
        input_file_classsifcation_rules = doc.input_file_snapshot.description
        
        # First, enrich check transaction descriptions with payee and memo info
        logger.error(f"Enriching check descriptions for document {document_id}")
        enrich_check_transaction_descriptions(document_id)
        
        # Get the input file configuration for GL mapping
        input_file_snapshot = doc.input_file_snapshot
        
        # Get GL accounts from the input file configuration
        gl_mapping = {}
        offset_mapping = {}
        
        if input_file_snapshot and hasattr(input_file_snapshot, 'attribute_snapshots'):
            for attr_snapshot in input_file_snapshot.attribute_snapshots.all():
                if attr_snapshot.gl_account:
                    # Map attribute name to GL account
                    gl_mapping[attr_snapshot.name] = attr_snapshot.gl_account
                if attr_snapshot.offset_gl_account:
                    offset_mapping[attr_snapshot.name] = attr_snapshot.offset_gl_account
        
        # Actual GL classification logic
        try:
            client_assistant = getattr(doc.monthly_accounting.client, 'assistant', None)
            assistant_id = client_assistant.assistant_id if client_assistant and client_assistant.assistant_id else None
            vector_store_ids = [client_assistant.vector_store_id] if client_assistant and client_assistant.vector_store_id else []

            classified_pages_data = {}
            if assistant_id:
                try:

                    classifier_assistant = GLClassifier(
                        assistant_id=assistant_id,
                        vector_store_ids=vector_store_ids,
                        special_rules=input_file_classsifcation_rules
                    )
                    classified_pages_data = classifier_assistant.classify(document_id) or {}
                except Exception as e:
                    logger.error(f"Assistant classification call failed for document {document_id}: {e}")
            
            
            defaul_offset_gl = None
            bank_attributes = doc.input_file_snapshot.attribute_snapshots.all()
            if bank_attributes.count() != 1:
                raise
            else:
                defaul_offset_gl = bank_attributes.first().offset_gl_account
            
            # Fetch line items
            line_items_qs = MonthlyDocumentBankLineItem.objects.filter(document=doc).select_related('gl_account', 'offset_gl_account')

            line_items_qs.update(
                offset_gl_account=defaul_offset_gl,
            )

            line_items_by_page_and_line = {}
            for li in line_items_qs:
                line_items_by_page_and_line.setdefault(li.page_number, {})[li.line_number] = li

            # (Simplified) Only exact account number matching based on assistant output
            client_gl_accounts = None  # no preload needed for exact lookup

            updated_line_items = []
            # Apply assistant classification results if available
            for page_num, page_classifications in classified_pages_data.items():
                iterable = page_classifications.values() if isinstance(page_classifications, dict) else page_classifications
                for cls_item in iterable:
                    try:
                        line_id_raw = cls_item.get('id')
                        # Assistant returns line id as string; convert
                        try:
                            line_num_int = int(line_id_raw)
                        except Exception:
                            line_num_int = None
                        target_li = None
                        if line_num_int is not None:
                            target_li = line_items_by_page_and_line.get(int(page_num), {}).get(line_num_int)
                        if not target_li:
                            continue
                        if target_li.gl_account:
                            continue

                        gl_account_identifier = cls_item.get('gl_account')
                        resolved_gl = None
                        if gl_account_identifier:
                            resolved_gl = DimAICGLAcct.objects.filter(
                                client_id=doc.monthly_accounting.client,
                                account_number=str(gl_account_identifier).strip()
                            ).first()
                        if resolved_gl:
                            target_li.gl_account = resolved_gl
                            updated_line_items.append(target_li)
                    except Exception as ie:
                        logger.error(f"Skipping classification item due to error: {ie}")

            # Bulk update classified line items
            if updated_line_items:
                MonthlyDocumentBankLineItem.objects.bulk_update(updated_line_items, ['gl_account'])
                logger.error(f"Classified {len(updated_line_items)} line items for document {document_id}")
            else:
                logger.error(f"No line items classified for document {document_id}")

            # Save document (optionally could track a classification timestamp/flag)
            doc.status = "classified"
            doc.save()

            logger.error(f"GL classification completed for document {document_id}")

        except Exception as e:
            logger.error(f"GL Classification failed for document {document_id}: {str(e)}")
            # Continue without classification - fields will remain null
            
    except MonthlyAccountingDocument.DoesNotExist:
        logger.error(f"MonthlyAccountingDocument with id {document_id} not found")
    except Exception as e:
        logger.error(f"Error in GL classification for document {document_id}: {str(e)}")
        raise
