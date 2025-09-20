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
        self.transaction_extractor = TransactionExtractor(self, self.ai_schema, self.prompt)

    def process_document(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages


        # page_bytes_list = split_pdf_to_pages(file_bytes)
    
        # for i, page_bytes in enumerate(page_bytes_list):
        try:
            parsed_data = self.transaction_extractor.extract(file_bytes, mime_type)
            self.page_data = parsed_data
            pass
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception during processing: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page bytes: {file_bytes[:20]}")
        
        # Process and save extracted data
        processing_stats = self._save_extracted_data()
        return {
            "status": "success",
            "control_totals": self.control_totals,
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }
    
    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Save extracted data to database models.
        
        Args:
            page_data: List of page data from processor
            
        Returns:
            Dict with processing statistics
        """
        stats = {
            "key_items": 0,
            "line_items": 0,
            "check_items": 0,
            "pages_processed": 0
        }
        page_data = self.page_data
        with transaction.atomic():
            for page_idx, page_item in enumerate(page_data):
                pass

        logger.info(f"Saved extracted data: {stats}")
        return stats