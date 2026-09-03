import re
import os
import sys
import json
from django.db import transaction
from typing import List, Dict, Any
from extractor.base import GeminiDocumentProcessor
from extractor.utils import JSONHelper, detect_check_transaction
from extractor.prompter import (
    Configuration,
    prepare_prompt,
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
            logger.error(
                f"[ERROR][{fname}:{exc_tb.tb_lineno}] Transaction Stream error: {te}")
            return {}

        parsed_data = JSONHelper.parse_json(raw, default={})

        for item in parsed_data.get("line_items", []):
            item.update(detect_check_transaction(item.get("description", "")))

        return parsed_data


class DocumentProcessor(GeminiDocumentProcessor):

    def __init__(self, doc: MonthlyAccountingDocument):
        super().__init__(doc)
        config = Configuration.from_document(doc)
        self.prompt = prepare_prompt(config)

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
        # Track already extracted attributes to avoid duplicates
        self.extracted_attributes = set()
        self.transaction_extractor = TransactionExtractor(
            self, self.ai_schema, self.prompt
        )

    def process_document(self, file_bytes: bytes, **kwargs) -> Dict[str, Any]:
        from extractor.utils import split_pdf_to_pages
        from extractor.persistence.attribute_saver import AttributeSaver

        mime_type = kwargs.get('mime_type', 'application/pdf')
        md = kwargs.get('md', False)

        page_bytes_list = split_pdf_to_pages(file_bytes)
        saver = AttributeSaver(self.document)

        for i, page_bytes in enumerate(page_bytes_list):
            try:
                parsed_data = self.transaction_extractor.extract(
                    page_bytes, mime_type)
                # Store page data with page number
                page_result = {
                    "page_number": i + 1,
                    "key_items": parsed_data.get("key_items", [])
                }
                self.page_data.append(page_result)

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                logger.error(
                    f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception during processing page {i+1}: {e}")
                logger.error(
                    f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page bytes: {page_bytes[:20]}")

        # Process and save extracted data using centralized saver
        processing_stats = saver.save_attributes(self.page_data)
        
        return {
            "status": "success",
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }
