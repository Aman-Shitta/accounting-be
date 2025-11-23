"""
Azure Storage Path Management and Naming Convention

This module defines a unified, trackable directory structure for all Azure blob storage uploads.
It provides consistency across the entire application and makes document tracking easy.

Structure:
    customer_<customer_name>_<customer_id>/
        client_<client_name>_<client_id>/
            input_files/
                YYYY-MM-DD/
                    filename.ext
            je_exports/
                YYYY-MM-DD/
                    filename.ext
            monthly_accounting/
                YYYY-MM-DD/
                    filename.ext
                documents/
                    doc_id/
                        markdown/
                            document.md
                processed_documents/
                    doc_id/
                        output_file.ext
                    processed_output/
                        data_file.ext
"""

from datetime import datetime
from pathlib import Path
from typing import Optional


class AzureStoragePathConstants:
    """Constants for Azure storage paths"""
    
    # Date format for daily folders (for trackability)
    DATE_FORMAT = "%Y-%m-%d"
    
    # Folder names
    CUSTOMER_DOCUMENTS = "customer_documents"
    INPUT_FILES = "input_files"
    JE_EXPORTS = "je_exports"
    MONTHLY_ACCOUNTING = "monthly_accounting"
    DOCUMENTS = "documents"
    PROCESSED_DOCUMENTS = "processed_documents"
    PROCESSED_OUTPUT = "processed_output"
    MARKDOWN = "markdown"
    
    # Special folders
    TEMPLATES = "templates"
    BACKUPS = "backups"
    REPORTS = "reports"
    TEMP = "temp"


