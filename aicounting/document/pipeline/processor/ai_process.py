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

class DocumentProcessor:
    def __init__(self, config: Configuration):
        self.client = None
        self.model = "gemini-2.0-flash"
        self.validator = None
        self.page_data = []

        self.doc_type: str = config.doc_type # "bank_statement"
        self.prompt = prepare_prompt(config)

        self.doc_config = config
        self.api_key = "REDACTED-GOOGLE-API-KEY"
    
        self.init_ai_clientel()
        self.control_totals = {}

    def init_ai_clientel(self):
        self.model = "gemini-2.0-flash"
        self.client = genai.Client(api_key=self.api_key)


    def __prepare_validator__(self):
        """
        Dynamically imports the validator module and retrieves the validator class
        based on the document type. For example, for doc_type "bank_statement", it
        imports module "validator.bank_statement_validator" and returns "BankStatementValidator".
        """
        try:
            # Build the module name: e.g. "validator.bank_statement_validator"
            module_name = f"document.pipeline.validator.{self.doc_type}"
            mod = importlib.import_module(module_name)
            # Build the expected class name based on naming convention
            class_name = "".join(word.capitalize() for word in self.doc_type.split("_")) + "Validator"
            validator_cls = getattr(mod, class_name, None)
            if not validator_cls:
                print(f"Validator class '{class_name}' not found in module '{module_name}'.")
            return validator_cls
        except Exception as e:
            print(f"Error importing validator for doc_type '{self.doc_type}': {e}")
            return None


    def _validate_data(self, file_bytes) -> bool:

        summary_response = self.validator.generate_transaction_summary(file_bytes)
        aggregated = self.validator.aggregate_page_totals(self.page_data)
        if (
            summary_response.get("Total Debits") is not None
            and summary_response.get("Total Credits") is not None
        ):
            if (
                float(summary_response["Total Debits"]) != aggregated.get("Total Debits", 0)
                or float(summary_response["Total Credits"]) != aggregated.get("Total Credits", 0)
            ):
                print("Warning: Aggregated totals do not match the summary from LLM.")
   
        # Append the summary verification to the output
        
        
        self.control_totals = {
            "transaction_summary": summary_response,
            "aggregated_totals": aggregated
        }

    def process_document(self, file_bytes: bytes, mime_type: str = "application/pdf") -> Any:
        try:
            self.process_pages(file_bytes, mime_type)

            # Dynamically determine and initialize the validator based on doc_type
            validator_cls = self.__prepare_validator__()
            if validator_cls:
                self.validator = validator_cls(self.client, self.model)
                self._validate_data(file_bytes)

            return self.page_data, self.control_totals
        except Exception as e:
            raise RuntimeError(f"Failed to process document: {str(e)}")

    def process_pages(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages

        page_bytes_list = split_pdf_to_pages(file_bytes)
        previous_page_context = ""

        for i, page_bytes in enumerate(page_bytes_list):
            content = [
                types.Part.from_bytes(
                    data=page_bytes,
                    mime_type=mime_type,
                ),
                f"{self.prompt}\n**Previous page context: {previous_page_context}\nExtract data from current page only."
            ]

            stream_response = self.client.models.generate_content_stream(
                model=self.model,
                contents=[content],
            )

            raw = ""
            print("stream_response :: ", stream_response)
            for resp in stream_response:
                raw += resp.text

            clean_json_str = self._clean_json_string(raw)
            try:
                parsed_data = json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                print(f"JSONDecodeError: {e}")
                print(f"Raw response: {raw}")
                parsed_data = {}

            processed_data = self._process_gemini_output(parsed_data)

            self.page_data.append({"page_{}".format(i + 1): processed_data})

            # Update previous page context (customize as needed)
            previous_page_context = str(processed_data)

    def _clean_json_string(self, raw: str) -> str:
        # Remove Markdown fences and leading/trailing whitespace
        raw = re.sub(r'^```(?:json)?', '', raw)
        raw = raw.strip('` \n')

        # Normalize line endings
        raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')

        raw = raw.replace("None", "null")

        # Remove control characters (except tab and newline)
        raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')

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