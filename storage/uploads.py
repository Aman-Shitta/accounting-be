"""
``upload_to`` callables and processing-artifact storage.

Every ``FileField`` in the project routes through one of the ``upload_to_*``
functions here so the on-disk layout stays consistent and auditable. See
:mod:`storage.paths` for the layout itself.

Usage::

    models.FileField(upload_to=upload_to_input_files_folder)
"""

import json
import logging
import traceback
from datetime import datetime
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from storage.paths import DocumentPathBuilder

logger = logging.getLogger(__name__)


def get_path_builder(instance: Any) -> DocumentPathBuilder | None:
    """
    Build a :class:`DocumentPathBuilder` from any model instance that can
    reach a client, directly or through its accounting period.

    Returns ``None`` when the instance has no client, in which case callers
    fall back to a flat path.
    """
    client = getattr(instance, "client", None)

    if client is None:
        period = getattr(instance, "monthly_accounting", None) or getattr(
            instance, "period", None
        )
        client = getattr(period, "client", None)

    if client is None:
        return None

    # `customer` today, `firm` after the tenancy rename — accept either.
    firm = getattr(client, "firm", None) or getattr(client, "customer", None)
    if firm is None:
        return None

    return DocumentPathBuilder(
        firm_id=firm.id,
        firm_name=getattr(firm, "name", None) or getattr(firm, "customer_name", ""),
        client_id=client.id,
        client_name=getattr(client, "client_name", "") or getattr(client, "name", ""),
    )


def _timestamped(filename: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if "." in filename:
        name, ext = filename.rsplit(".", 1)
        return f"{stamp}_{name}.{ext}"
    return f"{stamp}_{filename}"


# =============================================================================
# upload_to callables
# =============================================================================

def upload_to_customer_client_folder(instance, filename):
    """Client reference documents — COA, vendor list, GL history."""
    builder = get_path_builder(instance)
    if builder:
        return builder.client_documents_path(filename)
    return f"client_documents/{_timestamped(filename)}"


def upload_to_je_export_folder(instance, filename):
    """Generated journal-entry exports."""
    builder = get_path_builder(instance)
    if builder:
        return builder.je_template_path(filename)
    return f"je_templates/{_timestamped(filename)}"


def upload_to_input_files_folder(instance, filename):
    """Sample or reference file attached to a configured document source."""
    builder = get_path_builder(instance)
    if builder:
        return builder.input_files_path(filename)
    return f"input_files/{_timestamped(filename)}"


def upload_to_montly_accounting_folder(instance, filename):
    """The document a user uploads for a period."""
    builder = get_path_builder(instance)
    doc_id = str(getattr(instance, "id", "unknown"))
    if builder:
        return builder.period_document_path(filename, doc_id=doc_id)
    return f"accounting/{doc_id}/{_timestamped(filename)}"


def upload_to_monthly_accounting_snapshot_folder(instance, filename):
    """
    Legacy: per-period copies of source files.

    Config versioning replaces snapshots in Phase 5 and nothing will write
    here afterwards; kept only so historical migrations stay importable.
    """
    builder = get_path_builder(instance)
    if builder:
        return builder.je_template_path(filename)
    return f"accounting_snapshots/{_timestamped(filename)}"


# =============================================================================
# Processing artifacts
# =============================================================================

class DocumentDebugStorage:
    """
    Writes the intermediate output of each pipeline stage alongside the
    document, so an extraction can be audited after the fact.

    Every method returns the saved path, or ``None`` if the write failed —
    artifact storage is best-effort and never blocks extraction.
    """

    def __init__(self, document):
        self.document = document
        self.doc_id = str(document.id)
        self._paths = get_path_builder(document)

        if not self._paths:
            logger.warning(
                f"No path builder for document {self.doc_id}; "
                f"artifacts fall back to a flat folder"
            )

    def _fallback(self, stage: str, filename: str) -> str:
        return f"processing_artifacts/{self.doc_id}/{stage}/{filename}"

    def _save_file(self, content: bytes | str, path: str) -> str | None:
        try:
            if isinstance(content, str):
                content = content.encode("utf-8")
            saved_path = default_storage.save(path, ContentFile(content))
            logger.info(f"Artifact saved: {saved_path}")
            return saved_path
        except Exception as e:
            logger.error(f"Failed to save artifact to {path}: {e}")
            return None

    def _save_json(self, data: Any, path: str) -> str | None:
        try:
            return self._save_file(json.dumps(data, indent=2, default=str), path)
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize artifact for {path}: {e}")
            return None

    def save_raw_input(self, file_bytes: bytes, original_filename: str) -> str | None:
        path = (
            self._paths.artifact_raw_input_path(self.doc_id, original_filename)
            if self._paths
            else self._fallback("01_raw_input", original_filename)
        )
        return self._save_file(file_bytes, path)

    def save_parsed_markdown(self, markdown: str, filename: str = "full_document.md") -> str | None:
        path = (
            self._paths.artifact_ocr_path(self.doc_id, filename)
            if self._paths
            else self._fallback("02_ocr_output", filename)
        )
        return self._save_file(markdown, path)

    def save_extracted_data(self, data: dict, filename: str = "extracted_data.json") -> str | None:
        path = (
            self._paths.artifact_extractor_path(self.doc_id, filename)
            if self._paths
            else self._fallback("03_extractor_ai", filename)
        )
        return self._save_json(data, path)

    def save_final_output(self, output: dict, filename: str = "final_output.json") -> str | None:
        path = (
            self._paths.artifact_final_summary_path(self.doc_id, filename)
            if self._paths
            else self._fallback("07_final_summary", filename)
        )
        return self._save_json(output, path)

    def save_error_log(self, error: Exception, context: dict = None) -> str | None:
        return self.save_final_output(
            {
                "document_id": self.doc_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat(),
                "context": context or {},
            },
            "error_log.json",
        )

    def artifacts_folder(self) -> str:
        if self._paths:
            return self._paths.artifacts_folder(self.doc_id)
        return f"processing_artifacts/{self.doc_id}"