class AzureBlobPathBuilder:
    """
    Builds trackable, standardized paths for Azure blob storage uploads.
    
    Example:
        builder = AzureBlobPathBuilder(customer_id=1, customer_name="ACME Corp", 
                                       client_id=2, client_name="New York Branch")
        
        # Input files
        path = builder.input_files_path(filename="statement.pdf")
        # => customer_ACME Corp_1/client_New York Branch_2/input_files/2025-11-14/statement.pdf
        
        # Monthly accounting documents
        path = builder.monthly_accounting_document_path(
            filename="document.pdf",
            doc_id="uuid-123"
        )
        # => customer_ACME Corp_1/client_New York Branch_2/monthly_accounting/documents/uuid-123/document.pdf
        
        # Processed output
        path = builder.processed_output_path(
            doc_id="uuid-123",
            filename="output.json"
        )
        # => customer_ACME Corp_1/client_New York Branch_2/monthly_accounting/processed_documents/processed_output/output.json
    """
    
    def __init__(
        self,
        customer_id: int,
        customer_name: str,
        client_id: int,
        client_name: str
    ):
        """
        Initialize the path builder.
        
        Args:
            customer_id: Customer ID
            customer_name: Customer name (will be sanitized)
            client_id: Client ID
            client_name: Client name (will be sanitized)
        """
        self.customer_id = customer_id
        self.customer_name = self._sanitize_name(customer_name)
        self.client_id = client_id
        self.client_name = self._sanitize_name(client_name)
        
        # Build base path
        self.base_path = (
            f"customer_{self.customer_name}_{customer_id}/"
            f"client_{self.client_name}_{client_id}"
        )
    
    @staticmethod
    def _sanitize_name(name: str) -> str:
        """
        Sanitize names for use in paths (remove special characters, spaces to underscores).
        
        Args:
            name: Name to sanitize
            
        Returns:
            Sanitized name
        """
        # Replace spaces with underscores
        name = name.replace(" ", "_")
        # Remove special characters except underscores and hyphens
        name = "".join(c for c in name if c.isalnum() or c in "_-")
        return name.lower()
    
    @staticmethod
    def _get_today_folder() -> str:
        """Get today's date folder in YYYY-MM-DD format."""
        return datetime.now().strftime(AzureStoragePathConstants.DATE_FORMAT)
    
    def _add_timestamp_to_filename(self, filename: str) -> str:
        """
        Add timestamp to filename to ensure uniqueness.
        
        Args:
            filename: Original filename
            
        Returns:
            Filename with timestamp
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            return f"{timestamp}_{name}.{ext}"
        return f"{timestamp}_{filename}"
    
    # ========== INPUT FILES ==========
    def input_files_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Generate path for input files.
        
        Structure: customer_*/client_*/input_files/YYYY-MM-DD/filename.ext
        
        Args:
            filename: File to upload
            add_timestamp: Whether to add timestamp to filename (default: True)
            custom_date: Custom date folder (YYYY-MM-DD format, default: today)
            
        Returns:
            Full blob path
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.INPUT_FILES}/{date_folder}/{filename}"

    def customer_documents_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Generate path for input files.
        
        Structure: customer_*/client_*/input_files/YYYY-MM-DD/filename.ext
        
        Args:
            filename: File to upload
            add_timestamp: Whether to add timestamp to filename (default: True)
            custom_date: Custom date folder (YYYY-MM-DD format, default: today)
            
        Returns:
            Full blob path
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.CUSTOMER_DOCUMENTS}/{date_folder}/{filename}"
    
    # ========== JE EXPORTS ==========
    def je_exports_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Generate path for JE export files.
        
        Structure: customer_*/client_*/je_exports/YYYY-MM-DD/filename.ext
        
        Args:
            filename: File to upload
            add_timestamp: Whether to add timestamp to filename (default: True)
            custom_date: Custom date folder (YYYY-MM-DD format, default: today)
            
        Returns:
            Full blob path
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.JE_EXPORTS}/{date_folder}/{filename}"
    
    # ========== MONTHLY ACCOUNTING ==========
    def monthly_accounting_upload_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Generate path for monthly accounting document uploads.
        
        Structure: customer_*/client_*/monthly_accounting/YYYY-MM-DD/filename.ext
        
        Args:
            filename: File to upload
            add_timestamp: Whether to add timestamp to filename (default: True)
            custom_date: Custom date folder (YYYY-MM-DD format, default: today)
            
        Returns:
            Full blob path
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/{date_folder}/{filename}"
    
    def monthly_accounting_document_path(
        self,
        filename: str,
        doc_id: str,
        add_timestamp: bool = True
    ) -> str:
        """
        Generate path for extracted/processed monthly accounting documents.
        
        Structure: customer_*/client_*/monthly_accounting/documents/doc_id/filename.ext
        
        Args:
            filename: File to upload
            doc_id: Document ID (UUID or unique identifier)
            add_timestamp: Whether to add timestamp to filename (default: True)
            
        Returns:
            Full blob path
        """
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return (
            f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/"
            f"{AzureStoragePathConstants.DOCUMENTS}/{doc_id}/{filename}"
        )
    
    def markdown_document_path(
        self,
        doc_id: str,
        filename: str = "document.md",
        add_timestamp: bool = False
    ) -> str:
        """
        Generate path for markdown versions of documents.
        
        Structure: customer_*/client_*/monthly_accounting/documents/doc_id/markdown/document.md
        
        Args:
            doc_id: Document ID (UUID or unique identifier)
            filename: Markdown filename (default: document.md)
            add_timestamp: Whether to add timestamp to filename (default: False)
            
        Returns:
            Full blob path
        """
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return (
            f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/"
            f"{AzureStoragePathConstants.DOCUMENTS}/{doc_id}/"
            f"{AzureStoragePathConstants.MARKDOWN}/{filename}"
        )
    
    # ========== PROCESSED DOCUMENTS ==========
    def processed_document_path(
        self,
        doc_id: str,
        filename: str,
        add_timestamp: bool = True
    ) -> str:
        """
        Generate path for processed document files.
        
        Structure: customer_*/client_*/monthly_accounting/processed_documents/doc_id/filename.ext
        
        Args:
            doc_id: Document ID (UUID or unique identifier)
            filename: Processed file (e.g., extracted JSON, cleaned PDF)
            add_timestamp: Whether to add timestamp to filename (default: True)
            
        Returns:
            Full blob path
        """
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return (
            f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/"
            f"{AzureStoragePathConstants.PROCESSED_DOCUMENTS}/{doc_id}/{filename}"
        )
    
    def processed_output_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Generate path for batch processed output files.
        
        Structure: customer_*/client_*/monthly_accounting/processed_documents/processed_output/filename.ext
        
        Args:
            filename: Output file (e.g., aggregated data, summary report)
            add_timestamp: Whether to add timestamp to filename (default: True)
            custom_date: Custom date folder (YYYY-MM-DD format, optional)
            
        Returns:
            Full blob path
        """
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        base = (
            f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/"
            f"{AzureStoragePathConstants.PROCESSED_DOCUMENTS}/"
            f"{AzureStoragePathConstants.PROCESSED_OUTPUT}"
        )
        
        if custom_date:
            return f"{base}/{custom_date}/{filename}"
        return f"{base}/{filename}"
    
    # ========== UTILITY PATHS ==========
    def get_base_customer_path(self) -> str:
        """Get base customer path."""
        return f"customer_{self.customer_name}_{self.customer_id}"
    
    def get_base_client_path(self) -> str:
        """Get base customer/client path."""
        return self.base_path
    
    def list_all_document_paths(self, doc_id: str) -> dict:
        """
        Get all possible paths for a specific document ID for easy reference.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Dictionary with all related paths
        """
        return {
            "document": self.monthly_accounting_document_path("doc.pdf", doc_id),
            "markdown": self.markdown_document_path(doc_id),
            "processed": self.processed_document_path(doc_id, "output.json"),
            "base_folder": (
                f"{self.base_path}/{AzureStoragePathConstants.MONTHLY_ACCOUNTING}/"
                f"{AzureStoragePathConstants.DOCUMENTS}/{doc_id}"
            ),
        }


