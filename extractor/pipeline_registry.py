"""
Pipeline routing: resolves a pipeline class for a given document type.

To switch provider for a document type, change one line in ``PIPELINE_MAP``.
"""

import importlib
from typing import Type

from extractor.constants import DocumentType


class UnsupportedDocTypeError(Exception):
    """Raised when no pipeline is mapped for a document type."""
    pass


PIPELINES: dict[str, str] = {
    "DATALABS_EXTRACTOR": "extractor.pipelines.datalabs.pipeline.ExtractorPipeline",
    "LANDING_AI_KV": "extractor.pipelines.kv.landing_pipeline.DocumentProcessor",
}


PIPELINE_MAP = {
    # transaction extraction — emits line items
    DocumentType.BANK_STATEMENT.value: PIPELINES["DATALABS_EXTRACTOR"],
    DocumentType.CREDIT_CARD.value: PIPELINES["DATALABS_EXTRACTOR"],

    # attribute extraction — emits values for configured fields
    DocumentType.SALES.value: PIPELINES["LANDING_AI_KV"],
    DocumentType.PAYROLL.value: PIPELINES["LANDING_AI_KV"],
    DocumentType.MISC.value: PIPELINES["LANDING_AI_KV"],
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
