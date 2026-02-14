"""
File Upload Helper Functions for AICounting Project

This module contains all the file upload path generation functions used across different models.
It provides a centralized location to manage file upload structures and naming conventions.

All upload functions follow the pattern:
- Centralized path generation via AzureBlobPathBuilder
- Organized folder structure based on entity relationships
- Timestamped filenames to avoid conflicts

Usage:
    models.FileField(upload_to=upload_to_input_files_folder)
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional, Union

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from aicounting.azure_storage_paths import AzureBlobPathBuilder, AzureStoragePathConstants

logger = logging.getLogger(__name__)


def get_blob_path_builder(instance: Any) -> Optional[AzureBlobPathBuilder]:
    """
    Centralized helper to extract Customer/Client info from ANY model instance
    and return an AzureBlobPathBuilder.

    Traverses common relationships (client, customer, monthly_accounting, calculations).
    """
    try:
        client = None
        customer = None

        # Direct relationships
        if hasattr(instance, 'client'):
            client = instance.client
        elif hasattr(instance, 'customer'):
            # Some models might link direct to customer, but usually we need client for full path
            customer = instance.customer
            # If strictly customer based, we might lack client_id.
            # The Builder requires both. If no client, we can't use the standard builder
            # effectively without a dummy client structure or a different builder.
            # However, most file uploads in this system seem client-centric.
            pass

        # Indirect relationships (common in this codebase)
        elif hasattr(instance, 'monthly_accounting') and hasattr(instance.monthly_accounting, 'client'):
            client = instance.monthly_accounting.client

        # If we found a client, we get the customer from it
        if client:
            customer = client.customer

        if client and customer:
            return AzureBlobPathBuilder(
                customer_id=customer.id,
                customer_name=customer.customer_name or "Unknown",
                client_id=client.id,
                client_name=client.client_name or "Unknown"
            )
    except Exception as e:
        logger.warning(
            f"Failed to create AzureBlobPathBuilder for {type(instance)}: {e}")

    return None


def _add_timestamp_to_filename(filename):
    """Add timestamp to filename to avoid conflicts"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
    return f"{timestamp}_{name}.{ext}" if ext else f"{timestamp}_{name}"


# =============================================================================
# DJANGO MODEL UPLOAD_TO CALLBACKS
# =============================================================================

def upload_to_customer_client_folder(instance, filename):
    """
    Upload to: .../client_documents/YYYY-MM-DD/filename
    Used by: DimAicClientDocument
    """
    builder = get_blob_path_builder(instance)
    if builder:
        return builder.client_documents_path(filename, add_timestamp=True)
    return f"client_documents/{_add_timestamp_to_filename(filename)}"


def upload_to_je_export_folder(instance, filename):
    """
    Upload to: .../je_templates/YYYY-MM-DD/filename
    (Note: Variable name says 'export' but often used for templates/outputs)
    """
    builder = get_blob_path_builder(instance)
    if builder:
        return builder.je_template_path(filename, add_timestamp=True)
    return f"je_templates/{_add_timestamp_to_filename(filename)}"


def upload_to_input_files_folder(instance, filename):
    """
    Upload to: .../input_files/YYYY-MM-DD/filename
    Used by: DimAicInputFiles
    """
    builder = get_blob_path_builder(instance)
    if builder:
        return builder.input_files_path(filename, add_timestamp=True)
    return f"input_files/{_add_timestamp_to_filename(filename)}"


def upload_to_montly_accounting_folder(instance, filename):
    """
    Upload to: .../accounting/YYYY-MM-DD/<doc_id>/filename
    Used by: MonthlyAccountingDocument (Input File)
    """
    builder = get_blob_path_builder(instance)
    doc_id = str(getattr(instance, 'id', 'unknown'))

    if builder:
        return builder.monthly_accounting_document_path(filename, doc_id=doc_id, add_timestamp=True)
    return f"accounting/{doc_id}/{_add_timestamp_to_filename(filename)}"


def upload_to_monthly_accounting_snapshot_folder(instance, filename):
    """
    Upload to: .../accounting_snapshots/YYYY-MM-DD/filename
    Used by: Snapshots
    """
    builder = get_blob_path_builder(instance)
    if builder:
        return builder.accounting_snapshots_path(filename, add_timestamp=True)
    return f"accounting_snapshots/{_add_timestamp_to_filename(filename)}"


# =============================================================================
# SPECIALIZED / LEGACY HANDLERS
# =============================================================================

