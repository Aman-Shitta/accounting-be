
import sys
import os
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from django.conf import settings
from google import genai
from google.genai import types

from extractor.prompter import prepare_prompt
from extractor.gemini_service import GeminiService, GeminiMixin, JSONHelper

import logging
logger = logging.getLogger(__name__)


class AbstractDocumentProcessor(ABC):
    """
    Abstract base class defining the interface for all document processors.
    
    All concrete processor implementations (BankStatementProcessor, KVProcessor, etc.)
    must implement these methods to ensure consistent behavior across the system.
    """
    
    @abstractmethod
    def process_document(
        self,
        file_bytes: bytes,
        mime_type: str = "application/pdf",
        md: bool = False,
        special_rules: str = ""
    ) -> Dict[str, Any]:
        """
        Process a document and extract data.
        
        Args:
            file_bytes: Raw bytes of the document file
            mime_type: MIME type of the file
            md: Whether to generate markdown output
            special_rules: Additional extraction rules
            
        Returns:
            Dict containing extracted data and processing stats
        """
        pass
    
    @abstractmethod
    def save_results(self, extracted_data: Dict[str, Any]) -> None:
        """
        Save extracted data to the database.
        
        Args:
            extracted_data: Data extracted from the document
        """
        pass
    
    @abstractmethod
    def validate_input(self, file_bytes: bytes) -> bool:
        """
        Validate the input file before processing.
        
        Args:
            file_bytes: Raw bytes of the document file
            
        Returns:
            True if valid, raises exception otherwise
        """
        pass


class BaseDocumentProcessor(GeminiMixin, AbstractDocumentProcessor):
    """
    Base document processor with Gemini AI capabilities.
    
    Extends GeminiMixin to provide shared AI functionality across all document processors.
    Implements AbstractDocumentProcessor to ensure consistent interface.
    
    Subclasses must implement:
        - process_document(): Main extraction logic
        - save_results(): Database persistence
        - validate_input(): Input validation
    """
    
    api_key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL
    ai_client = None
    
    def __init__(self, config, doc):
        self.init_gemini()  # Initialize Gemini via mixin
        self.ai_client = self.gemini_client  # Keep backward compatibility
        self.document = doc
        self.doc_type: str = config.doc_type
        self.prompt = prepare_prompt(config)
        self.config = config  # Store config for subclass access
    
    # Default implementations that subclasses can override
    def validate_input(self, file_bytes: bytes) -> bool:
        """
        Default validation - checks file_bytes is not empty.
        Subclasses should override for document-specific validation.
        """
        if not file_bytes:
            raise ValueError("Empty file provided")
        return True
    
    def save_results(self, extracted_data: Dict[str, Any]) -> None:
        """
        Default implementation - does nothing.
        Subclasses must override to implement actual persistence.
        """
        logger.warning(
            f"{self.__class__.__name__}.save_results() not implemented. "
            "Override in subclass to enable persistence."
        )
    
    def _generate_content_stream(self, **kwargs):
        """
        Generate content stream using the shared Gemini service.
        
        This method is kept for backward compatibility with existing code.
        """
        model = kwargs.get("model", None)
        contents = kwargs.get("contents", [])
        config = kwargs.get("config", {})

        # Build config using the mixin's helper
        final_config = self.get_gemini_config(
            max_output_tokens=config.get("max_output_tokens", 8000),
            top_p=config.get("top_p", 0.95),
            top_k=config.get("top_k", 25),
            temperature=config.get("temperature", 0.2),
        )
        
        # Merge with any additional config
        final_config.update(config)

        return self.gemini_generate_stream(
            contents=contents,
            config=final_config,
            model=model,
        )


class JSONCleaner:
    """
    Backward-compatible JSON cleaning utilities.
    
    Note: For new code, prefer using JSONHelper from extractor.gemini_service
    """
    
    @staticmethod
    def clean(raw: str) -> str:
        """Clean raw LLM output for JSON parsing."""
        return JSONHelper.clean(raw)

    @staticmethod
    def extract_first_json(raw: str) -> str:
        """Extract the first complete JSON object from a string."""
        return JSONHelper.extract_first_json(raw)
    
    @staticmethod
    def updated_json_repair(raw: str) -> str:
        """Repair malformed JSON using json_repair library."""
        return JSONHelper.repair(raw)