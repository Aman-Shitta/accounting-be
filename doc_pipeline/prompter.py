from typing import List


class Configuration:
    def __init__(
        self,
        doc_type: str = "bank_statement",
        extract_key_items: bool = True,
        key_items: List = [],
        extract_line_items: bool = True,
        excluded_fields: List[str] = None,
        line_items: List = [],
        base_prompt: str = None,
    ):
        self.doc_type = doc_type
        self.extract_key_items = extract_key_items
        self.key_items = key_items # summary details
        self.extract_line_items = extract_line_items
        self.line_items = line_items
        self.excluded_fields = excluded_fields or []
        self.base_prompt = base_prompt or self._get_default_base_prompt(doc_type)

    def _get_default_base_prompt(self, doc_type: str) -> str:
        if doc_type == "bank_statement":
            return """
            You are an expert financial document parsing agent.

            You are analyzing a bank statement PDF that may contain multiple sections, such as:
            - Transactional account activity
            - Cheque images or details
            - Deposit receipts or scanned deposits
            - Account summaries or metadata
            - Visual elements such as headers, logos, footers, or notes

            Your task is to extract **only the transactional account activity** — that is, the list of day-to-day transactions that reflect money being credited or debited from the account. This information might be presented in tabular or non-tabular formats. Accurately extract even if the format is varied or inconsistent across pages.

            **INCLUDE only these types of entries (per row or record):**
            - **Date** (of transaction)
            - **Description** (narration or merchant/payee info)
            - **Debit** amount (money withdrawn or spent)
            - **Credit** amount (money received)
            - **Balance** (optional, if available)

            **EXCLUDE the following entirely:**
            - Any cheque-related records (including cheque numbers, scan images, payees)
            - Deposit slips, scanned receipts, or deposit metadata
            - Loan or overdraft summaries, account metadata, customer info
            - Bank logo, footer, headers, and all visual branding elements
            - Any scanned or handwritten content
            - Any "non-transactional" block text such as terms, summaries, or notifications

            **Additional Instructions:**
            - Do not attempt to OCR scanned cheque or deposit images.
            - If transactional rows appear in paragraph or sentence form, still extract them into structured entries.
            - Use consistent formatting across all extracted transactions.

            {formatting}

            **Data Cleaning Rules:**
            - Normalize all dates to MM/DD/YYYY format (e.g., "30 Sep 2024" → "09/30/2024")
            - Remove currency symbols and commas from amounts (e.g., "₹1,234.56" → "1234.56")
            - If a field is not found, return `null` or leave it as an empty string.

            Focus strictly on daily account activity that reflects money movement.
            Skip everything else that is not a transactional statement.
            """

        elif doc_type == "credit_card":
            return """
            You are an expert data extraction specialist. 
            Your job is to extract key information exclusively from credit card statements.
            Do not extract any bank statement information or unrelated data.
            Focus on capturing credit card transaction details, billing amounts, due dates, and any additional credit card related info.
            You should output a JSON object.
            """
        # Add other document types here if needed
        return "You are an expert data extraction specialist. You should output a JSON object."


def prepare_prompt(config: Configuration) -> str:
    """
    Generates a refined prompt based on the given configuration.
    """
    prompt = config.base_prompt

    # Add instructions based on configuration
    if config.extract_key_items:
        prompt += f"Extract key items such as {', '.join(config.key_items)}.\n"
    if config.extract_line_items:
        prompt += f"Extract line items (transactions) including {', '.join(config.line_items)}.\n"

    if config.excluded_fields:
        prompt += f"Do not extract the following fields: {', '.join(config.excluded_fields)}.\n"

    key_items_str = ", ".join([f'"{convert_to_snake_case(item.split(":")[0])}": "value/null"' for item in config.key_items])
    line_items_str = ", ".join([f'"{convert_to_snake_case(item.split(":")[0])}": "value/null"' for item in config.line_items])

    prompt = prompt.format(formatting=f"""
    **Handling Different Formats:**  
    - Remove any non-transactional data such as balances, summaries, and fees.  

    **Formatting Rules:**  
    - Convert all dates to MM/DD/YYYY format (e.g., "Sep 30, 2024" → "09/30/2024").  
    - Remove commas from numbers (e.g., "1,234.56" → "1234.56")

    For each page in the document, extract and return:
        ```json
        {{
            "key_items": {{
            {key_items_str}
            }},
            "line_items": [
            {{
                {line_items_str}
            }},
            ...
            ]
        }}
        ```
    Ensure that the output is valid JSON. If a field is not available, leave it blank.
    """)

    print("Prompt formed : ", prompt)

    return prompt

def convert_to_snake_case(text):
    text = text.lower()  # Convert to lowercase
    text = text.replace(" ", "_")  # Replace spaces with underscores
    return text
