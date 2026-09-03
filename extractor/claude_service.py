"""
Shared Claude (Anthropic) service.

Mirrors ``extractor.gemini_service``: a singleton service wrapping the
Anthropic SDK plus a ``ClaudeMixin`` so any class can get Claude access by
calling ``self.init_claude()``.

Usage:

    class MyThing(ClaudeMixin):
        def __init__(self):
            self.init_claude()

        def do(self, pdf_bytes):
            return self.claude_generate_text(
                messages=[{"role": "user", "content": [
                    self.claude.create_pdf_part(pdf_bytes),
                    self.claude.create_text_part("Summarize this statement."),
                ]}],
                system="You are a bank-statement parser.",
            )
"""

from __future__ import annotations

import base64
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Type

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


class ClaudeService:
    """
    Centralized Anthropic / Claude service for document processing.

    Handles client construction (singleton by default), retries on transient
    errors (overloaded / rate-limited), and ergonomics for document (PDF)
    content blocks and tool-use structured output.
    """

    _instance: Optional["ClaudeService"] = None
    _client: Optional[anthropic.Anthropic] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        use_singleton: bool = True,
    ):
        self.api_key = api_key or getattr(settings, "ANTHROPIC_API_KEY", None)
        self.model = model or getattr(settings, "CLAUDE_MODEL", "claude-sonnet-4-6")

        if use_singleton and ClaudeService._client is not None:
            self.client = ClaudeService._client
        else:
            self.client = (
                anthropic.Anthropic(api_key=self.api_key)
                if self.api_key
                else anthropic.Anthropic()
            )
            if use_singleton:
                ClaudeService._client = self.client

    @classmethod
    def get_instance(cls) -> "ClaudeService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None
        cls._client = None

    # ----- content-block helpers --------------------------------------------

    @staticmethod
    def create_text_part(text: str) -> Dict[str, Any]:
        return {"type": "text", "text": text}

    @staticmethod
    def create_pdf_part(pdf_bytes: bytes) -> Dict[str, Any]:
        """Build a base64-encoded PDF document block."""
        data = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": data,
            },
        }

    @staticmethod
    def build_tool_schema(
        name: str,
        description: str,
        input_schema: Dict[str, Any] | Type,
    ) -> Dict[str, Any]:
        """
        Build a Claude tool definition.

        ``input_schema`` can be either a plain dict JSON-schema or a Pydantic
        model class, in which case ``$defs`` are resolved inline.
        """
        if isinstance(input_schema, dict):
            schema = input_schema
        else:
            schema = input_schema.model_json_schema()
            schema = _inline_refs(schema)

        return {
            "name": name,
            "description": description,
            "input_schema": schema,
        }

    # ----- generation helpers ----------------------------------------------

    def generate_text(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        max_tokens: int = 16000,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        **extra,
    ) -> str:
        """
        Run a non-streaming completion and return concatenated text blocks.
        """
        message = self._call_with_retry(
            self.client.messages.create,
            max_retries=max_retries,
            retry_delay=retry_delay,
            model=model or self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **extra,
        )
        return "".join(
            block.text
            for block in message.content
            if getattr(block, "type", "") == "text"
        )

    def generate_tool_use(
        self,
        messages: List[Dict[str, Any]],
        tool: Dict[str, Any],
        system: Optional[str] = None,
        max_tokens: int = 16000,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Force Claude to call a specific tool and return its ``input`` dict.

        Raises ``ValueError`` if Claude does not emit the expected tool_use.
        """
        message = self._call_with_retry(
            self.client.messages.create,
            max_retries=max_retries,
            retry_delay=retry_delay,
            model=model or self.model,
            max_tokens=max_tokens,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            system=system,
            messages=messages,
        )
        for block in message.content:
            if getattr(block, "type", "") == "tool_use" and block.name == tool["name"]:
                return block.input
        raise ValueError(
            f"Claude did not return tool_use '{tool['name']}'. "
            f"Stop reason: {message.stop_reason}"
        )

    def stream_tool_use(
        self,
        messages: List[Dict[str, Any]],
        tool: Dict[str, Any],
        system: Optional[str] = None,
        max_tokens: int = 16000,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> Dict[str, Any]:
        """
        Streaming variant of ``generate_tool_use`` — useful for long outputs.
        Returns the tool_use ``input`` dict from the final message.
        """
        tool_input, _ = self.stream_tool_use_with_meta(
            messages=messages,
            tool=tool,
            system=system,
            max_tokens=max_tokens,
            model=model,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        return tool_input

    def stream_tool_use_with_meta(
        self,
        messages: List[Dict[str, Any]],
        tool: Dict[str, Any],
        system: Optional[str] = None,
        max_tokens: int = 16000,
        model: Optional[str] = None,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Streaming tool-use call that also returns response metadata.

        Returns ``(tool_input, meta)`` where ``meta`` is a JSON-serializable
        dict with ``id``, ``model``, ``stop_reason``, and ``usage`` — suitable
        for debug storage.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=model or self.model,
                    max_tokens=max_tokens,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    messages=messages,
                )
                if system is not None:
                    kwargs["system"] = system
                with self.client.messages.stream(**kwargs) as stream:
                    message = stream.get_final_message()
                meta = {
                    "id": message.id,
                    "model": message.model,
                    "stop_reason": message.stop_reason,
                    "usage": {
                        "input_tokens": message.usage.input_tokens,
                        "output_tokens": message.usage.output_tokens,
                    },
                }
                for block in message.content:
                    if (
                        getattr(block, "type", "") == "tool_use"
                        and block.name == tool["name"]
                    ):
                        return block.input, meta
                raise ValueError(
                    f"Claude did not return tool_use '{tool['name']}'. "
                    f"Stop reason: {message.stop_reason}"
                )
            except Exception as e:
                last_exc = e
                if not _should_retry(e) or attempt >= max_retries:
                    _log_exc("Claude stream_tool_use error", e)
                    raise
                _log_retry("Claude stream_tool_use", attempt, max_retries, retry_delay, e)
                time.sleep(retry_delay * (2 ** (attempt - 1)))
        raise last_exc if last_exc else RuntimeError("Claude stream failed")

    # ----- internals --------------------------------------------------------

    def _call_with_retry(
        self,
        fn,
        *,
        max_retries: int,
        retry_delay: float,
        **kwargs,
    ):
        # Drop system=None so the SDK's default (omitted) is used.
        if kwargs.get("system") is None:
            kwargs.pop("system", None)

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                return fn(**kwargs)
            except Exception as e:
                last_exc = e
                if not _should_retry(e) or attempt >= max_retries:
                    _log_exc("Claude API error", e)
                    raise
                _log_retry("Claude call", attempt, max_retries, retry_delay, e)
                time.sleep(retry_delay * (2 ** (attempt - 1)))
        raise last_exc if last_exc else RuntimeError("Claude call failed")


def _should_retry(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in _RETRYABLE_STATUS_CODES:
        return True
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return False


def _log_retry(label: str, attempt: int, max_retries: int, delay: float, exc: Exception) -> None:
    logger.warning(
        f"{label}: retry {attempt}/{max_retries} after {delay}s — {type(exc).__name__}: {exc}"
    )


def _log_exc(label: str, exc: Exception) -> None:
    _, _, exc_tb = sys.exc_info()
    if exc_tb is not None:
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger.error(f"[{fname}:{exc_tb.tb_lineno}] {label}: {exc}")
    else:
        logger.error(f"{label}: {exc}")


def _inline_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten Pydantic $defs inline so Claude can consume the schema."""
    defs = schema.pop("$defs", {})
    schema.pop("definitions", None)

    def _resolve(obj):
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].rsplit("/", 1)[-1]
                return _resolve(defs.get(ref_name, {}))
            return {k: _resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_resolve(i) for i in obj]
        return obj

    return _resolve(schema)


