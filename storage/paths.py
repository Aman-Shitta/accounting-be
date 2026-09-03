"""
Storage path conventions.

One trackable, auditable layout for every uploaded and generated file,
independent of the backend holding them (local filesystem now, GCS later).

    firm_<name>_<id>/
        client_<name>_<id>/
            input_files/YYYY-MM-DD/<filename>
            je_templates/YYYY-MM-DD/<filename>
            client_documents/YYYY-MM-DD/<filename>
            accounting/YYYY-MM-DD/<doc_id>/
                <original filename>
                processing_artifacts/
                    01_raw_input/
                    02_ocr_output/
                    03_extractor_ai/
                    04_gemini_ai/
                    07_final_summary/
"""

from datetime import datetime


class StoragePaths:
    """Folder names used to build storage paths."""

    DATE_FORMAT = "%Y-%m-%d"
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

    # Per-client root folders
    CLIENT_DOCUMENTS = "client_documents"
    INPUT_FILES = "input_files"
    JE_TEMPLATES = "je_templates"
    ACCOUNTING = "accounting"

    # Inside accounting/<date>/<doc_id>/
    PROCESSING_ARTIFACTS = "processing_artifacts"

    # Numbered so a listing reads in pipeline order
    ARTIFACT_RAW = "01_raw_input"
    ARTIFACT_OCR = "02_ocr_output"
    ARTIFACT_EXTRACTOR_AI = "03_extractor_ai"
    ARTIFACT_GEMINI_AI = "04_gemini_ai"
    ARTIFACT_FINAL_SUMMARY = "07_final_summary"


class DocumentPathBuilder:
    """
    Builds storage paths for one firm/client pair.

    Paths are relative keys — the storage backend decides where they land.
    """

    def __init__(self, firm_id: int, firm_name: str, client_id: int, client_name: str):
        self.firm_id = firm_id
        self.firm_name = self._sanitize(firm_name)
        self.client_id = client_id
        self.client_name = self._sanitize(client_name)

        self.base_path = (
            f"firm_{self.firm_name}_{firm_id}/"
            f"client_{self.client_name}_{client_id}"
        )

    @staticmethod
    def _sanitize(name: str) -> str:
        """Reduce a display name to a path-safe slug."""
        name = (name or "unknown").replace(" ", "_")
        return "".join(c for c in name if c.isalnum() or c in "_-").lower() or "unknown"

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime(StoragePaths.DATE_FORMAT)

    @staticmethod
    def _timestamped(filename: str) -> str:
        """Prefix a filename with a timestamp so re-uploads never collide."""
        stamp = datetime.now().strftime(StoragePaths.TIMESTAMP_FORMAT)
        if "." in filename:
            name, ext = filename.rsplit(".", 1)
            return f"{stamp}_{name}.{ext}"
        return f"{stamp}_{filename}"

    def _dated_path(
        self,
        folder: str,
        filename: str,
        add_timestamp: bool = True,
        custom_date: str | None = None,
    ) -> str:
        date_folder = custom_date or self._today()
        if add_timestamp:
            filename = self._timestamped(filename)
        return f"{self.base_path}/{folder}/{date_folder}/{filename}"

    # ---- client-level uploads -------------------------------------------

    def input_files_path(self, filename: str, **kwargs) -> str:
        return self._dated_path(StoragePaths.INPUT_FILES, filename, **kwargs)

    def client_documents_path(self, filename: str, **kwargs) -> str:
        return self._dated_path(StoragePaths.CLIENT_DOCUMENTS, filename, **kwargs)

    def je_template_path(self, filename: str, **kwargs) -> str:
        return self._dated_path(StoragePaths.JE_TEMPLATES, filename, **kwargs)

    # ---- period documents ------------------------------------------------

    def _accounting_base(self, date_folder: str, doc_id: str) -> str:
        return f"{self.base_path}/{StoragePaths.ACCOUNTING}/{date_folder}/{doc_id}"

    def period_document_path(
        self,
        filename: str,
        doc_id: str,
        add_timestamp: bool = True,
        custom_date: str | None = None,
    ) -> str:
        date_folder = custom_date or self._today()
        if add_timestamp:
            filename = self._timestamped(filename)
        return f"{self._accounting_base(date_folder, doc_id)}/{filename}"

    # ---- processing artifacts -------------------------------------------

    def _artifact_path(
        self,
        doc_id: str,
        stage: str,
        filename: str,
        add_timestamp: bool = True,
        custom_date: str | None = None,
    ) -> str:
        date_folder = custom_date or self._today()
        if add_timestamp:
            filename = self._timestamped(filename)
        base = self._accounting_base(date_folder, doc_id)
        return f"{base}/{StoragePaths.PROCESSING_ARTIFACTS}/{stage}/{filename}"

    def artifact_raw_input_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._artifact_path(doc_id, StoragePaths.ARTIFACT_RAW, filename, **kwargs)

    def artifact_ocr_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._artifact_path(doc_id, StoragePaths.ARTIFACT_OCR, filename, **kwargs)

    def artifact_extractor_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._artifact_path(doc_id, StoragePaths.ARTIFACT_EXTRACTOR_AI, filename, **kwargs)

    def artifact_gemini_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._artifact_path(doc_id, StoragePaths.ARTIFACT_GEMINI_AI, filename, **kwargs)

    def artifact_final_summary_path(self, doc_id: str, filename: str, **kwargs) -> str:
        return self._artifact_path(doc_id, StoragePaths.ARTIFACT_FINAL_SUMMARY, filename, **kwargs)

    def artifacts_folder(self, doc_id: str) -> str:
        """Folder holding every artifact for a document uploaded today."""
        base = self._accounting_base(self._today(), doc_id)
        return f"{base}/{StoragePaths.PROCESSING_ARTIFACTS}"
