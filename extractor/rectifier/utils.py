import re

from google.genai import types

TRANSACTIONS_ROWS_JSON_PROMPT_BB = """
You are a financial data extraction system.

Extract transactions from the provided page content.

A) Ledger transaction:
- Must contain a date AND a description AND at least one monetary amount.
- Columns may be:
  - date, description, amount, balance
  - date, description, debit, credit, balance
  - date, description, amount (no balance)
- Sometimes debit/credit are in a single column: debits negative, credits positive.
- any text between date and amount should be considered as description
- If a transaction is split across consecutive rows (date/description on one row and the amount on the next),
  treat it as a single transaction using the combined text.

- Include "page_number" for every transaction using the page_number from the input.

B) Checks table (IMPORTANT - MUST EXTRACT):
- Bank statements often have a "Checks Paid" or "Checks" table section listing cleared checks.
- A row may contain repeated sets of (check_number, date, amount) in any order.
- A single row may contain 2, 3, 4, or 5 sets of check data.
- Split each set into a separate transaction.
- For checks table entries:
  - Use the check_number as the description (e.g., "Check #1234" or just "1234")
  - Set type to "debit" (checks are withdrawals)
  - Include the check_number field
- Example checks table row: "1234 12/05 150.00 1235 12/06 200.00" should become TWO transactions.

CRITICAL: Extract data from BOTH the transaction ledger AND the checks table. Do NOT extract from check images (scanned check pictures).

DATE FORMAT REQUIREMENT:
- Always output the field "date" in the exact format MM/DD/YYYY (zero-padded).
- Infer the year from the statement period if available on the page (e.g., "12/01/2025 - 12/31/2025"). If not present, use the year from the page header date (e.g., "12/31/2025"). If still unknown, use "01/01/1900".
- Never output dates like "Dec. 01" or "Dec 1". Convert to MM/DD/YYYY.  

MONTH MAPPING:
Jan=01 Feb=02 Mar=03 Apr=04 May=05 Jun=06 Jul=07 Aug=08 Sep=09 Oct=10 Nov=11 Dec=12

Return ONLY valid JSON in this exact format:

{
  "transactions": [
    {
      "page_number": <integer>,
      "date": "MM/DD/YYYY",
      "description": "<string> | < Check Number if from check table >",
      "amount": <number>,
      "type": "debit" | "credit",
      "check_number": "<string> (only if from check table)",
    }
  ]
}


Rules:
- Preserve transaction order as it appears in reading order.
- Do not invent transactions.
- If none exist, return {"transactions": []}.
- "amount" must be a number (negative for debits if indicated; otherwise positive).
- Use the row text/cells to understand tables with variable numbers of columns.
- "amount" must be a JSON number with no thousands separators (e.g., 1612.83 NOT 1,612.83).

OUTPUT RULES (STRICT):
- Only include a transaction if you can extract ALL of:
  1) date (MM/DD/YYYY),
  2) description (non-empty),
  3) amount (a number).

- Set "type" to "debit" if money leaves the account (payments, purchases, withdrawals, fees).
- Set "type" to "credit" if money enters the account (deposits, refunds, interest, transfers in).
- If the statement explicitly labels the column as Debit/Credit, use that.
- If the statement shows separate columns (e.g., “Withdrawals” vs “Deposits”), map them accordingly.
- If unclear, infer from signs/parentheses:
- Negative / “-” / parentheses usually → "debit"
- Positive (no minus) in a credit column or labeled credit → "credit"

Always output amount as a positive number; use "type" to indicate direction.
- Never output "amount": null. If amount is missing/uncertain, OMIT that transaction entirely.
- all amounts should be positive.
- Never invent a date. If date is missing/uncertain, OMIT that transaction entirely.
- Ignore non-transaction text such as "CURRENCY", "DOLLARS", disclosures, check-image text, headers/footers.
- Return ONLY valid JSON (no markdown, no code fences), in this schema:


{"transactions":[{"page_number":1,"date":"01/15/2026","description":"POS PURCHASE - STORE","amount":23.45,"type":"debit"}]}
"""

