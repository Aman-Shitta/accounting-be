# System imports
import json
import logging
from pathlib import Path

# Third-party imports
from celery import shared_task
from django.conf import settings

# Local imports
from extractor.bank_statement.classify import GLClassifier
from extractor.bank_statement.processor import MonthlyAccountingDocumentProcessor
from extractor.bank_statement.prompter import Configuration

from .models.monthly_accounting_document_model import MonthlyAccountingDocument
from .models.monthly_document_line_models import (
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankCheckItem
)

logger = logging.getLogger(__name__)

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
            logger.error(f"Documentdoes not exist: {doc_id} invalid id")
            doc.upload_status = "failed"
            doc.save()
            return 

        # Check if file exists
        from django.core.files.storage import default_storage
        file_path = doc.file.name if doc.file else None

        if not file_path or not default_storage.exists(file_path):
            logger.error(f"File does not exist in Azure storage: {file_path}")
            doc.upload_status = "failed"
            doc.save()
            return

        # Get file content from Azure storage
        with default_storage.open(file_path, 'rb') as azure_file:
            pdf_bytes = azure_file.read()

        # Use the new MonthlyAccountingDocumentProcessor
        processor = MonthlyAccountingDocumentProcessor(doc, config)
        result = processor.process_document(pdf_bytes)

        
        # Save JSON output to Azure storage for reference
        import json
        from django.core.files.base import ContentFile
        
        output_json = json.dumps(result, indent=2, default=str)
        output_path = f"processed_output/{doc.doc_id}/processing_result.json"
        default_storage.save(output_path, ContentFile(output_json.encode('utf-8')))
        
        logger.info(f"Document {doc.doc_id} processed successfully: {result['processing_stats']}")


    except Exception as e:
        if doc:
            doc.upload_status = "failed"
            doc.save()
            logger.error(f"Error processing document {doc.doc_id}: {str(e)}")
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")
        raise


@shared_task
def classify_monthly_document_gl_accounts(document_id: str):
    """
    Classify GL accounts for line items in a MonthlyAccountingDocument
    
    Args:
        document_id: UUID string of the MonthlyAccountingDocument
    """
    from .models import DimAICGLAcct
    try:
        # Get the document
        doc = MonthlyAccountingDocument.objects.get(doc_id=document_id)
        
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
                        vector_store_ids=vector_store_ids
                    )
                    classified_pages_data = classifier_assistant.classify(document_id) or {}
                except Exception as e:
                    logger.warning(f"Assistant classification call failed for document {document_id}: {e}")
            
            
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
                        logger.debug(f"Skipping classification item due to error: {ie}")

            # Bulk update classified line items
            if updated_line_items:
                MonthlyDocumentBankLineItem.objects.bulk_update(updated_line_items, ['gl_account'])
                logger.info(f"Classified {len(updated_line_items)} line items for document {document_id}")
            else:
                logger.info(f"No line items classified for document {document_id}")

            # Save document (optionally could track a classification timestamp/flag)
            doc.upload_status = "classified"
            doc.save()

            logger.info(f"GL classification completed for document {document_id}")

        except Exception as e:
            logger.warning(f"GL Classification failed for document {document_id}: {str(e)}")
            # Continue without classification - fields will remain null
            
    except MonthlyAccountingDocument.DoesNotExist:
        logger.error(f"MonthlyAccountingDocument with id {document_id} not found")
    except Exception as e:
        logger.error(f"Error in GL classification for document {document_id}: {str(e)}")
        raise
