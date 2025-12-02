from __future__ import annotations

import os
import logging
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Optional

from django.conf import settings
from django.db import transaction

from pydantic import BaseModel, Field
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


class DocumentProcessor(BaseDocumentProcessor):
    """
    Sales document processor using LandingAI for extraction.
    Extracts key-value attributes from sales documents and saves them to the database.
    """
    
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.pages_data = {}
        self.extracted_attributes = set()  # Track already extracted attributes to avoid duplicates
        
        # Initialize LandingAI client
        api_key = settings.LANDING_AI_API_KEY
        if not api_key:
            logger.warning("LANDING_AI_API_KEY not found in settings or env.")
        
        self.client = LandingAIADE(apikey=api_key)
        
        # Prepare extraction schema for key items
        self.key_item_schema = pydantic_to_json_schema(KeyItemList)
        
        # Build dynamic schema based on configured attributes
        self._build_dynamic_schema()

    def _build_dynamic_schema(self):
        """
        Build a dynamic extraction schema based on the configured attributes
        for this document's input file.
        """
        from account.models import FactAICInputFileAttributeSnapshot
        
        self.configured_attributes = {
            obj.name.lower().replace(" ", "_"): obj
            for obj in FactAICInputFileAttributeSnapshot.objects.only(
                'id', 'name', 'type', 'gl_account', 'offset_gl_account'
            ).filter(input_file_snapshot=self.document.input_file_snapshot)
        }
        
        # Create a list of attribute names for the extraction prompt
        self.attribute_names = list(self.configured_attributes.keys())
        logger.info(f"Configured attributes for extraction: {self.attribute_names}")

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
            model="dpt-2-latest"
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
                    schema=self.key_item_schema,
                    markdown=BytesIO(markdown_content.encode('utf-8'))
                )
                
                extracted_data = extraction_response.extraction
                key_items = extracted_data.get("key_items", [])
                
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
    
    def _save_doc_metadata(self):
        """Save document-level metadata including markdown content."""
        self.document.markdown_metadata = self.pages_data
        self.document.save()

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
                    
                    if attribute_instance and extracted_value and extracted_value.strip() and extracted_value.strip().lower() != "null":
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
