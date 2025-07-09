import json
import re
import unicodedata
from typing import Any

from google import genai
from google.genai import types

import importlib
from document.pipeline.prompter import (
    Configuration,
    prepare_prompt,
    
)

from django.conf import settings
import sys
import logging

class DocumentProcessor:
    def __init__(self, config: Configuration):
        self.client = None
        self.model = "gemini-2.0-flash"
        self.validator = None
        self.page_data = []

        self.doc_type: str = config.doc_type # "bank_statement"
        self.prompt = prepare_prompt(config)

        self.doc_config = config
        self.api_key = settings.GEMINI_API_KEY
    
        self.init_ai_clientel()
        self.control_totals = {}

        self.response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "key_items": {
                    "type": types.Type.OBJECT,
                    "properties": {
                        "key": {"type": types.Type.STRING},
                        "value": {"type": types.Type.STRING},
                    }                },
                "line_items": {
                    "type": types.Type.ARRAY,
                    "items": {
                        "type": types.Type.OBJECT,
                        "properties": {
                            "date": {"type": types.Type.STRING},
                            "description": {"type":types.Type.STRING},
                            "debit_amount": {"type": types.Type.STRING, "nullable": True},
                            "credit_amount": {"type": types.Type.STRING, "nullable": True}
                        },
                        "required": ["date", "description"]
                    }
                }
            },
            required=["line_items"]
        )


    def init_ai_clientel(self):
        self.model = "gemini-2.0-flash"
        self.client = genai.Client(api_key=self.api_key)


    def __prepare_summarizer__(self):
        """
        Dynamically imports the validator module and retrieves the validator class
        based on the document type. For example, for doc_type "bank_statement", it
        imports module "validator.bank_statement_validator" and returns "BankStatementValidator".
        """
        try:
            # Build the module name: e.g. "validator.bank_statement_validator"
            module_name = f"document.pipeline.summarizer.{self.doc_type}"
            mod = importlib.import_module(module_name)
            # Build the expected class name based on naming convention
            class_name = "".join(word.capitalize() for word in self.doc_type.split("_")) + "Summarizer"
            validator_cls = getattr(mod, class_name, None)
            if not validator_cls:
                print(f"Validator class '{class_name}' not found in module '{module_name}'.")
            return validator_cls
        except Exception as e:
            print(f"Error importing validator for doc_type '{self.doc_type}': {e}")
            return None


    def process_document(self, file_bytes: bytes, mime_type: str = "application/pdf") -> Any:
        try:
            self.process_pages(file_bytes, mime_type)

            # Dynamically determine and initialize the validator based on doc_type
            summary_cls = self.__prepare_summarizer__()
            if summary_cls:
                self.summarizer = summary_cls(self.client, self.model)
            
            self.control_totals = self.summarizer.generate_statement_summary(file_bytes)

        except Exception as e:
            print(f"Failed to process document: {str(e)}")
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)

        return self.page_data, self.control_totals

    def process_pages(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages

        page_bytes_list = split_pdf_to_pages(file_bytes)
        previous_page_context = ""

        for i, page_bytes in enumerate(page_bytes_list):
            try:
                content = [
                    types.Part.from_bytes(
                        data=page_bytes,
                        mime_type=mime_type,
                    ),
                    f"{self.prompt}\n**Previous page context: {previous_page_context}\nExtract data from current page only."
                ]

                config: types.GenerateContentConfigDict = {
                    "response_schema": self.response_schema,
                    "response_mime_type":"application/json"
                }
                stream_response = self.client.models.generate_content_stream(
                    model=self.model,
                    contents=[content],
                    config=config,
                )

                raw = ""
                for resp in stream_response:
                    raw += resp.text

                clean_json_str = self._clean_json_string(raw)

                parsed_data = json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] JSONDecodeError: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response : {raw}")
                parsed_data = {}

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Exception: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response: {raw}")
                parsed_data = {}

            try:
                print(f"[DEBUG] Page {i+1}: Parsed data before processing: {parsed_data}")
                processed_data = self._process_gemini_output(parsed_data)

                self.page_data.append({"page_{}".format(i + 1): processed_data})

                previous_page_context = str(processed_data)
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Exception during processing: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response: {raw}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Parsed data: {parsed_data}")
                parsed_data = {}

    def _clean_json_string(self, raw: str) -> str:
        try:
            # Remove Markdown fences and leading/trailing whitespace
            raw = re.sub(r'^```(?:json)?', '', raw)
            raw = raw.strip('` \n')

            # Normalize line endings
            raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')

            raw = raw.replace("None", "null")

            # Remove control characters (except tab and newline)
            raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print(f"[ERROR][Line {exc_tb.tb_lineno}] Cleaning JSON: {e}")
            print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw input: {raw}")

        return raw

    def _process_gemini_output(self, data: dict) -> dict:
        # if "data" not in data:
        #     raise ValueError("Missing 'data' field in Gemini output")

        # Add extra info
        data["extra_info"] = "Processed by LLM"

        meta = data.get("meta", {})
        if isinstance(meta, dict) and isinstance(meta.get("pages"), (int, float)):
            if meta["pages"] != 1:
                print("Warning: Expected 1 page, got", meta["pages"])

        return data