class AzureBlobPathValidator:
    """
    Validates and parses Azure blob paths against the naming convention.
    Useful for tracking and debugging document flow.
    """
    
    @staticmethod
    def parse_path(blob_path: str) -> Optional[dict]:
        """
        Parse a blob path and extract components.
        
        Args:
            blob_path: Full blob path
            
        Returns:
            Dictionary with parsed components or None if invalid format
            
        Example:
            >>> path = "customer_acme_corp_1/client_ny_branch_2/input_files/2025-11-14/file.pdf"
            >>> AzureBlobPathValidator.parse_path(path)
            {
                'customer_name': 'acme_corp',
                'customer_id': '1',
                'client_name': 'ny_branch',
                'client_id': '2',
                'type': 'input_files',
                'date': '2025-11-14',
                'filename': 'file.pdf'
            }
        """
        try:
            parts = blob_path.strip("/").split("/")
            
            if len(parts) < 3:
                return None
            
            # Parse customer and client
            customer_parts = parts[0].split("_")
            client_parts = parts[1].split("_")
            
            if len(customer_parts) < 3 or len(client_parts) < 3:
                return None
            
            customer_id = customer_parts[-1]
            customer_name = "_".join(customer_parts[1:-1])
            
            client_id = client_parts[-1]
            client_name = "_".join(client_parts[1:-1])
            
            doc_type = parts[2]
            
            result = {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "client_id": client_id,
                "client_name": client_name,
                "type": doc_type,
                "full_path": blob_path,
            }
            
            # Parse remaining parts based on document type
            if doc_type in ["input_files", "je_exports"]:
                if len(parts) >= 5:
                    result["date"] = parts[3]
                    result["filename"] = parts[4]
            elif doc_type == "monthly_accounting":
                if len(parts) >= 4:
                    if parts[3] == "documents":
                        result["category"] = "documents"
                        if len(parts) >= 5:
                            result["doc_id"] = parts[4]
                        if len(parts) >= 6:
                            if parts[5] == "markdown":
                                result["subtype"] = "markdown"
                            result["filename"] = parts[6] if len(parts) > 6 else None
                    elif parts[3] == "processed_documents":
                        result["category"] = "processed_documents"
                        if len(parts) >= 5:
                            if parts[4] == "processed_output":
                                result["subtype"] = "processed_output"
                                if len(parts) >= 6:
                                    result["filename"] = parts[5]
                            else:
                                result["doc_id"] = parts[4]
                                if len(parts) >= 6:
                                    result["filename"] = parts[5]
                    else:
                        result["date"] = parts[3]
                        if len(parts) >= 5:
                            result["filename"] = parts[4]
            
            return result
        except Exception:
            return None
    
    @staticmethod
    def validate_path(blob_path: str) -> tuple[bool, str]:
        """
        Validate a path against the naming convention.
        
        Args:
            blob_path: Path to validate
            
        Returns:
            Tuple (is_valid, message)
        """
        parsed = AzureBlobPathValidator.parse_path(blob_path)
        
        if not parsed:
            return False, "Invalid path format. Expected: customer_<name>_<id>/client_<name>_<id>/..."
        
        # Additional validations
        if not parsed.get("customer_id").isdigit():
            return False, "Customer ID must be numeric"
        
        if not parsed.get("client_id").isdigit():
            return False, "Client ID must be numeric"
        
        if parsed.get("date") and not _is_valid_date(parsed["date"]):
            return False, f"Invalid date format: {parsed['date']}. Expected YYYY-MM-DD"
        
        return True, "Valid path"


def _is_valid_date(date_str: str) -> bool:
    """Check if date string is in YYYY-MM-DD format."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False