TRANSACTIONS_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["transactions"],
    properties={
        "transactions": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                required=["date", "description",
                          "amount", "type", "page_number"],
                properties={
                    "date": types.Schema(
                        type=types.Type.STRING,
                        description="Transaction date in MM/DD/YYYY format",
                    ),
                    "page_number": types.Schema(
                        type=types.Type.NUMBER,
                        description="Page number where the transaction was found",
                    ),
                    "description": types.Schema(
                        type=types.Type.STRING,
                        description="Transaction description or check number",
                    ),
                    "amount": types.Schema(
                        type=types.Type.NUMBER,
                        description="Transaction amount as a positive number",
                    ),
                    "type": types.Schema(
                        type=types.Type.STRING,
                        enum=["debit", "credit"],
                        description="Transaction type indicating money flow",
                    ),
                    "check_number": types.Schema(
                        type=types.Type.STRING,
                        description="Check number if the transaction is from a check table",
                    ),
                },
            ),
        ),
    },
)

CHECKS_ROWS_JSON_PROMPT = """
You are a financial data extraction system.

You are processing a multi-page document or set of images that may include:
- bank statement transaction pages (tables/lines of transactions)
- check images (front/back) embedded in the statement
- deposit slips, receipts, or other non-check images

Your goal is to extract data only from check images while continuing through the entire document.

Step 1 — Scan All Pages and Locate Check Images

For each page/image, do the following:
1. Determine whether the page contains one or more check images (full check or partial check).
2. the page contains check images, treat each check image as a separate item to extract.
3. If the page does not contain a check image, do not stop. Mark it as no_check_found and continue to the next page.

Step 2 — Check Identification (Per Detected Check)
- Classify a region as a check only if multiple indicators are present.
- Strong textual indicators (at least one):
- “Pay to the Order of” / “Pay to Order of”
- “Dollars” (written amount line)
- “Memo”
- “Signature” / “Authorized Signature”
- “Check No.” / “Check #”

Banking/numeric indicators (at least one):
- Routing number (9-digit ABA)
-Account number
- MICR line or long numeric/MICR-looking string along the bottom edge

Visual/layout indicators (at least one):
- Horizontal check layout
- Numeric amount box on the right (e.g., $1,234.56)
- Signature line near bottom right
- Check number printed top-right and/or bottom

Negative indicators (if present, likely NOT a check):

“Deposit Slip”, “Statement”, “Transaction Summary”, “Receipt”, “ATM Deposit”, “Balance Forward”

If the region does not meet the criteria, label it not_a_check and continue scanning.


Extract transactions from the provided check images: (STRICT)
1) transaction date (date when the check cleared),
2) check number,
3) pay to the order of,
4) check written date (date written on the check),
5) amount (numeric amount; do not infer from words unless clearly legible).
6) for_memo (what the check is for)


DATE FORMAT REQUIREMENT:
- Always output the field "date" in the exact format MM/DD/YYYY (zero-padded).
- Infer the year from the statement period if available on the page (e.g., "12/01/2025 - 12/31/2025"). If not present, use the year from the page header date (e.g., "12/31/2025"). If still unknown, use "01/01/1900".
- Never output dates like "Dec. 01" or "Dec 1". Convert to MM/DD/YYYY.


MONTH MAPPING:
Jan=01 Feb=02 Mar=03 Apr=04 May=05 Jun=06 Jul=07 Aug=08 Sep=09 Oct=10 Nov=11 Dec=12

Return ONLY valid JSON in this exact format:

{
  "transactions": [
    {
      "date" : "MM/DD/YYYY",
      "check_nbr" : "<string>",
      "payee": "<string>",
      "check_written_date" : "MM/DD/YYYY",
      "amount": <number>,
      "for_memo": "<string>",
    }
  ]
}

Rules:
- Preserve transaction order as it appears in reading order.
- Do not invent transactions.
- If none exist, return {"transactions": []}.
- "amount" must be a number (negative for debits if indicated; otherwise positive).
- Use the row text/cells to understand tables with variable numbers of columns.
- "amount" must be a JSON number with no thousands separators (e.g., 1612.83 NOT 1,612.83).

OUTPUT RULES (STRICT):
- Only include a transaction if you can extract ALL of:
  1) date (MM/DD/YYYY),
  2) check_nbr (non-empty),
  3) payee (non-empty),
  4) check_written_date (non-empty),
  5) amount (a number).
  6) for_memo
- Never output "amount": null. If amount is missing/uncertain, OMIT that transaction entirely.
- all amounts should be positive.
- Never invent a date. If date is missing/uncertain, OMIT that transaction entirely.
- Ignore non-transaction text such as "CURRENCY", "DOLLARS", disclosures, check-image text, headers/footers.
- Return ONLY valid JSON (no markdown, no code fences), in this schema:


{"transactions":[{"date":"MM/DD/YYYY","check_nbr":"1234","payee":"abcd","check_written_date":"MM/DD/YYYY","amount":123.45,"for_memo": "abcd"}]}

"""

