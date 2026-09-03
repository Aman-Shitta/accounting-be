import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from celery import shared_task, chain
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Sum, Q

from aicounting.file_upload_helper import DocumentDebugStorage
from account.models import (
    ClassificationQueue,
    MonthlyAccountingDocument,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankKeyItem,
    MonthlyDocumentBankCheckItem,
)
from extractor.classification.service import GLClassificationService
from extractor.constants import DocumentType
from extractor.pipeline_registry import get_pipeline_class
from extractor.utils import split_pdf_to_pages
from user.models import DimAICReviewer

logger = logging.getLogger(__name__)



def _clear_existing_extraction(doc: MonthlyAccountingDocument) -> None:
    """Remove prior extracted data so the pipeline can re-run cleanly."""
    MonthlyDocumentBankKeyItem.objects.filter(document=doc).delete()
    MonthlyDocumentBankLineItem.objects.filter(document=doc).delete()
    MonthlyDocumentBankCheckItem.objects.filter(document=doc).delete()


def _fail(
    doc: Optional[MonthlyAccountingDocument], error: str
) -> dict[str, Any]:
    """Mark doc failed (if present) and return a uniform error payload."""
    if doc:
        doc.status = "failed"
        doc.save(update_fields=["status"])
    return {"status": "error", "error": error}


@shared_task
def process_document_task(doc_id: str) -> dict[str, Any]:
    """
    Single Celery entry point for document extraction.

    Fetches the document + file, resolves the pipeline by doc_type, runs
    it, and updates document status. Returns a result dict that can be
    chained into ``validate_control_totals_task``.
    """
    doc: Optional[MonthlyAccountingDocument] = (
        MonthlyAccountingDocument.objects.filter(id=doc_id).first()
    )
    if not doc:
        logger.error(f"Document does not exist: {doc_id}")
        return {"status": "error", "error": "Document not found"}

    file_path = doc.file.name if doc.file else None
    if not file_path or not default_storage.exists(file_path):
        logger.error(f"File does not exist in Azure storage: {file_path}")
        return _fail(doc, "File not found")

    try:
        with default_storage.open(file_path, "rb") as azure_file:
            file_bytes = azure_file.read()

        _clear_existing_extraction(doc)

        pipeline_cls = get_pipeline_class(doc.doc_type)
        pipeline = pipeline_cls(doc)

        try:
            debug_storage = DocumentDebugStorage(doc)
            pipeline.set_debug_storage(debug_storage)
        except Exception as e:
            logger.warning(f"Failed to initialize debug storage: {e}")
            debug_storage = None

        start_time = time.time()
        result = pipeline.process_document(file_bytes)
        processing_time = time.time() - start_time
        logger.info(
            f"Document {doc.id} processing time: {processing_time:.2f}s"
        )

        if result.get("status") != "success":
            error_msg = result.get("error", "Unknown error during processing")
            logger.error(
                f"Pipeline processing failed for document {doc_id}: {error_msg}"
            )
            return _fail(doc, error_msg)

        doc.status = "extracted"
        doc.save(update_fields=["status"])

        if debug_storage:
            debug_storage.save_final_output(result, "processing_result.json")

        stats = result.get("processing_stats", {})
        logger.info(f"Document {doc.id} processed successfully: {stats}")

        return {
            "status": "success",
            "doc_id": str(doc.id),
            "processing_time": processing_time,
            "stats": stats,
        }

    except Exception as e:
        logger.error(
            f"Error processing document {doc.id}: {e}", exc_info=True
        )
        return _fail(doc, str(e))


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

    Can be used standalone or chained after process_document_task.
    The _previous_result parameter allows this to be used in a Celery chain.

    Args:
        _previous_result: Result from previous task in chain (ignored)
        document_id: MonthlyAccountingDocument ID (string)

    Returns:
        dict: Validation result with status
    """
    try:

        doc = (
            MonthlyAccountingDocument.objects
            .select_related('monthly_accounting__client')
            .get(id=document_id)
        )

        client_id = str(doc.monthly_accounting.client_id)

        # If a reviewer already approved this document, skip validation
        if doc.status == 'reviewed' or not doc.monthly_accounting.client.allow_review:
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

            will_retry = queue_item.status == ClassificationQueue.Status.PENDING

            results.append({
                "queue_id": str(queue_item.id),
                "doc_id": document_id,
                "status": "failed",
                "error": error_msg,
                "will_retry": will_retry
            })

    return {
        "status": "processed",
        "processed_count": len(results),
        "results": results
    }
