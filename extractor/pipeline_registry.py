"""
Pipeline routing: resolves a pipeline class for a given document type.

Replaces the previous ProcessorRegistry + _register_default_processors dance.
To switch provider (e.g., LandingAI vs Claude for bank statements), change one
line in PIPELINE_MAP below.
"""

import importlib
from typing import Type

from extractor.constants import DocumentType


class UnsupportedDocTypeError(Exception):
    """Raised when no pipeline is mapped for a document type."""
    pass

PIPELINES: dict[str, str] = {
    "GEMINI_EXTRACTOR": "extractor.pipelines.gemini.pipeline.ExtractorPipeline",
    "LANDING_AI_EXTRACTOR": "extractor.pipelines.landing_ai.pipeline.ExtractorPipeline",
    "CLAUDE_EXTRACTOR": "extractor.pipelines.claude.pipeline.ExtractorPipeline",
    "LANDING_AI_KV": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
    "DATALABS_EXTRACTOR": "extractor.pipelines.datalabs.pipeline.ExtractorPipeline",
}


PIPELINE_MAP = {
    # transaction extraction
    DocumentType.BANK_STATEMENT.value: PIPELINES.get("DATALABS_EXTRACTOR"),
    DocumentType.CREDIT_CARD.value: PIPELINES.get("DATALABS_EXTRACTOR"),

    # DocumentType.BANK_STATEMENT.value: PIPELINES.get("LANDING_AI_EXTRACTOR"),
    # DocumentType.CREDIT_CARD.value: PIPELINES.get("LANDING_AI_EXTRACTOR"),
    # attribute extraction 
    DocumentType.SALES.value: PIPELINES.get("LANDING_AI_KV"),
    DocumentType.PAYROLL.value: PIPELINES.get("LANDING_AI_KV"),
    DocumentType.MISC.value: PIPELINES.get("LANDING_AI_KV"),
}


def get_pipeline_class(doc_type: str) -> Type:
    """
    Resolve the pipeline class for a document type.

    Imports lazily via dotted path to avoid circular imports between
    pipelines and shared base classes.
    """
    dotted_path = PIPELINE_MAP.get(doc_type)

    if not dotted_path:
        raise UnsupportedDocTypeError(
            f"No pipeline registered for doc_type '{doc_type}'. "
            f"Available: {list(PIPELINE_MAP.keys())}"
        )
    module_path, _, class_name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)
