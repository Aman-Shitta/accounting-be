"""
Document processing pipeline.

    upload → process_document_task
           → validate_control_totals_task
           → enqueue_classification_task  → ClassificationJob
           → process_classification_queue_task  [celery beat]

Classification is queued rather than run inline because a client's OpenAI
assistant cannot safely serve two concurrent runs; the beat task drains the
queue one job per client at a time.
"""

import logging
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from celery import shared_task
from django.core.files.storage import default_storage
from django.db.models import Q, Sum

from extractor.classification.service import (
    ClassifierUnavailableError,
    DocumentNotFoundError,
    GLClassificationService,
)
from extractor.pipeline_registry import UnsupportedDocTypeError, get_pipeline_class
from storage.uploads import DocumentDebugStorage
from v1.periods.models import (
    ClassificationJob,
    PeriodCheckDetail,
    PeriodDocument,
    PeriodFieldValue,
    PeriodTransaction,
)
from v1.tenancy.models import FirmMembership

logger = logging.getLogger(__name__)


def _clear_previous_extraction(doc: PeriodDocument) -> None:
    """Re-uploading a document replaces its extraction rather than adding to it."""
    PeriodCheckDetail.objects.filter(document=doc).delete()
    PeriodTransaction.objects.filter(document=doc).delete()
    PeriodFieldValue.objects.filter(document=doc).delete()


def _fail(doc: PeriodDocument, reason: str) -> dict[str, Any]:
    doc.mark_failed(reason)
    return {"status": "error", "doc_id": str(doc.id), "error": reason}


@shared_task
def process_document_task(doc_id) -> dict[str, Any]:
    """Read the uploaded file, run the pipeline for its type, persist results."""
    doc: PeriodDocument | None = (
        PeriodDocument.objects.filter(id=doc_id)
        .select_related("period__client", "document_source")
        .first()
    )
    if not doc:
        logger.error(f"Document does not exist: {doc_id}")
        return {"status": "error", "error": "Document not found"}

    file_path = doc.file.name if doc.file else None
    if not file_path or not default_storage.exists(file_path):
        logger.error(f"File missing from storage: {file_path}")
        return _fail(doc, "File not found")

    try:
        pipeline_cls = get_pipeline_class(doc.extraction_mode)
    except UnsupportedDocTypeError as e:
        return _fail(doc, str(e))

    doc.status = PeriodDocument.Status.EXTRACTING
    doc.save(update_fields=["status", "updated_at"])

    try:
        with default_storage.open(file_path, "rb") as handle:
            file_bytes = handle.read()

        _clear_previous_extraction(doc)

        pipeline = pipeline_cls(doc)

        debug_storage = None
        try:
            debug_storage = DocumentDebugStorage(doc)
            pipeline.set_debug_storage(debug_storage)
        except Exception as e:
            # Artifact storage is best-effort; extraction still runs without it.
            logger.warning(f"Could not initialise artifact storage: {e}")

        started = time.time()
        result = pipeline.process_document(file_bytes)
        elapsed = time.time() - started

        if result.get("status") != "success":
            error = result.get("error", "Unknown error during processing")
            logger.error(f"Pipeline failed for document {doc_id}: {error}")
            return _fail(doc, error)

        doc.status = PeriodDocument.Status.EXTRACTED
        doc.save(update_fields=["status", "updated_at"])

        if debug_storage:
            debug_storage.save_final_output(result, "processing_result.json")

        stats = result.get("processing_stats", {})
        logger.info(f"Document {doc.id} processed in {elapsed:.2f}s: {stats}")

        return {
            "status": "success",
            "doc_id": str(doc.id),
            "processing_time": elapsed,
            "stats": stats,
        }

    except Exception as e:
        logger.error(f"Error processing document {doc.id}: {e}", exc_info=True)
        return _fail(doc, str(e))


@shared_task
def validate_control_totals_task(_previous_result=None, document_id=None) -> dict[str, Any]:
    """
    Check the extracted transactions against the statement's own control
    totals:

        beginning balance − debits + credits == ending balance

    On a match (or when there is nothing to check) the document goes straight
    to classification. On a mismatch it is assigned to a reviewer instead.
    """
    doc = (
        PeriodDocument.objects.filter(id=document_id)
        .select_related("period__client")
        .first()
    )
    if not doc:
        logger.error(f"Document not found: {document_id}")
        return {"status": "error", "error": f"Document not found: {document_id}"}

    client = doc.period.client

    def _skip(reason: str) -> dict[str, Any]:
        logger.info(f"Skipping control-total validation for {document_id}: {reason}")
        enqueue_classification_task.delay(document_id=document_id)
        return {
            "status": "skipped_validation",
            "reason": reason,
            "doc_id": str(document_id),
            "client_id": client.id,
        }

    if doc.status == PeriodDocument.Status.REVIEWED:
        return _skip("already reviewed")
    if not client.allow_review:
        return _skip("review not enabled for this client")

    control_totals = doc.control_totals or {}
    if not control_totals:
        return _skip("no control totals extracted")

    sums = PeriodTransaction.objects.filter(document=doc).aggregate(
        debits=Sum("amount", filter=Q(direction=PeriodTransaction.Direction.DEBIT)),
        credits=Sum("amount", filter=Q(direction=PeriodTransaction.Direction.CREDIT)),
    )
    debits = Decimal(str(sums["debits"] or 0))
    credits = Decimal(str(sums["credits"] or 0))

    opening = Decimal(str(control_totals.get("beginning_balance") or 0))
    expected_closing = Decimal(str(control_totals.get("ending_balance") or 0))
    calculated_closing = opening - debits + credits

    if calculated_closing == expected_closing:
        logger.info(
            f"Control totals balance for document {document_id}: {calculated_closing}"
        )
        enqueue_classification_task.delay(document_id=document_id)
        return {
            "status": "validation_passed",
            "doc_id": str(document_id),
            "client_id": client.id,
        }

    mismatch = {
        "beginning_balance": str(opening),
        "sum_debits": str(debits),
        "sum_credits": str(credits),
        "calculated_ending": str(calculated_closing),
        "expected_ending": str(expected_closing),
        "difference": str(
            (calculated_closing - expected_closing).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        ),
    }
    _assign_reviewer(doc, mismatch)

    return {
        "status": "pending_review",
        "doc_id": str(document_id),
        "client_id": client.id,
        "assigned_reviewer": (
            doc.assigned_reviewer.user.email if doc.assigned_reviewer else None
        ),
        "mismatch": mismatch,
    }


