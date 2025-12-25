"""
File Upload Helper Functions for AICounting Project

This module contains all the file upload path generation functions used across different models.
It provides a centralized location to manage file upload structures and naming conventions.

All upload functions follow the pattern:
- Organized folder structure based on entity relationships
- Timestamped filenames to avoid conflicts
- Consistent path formats across the application

IMPORTANT: This module now uses the unified AzureBlobPathBuilder for trackable paths.
See aicounting.azure_storage_paths for the new standardized structure.

New Structure:
    customer_<customer_name>_<customer_id>/
        client_<client_name>_<client_id>/
            input_files/YYYY-MM-DD/
            je_exports/YYYY-MM-DD/
            monthly_accounting/YYYY-MM-DD/
            monthly_accounting/documents/doc_id/
            monthly_accounting/documents/doc_id/markdown/
            monthly_accounting/processed_documents/doc_id/
            monthly_accounting/processed_documents/processed_output/
"""

from datetime import datetime
import os
from aicounting.azure_storage_paths import AzureBlobPathBuilder, AzureStoragePathConstants


def _add_timestamp_to_filename(filename):
    """
    Add timestamp to filename to avoid conflicts
    
    Args:
        filename (str): Original filename
        
    Returns:
        str: Timestamped filename
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
    return f"{timestamp}_{name}.{ext}" if ext else f"{timestamp}_{name}"


def upload_to_customer_client_folder(instance, filename):
    """
    Generate upload path for client documents.
    Structure: customer_<name>_<id>/client_<name>_<id>/client_documents/DD-MM-YYYY/filename
    """
    try:
        builder = AzureBlobPathBuilder(
            customer_id=instance.client.customer.id,
            customer_name=instance.client.customer.customer_name or "Unknown",
            client_id=instance.client.id,
            client_name=instance.client.client_name or "Unknown"
        )
        return builder.client_documents_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        return f"client_documents/{_add_timestamp_to_filename(filename)}"

def upload_to_je_export_folder(instance, filename):
    """
    Generate upload path for JE export files.
    Structure: customer_<name>_<id>/client_<name>_<id>/accounting/output_files/DD-MM-YYYY/filename
    """
    try:
        builder = AzureBlobPathBuilder(
            customer_id=instance.customer.id,
            customer_name=instance.customer.customer_name or "Unknown",
            client_id=instance.client.id,
            client_name=instance.client.client_name or "Unknown"
        )
        return builder.accounting_output_files_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        return f"accounting/output_files/{_add_timestamp_to_filename(filename)}"


def upload_to_input_files_folder(instance, filename):
    """
    Generate upload path for input files.
    Structure: customer_<name>_<id>/client_<name>_<id>/input_files/DD-MM-YYYY/filename
    """
    try:
        builder = AzureBlobPathBuilder(
            customer_id=instance.client.customer.id,
            customer_name=instance.client.customer.customer_name or "Unknown",
            client_id=instance.client.id,
            client_name=instance.client.client_name or "Unknown"
        )
        return builder.input_files_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        return f"input_files/{_add_timestamp_to_filename(filename)}"

def upload_to_documents_folder(instance, filename):
    """
    Generate upload path for general documents.
    Structure: documents/doc_type/id/filename
    (Note: This falls outside the customer/client structure if no client info is available)
    """
    doc_type = getattr(instance, 'doc_typ', 'general')
    doc_id = getattr(instance, 'id', 'unknown')
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"documents/{doc_type}/{doc_id}/{timestamped_filename}"


def upload_to_processed_documents_folder(instance, filename):
    """
    Generate upload path for processed documents.
    Structure: customer_<name>_<id>/client_<name>_<id>/accounting/processed_documents/doc_id/filename
    """
    try:
        if hasattr(instance, 'customer'):
            customer = instance.customer
            client = instance.client if hasattr(instance, 'client') else None
        else:
            client = instance.client if hasattr(instance, 'client') else None
            customer = client.customer if client else None
        
        if customer and client:
            builder = AzureBlobPathBuilder(
                customer_id=customer.id,
                customer_name=customer.customer_name or "Unknown",
                client_id=client.id,
                client_name=client.client_name or "Unknown"
            )
            doc_id = getattr(instance, 'id', 'unknown')
            return builder.processed_document_path(doc_id, filename, add_timestamp=True)
    except (AttributeError, TypeError):
        pass
    
    return f"processed_documents/{_add_timestamp_to_filename(filename)}"


def upload_to_templates_folder(instance, filename):
    """
    Generate upload path for template files.
    Structure: templates/{template_type}/{template_id}/DD-MM-YYYY/{timestamped_filename}
    """
    template_type = getattr(instance, 'template_type', 'general')
    template_id = getattr(instance, 'id', 'default')
    timestamped_filename = _add_timestamp_to_filename(filename)
    today = datetime.now().strftime("%d-%m-%Y")
    
    return f"templates/{template_type}/{template_id}/{today}/{timestamped_filename}"


def upload_to_reports_folder(instance, filename):
    """
    Generate upload path for generated reports.
    Structure: reports/{report_type}/{year}/{month}/{timestamped_filename}
    """
    report_type = getattr(instance, 'report_type', 'general')
    current_date = datetime.now()
    year = current_date.year
    month = current_date.strftime("%m")
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"reports/{report_type}/{year}/{month}/{timestamped_filename}"


def upload_to_backups_folder(instance, filename):
    """
    Generate upload path for backup files.
    Structure: backups/{backup_type}/{year}/{month}/{day}/{timestamped_filename}
    """
    backup_type = getattr(instance, 'backup_type', 'general')
    current_date = datetime.now()
    year = current_date.year
    month = current_date.strftime("%m")
    day = current_date.strftime("%d")
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"backups/{backup_type}/{year}/{month}/{day}/{timestamped_filename}"


def upload_to_temp_folder(instance, filename):
    """
    Generate upload path for temporary files.
    Structure: temp/{session_id}/DD-MM-YYYY/{timestamped_filename}
    """
    session_id = getattr(instance, 'session_id', 'default')
    today = datetime.now().strftime("%d-%m-%Y")
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"temp/{session_id}/{today}/{timestamped_filename}"


def upload_to_montly_accounting_folder(document, filename):
    """
    Generate upload path for monthly accounting document uploads.
    Structure: customer_<name>_<id>/client_<name>_<id>/accounting/input_files/DD-MM-YYYY/filename
    """
    try:
        client = document.monthly_accounting.client
        builder = AzureBlobPathBuilder(
            customer_id=client.customer.id,
            customer_name=client.customer.customer_name or "Unknown",
            client_id=client.id,
            client_name=client.client_name or "Unknown"
        )
        return builder.accounting_input_files_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        return f"accounting/input_files/{_add_timestamp_to_filename(filename)}"


def upload_to_monthly_accounting_snapshot_folder(instance, filename):
    """
    Generate upload path for monthly accounting input file snapshots.
    Structure: customer_<name>_<id>/client_<name>_<id>/accounting/input_files/DD-MM-YYYY/filename
    """
    try:
        client = None
        if hasattr(instance, 'client'):
            client = instance.client
        elif hasattr(instance, 'monthly_accounting') and hasattr(instance.monthly_accounting, 'client'):
            client = instance.monthly_accounting.client
            
        if client:
            builder = AzureBlobPathBuilder(
                customer_id=client.customer.id,
                customer_name=client.customer.customer_name or "Unknown",
                client_id=client.id,
                client_name=client.client_name or "Unknown"
            )
            # Snapshots go to accounting/input_files as they are inputs for that session
            return builder.accounting_snapshots_input_files_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        pass
        
    return f"accounting_snapshots/input_files/{_add_timestamp_to_filename(filename)}"



def upload_to_montly_accounting_path_folder(document, path, filename):
    """
    Generate upload path for monthly accounting documents with custom subfolder.
    Uses unified AzureBlobPathBuilder for trackable paths.
    
    Structure: customer_<name>_<id>/client_<name>_<id>/monthly_accounting/documents/doc_id/filename
    
    Args:
        document: MonthlyAccountingDocument instance
        path (str): Subfolder path (e.g., 'documents/{doc_id}' or 'processed_documents/{doc_id}')
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    try:
        client = document.monthly_accounting.client
        builder = AzureBlobPathBuilder(
            customer_id=client.customer.id,
            customer_name=client.customer.customer_name or "Unknown",
            client_id=client.id,
            client_name=client.client_name or "Unknown"
        )
        
        # Handle different subfolder types
        if path.startswith('documents/'):
            doc_id = path.split('/')[-1]
            return builder.monthly_accounting_document_path(filename, doc_id, add_timestamp=True)
        elif path.startswith('processed_documents/'):
            doc_id = path.split('/')[-1] if '/' in path else None
            if doc_id:
                return builder.processed_document_path(doc_id, filename, add_timestamp=True)
            return builder.processed_output_path(filename, add_timestamp=True)
        
        # Default fallback
        return builder.monthly_accounting_upload_path(filename, add_timestamp=True)
    except (AttributeError, TypeError):
        # Fallback to legacy path if relationship is broken
        return f"monthly_accounting/{path}/{_add_timestamp_to_filename(filename)}"

