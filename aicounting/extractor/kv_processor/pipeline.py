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
        ]
        gemini_config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "system_instruction": [self.prompt]
        }
        try:
            stream_response = self.processor._generate_content_stream(
                contents=[content],
                config=gemini_config
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

    def process_document(self, file_bytes: bytes, mime_type: str, md: bool) -> Dict[str, any]:
        from extractor.utils import split_pdf_to_pages

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

        configured_attribute_instances = {
            obj.name.lower().replace(" ", "_"): obj
            for obj in FactAICInputFileAttributeSnapshot.objects.only('id', 'name', 'type', 'gl_account', 'offset_gl_account')
                .filter(input_file_snapshot=self.document.input_file_snapshot)
        }

        with transaction.atomic():
            for page_result in self.page_data:
                page_number = page_result.get("page_number", 1)
                extracted_attributes_data = page_result.get("key_items", [])
                for extracted_attribute in extracted_attributes_data:
                    extracted_key_name = extracted_attribute.get("key", "").lower().replace(" ", "_")
                    
                    # Skip if this attribute was already extracted from a previous page
                    if extracted_key_name in self.extracted_attributes:
                        stats["duplicate_attributes_skipped"] += 1
                        continue

                    attribute_instance = configured_attribute_instances.get(extracted_key_name)

                    if attribute_instance and (extracted_attribute.get("value").strip() and extracted_attribute.get("value").strip().lower() != "null"):
                        MonthlyDocumentAttributeItem.objects.create(
                            document=self.document,
                            attribute=attribute_instance,
                            page_number=page_number,
                            value=extracted_attribute.get("value", ""),
                            transaction_type=attribute_instance.type,
                            gl_account=attribute_instance.gl_account,
                            offset_gl_account=attribute_instance.offset_gl_account,
                        )

                        # Mark this attribute as extracted to avoid duplicates
                        self.extracted_attributes.add(extracted_key_name)
                        stats["key_items"] += 1

            for attr_name, attr_obj in configured_attribute_instances.items():
                if attr_name not in self.extracted_attributes:
                    print("Saving empty attribute for missing: ", attr_name)
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

        logger.error(f"Saved extracted data: {stats}")
        return stats
