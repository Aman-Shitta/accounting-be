
import os
import sys
import json

from google.genai import types

from extractor.gemini_service import GeminiService
from extractor.utils import JSONHelper


import logging
logger = logging.getLogger(__name__)


class PageClassifier:
    """
    Page classifier for bank statements using Gemini AI.

    Classifies bank statement pages into categories like transaction tables,
    check images, summary tables, etc.
    """

    def __init__(self, processor):
        """
        Initialize the classifier with a document processor.

        Args:
            processor: A processor instance with Gemini capabilities (e.g., BaseDocumentProcessor)
        """
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

        # Use service helpers to create content parts
        if md_bytes:
            logger.error(
                f"[DEBUG] Classifying page using markdown content ({len(md_bytes)} bytes)")
            content = [
                GeminiService.create_markdown_part(md_bytes),
                "Analyze the above markdown content from a bank statement page."
            ]
        elif page_bytes and mime_type:
            logger.error(
                f"[DEBUG] Classifying page using PDF fallback ({len(page_bytes)} bytes)")
            content = [
                GeminiService.create_part_from_bytes(page_bytes, mime_type),
                "Analyze the above PDF page content from a bank statement."
            ]
        else:
            logger.error(
                f"[ERROR] No content provided for page classification")
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

            logger.error(
                f"[DEBUG] Classification raw response: {raw[:200]}...")

            # Use JSONHelper for robust parsing
            parsed = JSONHelper.parse_json(
                raw, default={"page_types": [{"type": "other", "confidence": 0.1337}]})

            page_types = parsed.get(
                "page_types", [{"type": "other", "confidence": 0.1337}])
            elements = parsed.get("detected_elements", [])

            if elements:
                logger.error(f"[DEBUG] Detected elements: {elements}")

            return page_types

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(
                f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception in page classification: {e}")
            return ["other"]
