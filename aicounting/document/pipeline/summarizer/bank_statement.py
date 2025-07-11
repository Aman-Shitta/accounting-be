import re
import unicodedata

import json
from google.genai import types, Client
from typing import List


class BankStatementSummarizer:
    def __init__(self, llm_client: Client, model: str, schema: types.Schema=None):
        
        self.client = llm_client
        self.model = model

        self.response_schema = schema if schema and isinstance(schema, type.Schema) else types.Schema(
            type=types.Type.OBJECT,
            properties={
                "beginning_balance": {"type": types.Type.NUMBER},
                "ending_balance": {"type": types.Type.NUMBER},
                "total_deposits": {"type": types.Type.NUMBER},
                "total_withdrawals": {"type": types.Type.NUMBER},
            },
            required=[
                "beginning_balance",
                "ending_balance",
                "total_deposits",
                "total_withdrawals"
            ],
        )


    def generate_statement_summary(self, file_bytes: bytes) -> dict:
        """
        Extracts beginning balance, ending balance, total deposits, and total withdrawals
        from a complete bank statement PDF (may span multiple pages).
        """
        summary_prompt = """
        You are a financial document analyst.
        From the attached bank statement PDF, extract the following summary fields using
        the entire document context (up to 20 pages may be present):

        - beginning_balance: The opening balance at the start of the statement.
        - ending_balance: The final balance at the end of the statement.
        - total_deposits: The total amount of all deposit transactions (credits).
        - total_withdrawals: The total amount of all withdrawal transactions (debits).

        Ensure:
        - All amounts are extracted as float or numeric values (no currency symbols).
        - The result is a single flat JSON object with the above 4 keys only.
        - If a field is missing, set its value as `null`.

        Output only JSON like this:
        {
          "beginning_balance": 1234.56,
          "ending_balance": 4567.89,
          "total_deposits": 2000.00,
          "total_withdrawals": 500.00
        }
        """

        content = [
            types.Part.from_bytes(
                data=file_bytes,
                mime_type="application/pdf",
            ),
            summary_prompt
        ]


        config: types.GenerateContentConfigDict = {
            "response_schema": self.response_schema,
            "response_mime_type":"application/json",
            "temperature": 0.2,
        }

        try:
            stream_response = self.client.models.generate_content_stream(
                model=self.model,
                contents=[content],
                config=config
            )

            raw = ""

            for resp in stream_response:
                raw += resp.text

            clean_json_str = self._clean_json_string(raw)

            try:
                summary = json.loads(clean_json_str)
            except json.JSONDecodeError as e:
                import sys
                exc_type, exc_obj, exc_tb = sys.exc_info()
                print(f"[ERROR][Line {exc_tb.tb_lineno}] JSONDecodeError: {e}")
                print(f"[ERROR][Line {exc_tb.tb_lineno}] Raw response : {raw}")
                parsed_data = {}
                summary = {}

            return summary

        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            print(f"[ERROR][Line {exc_tb.tb_lineno}] Error while generating summary: {e}")
            return {}

    def _clean_json_string(self, raw: str) -> str:
        """
        Cleans and prepares LLM output for safe JSON decoding.
        """
        raw = re.sub(r'^```(?:json)?', '', raw)
        raw = raw.strip('` \n')
        raw = raw.replace('\r\n', '\\n').replace('\r', '\\n')
        raw = raw.replace("None", "null")

        # Remove control characters except newline/tab
        raw = ''.join(c for c in raw if unicodedata.category(c)[0] != 'C' or c in '\n\t')
        return raw