"""
Django Management Command: update_gl_classification

This command processes modified GL line items from bank/cc documents,
condenses similar descriptions using Gemini, and updates the client's
gl_history file in Azure and OpenAI vector store.

Usage:
    python manage.py update_gl_classification
    python manage.py update_gl_classification --client-id=123
    python manage.py update_gl_classification --dry-run
"""

import io
import json
import logging

from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from django.db.models import Prefetch

from google.genai import types

from extractor.gemini_service import GeminiMixin, JSONHelper

from user.models import DimAICClient, DimAICAssistant, DimAICClientDocument
from account.models import MonthlyDocumentBankLineItem, MonthlyAccountingDocument

logger = logging.getLogger(__name__)


# Normalized file names for vector store (no date prefix)
VECTOR_STORE_FILE_NAMES = {
    'chart_of_account': 'coa.json',
    'vendor_list': 'vendor_list.json',
    'gl_history': 'gl_history.json',
}


class GeminiGLCondenser(GeminiMixin):
    """
    Service to condense GL classification mappings using Gemini.
    Takes a list of description/gl_code/gl_description and returns condensed patterns.
    """
    
    CONDENSATION_PROMPT = """You are a financial data analyst. Your task is to condense a list of transaction descriptions with their GL classifications into reusable patterns.

    Given a list of transactions with their GL codes and descriptions, identify similar transactions that share the same GL classification and create condensed pattern rules.

    For example:
    - "AMAZON PURCHASE #12345" and "AMAZON PURCHASE #67890" should become "AMAZON PURCHASE*"
    - "PAYROLL 01/15/2024" and "PAYROLL 02/15/2024" should become "PAYROLL*"
    - "Sales 01/3/2025 amazon" and "Ebay 02/5/2025 sales" should remain unique as they differ in key terms.
    - Keep unique descriptions as-is if they don't have similar patterns

    Rules:
    1. Group transactions by their GL code first
    2. Within each GL code group, identify common patterns in descriptions
    3. Use * as wildcard for variable parts (numbers, dates, etc.)
    4. Preserve important keywords that identify the transaction type
    5. Return a condensed list with unique patterns only
    6. Each pattern should map to exactly one GL code

    Return the condensed list in JSON format.
    """

    RESPONSE_SCHEMA = types.Schema(
        type=types.Type.ARRAY,
        items=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "description": types.Schema(
                    type=types.Type.STRING,
                    description="Condensed description pattern (use * for wildcards)"
                ),
                "gl_code": types.Schema(
                    type=types.Type.STRING,
                    description="GL account code"
                ),
                "gl_description": types.Schema(
                    type=types.Type.STRING,
                    description="GL account description/name"
                )
            },
            required=["description", "gl_code", "gl_description"]
        )
    )

    def __init__(self):
        self.init_gemini()

    def condense(self, gl_mappings: list) -> list:
        """
        Condense a list of GL mappings into patterns.
        
        Args:
            gl_mappings: List of dicts with {description, gl_code, gl_description}
            
        Returns:
            Condensed list of pattern mappings
        """
        if not gl_mappings:
            return []

        try:
            content = f"""Here are the transactions to condense:

            {json.dumps(gl_mappings, indent=2)}

            Please analyze these transactions and return a condensed list of patterns."""

            # Use mixin's config builder
            config = self.get_gemini_config(
                temperature=0.2,
                response_schema=self.RESPONSE_SCHEMA,
                response_mime_type="application/json",
                system_instruction=[self.CONDENSATION_PROMPT],
            )

            # Use mixin's generate method
            raw = self.gemini_generate(
                contents=[content],
                config=config,
            )

            # Use JSONHelper for parsing
            result = JSONHelper.parse_json(raw, default=[])
            return result

        except Exception as e:
            logger.error(f"Error condensing GL mappings with Gemini: {e}")
            # Return original mappings if condensation fails
            return gl_mappings