CHECKS_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=[],
    properties={
        "transactions": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                required=["date", "check_number",
                          "check_written_date", "amount", "for_memo"],
                properties={
                    "date": types.Schema(
                        type=types.Type.STRING,
                        description="Transaction date in MM/DD/YYYY format",
                    ),
                    "check_number": types.Schema(
                        type=types.Type.STRING,
                        description="Check number as printed on the check",
                    ),
                    "payee": types.Schema(
                        type=types.Type.STRING,
                        description="Name of the payee on the check",
                    ),
                    "check_written_date": types.Schema(
                        type=types.Type.STRING,
                        description="Date written on the check in MM/DD/YYYY format",
                    ),
                    "amount": types.Schema(
                        type=types.Type.NUMBER,
                        description="Check amount as a positive number",
                    ),
                    "for_memo": types.Schema(
                        type=types.Type.STRING,
                        description="Memo or purpose of the check",
                    )
                },
            ),
        ),
    },
)


# RAW PROMPT


GEMINI_PREFIX = """
You are a financial data extraction system.

Extract transactions from the provided page content.

A) Ledger transaction:
- Must contain a date AND a description AND at least one monetary amount.
- Columns may be:
  - date, description, amount, balance
  - date, description, debit, credit, balance
  - date, description, amount (no balance)
- Sometimes debit/credit are in a single column: debits negative, credits positive.
- any text between date and amount should be considered as description
- If a transaction is split across consecutive rows (date/description on one row and the amount on the next),
  treat it as a single transaction using the combined text.

- Include "page_number" for every transaction using the page_number from the input.

B) Checks table:
- A row may contain repeated sets of (check_number, date, amount) in any order.
- A single row may contain 2, 3, 4, or 5 sets.
- Split each set into a transaction.

DATE FORMAT REQUIREMENT:
- Always output the field "date" in the exact format MM/DD/YYYY (zero-padded).
- Infer the year from the statement period if available on the page (e.g., "12/01/2025 - 12/31/2025"). If not present, use the year from the page header date (e.g., "12/31/2025"). If still unknown, use "01/01/1900".
- Never output dates like "Dec. 01" or "Dec 1". Convert to MM/DD/YYYY.  

MONTH MAPPING:
Jan=01 Feb=02 Mar=03 Apr=04 May=05 Jun=06 Jul=07 Aug=08 Sep=09 Oct=10 Nov=11 Dec=12

Return ONLY valid JSON in this exact format:

{
  "transactions": [
    {
      "page_number": <integer>,
      "date": "MM/DD/YYYY",
      "description": "<string>",
      "amount": <number>,
      "type": "debit" | "credit",
      "check_nbr" : "number"
    }
  ]
}


Rules:
- Preserve transaction order as it appears in reading order.
- Do not invent transactions.
- If none exist, return {"transactions": []}.
- "amount" must be a number (negative for debits if indicated; otherwise positive).
- Use the row text/cells to understand tables with variable numbers of columns.
- "amount" must be a JSON number with no thousands separators (e.g., 1612.83 NOT 1,612.83).

OUTPUT RULES (STRICT):
- Only include a transaction if you can extract ALL of:
  1) date (MM/DD/YYYY),
  2) description (non-empty),
  3) amount (a number),
  4) check_nbr (a number or null).

- Set "type" to "debit" if money leaves the account (payments, purchases, withdrawals, fees).
- Set "type" to "credit" if money enters the account (deposits, refunds, interest, transfers in).
- If the statement explicitly labels the column as Debit/Credit, use that.
- If the statement shows separate columns (e.g., “Withdrawals” vs “Deposits”), map them accordingly.
- If unclear, infer from signs/parentheses:
- Negative / “-” / parentheses usually → "debit"
- Positive (no minus) in a credit column or labeled credit → "credit"

Always output amount as a positive number; use "type" to indicate direction.
- Never output "amount": null. If amount is missing/uncertain, OMIT that transaction entirely.
- all amounts should be positive.
- Never invent a date. If date is missing/uncertain, OMIT that transaction entirely.
- Ignore non-transaction text such as "CURRENCY", "DOLLARS", disclosures, check-image text, headers/footers.
- Return ONLY valid JSON (no markdown, no code fences), in this schema:


{"transactions":[{"page_number":1,"date":"01/15/2026","description":"POS PURCHASE - STORE","amount":23.45,"type":"debit","check_nbr":1234}]}


"""

