from google.cloud import documentai_v1
import json
import mimetypes
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Set, Union
from collections import Counter

from django.conf import settings

from google.genai import types

from google.api_core.client_options import ClientOptions

from extractor.rectifier.utils import (
    TRANSACTIONS_ROWS_JSON_PROMPT,
    TRANSACTIONS_SCHEMA,
    CHECKS_ROWS_JSON_PROMPT,
    CHECKS_SCHEMA,
    _DATE_RE,
    _AMOUNT_TOKEN_RE
)

from extractor.gemini_service import GeminiMixin, JSONHelper

class DocumentAIMixin:

    def __init__(self, **kwargs):

        location = kwargs.get('location', 'us')
        # service_account_json = kwargs.get('service_account_json')

        # Set `api_endpoint` if you use a location other than "us".
        opts = ClientOptions(
            api_endpoint=f"{location}-documentai.googleapis.com"
        )

        # Initialize Document AI client.
        self.doc_ai_client = documentai_v1.DocumentProcessorServiceClient(client_options=opts)

        self.doc_ai_processor = self.init_processor(**kwargs)

    def init_processor(self, **kwargs):

        """
        returns

        `processor.name` is the full resource name of the processor.
        For example: `projects/{project_id}/locations/{location}/processors/{processor_id}`
        print(f"Processor Name: {processor.name}")
        """

        project_id = kwargs.get('project_id')
        location = kwargs.get('location', 'us')
        processor_id = kwargs.get('processor_id')

        # # Get the Fully-qualified Processor path.
        full_processor_name = self.doc_ai_client.processor_path(
            project_id,
            location,
            processor_id
        )

        # # Get a Processor reference.
        processor_request = documentai_v1.GetProcessorRequest(
            name=full_processor_name
        )

        return self.doc_ai_client.get_processor(
            request=processor_request
        )
    
    def prepare_request_document(self, page_bytes, mime_type='application/pdf'):
        raw_document = documentai_v1.RawDocument(
            content=page_bytes,
            mime_type=mime_type,
        )
        return raw_document

    def create_document_request(self, raw_document):
        request = documentai_v1.ProcessRequest(
            name=self.doc_ai_processor.name,
            raw_document=raw_document
        )
        return request
    
    def process_request(self, request)-> documentai_v1.ProcessResponse:
        result = self.doc_ai_client.process_document(
            request=request
        )
        return result


