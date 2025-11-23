from __future__ import annotations

import os
import logging
import time
import tempfile
import re
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Optional, Any

from django.conf import settings
from django.db import transaction
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from pydantic import BaseModel, Field
from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from extractor.base import BaseDocumentProcessor
from extractor.prompter import Configuration
from account.models import (
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
    MonthlyDocumentBankKeyItem,
    MonthlyAccountingDocument
)
from document.pipeline.utils import split_pdf_to_pages

logger = logging.getLogger(__name__)

# --- Pydantic Models for Extraction Schemas ---

class PageClassification(BaseModel):
    page_types: List[str] = Field(
        ..., 
        description="List of page types detected. Options: 'transaction_table', 'check_images', 'summary_table', 'other'. "
                    "transaction_table: Contains transaction listings with dates, descriptions, amounts. "
                    "check_images: Contains images or details of cleared checks. "
                    "summary_table: Contains account summaries, beginning/ending balances. "
                    "other: Any other content."
    )

class Transaction(BaseModel):
    date: str = Field(..., description="The date when the transaction occurred.")
    description: str = Field(..., description="Description of the transaction.")
    debit_amount: Optional[str] = Field(None, description="The amount debited (money out).")
    credit_amount: Optional[str] = Field(None, description="The amount credited (money in).")
    is_check_transaction: bool = Field(False, description="True if this transaction appears to be a check.")
    check_number: Optional[str] = Field(None, description="Check number if identified in the description.")

class TransactionList(BaseModel):
    line_items: List[Transaction] = Field(..., description="List of all financial transactions extracted from the page.")
    type: str = Field(..., description="Type of transaction list, e.g., 'deposit', 'withdrawls', 'transaction_actvity', 'check'.")

class Check(BaseModel):
    amount: str = Field(..., description="Check amount.")
    payee: str = Field(..., description="Payee name.")
    memo: Optional[str] = Field(None, description="Memo line.")
    clearing_date: Optional[str] = Field(None, description="Date check cleared.")
    passing_date: Optional[str] = Field(None, description="Date check passed.")
    check_number: Optional[str] = Field(None, description="Check number.")

class CheckList(BaseModel):
    checks: List[Check] = Field(..., description="List of checks found in images on the page.")

class StatementSummary(BaseModel):
    beginning_balance: Optional[float] = Field(None, description="The opening balance at the start of the statement.")
    ending_balance: Optional[float] = Field(None, description="The final balance at the end of the statement.")
    total_deposits: Optional[float] = Field(None, description="The total amount of all deposit transactions.")
    total_withdrawals: Optional[float] = Field(None, description="The total amount of all withdrawal transactions.")

import os, sys
import json
from google.genai import types
from extractor.base import JSONCleaner

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

