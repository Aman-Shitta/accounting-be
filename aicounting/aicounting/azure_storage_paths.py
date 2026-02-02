"""
Azure Storage Path Management and Naming Convention

This module defines a unified, trackable directory structure for all Azure blob storage uploads.
It provides consistency across the entire application and makes document tracking easy and audit-ready.

Structure:
    customer_<customer_name>_<customer_id>/
        client_<client_name>_<client_id>/
            input_files/
                YYYY-MM-DD/
                    <filename>
            je_templates/
                YYYY-MM-DD/
                    <filename>
            client_documents/
                YYYY-MM-DD/
                    <filename>
            accounting/
                YYYY-MM-DD/
                    <doc_id>/
                        original_document.pdf
                        snapshots/
                            input_file_snapshot_<timestamp>.pdf
                            je_template_snapshot_<timestamp>.csv
                        processing_artifacts/
                            01_raw_input/
                            02_ocr_output/
                            03_landing_ai/
                            04_gemini_ai/
                            05_document_ai/
                            06_rectification/
                            07_final_je/
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict


class AzureStoragePathConstants:
    """Constants for Azure storage paths"""
    
    # Date format for daily folders
    DATE_FORMAT = "%Y-%m-%d"
    
    # Root Level Folders
    CLIENT_DOCUMENTS = "client_documents"
    INPUT_FILES = "input_files"
    JE_TEMPLATES = "je_templates"
    
    # Accounting Structure
    ACCOUNTING = "accounting"
    
    # Subfolders within accounting/<date>/<doc_id>/
    SNAPSHOTS = "snapshots"
    PROCESSING_ARTIFACTS = "processing_artifacts"
    
    # Process Artifact Stages (formerly debug_files)
    ARTIFACT_RAW = "01_raw_input"
    ARTIFACT_OCR = "02_ocr_output"
    ARTIFACT_LANDING_AI = "03_landing_ai"
    ARTIFACT_GEMINI_AI = "04_gemini_ai"
    ARTIFACT_DOCUMENT_AI = "05_document_ai"
    ARTIFACT_RECTIFICATION = "06_rectification"
    ARTIFACT_FINAL_JE = "07_final_je"
    
    # Legacy/Mapping for backward compatibility
    LEGACY_DOCUMENTS = "documents"
    LEGACY_PROCESSED_DOCUMENTS = "processed_documents"
    LEGACY_OUTPUT_FILES = "output_files"


class AzureBlobPathBuilder:
    """
    Builds trackable, standardized paths for Azure blob storage uploads.
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
        """Sanitize names for use in paths."""
        name = name.replace(" ", "_")
        name = "".join(c for c in name if c.isalnum() or c in "_-")
        return name.lower()
    
    @staticmethod
    def _get_today_folder() -> str:
        """Get today's date folder in YYYY-MM-DD format."""
        return datetime.now().strftime(AzureStoragePathConstants.DATE_FORMAT)
    
    def _add_timestamp_to_filename(self, filename: str) -> str:
        """Add timestamp to filename to ensure uniqueness."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            return f"{timestamp}_{name}.{ext}"
        return f"{timestamp}_{filename}"
    
    # ========== ROOT LEVEL INPUTS ==========
    
    def input_files_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Path: customer_*/client_*/input_files/YYYY-MM-DD/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.INPUT_FILES}/{date_folder}/{filename}"

    def client_documents_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Path: customer_*/client_*/client_documents/YYYY-MM-DD/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.CLIENT_DOCUMENTS}/{date_folder}/{filename}"
        
    def je_template_path(
        self,
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Path: customer_*/client_*/je_templates/YYYY-MM-DD/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
        
        return f"{self.base_path}/{AzureStoragePathConstants.JE_TEMPLATES}/{date_folder}/{filename}"

    # ========== ACCOUNTING DOCUMENTS ==========
    
    def _get_accounting_base_path(self, date_folder: str, doc_id: str) -> str:
        """
        Helper: customer_*/client_*/accounting/YYYY-MM-DD/doc_id/
        """
        return (
            f"{self.base_path}/{AzureStoragePathConstants.ACCOUNTING}/"
            f"{date_folder}/{doc_id}"
        )

    def monthly_accounting_document_path(
        self,
        filename: str,
        doc_id: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Path: customer_*/client_*/accounting/YYYY-MM-DD/doc_id/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
            
        base = self._get_accounting_base_path(date_folder, doc_id)
        return f"{base}/{filename}"
        
    def accounting_snapshot_path(
        self,
        filename: str,
        doc_id: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Path: customer_*/client_*/accounting/YYYY-MM-DD/doc_id/snapshots/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
            
        base = self._get_accounting_base_path(date_folder, doc_id)
        return f"{base}/{AzureStoragePathConstants.SNAPSHOTS}/{filename}"

    # ========== PROCESSING ARTIFACTS (COMPLIANCE/DEBUG) ==========
    
    def _get_artifact_path(
        self,
        doc_id: str, 
        stage_folder: str, 
        filename: str,
        add_timestamp: bool = True,
        custom_date: Optional[str] = None
    ) -> str:
        """
        Helper for artifacts: .../accounting/YYYY-MM-DD/doc_id/processing_artifacts/<stage>/filename
        """
        date_folder = custom_date or self._get_today_folder()
        if add_timestamp:
            filename = self._add_timestamp_to_filename(filename)
            
        base = self._get_accounting_base_path(date_folder, doc_id)
        return (
            f"{base}/{AzureStoragePathConstants.PROCESSING_ARTIFACTS}/"
            f"{stage_folder}/{filename}"
        )

    def artifact_raw_input_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_RAW, filename, **kwargs)

    def artifact_ocr_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_OCR, filename, **kwargs)

    def artifact_landing_ai_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_LANDING_AI, filename, **kwargs)
        
    def artifact_gemini_ai_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_GEMINI_AI, filename, **kwargs)
        
    def artifact_document_ai_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_DOCUMENT_AI, filename, **kwargs)
        
    def artifact_rectification_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_RECTIFICATION, filename, **kwargs)
        
    def artifact_final_je_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._get_artifact_path(doc_id, AzureStoragePathConstants.ARTIFACT_FINAL_JE, filename, **kwargs)

    # ========== ALIASES FOR COMPATIBILITY (MAPPED TO ARTIFACTS) ==========
    
    def debug_base_path(self, doc_id: str) -> str:
        """Alias: Returns the processing_artifacts folder path (assuming today for date if not context)"""
        # Note: This is tricky without date. We assume today effectively for new calls.
        # For read operations, full path should be stored in DB.
        date_folder = self._get_today_folder()
        return (
            f"{self._get_accounting_base_path(date_folder, doc_id)}/"
            f"{AzureStoragePathConstants.PROCESSING_ARTIFACTS}"
        )
    
    def debug_raw_input_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self.artifact_raw_input_path(doc_id, filename, **kwargs)
    
    def debug_parsed_markdown_path(self, doc_id: str, filename: str = "parsed_markdown.md", **kwargs) -> str:
        return self.artifact_ocr_path(doc_id, filename, **kwargs)
        
    def debug_extracted_data_path(self, doc_id: str, filename: str = "extracted_data.json", **kwargs) -> str:
        return self.artifact_landing_ai_path(doc_id, filename, **kwargs) # Defaulting to Landing AI for 'extracted'
        
    def debug_rectified_data_path(self, doc_id: str, filename: str = "rectified_data.json", **kwargs) -> str:
        return self.artifact_rectification_path(doc_id, filename, **kwargs)
        
    def debug_classified_data_path(self, doc_id: str, filename: str = "classified_data.json", **kwargs) -> str:
        # Mapping classified to final JE area or rectification depending on pipeline step, using rectification for now
        return self.artifact_rectification_path(doc_id, filename, **kwargs)
        
    def debug_final_output_path(self, doc_id: str, filename: str = "final_output.json", **kwargs) -> str:
        return self.artifact_final_je_path(doc_id, filename, **kwargs)

    def accounting_output_files_path(self, filename: str, add_timestamp: bool = True, custom_date: Optional[str] = None) -> str:
        """Legacy alias: maps to main accounting folder or could map to JE templates if they are exports."""
        # Mapping to JE templates as that seems to be the intent of 'output files' usually (JE Exports)
        return self.je_template_path(filename, add_timestamp, custom_date)


class AzureBlobPathValidator:
    """
    Validates and parses Azure blob paths.
    """
    
    @staticmethod
    def parse_path(blob_path: str) -> Optional[dict]:
        """
        Parse a blob path and extract components.
        Supports both NEW and OLD structures.
        """
        try:
            parts = blob_path.strip("/").split("/")
            if len(parts) < 3:
                return None
            
            # Base Extraction
            customer_parts = parts[0].split("_")
            client_parts = parts[1].split("_")
            
            result = {
                "customer_id": customer_parts[-1] if len(customer_parts) > 1 else None,
                "client_id": client_parts[-1] if len(client_parts) > 1 else None,
                "full_path": blob_path,
                "type": parts[2]
            }
            
            doc_type = parts[2]
            
            # 1. NEW STRUCTURE PARSING
            # accounting/YYYY-MM-DD/doc_id/...
            if doc_type == AzureStoragePathConstants.ACCOUNTING:
                if len(parts) >= 5:
                    result["date"] = parts[3]
                    result["doc_id"] = parts[4]
                    if len(parts) >= 6:
                        result["category"] = parts[5] # e.g. snapshots, processing_artifacts
                        result["filename"] = parts[-1]
            
            # input_files/YYYY-MM-DD/filename
            elif doc_type in [AzureStoragePathConstants.INPUT_FILES, AzureStoragePathConstants.CLIENT_DOCUMENTS, AzureStoragePathConstants.JE_TEMPLATES]:
                if len(parts) >= 5:
                    result["date"] = parts[3]
                    result["filename"] = parts[4]

            return result
        except Exception:
            return None

def _is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