class DocumentAIProcessor(DocumentAIMixin):
    def __init__(self):
        project_id = settings.DOCUMENT_AI_PROJECT_ID
        processor_id = settings.DOCUMENT_AI_PROCESSOR_ID
        location = settings.DOCUMENT_AI_LOCATION
        super().__init__(
            location=location,
            project_id=project_id,
            processor_id=processor_id
        )

    def _x0(self, word: Dict[str, Any]) -> float:
        return min(v["x"] for v in word["bounding_box"])

    def _x1(self, word: Dict[str, Any]) -> float:
        return max(v["x"] for v in word["bounding_box"])

    def _y0(self, word: Dict[str, Any]) -> float:
        return min(v["y"] for v in word["bounding_box"])

    def _y1(self, word: Dict[str, Any]) -> float:
        return max(v["y"] for v in word["bounding_box"])

    def _x_center(self, word: Dict[str, Any]) -> float:
        return (self._x0(word) + self._x1(word)) / 2.0

    def _y_center(self, word: Dict[str, Any]) -> float:
        return (self._y0(word) + self._y1(word)) / 2.0

    def _calculate_bounding_box(self, words: List[Dict[str, Any]]) -> List[float]:
        """
        Calculate the bounding box that encompasses all words.
        Returns [x0, y0, x1, y1] in normalized coordinates.
        """
        if not words:
            return [0.0, 0.0, 0.0, 0.0]
        
        x0 = min(self._x0(w) for w in words)
        y0 = min(self._y0(w) for w in words)
        x1 = max(self._x1(w) for w in words)
        y1 = max(self._y1(w) for w in words)
        
        return [x0, y0, x1, y1]

    def _estimate_y_eps(self, words: List[Dict[str, Any]]) -> float:
        """
        Estimate row height tolerance (normalized y units).
        """
        ys = sorted(set(round(self._y_center(w), 4) for w in words))
        if len(ys) < 3:
            return 0.015
        deltas = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        deltas_sorted = sorted(deltas)
        med = deltas_sorted[len(deltas_sorted) // 2]
        # clamp to sane bounds; statements vary a lot
        return max(0.006, min(0.03, med * 0.9))

    def doc_ai_process_document(self, page_bytes, mime_type)-> documentai_v1.Document:

        raw_document = self.prepare_request_document(
            page_bytes=page_bytes,
            mime_type=mime_type
        )

        doc_request = self.create_document_request(
            raw_document
        )

        result = self.process_request(request=doc_request)

        doc = result.document

        return doc
    
    def process_doc_to_json(self, doc: documentai_v1.Document):
        
        full_text = doc.text or ""
        output: Dict[str, Any] = {"pages": []}

        for page_num, page in enumerate(doc.pages, start=1):
            words_on_page: List[Dict[str, Any]] = []

            for token in page.tokens:
                token_text = self.extract_text_from_anchor(token.layout.text_anchor, full_text).strip()
                if not token_text:
                    continue

                bounding_box = [
                    {"x": v.x / page.dimension.width, "y": v.y / page.dimension.height}
                    for v in token.layout.bounding_poly.vertices
                ]

                words_on_page.append({"text": token_text, "bounding_box": bounding_box})

            # rows = self.build_rows_with_cells_bounding_box(words_on_page)
            rows = self.build_rows_with_cells(words_on_page)

            output['pages'].append({
                "page_number": page_num,
                "rows": rows,
            })

        return output

    def extract_text_from_anchor(self, text_anchor, full_text: str) -> str:
        if not text_anchor.text_segments:
            return ""
        result = []
        for seg in text_anchor.text_segments:
            try:
                start = seg.start_index
                end = seg.end_index
                if start is not None and end is not None:
                    result.append(full_text[start:end])
            except Exception:
                continue
        return "".join(result)

    def build_rows_with_cells_bounding_box(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Returns:
        [
            {
                "row_index": 1,
                "cells": ["...", "...", ...],
                "cells_with_bounding_box": [{"text": "...", "bounding_box": [x0, y0, x1, y1]}, ...],
                "text": "cell1 | cell2 | ...",
                "bounding_box": [x0, y0, x1, y1]
            },
            ...
        ]
        """
        rows = self.cluster_words_into_rows(words)
        out: List[Dict[str, Any]] = []

        for idx, row_words in enumerate(rows, start=1):
            cells_data = self.split_row_into_cells_with_bounding_box(row_words)
            if not cells_data:
                continue
            
            # Extract just the text for backward compatibility
            cells = [cell["text"] for cell in cells_data]
            
            # Calculate row bounding box from all words in the row
            row_bounding_box = self._calculate_bounding_box(row_words) if row_words else [0, 0, 0, 0]
            
            out.append({
                "row_index": idx,
                "cells": cells,
                # "cells_with_bounding_box": cells_data,
                "text": " | ".join(cells),
                "bounding_box": row_bounding_box
            })

        return out
    
    def build_rows_with_cells(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Returns:
        [
            {"row_index": 1, "cells": ["...", "...", ...], "text": "cell1 | cell2 | ..."},
            ...
        ]
        """
        rows = self.cluster_words_into_rows(words)
        out: List[Dict[str, Any]] = []

        for idx, row_words in enumerate(rows, start=1):
            cells = self.split_row_into_cells(row_words)
            if not cells:
                continue
            out.append({
                "row_index": idx,
                "cells": cells,
                "text": " | ".join(cells),
            })

        return out


    def cluster_words_into_rows(self, words: List[Dict[str, Any]], y_eps: Optional[float] = None) -> List[List[Dict[str, Any]]]:
        """
        Group tokens into rows by y-center quantization.
        """
        if not words:
            return []
        if y_eps is None:
            y_eps = self._estimate_y_eps(words)

        buckets: Dict[int, List[Dict[str, Any]]] = {}
        for w in words:
            key = int(round(self._y_center(w) / y_eps))
            buckets.setdefault(key, []).append(w)

        # Return rows top-to-bottom
        rows = [buckets[k] for k in sorted(buckets.keys())]
        return rows

    def split_row_into_cells_with_bounding_box(
        self,
        row_words: List[Dict[str, Any]],
        min_abs_gap: float = 0.02,
        gap_mult: float = 6.0,
    ) -> List[Dict[str, Any]]:
        """
        Split a single row into cells with bounding boxes.

        Returns:
        [
            {"text": "cell1", "bounding_box": [x0, y0, x1, y1]},
            {"text": "cell2", "bounding_box": [x0, y0, x1, y1]},
            ...
        ]
        """
        if not row_words:
            return []

        row_words = sorted(row_words, key=self._x0)

        # compute gaps between consecutive tokens
        gaps = []
        for i in range(len(row_words) - 1):
            right = self._x1(row_words[i])
            left_next = self._x0(row_words[i + 1])
            gaps.append(max(0.0, left_next - right))

        if gaps:
            gaps_sorted = sorted(gaps)
            med = gaps_sorted[len(gaps_sorted) // 2]
        else:
            med = 0.0

        threshold = max(min_abs_gap, med * gap_mult)

        cells: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = [row_words[0]]

        for i in range(len(row_words) - 1):
            if gaps[i] > threshold:
                cells.append(current)
                current = [row_words[i + 1]]
            else:
                current.append(row_words[i + 1])

        if current:
            cells.append(current)

        # Build cell text and bounding_box
        cell_data: List[Dict[str, Any]] = []
        for cell in cells:
            # Keep internal ordering stable
            cell = sorted(cell, key=self._x0)
            text = " | ".join(w["text"] for w in cell if w.get("text"))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                bounding_box = self._calculate_bounding_box(cell)
                cell_data.append({
                    "text": text,
                    "bounding_box": bounding_box
                })

        return cell_data

    def split_row_into_cells(
        self,
        row_words: List[Dict[str, Any]],
        min_abs_gap: float = 0.02,
        gap_mult: float = 6.0,
    ) -> List[str]:
        """
        Split a single row into cells by detecting large horizontal gaps between adjacent tokens.

        Dynamic threshold:
        threshold = max(min_abs_gap, median_gap * gap_mult)
        """
        if not row_words:
            return []

        row_words = sorted(row_words, key=self._x0)

        # compute gaps between consecutive tokens
        gaps = []
        for i in range(len(row_words) - 1):
            right = self._x1(row_words[i])
            left_next = self._x0(row_words[i + 1])
            gaps.append(max(0.0, left_next - right))

        if gaps:
            gaps_sorted = sorted(gaps)
            med = gaps_sorted[len(gaps_sorted) // 2]
        else:
            med = 0.0

        threshold = max(min_abs_gap, med * gap_mult)

        cells: List[List[Dict[str, Any]]] = []
        current: List[Dict[str, Any]] = [row_words[0]]

        for i in range(len(row_words) - 1):
            if gaps[i] > threshold:
                cells.append(current)
                current = [row_words[i + 1]]
            else:
                current.append(row_words[i + 1])

        if current:
            cells.append(current)

        # Build cell text
        cell_texts = []
        for cell in cells:
            # Keep internal ordering stable
            cell = sorted(cell, key=self._x0)
            text = " ".join(w["text"] for w in cell if w.get("text"))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                cell_texts.append(text)

        return cell_texts

    def process(self, page_bytes, mime_type)-> Dict[str, List[Dict[str, Any]]]:

        document = self.doc_ai_process_document(page_bytes=page_bytes, mime_type=mime_type)
        doc_result = self.process_doc_to_json(doc=document)
        return doc_result


class TransactionRectifierV2(GeminiMixin, JSONHelper):
    """Transaction Rectifier using Gemini API - Version 2"""
    
    def __init__(self):
        self.init_gemini()

    @staticmethod
    def _row_text(row: Dict[str, Any]) -> str:
        return (row.get("text") or " | ".join(row.get("cells", []) or [])).strip()

    @staticmethod
    def _has_date(s: str) -> bool:
        return bool(_DATE_RE.search(s))

    @staticmethod
    def _has_amount(s: str) -> bool:
        # Avoid treating tiny integers like "01" as amount: require decimal/comma/$/()/-
        matches = _AMOUNT_TOKEN_RE.findall(s)
        if not matches:
            return False
        return any(
            ('.' in m) or (',' in m) or ('$' in m) or ('(' in m) or (')' in m) or ('-' in m)
            for m in matches
        )

    @staticmethod
    def _merge_bboxes(b1: List[float], b2: List[float]) -> List[float]:
        """Merge two [x0, y0, x1, y1] bounding boxes."""
        if not b1: return b2
        if not b2: return b1
        return [
            min(b1[0], b2[0]),
            min(b1[1], b2[1]),
            max(b1[2], b2[2]),
            max(b1[3], b2[3])
        ]

    def _stitch_split_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge split transactions where date/description and amount end up on different rows.
        CRITICAL: This merges the bounding boxes as well.
        """
        stitched: List[Dict[str, Any]] = []
        i = 0

        while i < len(rows):
            r = rows[i]
            t = self._row_text(r)
            if not t:
                i += 1
                continue

            has_d = self._has_date(t)
            has_a = self._has_amount(t)

            # (B) Amount-only followed by date-only: Row inversion (uncommon but possible)
            if has_a and not has_d and i + 1 < len(rows):
                r2 = rows[i + 1]
                t2 = self._row_text(r2)
                if t2 and self._has_date(t2) and not self._has_amount(t2):
                    merged_cells = (r2.get("cells", []) or []) + (r.get("cells", []) or [])
                    merged_text = (t2 + " " + t).strip()
                    # Merge BBoxes: Date row (r2) + Amount row (r)
                    merged_bbox = self._merge_bboxes(
                        r2.get("bounding_box", []), r.get("bounding_box", [])
                    )
                    
                    stitched.append({
                        "row_index": r2.get("row_index", i + 2),
                        "cells": merged_cells,
                        "text": merged_text,
                        "bounding_box": merged_bbox,
                    })
                    i += 2
                    continue

            # (A) Date-only followed by amount-only: Standard split row
            if has_d and not has_a and i + 1 < len(rows):
                r2 = rows[i + 1]
                t2 = self._row_text(r2)
                if t2 and self._has_amount(t2) and not self._has_date(t2):
                    merged_cells = (r.get("cells", []) or []) + (r2.get("cells", []) or [])
                    merged_text = (t + " " + t2).strip()
                    # Merge BBoxes: Date row (r) + Amount row (r2)
                    merged_bbox = self._merge_bboxes(
                        r.get("bounding_box", []), r2.get("bounding_box", [])
                    )

                    stitched.append({
                        "row_index": r.get("row_index", i + 1),
                        "cells": merged_cells,
                        "text": merged_text,
                        "bounding_box": merged_bbox,
                    })
                    i += 2
                    continue

            stitched.append(r)
            i += 1

        return stitched

    def _validate_transactions(self, txns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate transaction payload - similar to validate_transactions_payload in extract_data_v43.
        Ensures all required fields are present and properly formatted.
        """
        if not isinstance(txns, list):
            return []

        cleaned: List[Dict[str, Any]] = []
        # breakpoint()

        for t in txns:
            if not isinstance(t, dict):
                continue

            page_number = t.get("page_number")
            date = t.get("date")
            desc = t.get("description")
            amt = t.get("amount")
            txn_type = t.get("type")

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
                amount = abs(self._coerce_amount(amt))
            except Exception:
                continue

            cleaned.append({
                "page_number": page_number,
                "date": date.strip(),
                "description": desc.strip(),
                "amount": amount,
                "type": txn_type_norm,
                "check_number": t.get("check_number", "").strip()
            })

        return cleaned

    @staticmethod
    def _normalize_description(desc: str) -> str:
        """Normalize description for comparison: lowercase, remove extra whitespace."""
        if not desc:
            return ""
        return " ".join(desc.lower().split())

    @staticmethod
    def _fuzzy_match_ratio(s1: str, s2: str) -> float:
        """
        Calculate fuzzy match ratio between two strings using SequenceMatcher.
        Returns a value between 0.0 and 1.0.
        """
        from difflib import SequenceMatcher
        if not s1 or not s2:
            return 0.0
        return SequenceMatcher(None, s1, s2).ratio()

    @staticmethod
    def _amounts_match(amt1: float, amt2: float, tolerance: float = 0.01) -> bool:
        """Check if two amounts are equal within tolerance."""
        return abs(amt1 - amt2) <= tolerance

    def extract_transaction_data(self, doc_data, schema, instructions):
        try:
            # Use config WITHOUT system_instruction - include instructions in user content instead
            # This matches the working pattern from extract_data_v43.py

            config = types.GenerateContentConfigDict(
                response_schema = schema,
                system_instruction = instructions,
                max_output_tokens=128000
            )

            result = list()
            # Apply row stitching to merge split rows (Date/Amount) and their bounding boxes
            stitched_doc_data = []
            pages = doc_data.get('pages', [])

            for page in pages:
                page_number = page.get("page_number")

                print("Processing :: ", page_number)
                raw_transactions = []

                page = dict(page)
                stitch = self._stitch_split_rows(page.get("rows", []) or [])
                page["rows"] = stitch


                payload = {"pages": page}
                payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

                content_parts = [
                    self._gemini_service.create_part_from_text(payload_json)
                ]

                content_with_json = self._gemini_service.create_user_content_type(
                    content_parts
                )

                raw = self.gemini_generate(
                    contents=content_with_json,
                    config=config,
                    model="gemini-2.5-flash-lite",
                )

                parsed = self.parse_json(raw)
                
                # Extract transactions list from the response dict
                if isinstance(parsed, dict):
                    raw_transactions = parsed.get("transactions", [])
                elif isinstance(parsed, list):
                    raw_transactions = parsed

                # Validate transactions (similar to validate_transactions_payload in extract_data_v43)
                validated = self._validate_transactions(raw_transactions)

                seen: set[tuple] = set()
                global_id: int = 1

                for t in validated:
                    key = (
                        t["date"].strip(),
                        " ".join(t["description"].split()).lower(),  # normalize whitespace + case
                        round(float(t["amount"]), 2),                # normalize cents
                        t["type"].strip().lower(),
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    result.append({
                        "id": global_id,
                        "page_number": page_number,   # keep it, but NOT part of dedupe
                        "date": t["date"],
                        "description": t["description"],
                        "amount": t["amount"],
                        "type": t["type"],
                        "check_number":  t["check_number"],
                        "bounding_box": t.get('bounding_box', {})
                    })
                    global_id += 1
        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

        return result
    
    def extract_check_data(self, doc_data, schema, instructions):
        print("Starting check data extraction using Gemini V2...")
        result = list()
        global_id: int = 1
        try:
            config = types.GenerateContentConfigDict(
                response_schema = schema,
                system_instruction = instructions,
            )

            result = list()
            pages = doc_data.get('pages', [])
            for page_data in pages:
                page_number = page_data.get("page_number")
                rows = page_data.get("rows", [])

                stitched_page_rows = self._stitch_split_rows(rows)
                
                page_data["rows"] = stitched_page_rows

                payload = {
                    "page":  page_data
                }
                payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

                content_parts = [
                    self._gemini_service.create_part_from_text(
                        payload_json
                    )
                ]
                
                content_with_json = self._gemini_service.create_user_content_type(
                    content_parts
                )

                raw = self.gemini_generate(
                    contents=content_with_json,
                    config=config,
                    model="gemini-2.5-flash-lite",
                )
                parsed = self.parse_json(raw)
                validated = self.chk_img_validate_transactions_payload(parsed)

                #  # Removed
                for t in validated:
                    result.append({
                    "id": global_id,
                    "page_number": page_number,
                    "date": t["date"],
                    "check_number": t["check_number"],
                    "payee": t["payee"],
                    "check_written_date": t["check_written_date"],
                    "amount": t["amount"],
                    "for_memo": t["for_memo"],
                    })
                    global_id += 1
        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

        return result

    def chk_img_validate_transactions_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:

        
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

            if for_memo == payee:
                continue

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
                amount = self._coerce_amount(amt)
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

    @staticmethod    
    def _coerce_amount(v: Any) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace("$", "").replace(",", "")
            if s.startswith("(") and s.endswith(")"):
                s = "-" + s[1:-1]
            return float(s)
        raise ValueError(f"Invalid amount type: {type(v)}")

    @staticmethod
    def remove_pages_with_high_check_counts(
        checks_data: Union[Dict[str, Any], List[Dict[str, Any]]],
        page_txn_data: Union[Dict[str, Any], List[Dict[str, Any]]],
        *,
        threshold: int = 5,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Counts page occurrences in checks_data and removes from page_txn_data any transaction
        whose page number appears >= threshold times in checks_data.

        Accepts either:
        - dict: {"transactions": [...]}
        - list: [...]
        Returns the same container type as page_txn_data (dict or list).
        """
        # Normalize checks list
        if isinstance(checks_data, list):
            checks_txns = checks_data
        elif isinstance(checks_data, dict):
            checks_txns = checks_data.get("transactions", []) or []
        else:
            checks_txns = []

        # Normalize page_txn list
        page_txn_is_list = isinstance(page_txn_data, list)
        if page_txn_is_list:
            page_txns = page_txn_data
        elif isinstance(page_txn_data, dict):
            page_txns = page_txn_data.get("transactions", []) or []
        else:
            page_txns = []

        # Count pages in checks
        page_counter = Counter()
        for txn in checks_txns:
            if not isinstance(txn, dict):
                continue
            page = txn.get('page_number')
            if isinstance(page, int):
                page_counter[page] += 1

        excluded_pages: Set[int] = {p for p, c in page_counter.items() if c >= threshold}
        print(f"Excluding pages with high check counts: {excluded_pages}")

        # Filter page-based txns
        filtered = [
            txn for txn in page_txns
            if not (isinstance(txn, dict) and txn.get('page_number') in excluded_pages)
        ]

        # Return in same shape as input page_txn_data
        if page_txn_is_list:
            return filtered

        if isinstance(page_txn_data, dict):
            out = dict(page_txn_data)
            out["transactions"] = filtered
            return out

        # Fallback
        return {"transactions": filtered}

    def rectify_document(self, master_data, raw_doc_data):
        """
        Process and rectify the document using Gemini API.
        return: {'id': 1, 'date': '08/01/2025', 'type': 'credit', 'amount': 16.2, 'description': '8882442160 CSIPAY SV96 POS Rangeline', 'page_number': 1, 'was_missing': False, 'check_number': '', 'is_rectified': False, 'is_check_transaction': False, "bounding_box": [0.21, 0.34, 0.22, 0.65]}

        """       
        rectified_items = []
        rectifier_items = {}
        
        try:
            transactions_data =  self.extract_transaction_data(
                raw_doc_data,
                TRANSACTIONS_SCHEMA,
                TRANSACTIONS_ROWS_JSON_PROMPT
            )  
            rectifier_items.update({
                "transactions": transactions_data
            })

            checks_data =  self.extract_check_data(
                raw_doc_data,
                CHECKS_SCHEMA,
                CHECKS_ROWS_JSON_PROMPT
            )

            rectifier_items.update({
                "checks": checks_data
            })

            processed_data = self.remove_pages_with_high_check_counts(
                    checks_data=checks_data,
                    page_txn_data=transactions_data,
                    threshold=1,
                )
            rectifier_items.update({
                "processed_data": processed_data
            })
            breakpoint()

            # rectified_items = self.rectify_transactions(
            #     master_data=master_data,
            #     rectifier_items=rectifier_items
            # )

        
        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"Exception type: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")

        return rectified_items, rectifier_items




def get_rectifier() -> TransactionRectifierV2:
    """Factory method to get the TransactionRectifierV2 instance."""
    return TransactionRectifierV2()


def main():

    file_path = "/home/aman/Downloads/20260122_163930_Dec_2025_Bank_Statement.pdf"

    file_bytes = open(file_path, "rb").read()
    doc_ai = DocumentAIProcessor()

    raw_doc_data = doc_ai.process(
        page_bytes=file_bytes,
        mime_type="application/pdf"
    )
    
    # breakpoint()
    # from extractor.rectifier.utils import DATA

    # raw_doc_data = DATA
    
    rectifier = get_rectifier()

    # raw_doc_data = RAW.copy()
    rectifier.rectify_document({}, raw_doc_data)
