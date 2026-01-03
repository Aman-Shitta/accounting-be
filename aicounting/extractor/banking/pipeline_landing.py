from __future__ import annotations

import os
import logging
import time
import tempfile
import re
import json
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

from extractor.banking.models import *
from extractor.banking.page_classifier import PageClassifier


logger = logging.getLogger(__name__)


def convert_decimals_to_float(obj):
    """
    Recursively convert all Decimal objects to strings for JSON serialization.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    else:
        return obj


class DocumentProcessor(BaseDocumentProcessor):
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.page_data = []
        self.pages_data = {}
        self.control_totals = {}
        self.rectifier = self.get_rectifier()
        
        
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

    def get_rectifier(self):
        from extractor.rectifier.rectify import DocumentRectifier
        return DocumentRectifier()

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


    def process_document(self, file_bytes: bytes, mime_type: None, md=False, special_rules=""):
        page_bytes_list = split_pdf_to_pages(file_bytes)
        
        for i, page_bytes in enumerate(page_bytes_list):
            page_num = i + 1
            logger.info(f"Processing page {page_num}...")
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
                
                logger.info(f"Page {page_num} classified as: {page_types}")

                page_result = {"page_types": page_types}
                
                page_types_names = [pt['type'] if isinstance(pt, dict) else pt for pt in page_types]


                logger.info(f"[DEBUG] Page {page_num} types names: {page_types_names}")
                check_key = None

                # 3. Extract Data based on classification
                if "transaction_table" in page_types_names:
                    transaction_response = self.client.extract(
                        schema=self.transaction_schema,
                        markdown=BytesIO(markdown_content.encode('utf-8'))
                    )
                    # Store both extraction data and full response for metadata
                    page_result["transactions"] = transaction_response.extraction
                
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
                
                # Rectify extracted data using AI visual verification
                page_result = self.rectifier.rectify_document(
                    extracted_data=page_result,
                    page_bytes=page_bytes,
                    config={
                        'check_key':check_key
                    }
                )

                self.pages_data[page_num] = {
                    "page_types": page_types_names,
                    "markdown": markdown_content,
                    'extracted_data': page_result
                }

                # self.page_data.append({f"page_{page_num}": page_result})
                    
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
        

        # Check if summary is incomplete and re-extract if needed
        if self.control_totals and self._is_summary_incomplete():
            logger.info("Summary is incomplete, attempting re-extraction from combined pages")
            relevant_pages = self._get_relevant_pages()
            if relevant_pages:
                enhanced_summary = self._extract_summary_from_combined_pages(relevant_pages)
                if enhanced_summary:
                    self.control_totals = enhanced_summary
                    logger.error("Successfully re-extracted summary from combined pages")

        self._save_doc_metadata()
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
        try:
            self.document.control_item = convert_decimals_to_float(self.control_totals)
            self.pages_data['control_totals'] = self.document.control_item
            self.document.save()
        except Exception as e:
            logger.error(f"Failed to convert control totals for saving: {self.control_totals} : {e}")
            self.document.control_item = {}
            self.pages_data['control_totals'] = {}
            self.document.save()
    
    def _save_doc_metadata(self):
        # Save any document-level metadata if needed
        # Convert any Decimals in pages_data before saving
        try:
            import json
            self.document.markdown_metadata = convert_decimals_to_float(self.pages_data)
            self.document.save()
        except Exception as e:
            logger.error(f"Failed to convert markdown metadata for saving: {self.pages_data} : {e}")
            self.document.markdown_metadata = {}
            self.document.save()

    
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
            if num in self.pages_data:
                combined_md += f"\n\n--- Page {num} ---\n\n{self.pages_data[num]['markdown']}"
        
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
        
        checks_linked = dict()

        with transaction.atomic():
            for page_idx, page_content in self.pages_data.items():

                if not isinstance(page_idx, int):
                    continue

                # page_key = f"page_{page_idx + 1}"
                # page_content = page_item.get(page_key, {})
                
                extracted_data = page_content.get("extracted_data", {})
                if not extracted_data:
                    continue
                
                transactions = extracted_data.get("transactions", {})
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

                    if check_num:
                        # replace any non-digit and decimal point characters
                        check_num = re.sub(r'[^\d\.]', '', check_num)

                    
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
                
                # Save check table data (create line items if missing)
                check_table_data = page_content.get("check_table_data", {})
                table_checks = check_table_data.get("checks", [])
                for check_item in table_checks:
                    check_obj = self._save_check_item(page_idx + 1, check_item)
                    if check_obj is None:
                        continue
                    stats["check_items"] += 1
                    self._link_check_to_line_item(check_obj, create_if_missing=True)

                # Save check images data (only link/update existing)
                check_images_data = page_content.get("check_images_data", {})
                image_checks = check_images_data.get("checks", [])
                for check_item in image_checks:
                    check_obj = self._save_check_item(page_idx + 1, check_item)
                    if check_obj is None:
                        continue

                    stats["check_items"] += 1
                    
                    # Try to link check to line item
                    self._link_check_to_line_item(check_obj, create_if_missing=False)
                
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
        
        amount_str = re.sub(r'[^\d\.]', '', str(amount_str))

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
        The line_data already contains rectified values if rectification was applied.
        """
        # Extract basic fields
        date = line_data.get("date", "")
        date = self.format_date(date)
        description = line_data.get("description", "")
        
        # These values are already rectified (if rectification was applied)
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
        
        # Extract rectification metadata (already applied to debit/credit amounts by rectifier)
        is_rectified = line_data.get("is_rectified", False)
        rectified_confidence = line_data.get("rectified_confidence", None)
        rectification_reasoning = line_data.get("rectification_reasoning", None)
        
        # Create line item with all data including rectification metadata
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
            # Rectification fields
            is_rectified=is_rectified,
            rectified_confidence=rectified_confidence,
            rectification_reasoning=rectification_reasoning,
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

        if check_number:
            # replace any non-digit and decimal point characters
            check_number = re.sub(r'[^\d\.]', '', check_number)

        if not check_number or str(check_number).strip() == '':
            return None


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
    
    def _link_check_to_line_item(self, check_item: MonthlyDocumentBankCheckItem, create_if_missing: bool = True):
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
            # Update description with payee and memo
            new_desc_parts = []
            if check_item.payee:
                new_desc_parts.append(f"Payee: {check_item.payee}")
            if check_item.memo:
                new_desc_parts.append(f"Memo: {check_item.memo}")
            
            if new_desc_parts:
                additional_desc = " - ".join(new_desc_parts)
                if additional_desc not in matching_line_item.description:
                    matching_line_item.description = f"{matching_line_item.description} - {additional_desc}"
                    matching_line_item.save()

            check_item.related_line_item = matching_line_item
            check_item.save()
            logger.info(f"Linked check #{check_item.check_number} to line item {matching_line_item.id}")
        elif create_if_missing:
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
        else:
            logger.info(f"Check #{check_item.check_number} not found in line items. Skipping creation as create_if_missing=False.")