def upload_to_documents_folder(instance, filename):
    """Generic document upload (non-client specific)"""
    doc_type = getattr(instance, 'doc_typ', 'general')
    doc_id = getattr(instance, 'id', 'unknown')
    timestamped_filename = _add_timestamp_to_filename(filename)
    return f"documents/{doc_type}/{doc_id}/{timestamped_filename}"


def upload_to_processed_documents_folder(instance, filename):
    """
    Upload to processed documents.
    Logic tries to map to new structure if possible.
    """
    builder = get_blob_path_builder(instance)
    doc_id = str(getattr(instance, 'id', 'unknown'))

    if builder:
        return builder.processed_document_path(doc_id, filename, add_timestamp=True)
    return f"processed_documents/{_add_timestamp_to_filename(filename)}"


def upload_to_templates_folder(instance, filename):
    template_type = getattr(instance, 'template_type', 'general')
    template_id = getattr(instance, 'id', 'default')
    timestamped_filename = _add_timestamp_to_filename(filename)
    today = datetime.now().strftime("%Y-%m-%d")
    return f"templates/{template_type}/{template_id}/{today}/{timestamped_filename}"


def upload_to_reports_folder(instance, filename):
    report_type = getattr(instance, 'report_type', 'general')
    current_date = datetime.now()
    year = current_date.year
    month = current_date.strftime("%m")
    timestamped_filename = _add_timestamp_to_filename(filename)
    return f"reports/{report_type}/{year}/{month}/{timestamped_filename}"


def upload_to_backups_folder(instance, filename):
    backup_type = getattr(instance, 'backup_type', 'general')
    current_date = datetime.now()
    year = current_date.year
    month = current_date.strftime("%m")
    day = current_date.strftime("%d")
    timestamped_filename = _add_timestamp_to_filename(filename)
    return f"backups/{backup_type}/{year}/{month}/{day}/{timestamped_filename}"


def upload_to_temp_folder(instance, filename):
    session_id = getattr(instance, 'session_id', 'default')
    today = datetime.now().strftime("%Y-%m-%d")
    timestamped_filename = _add_timestamp_to_filename(filename)
    return f"temp/{session_id}/{today}/{timestamped_filename}"


def upload_to_montly_accounting_path_folder(document, path, filename):
    """
    Legacy helper for flexible paths.
    Tries to route to new builder methods where possible.
    """
    builder = get_blob_path_builder(document)
    if not builder:
        return f"monthly_accounting/{path}/{_add_timestamp_to_filename(filename)}"

    # Heuristic routing based on 'path' string
    if 'processed' in path:
        doc_id = str(document.id)
        return builder.processed_document_path(doc_id, filename, add_timestamp=True)

    # Default to document path
    doc_id = str(document.id)
    return builder.monthly_accounting_document_path(filename, doc_id, add_timestamp=True)


# =============================================================================
# FILE UTILS & VALIDATION
# =============================================================================

def get_file_extension(filename):
    return filename.rsplit('.', 1)[1] if '.' in filename else ''


def is_allowed_file_type(filename, allowed_extensions):
    extension = get_file_extension(filename).lower()
    return extension in [ext.lower() for ext in allowed_extensions]


def get_file_size_display(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f}{size_names[i]}"


