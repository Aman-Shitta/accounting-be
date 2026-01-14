"""
Document Rectifier for Banking Extractor

This module provides AI-powered rectification of extracted banking data using 
Google Gemini to verify and provide probable corrections for transaction data 
and check data extracted from bank statements.
"""
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal, InvalidOperation


from google.genai import types

from extractor.gemini_service import GeminiMixin, JSONHelper
from extractor.gemini_service import get_gemini_service
            

logger = logging.getLogger(__name__)


class DocumentRectifier(GeminiMixin):
    """
    Rectifier that uses Gemini AI to verify and correct extracted banking data.
    
    The rectifier takes extracted transaction and check data along with the 
    original page image/bytes and uses Gemini's visual capabilities to:
    1. Verify extracted values against the visual document
    2. Provide probable corrections for amount with confidence scores
    3. Return a rectified data structure with corrections and confidence levels
    """

    def __init__(self):
        self.init_gemini()
   
    def rectify_document(
        self,
        page_bytes: bytes,
        extracted_data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Rectify extracted document data using Gemini AI.
        
        Verifies transaction amounts against the visual document and provides
        rectified amounts with confidence scores when discrepancies are detected.

        Args:
            page_bytes (bytes): The original page image/bytes.
            extracted_data (Dict[str, Any]): Extracted transaction and check data.
            config (Dict[str, Any]): Configuration parameters for rectification.

        Returns:
            Dict[str, Any]: Rectified data with corrections and confidence scores.
                Each transaction will have 'rectified_amount' and 'rectified_confidence' 
                fields added if a correction is suggested.
        """
        try:
            # Get line items from extracted data
            transactions = extracted_data.get('transactions', {})
            line_items = transactions.get('line_items', [])
            
            if not line_items:
                logger.info("No line items to rectify")
                return extracted_data
            
            # # Limit processing to avoid token limits (process in batches if needed)
            # max_items_per_call = 30
            # if len(line_items) > max_items_per_call:
            #     logger.warning(f"Processing only first {max_items_per_call} items of {len(line_items)}")
            #     items_to_rectify = line_items[:max_items_per_call]
            # else:
            items_to_rectify = line_items

            # Build prompt for Gemini
            prompt = self._build_rectification_prompt(items_to_rectify)
            logger.debug(f"Rectification prompt length: {len(prompt)} chars")
            
            # Call Gemini API
            logger.info(f"Rectifying {len(items_to_rectify)} line items using Gemini AI")
            
            # Create parts using service helper
            page_part = self._gemini_service.create_pdf_part(page_bytes)
            prompt_part = self._gemini_service.cretate_part_from_text(text=prompt)

            content = [
                prompt_part,
                page_part
            ]
            
            rectification_schema = self._get_rectification_schema()

            # Generate content with structured JSON response
            config = self._gemini_service.get_default_config(
                temperature=0.1,  # Low temperature for consistency
                response_mime_type="application/json",
                response_schema=rectification_schema
            )

            response_text = self._gemini_service.generate_content(
                contents=content,
                config=config
            )
            
            # Parse response
            rectified_data = JSONHelper.parse_json(response_text)

            logger.info(f"Rectification data received from Gemini :: {rectified_data}")
            
            if not rectified_data or 'rectifications' not in rectified_data:
                logger.warning("No valid rectification data returned from Gemini")
                return extracted_data
            
            # Apply rectifications to line items
            rectifications = rectified_data.get('rectifications', [])
            rectified_items, rectified_count = self._apply_rectifications(line_items, rectifications)
            
            # Update extracted data with rectified items
            extracted_data['transactions']['line_items'] = rectified_items
            
            # Add metadata
            extracted_data['rectification_metadata'] = {
                'total_items': len(line_items),
                'rectified_items': rectified_count,
                'rectification_timestamp': datetime.now().isoformat()
            }
            
            logger.info(
                f"Rectification complete: {rectified_count} "
                f"items corrected out of {len(items_to_rectify)}"
            )
            
            return extracted_data
            
        except Exception as e:
            import os, sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)

            logger.error(f"Error during rectification: {str(e)}", exc_info=True)
            # Return original data if rectification fails
            return extracted_data
    
    def _build_rectification_prompt(self, line_items: List[Dict[str, Any]]) -> str:
        """
        Build the prompt for Gemini to rectify transaction amounts.
        
        Args:
            line_items: List of extracted transaction line items
            
        Returns:
            Formatted prompt string
        """
        prompt = """
        You are a banking document verification expert. Your task is to verify transaction amounts 
        extracted from a bank statement by comparing them against what you actually see in the visual document image.

        **CRITICAL INSTRUCTIONS:**
        1. Look at the bank statement image and find each transaction row
        2. Compare the VISUAL amount in the image with the EXTRACTED amount provided below
        3. ONLY set needs_correction to TRUE if the extracted amount is DIFFERENT from what you see in the image
        4. If the extracted amount MATCHES the visual amount exactly, set needs_correction to FALSE
        5. Do NOT suggest corrections for amounts that are already correct

        **When to Flag for Correction:**
        - The extracted amount has wrong digits (e.g., extracted "2,168.55" but image shows "2,168.50")
        - Decimal point is in wrong position (e.g., extracted "216.855" but image shows "2,168.55")
        - Commas are wrong or missing causing number change
        - Amount is in wrong column (debit vs credit swapped)
        - Extracted amount is null/missing but image clearly shows an amount

        **When NOT to Flag:**
        - Extracted amount matches image exactly (even if formatting differs slightly)
        - You cannot clearly read the amount in the image (uncertainty means no correction)
        - The difference is just comma formatting without changing the actual number value

        **Confidence Scoring:**
        - Only suggest corrections if confidence > 0.7
        - Give reasoning that specifically describes what you SEE in the image vs what was extracted

        **Extracted Transactions to Verify:**
        """
        
        for idx, item in enumerate(line_items, 1):
            debit = item.get('debit_amount') or 'None'
            credit = item.get('credit_amount') or 'None'
            date = item.get('date', 'N/A')
            desc = item.get('description', 'N/A')[:60]  # Truncate long descriptions
            
            prompt += f"\n{idx}. Date: {date}, Description: {desc}\n"
            prompt += f"   Extracted Values - Debit: {debit}, Credit: {credit}\n"
            prompt += f"   → Look at row {idx} in the image and verify if these amounts are correct\n"
        
        prompt += """
            **Your Response Format:**
            Return a JSON with rectifications array. For EACH transaction, provide:
            - needs_correction: TRUE only if extracted amount differs from what you see in image, FALSE if it matches
            - rectified_debit_amount: The ACTUAL amount you see in the image for debit column (or empty string if none)
            - rectified_credit_amount: The ACTUAL amount you see in the image for credit column (or empty string if none)
            - confidence: 0.0-1.0 (only values > 0.7 will be used, set to 1.0 if extracted matches image)
            - reasoning: Describe what you SEE vs what was extracted. Examples:
                * "Extracted amount matches image exactly - no correction needed"
                * "Image shows 2,168.50 but extracted as 2,168.55 - last digit incorrect"
                * "Image shows amount in credit column, but extracted as debit - column error"
                * "Image clearly shows 3,564.74 but extracted as 3,564.14 - middle digit wrong"

            **Example Response:**
            {
            "rectifications": [
                {
                "needs_correction": false,
                "rectified_debit_amount": "",
                "rectified_credit_amount": "2,168.55",
                "confidence": 1.0,
                "reasoning": "Extracted amount 2,168.55 matches image exactly - no correction needed"
                },
                {
                "needs_correction": true,
                "rectified_debit_amount": "",
                "rectified_credit_amount": "3,564.74",
                "confidence": 0.95,
                "reasoning": "Image shows 3,564.74 but extracted as 3,564.14 - the '7' was misread as '1'"
                }
            ]
            }

            Remember: Set needs_correction to TRUE only when there is an ACTUAL DISCREPANCY between image and extraction!
            """
        return prompt
    
    def _get_rectification_schema(self) -> Dict[str, Any]:
        """
        Get the JSON schema for rectification response.
        
        Returns:
            JSON schema dictionary for Gemini structured output
        """
        return {
            "type": "object",
            "properties": {
                "rectifications": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "rectified_debit_amount": {
                                "type": "string",
                                "description": "The actual debit amount visible in the image (with commas). Empty string if no debit amount or if credit transaction."
                            },
                            "rectified_credit_amount": {
                                "type": "string",
                                "description": "The actual credit amount visible in the image (with commas). Empty string if no credit amount or if debit transaction."
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence score 0.0-1.0. Use 1.0 if extracted matches image. Only corrections with >0.7 confidence will be applied."
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Specific explanation: describe what you SEE in the image vs what was extracted. Be explicit about discrepancies or matches."
                            }
                        },
                        "required": ["rectified_debit_amount", "rectified_credit_amount", "confidence", "reasoning"]}
                }
            },
            "required": ["rectifications"]
        }
    
    def _apply_rectifications(
        self, 
        line_items: List[Dict[str, Any]], 
        rectifications: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Apply rectification corrections to line items.
        
        When AI detects a correction is needed with sufficient confidence,
        the debit_amount and credit_amount values are directly overwritten
        with the corrected values. Rectification metadata is added for tracking.
        
        Args:
            line_items: Original line items
            rectifications: Rectification suggestions from Gemini
            
        Returns:
            Line items with rectified values and rectification metadata
        """
        rectified_items = []
        rectified_count = 0
        
        # Helper function to clean null/empty values
        def _parse_amount(value):
            """Parse amount string to Decimal, handling common formats"""
            if value in (None, ""):
                return None
            try:
                # Remove commas and whitespace
                value = re.sub(r'[^\d\.]', '', str(value))
                return Decimal(value)
            except Exception as e:
                logger.warning(f"Failed to parse amount '{value}': {str(e)}")
            
            return value
            
        for item in line_items:
            # Create a copy to avoid mutating original
            rectified_item = item.copy()
            
            # Initialize rectification fields
            rectified_item['is_rectified'] = False
            rectified_item['rectified_confidence'] = None
            rectified_item['rectification_reasoning'] = None
            
            rectified_items.append(rectified_item)
        
        # Apply rectifications by index (enumerate to match line items by position)
        for idx, rect in enumerate(rectifications):
            
            if idx >= len(rectified_items):
                logger.warning(f"Rectification index {idx} exceeds line items count {len(rectified_items)}")
                break
            
            confidence = rect.get('confidence', 0.0)

            original_debit = _parse_amount(rectified_items[idx].get('debit_amount'))
            original_credit = _parse_amount(rectified_items[idx].get('credit_amount'))
            
            rectified_debit = _parse_amount(rect.get('rectified_debit_amount'))
            rectified_credit = _parse_amount(rect.get('rectified_credit_amount'))

            needs_correction = False

            if original_debit:
                # Check if there's an actual change in values
                has_debit_change = str(original_debit or '').strip() != str(rectified_debit or '').strip()
                if has_debit_change:
                    needs_correction = True

            if original_credit:
                has_credit_change = str(original_credit or '').strip() != str(rectified_credit or '').strip()
                if has_credit_change:
                    needs_correction = True
            
            if not original_debit and not original_credit:
                # Both original amounts are missing, check if rectified provides a value
                if rectified_debit or rectified_credit:
                    has_debit_change = bool(rectified_debit)
                    has_credit_change = bool(rectified_credit)
                    needs_correction = True

        
            # Only apply corrections with sufficient confidence AND needs_correction flag
            if needs_correction and confidence >= 0.7:
                
                if has_debit_change or has_credit_change:
                    # Directly overwrite the debit_amount and credit_amount with rectified values
                    rectified_items[idx]['debit_amount'] = rectified_debit
                    rectified_items[idx]['credit_amount'] = rectified_credit
                    
                    # Set rectification metadata
                    rectified_items[idx]['is_rectified'] = True
                    rectified_items[idx]['rectified_confidence'] = confidence
                    rectified_items[idx]['rectification_reasoning'] = rect.get('reasoning')
                    
                    logger.info(
                        f"Item {idx+1}: Applied rectification - "
                        f"Original Debit: {original_debit} -> {rectified_debit}, "
                        f"Original Credit: {original_credit} -> {rectified_credit}, "
                        f"Confidence: {confidence}"
                    )
                    rectified_count += 1
                else:
                    logger.debug(f"Item {idx+1}: needs_correction=True but values unchanged, skipping")
            else:
                # Log when no correction is needed
                if not needs_correction:
                    logger.debug(f"Item {idx+1}: No correction needed - {rect.get('reasoning', 'Amount matches')}")
                elif confidence < 0.7:
                    logger.debug(f"Item {idx+1}: Low confidence ({confidence}) - skipping correction")
        
        return rectified_items, rectified_count