class VectorStoreManager:
    """
    Manages OpenAI vector store file operations with normalized naming.
    """
    
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
    
    def list_files(self, vector_store_id: str) -> list:
        """List all files in a vector store with their names."""
        try:
            files = self.client.vector_stores.files.list(vector_store_id=vector_store_id)
            file_details = []
            for vs_file in files.data:
                try:
                    # Get the actual file details to get the name
                    file_info = self.client.files.retrieve(vs_file.id)
                    file_details.append({
                        'id': vs_file.id,
                        'name': file_info.filename,
                        'status': vs_file.status
                    })
                except Exception as e:
                    logger.warning(f"Could not get details for file {vs_file.id}: {e}")
                    file_details.append({
                        'id': vs_file.id,
                        'name': None,
                        'status': vs_file.status
                    })
            return file_details
        except Exception as e:
            logger.error(f"Error listing vector store files: {e}")
            return []
    
    def find_file_by_name(self, vector_store_id: str, filename: str):
        """Find a file in the vector store by its name."""
        files = self.list_files(vector_store_id)
        for f in files:
            if f['name'] and filename in f['name']:
                return f['id']
        return None
    
    def upload_file(self, vector_store_id: str, content: str, filename: str):
        """Upload a file to the vector store."""
        try:
            # Create file stream
            file_stream = io.BytesIO(content.encode('utf-8'))
            file_stream.name = filename
            
            # Upload to vector store
            file_batch = self.client.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store_id,
                files=[file_stream]
            )
            
            file_stream.close()
            
            # Get the uploaded file ID
            if file_batch.file_counts.completed > 0:
                # Find the newly uploaded file
                new_file_id = self.find_file_by_name(vector_store_id, filename)
                logger.info(f"Uploaded {filename} to vector store {vector_store_id}")
                return new_file_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error uploading file to vector store: {e}")
            return None
    
    def delete_file(self, vector_store_id: str, file_id: str) -> bool:
        """Delete a file from the vector store."""
        try:
            self.client.vector_stores.files.delete(
                vector_store_id=vector_store_id,
                file_id=file_id
            )
            logger.info(f"Deleted file {file_id} from vector store {vector_store_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file from vector store: {e}")
            return False
    
    def replace_file(self, vector_store_id: str, content: str, filename: str) -> bool:
        """
        Replace a file in the vector store by name.
        Uploads new file first, then deletes old file only on success.
        """
        # Find existing file
        old_file_id = self.find_file_by_name(vector_store_id, filename)
        
        # Upload new file
        new_file_id = self.upload_file(vector_store_id, content, filename)
        
        if not new_file_id:
            logger.error(f"Failed to upload new {filename}")
            return False
        
        # Delete old file only after successful upload
        if old_file_id and old_file_id != new_file_id:
            self.delete_file(vector_store_id, old_file_id)
        
        return True


