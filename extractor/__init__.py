"""
Extractor Package

Provides document processing and data extraction capabilities.
"""

from extractor.base import (
    AbstractDocumentProcessor,
    BaseDocumentProcessor,
    GeminiDocumentProcessor,
)
from extractor.constants import DocumentType
from extractor.pipeline_registry import get_pipeline_class, UnsupportedDocTypeError

__all__ = [
    "AbstractDocumentProcessor",
    "BaseDocumentProcessor",
    "GeminiDocumentProcessor",
    "DocumentType",
    "get_pipeline_class",
    "UnsupportedDocTypeError",
]
