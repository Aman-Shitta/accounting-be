# System imports
import json
import os
import re
import sys
import time
import unicodedata

# Third-party imports
from google.genai import types

from decimal import Decimal, InvalidOperation
from django.db import transaction

from typing import List, Dict, Optional
from agentic_doc.parse import parse
from agentic_doc.config import ParseConfig
# Local imports
from extractor.prompter import (
    Configuration,
)
from extractor.base import JSONCleaner
from extractor.base import BaseDocumentProcessor

from account.models import (
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankKeyItem,
    MonthlyAccountingDocument
)
from document.pipeline.utils import split_pdf_to_pages

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

import logging

logger = logging.getLogger(__name__)



class LandingAIService:
    def __init__(self):
        self.config = ParseConfig(
            api_key=os.getenv("LANDING_AI_API_KEY"),
        )

    def extract_markdown(self, page_bytes):
        """
        Send page bytes to Landing AI OCR to get markdown.
        Adjust this method to match the actual Landing AI SDK signature.
        """
        try:
            result = parse(
                documents=page_bytes,
                config=self.config
            )
            return result[0].markdown
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Landing AI OCR failed: {e}")
            return ""

class PageClassifier:
    
    def __init__(self, processor):
        self.processor = processor
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

    def classify(self, md_bytes, page_bytes=None, mime_type=None):
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
        - check_images: Contains images or details of cleared checks with check numbers, payees, amounts
        - summary_table: Contains account summaries, beginning/ending balances, totals, or statement overview
        - other: Any other content not fitting the above categories

        **Analysis Guidelines:**
        - Look for table structures, headers, repeated patterns
        - Transaction tables have columns like Date, Description, Debit, Credit, Balance
        - Check images have check numbers, payee names, amounts, memo fields
        - Summary tables have totals, balances, account information
        - A page can have multiple types (e.g., both transactions and summary)

        **Output Format:**
        Return JSON with:
        - page_types: Array of detected types

        Example: {"page_types": ["transaction_table"]}
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
                
                page_types = parsed.get("page_types", ["other"])
                confidence = parsed.get("confidence", 0.5)
                elements = parsed.get("detected_elements", [])
                
                print(f"[DEBUG] Classification result: {page_types} (confidence: {confidence})")
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

class TransactionExtractor:
    
    def __init__(self, processor, schema, prompt):
        self.processor = processor
        self.schema = schema
        self.prompt = prompt

    def extract(self, page_bytes, md_bytes,  mime_type, previous_page_context):
        # Use both PDF (visual context) and Markdown (text data) when available
        # PDF helps LLM understand layout/tables, Markdown provides clean text
        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
        ]
        
        # Build instruction text separately to keep it cleaner
        instruction = f"Extract transactions from this bank statement page.\n\n**Context from previous page:** {previous_page_context}\n\n**Important:** Extract ONLY data from the current page."
        
        if md_bytes:
            # Add markdown AFTER PDF but BEFORE instruction for better context flow
            content.append(types.Part.from_bytes(data=md_bytes, mime_type="text/markdown"))
            instruction = "**PDF provides visual layout, Markdown provides text data.**\n\n" + instruction
        
        content.append(instruction)

        gemini_config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.2,
            "top_p": 0.9,  # Slightly higher for transaction diversity
            "top_k": 25,   # Moderate value for transaction extraction balance
            "system_instruction": [self.prompt],
            "max_output_tokens": 6000,  # Explicit limit for transaction extraction
        }
        try:
            stream_response = self.processor._generate_content_stream(
                contents=content,
                config=gemini_config
            )
            raw = ""
            chunk_count = 0
            for resp in stream_response:
                raw += resp.text
                chunk_count += 1
            
            # Log if response seems truncated
            if chunk_count > 0 and not raw.strip().endswith('}'):
                print(f"[WARN] Response may be truncated, received {chunk_count} chunks, length: {len(raw)}")
                
        except Exception as te:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Transaction Stream error: {te}")
            return {"line_items": []}

        # Validate and repair JSON with expected structure
        try:
            clean_json_str = JSONCleaner.updated_json_repair(raw)
            try:
                parsed_data = json.loads(clean_json_str)
            except json.JSONDecodeError:
                # Try fallback extraction
                fallback_json = JSONCleaner.extract_first_json(clean_json_str)
                parsed_data = json.loads(fallback_json)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Transaction extraction failed: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw output (first 1000 chars): {raw[:1000]}")
            parsed_data = {"line_items": []}

        # Ensure line_items exists
        if "line_items" not in parsed_data:
            parsed_data["line_items"] = []

        # Post-process: detect check transactions
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
    
    def __init__(self, processor):
        self.processor = processor
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
        ]
        gemini_config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.1,
            "top_p": 0.8,
            "top_k": 15,   # Low value for precise check data extraction
            "system_instruction": [check_image_prompt],
            "max_output_tokens": 4000,  # Explicit limit for check extraction
        }
        try:
            stream_response = self.processor._generate_content_stream(
                contents=content,
                config=gemini_config
            )
            raw = ""
                
            for resp in stream_response:
                raw += resp.text
        except Exception as ce:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Check Stream error: {ce}")
            return {}

        try:
            clean_json_str = JSONCleaner.updated_json_repair(raw)
            parsed_data = json.loads(clean_json_str)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Check image extraction failed: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw output: {raw}")
            parsed_data = {"checks": []}
        return parsed_data

