from decimal import Decimal
from difflib import SequenceMatcher
from google.cloud import documentai_v1 as documentai
import json
import mimetypes
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Set, Union
from collections import Counter

from google import genai
from google.genai import types

from django.conf import settings

from extractor.rectifier.utils import (
    _remove_thousands_commas_outside_strings,
    _JSON_OBJECT_RE,
    GEMINI_PREFIX,
    GEMINI_CHK_IMG_PREFIX,
    TRANSACTIONS_SCHEMA,
    CHECKS_SCHEMA,
    stitch_split_rows,
    _coerce_amount
)

from extractor.rectifier.doc_ai_helper import DocumentAIProcessor


class GeminiRectifyHelper:
    def __init__(self):
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self.MODEL_NAME = "gemini-2.5-flash-lite"

    @staticmethod
    def _gemini_response_to_text(resp) -> str:
        # google.genai responses typically expose `.text` directly.
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text

        # Fallback: try to reconstruct from candidates/parts if present.
        candidates = getattr(resp, "candidates", None)
        if candidates:
            try:
                parts = candidates[0].content.parts
                chunks = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if t:
                        chunks.append(t)
                out = "".join(chunks)
                return out
            except Exception:
                pass

        return ""

    def parse_gemini_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # PATCH: sanitize thousands separators like 1,612.83 -> 1612.83
        text = _remove_thousands_commas_outside_strings(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = _JSON_OBJECT_RE.search(text)
            if not m:
                # raise ValueError("No JSON object found in Gemini response")
                print("No JSON object found in Gemini response")
            return json.loads(m.group(0))

    def call_gemini(self, contents, prompt: str, schema: str, retries: int = 3, delay: float = 2.0) -> str:
        last_err: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                resp = self.client.models.generate_content(
                    model=self.MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfigDict(
                        system_instruction=prompt,
                        response_schema=schema,
                        response_mime_type="application/json"
                    )
                )
                if not resp.parsed:
                    raise ValueError("Gemini returned no parsed content")
                return resp.parsed
                # text = self._gemini_response_to_text(resp)
                # if not text or not text.strip():
                #     raise ValueError("Gemini returned empty response")
                # return text
            except Exception as e:
                last_err = e
                if attempt < retries:
                    time.sleep(delay * attempt)
        raise RuntimeError(
            f"Gemini call failed after {retries} attempts: {last_err}")


class TransactionRectifierV3(GeminiRectifyHelper):
    def __init__(self):
        super().__init__()
        self.doc_ai_processor = DocumentAIProcessor()

    @staticmethod
    def validate_transactions_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        txns = payload.get("transactions")
        if not isinstance(txns, list):
            return []

        cleaned: List[Dict[str, Any]] = []

        for t in txns:
            if not isinstance(t, dict):
                continue

            page_number = t.get("page_number")
            date = t.get("date")
            desc = t.get("description")
            amt = t.get("amount")
            txn_type = t.get("type")
            check_number = t.get("check_number")

            if not isinstance(page_number, int):
                continue
            if not isinstance(date, str) or not date.strip():
                continue
            if not isinstance(desc, str) or not desc.strip():
                continue
            if amt is None:
                continue

            # Validate type
            if not isinstance(txn_type, str):
                continue
            txn_type_norm = txn_type.strip().lower()
            if txn_type_norm not in {"debit", "credit"}:
                continue

            # Coerce amount to a positive number
            try:
                amount = abs(_coerce_amount(amt))
            except Exception:
                continue

            cleaned.append({
                "page_number": page_number,
                "date": date.strip(),
                "description": desc.strip(),
                "amount": amount,
                "type": txn_type_norm,
                "check_number": check_number
            })

        return cleaned

    @staticmethod
    def chk_img_validate_transactions_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        txns = payload.get("transactions")
        if not isinstance(txns, list):
            return []

        cleaned: List[Dict[str, Any]] = []

        for t in txns:
            if not isinstance(t, dict):
                continue

            date = t.get("date")
            check_number = t.get("check_number")
            payee = t.get("payee")
            check_written_date = t.get("check_written_date")
            amt = t.get("amount")
            for_memo = t.get("for_memo")

            # Require all 3 fields
            if not isinstance(date, str) or not date.strip():
                continue
            if not isinstance(check_number, str) or not check_number.strip():
                continue
            if not isinstance(payee, str) or not payee.strip():
                continue
            if not isinstance(check_written_date, str) or not check_written_date.strip():
                continue
            if amt is None:
                continue

            # Coerce amount; if it fails, skip
            try:
                amount = _coerce_amount(amt)
            except Exception:
                continue

            cleaned.append({
                "date": date.strip(),
                "check_number": check_number.strip(),
                "payee": payee.strip(),
                "check_written_date": check_written_date.strip(),
                "amount": amount,
                "for_memo": for_memo
            })

        return cleaned

    def extract_transactions(self, doc_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Sends ALL pages in a single Gemini request (instead of per-page).
        """
        all_transactions: List[Dict[str, Any]] = []
        global_id = 1

        # Stitch split rows per page before sending
        stitched_pages: List[Dict[str, Any]] = []
        for page in doc_json.get("pages", []) or []:
            page = dict(page)
            page["rows"] = stitch_split_rows(page.get("rows", []) or [])
            stitched_pages.append(page)

        payload = {"pages": stitched_pages}
        payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

        # print(f"\n📤 Sending {len(stitched_pages)} pages to Gemini in one request...")
        parsed = self.call_gemini(
            payload_json,
            GEMINI_PREFIX,
            schema=TRANSACTIONS_SCHEMA
        )
        # print("\n📥 Gemini response:")
        # print(raw)

        # parsed = self.parse_gemini_json(raw)

        validated = self.validate_transactions_payload(parsed)

        seen: set[tuple] = set()

        for t in validated:
            key = (
                t["date"].strip(),
                # normalize whitespace + case
                " ".join(t["description"].split()).lower(),
                round(float(t["amount"]), 2),                # normalize cents
                t["type"].strip().lower(),
            )

            if key in seen:
                continue

            seen.add(key)

            all_transactions.append({
                "id": global_id,
                # keep it, but NOT part of dedupe
                "page_number": t["page_number"],
                "date": t["date"],
                "description": t["description"],
                "amount": t["amount"],
                "type": t["type"],
                "check_number": t["check_number"]
            })
            global_id += 1

        return all_transactions

    def extract_check_transactions(self, doc_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        all_transactions: List[Dict[str, Any]] = []
        global_id = 1

        for page in doc_json.get("pages", []):
            page = dict(page)
            page["rows"] = stitch_split_rows(page.get("rows", []) or [])

            page_payload = {"page": page}
            page_json = json.dumps(
                page_payload,
                ensure_ascii=False,
                indent=2
            )

            # prompt = GEMINI_CHK_IMG_PREFIX + "\n\nPAGE_CONTENT:\n" + page_json

            print(f"\n📤 Sending page {page.get('page_number')} to Gemini...")

            parsed = self.call_gemini(
                page_json,
                prompt=GEMINI_CHK_IMG_PREFIX,
                schema=CHECKS_SCHEMA
            )

            # parsed = self.parse_gemini_json(raw)

            validated = self.chk_img_validate_transactions_payload(parsed)

            for t in validated:
                all_transactions.append({
                    "id": global_id,
                    "page_number": page.get("page_number"),
                    "date": t["date"],
                    "check_number": t["check_number"],
                    "payee": t["payee"],
                    "check_written_date": t["check_written_date"],
                    "amount": t["amount"],
                    "for_memo": t["for_memo"]
                })
                global_id += 1
            time.sleep(5)

        return all_transactions

    def remove_pages_with_high_check_counts(
        self,
        checks_json: Union[Dict[str, Any], List[Dict[str, Any]]],
        page_txn_json: Union[Dict[str, Any], List[Dict[str, Any]]],
        *,
        threshold: int = 5,
    ) -> Dict[str, Any]:
        """
        Counts page occurrences in checks_json and removes from page_txn_json any transaction
        whose page number appears >= threshold times in checks_json.

        Accepts either:
        - dict: {"transactions": [...]}
        - list: [...]
        Always returns dict: {"transactions": [...]}
        """

        # Normalize checks list
        if isinstance(checks_json, list):
            checks_txns = checks_json
        elif isinstance(checks_json, dict):
            checks_txns = checks_json.get("transactions", []) or []
        else:
            checks_txns = []

        # Normalize page_txn list
        if isinstance(page_txn_json, list):
            page_txns = page_txn_json
        elif isinstance(page_txn_json, dict):
            page_txns = page_txn_json.get("transactions", []) or []
        else:
            page_txns = []

        # Count pages in checks
        page_counter = Counter()
        for txn in checks_txns:
            if not isinstance(txn, dict):
                continue
            page = txn.get("page_number")
            if isinstance(page, int):
                page_counter[page] += 1

        excluded_pages: Set[int] = {
            p for p, c in page_counter.items() if c >= threshold}

        # Filter page-based txns
        filtered = [
            txn for txn in page_txns
            if not (isinstance(txn, dict) and txn.get("page_number") in excluded_pages)
        ]

        return {"transactions": filtered}

    def rectify_document(self, line_items, page_bytes, mime_type="application/pdf") -> List[Dict[str, Any]]:

        result_json = self.doc_ai_processor.process_document_ai(
            page_bytes=page_bytes,
            mime_type=mime_type
        )

        transactions = self.extract_transactions(result_json)

        chk_img_transactions = self.extract_check_transactions(result_json)

        filtered_page_txns = self.remove_pages_with_high_check_counts(
            checks_json=chk_img_transactions,
            page_txn_json=transactions,
            threshold=1,
        )

        gemini_items = filtered_page_txns.get("transactions", [])

        if not gemini_items:
            print("No transactions extracted by Gemini, returning original data")
            return line_items, gemini_items

        print(f"Gemini extracted {len(gemini_items)} transactions")

        rectified_items = self._compare_and_rectify(line_items, gemini_items)

        return rectified_items, gemini_items

        return

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
                    print(
                        f"Added missing amount at index {idx}: {gemini_amount}")
                elif line_amount != gemini_amount and gemini_amount is not None:
                    # Amounts differ - use gemini's amount
                    rectified_item['amount'] = gemini_amount
                    rectified_item['is_rectified'] = True
                    print(
                        f"Updated amount at index {idx}: {line_amount} -> {gemini_amount}")
            else:
                # Items don't match at this index - keep original
                print(f"Items don't match at index {idx}")

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

                    if match_found:
                        # Gemini has an extra item - insert it as missing
                        # Skip check transactions - don't add them as missing
                        if gemini_item.get('is_check_transaction', False):
                            print(
                                f"Skipping extra check transaction from gemini at position {gemini_idx}")
                            gemini_idx += 1
                            continue

                        new_item = self._create_item_from_gemini(
                            gemini_item, line_items[0] if line_items else {})
                        new_item['is_rectified'] = True
                        new_item['was_missing'] = True
                        rectified.append(new_item)
                        print(
                            f"Inserted missing item from gemini at position {len(rectified)}")
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
                    logger.info(
                        f"Skipping trailing check transaction from gemini at position {gemini_idx}")
                    gemini_idx += 1
                    continue

                new_item = self._create_item_from_gemini(
                    gemini_item, line_items[0] if line_items else {})
                new_item['is_rectified'] = True
                new_item['was_missing'] = True
                rectified.append(new_item)
                logger.info(
                    f"Added trailing item from gemini at position {len(rectified)}")
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
        line_desc = str(line_item.get('description', '')).strip().lower() if not line_item.get(
            'is_check_transaction', False) else f'Check {line_item.get("check_number", "")}'
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


def get_rectifier_v3() -> TransactionRectifierV3:
    """Factory function to get a TransactionRectifierV3 instance."""
    return TransactionRectifierV3()


def main():

    file_path = "/home/aman/Downloads/20260122_163930_Dec_2025_Bank_Statement.pdf"

    file_bytes = open(file_path, "rb").read()

    # from extractor.rectifier.utils import DATA

    # raw_doc_data = DATA

    rectifier = TransactionRectifierV3()

    # raw_doc_data = RAW.copy()
    rectifier.rectify_document({}, file_bytes, mime_type="application/pdf")
