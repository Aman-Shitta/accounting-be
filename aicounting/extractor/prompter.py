from typing import List, Dict, Union


import logging
logger = logging.getLogger(__name__)

class Configuration:
    def __init__(
        self,
        doc_type: str,
        extract_key_items: bool = True,
        key_items: List = [],
        key_items_formatted: Union[List, Dict] = [],
        extract_line_items: bool = True,
        excluded_fields: List[str] = None,
        line_items: List = [],
        base_prompt: str = None,
    ):
        self.doc_type = doc_type
        self.extract_key_items = extract_key_items
        self.key_items_formatted = key_items_formatted
        self.key_items = key_items
        self.extract_line_items = extract_line_items
        self.line_items = line_items
        self.excluded_fields = excluded_fields or []
        self.base_prompt = base_prompt or self._get_default_base_prompt()

    def _get_default_base_prompt(self) -> str:

        if self.doc_type in ["bank_statement", "credit_card"]:
            return """
            You are an expert financial document parsing agent.

            If the page is NOT `transaction_table`, do not extract any data.

            Your task is to extract **only the transactional account activity** i.e, the list of day-to-day transactions that reflect money being credited or debited from the account. This information might be presented in tabular format. Accurately extract even if the format is varied or inconsistent across pages.

            **INCLUDE only these types of entries (per row or record):**
            - **Date** (of transaction)
            - **Description** (narration or merchant/payee info)
            - **Debit** amount (money withdrawn or spent)
            - **Credit** amount (money received)

            **Additional Instructions:**
            - Do not attempt to OCR scanned cheque or deposit images.
            - Identify the cheque table items as transactional activity (i.e cheque number, date, amount) and extract them where cheque number will become  Description..
            - If transactional rows appear in paragraph or sentence form, still extract them into structured entries.
            - Use consistent formatting across all extracted transactions.

            {formatting}

            **Data Cleaning Rules:**
            - Normalize all dates to MM/DD/YYYY format (e.g., "30 Sep 2024" → "09/30/2024")
            - Remove currency symbols and commas from amounts (e.g., "₹1,234.56" → "1234.56")
            - If a field is not found, return `null` or leave it as an empty string.
            - The amounts for currency should be absolute e.g (-123 -> 123, +123 -> 123)

            Focus strictly on daily account activity that reflects money movement.
            Skip everything else that is not a transactional statement.
            """
        elif self.doc_type in ['sales', 'payroll', 'misc']:
            return """
                You are an expert financial document parsing agent specialized in sales document analysis.

                Your task is to extract structured **attribute data** from sales documents.  
                Each attribute corresponds to a specific financial or metadata field with detailed extraction instructions.  
                For every configured attribute, you must extract its **name** and **value** (as a float if numeric, else string).  

                **Attribute-Specific Instructions:**  
                        {attribute_instructions}

                **Document-Level Instructions:**
                - Extract **all attributes** explicitly defined in the Attribute-Specific Instructions above.
                - Return an entry for every configured attribute, even if its value is not found.
                - Do not extract text or data beyond the listed attributes.
                - If attribute values appear under synonyms, alternative headers, or alternate wording, map them back to the specified attribute name.
                - Ensure consistent formatting for extracted attributes across all documents.
                - If an attribute value is missing or not found, set its value to `null` (do not omit the key).

                **Data Cleaning Rules:**
                - Normalize all numeric values to float format (remove any ₹, $, commas, plus/minus signs).
                - Always return the absolute value for numeric amounts (e.g., "-123.45" → 123.45, "+123.45" → 123.45).
                - If value is missing, set it to null.
                - Dates (if attributes require them) must be in MM/DD/YYYY format.

                **Output Format (MANDATORY):**
                Return a single, valid JSON object in the following structure: 
                        {formatting}
            """


        else:
            return """
            You are an expert data extraction specialist. 
            Your job is to extract key information exclusively from sales documents.
            Do not extract any bank statement information or unrelated data.
            Focus on capturing sales transaction details, amounts, dates, and any additional sales related info.
            You should output a JSON object.
            """


def prepare_prompt(config: Configuration) -> str:
    """
    Generates a refined prompt based on the given configuration and document type.
    """
    prompt = config.base_prompt
    
    if config.doc_type in ["bank_statement", "credit_card"]:
        # Handle bank statement and credit card documents
        return _prepare_bank_statement_prompt(config, prompt)
    elif config.doc_type in ["sales", "payroll", "misc"]:
        # Handle sales documents
        return _prepare_sales_prompt(config, prompt)
    else:
        # Fallback for other document types
        return _prepare_generic_prompt(config, prompt)


