from __future__ import annotations


import mimetypes
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Set, Union
from google.cloud import documentai_v1
from google.api_core.client_options import ClientOptions
from django.conf import settings


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

    def process_document_ai(self, page_bytes, mime_type)-> documentai_v1.Document:

        raw_document = self.prepare_request_document(
            page_bytes=page_bytes,
            mime_type=mime_type
        )

        doc_request = self.create_document_request(
            raw_document
        )

        result = self.process_request(request=doc_request)

        doc = result.document

        result = self.process_doc_to_json(doc)

        return result
# Default auto field