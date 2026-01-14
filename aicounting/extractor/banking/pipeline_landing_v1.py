from __future__ import annotations

import os
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
from extractor.prompter import Configuration
from account.models import (
    MonthlyDocumentBankCheckItem,
    MonthlyDocumentBankLineItem,
    MonthlyAccountingDocument
)
from extractor.utils import split_pdf_to_pages

from extractor.banking.statement_models import (
    BankStatementExtraction,
    StatementTransaction,
    StatementSummaryTotals
)

logger = logging.getLogger(__name__)


def convert_decimals_to_float(obj):
    """
    Recursively convert all Decimal objects to floats for JSON serialization.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_float(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    else:
        return obj


class DocumentProcessorV1(BaseDocumentProcessor):
    """
    Simplified document processor that processes the entire bank statement document
    at once using the BankStatementExtraction schema, then post-processes and saves
    the extracted data to the database.
    """
    
    def __init__(self, config: Configuration, doc: MonthlyAccountingDocument):
        super().__init__(config, doc)
        self.extracted_data: Optional[Dict] = None
        self.extracted_meta_data = None
        self.control_totals: Dict = {}
        self.markdown_content: str = ""
        self.page_bytes_list: List[bytes] = []  # Store page bytes for rectification
        
        # Initialize rectifier
        self.rectifier = self._get_rectifier()
        
        # Initialize LandingAI client
        api_key = settings.LANDING_AI_API_KEY
        if not api_key:
            logger.error("LANDING_AI_API_KEY not found in settings or env.")
        
        self.client = LandingAIADE(apikey=api_key)
        
        # Prepare the unified extraction schema
        self.extraction_schema = pydantic_to_json_schema(BankStatementExtraction)

    def _get_rectifier(self):
        """Initialize and return the document rectifier."""
        from extractor.rectifier.rectify import DocumentRectifier
        return DocumentRectifier()

    def _generate_temp_file(self, file_bytes: bytes) -> tempfile.NamedTemporaryFile:
        """Generate a temporary file from bytes for LandingAI processing."""
        temp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temp_pdf.write(file_bytes)
        temp_pdf.flush()
        return temp_pdf
    
    def _clean_temp_file(self, temp_pdf: tempfile.NamedTemporaryFile):
        """Clean up temporary file."""
        try:
            temp_pdf.close()
            os.unlink(temp_pdf.name)
        except Exception:
            pass

    def _parse_document(self, pdf_path: str) -> str:
        """
        Parse the entire PDF document and return markdown content.
        """
        parse_response = self.client.parse(
            document=Path(pdf_path),
            model=settings.LANDING_AI_ADE_MODEL,
        )
        return parse_response.markdown

    def _extract_data(self, markdown_content: str) -> Dict:
        """
        Extract structured data from markdown using the BankStatementExtraction schema.
        """
        response = self.client.extract(
            schema=self.extraction_schema,
            markdown=BytesIO(markdown_content.encode('utf-8')),
        )
        self.extracted_data = response.extraction
        self.extracted_meta_data = response.extraction_metadata
        return response.extraction

    def process_document(self, file_bytes: bytes, mime_type: str = None, md: bool = False, special_rules: str = "") -> Dict:
        """
        Process the entire bank statement document at once.
        
        1. Split PDF into pages (for rectification)
        2. Parse the full PDF to markdown
        3. Extract all transactions and summary using the unified schema
        4. Rectify amounts page by page
        5. Post-process and save to database
        """
        temp_file = None
        
        try:
            # Step 0: Split PDF into pages for later rectification
            logger.info("Splitting PDF into pages...")
            self.page_bytes_list = split_pdf_to_pages(file_bytes)
            logger.info(f"Document has {len(self.page_bytes_list)} pages")
            
            # Step 1: Generate temp file and parse entire document
            logger.info("Parsing entire document to markdown...")
            temp_file = self._generate_temp_file(file_bytes)
            self.markdown_content = self._parse_document(temp_file.name)
            
            if not self.markdown_content:
                logger.error("No markdown extracted from document")
                return {"status": "error", "message": "Failed to extract markdown from document"}
            
            logger.info(f"Extracted {len(self.markdown_content)} characters of markdown")
            
            # Step 2: Extract structured data using unified schema
            logger.info("Extracting transactions and summary from document...")
            self._extract_data(self.markdown_content)
            
            if not self.extracted_data:
                logger.error("No data extracted from document")
                return {"status": "error", "message": "Failed to extract data from document"}
            
            # Step 3: Rectify amounts page by page
            logger.info("Rectifying extracted amounts...")
            self._rectify_transactions()
            
            # Step 4: Post-process and extract control totals
            self._process_control_totals()
            
            # Step 5: Save metadata and extracted data
            self._save_doc_metadata()
            self._save_control_totals()
            processing_stats = self._save_extracted_data()
            
            return {
                "status": "success",
                "control_totals": self.control_totals,
                "processing_stats": processing_stats,
                "transaction_count": len(self.extracted_data.get("transactions", []))
            }
            
        except Exception as e:
            logger.error(f"Error processing document: {e}")
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")
            return {"status": "error", "message": str(e)}
            
        finally:
            if temp_file:
                self._clean_temp_file(temp_file)

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

    def _rectify_transactions(self):
        """
        Rectify transaction amounts page by page using the DocumentRectifier.
        
        The rectifier expects data in the format:
        {"transactions": {"line_items": [{"debit_amount": ..., "credit_amount": ...}]}}
        
        Our new schema has: {"transactions": [{"amount": ..., "type": "debit/credit"}]}
        
        This method:
        1. Groups transactions by page_number
        2. Converts each page's transactions to rectifier format
        3. Calls rectifier for each page with page image
        4. Converts rectified data back to our schema format
        """
        transactions = self.extracted_data.get("transactions", [])
        
        if not transactions:
            logger.info("No transactions to rectify")
            return
        
        # Group transactions by page number
        transactions_by_page = defaultdict(list)
        transaction_indices = defaultdict(list)  # Track original indices
        
        for idx, txn in enumerate(transactions):
            page_num = txn.get("page_number", 1)
            transactions_by_page[page_num].append(txn)
            transaction_indices[page_num].append(idx)
        
        logger.info(f"Rectifying transactions across {len(transactions_by_page)} pages")
        
        # Process each page
        for page_num, page_transactions in transactions_by_page.items():
            try:
                # Get page bytes (page_num is 1-indexed, list is 0-indexed)
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(self.page_bytes_list):
                    logger.warning(f"Page {page_num} out of range, skipping rectification")
                    continue
                
                page_bytes = self.page_bytes_list[page_idx]
                
                # Convert to rectifier format
                line_items = self._convert_to_rectifier_format(page_transactions)
                
                # Prepare data for rectifier
                extracted_data_for_rectifier = {
                    "transactions": {
                        "line_items": line_items
                    }
                }
                
                # Call rectifier
                rectified_data = self.rectifier.rectify_document(
                    page_bytes=page_bytes,
                    extracted_data=extracted_data_for_rectifier,
                    config={"check_key": None}
                )
                
                # Convert back to our schema format and update original transactions
                rectified_line_items = rectified_data.get("transactions", {}).get("line_items", [])
                original_indices = transaction_indices[page_num]
                
                self._apply_rectified_data(rectified_line_items, original_indices)
                
                logger.info(f"Page {page_num}: Rectified {len(page_transactions)} transactions")
                
            except Exception as e:
                logger.error(f"Error rectifying page {page_num}: {e}")
                continue

    def _convert_to_rectifier_format(self, transactions: List[Dict]) -> List[Dict]:
        """
        Convert transactions from new schema format to rectifier format.
        
        New schema: {"amount": 100.0, "type": "debit", ...}
        Rectifier format: {"debit_amount": "100.0", "credit_amount": "", ...}
        """
        line_items = []
        
        for txn in transactions:
            amount = txn.get("amount")
            txn_type = txn.get("type", "").lower()
            
            line_item = {
                "date": txn.get("date", ""),
                "description": txn.get("description", ""),
                "debit_amount": "",
                "credit_amount": "",
                "is_check_transaction": bool(txn.get("check_number")),
                "check_number": txn.get("check_number", ""),
            }
            
            # Set amount in appropriate column based on type
            if amount is not None:
                amount_str = str(amount)
                if txn_type == "debit":
                    line_item["debit_amount"] = amount_str
                elif txn_type == "credit":
                    line_item["credit_amount"] = amount_str
            
            line_items.append(line_item)
        
        return line_items

    def _apply_rectified_data(self, rectified_line_items: List[Dict], original_indices: List[int]):
        """
        Apply rectified data back to the original transactions.
        
        Converts rectifier format back to our schema format.
        """
        transactions = self.extracted_data.get("transactions", [])
        
        for i, line_item in enumerate(rectified_line_items):
            if i >= len(original_indices):
                break
            
            original_idx = original_indices[i]
            if original_idx >= len(transactions):
                continue
            
            txn = transactions[original_idx]
            
            # Check if rectification was applied
            is_rectified = line_item.get("is_rectified", False)
            
            if is_rectified:
                # Get rectified amounts
                debit_amount = line_item.get("debit_amount")
                credit_amount = line_item.get("credit_amount")
                
                # Determine the new amount and type
                if debit_amount and str(debit_amount).strip():
                    try:
                        txn["amount"] = float(re.sub(r'[^\d\.\-]', '', str(debit_amount)))
                        txn["type"] = "debit"
                    except (ValueError, TypeError):
                        pass
                elif credit_amount and str(credit_amount).strip():
                    try:
                        txn["amount"] = float(re.sub(r'[^\d\.\-]', '', str(credit_amount)))
                        txn["type"] = "credit"
                    except (ValueError, TypeError):
                        pass
                
                # Add rectification metadata to transaction
                txn["is_rectified"] = True
                txn["rectified_confidence"] = line_item.get("rectified_confidence")
                txn["rectification_reasoning"] = line_item.get("rectification_reasoning")
                
                logger.debug(f"Applied rectification to transaction {original_idx}: amount={txn.get('amount')}, type={txn.get('type')}")

    def _save_control_totals(self):
        """Save control totals to document."""
        try:
            self.document.control_item = convert_decimals_to_float(self.control_totals)
            self.document.save()
            logger.info("Control totals saved to document")
        except Exception as e:
            logger.error(f"Failed to save control totals: {e}")
            self.document.control_item = {}
            self.document.save()
    
    def _save_doc_metadata(self):
        """Save document-level metadata."""
        try:
            metadata = {
                "markdown": self.markdown_content,
                "extracted_data": convert_decimals_to_float(self.extracted_data),
                "control_totals": convert_decimals_to_float(self.control_totals)
            }
            self.document.markdown_metadata = metadata
            self.document.save()
            logger.info("Document metadata saved")
        except Exception as e:
            logger.error(f"Failed to save markdown metadata: {e}")
            self.document.markdown_metadata = {}
            self.document.save()

    def _parse_amount(self, amount_value) -> Optional[Decimal]:
        """Parse amount to Decimal."""
        if amount_value is None:
            return None
        
        if isinstance(amount_value, (int, float)):
            return Decimal(str(amount_value))
        
        amount_str = str(amount_value).strip()
        if amount_str in ['', 'null', 'none', '-']:
            return None
        
        # Clean the amount string
        amount_str = re.sub(r'[^\d\.\-]', '', amount_str)
        
        try:
            return Decimal(amount_str)
        except (InvalidOperation, ValueError, TypeError) as e:
            logger.error(f"Failed to parse amount '{amount_value}': {e}")
            return None

    def _format_date(self, date_str: str) -> str:
        """
        Format date string to standard DD-Month-YYYY format.
        Handles formats like: Jun1, 2025 | 1 June 2025 | 06/01/2025 | 6-1-2025
        """
        from dateutil import parser
        
        if not date_str or not str(date_str).strip():
            return date_str
        
        date_str = str(date_str).strip()
        
        month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December"
        }
        
        try:
            parsed_date = parser.parse(date_str, dayfirst=False, fuzzy=True)
            day = parsed_date.day
            month_name = month_names[parsed_date.month]
            year = parsed_date.year
            return f"{day:02d}-{month_name}-{year}"
        except (ValueError, parser.ParserError) as e:
            # Try MM/YYYY pattern (assume day 01)
            match = re.match(r'(\d{1,2})[/-](\d{4})', date_str)
            if match:
                month, year = match.groups()
                month_num = int(month)
                if 1 <= month_num <= 12:
                    month_name = month_names[month_num]
                    return f"01-{month_name}-{year}"
            
            logger.warning(f"Could not parse date format: {date_str}")
            return date_str

    def _save_extracted_data(self) -> Dict[str, int]:
        """
        Post-process and save extracted transactions to the database.
        """
        stats = {
            "line_items": 0,
            "check_items": 0,
            "pages_processed": set()
        }
        
        transactions = self.extracted_data.get("transactions", [])
        
        if not transactions:
            logger.warning("No transactions found in extracted data")
            return {"line_items": 0, "check_items": 0, "pages_processed": 0}
        
        logger.info(f"Processing {len(transactions)} transactions...")
        
        # Track checks for linking
        checks_by_number: Dict[str, MonthlyDocumentBankLineItem] = {}
        
        for i in range(len(transactions)):
            idx = i
            try:
                
                if 'transactions' in self.extracted_meta_data:
                    if idx < len(self.extracted_meta_data['transactions']):
                        for field_item in self.extracted_data['transactions'][idx]:
                            if field_item in self.extracted_meta_data['transactions'][idx]:
                                if 'references' in self.extracted_meta_data['transactions'][idx][field_item]:

                                    if self.extracted_meta_data['transactions'][idx][field_item]['references']:
                                        self.extracted_meta_data['transactions'][idx][field_item]['references'].sort()

                                        x, *y = self.extracted_meta_data['transactions'][idx][field_item]['references'][0].split('-')
                                        print("*"*50)
                                        if x.strip() and x.isdigit():
                                            print(f"Found page number reference for transaction index {idx}: {x} from field {field_item}")
                                            print(self.extracted_meta_data['transactions'][idx][field_item]['references'])
                                            actual_page_number_str = x
                                            break
                        try:
                            actual_page_number = int(actual_page_number_str) + 1
                        except Exception as e:
                            logger.error(f"Default{idx}: {e}")
                            actual_page_number = transactions[idx]['page_number']
                        transactions[idx]['page_number'] = actual_page_number
            except Exception as e:
                logger.error(f"Error updating page number for transaction index {idx}: {e}")
                    

        with transaction.atomic():
            for idx, txn in enumerate(transactions):
                
                line_item = self._save_transaction(idx + 1, txn)
                stats["line_items"] += 1
                stats["pages_processed"].add(txn.get("page_number", 1))
                
                # Track check transactions for potential linking
                if line_item.is_check_transaction and line_item.check_number:
                    checks_by_number[line_item.check_number] = line_item
        
        stats["pages_processed"] = len(stats["pages_processed"])
        logger.info(f"Saved extracted data: {stats}")
        return stats

    def _save_transaction(self, line_number: int, txn_data: Dict) -> MonthlyDocumentBankLineItem:
        """
        Save a single transaction to the database.
        """
        # Extract and format date
        date = self._format_date(txn_data.get("date", ""))
        
        # Extract description
        description = txn_data.get("description", "")
        
        # Extract amount and type
        amount = self._parse_amount(txn_data.get("amount"))
        transaction_type = txn_data.get("type", "").lower()  # 'debit' or 'credit'
        
        # Determine debit/credit amounts
        debit_amount = None
        credit_amount = None
        
        if transaction_type == "debit" and amount:
            debit_amount = str(amount)
        elif transaction_type == "credit" and amount:
            credit_amount = str(amount)
        
        # Check transaction detection
        check_number = txn_data.get("check_number", "")
        is_check_transaction = bool(check_number and str(check_number).strip())
        
        # Clean check number
        if check_number:
            check_number = str(check_number).lstrip('0').strip('*')
            check_number = re.sub(r'[^\d\.]', '', check_number)
            if not check_number:
                is_check_transaction = False
                check_number = None
        
        # Get page number
        page_number = txn_data.get("page_number", 1)

        # Extract rectification metadata
        is_rectified = txn_data.get("is_rectified", False)
        rectified_confidence = txn_data.get("rectified_confidence")
        rectification_reasoning = txn_data.get("rectification_reasoning")
        
        # Create line item
        line_item = MonthlyDocumentBankLineItem.objects.create(
            document=self.document,
            page_number=page_number,
            line_number=line_number,
            date=date,
            description=description,
            amount=amount,
            transaction_type=transaction_type if transaction_type in ['debit', 'credit'] else None,
            debit_amount=debit_amount,
            credit_amount=credit_amount,
            is_check_transaction=is_check_transaction,
            check_number=check_number if is_check_transaction else None,
            # Rectification fields
            is_rectified=is_rectified,
            rectified_confidence=rectified_confidence,
            rectification_reasoning=rectification_reasoning,
            gl_account=None,
            offset_gl_account=None
        )
        
        # If this is a check transaction, also create a check item
        if is_check_transaction:
            self._create_check_item_from_transaction(line_item, txn_data)
        
        return line_item

    def _create_check_item_from_transaction(self, line_item: MonthlyDocumentBankLineItem, txn_data: Dict):
        """
        Create a check item from a transaction if it's a check transaction.
        """
        check_written_date = txn_data.get("check_written_date", "")
        if check_written_date:
            check_written_date = self._format_date(check_written_date)
        
        # Extract payee and memo from description if present
        description = txn_data.get("description", "")
        payee = ""
        memo = ""
        
        # Try to extract payee from description patterns like "Check #123 to John Doe"
        payee_match = re.search(r'(?:to|payee[:\s]+)([^-]+)', description, re.IGNORECASE)
        if payee_match:
            payee = payee_match.group(1).strip()
        
        memo_match = re.search(r'(?:memo[:\s]+)(.+)', description, re.IGNORECASE)
        if memo_match:
            memo = memo_match.group(1).strip()
        
        check_item = MonthlyDocumentBankCheckItem.objects.create(
            document=self.document,
            page_number=line_item.page_number,
            amount=str(line_item.amount) if line_item.amount else "",
            payee=payee,
            memo=memo,
            clearing_date=line_item.date,
            passing_date=check_written_date,
            check_number=line_item.check_number,
            related_line_item=line_item
        )
        
        logger.debug(f"Created check item for check #{line_item.check_number}")
        return check_item
