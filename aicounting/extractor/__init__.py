"""
Extractor Package

Provides document processing and data extraction capabilities.
"""

# Configuration
from extractor.config_factory import (
    DocumentConfig,
    DocumentConfigFactory,
    DocumentType,
)

# Services
from extractor.services import (
    DocumentProcessingService,
    GLClassificationService,
    DocumentProcessingError,
    DocumentNotFoundError,
    UnsupportedDocTypeError,
)

# Processors
from extractor.processor import (
    MonthlyAccountingDocumentProcessor,
    ProcessorRegistry,
)

# Base classes
from extractor.base import (
    AbstractDocumentProcessor,
    BaseDocumentProcessor,
)

__all__ = [
    # Config
    "DocumentConfig",
    "DocumentConfigFactory",
    "DocumentType",
    # Services
    "DocumentProcessingService",
    "GLClassificationService",
    "DocumentProcessingError",
    "DocumentNotFoundError",
    "UnsupportedDocTypeError",
    # Processors
    "MonthlyAccountingDocumentProcessor",
    "ProcessorRegistry",
    "AbstractDocumentProcessor",
    "BaseDocumentProcessor",
]
