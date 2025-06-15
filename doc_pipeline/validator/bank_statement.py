import re
import unicodedata

import json
from google.genai import types
from typing import List

from ai_process_validate import DocumentProcessor

class BankStatementValidator:
    def __init__(self, llm_client, model):
        self.client = llm_client
        self.model = model

    def generate_transaction_summary(self, file_bytes: bytes) -> dict:
        """
        For bank statements, send the whole PDF with a summary prompt to extract
        the overall debit and credit totals.
        """
        summary_prompt = """
                You are an expert data extraction specialist.
                From the provided bank statement PDF, extract a transactional summary containing:
                - Total Debits: summed total of all debit transactions (numeric value).
                - Total Credits: summed total of all credit transactions (numeric value).

                Only use the data from the top pages if available. If not present, return an empty JSON object.
                Output the result in JSON format exactly as:
                {
                "Total Debits": <value>,
                "Total Credits": <value>
                }
            """
        content = [
            types.Part.from_bytes(
                data=file_bytes,
                mime_type="application/pdf",
            ),
            summary_prompt
        ]
        stream_response = self.client.models.generate_content_stream(
            model=self.model,
            contents=[content],
        )
        raw = ""
        for resp in stream_response:
            raw += resp.text

        clean_json_str = self._clean_json_string(raw)
        try:
            summary = json.loads(clean_json_str)
        except json.JSONDecodeError as e:
            print(f"Summary JSONDecodeError: {e}")
            print(f"Raw summary response: {raw}")
            summary = {}

        return summary

    def aggregate_page_totals(self, pages: List[dict]) -> dict:
        """
        Aggregates debit and credit totals from page data.
        Assumes each page's data has a structure that contains "line_items"
        with transaction entries holding 'Debits' and 'Credits' fields.
        """
        total_debits = 0.0
        total_credits = 0.0
        
        for page in pages:
            # page is in the form {"page_N": { ... }}
            for key, data in page.items():

                line_items = data.get("line_items", [])
                for item in line_items:
                    print("item :: ", item)
                    # Use get() and convert to float if possible; ignore if conversion fails.
                    debit_value = item.get("debit_amount", "0")
                    if debit_value:
                        debit_value = debit_value.replace(",", "").strip()
                    credit_value = item.get("credit_amount", "0")
                    if credit_value:
                        credit_value = credit_value.replace(",", "").strip()
                    try:
                        total_debits += float(debit_value) if debit_value else 0.0
                    except ValueError as ve:
                        print("Value error :: ", ve)
                    try:
                        total_credits += float(credit_value) if credit_value else 0.0
                    except ValueError as vex:
                        print("Value error crd :: ", vex)
                        # pass

        return {"Total Debits": total_debits, "Total Credits": total_credits}
    
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