ALLOWED_DOCUMENT_EXTENSIONS = [
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv']
ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff']
ALLOWED_BANK_STATEMENT_EXTENSIONS = ['pdf', 'csv', 'xls', 'xlsx', 'txt']


def validate_document_file(filename):
    return is_allowed_file_type(filename, ALLOWED_DOCUMENT_EXTENSIONS)


def validate_image_file(filename):
    return is_allowed_file_type(filename, ALLOWED_IMAGE_EXTENSIONS)


def validate_bank_statement_file(filename):
    return is_allowed_file_type(filename, ALLOWED_BANK_STATEMENT_EXTENSIONS)


# =============================================================================
# DEBUG / ARTIFACT STORAGE
# =============================================================================

class DocumentDebugStorage:
    """
    Helper to save processing artifacts (formerly debug files).
    Now routes to 'processing_artifacts' via AzureBlobPathBuilder.
    """

    def __init__(self, document):
        self.document = document
        self.doc_id = str(document.id)
        self._path_builder = get_blob_path_builder(document)

        if not self._path_builder:
            logger.warning(
                f"Could not initialize path builder for document {self.doc_id}")

    def _save_file(self, content: Union[bytes, str], path: str, content_type: str = "application/octet-stream") -> Optional[str]:
        try:
            if isinstance(content, str):
                content = content.encode('utf-8')

            content_file = ContentFile(content)
            saved_path = default_storage.save(path, content_file)
            logger.info(f"Artifact saved: {saved_path}")
            return saved_path
        except Exception as e:
            logger.error(f"Failed to save artifact to {path}: {e}")
            return None

    def _save_json(self, data: Any, path: str) -> Optional[str]:
        try:
            json_content = json.dumps(data, indent=2, default=str)
            return self._save_file(json_content, path, "application/json")
        except Exception as e:
            logger.error(f"Failed to save JSON to {path}: {e}")
            return None

    # --- Specific Writer Methods ---

    def save_raw_input(self, file_bytes: bytes, original_filename: str) -> Optional[str]:
        if self._path_builder:
            path = self._path_builder.artifact_raw_input_path(
                self.doc_id, original_filename)
        else:
            path = f"debug_files/{self.doc_id}/01_raw_input/{original_filename}"
        return self._save_file(file_bytes, path)

    def save_parsed_markdown(self, markdown_content: str, filename: str = "full_document.md") -> Optional[str]:
        if self._path_builder:
            path = self._path_builder.artifact_ocr_path(self.doc_id, filename)
        else:
            path = f"debug_files/{self.doc_id}/02_ocr_output/{filename}"
        return self._save_file(markdown_content, path, "text/markdown")

    def save_page_markdown(self, page_num: int, markdown_content: str) -> Optional[str]:
        filename = f"page_{page_num:03d}.md"
        return self.save_parsed_markdown(markdown_content, filename)

    def save_extracted_data(self, extracted_data: Dict, filename: str = "extracted_data.json") -> Optional[str]:
        if self._path_builder:
            path = self._path_builder.artifact_landing_ai_path(
                self.doc_id, filename)
        else:
            path = f"debug_files/{self.doc_id}/03_landing_ai/{filename}"
        return self._save_json(extracted_data, path)

    def save_extracted_metadata(self, metadata: Dict, filename: str = "extraction_metadata.json") -> Optional[str]:
        return self.save_extracted_data(metadata, filename)

    def save_rectified_data(self, rectified_data: Dict, filename: str = "rectified_data.json") -> Optional[str]:
        if self._path_builder:
            path = self._path_builder.artifact_rectification_path(
                self.doc_id, filename)
        else:
            path = f"debug_files/{self.doc_id}/06_rectification/{filename}"
        return self._save_json(rectified_data, path)

    def save_rectifier_items(self, rectifier_items: list, filename: str = "rectifier_items.json") -> Optional[str]:
        return self.save_rectified_data({"rectifier_items": rectifier_items}, filename)

    def save_classified_data(self, classified_data: Dict, filename: str = "classified_data.json") -> Optional[str]:
        # Using Rectification folder for classification results as they are often paired stages
        if self._path_builder:
            path = self._path_builder.artifact_rectification_path(
                self.doc_id, filename)
        else:
            path = f"debug_files/{self.doc_id}/06_rectification/{filename}"
        return self._save_json(classified_data, path)

    def save_final_output(self, final_output: Dict, filename: str = "final_output.json") -> Optional[str]:
        if self._path_builder:
            path = self._path_builder.artifact_final_summary_path(
                self.doc_id, filename)
        else:
            path = f"debug_files/{self.doc_id}/07_final_summary/{filename}"
        return self._save_json(final_output, path)

    def save_processing_summary(self, summary: Dict) -> Optional[str]:
        from datetime import datetime
        summary_with_meta = {
            "document_id": self.doc_id,
            "document_type": getattr(self.document, 'doc_type', 'unknown'),
            "saved_at": datetime.now().isoformat(),
            "status": getattr(self.document, 'status', 'unknown'),
            **summary
        }
        return self.save_final_output(summary_with_meta, "processing_summary.json")

    def save_error_log(self, error: Exception, context: Dict = None) -> Optional[str]:
        import traceback
        error_data = {
            "document_id": self.doc_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now().isoformat(),
            "context": context or {}
        }
        return self.save_final_output(error_data, "error_log.json")

    def get_debug_folder_path(self) -> str:
        if self._path_builder:
            return self._path_builder.debug_base_path(self.doc_id)
        return f"debug_files/{self.doc_id}"