def _assign_reviewer(doc: PeriodDocument, mismatch: dict) -> None:
    """
    Park the document for review and hand it to the next reviewer at the firm
    that owns it. A firm with no reviewers leaves the document unassigned but
    still parked, so it shows up in that firm's queue rather than vanishing.
    """
    reviewer = FirmMembership.next_reviewer(doc.period.client.firm)

    doc.status = PeriodDocument.Status.PENDING_REVIEW
    doc.balance_mismatch_details = mismatch
    doc.assigned_reviewer = reviewer
    doc.save(
        update_fields=[
            "status",
            "balance_mismatch_details",
            "assigned_reviewer",
            "updated_at",
        ]
    )

    if reviewer:
        logger.info(f"Document {doc.id} assigned to reviewer {reviewer.user.email}")
    else:
        logger.warning(
            f"No reviewer at {doc.period.client.firm.name} available for "
            f"document {doc.id}; it is parked unassigned"
        )

    logger.warning(f"Control total mismatch for document {doc.id}: {mismatch}")


@shared_task
def enqueue_classification_task(_previous_result=None, document_id=None) -> dict[str, Any]:
    """Queue a document for GL classification."""
    doc = (
        PeriodDocument.objects.filter(id=document_id)
        .select_related("period__client")
        .first()
    )
    if not doc:
        logger.error(f"Document not found: {document_id}")
        return {"status": "error", "error": f"Document not found: {document_id}"}

    job = ClassificationJob.enqueue(doc)
    logger.info(
        f"Document {document_id} queued for classification "
        f"(job {job.id}, client {job.client_id})"
    )

    return {
        "status": "queued",
        "doc_id": str(document_id),
        "job_id": job.id,
        "client_id": job.client_id,
    }


@shared_task
def process_classification_queue_task() -> dict[str, Any]:
    """
    Drain the classification queue, at most one job per client per tick.

    Serializing per client keeps two runs from sharing one OpenAI assistant.
    """
    pending_clients = ClassificationJob.pending_client_ids()
    if not pending_clients:
        return {"status": "idle", "message": "No pending classifications"}

    results = []

    for client_id in pending_clients:
        job = ClassificationJob.next_for_client(client_id)
        if job is None:
            # A job for this client is already running.
            continue

        job.mark_processing()
        document_id = job.document_id

        try:
            logger.info(f"Classifying document {document_id} (client {client_id})")

            service = GLClassificationService.from_document_id(document_id)
            service.document.status = PeriodDocument.Status.CLASSIFYING
            service.document.save(update_fields=["status", "updated_at"])

            count = service.classify_transactions()

            service.document.status = PeriodDocument.Status.CLASSIFIED
            service.document.save(update_fields=["status", "updated_at"])
            job.mark_completed()

            logger.info(f"Classified {count} transactions on document {document_id}")
            results.append(
                {
                    "job_id": job.id,
                    "doc_id": str(document_id),
                    "status": "completed",
                    "classified_count": count,
                }
            )

        except (ClassifierUnavailableError, DocumentNotFoundError) as e:
            # Retrying will not help: the profile or the document is missing.
            logger.error(f"Classification cannot run for {document_id}: {e}")
            job.attempts = job.max_attempts
            job.mark_failed(str(e))
            results.append(
                {
                    "job_id": job.id,
                    "doc_id": str(document_id),
                    "status": "failed",
                    "error": str(e),
                    "will_retry": False,
                }
            )

        except Exception as e:
            logger.error(
                f"Classification failed for document {document_id}: {e}", exc_info=True
            )
            job.mark_failed(str(e))
            results.append(
                {
                    "job_id": job.id,
                    "doc_id": str(document_id),
                    "status": "failed",
                    "error": str(e),
                    "will_retry": job.will_retry,
                }
            )

    return {"status": "processed", "processed_count": len(results), "results": results}