"""
Gemini Check Image Extraction
"""

GEMINI_CHK_IMG_PREFIX = """
You are a financial data extraction system.

You are processing a multi-page document or set of images that may include:
- bank statement transaction pages (tables/lines of transactions)
- check images (front/back) embedded in the statement
- deposit slips, receipts, or other non-check images

Your goal is to extract data only from check images while continuing through the entire document.

Step 1 — Scan All Pages and Locate Check Images

For each page/image, do the following:
1. Determine whether the page contains one or more check images (full check or partial check).
2. the page contains check images, treat each check image as a separate item to extract.
3. If the page does not contain a check image, do not stop. Mark it as no_check_found and continue to the next page.

Step 2 — Check Identification (Per Detected Check)
- Classify a region as a check only if multiple indicators are present.
- Strong textual indicators (at least one):
- “Pay to the Order of” / “Pay to Order of”
- “Dollars” (written amount line)
- “Memo”
- “Signature” / “Authorized Signature”
- “Check No.” / “Check #”

Banking/numeric indicators (at least one):
- Routing number (9-digit ABA)
-Account number
- MICR line or long numeric/MICR-looking string along the bottom edge

Visual/layout indicators (at least one):
- Horizontal check layout
- Numeric amount box on the right (e.g., $1,234.56)
- Signature line near bottom right
- Check number printed top-right and/or bottom

Negative indicators (if present, likely NOT a check):

“Deposit Slip”, “Statement”, “Transaction Summary”, “Receipt”, “ATM Deposit”, “Balance Forward”

If the region does not meet the criteria, label it not_a_check and continue scanning.


Extract transactions from the provided check images: (STRICT)
1) transaction date (date when the check cleared),
2) check number,
3) pay to the order of,
4) check written date (date written on the check),
5) amount (numeric amount; do not infer from words unless clearly legible).
6) for_memo (what the check is for)


DATE FORMAT REQUIREMENT:
- Always output the field "date" in the exact format MM/DD/YYYY (zero-padded).
- Infer the year from the statement period if available on the page (e.g., "12/01/2025 - 12/31/2025"). If not present, use the year from the page header date (e.g., "12/31/2025"). If still unknown, use "01/01/1900".
- Never output dates like "Dec. 01" or "Dec 1". Convert to MM/DD/YYYY.


MONTH MAPPING:
Jan=01 Feb=02 Mar=03 Apr=04 May=05 Jun=06 Jul=07 Aug=08 Sep=09 Oct=10 Nov=11 Dec=12

Return ONLY valid JSON in this exact format:

{
  "transactions": [
    {
      "date" : "MM/DD/YYYY",
      "check_nbr" : "<string>",
      "payee": "<string>",
      "check_written_date" : "MM/DD/YYYY",
      "amount": <number>,
      "for_memo": "<string>",
    }
  ]
}

Rules:
- Preserve transaction order as it appears in reading order.
- Do not invent transactions.
- If none exist, return {"transactions": []}.
- "amount" must be a number (negative for debits if indicated; otherwise positive).
- Use the row text/cells to understand tables with variable numbers of columns.
- "amount" must be a JSON number with no thousands separators (e.g., 1612.83 NOT 1,612.83).

OUTPUT RULES (STRICT):
- Only include a transaction if you can extract ALL of:
  1) date (MM/DD/YYYY),
  2) check_nbr (non-empty),
  3) payee (non-empty),
  4) check_written_date (non-empty),
  5) amount (a number).
  6) for_memo
- Never output "amount": null. If amount is missing/uncertain, OMIT that transaction entirely.
- all amounts should be positive.
- Never invent a date. If date is missing/uncertain, OMIT that transaction entirely.
- Ignore non-transaction text such as "CURRENCY", "DOLLARS", disclosures, check-image text, headers/footers.
- Return ONLY valid JSON (no markdown, no code fences), in this schema:


{"transactions":[{"date":"MM/DD/YYYY","check_nbr":"1234","payee":"abcd","check_written_date":"MM/DD/YYYY","amount":123.45,"for_memo": "abcd"}]}

"""