class ClaudeMixin:
    """
    Mixin that adds Claude access to any class.

    Usage::

        class MyProcessor(ClaudeMixin):
            def __init__(self):
                self.init_claude()

            def summarize(self, pdf_bytes):
                return self.claude_generate_text(
                    messages=[{"role": "user", "content": [
                        self.claude.create_pdf_part(pdf_bytes),
                        self.claude.create_text_part("Summarize this."),
                    ]}],
                    system="You are a bank-statement parser.",
                )
    """

    _claude_service: Optional[ClaudeService] = None

    def init_claude(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        use_singleton: bool = True,
    ) -> None:
        if use_singleton:
            self._claude_service = ClaudeService.get_instance()
            if model:
                self._claude_service.model = model
        else:
            self._claude_service = ClaudeService(
                api_key=api_key, model=model, use_singleton=False
            )

    @property
    def claude(self) -> ClaudeService:
        if self._claude_service is None:
            self.init_claude()
        return self._claude_service

    @property
    def claude_client(self) -> anthropic.Anthropic:
        return self.claude.client

    @property
    def claude_model(self) -> str:
        return self.claude.model

    def claude_generate_text(self, **kwargs) -> str:
        return self.claude.generate_text(**kwargs)

    def claude_generate_tool(self, **kwargs) -> Dict[str, Any]:
        return self.claude.generate_tool_use(**kwargs)

    def claude_stream_tool(self, **kwargs) -> Dict[str, Any]:
        return self.claude.stream_tool_use(**kwargs)

    def claude_stream_tool_with_meta(self, **kwargs):
        return self.claude.stream_tool_use_with_meta(**kwargs)


def get_claude_service() -> ClaudeService:
    """Convenience alias for the singleton service."""
    return ClaudeService.get_instance()
