from __future__ import annotations

import os
import sys
import logging
import tempfile
import re
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, List
from collections import defaultdict

from django.conf import settings
from django.db import transaction

from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from extractor.base import BaseDocumentProcessor
from extractor.utils import convert_decimals_to_float, generate_temp_pdf, clean_temp_file
from account.models import MonthlyAccountingDocument
from extractor.utils import split_pdf_to_pages
from extractor.persistence.bank_statement_saver import BankStatementSaver

from extractor.statement_models import BankStatementExtraction

logger = logging.getLogger(__name__)


class ExtractorPipeline(BaseDocumentProcessor):
    """
    LandingAI Extraction Pipeline.

    Processes the bank statement using LandingAI ADE and a unified Pydantic schema,
    rectifies amounts using Gemini, and saves results using the BankStatementSaver.
    """

    def __init__(self, doc: MonthlyAccountingDocument):
        super().__init__(doc)
        self.extracted_data: Optional[Dict] = None
        self.extracted_meta_data = None
        self.control_totals: Dict = {}
        self.markdown_content: str = ""
        self.landing_metadata: Dict = {}
        # Store page bytes for rectification
        self.page_bytes_list: List[bytes] = []
        # Store gemini output per page
        self.gemini_output: Dict[str, List] = {}
        self.rectified_data: Dict = {}

        # Initialize rectifier
        self.transaction_rectifier = self._get_transactions_rectifier()

        # Prepare the unified extraction schema
        self.extraction_schema = pydantic_to_json_schema(BankStatementExtraction)

        self.client = LandingAIADE()

        

    def _get_transactions_rectifier(self):
        """Initialize and return the document rectifier."""
        from extractor.rectifier.rectify import get_rectifier
        return get_rectifier()

    def _generate_temp_file(self, file_bytes: bytes):
        """Generate a temporary file from bytes for LandingAI processing."""
        return generate_temp_pdf(file_bytes)

    def _parse_document(self, pdf_path: str):
        """
        Parse the entire PDF document and return markdown content.
        """
        parse_response = self.client.parse(
            document=Path(pdf_path),
            model=settings.LANDING_AI_ADE_MODEL,
            custom_prompts = {
                "figure": (
                    "If the page has check images, extract the following fields and include them in the markdown:\n"
                    "- check_number: <number>\n"
                    "- date: <date>\n"
                    "- payee: <payee>\n"
                    "- memo: <memo>"
                )
            },
        )
        self.markdown_content = parse_response.markdown

    def _extract_data(self):
        """
        Extract structured data from markdown using the BankStatementExtraction schema.
        """
        response = self.client.extract(
            schema=self.extraction_schema,
            markdown=BytesIO(self.markdown_content.encode('utf-8')),
        )

        self.extracted_data = response.extraction
        self.extracted_meta_data = response.extraction_metadata
        self.landing_metadata = response.metadata.to_dict()
    
    def process_document(self, file_bytes: bytes, **kwargs) -> Dict:
        """
        Process the entire bank statement document at once.
        """
        temp_file = None
        saver = BankStatementSaver(self.document)
        processing_stats = {"line_items": 0, "check_items": 0, "pages_processed": 0}

        try:
            # Step 1: Generate temp file and parse entire document
            logger.info("Parsing entire document to markdown...")
            temp_file = self._generate_temp_file(file_bytes)
            self._parse_document(temp_file.name)

            if not self.markdown_content:
                logger.error("No markdown extracted from document")
                return {"status": "error", "message": "Failed to extract markdown from document"}

            if self.debug_storage:
                self.debug_storage.save_parsed_markdown(self.markdown_content, "full_document_markdown.md")

            # Step 2: Extract structured data using unified schema
            logger.info("Extracting transactions and summary from document...")
            self._extract_data()

            if not self.extracted_data:
                logger.error("No data extracted from document")
                return {"status": "error", "message": "Failed to extract data from document"}

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    convert_decimals_to_float(self.extracted_data), "landing_ai_extracted_data.json"
                )
                if self.extracted_meta_data:
                    self.debug_storage.save_extracted_metadata(
                        convert_decimals_to_float(self.extracted_meta_data), "landing_ai_extraction_metadata.json"
                    )
                if self.landing_metadata:
                    self.debug_storage.save_extracted_data(
                        convert_decimals_to_float(self.landing_metadata), "landing_ai_response_metadata.json"
                    )

            self.brute_page_fix()

            if self.debug_storage:
                self.debug_storage.save_extracted_data(
                    convert_decimals_to_float(self.extracted_data), "extracted_data_after_page_number_fix.json"
                )

            # Step 3: Rectify amounts page by page
            logger.info("Rectifying extracted amounts...")
            self._rectify(file_bytes)

            if self.debug_storage:
                self.debug_storage.save_rectified_data(
                    convert_decimals_to_float(self.rectified_data), "rectified_transactions.json"
                )

            # Step 4: Post-process and extract control totals
            self._process_control_totals()
            
            # Step 5: Save using unified persistence layer
            saver.save_control_totals(self.control_totals)
            processing_stats = saver.save_transactions(self.rectified_data.get("transactions", []))

            return {
                "status": "success",
                "control_totals": self.control_totals,
                "processing_stats": processing_stats,
                "transaction_count": len(self.extracted_data.get("transactions", []))
            }

        except Exception as e:
            logger.error(f"Error processing document: {e}")
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

            if self.debug_storage:
                self.debug_storage.save_error_log(e, {
                    "stage": "process_document",
                    "has_markdown": bool(self.markdown_content),
                    "has_extracted_data": bool(self.extracted_data)
                })

            return {"status": "error", "message": str(e)}

        finally:
            if temp_file:
                clean_temp_file(temp_file)
            
            # Use saver for metadata
            metadata = {
                "markdown": self.markdown_content,
                "extracted_data": self.extracted_data,
                "control_totals": self.control_totals,
                "landing_metadata": self.landing_metadata,
                "gemini_output": self.gemini_output,
                "rectifier_items": self.rectified_data.get("rectifier_items", [])
            }
            saver.save_metadata(metadata)

    def brute_page_fix(self):
        """
        Update transaction page numbers using metadata references.
        """
        transactions = self.extracted_data.get('transactions', [])
        metadata_transactions = self.extracted_meta_data.get(
            'transactions', []) if self.extracted_meta_data else []

        # Do NOT sort transactions here based on global_id, local_id, or table_number.
        # Landing AI naturally chunks arrays sequentially top-to-bottom. However, 
        # the LLM often completely hallucinates numerical IDs causing massive scrambling if sorted.
        
        last_known_page_number = 1
        for i in range(len(transactions)):
            try:
                # Retain the exact original sequence from Landing AI which is natively chronological
                transactions[i]['_original_index'] = i
                
                if i >= len(metadata_transactions):
                    transactions[i]['page_number'] = last_known_page_number
                    continue

                actual_page_number_str = None
                for field_item in ['amount', 'description']:
                    field_metadata = metadata_transactions[i].get(field_item, {})
                    references = field_metadata.get('references', [])

                    if references:
                        sorted_refs = sorted(references)
                        ref_str = sorted_refs[0]
                        parts = ref_str.split('-')
                        if parts and parts[0].strip().isdigit():
                            actual_page_number_str = parts[0].strip()
                            logger.debug(f"Found page reference for transaction {i}: page {actual_page_number_str}")
                            break

                if actual_page_number_str is not None:
                    actual_page_number = int(actual_page_number_str) + 1
                    transactions[i]['page_number'] = actual_page_number
                    last_known_page_number = actual_page_number
                else:
                    transactions[i]['page_number'] = last_known_page_number
            except Exception as e:
                logger.error(f"Error updating page number for transaction index {i}: {e}")
                transactions[i]['page_number'] = last_known_page_number

        # Safely ensure pages are clumped together correctly without disturbing chronological lines
        transactions.sort(key=lambda x: (x.get('page_number', 1), x.get('_original_index', 0)))

        # Regenerate strictly robust and clean IDs completely overriding LLM hallucinations 
        current_page = None
        global_counter = 1
        local_counter = 1

        for t in transactions:
            p_num = t.get('page_number', 1)
            if p_num != current_page:
                current_page = p_num
                local_counter = 1  # Reset purely strictly on a new page

            t['global_id'] = global_counter
            t['local_id'] = local_counter
            t['id'] = local_counter
            
            # Clean up the trace key
            if '_original_index' in t:
                del t['_original_index']
                
            global_counter += 1
            local_counter += 1

        logger.info(f"Transaction page numbers fixed and IDs regenerated for {len(transactions)} transactions")
        self.extracted_data['transactions'] = transactions

    def _process_control_totals(self):
        """Extract and process control totals from the summary."""
        summary = self.extracted_data.get("summary", {})

        self.control_totals = {
            "beginning_balance": summary.get("beginning_balance"),
            "ending_balance": summary.get("ending_balance"),
            "total_deposits": summary.get("total_deposits"),
            "total_withdrawals": summary.get("total_withdrawals"),
            "total_credits_count": summary.get("total_credits_count"),
            "total_withdrawl_count": summary.get("total_withdrawl_count"),
        }

        logger.info(f"Control totals extracted: {self.control_totals}")

    def _rectify(self, file_bytes):
        transactions = self.extracted_data.get("transactions", [])

        self.rectified_data = {
            'transactions': [],
            'summary': self.extracted_data.get('summary', {}),
            'rectifier_items': []
        }

        rectified_items, rectifier_items = self.transaction_rectifier.rectify_document(
            file_bytes,
            master_data=transactions,
            debug_storage=self.debug_storage
        )
        self.rectified_data['transactions'] = rectified_items
        self.rectified_data['rectifier_items'] = rectifier_items