class BankStatementSummarizer:
    def __init__(self, processor, schema: types.Schema=None):
        
        self.processor = processor

        self.response_schema = schema if schema and isinstance(schema, types.Schema) else types.Schema(
            type=types.Type.OBJECT,
            properties={
                "beginning_balance": {"type": types.Type.NUMBER},
                "ending_balance": {"type": types.Type.NUMBER},
                "total_deposits": {"type": types.Type.NUMBER},
                "total_withdrawals": {"type": types.Type.NUMBER},
            },
            required=[
                "beginning_balance",
                "ending_balance",
                "total_deposits",
                "total_withdrawals"
            ],
        )

    def generate_statement_summary(self, file_bytes: bytes) -> dict:
        """
        Extracts beginning balance, ending balance, total deposits, and total withdrawals
        from a complete bank statement PDF (may span multiple pages).
        """
        summary_prompt = """
        You are a financial document analyst.
        From the attached bank statement PDF, extract the following summary fields using
        the entire document context (up to 20 pages may be present):

        - beginning_balance: The opening balance at the start of the statement.
        - ending_balance: The final balance at the end of the statement.
        - total_deposits: The total amount of all deposit transactions (credits).
        - total_withdrawals: The total amount of all withdrawal transactions (debits).

        Ensure:
        - All amounts are extracted as float or numeric values (no currency symbols).
        - The result is a single flat JSON object with the above 4 keys only.
        - If a field is missing, set its value as `null`.

        Output only JSON like this:
        {
          "beginning_balance": 1234.56,
          "ending_balance": 4567.89,
          "total_deposits": 2000.00,
          "total_withdrawals": 500.00
        }
        """

        content = [
            types.Part.from_bytes(
                data=file_bytes,
                mime_type="application/pdf",
            ),
        ]


        gemini_config: types.GenerateContentConfigDict = {
            "response_schema": self.response_schema,
            "response_mime_type":"application/json",
            "temperature": 0.2,
            "top_p": 0.85,
            "top_k": 20,   # Moderate value for summary extraction
            "system_instruction": [summary_prompt],
            "max_output_tokens": 1000,  # Summary needs minimal output
        }

        try:
            stream_response = self.processor._generate_content_stream(
                contents=[content],
                config=gemini_config
            )

            raw = ""

            for resp in stream_response:
                raw += resp.text

            clean_json_str = self._clean_json_string(raw)

            try:
                summary = json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] JSONDecodeError: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response : {raw}")
                summary = {}

            return summary

        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print(f"[ERROR][Line {exc_tb.tb_lineno}] Error while generating summary: {e}")
            return {}

    def _clean_json_string(self, raw: str) -> str:
        """
        Cleans and prepares LLM output for safe JSON decoding.
        """
        raw = re.sub(r'^```(?:json)?', '', raw)
        raw = raw.strip('` \n')
        raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')
        raw = raw.replace("None", "null")

        # Remove control characters except newline/tab
        raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')
        return raw