def _prepare_bank_statement_prompt(config: Configuration, prompt: str) -> str:
    """
    Prepare prompt specifically for bank statements and credit card documents.
    """
    # Add instructions based on configuration
    if config.extract_key_items and config.key_items:
        prompt += f"\nExtract key items such as:\n{chr(10).join(config.key_items)}.\n"
    
    if config.extract_line_items and config.line_items:
        prompt += f"\nExtract line items (transactions) including {', '.join(config.line_items)}.\n"

    if config.excluded_fields:
        prompt += f"\nDo not extract the following fields: {', '.join(config.excluded_fields)}.\n"

    # Format key items and line items for bank statements
    key_items_str = ""
    line_items_str = ""
    
    if config.key_items_formatted:
        if isinstance(config.key_items_formatted, list):
            key_items_str = ", ".join([f'"{convert_to_snake_case(item.split(":")[0])}": "value/null"' for item in config.key_items_formatted])
        elif isinstance(config.key_items_formatted, dict):
            key_items_str = ", ".join([f'"{convert_to_snake_case(key)}": "value/null"' for key in config.key_items_formatted.keys()])
    
    if config.line_items:
        line_items_str = ", ".join([f'"{convert_to_snake_case(item.split(":")[0])}": "value/null"' for item in config.line_items])

    formatting = f"""
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
    """

    prompt = prompt.format(formatting=formatting)
    logger.error("Bank Statement Prompt formed:", prompt)
    return prompt


def _prepare_sales_prompt(config: Configuration, prompt: str) -> str:
    """
    Prepare prompt specifically for sales documents with attribute-specific instructions.
    """
    # Generate attribute-specific instructions from key_items_formatted
    attribute_instructions = ""
    key_items_json = ""
    
    if config.key_items_formatted:
        if isinstance(config.key_items_formatted, dict):
            # key_items_formatted is a dict with attribute names as keys and instructions as values
            instructions_list = []
            json_fields = []
            
            for attribute, instruction in config.key_items_formatted.items():
                snake_case_attr = convert_to_snake_case(attribute)
                instructions_list.append(f"- **{attribute}**: {instruction}")
                json_fields.append(f'"{snake_case_attr}": "value/null"')
            
            attribute_instructions = "\n".join(instructions_list)
            key_items_json = ",\n            ".join(json_fields)
            
        elif isinstance(config.key_items_formatted, list):
            # Fallback: key_items_formatted is a list of strings
            instructions_list = []
            json_fields = []
            
            for item in config.key_items_formatted:
                if ":" in item:
                    attr_name, instruction = item.split(":", 1)
                    snake_case_attr = convert_to_snake_case(attr_name.strip())
                    instructions_list.append(f"- **{attr_name.strip()}**: {instruction.strip()}")
                    json_fields.append(f'"{snake_case_attr}": "value/null"')
                else:
                    snake_case_attr = convert_to_snake_case(item)
                    instructions_list.append(f"- **{item}**: Extract the value for {item}")
                    json_fields.append(f'"{snake_case_attr}": "value/null"')
            
            attribute_instructions = "\n".join(instructions_list)
            key_items_json = ",\n            ".join(json_fields)
    
    # Add excluded fields instruction
    if config.excluded_fields:
        prompt += f"\n**EXCLUDED FIELDS:** Do not extract the following fields: {', '.join(config.excluded_fields)}.\n"

    # Format the output structure for sales documents
    formatting = f"""
    **Output Format:**
    Return the extracted data as a JSON object with the following structure:
        ```json
        {{
            "key_items": {{
            {key_items_json}
            }}
        }}
        ```
    
    Ensure that the output is valid JSON. If a field is not available, set it to null.
    """

    # Replace placeholders in the prompt
    prompt = prompt.format(
        attribute_instructions=attribute_instructions,
        formatting=formatting
    )
    prompt =  prompt.replace("    ", "") # Remove leading spaces for cleaner formatting
    logger.error("Sales Prompt formed:", prompt)
    return  prompt


def _prepare_generic_prompt(config: Configuration, prompt: str) -> str:
    """
    Prepare prompt for generic document types (fallback).
    """
    # Add basic instructions
    if config.extract_key_items and config.key_items:
        prompt += f"\nExtract key items: {', '.join(config.key_items)}.\n"
    
    if config.excluded_fields:
        prompt += f"\nDo not extract: {', '.join(config.excluded_fields)}.\n"
    
    # Basic formatting placeholder
    if "{formatting}" in prompt:
        prompt = prompt.format(formatting="Return data as a structured JSON object.")
    
    logger.error("Generic Prompt formed:", prompt)
    return prompt


def convert_to_snake_case(text):
    text = text.lower()  # Convert to lowercase
    text = text.replace(" ", "_")  # Replace spaces with underscores
    return text
