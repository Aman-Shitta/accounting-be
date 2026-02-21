import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from celery import shared_task, chain
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Sum, Q

from aicounting.file_upload_helper import DocumentDebugStorage
from account.models import (
    MonthlyAccountingDocument,
    MonthlyDocumentBankLineItem
)
from agentic_doc.config import ParseConfig
from agentic_doc.parse import parse
from extractor.config_factory import DocumentConfig
from extractor.processor import MonthlyAccountingDocumentProcessor
from extractor.utils import split_pdf_to_pages
from user.models import DimAICReviewer

from account.models import ClassificationQueue
from extractor.services import GLClassificationService

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
        if doc.doc_type not in BANKING_DOCS:
            logger.error(
                f"Document type {doc.doc_type} doesn't require markdown pre-processing")
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
                logger.info(
                    f"Generating markdown for page {page_num}/{len(page_bytes_list)}")

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
                saved_path = default_storage.save(
                    markdown_path, markdown_content)

                markdown_url = default_storage.url(
                    saved_path, expire_minutes=10)

                markdown_pages.append({
                    "page_number": page_num,
                    "path": saved_path,
                    "url": markdown_url,
                    "size": len(page_markdown)
                })

                logger.info(
                    f"Saved markdown for page {page_num} to {saved_path}")

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
        logger.error(
            f"Error in markdown pre-processing for document {doc_id}: {str(e)}")
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
        result = processor.start_process(
            file_bytes, md=True, special_rules=special_rules)

        processing_time = time.time() - start_time
        logger.info(f"Document processing time: {processing_time} seconds")
        processor.__release_resources__()

        # Save processing output
        debug_storage = DocumentDebugStorage(doc)
        debug_storage.save_final_output(result, "processing_result.json")

        logger.info(
            f"Document {doc.id} processed successfully: {result.get('processing_stats', {})}")

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
def validate_control_totals_task(_previous_result=None, document_id: str = None):
    """
    Validate extracted control totals against line-item sums.

    Formula: beginning_balance − total_debits + total_credits == ending_balance

    Outcomes:
      • Balances match (or no control totals / already reviewed)
          → automatically chains to enqueue_classification_task
      • Mismatch detected
          → assigns a reviewer via round-robin, sets status to 'pending_review'

    Can be used standalone or chained after process_uploaded_document.
    The _previous_result parameter allows this to be used in a Celery chain.

    Args:
        _previous_result: Result from previous task in chain (ignored)
        document_id: MonthlyAccountingDocument ID (string)

    Returns:
        dict: Validation result with status
    """
    try:

        doc = MonthlyAccountingDocument.objects.get(
            id=document_id
        ).select_related(
            'monthly_accounting__client'
        )

        client_id = str(doc.monthly_accounting.client_id)

        # If a reviewer already approved this document, skip validation
        if doc.status == 'reviewed' or doc.monthly_accounting.client.allow_review == False:
            logger.info(
                f"Document {document_id} was approved by reviewer — "
                f"skipping control-total validation."
            )
            enqueue_classification_task.delay(document_id=document_id)
            return {
                "status": "skipped_validation",
                "doc_id": document_id,
                "client_id": client_id,
            }

        control_total = doc.control_item or {}

        if not control_total:
            logger.info(
                f"No control totals for document {document_id} — "
                f"proceeding to classification."
            )
            enqueue_classification_task.delay(document_id=document_id)
            return {
                "status": "skipped_validation",
                "reason": "no_control_totals",
                "doc_id": document_id,
                "client_id": client_id,
            }

        line_items = MonthlyDocumentBankLineItem.objects.filter(document=doc)
        sums = line_items.aggregate(
            total_debits=Sum('amount', filter=Q(transaction_type='debit')),
            total_credits=Sum('amount', filter=Q(transaction_type='credit')),
        )
        sum_debits = Decimal(str(sums['total_debits'] or 0))
        sum_credits = Decimal(str(sums['total_credits'] or 0))

        beginning_balance = Decimal(
            str(control_total.get('beginning_balance') or 0))
        expected_ending = Decimal(
            str(control_total.get('ending_balance') or 0))

        calculated_ending = beginning_balance - sum_debits + sum_credits

        if calculated_ending == expected_ending:
            logger.info(
                f"Control total validation passed for document {document_id}: "
                f"calculated={calculated_ending}, expected={expected_ending}"
            )
            enqueue_classification_task.delay(document_id=document_id)
            return {
                "status": "validation_passed",
                "doc_id": document_id,
                "client_id": client_id,
            }

        mismatch_details = {
            "beginning_balance": str(beginning_balance),
            "sum_debits": str(sum_debits),
            "sum_credits": str(sum_credits),
            "calculated_ending": str(calculated_ending),
            "expected_ending": str(expected_ending),
            "difference": str(
                (calculated_ending - expected_ending)
                .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            ),
        }

        _assign_reviewer_for_mismatch(doc, document_id, mismatch_details)

        return {
            "status": "pending_review",
            "doc_id": document_id,
            "client_id": client_id,
            "assigned_reviewer": (
                doc.assigned_reviewer.system_user.username
                if doc.assigned_reviewer else None
            ),
            "mismatch": mismatch_details,
        }

    except MonthlyAccountingDocument.DoesNotExist:
        logger.error(f"Document not found: {document_id}")
        return {"status": "error", "error": f"Document not found: {document_id}"}
    except Exception as e:
        logger.error(
            f"Control-total validation failed for document {document_id}: {e}",
            exc_info=True,
        )
        return {"status": "error", "error": str(e)}


