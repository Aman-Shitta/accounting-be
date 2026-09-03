"""
Extractor Package

Provides document processing and data extraction capabilities.
"""

from extractor.base import AbstractDocumentProcessor, BaseDocumentProcessor
from extractor.constants import DocumentType
from extractor.pipeline_registry import UnsupportedDocTypeError, get_pipeline_class

__all__ = [
    "AbstractDocumentProcessor",
    "BaseDocumentProcessor",
    "DocumentType",
    "get_pipeline_class",
    "UnsupportedDocTypeError",
]
