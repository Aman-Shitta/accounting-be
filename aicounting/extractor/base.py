
import sys
import os

from django.conf import settings
from google import genai
from google.genai import types

from extractor.prompter import prepare_prompt
from extractor.gemini_service import GeminiService, GeminiMixin, JSONHelper

import logging
logger = logging.getLogger(__name__)


class BaseDocumentProcessor(GeminiMixin):
    """
    Base document processor with Gemini AI capabilities.
    
    Extends GeminiMixin to provide shared AI functionality across all document processors.
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