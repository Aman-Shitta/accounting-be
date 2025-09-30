# System imports
import importlib
import json
import os
import re
import sys
import time
import unicodedata

# Third-party imports
from google.genai import types

from decimal import Decimal, InvalidOperation

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

from django.db import transaction

from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

from agentic_doc.parse import parse
from agentic_doc.config import ParseConfig

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
                file_bytes=page_bytes,
                config=self.config
            )
            return result.markdown  # adjust to actual return value
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
        ]
        gemini_config = {
            "response_schema": self.schema,
            "response_mime_type": "application/json",
            "temperature": 0.0,
            "top_p": 0.8,
            "top_k": 20,
            "system_instruction": [classification_prompt]
        }
        try:
            stream_response = self.processor._generate_content_stream(
                contents=[content],
                config=gemini_config
            )
            raw = ""
            for resp in stream_response:
                raw += resp.text
            try:
                clean_json_str = JSONCleaner.updated_json_repair(raw)
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
    
    def __init__(self, processor, schema, prompt):
        self.processor = processor
        self.schema = schema
        self.prompt = prompt

    def extract(self, page_bytes, mime_type, previous_page_context):
        content = [
            types.Part.from_bytes(data=page_bytes, mime_type=mime_type),
            f"\n**Previous page context: {previous_page_context}\nExtract data from current page only."
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
            clean_json_str = JSONCleaner.updated_json_repair(raw)
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
            "system_instruction": [check_image_prompt]
        }
        try:
            stream_response = self.processor._generate_content_stream(
                contents=[content],
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
            clean_json_str = JSONCleaner.clean(raw)
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
            "system_instruction": [summary_prompt]
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
                import sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] JSONDecodeError: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response : {raw}")
                parsed_data = {}
                summary = {}

            return summary

        except Exception as e:
            import sys
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

    def process_document(self, file_bytes: bytes, mime_type: str):
        from document.pipeline.utils import split_pdf_to_pages

        page_bytes_list = split_pdf_to_pages(file_bytes)
        previous_page_context = ""

        page_classifier = PageClassifier(self)
        transaction_extractor = TransactionExtractor(self, self.ai_schema, self.prompt)
        check_image_extractor = CheckImageExtractor(self)
        summarizer = None

        for i, page_bytes in enumerate(page_bytes_list):
            try:
                # 1. Classify the page
                page_types = page_classifier.classify(page_bytes, mime_type)
                print(f"\n\n[DEBUG] Page {i+1} classified as: {page_types}")
                page_result = {"page_types": page_types}

                # 2. Extract data based on classification
                if "transaction_table" in page_types:
                    parsed_data = transaction_extractor.extract(page_bytes, mime_type, previous_page_context)
                    page_result["transactions"] = parsed_data
                    previous_page_context = str(parsed_data)

                if "check_images" in page_types:
                    parsed_data = check_image_extractor.extract(page_bytes, mime_type)
                    page_result["check_data"] = parsed_data

                if "summary_table" in page_types and not self.control_totals:
                    summarizer = BankStatementSummarizer(self)
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
        
        del page_classifier
        del transaction_extractor
        del check_image_extractor
        if summarizer:
            del summarizer

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
