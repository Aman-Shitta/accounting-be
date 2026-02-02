from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.db import transaction
from django.conf import settings
from datetime import datetime
import logging

# Import Models
from account.models import MonthlyAccountingDocument, DimAicInputFiles
from user.models.dim_aic_client_model import DimAICClientDocument

# Import Path Helpers
from aicounting.azure_storage_paths import AzureBlobPathBuilder
from aicounting.file_upload_helper import get_blob_path_builder

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Migrate files to the new date-based folder structure'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Simulate migration without moving files')
        parser.add_argument('--model', type=str, help='Specific model to migrate (input/client/accounting)')

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        model_type = options['model']
        
        self.stdout.write(self.style.SUCCESS(f"Starting migration (Dry Run: {self.dry_run})..."))
        
        if not model_type or model_type == 'input':
            self.migrate_input_files()
            
        if not model_type or model_type == 'client':
            self.migrate_client_documents()
            
        if not model_type or model_type == 'accounting':
            self.migrate_accounting_documents()
            
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
            self.stdout.write(self.style.WARNING(f"Skipping {instance} (ID: {instance.id}): No Client/Customer info"))
            return

        # Determine date for the folder
        date_obj = instance.created_at if hasattr(instance, 'created_at') else datetime.now()
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
                    self.stdout.write(self.style.ERROR(f"File not found in storage: {old_path}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to migrate {old_path}: {e}"))

    def migrate_input_files(self):
        self.stdout.write("Migrating Input Files...")
        qs = DimAicInputFiles.objects.all()
        for item in qs:
            self._migrate_file(
                item, 
                'file', 
                lambda b, f, d: b.input_files_path(f, add_timestamp=False, custom_date=d)
            )

    def migrate_client_documents(self):
        self.stdout.write("Migrating Client Documents...")
        qs = DimAICClientDocument.objects.all()
        for item in qs:
            self._migrate_file(
                item, 
                'file', 
                lambda b, f, d: b.client_documents_path(f, add_timestamp=False, custom_date=d)
            )

    def migrate_accounting_documents(self):
        self.stdout.write("Migrating Monthly Accounting Documents...")
        qs = MonthlyAccountingDocument.objects.all()
        for item in qs:
            # Main File
            self._migrate_file(
                item, 
                'file', 
                lambda b, f, d: b.monthly_accounting_document_path(f, str(item.id), add_timestamp=False, custom_date=d)
            )
