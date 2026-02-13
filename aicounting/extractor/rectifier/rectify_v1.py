"""
Document Rectifier V1 for Landing AI V1 Pipeline

Simplified rectifier that:
1. Extracts transactions from Gemini in JSON format
2. Compares with Landing AI line_items by index
3. Updates amounts where they differ or are missing
4. Adds missing transactions if Gemini has more items
"""

import os, sys
import re
import logging
from typing import Dict, List, Any, Tuple, Optional
from decimal import Decimal
from difflib import SequenceMatcher

from extractor.gemini_service import GeminiMixin, JSONHelper

logger = logging.getLogger(__name__)


class DocumentRectifierV1(GeminiMixin):
    """
    Simple rectifier that uses Gemini AI for parallel extraction and comparison.
    """

    def __init__(self):
        """Initialize the rectifier with Gemini service."""
        self.init_gemini()
        self._extraction_schema = self._build_extraction_schema()

    def rectify_document(
        self,
        page_bytes: bytes,
        line_items: List[Dict[str, Any]],
        config: Dict[str, Any] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Rectify extracted document data using Gemini AI.
        
        Args:
            page_bytes: The original page as PDF bytes.
            line_items: List of line items from Landing AI.
            config: Optional configuration parameters.

        Returns:
            Tuple of (rectified_items, gemini_items)
        """
        gemini_items = []
        
        try:
            logger.info(f"Rectifying {len(line_items)} line items using Gemini extraction")

            # Step 1: Extract transactions from page using Gemini
            gemini_items = self._extract_transactions_with_gemini(page_bytes)
            
            if not gemini_items:
                logger.warning("No transactions extracted by Gemini, returning original data")
                return line_items, gemini_items
            
            logger.info(f"Gemini extracted {len(gemini_items)} transactions")
            
            # Step 2: Compare and rectify
            rectified_items = self._compare_and_rectify(line_items, gemini_items)
            
            return rectified_items, gemini_items
            
        except Exception as e:

            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(f"Error during rectification: {exc_type}, {fname}, {exc_tb.tb_lineno}")
            logger.error(f"Rectification error: {str(e)}", exc_info=True)
            return line_items, gemini_items

    def _extract_transactions_with_gemini(self, page_bytes: bytes) -> List[Dict[str, Any]]:
        """Extract transactions from a bank statement page using Gemini."""
        prompt = self._build_extraction_prompt()
        
        page_part = self._gemini_service.create_pdf_part(page_bytes)
        prompt_part = self._gemini_service.cretate_part_from_text(text=prompt)
        
        content = [prompt_part, page_part]
        
        config = self._gemini_service.get_default_config(
            temperature=0.1,
            max_output_tokens=16000,
            response_mime_type="application/json",
            response_schema=self._extraction_schema
        )
        
        try:
            response_text = self._gemini_service.generate_content(
                contents=content,
                config=config
            )
            
            result = JSONHelper.parse_json(response_text)
            
            if not result or 'transactions' not in result:
                logger.warning("No valid extraction data returned from Gemini")
                return []
            
            return result.get('transactions', [])
            
        except Exception as e:
            logger.error(f"Gemini extraction failed: {str(e)}")
            return []

    def _build_extraction_prompt(self) -> str:
        """Build the prompt for Gemini to extract transactions."""
        return """
You are a financial data extraction system.

Extract transactions from the provided page content.

A) Ledger transaction:
- Must contain a date AND a description AND at least one monetary amount.
- Columns may be: date, description, amount, balance OR date, description, debit, credit, balance
- Any text between date and amount should be considered as description
- If a transaction is split across rows, combine into single transaction.

B) Checks table:
- A row may contain repeated sets of (check_number, date, amount).
- Split each set into a transaction.

DATE FORMAT:
- Output date in exact format MM/DD/YYYY (zero-padded).
- Infer the year from the statement period if available.

Return ONLY valid JSON:

{
  "transactions": [
    {
      "id": 1,
      "date": "MM/DD/YYYY",
      "description": "<string>",
      "amount": <number>,
      "type": "debit" or "credit"
    }
  ]
}

