
import os, sys
import json
from extractor.base import JSONCleaner

from google.genai import types


class PageClassifier:
    
    def __init__(self, processor):
        self.processor = processor
        self.schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "page_types": {
                    "type": types.Type.ARRAY,
                    "items": types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "type": types.Schema(type=types.Type.STRING),
                            "confidence": types.Schema(type=types.Type.NUMBER)
                        },
                        required=["type", "confidence"]
                    )
                }
            },
            required=["page_types"]
        )

    def classify(self, md_bytes=None, page_bytes=None, mime_type=None):
        """
        Classify page content using markdown text for better LLM understanding.
        Falls back to PDF if markdown is not available.
        
        Args:
            md_bytes: Markdown content bytes (preferred)
            page_bytes: PDF page bytes (fallback)
            mime_type: MIME type for PDF fallback
        """
        classification_prompt = """
        You are analyzing a bank statement page. Based on the content, classify this page into one or more categories:

        **Page Types:**
        - transaction_table: Contains transaction listings with dates, descriptions, amounts, debits/credits
        - check_table: Contains transaction listings specifically for checks
        - check_images: Contains images or details of cleared checks with check numbers, payees, amounts
        - summary_table: Contains account summaries, beginning/ending balances, totals, or statement overview
        - other: Any other content not fitting the above categories

        **Analysis Guidelines:**
        - Look for table structures, headers, repeated patterns
        - Transaction tables have columns like Date, Description, Debit, Credit, Balance
        - Check images have check numbers, payee names, amounts, memo fields
        - Summary tables have totals, balances, account information
        - A page can have multiple types (e.g., both transactions and summary)
        - Provide a confidence score (0.0-1.0) for your classification

        **Output Format:**
        Return JSON with:
        - page_types: Array of detected types

        Example: {"page_types": [{"type": "transaction_table", "confidence": 0.95}, {"type": "summary_table", "confidence": 0.85}]}
        """
        
        # Prefer markdown over PDF for classification
        if md_bytes:
            print(f"[DEBUG] Classifying page using markdown content ({len(md_bytes)} bytes)")
            content = [
                types.Part.from_bytes(data=md_bytes, mime_type="text/markdown"),
                "Analyze the above markdown content from a bank statement page."
            ]
        elif page_bytes and mime_type:
            print(f"[DEBUG] Classifying page using PDF fallback ({len(page_bytes)} bytes)")
            content = [
                types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
                "Analyze the above PDF page content from a bank statement."
            ]
        else:
            print(f"[ERROR] No content provided for page classification")
            return ["other"]

        gemini_config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 15,  # Reduced from 20 to 15 for more focused, cost-effective classification
            "system_instruction": [classification_prompt],
            "max_output_tokens": 500,  # Classification needs minimal output
        }
        
        try:
            stream_response = self.processor._generate_content_stream(
                contents=content,
                config=gemini_config
            )
            raw = ""
            for resp in stream_response:
                raw += resp.text
                
            print(f"[DEBUG] Classification raw response: {raw[:200]}...")
            
            try:
                clean_json_str = JSONCleaner.updated_json_repair(raw)
                try:
                    parsed = json.loads(clean_json_str)
                except Exception:
                    fallback_json = JSONCleaner.extract_first_json(clean_json_str)
                    parsed = json.loads(fallback_json)
                
                page_types = parsed.get("page_types", [{"type": "other", "confidence": 0.1337}])
                elements = parsed.get("detected_elements", [])
                
                if elements:
                    print(f"[DEBUG] Detected elements: {elements}")
                
                return page_types
                
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page classification JSON parsing failed: {e}")
                print(f"[ERROR] Raw response: {raw}")
                return ["other"]
                
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception in page classification: {e}")
            return ["other"]

