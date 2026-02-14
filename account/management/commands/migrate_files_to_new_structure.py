from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.db import transaction
from django.conf import settings
from datetime import datetime
import logging

# Import Models
from account.models import MonthlyAccountingDocument, DimAicInputFiles
from user.models import DimAICClientDocument
from account.models import FactAICInputFileSnapshot, FactAICJETemplateHeaderSnapshot

# Import Path Helpers
from aicounting.azure_storage_paths import AzureBlobPathBuilder
from aicounting.file_upload_helper import get_blob_path_builder
from aicounting.azure_storage_backends import AzureMediaStorage

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate files to the new date-based folder structure'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Simulate migration without moving files')
        parser.add_argument(
            '--model', type=str, help='Specific model to migrate (input/client/accounting)')

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        model_type = options['model']

        self.stdout.write(self.style.SUCCESS(
            f"Starting migration (Dry Run: {self.dry_run})..."))

        if not model_type or model_type == 'input':
            self.migrate_input_files()

        if not model_type or model_type == 'client':
            self.migrate_client_documents()

        if not model_type or model_type == 'accounting':
            self.migrate_accounting_documents()

        if not model_type or model_type == 'snapshots':
            self.migrate_snapshots()

        if not model_type or model_type == 'je_templates':
            self.migrate_je_templates()

        if not model_type or model_type == 'artifacts':
            self.migrate_processing_artifacts()

        self.stdout.write(self.style.SUCCESS("Migration process completed."))

    def _migrate_file(self, instance, file_field_name, new_path_func):
        """
        Generic migration logic for a file field.
        """
        file_field = getattr(instance, file_field_name)
        if not file_field:
            return

        old_path = file_field.name

        # Generate new path
        # We need to construct the builder manually or use helper, but strictly respecting the CREATION DATE of the file/instance
        # to ensure historical accuracy, rather than "today".

        builder = get_blob_path_builder(instance)
        if not builder:
            self.stdout.write(self.style.WARNING(
                f"Skipping {instance} (ID: {instance.id}): No Client/Customer info"))
            return

        # Determine date for the folder
        date_obj = instance.created_at if hasattr(
            instance, 'created_at') else datetime.now()
        date_str = date_obj.strftime("%Y-%m-%d")

        # Calculate new path
        filename = old_path.split('/')[-1]

        # Execute the specific path function passed in
        new_path = new_path_func(builder, filename, date_str)

        if old_path == new_path:
            # Already in correct place
            return

        self.stdout.write(f"Migrating: {old_path} -> {new_path}")

        if not self.dry_run:
            try:
                if default_storage.exists(old_path):
                    # Copy file
                    with default_storage.open(old_path, 'rb') as f:
                        default_storage.save(new_path, f)

                    # Update DB
                    setattr(instance, file_field_name, new_path)
                    instance.save(update_fields=[file_field_name])

                    # Optional: Delete old file?
                    # specific requirement usually mentions "copy" or "move".
                    # Safest is COPY first. We won't delete in this pass to avoid data loss.
                else:
                    self.stdout.write(self.style.ERROR(
                        f"File not found in storage: {old_path}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Failed to migrate {old_path}: {e}"))

    def migrate_input_files(self):
        self.stdout.write("Migrating Input Files...")
        qs = DimAicInputFiles.objects.all()
        for item in qs:
            self._migrate_file(
                item,
                'file',
                lambda b, f, d: b.input_files_path(
                    f, add_timestamp=False, custom_date=d)
            )

    def migrate_client_documents(self):
        self.stdout.write("Migrating Client Documents...")
        qs = DimAICClientDocument.objects.all()
        for item in qs:
            self._migrate_file(
                item,
                'file',
                lambda b, f, d: b.client_documents_path(
                    f, add_timestamp=False, custom_date=d)
            )

    def migrate_accounting_documents(self):
        self.stdout.write("Migrating Monthly Accounting Documents...")
        qs = MonthlyAccountingDocument.objects.all()
        for item in qs:
            # Main File
            self._migrate_file(
                item,
                'file',
                lambda b, f, d: b.monthly_accounting_document_path(
                    f, str(item.id), add_timestamp=False, custom_date=d)
            )

    def migrate_snapshots(self):
        self.stdout.write("Migrating Input File Snapshots...")
        qs = FactAICInputFileSnapshot.objects.all()
        for item in qs:
            self._migrate_file(
                item,
                'file',
                lambda b, f, d: b.accounting_snapshots_path(
                    f, add_timestamp=False, custom_date=d)
            )

    def migrate_je_templates(self):
        self.stdout.write("Migrating JE Template Snapshots...")
        qs = FactAICJETemplateHeaderSnapshot.objects.all()
        for item in qs:
            self._migrate_file(
                item,
                'je_export_file',
                lambda b, f, d: b.je_template_path(
                    f, add_timestamp=False, custom_date=d)
            )

    def migrate_processing_artifacts(self):
        self.stdout.write("Migrating Processing Artifacts...")
        qs = MonthlyAccountingDocument.objects.all()
        total = qs.count()
        count = 0

        for doc in qs:
            count += 1
            if count % 100 == 0:
                self.stdout.write(f"Processed {count}/{total} documents...")

            builder = get_blob_path_builder(doc)
            if not builder:
                continue

            doc_id = str(doc.id)

            # Determine date for the folder
            # We use created_at of the document to place artifacts in the correct time-based folder
            date_obj = doc.created_at if hasattr(
                doc, 'created_at') else datetime.now()
            date_str = date_obj.strftime("%Y-%m-%d")

            # Old path prefix: debug_files/{doc_id}/
            old_prefix = f"debug_files/{doc_id}/"

            # List all blobs in old prefix
            try:
                # We need direct access to blob client to list blobs
                # Assuming default_storage is AzureMediaStorage or compatible
                # that exposes specific method or we can use underlying client if available.
                # Since we don't have list_blobs on Storage API directly usually (listdir is limited),
                # we might need to access the client.

                # However, AzureMediaStorage definition shows listdir uses list_blobs.
                # But listdir is not recursive usually.
                # Let's try to grab the client from default_storage if possible.

                if hasattr(default_storage, 'blob_service_client'):
                    container_client = default_storage.blob_service_client.get_container_client(
                        default_storage.container_name)
                    blobs = container_client.list_blobs(
                        name_starts_with=old_prefix)

                    for blob in blobs:
                        old_blob_name = blob.name

                        # Determine new path
                        # Old: debug_files/{doc_id}/01_raw_input/file.pdf
                        # New: .../accounting/{date}/{doc_id}/processing_artifacts/01_raw_input/file.pdf

                        # Strip prefix
                        relative_path = old_blob_name[len(old_prefix):]

                        # Construct new path using builder logic manually or via helper?
                        # The builder has `artifact_rectification_path` etc but generic mapping is safer for bulk move

                        # builder.monthly_accounting_document_path usually builds .../accounting/{date}/{doc_id}/...
                        # We want .../accounting/{date}/{doc_id}/processing_artifacts/{relative_path}

                        # Let's inspect builder base path for accounting
                        # base = f"customer_{c}/{custom_date}/{doc_id}" ? No
                        # format: customer_{c}/client_{cl}/accounting/{date}/{doc_id}/...

                        # We can use the builder to get the base accounting path
                        # But builder methods return full string.
                        # Let's create a custom path construction using builder attributes

                        new_path = f"customer_{builder.customer_name}_{builder.customer_id}/" \
                                   f"client_{builder.client_name}_{builder.client_id}/" \
                                   f"accounting/{date_str}/{doc_id}/processing_artifacts/{relative_path}"

                        self.stdout.write(
                            f"Artifact: {old_blob_name} -> {new_path}")

                        if not self.dry_run:
                            try:
                                # We can copy blob directly on server side if same account?
                                # But here we support moving to NEW CONTAINER.
                                # So we must download/upload or start copy between containers.
                                # Simple approach: read/write (slow for many files but reliable)
                                # Or use start_copy_from_url if SAS available.

                                # Using read/write as implemented in _migrate_file
                                with default_storage.open(old_blob_name, 'rb') as f:
                                    self.dest_storage.save(new_path, f)

                            except Exception as e:
                                self.stdout.write(self.style.ERROR(
                                    f"Failed artifact {old_blob_name}: {e}"))

            except Exception as e:
                self.stdout.write(self.style.WARNING(
                    f"Could not list artifacts for {doc_id}: {e}"))