class Command(BaseCommand):
    help = 'Update GL classification by condensing modified GL mappings and updating vector store'

    def add_arguments(self, parser):
        parser.add_argument(
            '--client-id',
            type=int,
            help='Process only a specific client by ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without actually updating Azure/OpenAI',
        )

    def handle(self, *args, **options):
        client_id = options.get('client_id')
        dry_run = options.get('dry_run', False)

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))

        # Get clients to process
        if client_id:
            clients = DimAICClient.objects.filter(id=client_id)
            if not clients.exists():
                self.stdout.write(self.style.ERROR(f'Client with ID {client_id} not found'))
                return
        else:
            clients = DimAICClient.objects.all()

        self.stdout.write(f'Processing {clients.count()} client(s)...')

        # Initialize services
        gemini_condenser = GeminiGLCondenser()
        vector_store_manager = VectorStoreManager(api_key=settings.OPENAI_API_KEY)

        for client in clients:
            self.process_client(client, gemini_condenser, vector_store_manager, dry_run)

        self.stdout.write(self.style.SUCCESS('GL Classification update completed'))

    def process_client(self, client: DimAICClient, condenser: GeminiGLCondenser, 
                       vs_manager: VectorStoreManager, dry_run: bool):
        """Process a single client's modified GL line items."""
        self.stdout.write(f'\nProcessing client: {client.client_name} (ID: {client.id})')

        # Get modified GL line items for bank/cc documents
        # for last two months.
        from django.utils import timezone
        from datetime import timedelta
        modified_items = MonthlyDocumentBankLineItem.objects.filter(
            document__monthly_accounting__client=client,
            document__doc_type__in=['bank_statement', 'credit_card'],
            modified_gl=True,
            gl_account__isnull=False
            # updated_at__gte=timezone.now().replace(day=1) - timedelta(days=60)
    
        ).select_related('gl_account')

        if not modified_items.exists():
            self.stdout.write(f'  No modified GL items found for {client.client_name}')
            return

        self.stdout.write(f'  Found {modified_items.count()} modified GL items')

        # Build GL mappings list
        gl_mappings = []
        for item in modified_items:
            gl_mappings.append({
                'description': item.description,
                'gl_code': item.gl_account.account_number,
                'gl_description': item.gl_account.account_name
            })

        self.stdout.write(f'  Built {len(gl_mappings)} GL mappings')

        # Condense using Gemini
        condensed_mappings = condenser.condense(gl_mappings)
        self.stdout.write(f'  Condensed to {len(condensed_mappings)} patterns')

        if dry_run:
            self.stdout.write('  [DRY RUN] Would save condensed mappings:')
            for mapping in condensed_mappings[:5]:  # Show first 5
                self.stdout.write(f'    - {mapping["description"]} -> {mapping["gl_code"]}')
            if len(condensed_mappings) > 5:
                self.stdout.write(f'    ... and {len(condensed_mappings) - 5} more')
            return

        # Build JSON content for vector store
        json_content = json.dumps({
            "document_type": "GL History",
            "description": "Condensed GL classification patterns from modified transactions",
            "patterns": condensed_mappings
        }, indent=2)

        # Get client's assistant configuration
        try:
            assistant_config = DimAICAssistant.objects.get(client=client, is_active=True)
        except DimAICAssistant.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'  No active assistant for {client.client_name}'))
            return

        if not assistant_config.vector_store_id:
            self.stdout.write(self.style.WARNING(f'  No vector store for {client.client_name}'))
            return

        # Save to Azure storage
        try:
            azure_path = self._get_azure_path(client, VECTOR_STORE_FILE_NAMES['gl_history'])
            default_storage.save(azure_path, ContentFile(json_content.encode('utf-8')))
            self.stdout.write(f'  Saved to Azure: {azure_path}')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'  Failed to save to Azure: {e}'))
            return

        # Update vector store (upload new, delete old)
        success = vs_manager.replace_file(
            vector_store_id=assistant_config.vector_store_id,
            content=json_content,
            filename=VECTOR_STORE_FILE_NAMES['gl_history']
        )

        if success:
            self.stdout.write(self.style.SUCCESS(f'  Updated vector store for {client.client_name}'))
            
            # Delete old gl_history document record (not the Azure file, just the DB record)
            old_docs = DimAICClientDocument.objects.filter(
                client=client,
                document_type='gl_history'
            )
            if old_docs.exists():
                # Keep the file in Azure but update the record to point to new file
                for doc in old_docs:
                    doc.delete()
                self.stdout.write(f'  Removed old gl_history document records')
        else:
            self.stdout.write(self.style.ERROR(f'  Failed to update vector store for {client.client_name}'))

    def _get_azure_path(self, client: DimAICClient, filename: str) -> str:
        """Build Azure storage path for client's processed documents."""
        customer = client.customer
        customer_name = customer.customer_name.lower().replace(' ', '_')
        client_name = client.client_name.lower().replace(' ', '_')
        
        return f"customer_{customer_name}_{customer.id}/client_{client_name}_{client.id}/processed_documents/{filename}"