class DocumentProcessor(BaseDocumentProcessor):

    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.control_totals = {}

        # Define the transaction extraction schema (used for each page)
        self.ai_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
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
    
    def _validate_and_repair_json(self, raw_json: str, expected_structure: dict) -> dict:
        """
        Validate and repair incomplete JSON responses from LLM.
        
        Args:
            raw_json: Raw JSON string from LLM
            expected_structure: Expected keys in the response
            
        Returns:
            Parsed and validated JSON dict
        """
        try:
            clean_json_str = JSONCleaner.updated_json_repair(raw_json)
            parsed_data = json.loads(clean_json_str)
            
            # Validate expected structure
            for key in expected_structure.keys():
                if key not in parsed_data:
                    logger.warning(f"Missing key '{key}' in LLM response, adding default value")
                    parsed_data[key] = expected_structure[key]
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.error(f"Raw JSON (first 500 chars): {raw_json[:500]}")
            
            # Try to extract partial JSON using fallback
            try:
                fallback_json = JSONCleaner.extract_first_json(raw_json)
                parsed_data = json.loads(fallback_json)
                
                # Fill in missing keys
                for key in expected_structure.keys():
                    if key not in parsed_data:
                        parsed_data[key] = expected_structure[key]
                        
                return parsed_data
            except:
                # Return default structure if all parsing fails
                logger.error("All JSON parsing attempts failed, returning default structure")
                return expected_structure

    def process_document(self, file_bytes: bytes, mime_type: str, md=False):

        page_bytes_list = split_pdf_to_pages(file_bytes)
        
        # Optimize: Use compact context instead of full parsed data
        # Only track last transaction date and count to maintain continuity
        previous_page_context = ""

        # Check if we have pre-generated markdown
        markdown_pages_data = {}
        if md and self.document.markdown_metadata:
            metadata = self.document.markdown_metadata
            logger.info(f"Using pre-generated markdown for {metadata.get('total_pages', 0)} pages")
            
            # Build a dict for quick lookup: page_number -> markdown data
            for page_info in metadata.get('pages', []):
                page_num = page_info.get('page_number')
                if page_num and page_info.get('path'):
                    markdown_pages_data[page_num] = page_info

        # Create extractors once and reuse
        page_classifier = PageClassifier(self)
        transaction_extractor = TransactionExtractor(self, self.ai_schema, self.prompt)
        check_image_extractor = CheckImageExtractor(self)
        parser = LandingAIService() if (md and not markdown_pages_data) else None  # Only if no pre-generated markdown
        summarizer = None

        for i, page_bytes in enumerate(page_bytes_list):
            try:
                md_bytes = None
                page_num = i + 1
                
                if md:
                    # Try to get pre-generated markdown first
                    if page_num in markdown_pages_data:
                        logger.info(f"Using pre-generated markdown for page {page_num}")
                        page_info = markdown_pages_data[page_num]
                        
                        # Fetch markdown from Azure using the stored path
                        try:
                            with default_storage.open(page_info['path'], 'rb') as md_file:
                                md_bytes = md_file.read()
                            logger.info(f"Loaded pre-generated markdown for page {page_num} ({len(md_bytes)} bytes)")
                        except Exception as e:
                            logger.warning(f"Failed to load pre-generated markdown for page {page_num}: {e}")
                            md_bytes = None
                    
                    # Fallback to real-time generation if pre-generated not available
                    if md_bytes is None and parser:
                        logger.info(f"Generating markdown in real-time for page {page_num}")
                        page_markdown = parser.extract_markdown(page_bytes=page_bytes)
                        if page_markdown:
                            md_bytes = page_markdown.encode("utf-8")
                            logger.info(f"Generated markdown for page {page_num} ({len(md_bytes)} bytes)")
                        else:
                            logger.warning(f"Failed to generate markdown for page {page_num}")
                            md_bytes = None

                # 1. Classify the page using markdown first, fallback to PDF
                if md_bytes:
                    page_types = page_classifier.classify(md_bytes=md_bytes)
                else:
                    page_types = page_classifier.classify(md_bytes=None, page_bytes=page_bytes, mime_type=mime_type)
                print(f"\n\n[DEBUG] Page {i+1} classified as: {page_types}")
                page_result = {"page_types": page_types}

                # 2. Extract data based on classification
                if "transaction_table" in page_types:
                    parsed_data = transaction_extractor.extract(page_bytes, md_bytes, mime_type, previous_page_context)
                    page_result["transactions"] = parsed_data
                    
                    # Optimize: Keep only minimal context (last 2 transactions summary)
                    line_items = parsed_data.get("line_items", [])
                    if line_items:
                        last_items = line_items[-2:] if len(line_items) >= 2 else line_items
                        previous_page_context = f"Last {len(last_items)} transaction(s): " + "; ".join([
                            f"{item.get('date', 'N/A')}: {item.get('description', 'N/A')[:50]}"
                            for item in last_items
                        ])
                    else:
                        previous_page_context = "No transactions on previous page"

                if "check_images" in page_types:
                    parsed_data = check_image_extractor.extract(page_bytes, mime_type)
                    page_result["check_data"] = parsed_data

                if "summary_table" in page_types and not self.control_totals:
                    if not summarizer:
                        summarizer = BankStatementSummarizer(self)
                    summary = summarizer.generate_statement_summary(page_bytes)
                    self.control_totals = summary

                self.page_data.append({f"page_{i+1}": page_result})
                print(f"[DEBUG] Page {i+1} data is: {page_result}")
                
                # Reduce sleep time from 3s to 1s for better throughput
                time.sleep(1)


            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Exception during processing page {i+1}: {e}")
                print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Page bytes preview: {page_bytes[:20] if page_bytes else 'None'}")
                # Log but continue processing other pages
                continue
            finally:
                # Clean up page-level resources
                if md_bytes:
                    del md_bytes
                if 'page_bytes' in locals():
                    del page_bytes
        
        # Clean up extractors after all pages are processed
        try:
            del page_classifier
            del transaction_extractor
            del check_image_extractor
            if parser:
                del parser
            if summarizer:
                del summarizer
        except Exception as cleanup_error:
            logger.warning(f"Error during cleanup: {cleanup_error}")

        self._save_contorl_totals()
        # Process and save extracted data
        processing_stats = self._save_extracted_data()

        return {
            "status": "success",
            "control_totals": self.control_totals,
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }

    def _save_contorl_totals(self):
        # Save control totals to document
        self.document.control_item = self.control_totals
        self.document.save()

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
                page_key = f"page_{page_idx + 1}"
                page_content = page_item.get(page_key, {})
                
                # Process transactions
                transactions = page_content.get("transactions", {})
                
                # Save key items (summary data)
                key_items_data = transactions.get("key_items", {})
                if isinstance(key_items_data, dict):
                    for key, value in key_items_data.items():
                        MonthlyDocumentBankKeyItem.objects.create(
                            document=self.document,
                            page_number=page_idx + 1,
                            key=key,
                            value=str(value) if value is not None else ""
                        )
                        stats["key_items"] += 1
                
                # Save line items (transactions)
                line_items_data = transactions.get("line_items", [])
                for line_idx, line_item in enumerate(line_items_data):
                    self._save_line_item(page_idx + 1, line_idx + 1, line_item)
                    stats["line_items"] += 1
                
                # Save check data
                check_data = page_content.get("check_data", {})
                checks = check_data.get("checks", [])
                for check_item in checks:
                    check_obj = self._save_check_item(page_idx + 1, check_item)
                    stats["check_items"] += 1
                    
                    # Try to link check to line item
                    self._link_check_to_line_item(check_obj)
                
                stats["pages_processed"] += 1

        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """
        Parse amount string to Decimal.
        
        Args:
            amount_str: Amount string from extraction
            
        Returns:
            Parsed Decimal amount or None if parsing fails
        """
        if not amount_str or str(amount_str).strip() in ['', 'null', 'none', '-']:
            return None
        
        try:
            # Clean the amount string
            clean_amount = str(amount_str).replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            
            # Handle parentheses for negative amounts
            if clean_amount.startswith('-'):
                clean_amount = clean_amount[1:]
                return -Decimal(clean_amount)
            
            return Decimal(clean_amount)
            
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.warning(f"Failed to parse amount '{amount_str}': {e}")
            return None


    def _save_line_item(self, page_number: int, line_number: int, line_data: Dict) -> MonthlyDocumentBankLineItem:
        """
        Save a transaction line item to the database.
        
        Args:
            page_number: Page number
            line_number: Line number within page
            line_data: Raw line item data from extractor
            
        Returns:
            Created MonthlyDocumentBankLineItem instance
        """
        # Extract basic fields
        date = line_data.get("date", "")
        description = line_data.get("description", "")
        debit_amount_raw = line_data.get("debit_amount", "")
        credit_amount_raw = line_data.get("credit_amount", "")
        
        # Determine transaction type and amount
        transaction_type = None
        amount = None
        
        try:
            if debit_amount_raw and str(debit_amount_raw).strip() and str(debit_amount_raw).lower() not in ['', 'null', 'none', '-']:
                transaction_type = 'debit'
                amount = self._parse_amount(debit_amount_raw)
            elif credit_amount_raw and str(credit_amount_raw).strip() and str(credit_amount_raw).lower() not in ['', 'null', 'none', '-']:
                transaction_type = 'credit'
                amount = self._parse_amount(credit_amount_raw)
        except Exception as e:
            logger.warning(f"Failed to parse amounts for line {page_number}.{line_number}: {e}")
        
        # Check transaction detection
        is_check_transaction = line_data.get("is_check_transaction", False)
        check_number = line_data.get("check_number", "") if is_check_transaction else None
        
        # Create line item
        line_item = MonthlyDocumentBankLineItem.objects.create(
            document=self.document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type,
            debit_amount=str(debit_amount_raw) if debit_amount_raw else None,
            credit_amount=str(credit_amount_raw) if credit_amount_raw else None,
            is_check_transaction=is_check_transaction,
            check_number=check_number,
            # GL accounts will be set during classification
            gl_account=None,
            offset_gl_account=None
        )
        
        return line_item
    
    def _save_check_item(self, page_number: int, check_data: Dict) -> MonthlyDocumentBankCheckItem:
        """
        Save a check item to the database.
        
        Args:
            page_number: Page number
            check_data: Raw check data from extractor
            
        Returns:
            Created MonthlyDocumentBankCheckItem instance
        """
        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.document,
            page_number=page_number,
            amount=str(check_data.get("amount", "")),
            payee=check_data.get("payee", ""),
            memo=check_data.get("memo", ""),
            clearing_date=check_data.get("clearing_date", ""),
            passing_date=check_data.get("passing_date", ""),
            check_number=check_data.get("check_number", ""),
            related_line_item=None  # Will be set in _link_check_to_line_item
        )
        
        return check_item
    
    def _link_check_to_line_item(self, check_item: MonthlyDocumentBankCheckItem):
        """
        Try to link a check item to its corresponding line item.
        
        Args:
            check_item: MonthlyDocumentBankCheckItem to link
        """
        if not check_item.check_number:
            return
        
        # Look for line item with matching check number
        matching_line_item = MonthlyDocumentBankLineItem.objects.filter(
            document=self.document,
            check_number=check_item.check_number,
            is_check_transaction=True
        ).first()
        
        if matching_line_item:
            check_item.related_line_item = matching_line_item
            check_item.save()
            logger.debug(f"Linked check #{check_item.check_number} to line item {matching_line_item.id}")
