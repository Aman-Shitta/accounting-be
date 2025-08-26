# System imports
import importlib
import json
import os
import re
import sys
import time
import unicodedata


# Third-party imports
from django.conf import settings
from google import genai
from google.genai import types

# Local imports
from extractor.bank_statement.prompter import (
    Configuration,
    prepare_prompt,
)

class JSONCleaner:
    @staticmethod
    def clean(raw: str) -> str:
        try:
            raw = re.sub(r'^```(?:json)?', '', raw)
            raw = raw.strip('` \n')
            raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')
            raw = raw.replace('\'', '\\\'')
            raw = raw.replace("None", "")
            raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')
            raw = re.sub(r"(?<!\\)'", '"', raw)
            raw = re.sub(r',(\s*[}\]])', r'\1', raw)
            first_brace = raw.find('{')
            if first_brace > 0:
                raw = raw[first_brace:]
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Cleaning JSON: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw input: {raw}")
        return raw

    @staticmethod
    def extract_first_json(raw: str) -> str:
        try:
            match = re.search(r'(\{[\s\S]*\})', raw)
            if match:
                return match.group(1)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Extracting first JSON: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw input: {raw}")
        return raw

class AIClient:
    def __init__(self, api_key: str, model: str):
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def generate_content_stream(self, contents, config):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                # Check for 503 UNAVAILABLE error
                if hasattr(e, "args") and e.args and "503" in str(e.args[0]):
                    print(f"[WARN][{fname}:{exc_tb.tb_lineno}] Gemini model overloaded (503). Retry {attempt+1}/{max_retries} after 5s...")
                    time.sleep(5)
                    continue
                else:
                    print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] AIClient generate_content_stream error: {e}")
                    raise
        # If all retries failed, raise the last exception
        raise Exception("Gemini model overloaded after multiple retries.")

class PageClassifier:
    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client
        self.schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "page_types": {
                    "type": types.Type.ARRAY,
                    "items": {"type": types.Type.STRING}
                }
            },
            required=["page_types"]
        )

    def classify(self, page_bytes, mime_type):
        classification_prompt = """
        Classify this page as one or more of the following types (return a JSON array in 'page_types' key):
        - transaction_table
        - check_images
        - summary_table
        - other
        If multiple types are present, include all. Example output: {\"page_types\": [\"transaction_table\", \"check_images\"]}
        """
        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
            classification_prompt
        ]
        config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "top_p": 0.8,
            "top_k": 20,
        }
        try:
            stream_response = self.ai_client.generate_content_stream(content, config)
            raw = ""
            for resp in stream_response:
                raw += resp.text
            try:
                clean_json_str = JSONCleaner.clean(raw)
                try:
                    parsed = json.loads(clean_json_str)
                except Exception:
                    fallback_json = JSONCleaner.extract_first_json(clean_json_str)
                    parsed = json.loads(fallback_json)
                return parsed.get("page_types", [])
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page classification failed: {e} :: for \n -------------------------\n{raw}\n -------------------------\n")
                return ["other"]
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception in classify: {e}")
            return ["other"]

class TransactionExtractor:
    def __init__(self, ai_client: AIClient, schema, prompt):
        self.ai_client = ai_client
        self.schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "key_items": {
                    "type": types.Type.OBJECT,
                    "properties": {
                        "key": {"type": types.Type.STRING},
                        "value": {"type": types.Type.STRING},
                    }
                },
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
        self.prompt = prompt

    def extract(self, page_bytes, mime_type, previous_page_context):
        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
            f"{self.prompt}\n**Previous page context: {previous_page_context}\nExtract data from current page only."
        ]
        config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        }
        try:
            stream_response = self.ai_client.generate_content_stream(content, config)
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

class CheckImageExtractor:
    def __init__(self, ai_client: AIClient):
        self.ai_client = ai_client

        self.schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "checks": {
                    "type": types.Type.ARRAY,
                    "items": {
                        "type": types.Type.OBJECT,
                        "properties": {
                            "amount": {"type": types.Type.STRING},
                            "payee": {"type": types.Type.STRING},
                            "memo": {"type": types.Type.STRING, "nullable": True},
                            "clearing_date": {"type": types.Type.STRING, "nullable": True},
                            "passing_date": {"type": types.Type.STRING, "nullable": True},
                            "check_number": {"type": types.Type.STRING, "nullable": True},
                        },
                        "required": ["amount", "payee", "check_number"]
                    }
                }
            },
            required=["checks"]
        )

    def extract(self, page_bytes, mime_type):
        check_image_prompt = """
        Extract all check images and for each, return a JSON object with: amount, payee, memo (optional), clearing_date, passing_date, check_number. Output as a list under 'checks'. If not found, return an empty list.
        Example: {\"checks\": [{\"amount\": "123.45", \"payee\": "John Doe", ...}]}

        Ensure:
        - All amounts are extracted as float or numeric values (no currency symbols).
        - The result is a single flat JSON object with the above 4 keys only.
        - If a field is missing, set its value as `null`.
        """

        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
            check_image_prompt
        ]
        config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.1,
        }
        try:
            stream_response = self.ai_client.generate_content_stream(content, config)
            raw = ""
                
            for resp in stream_response:
                raw += resp.text
        except Exception as ce:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Check Stream error: {ce}")
            return {}

        try:
            clean_json_str = JSONCleaner.clean(raw)
            parsed_data = json.loads(clean_json_str)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Check image extraction failed: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw output: {raw}")
            parsed_data = {"checks": []}
        return parsed_data

