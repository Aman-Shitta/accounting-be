"""
Datalabs SDK wrapper.

Sends a PDF through a **single** Datalabs pipeline that performs two steps
in one execution:

* **Step 0 — Marker parse** — converts the full PDF into a hierarchical
  JSON block-tree with tables, text, and images.
* **Step 1 — Segmentation** — classifies pages by type
  (``check_item``, ``deposit_slip``, or unclassified statement pages).

Running both steps in one pipeline avoids duplicate PDF ingestion and
reduces API cost.

Downstream code uses the segmentation result as a *routing table* to decide
which pages need check-image OCR, while Marker output feeds the LLM-based
transaction and summary extractors.
"""

from __future__ import annotations

import ast
import json
import logging
from typing import Any

from datalab_sdk import DatalabClient
from datalab_sdk.models import PipelineExecution
from django.conf import settings

logger = logging.getLogger(__name__)


class DatalabsParser:
    """Runs Datalabs pipelines and extracts structured data from the JSON tree."""

    # Combined pipeline ID — runs Marker (step 0) + Segmentation (step 1).
    PIPELINE_ID = settings.DATALABS_PIPELINE_ID
    DEFAULT_MAX_POLLS = 300
    DEFAULT_OUTPUT_FORMAT = "markdown,json"

    def __init__(
        self,
        pipeline_id: str = PIPELINE_ID,
        max_polls: int = DEFAULT_MAX_POLLS,
        output_format: str = DEFAULT_OUTPUT_FORMAT,
    ):
        self.client = DatalabClient()
        self.pipeline_id = pipeline_id
        self.max_polls = max_polls
        self.output_format = output_format

    def run_pipeline(self, file_path: str) -> PipelineExecution:
        """Submit a PDF and poll until the pipeline finishes. Returns the execution."""
        pipeline = self.client.run_pipeline(
            pipeline_id=self.pipeline_id,
            file_path=file_path,
            output_format=self.output_format,
        )
        execution = self.client.get_pipeline_execution(
            pipeline.execution_id, max_polls=self.max_polls
        )

        return execution
    # ------------------------------------------------------------------
    # Marker pipeline
    # ------------------------------------------------------------------

    def parse(self, execution: PipelineExecution) -> dict[str, Any]:
        """Extract the Marker JSON tree from step 0 of the pipeline execution."""

        results = self.client.get_step_result(execution.execution_id, step_index=0)
        # results = dict_keys(['success', 'error_in', 'error', 'inferenced_pages', 'total_pages', 'output_format', 'markdown', 'html', 'images', 'chunks', 'json', 'metadata', 'links', 'filepath', 'page_range', 'post_inference_params', 'runtime', 'status', 'page_count'])

        # results['markdown'][:100]
        # '\n\nE/\n\n![Central Bank logo](30a26f2d17ca95672702bf50fb4f0242_img.jpg)\n\nCentral Bank logo\n\n# Central B'


        raw = results["json"] if isinstance(results, dict) else results.json
        return self._coerce_to_dict(raw)

    def parse_markdown(self, execution: PipelineExecution) -> str:
        """Return the full-document Markdown from step 0 of the pipeline."""
        results = self.client.get_step_result(execution.execution_id, step_index=0)
        md = results["markdown"] if isinstance(results, dict) else getattr(results, "markdown", "")
        return md or ""

    # ------------------------------------------------------------------
    # Segmentation pipeline
    # ------------------------------------------------------------------

    def segment(self, execution: PipelineExecution) -> dict[str, Any]:
        """
        Extract the segmentation result from step 1 of the pipeline execution.

        Returns a dict with ``segments`` (list of segment entries) and
        ``metadata``.  Each segment entry has ``name``, ``pages``
        (0-indexed), and ``confidence``.

        Example return value::

            {
                "segments": [
                    {"name": "other", "pages": [0, 1, 2, 3, 4], "confidence": "high"},
                    {"name": "check_item", "pages": [5, 6, 7, 8], "confidence": "high"},
                ],
                "metadata": {
                    "total_pages": 9,
                    "segmentation_method": "user_guided",
                    "strategy": "GuidedSegmentationStrategy",
                },
            }
        """
        results = self.client.get_step_result(execution.execution_id, step_index=1)
        # Step 1 returns the full result dict; segmentation data lives
        # under the 'segmentation_results' key.
        if isinstance(results, dict):
            seg = results.get("segmentation_results", results)
        else:
            seg = getattr(results, "segmentation_results", results)
        return self._coerce_to_dict(seg) if isinstance(seg, str) else seg

    # ------------------------------------------------------------------
    # Static extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_tables(
        parse_json: dict[str, Any],
        pages: set[int] | None = None,
    ) -> dict[int, list[dict[str, Any]]]:
        """
        Flatten the Marker block tree into ``{page_number: [table_dict, ...]}``.

        Each table_dict has ``table`` (HTML), ``bbox``, ``polygon``, and
        ``section_header`` — the text of the nearest preceding
        ``SectionHeader`` block on the page (e.g. "Deposits",
        "Withdrawals", "Checks Paid"). This header context helps the LLM
        correctly classify transactions as credits vs debits when the
        table itself lacks an explicit direction column.

        Args:
            parse_json: The full Marker JSON output.
            pages: Optional set of 1-indexed page numbers to include.
                   If *None*, all pages are included.
        """
        by_page: dict[int, list[dict[str, Any]]] = {}
        for page_idx, child in enumerate(parse_json.get("children", []) or [], start=1):
            if child.get("block_type") != "Page":
                continue
            if pages is not None and page_idx not in pages:
                continue
            page_tables: list[dict[str, Any]] = []
            recent_headers: list[str] = []
            current_header_idx = -1
            for block_idx, page_child in enumerate(child.get("children", []) or []):
                block_type = page_child.get("block_type")
                if block_type == "SectionHeader":
                    header_text = (
                        page_child.get("text")
                        or page_child.get("html")
                        or ""
                    ).strip()
                    current_header_idx = block_idx
                    if header_text:
                        recent_headers.append(header_text)
                        recent_headers = recent_headers[-3:]
                elif block_type == "Table":
                    if block_idx - current_header_idx <= 3 and recent_headers:
                        section_header = "|".join(recent_headers)
                    else:
                        section_header = ""

                    page_tables.append(
                        {
                            # last up-to-3 SectionHeaders above the table, pipe-separated
                            "section_header": section_header,
                            "table": page_child.get("html"),
                            "bbox": page_child.get("bbox"),
                            "polygon": page_child.get("polygon"),
                        }
                    )
            by_page[page_idx] = page_tables
        return by_page

    @staticmethod
    def extract_pages_html(
        parse_json: dict[str, Any],
        pages: set[int] | None = None,
    ) -> dict[int, str]:
        """
        Return ``{1-indexed page_number: page_html}`` for the requested pages.

        Uses the Page block's own ``html`` field from the Marker tree.

        Args:
            parse_json: The full Marker JSON output.
            pages: Optional set of 1-indexed page numbers to include.
                   If *None*, all pages are included.
        """
        by_page: dict[int, str] = {}
        for idx, child in enumerate(parse_json.get("children", []) or [], start=1):
            if child.get("block_type") != "Page":
                continue
            if pages is not None and idx not in pages:
                continue
            by_page[idx] = child.get("html", "") or ""
        return by_page

    @staticmethod
    def extract_text_content(
        parse_json: dict[str, Any],
        pages: set[int] | None = None,
    ) -> str:
        """
        Collect readable text from Text / SectionHeader / ListItem blocks.

        Walks the Marker block tree and concatenates text content
        (excluding tables and images) into a single markdown-ish string
        suitable for the summary-extraction LLM call.

        Args:
            parse_json: The full Marker JSON output.
            pages: Optional set of 1-indexed page numbers to include.
        """
        _TEXT_BLOCK_TYPES = {"Text", "SectionHeader", "ListGroup", "ListItem", "Line"}
        lines: list[str] = []

        for idx, child in enumerate(parse_json.get("children", []) or [], start=1):
            if child.get("block_type") != "Page":
                continue
            if pages is not None and idx not in pages:
                continue

            lines.append(f"\n--- Page {idx} ---\n")
            DatalabsParser._collect_text(child, _TEXT_BLOCK_TYPES, lines)

        return "\n".join(lines)

    @staticmethod
    def _collect_text(
        node: dict[str, Any],
        allowed_types: set,
        out: list[str],
    ) -> None:
        """Recursively collect text from allowed block types."""
        block_type = node.get("block_type", "")
        if block_type in allowed_types:
            # Prefer the 'html' field stripped of tags, else 'text'
            text = node.get("text") or node.get("html") or ""
            text = text.strip()
            if text:
                out.append(text)
        for child in node.get("children", []) or []:
            DatalabsParser._collect_text(child, allowed_types, out)

    # ------------------------------------------------------------------
    # Segmentation routing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_page_route(segmentation_result: dict[str, Any]) -> dict[str, list[int]]:
        """
        Convert segmentation output to ``{segment_name: [page_numbers_0indexed]}``.

        Example return::

            {
                "check_item": [10, 11, 12, 13, 14],
                "deposit_slip": [7, 8, 9],
            }
        """
        route: dict[str, list[int]] = {}
        for segment in segmentation_result.get("segments", []):
            name = segment.get("name", "unknown")
            page_list = segment.get("pages", [])
            route.setdefault(name, []).extend(page_list)
        return route

    @staticmethod
    def resolve_check_pages(segmentation_result: dict[str, Any]) -> list[int]:
        """
        Build the final list of 0-indexed pages for check-image OCR.

        Includes ``deposit_slip`` pages that are immediately *before* a
        ``check_item`` page, because mixed pages (deposit slips at top,
        checks below) get classified as ``deposit_slip`` by the
        segmentation model.
        """
        route = DatalabsParser.build_page_route(segmentation_result)
        check_pages: set[int] = set(route.get("check_item", []))
        deposit_pages: set[int] = set(route.get("deposit_slip", []))

        # Adjacency heuristic — include deposit page N-1 when page N is check
        resolved = set(check_pages)
        for cp in check_pages:
            prev = cp - 1
            if prev in deposit_pages:
                resolved.add(prev)

        return sorted(resolved)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_to_dict(raw: Any) -> dict[str, Any]:
        """Datalabs sometimes returns JSON as a str (or a Python-repr str)."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return ast.literal_eval(raw)
        raise ValueError(f"Unexpected Datalabs json type: {type(raw)}")