# Utility functions for file management

def get_file_extension(filename):
    """
    Get file extension from filename
    
    Args:
        filename (str): Filename
        
    Returns:
        str: File extension (without dot)
    """
    return filename.rsplit('.', 1)[1] if '.' in filename else ''


def is_allowed_file_type(filename, allowed_extensions):
    """
    Check if file type is allowed based on extension
    
    Args:
        filename (str): Filename to check
        allowed_extensions (list): List of allowed extensions
        
    Returns:
        bool: True if file type is allowed
    """
    extension = get_file_extension(filename).lower()
    return extension in [ext.lower() for ext in allowed_extensions]


def get_file_size_display(size_bytes):
    """
    Convert file size in bytes to human readable format
    
    Args:
        size_bytes (int): File size in bytes
        
    Returns:
        str: Human readable file size
    """
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.2f}{size_names[i]}"


# File type validators for different document types

ALLOWED_DOCUMENT_EXTENSIONS = [
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'csv'
]

ALLOWED_IMAGE_EXTENSIONS = [
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff'
]

ALLOWED_BANK_STATEMENT_EXTENSIONS = [
    'pdf', 'csv', 'xls', 'xlsx', 'txt'
]


def validate_document_file(filename):
    """Validate document file type"""
    return is_allowed_file_type(filename, ALLOWED_DOCUMENT_EXTENSIONS)


def validate_image_file(filename):
    """Validate image file type"""
    return is_allowed_file_type(filename, ALLOWED_IMAGE_EXTENSIONS)


def validate_bank_statement_file(filename):
    """Validate bank statement file type"""
    return is_allowed_file_type(filename, ALLOWED_BANK_STATEMENT_EXTENSIONS)