def _assign_reviewer_for_mismatch(doc, document_id, mismatch_details):
    """
    Helper: set the document to 'pending_review', store mismatch details,
    and assign a reviewer via round-robin.
    """
    reviewer = DimAICReviewer.get_next_reviewer()

    doc.status = "pending_review"
    doc.balance_mismatch_details = mismatch_details

    if reviewer:
        doc.assigned_reviewer = reviewer
        logger.info(
            f"Document {document_id} assigned to reviewer "
            f"{reviewer.system_user.username} (id={reviewer.id})"
        )
    else:
        logger.warning(
            f"No verified reviewers available to assign document {document_id}"
        )

    doc.save()

    logger.warning(
        f"Control total mismatch for document {document_id}: {mismatch_details}"
    )


@shared_task
def enqueue_classification_task(_previous_result=None, document_id: str = None):
    """
    Enqueue a document for GL account classification.

    Adds the document to the ClassificationQueue so it can be picked up
    by the Celery Beat process_classification_queue_task (one-at-a-time
    per client).

    Can be called directly or chained after validate_control_totals_task.

    Args:
        _previous_result: Result from previous task in chain (ignored)
        document_id: MonthlyAccountingDocument ID (string)

    Returns:
        dict: Queue result with status
    """
    try:

        doc = MonthlyAccountingDocument.objects.get(id=document_id)
        client_id = str(doc.monthly_accounting.client_id)

        queue_item = ClassificationQueue.enqueue(
            document=doc,
            client_id=client_id,
        )

        logger.info(
            f"Document {document_id} queued for classification "
            f"(queue_id: {queue_item.id}, client: {client_id})"
        )

        return {
            "status": "queued",
            "doc_id": document_id,
            "queue_id": str(queue_item.id),
            "client_id": client_id,
        }

    except MonthlyAccountingDocument.DoesNotExist:
        logger.error(f"Document not found: {document_id}")
        return {"status": "error", "error": f"Document not found: {document_id}"}
    except Exception as e:
        logger.error(
            f"Failed to queue classification for document {document_id}: {e}",
            exc_info=True,
        )
        return {"status": "error", "error": str(e)}


@shared_task
def process_classification_queue_task():
    """
    Celery Beat task to process the classification queue.

    This task runs periodically and processes ONE pending classification
    per client. This ensures each client's assistant is only used by one
    task at a time.

    Returns:
        dict: Processing summary
    """
    # Get all clients with pending work
    pending_clients = ClassificationQueue.get_all_pending_clients()

    if not pending_clients:
        return {"status": "idle", "message": "No pending classifications"}

    results = []

    for client_id in pending_clients:
        # Get next item for this client (returns None if one is already processing)
        queue_item = ClassificationQueue.get_next_for_client(client_id)

        if not queue_item:
            # Already processing for this client, skip
            continue

        # Mark as processing
        queue_item.mark_processing()
        document_id = str(queue_item.document_id)

        try:
            logger.info(
                f"Processing classification queue item {queue_item.id} "
                f"for document {document_id} (client: {client_id})"
            )

            # Run the actual classification
            service = GLClassificationService.from_document_id(document_id)

            service.document.status = "classifying"
            service.document.save(update_fields=['status'])
            
            classified_count = service.classify_line_items()

            # Update document status
            doc = service.document
            doc.status = "classified"
            doc.save()

            # Mark queue item as completed
            queue_item.mark_completed()

            logger.info(
                f"Classification completed for document {document_id}: "
                f"{classified_count} items classified"
            )

            results.append({
                "queue_id": str(queue_item.id),
                "doc_id": document_id,
                "status": "completed",
                "classified_count": classified_count
            })

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Classification failed for document {document_id}: {error_msg}"
            )
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"{exc_type} in {fname}:{exc_tb.tb_lineno}")

            # Mark as failed (will retry if retries remaining)
            queue_item.mark_failed(error_msg)

            results.append({
                "queue_id": str(queue_item.id),
                "doc_id": document_id,
                "status": "failed",
                "error": error_msg,
                "will_retry": queue_item.status == ClassificationQueue.Status.PENDING
            })

    return {
        "status": "processed",
        "processed_count": len(results),
        "results": results
    }


def process_and_classify_document(doc_id: str, config_params: dict):
    """
    Convenience function to process a document through the full pipeline.

    Creates a Celery chain: extraction → control-total validation → classification

    Args:
        doc_id: MonthlyAccountingDocument ID
        config_params: Configuration dict

    Returns:
        Celery AsyncResult for the chain
    """
    task_chain = chain(
        process_uploaded_document.s(doc_id, config_params),
        validate_control_totals_task.s(document_id=doc_id)
    )
    return task_chain.apply_async()
