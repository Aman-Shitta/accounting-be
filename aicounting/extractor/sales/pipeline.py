import re
import os, sys
import json
from django.db import transaction
from typing import List, Dict
from extractor.base import (
    BaseDocumentProcessor,
    JSONCleaner
)
from extractor.prompter import (
    Configuration,
)

from account.models import (
    MonthlyAccountingDocument
)
import logging
from google.genai import types

logger = logging.getLogger(__name__)


class TransactionExtractor:
    
    def __init__(self, processor, schema, prompt):
        self.processor = processor
        self.schema = schema
        self.prompt = prompt

    def extract(self, page_bytes, mime_type):
        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
            f"{self.prompt}"
        ]
        config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        }
        try:
            stream_response = self.processor.generate_content_stream(
                contents=[content],
                config=config
            )
            raw = ""
            for resp in stream_response:
                raw += resp.text
        except Exception as te:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Transaction Stream error: {te}")
            return {}

        try:
            clean_json_str = JSONCleaner.clean(raw)
            parsed_data = json.loads(clean_json_str)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Transaction extraction failed: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw output: {raw}")
            parsed_data = {}

        for item in parsed_data.get("line_items", []):
            desc = item.get("description", "").lower()
            if "check" in desc or "cheque" in desc:
                item["is_check_transaction"] = True
                match = re.search(r"check\s*#?\s*(\d+)", desc)
                if match:
                    item["check_number"] = match.group(1)
                else:
                    item["check_number"] = ""
            else:
                item["is_check_transaction"] = False
                item["check_number"] = ""

        return parsed_data


class DocumentProcessor(BaseDocumentProcessor):

    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        
        # Define the transaction extraction schema
        self.ai_schema = \
            types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "key_items": {
                        "type": types.Type.ARRAY,
                        "items": {
                            "type": types.Type.OBJECT,
                            "properties": {
                                "key": {"type": types.Type.STRING},
                                "value": {"type": types.Type.STRING},
                            },
                            "required": ["key", "value"]
                        }
                    }
                },
                required=["key_items"]
            )
        self.page_data = list()
        self.extracted_attributes = set()  # Track already extracted attributes to avoid duplicates
        self.transaction_extractor = TransactionExtractor(self, self.ai_schema, self.prompt)

    def process_document(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages

        page_bytes_list = split_pdf_to_pages(file_bytes)
    
        for i, page_bytes in enumerate(page_bytes_list):
            try:
                parsed_data = self.transaction_extractor.extract(page_bytes, mime_type)
                
                # Store page data with page number
                page_result = {
                    "page_number": i + 1,
                    "key_items": parsed_data.get("key_items", [])
                }
                self.page_data.append(page_result)
                
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception during processing page {i+1}: {e}")
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page bytes: {page_bytes[:20]}")
        
        # Process and save extracted data
        processing_stats = self._save_extracted_data()
        return {
            "status": "success",
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }
    
    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Save extracted data to database models.
        
        Args:
            self.page_data: List of page data from processor
            
        Returns:
            Dict with processing statistics
        """
        stats = {
            "key_items": 0,
            "skipped_extracted_attributes": 0,
            "duplicate_attributes_skipped": 0,
        }
        from account.models import MonthlyDocumentAttributeItem, FactAICInputFileAttributeSnapshot

        with transaction.atomic():
            for page_result in self.page_data:
                page_number = page_result.get("page_number", 1)
                attributes_data = page_result.get("key_items", [])
                
                for attribute in attributes_data:
                    key_name = attribute.get("key", "")
                    
                    # Skip if this attribute was already extracted from a previous page
                    if key_name in self.extracted_attributes:
                        stats["duplicate_attributes_skipped"] += 1
                        continue

                    attribute_obj = FactAICInputFileAttributeSnapshot.objects.filter(
                        input_file_snapshot=self.document.input_file_snapshot,
                        name=key_name
                    ).first()

                    if not attribute_obj:
                        stats["skipped_extracted_attributes"] += 1
                        continue

                    MonthlyDocumentAttributeItem.objects.create(
                        document=self.document,
                        attribute=attribute_obj,
                        page_number=page_number,
                        value=attribute.get("value", ""),
                        transaction_type=attribute_obj.type,
                        gl_account=attribute_obj.gl_account,
                        offset_gl_account=attribute_obj.offset_gl_account,
                    )
                    
                    # Mark this attribute as extracted to avoid duplicates
                    self.extracted_attributes.add(key_name)
                    stats["key_items"] += 1

        logger.info(f"Saved extracted data: {stats}")
        return stats