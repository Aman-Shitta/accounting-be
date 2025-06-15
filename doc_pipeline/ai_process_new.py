import json
import re
import unicodedata
from typing import Any, List

from google import genai
from google.genai import types

from utils import split_pdf_to_pages

class DocumentProcessor:
    def __init__(self, key: str, prompt: str):
        self.prompt = prompt # bank_statment, cheque stm, POS
        self.client = genai.Client(api_key=key)
        self.model = "gemini-2.0-flash"

    def process_document(self, file_bytes: bytes, mime_type: str = "application/pdf") -> Any:
        try:
            return self.process_pages(file_bytes, mime_type)

        except Exception as e:
            raise RuntimeError(f"Failed to process document: {str(e)}")

    def process_pages(self, file_bytes: bytes, mime_type: str) -> List[dict]:

        page_bytes_list = split_pdf_to_pages(file_bytes)
        all_page_data = []
        previous_page_context = ""

        for i, page_bytes in enumerate(page_bytes_list):
            content = [
                types.Part.from_bytes(
                    data=page_bytes,
                    mime_type=mime_type,
                ),
                f"{self.prompt}\nPrevious page context: {previous_page_context}\nExtract data from current page only."
            ]

            stream_response = self.client.models.generate_content_stream(
                model=self.model,
                contents=[content],
            )

            # system_instruction = """
            #     You are a helpful language translator.
            #     Your mission is to translate text in English to French.
            #     """

            # prompt = """
            # User input: I like bagels.
            # Answer:
            # """

            
            # response = self.client.models.generate_content(
            #     model=self.model,
            #     contents=prompt,
            #     config=types.GenerateContentConfig(
            #         system_instruction=system_instruction,
            #         response_mime_type="application/json",

            #     ),
            #     )
            raw = ""
            for resp in stream_response:
                raw += resp.text

            clean_json_str = self._clean_json_string(raw)
            try:
                parsed_data = json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                print(f"JSONDecodeError: {e}")
                print(f"Raw response: {raw}")
                parsed_data = {}

            processed_data = self._process_gemini_output(parsed_data)
            all_page_data.append({"page_{}".format(i + 1): processed_data})

            # TODO: only update the INFORMATIION IF PREVIOUS PAGE HAD SOME VALID DATA
            # Update previous page context (you might want to customize this)
            previous_page_context = str(processed_data)  # Or a specific part of it

        return all_page_data

    def _clean_json_string(self, raw: str) -> str:
        # Remove Markdown fences and leading/trailing whitespace
        raw = re.sub(r'^```(?:json)?', '', raw)
        raw = raw.strip('` \n')

        # Normalize line endings
        raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')

        raw = raw.replace("None", "null")

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