from __future__ import annotations

import os
import logging
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Optional, Any

from django.conf import settings
from django.db import transaction

from decimal import Decimal, InvalidOperation


from pydantic import BaseModel, Field, create_model
from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from extractor.base import BaseDocumentProcessor
from extractor.prompter import Configuration
from account.models import (
    MonthlyAccountingDocument
)
from extractor.utils import split_pdf_to_pages

logger = logging.getLogger(__name__)


# --- Pydantic Models for Sales Document Extraction Schemas ---

class KeyItem(BaseModel):
    """Represents a key-value pair extracted from a sales document."""
    key: str = Field(..., description="The name/label of the extracted attribute (e.g., 'total_sales', 'tax_amount', 'net_revenue').")
    value: str = Field(..., description="The value associated with the key (e.g., '1500.00', '2024-01-15').")


class KeyItemList(BaseModel):
    """List of key-value pairs extracted from a sales document page."""
    key_items: List[KeyItem] = Field(
        default_factory=list,
        description="List of all key-value pairs (attributes) extracted from the document page. "
                    "Each item should represent a meaningful data point like totals, dates, amounts, etc."
    )


def build_dynamic_extraction_model(attributes: List[Dict[str, Any]]) -> type:
    """
    Dynamically build a Pydantic model based on configured attributes.
    
    Args:
        attributes: List of attribute dicts with 'name', 'key' (normalized), and 'comments' (helper text)
        
    Returns:
        A dynamically created Pydantic model class with fields for each attribute
    
    Example:
        If attributes = [
            {'key': 'property_number', 'name': 'Property Number', 'comments': 'Extract the property/parcel number from the document'},
            {'key': 'total_amount', 'name': 'Total Amount', 'comments': 'The total dollar amount due'},
        ]
        
        This will create a model like:
        class DynamicAttributeExtraction(BaseModel):
            property_number: Optional[str] = Field(None, description="Property Number: Extract the property/parcel number from the document")
            total_amount: Optional[str] = Field(None, description="Total Amount: The total dollar amount due")
    """
    field_definitions = {}
    
    for attr in attributes:
        key = attr['key']
        name = attr['name']
        comments = attr.get('comments') or ''
        
        # Build description from name and helper text
        if comments:
            description = f"{name}: {comments}"
        else:
            description = f"Extract the value for '{name}' from the document."
        
        # All fields are Optional[str] with None default
        field_definitions[key] = (
            Optional[str],
            Field(None, description=description)
        )
    
    # Create the dynamic model
    DynamicModel = create_model(
        'DynamicAttributeExtraction',
        **field_definitions
    )
    
    return DynamicModel