Rules:
- Preserve transaction order as it appears.
- Do not invent transactions.
- If none exist, return {"transactions": []}.
- "amount" must be a JSON number (no thousands separators).
"""

    def _build_extraction_schema(self) -> Dict[str, Any]:
        """Build JSON schema for Gemini structured output."""
        return {
            "type": "object",
            "properties": {
                "transactions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "Numerical unique identifier indicating the order as listed on the statement."},
                            "date": {"type": "string", "description": "Transaction or check Date in mm/dd/yyyy format."},
                            "description": {"type": "string", "description": "Description of the transaction or check, with payee and memo information appended for checks if applicable."},
                            "amount": {"type": "number", "description": "Amount of the transaction or check in positive value."},
                            "type": {"type": "string", "enum": ["debit", "credit"], "description": "Indicates whether the transaction is a debit or credit."},
                            "is_check_transaction": {"type": "boolean", "description": "Indicates if the transaction is a check."},
                        },
                        "required": ["id", "date", "description", "amount", "type", "is_check_transaction"]
                    }
                }
            },
            "required": ["transactions"]
        }

    def _compare_and_rectify(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Compare line_items with gemini_items and rectify.
        
        Logic:
        1. If lengths are same: index-by-index match description/date, update amount if different
        2. If gemini has more: find where missing items are and insert them
        """
        if not gemini_items:
            return line_items
        
        len_line = len(line_items)
        len_gemini = len(gemini_items)
        
        if len_line == len_gemini:
            # Same length - simple index-by-index comparison
            return self._rectify_same_length(line_items, gemini_items)
        elif len_gemini > len_line:
            # Gemini has more - find and insert missing items
            return self._rectify_gemini_has_more(line_items, gemini_items)
        else:
            # Line items has more - just update amounts where matched
            return self._rectify_line_items_has_more(line_items, gemini_items)

    def _rectify_same_length(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Rectify when both lists have same length - index by index comparison."""
        rectified = []
        
        for idx, (line_item, gemini_item) in enumerate(zip(line_items, gemini_items)):
            rectified_item = line_item.copy()
            rectified_item['is_rectified'] = False
            rectified_item['was_missing'] = False
            
            # Check if description and date match
            if self._items_match(line_item, gemini_item):
                # Items match - check if amount needs update
                line_amount = self._get_amount(line_item)
                gemini_amount = self._get_amount(gemini_item)
                
                if line_amount is None and gemini_amount is not None:
                    # Line item has no amount, use gemini's
                    rectified_item['amount'] = gemini_amount
                    rectified_item['is_rectified'] = True
                    logger.info(f"Added missing amount at index {idx}: {gemini_amount}")
                elif line_amount != gemini_amount and gemini_amount is not None:
                    # Amounts differ - use gemini's amount
                    rectified_item['amount'] = gemini_amount
                    rectified_item['is_rectified'] = True
                    logger.info(f"Updated amount at index {idx}: {line_amount} -> {gemini_amount}")
            else:
                # Items don't match at this index - keep original
                logger.warning(f"Items don't match at index {idx}")
            
            rectified.append(rectified_item)
        
        return rectified

    def _rectify_gemini_has_more(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Rectify when gemini has more items - find and insert missing."""
        rectified = []
        line_idx = 0
        gemini_idx = 0
        
        while gemini_idx < len(gemini_items):
            gemini_item = gemini_items[gemini_idx]
            
            if line_idx < len(line_items):
                line_item = line_items[line_idx]
                
                if self._items_match(line_item, gemini_item):
                    # Items match - update amount if needed
                    rectified_item = line_item.copy()
                    rectified_item['is_rectified'] = False
                    rectified_item['was_missing'] = False
                    
                    line_amount = self._get_amount(line_item)
                    gemini_amount = self._get_amount(gemini_item)
                    
                    if line_amount is None and gemini_amount is not None:
                        rectified_item['amount'] = gemini_amount
                        rectified_item['is_rectified'] = True
                    elif line_amount != gemini_amount and gemini_amount is not None:
                        rectified_item['amount'] = gemini_amount
                        rectified_item['is_rectified'] = True
                    
                    rectified.append(rectified_item)
                    line_idx += 1
                    gemini_idx += 1
                else:
                    # Check if gemini item matches any upcoming line_item
                    match_found = False
                    for lookahead in range(line_idx, min(line_idx + 5, len(line_items))):
                        if self._items_match(line_items[lookahead], gemini_item):
                            match_found = True
                            break
                    
                    if match_found :
                        # Gemini has an extra item - insert it as missing
                        # Skip check transactions - don't add them as missing
                        if gemini_item.get('is_check_transaction', False):
                            logger.info(f"Skipping extra check transaction from gemini at position {gemini_idx}")
                            gemini_idx += 1
                            continue
                        
                        new_item = self._create_item_from_gemini(gemini_item, line_items[0] if line_items else {})
                        new_item['is_rectified'] = True
                        new_item['was_missing'] = True
                        rectified.append(new_item)
                        logger.info(f"Inserted missing item from gemini at position {len(rectified)}")
                        gemini_idx += 1
                    else:
                        # No match found - keep line_item and move on
                        rectified_item = line_item.copy()
                        rectified_item['is_rectified'] = False
                        rectified_item['was_missing'] = False
                        rectified.append(rectified_item)
                        line_idx += 1
                        gemini_idx += 1
            else:
                # No more line_items - add remaining gemini items as missing
                # Skip check transactions - don't add them as missing
                if gemini_item.get('is_check_transaction', False):
                    logger.info(f"Skipping trailing check transaction from gemini at position {gemini_idx}")
                    gemini_idx += 1
                    continue
                
                new_item = self._create_item_from_gemini(gemini_item, line_items[0] if line_items else {})
                new_item['is_rectified'] = True
                new_item['was_missing'] = True
                rectified.append(new_item)
                logger.info(f"Added trailing item from gemini at position {len(rectified)}")
                gemini_idx += 1
        
        # Add any remaining line_items
        while line_idx < len(line_items):
            rectified_item = line_items[line_idx].copy()
            rectified_item['is_rectified'] = False
            rectified_item['was_missing'] = False
            rectified.append(rectified_item)
            line_idx += 1
        
        # Reassign IDs
        for idx, item in enumerate(rectified):
            item['id'] = idx + 1
        
        return rectified

    def _rectify_line_items_has_more(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Rectify when line_items has more - update matched items only."""
        rectified = []
        gemini_idx = 0
        
        for line_item in line_items:
            rectified_item = line_item.copy()
            rectified_item['is_rectified'] = False
            rectified_item['was_missing'] = False
            
            # Try to find matching gemini item
            if gemini_idx < len(gemini_items):
                gemini_item = gemini_items[gemini_idx]
                
                if self._items_match(line_item, gemini_item):
                    line_amount = self._get_amount(line_item)
                    gemini_amount = self._get_amount(gemini_item)
                    
                    if line_amount is None and gemini_amount is not None:
                        rectified_item['amount'] = gemini_amount
                        rectified_item['is_rectified'] = True
                    elif line_amount != gemini_amount and gemini_amount is not None:
                        rectified_item['amount'] = gemini_amount
                        rectified_item['is_rectified'] = True
                    
                    gemini_idx += 1
            
            rectified.append(rectified_item)
        
        return rectified

    def _items_match(self, line_item: Dict, gemini_item: Dict) -> bool:
        """Check if two items match by description and date."""
        # Compare dates
        line_date = str(line_item.get('date', '')).strip()
        gemini_date = str(gemini_item.get('date', '')).strip()
        
        if line_date and gemini_date:
            if not self._dates_match(line_date, gemini_date):
                return False
        
        # Compare descriptions using fuzzy matching
        line_desc = str(line_item.get('description', '')).strip().lower() if not line_item.get('is_check_transaction', False) else f'Check {line_item.get("check_number", "")}'
        gemini_desc = str(gemini_item.get('description', '')).strip().lower()
        
        if line_desc and gemini_desc:
            similarity = SequenceMatcher(None, line_desc, gemini_desc).ratio()
            if similarity < 0.6:
                return False
        
        return True

    def _dates_match(self, date1: str, date2: str) -> bool:
        """Check if two date strings represent the same date."""
        if not date1 or not date2:
            return True  # If either is missing, consider it a match
        
        # Extract numeric parts
        nums1 = re.findall(r'\d+', date1)
        nums2 = re.findall(r'\d+', date2)
        
        # Compare numeric parts
        if sorted(nums1) == sorted(nums2):
            return True
        
        # Direct comparison after stripping
        return date1.replace('/', '').replace('-', '') == date2.replace('/', '').replace('-', '')

    def _get_amount(self, item: Dict) -> Optional[float]:
        """Extract amount from line item."""
        amount = item.get('amount')
        if amount is None:
            return None
        if isinstance(amount, Decimal):
            return float(amount)
        try:
            return float(amount)
        except (ValueError, TypeError):
            return None

    def _create_item_from_gemini(self, gemini_item: Dict, template: Dict) -> Dict:
        """Create a line item from gemini item using template structure."""
        new_item = {
            'id': gemini_item.get('id', 0),
            'page_number': template.get('page_number', 1),
            'date': gemini_item.get('date', ''),
            'description': gemini_item.get('description', ''),
            'amount': gemini_item.get('amount'),
            'type': gemini_item.get('type', '').lower(),
            'is_check_transaction': False,
            'check_number': '',
        }
        return new_item


def get_rectifier_v1() -> DocumentRectifierV1:
    """Factory function to get a DocumentRectifierV1 instance."""
    return DocumentRectifierV1()