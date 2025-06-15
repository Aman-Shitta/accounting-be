import io
from pypdf import PdfReader, PdfWriter



def prepare_prompt_old(**kwargs):

    dtype = kwargs.get("doc_typ", "bank_statement")

    if dtype == "bank_statement":
        prompt = """
        You are an AI assistant specialized in extracting and categorizing transactions from bank statements in various formats. 
        Your task is to extract transactions and provide a clean, structured CSV output with PIPE as the delimiter.

        **Task:**  
        Extract all financial transactions from the bank statement text and output them in CSV format with the following five columns:  
        **Date | Description | Debits | Credits | Category**  

        **Important Instructions for Debit/Credit Handling:**  
        - If there is a **single Amount column**, treat **negative values as Debits** and **positive values as Credits**.  
        - If there are **separate Debit and Credit columns**, ensure that Debits are recorded under Debits and Credits under Credits.  
        - If an amount has a `-` symbol at the end, convert it into a negative number and classify as **Debit**.  
        - Transactions with terms like **"Deposit", "Payment Received", "Credit", "ACH Credit"** should be recorded as **Credits**.  
        - Transactions with terms like **"Withdrawal", "Purchase", "ACH Debit", "POS", "Check"** should be recorded as **Debits**.  

        **Handling Different Formats:**  
        - Remove any non-transactional data such as balances, summaries, and fees.  

        **Formatting Rules:**  
        - Convert all dates to MM/DD/YYYY format (e.g., "Sep 30, 2024" → "09/30/2024").  
        - Remove commas from numbers (e.g., "1,234.56" → "1234.56")

        For each page in the document, extract and return:
            ```json
            {
            "page_<page_number>": {
                "key_items": {
                "key1": "value1",
                "key2": "value2"
                },
                "line_items": [
                {
                    "Date": "MM/DD/YYYY",
                    "Description": "Transaction details",
                    "Debits": "amount",
                    "Credits": "amount",
                    "Category": "categorized label"
                },
                ...
                ]
            }
            }
        """

    return prompt


def prepare_prompt():
    return """
    You are an expert data extraction specialist. 
    Your job is to extract key information from bank statements.
    You should output a JSON object containing the following keys:

    - "transactions": A list of transactions. Each transaction should be a dictionary containing:
        - "date": The date of the transaction.
        - "description": A description of the transaction.
        - "amount": The amount of the transaction.
        - "type": The type of transaction (e.g., "deposit", "withdrawal", "payment").

    - "summary": A dictionary containing a summary of the account activity, including:
        - "opening_balance": The opening balance of the account.
        - "closing_balance": The closing balance of the account.
        - "total_deposits": The total amount of deposits.
        - "total_withdrawals": The total amount of withdrawals.
    
    **Handling Different Formats:**  
    - Remove any non-transactional data such as balances, summaries, and fees.  

    **Formatting Rules:**  
    - Convert all dates to MM/DD/YYYY format (e.g., "Sep 30, 2024" → "09/30/2024").  
    - Remove commas from numbers (e.g., "1,234.56" → "1234.56")

     - For each page in the document, extract and return:
        ```json
        {
        "page_<page_number>": {
            "key_items": {
            "key1": "value1",
            "key2": "value2"
            },
            "line_items": [
            {
                "Date": "MM/DD/YYYY",
                "Description": "Transaction details",
                "Debits": "amount",
                "Credits": "amount",
                "Category": "categorized label"
                "Missing value": null
            },
            ...
            ]
        }
        }

    Ensure that the output is valid JSON. If a field is not available, leave it blank.
    """


def split_pdf_to_pages(pdf_bytes: bytes):
    """Splits a PDF file into individual pages and returns a list of bytes for each page."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    page_bytes = []

    for page_num in range(num_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[page_num])
        
        with io.BytesIO() as output_stream:
            writer.write(output_stream)
            page_bytes.append(output_stream.getvalue())
    
    return page_bytes