class DocumentProcessor(BaseDocumentProcessor):
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.control_totals = {}
        
        # Initialize LandingAI client
        # Try to get API key from settings or environment
        api_key = settings.LANDING_AI_API_KEY

        if not api_key:
             logger.warning("LANDING_AI_API_KEY not found in settings or env.")
        
        self.client = LandingAIADE(apikey=api_key)
        
        # Prepare schemas
        # self.classification_schema = pydantic_to_json_schema(PageClassification)
        self.page_classifier = PageClassifier(self)
        self.transaction_schema = pydantic_to_json_schema(TransactionList)
        self.check_schema = pydantic_to_json_schema(CheckList)
        self.summary_schema = pydantic_to_json_schema(StatementSummary)

    def process_document(self, file_bytes: bytes, mime_type: None, md=False):
        page_bytes_list = split_pdf_to_pages(file_bytes)
        
        for i, page_bytes in enumerate(page_bytes_list):
            page_num = i + 1
            logger.info(f"Processing page {page_num}...")
            try:
                # LandingAI parse expects a file path. We'll use a temp file.
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as temp_pdf:
                    temp_pdf.write(page_bytes)
                    temp_pdf.flush()
                    
                    # 1. Parse Page to Markdown
                    start_time = time.time()
                    # Using dpt-2 model as per example
                    parse_response = self.client.parse(
                        document=Path(temp_pdf.name),
                        model="dpt-2" 
                    )
                    markdown_content = parse_response.markdown
                    logger.info(f"Page {page_num} parsed in {time.time() - start_time:.2f}s")
                    
                    if not markdown_content:
                        logger.warning(f"No markdown extracted for page {page_num}")
                        continue

                    # 2. Classify Page
                    start_time = time.time()
                    # classification_response = self.client.extract(
                    #     schema=self.classification_schema,
                    #     markdown=BytesIO(markdown_content.encode('utf-8'))
                    # )
                    # page_types = classification_response.extraction.get("page_types", ["other"])

                    page_types = self.page_classifier.classify(page_bytes=page_bytes, mime_type=mime_type)
                    logger.info(f"Page {page_num} classified in {time.time() - start_time:.2f}s")
                    
                    
                    logger.info(f"Page {page_num} classified as: {page_types}")
                    
                    page_result = {"page_types": page_types}
                    
                    # 3. Extract Data based on classification
                    if "transaction_table" in page_types:
                        start_time = time.time()
                        transaction_response = self.client.extract(
                            schema=self.transaction_schema,
                            markdown=BytesIO(markdown_content.encode('utf-8'))
                        )
                        page_result["transactions"] = transaction_response.extraction
                        logger.info(f"Page {page_num} transactions extracted in {time.time() - start_time:.2f}s")
                    
                    if "check_images" in page_types or "check_table" in page_types:
                        start_time = time.time()
                        check_response = self.client.extract(
                            schema=self.check_schema,
                            markdown=BytesIO(markdown_content.encode('utf-8'))
                        )
                        check_key = f"check_table_data" if "check_table" in page_types else "check_images_data"
                        page_result[check_key] = check_response.extraction
                        logger.info(f"Page {page_num} checks extracted in {time.time() - start_time:.2f}s")
                    
                    if "summary_table" in page_types and not self.control_totals:
                        start_time = time.time()
                        summary_response = self.client.extract(
                            schema=self.summary_schema,
                            markdown=BytesIO(markdown_content.encode('utf-8'))
                        )
                        self.control_totals = summary_response.extraction
                        logger.info(f"Page {page_num} summary extracted in {time.time() - start_time:.2f}s")
                    
                    self.page_data.append({f"page_{page_num}": page_result})
                    
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}")
                continue

        print("self.page_data :: ", self.page_data)
        # self.page_data = [{'page_1': {'page_types': ['summary_table', 'transaction_table'], 'transactions': {'line_items': [{'date': 'June 02', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,168.55', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 02', 'description': 'SpotOn SV92 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '3,564.74', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 02', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '4,690.38', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 03', 'description': 'SpotOn SV93 878144102 1043575881', 'debit_amount': None, 'credit_amount': '1,758.27', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 05', 'description': 'SpotOn SV95 877814102 1043575881', 'debit_amount': None, 'credit_amount': '1,231.28', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 06', 'description': 'SpotOn SV96 877814102 1043575881', 'debit_amount': None, 'credit_amount': '940.55', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 09', 'description': 'SpotOn SV92 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,312.32', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 09', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,398.83', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 09', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '4,420.47', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 10', 'description': 'SpotOn SV93 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '1,135.71', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 12', 'description': 'SpotOn SV95 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '1,795.31', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 13', 'description': 'SpotOn SV96 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,194.23', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 16', 'description': 'SpotOn SV9T 878144102 1043575881', 'debit_amount': None, 'credit_amount': '1,876.65', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 16', 'description': 'SpotOn SV92 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,212.77', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 16', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '3,507.40', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 17', 'description': 'SpotOn SV93 878144102 1043575881', 'debit_amount': None, 'credit_amount': '2,354.86', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 20', 'description': 'SpotOn SV96 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '1,879.62', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 20', 'description': 'SpotOn SV96 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '2,128.49', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 23', 'description': 'SpotOn SV92 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '1,982.26', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 23', 'description': 'SpotOn SV9T 877814102 1043575881', 'debit_amount': None, 'credit_amount': '2,225.92', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 23', 'description': 'SpotOn SV9T 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '3,711.89', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 24', 'description': 'SpotOn SV93 877814102 1043575881', 'debit_amount': None, 'credit_amount': '1,741.00', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 26', 'description': 'SpotOn SV95 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '1,222.54', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 27', 'description': 'SpotOn SV96 877814102 1043575881', 'debit_amount': None, 'credit_amount': '1,914.66', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 30', 'description': 'SpotOn SV9T 877814102 1043575881', 'debit_amount': None, 'credit_amount': '2,517.63', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 30', 'description': 'SpotOn SV9T 878144102 1043575881', 'debit_amount': None, 'credit_amount': '3,137.18', 'is_check_transaction': None, 'check_number': None}, {'date': 'June 30', 'description': 'SpotOn SV92 8778144102 1043575881', 'debit_amount': None, 'credit_amount': '3,453.22', 'is_check_transaction': None, 'check_number': None}], 'type': 'deposit'}}}, {'page_2': {'page_types': ['other']}}, {'page_3': {'page_types': ['check_table', 'transaction_table'], 'transactions': {'line_items': [{'date': 'June 10', 'description': 'Check No. 1', 'debit_amount': '677.10', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1'}, {'date': 'June 03', 'description': 'Check No. 10227', 'debit_amount': '109.83', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10227'}, {'date': 'June 16', 'description': 'Check No. 2', 'debit_amount': '881.96', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '2'}, {'date': 'June 04', 'description': 'Check No. 10228', 'debit_amount': '336.65', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10228'}, {'date': 'June 24', 'description': 'Check No. 3', 'debit_amount': '1,052.68', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '3'}, {'date': 'June 02', 'description': 'Check No. 10231', 'debit_amount': '931.01', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10231'}, {'date': 'June 23', 'description': 'Check No. 4', 'debit_amount': '250.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '4'}, {'date': 'June 03', 'description': 'Check No. 10232', 'debit_amount': '82.12', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10232'}, {'date': 'June 24', 'description': 'Check No. 6', 'debit_amount': '740.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '6'}, {'date': 'June 03', 'description': 'Check No. 10233', 'debit_amount': '117.83', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10233'}, {'date': 'June 24', 'description': 'Check No. 8', 'debit_amount': '300.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '8'}, {'date': 'June 06', 'description': 'Check No. 10234', 'debit_amount': '438.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10234'}, {'date': 'June 10', 'description': 'Check No. 9', 'debit_amount': '300.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '9'}, {'date': 'June 10', 'description': 'Check No. 10235', 'debit_amount': '623.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10235'}, {'date': 'June 23', 'description': 'Check No. 10', 'debit_amount': '976.40', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10'}, {'date': 'June 16', 'description': 'Check No. 10236', 'debit_amount': '931.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10236'}, {'date': 'June 09', 'description': 'Check No. 15', 'debit_amount': '868.36', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '15'}, {'date': 'June 16', 'description': 'Check No. 10237', 'debit_amount': '240.23', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10237'}, {'date': 'June 27', 'description': 'Check No. 40', 'debit_amount': '300.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '40'}, {'date': 'June 17', 'description': 'Check No. 10238', 'debit_amount': '386.47', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10238'}, {'date': 'June 03', 'description': 'Check No. 1208', 'debit_amount': '85.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1208'}, {'date': 'June 13', 'description': 'Check No. 10239', 'debit_amount': '655.54', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10239'}, {'date': 'June 17', 'description': 'Check No. 1218', 'debit_amount': '250.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1218'}, {'date': 'June 13', 'description': 'Check No. 10240', 'debit_amount': '794.09', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10240'}, {'date': 'June 02', 'description': 'Check No. 1220', 'debit_amount': '350.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1220'}, {'date': 'June 16', 'description': 'Check No. 10241', 'debit_amount': '931.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10241'}, {'date': 'June 16', 'description': 'Check No. 1221', 'debit_amount': '525.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1221'}, {'date': 'June 17', 'description': 'Check No. 10242', 'debit_amount': '130.75', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10242'}, {'date': 'June 06', 'description': 'Check No. 1222', 'debit_amount': '50.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1222'}, {'date': 'June 20', 'description': 'Check No. 10243', 'debit_amount': '438.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10243'}, {'date': 'June 06', 'description': 'Check No. 1224', 'debit_amount': '300.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1224'}, {'date': 'June 30', 'description': 'Check No. 10244', 'debit_amount': '931.01', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10244'}, {'date': 'June 04', 'description': 'Check No. 1225', 'debit_amount': '1,088.59', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '1225'}, {'date': 'June 30', 'description': 'Check No. 10247', 'debit_amount': '866.21', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10247'}, {'date': 'June 02', 'description': 'Check No. 10219', 'debit_amount': '365.95', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10219'}, {'date': 'June 30', 'description': 'Check No. 10248', 'debit_amount': '599.13', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10248'}, {'date': 'June 02', 'description': 'Check No. 10226', 'debit_amount': '931.01', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10226'}, {'date': 'June 30', 'description': 'Check No. 10249', 'debit_amount': '894.36', 'credit_amount': None, 'is_check_transaction': True, 'check_number': '10249'}, {'date': 'June 02', 'description': 'Check Plus MR GS LIQUOR Califor a MOMR GS LIQ UO 05/31', 'debit_amount': '12.01', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'CheckPlus CALS THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/01', 'debit_amount': '10.39', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'CheckPlus FAMILY DOLLAR 407 W BUCHANAN ST CALIFORNIA MO 05/30', 'debit_amount': '19.08', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'CheckPlus CALS THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 05/31', 'debit_amount': '23.06', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'CheckPlus CALS THRIFTIWA 408 W. BUCHANAN CALIFORNIA MO 0601', 'debit_amount': '23.12', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNA MO 0601", 'debit_amount': '34.24', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': "CheckPlus CAL'S THRIFTIWA 408 W. BUCHANAN CALIFORNIA MO 05/31", 'debit_amount': '49.72', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'CheckPlus LA COMADRE MAR 311 SAK ST CALIFORNIA MO 06/01', 'debit_amount': '77.41', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 02', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '300', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'ATM Withdrawl Fe MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': None, 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'ARAMARK UNIFORM Account St107690586537989390386001', 'debit_amount': '113.68', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'MENU MAKER FOODFRIDAY ACH419879/422372430906771', 'debit_amount': '877.32', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 02', 'description': 'US FOODSERVICE VENDOR PAY0602244375680004880371951', 'debit_amount': '3,616.83', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 03', 'description': 'CheckPlus Farm Bureau Jeffers CitMOFarm Bure au 06/02', 'debit_amount': '213.70', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 03', 'description': 'JP MO REV TAX MO REV TAXT26127481 333567123', 'debit_amount': '5,009.52', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '183.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Withdrawal MEXICALI BAR-1406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Wthdrawl Fee MEXICAL BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'Co-Mo Electic WEB PMTS GMSQHQ900302922', 'debit_amount': '149.19', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 04', 'description': 'IRS USATAXPYMT2705555397868938770200', 'debit_amount': '2,139.82', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 05', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/05", 'debit_amount': '6.86', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 05', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/05", 'debit_amount': '8.28', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 05', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/05", 'debit_amount': '81.32', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 05', 'description': 'CheckPlus TRACTOR SUPPLY 1400 West Buchanan California MO 06/05', 'debit_amount': '122.59', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 05', 'description': 'Co-Mo Electic WEB PMTS 535YHQ9000302922', 'debit_amount': '50.60', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 05', 'description': 'N H SCHEPPERS Wednesday 1 $4060003', 'debit_amount': '310.95', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 06', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/06", 'debit_amount': '54.71', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 06', 'description': 'US FOODSERVICE VENDOR PAY06062443756800480371951', 'debit_amount': '38034', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 09', 'description': 'il Payment Cityof Cal Day of Calfonia alformal 0', 'debit_amount': '318.13', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 09', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06:08", 'debit_amount': '5.37', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': 'Check Plus C&R SUPERMARKE 1021 BUCHANAN STRE CALIFORNIA MO 06/07', 'debit_amount': '8.35', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': 'Check Plus CALS THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/07', 'debit_amount': '25.80', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/08", 'debit_amount': '2798', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/07", 'debit_amount': '44.83', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/08", 'debit_amount': '54.76', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}], 'type': 'transaction_activity'}, 'check_data': {'checks': [{'amount': '677.10', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 10', 'check_number': '1'}, {'amount': '109.83', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 03', 'check_number': '10227'}, {'amount': '881.96', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 16', 'check_number': '2'}, {'amount': '336.65', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 04', 'check_number': '10228'}, {'amount': '1,052.68', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 24', 'check_number': '3'}, {'amount': '931.01', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 02', 'check_number': '10231'}, {'amount': '250.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 23', 'check_number': '4'}, {'amount': '82.12', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 03', 'check_number': '10232'}, {'amount': '740.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 24', 'check_number': '6'}, {'amount': '117.83', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 03', 'check_number': '10233'}, {'amount': '300.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 24', 'check_number': '8'}, {'amount': '438.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 06', 'check_number': '10234'}, {'amount': '300.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 10', 'check_number': '9'}, {'amount': '623.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 10', 'check_number': '10235'}, {'amount': '976.40', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 23', 'check_number': '10'}, {'amount': '931.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 16', 'check_number': '10236'}, {'amount': '868.36', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 09', 'check_number': '15'}, {'amount': '240.23', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 16', 'check_number': '10237'}, {'amount': '300.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 27', 'check_number': '40'}, {'amount': '386.47', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 17', 'check_number': '10238'}, {'amount': '85.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 03', 'check_number': '1208'}, {'amount': '655.54', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 13', 'check_number': '10239'}, {'amount': '250.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 17', 'check_number': '1218'}, {'amount': '794.09', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 13', 'check_number': '10240'}, {'amount': '350.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 02', 'check_number': '1220'}, {'amount': '931.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 16', 'check_number': '10241'}, {'amount': '525.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 16', 'check_number': '1221'}, {'amount': '130.75', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 17', 'check_number': '10242'}, {'amount': '50.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 06', 'check_number': '1222'}, {'amount': '438.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 20', 'check_number': '10243'}, {'amount': '300.00', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 06', 'check_number': '1224'}, {'amount': '931.01', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 30', 'check_number': '10244'}, {'amount': '1,088.59', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 04', 'check_number': '1225'}, {'amount': '866.21', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 30', 'check_number': '10247'}, {'amount': '365.95', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 02', 'check_number': '10219'}, {'amount': '599.13', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 30', 'check_number': '10248'}, {'amount': '931.01', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 02', 'check_number': '10226'}, {'amount': '894.36', 'payee': '', 'memo': None, 'clearing_date': None, 'passing_date': 'June 30', 'check_number': '10249'}]}}}, {'page_4': {'page_types': ['transaction_table'], 'transactions': {'line_items': [{'date': 'June 09', 'description': 'CheckPlus LA COMADRE MAR 311 S OAK ST CALIFORNIA MO 06/07', 'debit_amount': '92.89', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 09', 'description': '05/2025 SERVICE CHARGE', 'debit_amount': '33.95', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 09', 'description': 'ARAMARK UNIFORMAccount St1083036076657769390386001', 'debit_amount': '113.68', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 09', 'description': 'MENU MAKER FOODFRIDAY ACH419879 / 42223724390906771', 'debit_amount': '1,100.50', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 09', 'description': 'US FOODSERVICE VENDOR PAY060924437568004880371951', 'debit_amount': '4,84.53', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 10', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/10", 'debit_amount': '30.98', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 10', 'description': 'ATM Withdrawal CENTRAL BANK 1021 W BUCHANAN CALIFORNIA MO', 'debit_amount': '500.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 10', 'description': 'Co-Mo Electric WEB PMTS GADSJA 900302922', 'debit_amount': '125.80', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 10', 'description': 'SPOTON TRANSACT149380_15877-814-4102 53303903620', 'debit_amount': '350.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 11', 'description': 'N H SCHEPPERS Wednesday 1 S440660003', 'debit_amount': '268.40', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 12', 'description': 'CheckPlus LA COMADRE MAR 311 S OAK ST CALIFORNIA MO 06/12', 'debit_amount': '4.42', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 12', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/12", 'debit_amount': '44.90', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 13', 'description': 'CheckPlus CALIFORNIA CONSTRUCalifor a MOCALIFORNIA 06/12', 'debit_amount': '84.72', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 13', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/12", 'debit_amount': '20.62', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 13', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/13", 'debit_amount': '48.16', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 13', 'description': 'MENU MAKER FOODFRIDAY ACH419879 / 422372430906771', 'debit_amount': '1,211.49', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 16', 'description': 'CheckPlus FIVE CS CUSTOM BUTCALIFOR A MOFIVE CS C US 06/13', 'debit_amount': '100.00', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/14", 'debit_amount': '6.06', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/14", 'debit_amount': '18.23', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/15", 'debit_amount': '20.85', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/14", 'debit_amount': '21.16', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/15", 'debit_amount': '23.73', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': 'CheckPlus LA COMADRE MAR 311 S OAK ST CALIFORNIA MO 06/15', 'debit_amount': '46.45', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/14", 'debit_amount': '48.78', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/14", 'debit_amount': '87.14', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/15", 'debit_amount': '97.66', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': 'CheckPlus WAL-MART #0029 724 STADIUM WEST B JEFFERSON CIT MO 06/14', 'debit_amount': '157.17', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 16', 'description': 'US FOODSERVICE VENDOR PAY0616244375680004880371951', 'debit_amount': '2,802.11', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 18', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/18", 'debit_amount': '50.20', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 18', 'description': 'ATM Withdrawal CENTRAL BANK 1021 W BUCHANAN CALIFORNIA MO', 'debit_amount': '400.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 18', 'description': 'HARLAND CLARKE CHK ORDERS', 'debit_amount': '146.13', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 18', 'description': 'N SCHEPPERS Wednesday 1 S4406003', 'debit_amount': '489.35', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 18', 'description': 'IRS USATAXPYMT270556891430738770200', 'debit_amount': '1,989.16', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 20', 'description': 'CheckPlus TARGET.COM BROOKLY PARKIMINTARGET.COM 06/19', 'debit_amount': '118.45', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 20', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/20", 'debit_amount': '22.57', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 20', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/19", 'debit_amount': '47.8', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 20', 'description': 'Check Plus AMAZON.COM*NA2 AMAZON.COM SEATTLE WA 06/18', 'debit_amount': '81.86', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 20', 'description': 'CheckPlus LA COMADRE MAR 311 S OAK ST CALIFORNIA MO 06/20', 'debit_amount': '92.89', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 20', 'description': 'ATM Withdrawal CENTRAL BANK 1021 W BUCHANAN CALIFORNIA MO', 'debit_amount': '00.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 20', 'description': 'ATM Withdrawal CENTRAL BANK 1021 W BUCHANAN CALIFORNIA MO', 'debit_amount': '500.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 20', 'description': 'MENU MAKER FOODFRIDAY ACH419879 / 422372430906771', 'debit_amount': '794.90', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 23', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/22", 'debit_amount': '23.47', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 23', 'description': 'ARAMARK UNIFORM Account St1095131972071739390386001', 'debit_amount': '232.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 23', 'description': 'US FOODSERVICE VENDOR PAY0623243756800480371951', 'debit_amount': '2,570.59', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 24', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 24', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 24', 'description': 'Co-Mo Electic WEB PMTS HF5VLQ 9000302922', 'debit_amount': '3.23', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 24', 'description': 'Co-Mo Electric WEB PMTS KF5VLQ 9000302922', 'debit_amount': '50.82', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 25', 'description': 'Check Plus CALIFORNIA CONSTRUCalifor a MOCALIFORNIA 06/24', 'debit_amount': '36.87', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 25', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/25", 'debit_amount': '29.44', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 25', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/25", 'debit_amount': '132.06', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 25', 'description': 'ATM Withdrawal CENTRAL BANK 1021 W BUCHANAN CALIFORNIA MO', 'debit_amount': '400.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 25', 'description': 'N H SCHEPPERS Wednesday 1 S440660003', 'debit_amount': '118.15', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 26', 'description': 'CheckPlus CALIFORNIA CONSTRUCalfor a MOCALIFORNIA 06/25', 'debit_amount': '304.81', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 26', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/26", 'debit_amount': '26.40', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 26', 'description': 'CheckPlus CONVENIENT FOO EASTLAND DR JEFFERSON CIT MO 06/26', 'debit_amount': '40.02', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 26', 'description': 'Check Plus LA COMADRE MAR 311 S OAK ST CALIFORNIA MO 06/26', 'debit_amount': '71.75', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 26', 'description': 'US FOODSERVICE VENDOR PAY06262437568004880371951', 'debit_amount': '90551', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 27', 'description': "Check Plus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/27", 'debit_amount': '7.67', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 27', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/27", 'debit_amount': '7.91', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 27', 'description': 'CheckPlus C&R SUPERMARKE 1021 BUCHANAN STRE CALIFORNIA MO 06/26', 'debit_amount': '16.84', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 27', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/27", 'debit_amount': '73.95', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': 'June 27', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 27', 'description': 'ATM Withdrawal MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '203.25', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 27', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 27', 'description': 'ATM Withdrawl Fee MEXICALI BAR-1 406 N HIGH STREET CALIFORNIA MO', 'debit_amount': '3.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': 'June 27', 'description': 'MENU MAKER FOODFRIDAY ACH419879 / 4222372430906771', 'debit_amount': '1,873.65', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}], 'type': 'transaction_activity'}}}, {'page_5': {'page_types': ['transaction_table', 'summary_table'], 'transactions': {'line_items': [{'date': '2025-06-30', 'description': 'Bill Payment ZYGOON ZYGOON OMAHA NE', 'debit_amount': '750.00', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': '2025-06-30', 'description': 'CheckPlus MR GS LIQUOR Califor a MOMR GS LIQ UO 06/27', 'debit_amount': '16.01', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': 'CheckPlus MR GS LIQUOR Califor a MOMR GS LIQ UO 06/27', 'debit_amount': '24.02', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '5.59', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '7.80', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '8.21', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/28", 'debit_amount': '10.58', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '12.99', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '23.88', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/29", 'debit_amount': '26.28', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/28", 'debit_amount': '28.19', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': "CheckPlus CAL'S THRIFTWA 408 W. BUCHANAN CALIFORNIA MO 06/28", 'debit_amount': '33.03', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': 'CheckPlus AMAZON.COM*NQ1 AMAZON.COM SEATTLE WA 06/30', 'debit_amount': '52.28', 'credit_amount': None, 'is_check_transaction': True, 'check_number': None}, {'date': '2025-06-30', 'description': 'ARAMARK UNIFORMAccount St1101179412912469390386001', 'debit_amount': '115.28', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}, {'date': '2025-06-30', 'description': 'US FOODSERVICE VENDOR PAY0630244375680004880371951', 'debit_amount': '3,803.74', 'credit_amount': None, 'is_check_transaction': False, 'check_number': None}], 'type': 'transaction_activity'}}}, {'page_6': {'page_types': ['check_images'], 'check_data': {'checks': [{'amount': '$ 677.10', 'payee': 'Fechtel beverage', 'memo': None, 'clearing_date': '06/10/25', 'passing_date': '09/06/25', 'check_number': '0001'}, {'amount': '$881.96', 'payee': 'Signature Overhead Doors', 'memo': None, 'clearing_date': '06/16/25', 'passing_date': '5/6/25', 'check_number': '0002'}, {'amount': '$ 1052.68', 'payee': 'Pepsi Beverages', 'memo': None, 'clearing_date': None, 'passing_date': None, 'check_number': '0003'}, {'amount': '$ 250.00', 'payee': 'Fechtel beverage', 'memo': None, 'clearing_date': '06/23/25', 'passing_date': '20 June 25', 'check_number': '0004'}, {'amount': '$ 740.00', 'payee': None, 'memo': 'Form 641-BG', 'clearing_date': '06/24/25', 'passing_date': '6/19/25', 'check_number': '0006'}, {'amount': '$ 300.00', 'payee': 'Kimberly Deck', 'memo': 'Form 641-BG', 'clearing_date': None, 'passing_date': '6/20/25', 'check_number': '0008'}, {'amount': '$ 300.00', 'payee': 'Kimberly Deck', 'memo': None, 'clearing_date': None, 'passing_date': '6/7/25', 'check_number': '0009'}, {'amount': '$976.40', 'payee': 'SGWS', 'memo': None, 'clearing_date': None, 'passing_date': '6/18/25', 'check_number': '0010'}, {'amount': '$ 868.36', 'payee': 'Break Thru', 'memo': None, 'clearing_date': '06/09/25', 'passing_date': 'June 5, 2025', 'check_number': '0015'}]}}}, {'page_7': {'page_types': ['check_images'], 'check_data': {'checks': [{'amount': '$ 85.00', 'payee': 'Elite Pest Solutions', 'memo': 'pest control', 'clearing_date': '06/03/25', 'passing_date': '5/28/25', 'check_number': '1208'}, {'amount': '$ 250.00', 'payee': 'Deanna Harris', 'memo': 'entertainment.', 'clearing_date': '06/17/25', 'passing_date': '5/22/25', 'check_number': '1218'}, {'amount': '$ 350.00', 'payee': 'Kimberly Deck', 'memo': None, 'clearing_date': '06/02/25', 'passing_date': '5/3/25', 'check_number': '1220'}, {'amount': '$ 525.00', 'payee': 'City of California', 'memo': None, 'clearing_date': '06/16/25', 'passing_date': '5/29/25', 'check_number': '1221'}, {'amount': '$50.00', 'payee': 'California Chamber of Commerce', 'memo': None, 'clearing_date': '06/03/25', 'passing_date': '6/3/25', 'check_number': '1222'}, {'amount': '$ 300.00', 'payee': 'Brandy Baker', 'memo': None, 'clearing_date': None, 'passing_date': '5/29/25', 'check_number': '1224'}, {'amount': '$1088.59', 'payee': 'PepsiCo', 'memo': '#42276010', 'clearing_date': '06/04/25', 'passing_date': '5/30/25', 'check_number': '1225'}, {'amount': '$365.95', 'payee': 'Mirella Gomez Diaz', 'memo': 'Photo Safe Deposit', 'clearing_date': '06/02/25', 'passing_date': '5/16/2025', 'check_number': '10219'}, {'amount': '$931.01', 'payee': 'Eduardo Cagal Mixtega', 'memo': None, 'clearing_date': '06/02/25', 'passing_date': '5/30/2025', 'check_number': '10226'}, {'amount': '$109.83', 'payee': 'Jessica N Coonce', 'memo': None, 'clearing_date': '06/03/25', 'passing_date': '5/30/2025', 'check_number': '10227'}]}}}, {'page_8': {'page_types': ['check_images'], 'check_data': {'checks': [{'amount': '336.65', 'payee': 'Mirella Gomez Diaz', 'memo': 'Photo Gate Gapcaz Details on Back', 'clearing_date': None, 'passing_date': '5/30/2025', 'check_number': '10228'}, {'amount': '931.01', 'payee': 'Floralia Sanchez Diaz', 'memo': 'Photo Safe Deposit Details on Back', 'clearing_date': None, 'passing_date': '5/30/2025', 'check_number': '10231'}, {'amount': '82.12', 'payee': 'Bradley R Stuedle', 'memo': 'Photo Safe Deposit Bank on Back', 'clearing_date': '06/03/25', 'passing_date': '5/30/2025', 'check_number': '10232'}, {'amount': '117.83', 'payee': 'Haley N Wright', 'memo': 'Detalle on Back Photo Safe Depos', 'clearing_date': '06/03/25', 'passing_date': '5/30/2025', 'check_number': '10233'}, {'amount': '438.00', 'payee': 'Family Support Payment Center', 'memo': 'Photo Safe Deposit Details on Back', 'clearing_date': '06/06/25', 'passing_date': '5/30/2025', 'check_number': '10234'}, {'amount': '623.00', 'payee': 'Missouri Department of Revenue', 'memo': '20221668', 'clearing_date': None, 'passing_date': '5/30/2025', 'check_number': '10235'}, {'amount': '931.00', 'payee': 'Eduardo Cagal Mixtega', 'memo': None, 'clearing_date': '06/16/25', 'passing_date': '6/13/2025', 'check_number': '10236'}, {'amount': '240.23', 'payee': 'Jessica N Coonce', 'memo': None, 'clearing_date': '06/16/25', 'passing_date': '6/13/2025', 'check_number': '10237'}, {'amount': '386.47', 'payee': 'Mirella Gomez Diaz', 'memo': 'Photo Safe Deposit Details on Bank', 'clearing_date': None, 'passing_date': '6/13/2025', 'check_number': '10238'}, {'amount': '655.54', 'payee': 'Fernando Martinez Lemus', 'memo': None, 'clearing_date': '06/13/25', 'passing_date': '8/13/2025', 'check_number': '10239'}]}}}, {'page_9': {'page_types': ['check_images'], 'check_data': {'checks': [{'amount': '794.09', 'payee': 'Sangria Mueller', 'memo': None, 'clearing_date': None, 'passing_date': '6/13/2025', 'check_number': '10240'}, {'amount': '931.00', 'payee': 'Floralia Sanchez Diaz', 'memo': None, 'clearing_date': '06/16/25', 'passing_date': '6/13/2025', 'check_number': '10241'}, {'amount': '130.75', 'payee': 'Haley N Wright', 'memo': None, 'clearing_date': None, 'passing_date': '6/13/2025', 'check_number': '10242'}, {'amount': '438.00', 'payee': 'Family Support Payment Center', 'memo': None, 'clearing_date': '06/20/25', 'passing_date': '8/13/2025', 'check_number': '10243'}, {'amount': '931.01', 'payee': 'Eduardo Cagal Mixtaga', 'memo': None, 'clearing_date': None, 'passing_date': '6/27/2025', 'check_number': '10244'}, {'amount': '866.21', 'payee': 'Fernando Martinez Lemus', 'memo': None, 'clearing_date': None, 'passing_date': '6/27/2025', 'check_number': '10247'}, {'amount': '699.13', 'payee': 'Sangria Mueller', 'memo': None, 'clearing_date': '06/30/25', 'passing_date': '8/27/2025', 'check_number': '10248'}, {'amount': '894.36', 'payee': 'Floralia Sanchez Diaz', 'memo': None, 'clearing_date': '06/30/25', 'passing_date': '6/27/2025', 'check_number': '10249'}]}}}]
        self._save_control_totals()
        processing_stats = self._save_extracted_data()
        
        return {
            "status": "success",
            "control_totals": self.control_totals,
            "processing_stats": processing_stats,
            "page_count": len(self.page_data)
        }

    def _save_control_totals(self):
        # Save control totals to document
        self.document.control_item = self.control_totals
        self.document.save()

    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Save extracted data to database models.
        """
        stats = {
            "key_items": 0,
            "line_items": 0,
            "check_items": 0,
            "pages_processed": 0
        }
        page_data = self.page_data
        checks_linked = dict()
        with transaction.atomic():
            for page_idx, page_item in enumerate(page_data):
                page_key = f"page_{page_idx + 1}"
                page_content = page_item.get(page_key, {})
                
                # Process transactions
                transactions = page_content.get("transactions", {})
                
                # Save key items (summary data) - Not typically in transactions but if we had them
                # In this new structure, summary is in self.control_totals, but let's check if transactions has key_items
                # The schema for transactions is TransactionList which has line_items.
                
                line_items_data = transactions.get("line_items", [])
                
                for line_idx, line_item in enumerate(line_items_data):
                    # check if check related transaction already exists
                    check_num = line_item.get("check_number", "")
                    check_num = str(check_num).lstrip('0') if check_num else check_num
                    if check_num and str(check_num).strip() and (check_num in checks_linked):
                        if len(checks_linked[check_num].description) > len(line_item.get("description", "")):
                            continue
                        else:
                            checks_linked[check_num].description = line_item.get("description", "")
                            continue

                    line_item_obj = self._save_line_item(page_idx + 1, line_idx + 1, line_item)
                    if line_item_obj.is_check_transaction and line_item_obj.check_number:
                        checks_linked[line_item_obj.check_number] = line_item_obj

                    stats["line_items"] += 1
                
                # Save check data
                check_data = page_content.get("check_images_data", {})
                checks = check_data.get("checks", [])
                for check_item in checks:
                    check_obj = self._save_check_item(page_idx + 1, check_item)
                    stats["check_items"] += 1
                    
                    # Try to link check to line item
                    self._link_check_to_line_item(check_obj)
                
                stats["pages_processed"] += 1
        
        # cleanup
        del(checks_linked)
        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """
        Parse amount string to Decimal.
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
        is_check_transaction = line_data.get("is_check_transaction", False) is not None
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
        """
        check_number = check_data.get("check_number", "")
        check_number = str(check_number).lstrip('0') if check_number else check_number
        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.document,
            page_number=page_number,
            amount=str(check_data.get("amount", "")),
            payee=check_data.get("payee", ""),
            memo=check_data.get("memo", ""),
            clearing_date=check_data.get("clearing_date", ""),
            passing_date=check_data.get("passing_date", ""),
            check_number=check_number,
            related_line_item=None  # Will be set in _link_check_to_line_item
        )
        
        return check_item
    
    def _link_check_to_line_item(self, check_item: MonthlyDocumentBankCheckItem):
        """
        Try to link a check item to its corresponding line item.
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
        else:
            # Check not found in line items, add it as a new line item in the transaction table
            # Get the last line number for this page
            last_line_item = MonthlyDocumentBankLineItem.objects.filter(
                document=self.document,
                page_number=check_item.page_number
            ).order_by('-line_number').first()
            
            # Calculate next line number for this page
            next_line_number = (last_line_item.line_number + 1) if last_line_item else 1
            
            # Parse amount from check
            amount = self._parse_amount(check_item.amount)
            
            # Create a new line item from the check data
            new_line_item = MonthlyDocumentBankLineItem.objects.create(
                document=self.document,
                page_number=check_item.page_number,
                line_number=next_line_number,
                date=check_item.clearing_date or check_item.passing_date or "",
                description=f"Check #{check_item.check_number} to {check_item.payee}" + (f" - {check_item.memo}" if check_item.memo else ""),
                amount=amount,
                transaction_type='debit',  # Checks are typically debits
                debit_amount=check_item.amount,
                credit_amount=None,
                is_check_transaction=True,
                check_number=check_item.check_number,
                gl_account=None,
                offset_gl_account=None
            )
            
            # Link the check to the newly created line item
            check_item.related_line_item = new_line_item
            check_item.save()
            logger.info(f"Check #{check_item.check_number} not found in line items. Created new line item {new_line_item.id} on page {check_item.page_number}, line {next_line_number}")

