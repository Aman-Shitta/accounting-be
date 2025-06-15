import json
import re
import unicodedata
from typing import Any

from google import genai
from google.genai import types
import pathlib
import httpx


class DocumentProcessor:
    def __init__(self, key: str, prompt: str):
        self.prompt = prompt
        self.client = genai.Client(api_key=key)
        self.model = "gemini-2.0-flash"

    def process_document(self, file_bytes: bytes) -> Any:
        # filepath = pathlib.Path(file_path)
        try:
            raw = ""
            content = [
                    types.Part.from_bytes(
                        data=file_bytes,
                        mime_type='application/pdf',
                    ), 
                    self.prompt
                ]

            stream_response = self.client.models.generate_content_stream(
                model=self.model,
                contents=[content],
            )

            for resp in stream_response:
                raw += resp.text

            print("raw :: ", raw)

            clean_json_str = self._clean_json_string(raw)
            parsed_data = json.loads(clean_json_str)

            processed_data = self._process_gemini_output(parsed_data)
            print("processedData :: ", processed_data)

            return processed_data

        except Exception as e:
            raise RuntimeError(f"Failed to process document: {str(e)}")

    def _clean_json_string(self, raw: str) -> str:
        # Remove Markdown fences and leading/trailing whitespace
        raw = re.sub(r'^```(?:json)?', '', raw)
        raw = raw.strip('` \n')

        # Normalize line endings
        raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')

        # Remove control characters (except tab and newline)
        raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')

        return raw

    def _process_gemini_output(self, data: dict) -> dict:
        # if "data" not in data:
        #     raise ValueError("Missing 'data' field in Gemini output")

        # Add extra info
        data["extra_info"] = "Processed by DocOCR API"

        meta = data.get("meta", {})
        if isinstance(meta, dict) and isinstance(meta.get("pages"), (int, float)):
            if meta["pages"] != 1:
                print("Warning: Expected 1 page, got", meta["pages"])

        return data
