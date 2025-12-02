from __future__ import annotations

import os
import logging
import time
import tempfile
import re
from io import BytesIO
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import  Dict, Optional

from django.conf import settings
from django.db import transaction


from landingai_ade import LandingAIADE
from landingai_ade.lib import pydantic_to_json_schema

from extractor.base import BaseDocumentProcessor
from extractor.prompter import Configuration
from account.models import (
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
    MonthlyAccountingDocument
)
from extractor.utils import split_pdf_to_pages

logger = logging.getLogger(__name__)

# --- Pydantic Models for Extraction Schemas ---

from extractor.banking.models import *
from extractor.banking.page_classifier import PageClassifier



class DocumentProcessor(BaseDocumentProcessor):
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.pages_data = {}
        self.control_totals = {}
        self.page_metadata = {}
        
        
        # Initialize LandingAI client
        # Try to get API key from settings or environment
        api_key = settings.LANDING_AI_API_KEY

        if not api_key:
             logger.error("LANDING_AI_API_KEY not found in settings or env.")
        
        self.client = LandingAIADE(apikey=api_key)
        
        # Prepare schemas
        self.page_classifier = PageClassifier(self)
        self.transaction_schema = pydantic_to_json_schema(TransactionList)
        self.check_schema = pydantic_to_json_schema(CheckList)
        self.summary_schema = pydantic_to_json_schema(StatementSummary)

    def __generate_temp_file__(self, bytes):
        #  LandingAI parse expects a file path. We'll use a temp file.
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=True)
        temp_pdf.write(bytes)
        temp_pdf.flush()
        
        return temp_pdf
    
    def __clean_temp_file__(self, temp_pdf):
        temp_pdf.close()


    def parse_pdf(self, pdf_path):
        parse_response = self.client.parse(
                document=Path(pdf_path),
                model=settings.LANDING_AI_ADE_MODEL, 
            )
        return parse_response


    def process_document(self, file_bytes: bytes, mime_type: None, md=False):
        page_bytes_list = split_pdf_to_pages(file_bytes)
        
        for i, page_bytes in enumerate(page_bytes_list):
            page_num = i + 1
            logger.error(f"Processing page {page_num}...")
            try:
                # generate file from bytes
                temp_file = self.__generate_temp_file__(page_bytes)
                # parse pdf to generate markdown
                parse_response = self.parse_pdf(temp_file.name)
                self.__clean_temp_file__(temp_file)

                markdown_content = parse_response.markdown

                if not markdown_content:
                    logger.error(f"No markdown extracted for page {page_num}")
                    continue

                page_types = self.page_classifier.classify(page_bytes=page_bytes, mime_type=mime_type)
                
                logger.error(f"Page {page_num} classified as: {page_types}")

                page_result = {"page_types": page_types}
                
                page_types_names = [pt['type'] if isinstance(pt, dict) else pt for pt in page_types]

                self.pages_data[page_num] = {
                    "page_types": page_types_names,
                    "markdown": markdown_content,
                }

                print(f"[DEBUG] Page {page_num} types names: {page_types_names}")

                # 3. Extract Data based on classification
                if "transaction_table" in page_types_names:
                    transaction_response = self.client.extract(
                        schema=self.transaction_schema,
                        markdown=BytesIO(markdown_content.encode('utf-8'))
                    )
                    # Store both extraction data and full response for metadata
                    page_result["transactions"] = transaction_response.extraction
                    page_result["transaction_response"] = transaction_response  # Keep full response
                
                if "check_images" in page_types_names or "check_table" in page_types_names:
                    check_response = self.client.extract(
                        schema=self.check_schema,
                        markdown=BytesIO(markdown_content.encode('utf-8'))
                    )
                    check_key = f"check_table_data" if "check_table" in page_types_names else "check_images_data"
                    page_result[check_key] = check_response.extraction
                
                if "summary_table" in page_types_names and not self.control_totals:
                    summary_response = self.client.extract(
                        schema=self.summary_schema,
                        markdown=BytesIO(markdown_content.encode('utf-8'))
                    )
                    self.control_totals = summary_response.extraction
                
                self.page_data.append({f"page_{page_num}": page_result})
                    
            except Exception as e:
                logger.error(f"Error processing page {page_num}: {e}")
                import os, sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                logger.error(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

            finally:
                # Ensure temp file is cleaned up
                try:
                    self.__clean_temp_file__(temp_file)
                except Exception:
                    pass
                continue
        
        self._save_doc_metadata()

        # Check if summary is incomplete and re-extract if needed
        if self.control_totals and self._is_summary_incomplete():
            logger.error("Summary is incomplete, attempting re-extraction from combined pages")
            relevant_pages = self._get_relevant_pages()
            if relevant_pages:
                enhanced_summary = self._extract_summary_from_combined_pages(relevant_pages)
                if enhanced_summary:
                    self.control_totals = enhanced_summary
                    logger.error("Successfully re-extracted summary from combined pages")

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
    
    def _save_doc_metadata(self):
        # Save any document-level metadata if needed
        self.document.markdown_metadata = self.pages_data
    
    def _is_summary_incomplete(self) -> bool:
        """Check if summary has missing deposits or withdrawals."""
        if not self.control_totals:
            return True
        total_deposits = self.control_totals.get("total_deposits")
        total_withdrawals = self.control_totals.get("total_withdrawals")
        return total_deposits is None or total_withdrawals is None
    
    def _get_relevant_pages(self):
        """Get pages with transaction or summary data."""
        relevant = []
        for page_num, info in self.pages_data.items():
            types = info.get("page_types", [])
            if "transaction_table" in types or "summary_table" in types:
                relevant.append(page_num)
        return sorted(relevant)
    
    def _extract_summary_from_combined_pages(self, page_numbers):
        """Extract summary from combined markdown of multiple pages."""
        combined_md = ""
        for num in page_numbers:
            if num in self.page_metadata:
                combined_md += f"\n\n--- Page {num} ---\n\n{self.page_metadata[num]['markdown']}"
        
        if not combined_md:
            return {}
        
        try:
            response = self.client.extract(
                schema=self.summary_schema,
                markdown=BytesIO(combined_md.encode('utf-8'))
            )
            return response.extraction
        except Exception as e:
            logger.error(f"Failed to extract summary from combined pages: {e}")
            return {}

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
                    check_num = str(check_num).lstrip('0').strip('*') if check_num else check_num
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
        logger.error(f"Saved extracted data: {stats}")
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
            logger.error(f"Failed to parse amount '{amount_str}': {e}")
            return None

    def format_date(self, date_str: str) -> str:
        """
        Format date string to standard DD-Month-YYYY format.
        Handles formats like: Jun1, 2025 | 1 June 2025 | 06/01/2025 | 6-1-2025
        Uses dateutil.parser for intelligent parsing.
        """
        from dateutil import parser
        
        if not date_str or not str(date_str).strip():
            return date_str
        
        date_str = str(date_str).strip()
        
        # Month name mapping
        month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December"
        }
        
        try:
            # Use dateutil parser for intelligent date parsing
            # dayfirst=False means MM/DD/YYYY is preferred over DD/MM/YYYY for ambiguous dates
            parsed_date = parser.parse(date_str, dayfirst=False, fuzzy=True)
            
            day = parsed_date.day
            month_name = month_names[parsed_date.month]
            year = parsed_date.year
            
            return f"{day:02d}-{month_name}-{year}"
            
        except (ValueError, parser.ParserError) as e:
            # If dateutil fails, try MM/YYYY pattern (assume day 01)
            match = re.match(r'(\d{1,2})[/-](\d{4})', date_str)
            if match:
                month, year = match.groups()
                month_num = int(month)
                if 1 <= month_num <= 12:
                    month_name = month_names[month_num]
                    return f"01-{month_name}-{year}"
            
            logger.error(f"Could not parse date format: {date_str} - {e}")
            return date_str  # Return as-is if no match

    def _save_line_item(self, page_number: int, line_number: int, line_data: Dict) -> MonthlyDocumentBankLineItem:
        """
        Save a transaction line item to the database.
        """
        # Extract basic fields
        date = line_data.get("date", "")
        date = self.format_date(date)
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
            logger.error(f"Failed to parse amounts for line {page_number}.{line_number}: {e}")

        # Check transaction detection
        is_check_transaction = line_data.get("is_check_transaction", False) is not None
        check_number = line_data.get("check_number", "") if is_check_transaction else None
        
        if is_check_transaction:
            if not debit_amount_raw:
                debit_amount_raw = credit_amount_raw
                credit_amount_raw = ""

        # Extract confidence score and metadata
        amount_confidence = line_data.get("amount_confidence", None)
        bounding_box = line_data.get("bounding_box", None)
        
        # Build extraction metadata
        extraction_metadata = {}
        if amount_confidence is not None:
            extraction_metadata["amount_confidence"] = amount_confidence
        if bounding_box:
            extraction_metadata["bounding_box"] = bounding_box
        
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
            amount_confidence=amount_confidence,
            extraction_metadata=extraction_metadata if extraction_metadata else None,
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
        check_number = str(check_number).lstrip('0').strip('*') if check_number else check_number

        parsed_clearing_date = self.format_date(check_data.get("clearing_date", "")) if check_data.get("clearing_date", "") else ""
        parsed_passing_date = self.format_date(check_data.get("passing_date", "")) if check_data.get("passing_date", "") else ""

        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.document,
            page_number=page_number,
            amount=str(check_data.get("amount", "")),
            payee=check_data.get("payee", ""),
            memo=check_data.get("memo", ""),
            clearing_date=parsed_clearing_date,
            passing_date=parsed_passing_date,
            check_number=check_number,
            related_line_item=None
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
            logger.error(f"Linked check #{check_item.check_number} to line item {matching_line_item.id}")
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
            logger.error(f"Check #{check_item.check_number} not found in line items. Created new line item {new_line_item.id} on page {check_item.page_number}, line {next_line_number}")