class SummarizerLoader:
    @staticmethod
    def load(doc_type, ai_client, model):
        try:
            module_name = f"extractor.bank_statement.summarizer"
            mod = importlib.import_module(module_name)
            class_name = "".join(word.capitalize() for word in doc_type.split("_")) + "Summarizer"
            summarizer_cls = getattr(mod, class_name, None)
            if not summarizer_cls:
                print(f"Summarizer class '{class_name}' not found in module '{module_name}'.")
            return summarizer_cls(ai_client.client, model) if summarizer_cls else None
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Error importing summarizer for doc_type '{doc_type}': {e}")
            return None

class DocumentProcessor:
    def __init__(self, config: Configuration):
        self.doc_type: str = config.doc_type
        self.prompt = prepare_prompt(config)
        self.doc_config = config
        self.api_key = settings.GEMINI_API_KEY
        self.model = "gemini-2.0-flash"
        self.page_data = []
        self.control_totals = {}

        # Define the transaction extraction schema
        self.transaction_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "key_items": {
                    "type": types.Type.OBJECT,
                    "properties": {
                        "key": {"type": types.Type.STRING},
                        "value": {"type": types.Type.STRING},
                    }
                },
                "line_items": {
                    "type": types.Type.ARRAY,
                    "items": {
                        "type": types.Type.OBJECT,
                        "properties": {
                            "date": {"type": types.Type.STRING},
                            "description": {"type": types.Type.STRING},
                            "debit_amount": {"type": types.Type.STRING, "nullable": True},
                            "credit_amount": {"type": types.Type.STRING, "nullable": True}
                        },
                        "required": ["date", "description"]
                    }
                }
            },
            required=["line_items"]
        )

        # AI Client and helpers
        self.ai_client = AIClient(self.api_key, self.model)
        self.page_classifier = PageClassifier(self.ai_client)
        self.transaction_extractor = TransactionExtractor(self.ai_client, self.transaction_schema, self.prompt)
        self.check_image_extractor = CheckImageExtractor(self.ai_client)

    def process_document(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages

        page_bytes_list = split_pdf_to_pages(file_bytes)
        previous_page_context = ""
    
        for i, page_bytes in enumerate(page_bytes_list):
            try:
                # 1. Classify the page
                page_types = self.page_classifier.classify(page_bytes, mime_type)
                print(f"\n\n[DEBUG] Page {i+1} classified as: {page_types}")
                page_result = {"page_types": page_types}

                # 2. Extract data based on classification
                if "transaction_table" in page_types:
                    parsed_data = self.transaction_extractor.extract(page_bytes, mime_type, previous_page_context)
                    page_result["transactions"] = parsed_data
                    previous_page_context = str(parsed_data)

                if "check_images" in page_types:
                    parsed_data = self.check_image_extractor.extract(page_bytes, mime_type)
                    page_result["check_data"] = parsed_data

                if "summary_table" in page_types and not self.control_totals:
                    summarizer = SummarizerLoader.load(self.doc_type, self.ai_client, self.model)
                    if summarizer:
                        summary = summarizer.generate_statement_summary(page_bytes)
                        self.control_totals = summary

                self.page_data.append({f"page_{i+1}": page_result})
                print(f"[DEBUG] Page {i+1} data is: {page_result}")
                time.sleep(3)

            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception during processing: {e}")
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page bytes: {page_bytes[:20]}")
                continue

    def _process_gemini_output(self, data: dict) -> dict:
        data["extra_info"] = "Processed by LLM"
        meta = data.get("meta", {})
        if isinstance(meta, dict) and isinstance(meta.get("pages"), (int, float)):
            if meta["pages"] != 1:
                print("Warning: Expected single page output, but got multiple pages in Gemini response.")
                data["warning"] = "Expected single page output, but got multiple pages in Gemini response."
        return data

    def get_control_totals(self):
        return self.control_totals

    def get_page_data(self):
        return self.page_data

    def get_summary(self):
        if self.control_totals:
            return {
                "total_income": self.control_totals.get("total_income", 0),
                "total_expense": self.control_totals.get("total_expense", 0),
                "net_income": self.control_totals.get("net_income", 0),
            }
        return {}