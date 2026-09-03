"""
Shared Gemini AI Service

This module provides a centralized service and mixin for interacting with
Google Gemini AI across all extraction pipelines. It handles:
- Client initialization and configuration
- Streaming content generation with retry logic
- Response parsing and JSON handling
- Common utility methods for working with Gemini
"""

import logging
import os
import sys
import time
from typing import Any, Optional

from django.conf import settings
from google import genai
from google.genai import types

from extractor.utils import JSONHelper

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Centralized Gemini AI service for document processing.

    This service provides a unified interface for interacting with Google Gemini,
    including client management, content generation, and response handling.

    Usage:
        # As a standalone service
        service = GeminiService()
        response = service.generate_content(contents, config)

        # With custom model
        service = GeminiService(model="gemini-1.5-pro")
    """

    _instance: Optional['GeminiService'] = None
    _client: genai.Client | None = None

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        use_singleton: bool = True
    ):
        """
        Initialize the Gemini service.

        Args:
            api_key: Gemini API key. Defaults to settings.GEMINI_API_KEY
            model: Model name. Defaults to settings.GEMINI_MODEL
            use_singleton: If True, reuses the same client instance
        """
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL

        if use_singleton and GeminiService._client is not None:
            self.client = GeminiService._client
        else:
            self.client = genai.Client(api_key=self.api_key)
            if use_singleton:
                GeminiService._client = self.client

    @classmethod
    def get_instance(cls) -> 'GeminiService':
        """Get or create a singleton instance of the service."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None
        cls._client = None

    def get_default_config(
        self,
        temperature: float = 0.2,
        top_p: float = 0.95,
        top_k: int = 25,
        max_output_tokens: int = 8000,
        response_mime_type: str | None = None,
        response_schema: types.Schema | None = None,
        system_instruction: list[str] | None = None,
    ) -> types.GenerateContentConfigDict:
        """
        Build a default configuration dictionary for Gemini requests.

        Args:
            temperature: Sampling temperature (0.0-1.0). Lower = more deterministic
            top_p: Nucleus sampling parameter
            top_k: Top-k sampling parameter
            max_output_tokens: Maximum tokens in response
            response_mime_type: Expected response MIME type (e.g., "application/json")
            response_schema: Schema for structured output
            system_instruction: System instruction prompts

        Returns:
            GenerateContentConfigDict ready for use
        """
        config: types.GenerateContentConfigDict = {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_output_tokens": max_output_tokens,
        }

        if response_mime_type:
            config["response_mime_type"] = response_mime_type

        if response_schema:
            config["response_schema"] = response_schema

        if system_instruction:
            config["system_instruction"] = system_instruction

        return config

    # Named config presets for common pipeline tasks

    def config_for_classification(self, **overrides) -> types.GenerateContentConfigDict:
        """Config preset for page classification (low temp, minimal output)."""
        cfg = self.get_default_config(
            temperature=0.1, top_p=0.2, top_k=15, max_output_tokens=500,
        )
        cfg.update(overrides)
        return cfg

    def config_for_extraction(self, **overrides) -> types.GenerateContentConfigDict:
        """Config preset for transaction/data extraction."""
        cfg = self.get_default_config(
            temperature=0.2, top_p=0.9, top_k=25, max_output_tokens=6000,
        )
        cfg.update(overrides)
        return cfg

    def config_for_check_extraction(self, **overrides) -> types.GenerateContentConfigDict:
        """Config preset for check image extraction."""
        cfg = self.get_default_config(
            temperature=0.1, top_p=0.8, top_k=15, max_output_tokens=4000,
        )
        cfg.update(overrides)
        return cfg

    def config_for_summary(self, **overrides) -> types.GenerateContentConfigDict:
        """Config preset for summary/control totals extraction."""
        cfg = self.get_default_config(
            temperature=0.2, top_p=0.85, top_k=20, max_output_tokens=1000,
        )
        cfg.update(overrides)
        return cfg

    def generate_content_stream(
        self,
        contents: list[Any],
        config: dict | None = None,
        model: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ):
        """
        Generate content using Gemini with streaming and retry logic.

        Args:
            contents: Content parts to send to Gemini
            config: Generation configuration dict
            model: Model to use (overrides default)
            max_retries: Number of retries on 503 errors
            retry_delay: Delay between retries in seconds

        Returns:
            Generator yielding response chunks

        Raises:
            Exception: If all retries fail or non-retryable error occurs
        """
        model = model or self.model

        # Merge with defaults
        final_config = self.get_default_config()
        if config:
            final_config.update(config)

        for attempt in range(max_retries):
            try:
                return self.client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=final_config,
                )
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]

                # Check for 503 UNAVAILABLE error (model overloaded)
                if hasattr(e, "args") and e.args and "503" in str(e.args[0]):
                    logger.warning(
                        f"[{fname}:{exc_tb.tb_lineno}] Gemini model overloaded (503). "
                        f"Retry {attempt + 1}/{max_retries} after {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(
                        f"[{fname}:{exc_tb.tb_lineno}] Gemini generate_content_stream error: {e}"
                    )
                    raise

        raise Exception("Gemini model overloaded after multiple retries.")

    def generate_content(
        self,
        contents: list[Any],
        config: dict | None = None,
        model: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> str:
        """
        Generate content using Gemini (non-streaming, collects full response).

        Args:
            contents: Content parts to send to Gemini
            config: Generation configuration dict
            model: Model to use (overrides default)
            max_retries: Number of retries on 503 errors
            retry_delay: Delay between retries in seconds

        Returns:
            Complete response text
        """
        model = model or self.model

        # Merge with defaults
        final_config = self.get_default_config()
        if config:
            final_config.update(config)

        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(**final_config),
                )
                return response.text
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]

                if hasattr(e, "args") and e.args and "503" in str(e.args[0]):
                    logger.warning(
                        f"[{fname}:{exc_tb.tb_lineno}] Gemini model overloaded (503). "
                        f"Retry {attempt + 1}/{max_retries} after {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error(
                        f"[{fname}:{exc_tb.tb_lineno}] Gemini generate_content error: {e}"
                    )
                    raise

        raise Exception("Gemini model overloaded after multiple retries.")

    def stream_to_text(self, stream_response) -> str:
        """
        Collect streaming response into a single text string.

        Args:
            stream_response: Streaming response generator

        Returns:
            Collected response text
        """
        parts = []
        for resp in stream_response:
            text = getattr(resp, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)

    def generate_content_stream_to_text(
        self,
        contents: list[Any],
        config: dict | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """
        Convenience method: generate streaming content and collect as text.

        Args:
            contents: Content parts to send to Gemini
            config: Generation configuration dict
            model: Model to use (overrides default)
            max_retries: Number of retries

        Returns:
            Complete response text
        """
        stream = self.generate_content_stream(
            contents=contents,
            config=config,
            model=model,
            max_retries=max_retries,
        )
        return self.stream_to_text(stream)

    def generate_json(
        self,
        contents: list[Any],
        schema: types.Schema,
        system_instruction: list[str] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8000,
        model: str | None = None,
    ) -> dict:
        """
        Generate structured JSON output from Gemini.

        Args:
            contents: Content parts to send
            schema: Gemini Schema for structured output
            system_instruction: System prompts
            temperature: Sampling temperature
            max_output_tokens: Max output tokens
            model: Model to use

        Returns:
            Parsed JSON dict
        """
        config = self.get_default_config(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            system_instruction=system_instruction,
        )

        raw_text = self.generate_content_stream_to_text(
            contents=contents,
            config=config,
            model=model,
        )

        return JSONHelper.parse_json(raw_text)

    def create_part_from_text(
        self,
        text: str
    ) -> types.Part:
        """
        Create a Gemini Part object from text.

        Args:
            text: Text content

        Returns:
            Gemini Part object
        """
        return types.Part.from_text(text=text)

    def create_user_content_type(self, parts: list[types.Part]) -> types.Content:

        content = types.Content(
            role="user",
            parts=[*parts]
        )
        return content

    @staticmethod
    def create_part_from_bytes(
        data: bytes,
        mime_type: str = "application/pdf"
    ) -> types.Part:
        """
        Create a Gemini Part object from bytes.

        Args:
            data: Raw bytes data
            mime_type: MIME type of the data

        Returns:
            Gemini Part object
        """
        return types.Part.from_bytes(data=data, mime_type=mime_type)

    @staticmethod
    def create_image_part(
        image_bytes: bytes,
        mime_type: str = "image/png"
    ) -> types.Part:
        """
        Create an image part for Gemini from image bytes.

        Args:
            image_bytes: Raw image bytes
            mime_type: Image MIME type (image/png, image/jpeg, etc.)

        Returns:
            Gemini Part object for the image
        """
        return types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    @staticmethod
    def create_pdf_part(pdf_bytes: bytes) -> types.Part:
        """
        Create a PDF part for Gemini.

        Args:
            pdf_bytes: Raw PDF bytes

        Returns:
            Gemini Part object for the PDF
        """
        return types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    @staticmethod
    def create_markdown_part(markdown_bytes: bytes) -> types.Part:
        """
        Create a markdown text part for Gemini.

        Args:
            markdown_bytes: Markdown content as bytes

        Returns:
            Gemini Part object for markdown
        """
        return types.Part.from_bytes(data=markdown_bytes, mime_type="text/markdown")


class GeminiMixin:
    """
    Mixin class that provides Gemini AI functionality to any class.

    This mixin adds Gemini methods to existing classes without requiring
    inheritance from a specific base class.

    Usage:
        class MyProcessor(GeminiMixin):
            def __init__(self):
                self.init_gemini()

            def process(self, data):
                config = self.get_gemini_config(temperature=0.1)
                response = self.gemini_generate_stream(contents, config)
    """

    _gemini_service: GeminiService | None = None

    def init_gemini(
        self,
        api_key: str | None = None,
        model: str | None = None,
        use_singleton: bool = True
    ):
        """
        Initialize Gemini service for this instance.

        Args:
            api_key: Optional API key override
            model: Optional model override
            use_singleton: Whether to use singleton service instance
        """
        if use_singleton:
            self._gemini_service = GeminiService.get_instance()
            if model:
                self._gemini_service.model = model
        else:
            self._gemini_service = GeminiService(
                api_key=api_key,
                model=model,
                use_singleton=False
            )

    @property
    def gemini(self, model=None) -> GeminiService:
        """Get the Gemini service instance, initializing if needed."""
        if self._gemini_service is None:
            self.init_gemini(model=model)
        return self._gemini_service

    @property
    def gemini_model(self) -> str:
        """Get the current Gemini model name."""
        return self.gemini.model

    @property
    def gemini_client(self) -> genai.Client:
        """Get the underlying Gemini client."""
        return self.gemini.client

    def get_gemini_config(
        self,
        temperature: float = 0.2,
        top_p: float = 0.2,
        top_k: int = 25,
        max_output_tokens: int = 8000,
        response_mime_type: str | None = None,
        response_schema: types.Schema | None = None,
        system_instruction: list[str] | None = None,
    ) -> types.GenerateContentConfigDict:
        """
        Build a Gemini configuration dictionary.

        Convenience wrapper around GeminiService.get_default_config()
        """
        return self.gemini.get_default_config(
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            max_output_tokens=max_output_tokens,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            system_instruction=system_instruction,
        )

    def gemini_generate_stream(
        self,
        contents: list[Any],
        config: dict | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ):
        """
        Generate streaming content using Gemini.

        Convenience wrapper around GeminiService.generate_content_stream()
        """
        return self.gemini.generate_content_stream(
            contents=contents,
            config=config,
            model=model,
            max_retries=max_retries,
        )

    def gemini_generate(
        self,
        contents: list[Any],
        config: dict | None = None,
        model: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """
        Generate content using Gemini (non-streaming).

        Convenience wrapper around GeminiService.generate_content()
        """
        return self.gemini.generate_content(
            contents=contents,
            config=config,
            model=model,
            max_retries=max_retries,
        )

    def gemini_generate_json(
        self,
        contents: list[Any],
        schema: types.Schema,
        system_instruction: list[str] | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 8000,
        model: str | None = None,
    ) -> dict:
        """
        Generate structured JSON output from Gemini.

        Convenience wrapper around GeminiService.generate_json()
        """
        return self.gemini.generate_json(
            contents=contents,
            schema=schema,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            model=model,
        )


# Convenience aliases for backward compatibility
def get_gemini_service() -> GeminiService:
    """Get the singleton Gemini service instance."""
    return GeminiService.get_instance()


def create_gemini_config(**kwargs) -> types.GenerateContentConfigDict:
    """Create a Gemini configuration dict with defaults."""
    service = get_gemini_service()
    return service.get_default_config(**kwargs)
