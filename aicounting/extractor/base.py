
import re
import unicodedata
import sys, os, time
from django.conf import settings
from google import genai
from django.conf import settings

from extractor.prompter import prepare_prompt

class BaseDocumentProcessor:
    
    api_key = settings.GEMINI_API_KEY
    model = settings.GEMINI_MODEL
    ai_client = None
    
    def __init__(self, config, doc):
        self.ai_client = genai.Client(api_key=self.api_key)
        self.document = doc
        self.doc_config = config
        self.doc_type: str = config.doc_type
        self.prompt = prepare_prompt(config)
        

    def _process_gemini_output(self, data: dict) -> dict:
        data["extra_info"] = "Processed by LLM"
        meta = data.get("meta", {})
        if isinstance(meta, dict) and isinstance(meta.get("pages"), (int, float)):
            if meta["pages"] != 1:
                print("Warning: Expected single page output, but got multiple pages in Gemini response.")
                data["warning"] = "Expected single page output, but got multiple pages in Gemini response."
        return data
    
    def generate_content_stream(self, **kwargs):
        model = kwargs.get("model", None)
        contents = kwargs.get("contents", [])
        config =  kwargs.get("config", {})

        if not model:
            model = self.model

        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self.ai_client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as e:
                exc_type, exc_obj, exc_tb = sys.exc_info()
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                # Check for 503 UNAVAILABLE error
                if hasattr(e, "args") and e.args and "503" in str(e.args[0]):
                    print(f"[WARN][{fname}:{exc_tb.tb_lineno}] Gemini model overloaded (503). Retry {attempt+1}/{max_retries} after 5s...")
                    time.sleep(5)
                    continue
                else:
                    print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] AIClient generate_content_stream error: {e}")
                    raise
        # If all retries failed, raise the last exception
        raise Exception("Gemini model overloaded after multiple retries.")


class JSONCleaner:
    @staticmethod
    def clean(raw: str) -> str:
        try:
            raw = re.sub(r'^```(?:json)?', '', raw)
            raw = raw.strip('` \n')
            raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')
            raw = raw.replace('\'', '\\\'')
            raw = raw.replace("None", "")
            raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')
            raw = re.sub(r"(?<!\\)'", '"', raw)
            raw = re.sub(r',(\s*[}\]])', r'\1', raw)
            first_brace = raw.find('{')
            if first_brace > 0:
                raw = raw[first_brace:]
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Cleaning JSON: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw input: {raw}")
        return raw

    @staticmethod
    def extract_first_json(raw: str) -> str:
        try:
            match = re.search(r'(\{[\s\S]*\})', raw)
            if match:
                return match.group(1)
        except Exception as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Extracting first JSON: {e}")
            print(f"[ERROR][{fname}:{exc_tb.tb_lineno}] Raw input: {raw}")
        return raw