"""
Deprecated shim — import from :mod:`storage.uploads` instead.

Historical migrations under ``account/`` reference
``aicounting.file_upload_helper.upload_to_*`` by dotted path. This module
keeps those importable until Phase 3 replaces the migrations wholesale, at
which point it is deleted.
"""

from storage.uploads import (  # noqa: F401
    DocumentDebugStorage,
    upload_to_customer_client_folder,
    upload_to_input_files_folder,
    upload_to_je_export_folder,
    upload_to_monthly_accounting_snapshot_folder,
    upload_to_montly_accounting_folder,
)