class DocumentProcessor(BaseDocumentProcessor):
    """
    Sales document processor using LandingAI for extraction.
    Extracts key-value attributes from sales documents and saves them to the database.
    
    The processor dynamically builds a Pydantic schema based on the configured attributes
    for the document's input file, including any helper text/comments that guide extraction.
    """
    
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.pages_data = {}
        self.extracted_attributes = set()  # Track already extracted attributes to avoid duplicates
        
        # Initialize LandingAI client
        api_key = settings.LANDING_AI_API_KEY
        if not api_key:
            logger.error("LANDING_AI_API_KEY not found in settings or env.")
        
        self.client = LandingAIADE(apikey=api_key)
        
        # Build dynamic schema based on configured attributes
        self._build_dynamic_schema()

    def _build_dynamic_schema(self):
        """
        Build a dynamic extraction schema based on the configured attributes
        for this document's input file. Uses attribute name and comments (helper text)
        to create precise extraction instructions for LandingAI.
        """
        from account.models import FactAICInputFileAttributeSnapshot
        
        # Fetch configured attributes with all needed fields
        attribute_objects = FactAICInputFileAttributeSnapshot.objects.only(
            'id', 'name', 'type', 'gl_account', 'offset_gl_account', 'comments'
        ).filter(input_file_snapshot=self.document.input_file_snapshot)
        
        # Store attribute instances for later use when saving
        self.configured_attributes = {}
        attribute_configs = []
        
        for obj in attribute_objects:
            normalized_key = obj.name.lower().replace(" ", "_")
            self.configured_attributes[normalized_key] = obj
            
            attribute_configs.append({
                'key': normalized_key,
                'name': obj.name,
                'comments': obj.comments or ''  # Helper text for extraction,
            })
        
        # attribute_configs.append(
        #     {
        #         'key': 'page_number',
        #         'name': 'Page Number',
        #         'comments': 'The page number from which the attribute was extracted.'
        #     }
        # )
        # Create a list of attribute names for logging
        self.attribute_names = list(self.configured_attributes.keys())
        logger.info(f"Configured attributes for extraction: {self.attribute_names}")
        
        # Build the dynamic Pydantic model with attribute-specific descriptions
        if attribute_configs:
            self.DynamicExtractionModel = build_dynamic_extraction_model(attribute_configs)
            self.extraction_schema = pydantic_to_json_schema(self.DynamicExtractionModel)
            logger.info(f"Built dynamic schema with {len(attribute_configs)} fields")
        else:
            # Fallback to generic key-item schema if no attributes configured
            logger.warning("No attributes configured, using fallback KeyItemList schema")
            self.DynamicExtractionModel = None
            self.extraction_schema = pydantic_to_json_schema(KeyItemList)
    
    def __update_extraction_schema(self, key_items):
        """
        Update the extraction schema by removing attributes that have already been extracted.
        This optimizes subsequent page processing by only looking for remaining attributes.
        
        Args:
            key_items: List of extracted key-value pairs from the current page
        """
        import json
        
        if not self.extraction_schema:
            return
        
        # Convert JSON string to dict
        try:
            schema_dict = json.loads(self.extraction_schema) if isinstance(self.extraction_schema, str) else self.extraction_schema
        except json.JSONDecodeError:
            logger.error("Failed to parse extraction schema as JSON")
            return
        
        if 'properties' not in schema_dict:
            return
        
        # Remove extracted keys from the schema
        for item in key_items:
            key = item.get('key')
            value = item.get('value')
            if key and value and key in schema_dict.get('properties', {}):
                schema_dict['properties'].pop(key, None)
                # Also remove from 'required' if present
                if 'required' in schema_dict and key in schema_dict['required']:
                    schema_dict['required'].remove(key)
        
        # If no more properties to extract, set schema to None
        if not schema_dict.get('properties'):
            self.extraction_schema = None
        else:
            # Convert back to JSON string
            self.extraction_schema = json.dumps(schema_dict)
        
    
    def __generate_temp_file__(self, bytes_data):
        """Generate a temporary file from bytes for LandingAI processing."""
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=True)
        temp_pdf.write(bytes_data)
        temp_pdf.flush()
        return temp_pdf
    
    def __clean_temp_file__(self, temp_pdf):
        """Clean up temporary file."""
        try:
            temp_pdf.close()
        except Exception:
            pass

    def parse_pdf(self, pdf_path: str):
        """Parse PDF using LandingAI to extract markdown content."""
        parse_response = self.client.parse(
            document=Path(pdf_path),
            model=settings.LANDING_AI_ADE_MODEL,
        )
        return parse_response

    def process_document(self, file_bytes: bytes, mime_type: str = None, md: bool = False) -> Dict[str, any]:
        """
        Process the sales document by extracting key-value attributes from each page.
        
        Args:
            file_bytes: The PDF document bytes
            mime_type: MIME type of the document
            md: Whether to use markdown processing (not used in LandingAI pipeline)
            
        Returns:
            Dictionary containing processing status and statistics
        """
        page_bytes_list = split_pdf_to_pages(file_bytes)
        
        for i, page_bytes in enumerate(page_bytes_list):
            page_num = i + 1
            logger.info(f"Processing page {page_num}...")
            temp_file = None
            
            try:
                # Generate temporary file from page bytes
                temp_file = self.__generate_temp_file__(page_bytes)
                
                # Parse PDF to generate markdown
                parse_response = self.parse_pdf(temp_file.name)
                self.__clean_temp_file__(temp_file)
                temp_file = None
                
                markdown_content = parse_response.markdown
                
                if not markdown_content:
                    logger.warning(f"No markdown extracted for page {page_num}")
                    continue
                
                # Store markdown for reference
                self.pages_data[page_num] = {
                    "markdown": markdown_content,
                }
                
                # Extract key-value pairs using LandingAI
                extraction_response = self.client.extract(
                    schema=self.extraction_schema,
                    markdown=BytesIO(markdown_content.encode('utf-8'))
                )

                extracted_data = extraction_response.extraction

                key_items = self._convert_extraction_to_key_items(extracted_data)

                self.__update_extraction_schema(key_items)

                if self.extraction_schema is None:
                    logger.info("All attributes extracted, stopping further processing.")
                    # Still append current page results before breaking
                    page_result = {
                        "page_number": page_num,
                        "key_items": key_items
                    }
                    self.page_data.append(page_result)
                    break

                logger.info(f"Page {page_num}: Extracted {len(key_items)} key items")
                
                # Store page data
                page_result = {
                    "page_number": page_num,
                    "key_items": key_items
                }
                self.page_data.append(page_result)
                
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}")
                import sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                logger.error(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")
                
            finally:
                # Ensure temp file is cleaned up
                if temp_file:
                    self.__clean_temp_file__(temp_file)
        
        # Save document metadata
        self._save_doc_metadata()
        
        # Process and save extracted data
        processing_stats = self._save_extracted_data()
        
        return {
            "status": "success",
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }
    
    def _convert_extraction_to_key_items(self, extracted_data: Dict) -> List[Dict[str, str]]:
        """
        Convert extracted data to a unified key_items format.
        
        Handles both:
        1. Dynamic schema output: {'property_number': '12345', 'total_amount': '500.00'}
        2. Fallback KeyItemList output: {'key_items': [{'key': 'x', 'value': 'y'}]}
        
        Returns:
            List of {'key': str, 'value': str} dicts
        """
        key_items = []
        
        # Check if it's the fallback KeyItemList format
        if 'key_items' in extracted_data:
            return extracted_data.get('key_items', [])
        
        # Dynamic schema format - each field is a key with its value
        for key, value in extracted_data.items():
            if value is not None and str(value).strip() and str(value).strip().lower() != 'null':
                key_items.append({
                    'key': key,
                    'value': str(value).strip()
                })
        
        return key_items
    
    def _save_doc_metadata(self):
        """Save document-level metadata including markdown content."""
        self.document.markdown_metadata = self.pages_data
        self.document.save()

    def _parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """
        Parse amount string to Decimal.
        """
        if not amount_str or str(amount_str).strip() in ['', 'null', 'none', '-']:
            return None
        
        try:
            # Clean the amount string
            clean_amount = str(amount_str).replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            
            # Handle parentheses for negative amounts
            if clean_amount.startswith('-'):
                clean_amount = clean_amount[1:]
                return -Decimal(clean_amount)
            
            return Decimal(clean_amount)
            
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_str}': {e}")
        
        return amount_str

    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Save extracted data to database models.
        
        Returns:
            Dict with processing statistics
        """
        stats = {
            "key_items": 0,
            "skipped_extracted_attributes": 0,
            "duplicate_attributes_skipped": 0,
        }
        
        from account.models import MonthlyDocumentAttributeItem, FactAICInputFileAttributeSnapshot
        
        # Get configured attributes for this document
        configured_attribute_instances = {
            obj.name.lower().replace(" ", "_"): obj
            for obj in FactAICInputFileAttributeSnapshot.objects.only(
                'id', 'name', 'type', 'gl_account', 'offset_gl_account'
            ).filter(input_file_snapshot=self.document.input_file_snapshot)
        }
        
        with transaction.atomic():
            for page_result in self.page_data:
                page_number = page_result.get("page_number", 1)
                extracted_attributes_data = page_result.get("key_items", [])
                
                for extracted_attribute in extracted_attributes_data:
                    # Handle both dict format (from LandingAI) and Pydantic model format
                    if isinstance(extracted_attribute, dict):
                        extracted_key_name = extracted_attribute.get("key", "").lower().replace(" ", "_")
                        extracted_value = extracted_attribute.get("value", "")
                    else:
                        extracted_key_name = getattr(extracted_attribute, 'key', "").lower().replace(" ", "_")
                        extracted_value = getattr(extracted_attribute, 'value', "")
                    
                    # Skip if this attribute was already extracted from a previous page
                    if extracted_key_name in self.extracted_attributes:
                        stats["duplicate_attributes_skipped"] += 1
                        continue
                    
                    # Find matching configured attribute
                    attribute_instance = configured_attribute_instances.get(extracted_key_name)
                    
                    extracted_value = self._parse_amount(extracted_value)
                    if attribute_instance and extracted_value:
                        MonthlyDocumentAttributeItem.objects.create(
                            document=self.document,
                            attribute=attribute_instance,
                            page_number=page_number,
                            value=extracted_value,
                            transaction_type=attribute_instance.type,
                            gl_account=attribute_instance.gl_account,
                            offset_gl_account=attribute_instance.offset_gl_account,
                        )
                        
                        # Mark this attribute as extracted to avoid duplicates
                        self.extracted_attributes.add(extracted_key_name)
                        stats["key_items"] += 1
            
            # Create empty entries for configured attributes that weren't found
            for attr_name, attr_obj in configured_attribute_instances.items():
                if attr_name not in self.extracted_attributes:
                    logger.info(f"Saving empty attribute for missing: {attr_name}")
                    MonthlyDocumentAttributeItem.objects.create(
                        document=self.document,
                        attribute=attr_obj,
                        page_number=1,
                        value="",
                        transaction_type=attr_obj.type,
                        gl_account=attr_obj.gl_account,
                        offset_gl_account=attr_obj.offset_gl_account,
                    )
                    stats["skipped_extracted_attributes"] += 1
        
        logger.info(f"Saved extracted data: {stats}")
        return stats
