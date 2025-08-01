"""
File Upload Helper Functions for AICounting Project

This module contains all the file upload path generation functions used across different models.
It provides a centralized location to manage file upload structures and naming conventions.

All upload functions follow the pattern:
- Organized folder structure based on entity relationships
- Timestamped filenames to avoid conflicts
- Consistent path formats across the application
"""

from datetime import datetime
import os


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
    Generate upload path based on customer and client structure
    Used for: Client documents in user app
    
    Structure: customer_{customer_id}/{client_name}/client_documents/{timestamped_filename}
    
    Args:
        instance: Model instance with client relationship
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    customer_id = instance.client.customer.id
    client_name = instance.client.client_name
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"customer_{customer_id}/{client_name}/client_documents/{timestamped_filename}"


def upload_to_input_files_folder(instance, filename):
    """
    Generate upload path for input files based on client structure
    Used for: Input files in account app
    
    Structure: client_{client_id}/{client_name}/input_files/{timestamped_filename}
    
    Args:
        instance: Model instance with client relationship
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    customer_id = instance.client.customer.id
    client_name = instance.client.client_name
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"customer_{customer_id}/{client_name}/input_files/{timestamped_filename}"

def upload_to_documents_folder(instance, filename):
    """
    Generate upload path for general documents
    Used for: General documents in document app
    
    Structure: documents/{doc_type}/{doc_id}/{timestamped_filename}
    
    Args:
        instance: Model instance with doc_typ and doc_id attributes
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    doc_type = instance.doc_typ
    doc_id = instance.doc_id
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"documents/{doc_type}/{doc_id}/{timestamped_filename}"


def upload_to_processed_documents_folder(instance, filename):
    """
    Generate upload path for processed documents
    Used for: Processed/analyzed documents
    
    Structure: processed/{customer_id}/{client_id}/processed_docs/{timestamped_filename}
    
    Args:
        instance: Model instance with customer and client relationship
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    customer_id = instance.customer.id if hasattr(instance, 'customer') else instance.client.customer.id
    client_id = instance.client.id if hasattr(instance, 'client') else instance.id
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"processed/{customer_id}/{client_id}/processed_docs/{timestamped_filename}"


def upload_to_templates_folder(instance, filename):
    """
    Generate upload path for template files
    Used for: JE templates and other template documents
    
    Structure: templates/{template_type}/{template_id}/{timestamped_filename}
    
    Args:
        instance: Model instance with template information
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    template_type = getattr(instance, 'template_type', 'general')
    template_id = getattr(instance, 'id', 'default')
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"templates/{template_type}/{template_id}/{timestamped_filename}"


def upload_to_reports_folder(instance, filename):
    """
    Generate upload path for generated reports
    Used for: System generated reports and exports
    
    Structure: reports/{report_type}/{year}/{month}/{timestamped_filename}
    
    Args:
        instance: Model instance with report information
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    report_type = getattr(instance, 'report_type', 'general')
    current_date = datetime.now()
    year = current_date.year
    month = current_date.strftime("%m")
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"reports/{report_type}/{year}/{month}/{timestamped_filename}"


def upload_to_backups_folder(instance, filename):
    """
    Generate upload path for backup files
    Used for: Database backups, file backups
    
    Structure: backups/{backup_type}/{year}/{month}/{day}/{timestamped_filename}
    
    Args:
        instance: Model instance with backup information
        filename (str): Original filename
        
    Returns:
        str: Upload path
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
    Generate upload path for temporary files
    Used for: Temporary processing files that will be cleaned up
    
    Structure: temp/{session_id}/{timestamped_filename}
    
    Args:
        instance: Model instance
        filename (str): Original filename
        
    Returns:
        str: Upload path
    """
    session_id = getattr(instance, 'session_id', 'default')
    timestamped_filename = _add_timestamp_to_filename(filename)
    
    return f"temp/{session_id}/{timestamped_filename}"


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

