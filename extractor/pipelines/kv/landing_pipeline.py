from __future__ import annotations

import re
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
from account.models import (
    MonthlyAccountingDocument
)
from extractor.utils import split_pdf_to_pages, generate_temp_pdf, clean_temp_file

logger = logging.getLogger(__name__)


"""
Pydantic Models for Sales Document Extraction Schemas
"""

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

    def __init__(self, doc: MonthlyAccountingDocument):
        super().__init__(doc)
        self.page_data = []
        self.pages_data = {}
        # Track already extracted attributes to avoid duplicates
        self.extracted_attributes = set()

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
        logger.info(
            f"Configured attributes for extraction: {self.attribute_names}")

        # Build the dynamic Pydantic model with attribute-specific descriptions
        if attribute_configs:
            self.DynamicExtractionModel = build_dynamic_extraction_model(
                attribute_configs)
            self.extraction_schema = pydantic_to_json_schema(
                self.DynamicExtractionModel)
            logger.info(
                f"Built dynamic schema with {len(attribute_configs)} fields")
        else:
            # Fallback to generic key-item schema if no attributes configured
            logger.warning(
                "No attributes configured, using fallback KeyItemList schema")
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
            schema_dict = json.loads(self.extraction_schema) if isinstance(
                self.extraction_schema, str) else self.extraction_schema
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
        return generate_temp_pdf(bytes_data)

    def __clean_temp_file__(self, temp_pdf):
        """Clean up temporary file."""
        clean_temp_file(temp_pdf)

    def parse_pdf(self, pdf_path: str):
        """Parse PDF using LandingAI to extract markdown content."""
        parse_response = self.client.parse(
            document=Path(pdf_path),
            model=settings.LANDING_AI_ADE_MODEL,
        )
        return parse_response

    def process_document(self, file_bytes: bytes, **kwargs) -> Dict[str, Any]:
        """
        Process the sales document by extracting key-value attributes from each page.
        """
        from extractor.persistence.attribute_saver import AttributeSaver

        mime_type = kwargs.get('mime_type', 'application/pdf')
        md = kwargs.get('md', False)
        special_rules = kwargs.get('special_rules', "")

        page_bytes_list = split_pdf_to_pages(file_bytes)
        saver = AttributeSaver(self.document)

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
                    logger.warning(
                        f"No markdown extracted for page {page_num}")
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

                key_items = self._convert_extraction_to_key_items(
                    extracted_data)

                self.__update_extraction_schema(key_items)

                if self.extraction_schema is None:
                    logger.info(
                        "All attributes extracted, stopping further processing.")
                    # Still append current page results before breaking
                    page_result = {
                        "page_number": page_num,
                        "key_items": key_items
                    }
                    self.page_data.append(page_result)
                    break

                logger.info(
                    f"Page {page_num}: Extracted {len(key_items)} key items")

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
                logger.error(
                    f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

            finally:
                # Ensure temp file is cleaned up
                if temp_file:
                    self.__clean_temp_file__(temp_file)

        # Save document metadata
        self._save_doc_metadata()

        # Process and save extracted data
        processing_stats = saver.save_attributes(self.page_data)

        return {
            "status": "success",
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }

    def _convert_extraction_to_key_items(self, extracted_data: Dict) -> List[Dict[str, str]]:
        """
        Convert extracted data to a unified key_items format.
        """
        key_items = []

        if 'key_items' in extracted_data:
            return extracted_data.get('key_items', [])

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
