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
      "bounding_box": {
        "left":<number>,
        "top":<number>,
        "right":<number>,
        "bottom":<number>
      }
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


{"transactions":[{"page_number":1,"date":"01/15/2026","description":"POS PURCHASE - STORE","amount":23.45,"type":"debit", "bounding_box": {"left":0.21,"top":0.34,"right":0.24,"bottom":0.32}}]}
"""

TRANSACTIONS_SCHEMA = types.Schema(
    type = types.Type.OBJECT,
    required = ["transactions"],
    properties = {
        "transactions": types.Schema(
            type = types.Type.ARRAY,
            items = types.Schema(
                type = types.Type.OBJECT,
                required = ["date", "description", "amount", "type", "page_number"],
                properties = {
                    "date": types.Schema(
                        type = types.Type.STRING,
                        description = "Transaction date in MM/DD/YYYY format",
                    ),
                    "page_number": types.Schema(
                        type = types.Type.NUMBER,
                        description = "Page number where the transaction was found",
                    ),
                    "description": types.Schema(
                        type = types.Type.STRING,
                        description = "Transaction description or check number",
                    ),
                    "amount": types.Schema(
                        type = types.Type.NUMBER,
                        description = "Transaction amount as a positive number",
                    ),
                    "type": types.Schema(
                        type = types.Type.STRING,
                        enum = ["debit", "credit"],
                        description = "Transaction type indicating money flow",
                    ),
                    "check_number": types.Schema(
                        type = types.Type.STRING,
                        description = "Check number if the transaction is from a check table",
                    ),
                    # "bounding_box": types.Schema(
                    #     type = types.Type.OBJECT,
                    #     description = "Bounding box coordinates of the transaction row on the page",
                    #     required = ["left", "top", "right", "bottom"],
                    #     properties = {
                    #         "left": types.Schema(
                    #             type = types.Type.NUMBER,
                    #         ),
                    #         "top": types.Schema(
                    #             type = types.Type.NUMBER,
                    #         ),
                    #         "right": types.Schema(
                    #             type = types.Type.NUMBER,
                    #         ),
                    #         "bottom": types.Schema(
                    #             type = types.Type.NUMBER,
                    #         ),
                    #     },
                    # ),
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
    type = types.Type.OBJECT,
    required = [],
    properties = {
        "transactions": types.Schema(
            type = types.Type.ARRAY,
            items = types.Schema(
                type = types.Type.OBJECT,
                required = ["date", "check_number", "check_written_date", "amount", "for_memo"],
                properties = {
                    "date": types.Schema(
                        type = types.Type.STRING,
                        description = "Transaction date in MM/DD/YYYY format",
                    ),
                    "check_number": types.Schema(
                        type = types.Type.STRING,
                        description = "Check number as printed on the check",
                    ),
                    "payee": types.Schema(
                        type = types.Type.STRING,
                        description = "Name of the payee on the check",
                    ),
                    "check_written_date": types.Schema(
                        type = types.Type.STRING,
                        description = "Date written on the check in MM/DD/YYYY format",
                    ),
                    "amount": types.Schema(
                        type = types.Type.NUMBER,
                        description = "Check amount as a positive number",
                    ),
                    "for_memo": types.Schema(
                        type = types.Type.STRING,
                        description = "Memo or purpose of the check",
                    )
                },
            ),
        ),
    },
)


# RAW PROMPT


from google.cloud import documentai_v1 as documentai
import json
import mimetypes
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Set, Union
from collections import Counter

from google import genai
from google.genai import types

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

# =========================
# GEMINI CHECK IMAGE EXTRACTION
# =========================

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



_DATE_RE = re.compile(
    r"(\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b)|"
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b)",
    re.IGNORECASE,
)

_AMOUNT_TOKEN_RE = re.compile(r"\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\)?")

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _has_date(s: str) -> bool:
    return bool(_DATE_RE.search(s))

def _has_amount(s: str) -> bool:
    # Avoid treating tiny integers like "01" as amount: require decimal/comma/$/()/-`
    matches = _AMOUNT_TOKEN_RE.findall(s)
    if not matches:
        return False
    return any(
        ('.' in m) or (',' in m) or ('$' in m) or ('(' in m) or (')' in m) or ('-' in m)
        for m in matches
    )

def _row_text(row: Dict[str, Any]) -> str:
    return (row.get("text") or " | ".join(row.get("cells", []) or [])).strip()

def stitch_split_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge split transactions where date/description and amount end up on different rows.

    Handles two minimal patterns:
      A) date/no-amount  -> next row amount/no-date
      B) amount/no-date  -> next row date/no-amount   (row-order inversion)
    """
    stitched: List[Dict[str, Any]] = []
    i = 0

    while i < len(rows):
        r = rows[i]
        t = _row_text(r)
        if not t:
            i += 1
            continue

        has_d = _has_date(t)
        has_a = _has_amount(t)

        # (B) amount-only followed by date-only: attach amount into the date row
        if has_a and not has_d and i + 1 < len(rows):
            r2 = rows[i + 1]
            t2 = _row_text(r2)
            if t2 and _has_date(t2) and not _has_amount(t2):
                merged_cells = (r2.get("cells", []) or []) + (r.get("cells", []) or [])
                merged_text = (t2 + " " + t).strip()
                stitched.append({
                    "row_index": r2.get("row_index", i + 2),
                    "cells": merged_cells,
                    "text": merged_text,
                })
                i += 2
                continue

        # (A) date-only followed by amount-only: attach amount into the date row
        if has_d and not has_a and i + 1 < len(rows):
            r2 = rows[i + 1]
            t2 = _row_text(r2)
            if t2 and _has_amount(t2) and not _has_date(t2):
                merged_cells = (r.get("cells", []) or []) + (r2.get("cells", []) or [])
                merged_text = (t + " " + t2).strip()
                stitched.append({
                    "row_index": r.get("row_index", i + 1),
                    "cells": merged_cells,
                    "text": merged_text,
                })
                i += 2
                continue

        stitched.append(r)
        i += 1

    return stitched

def _coerce_amount(v: Any) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace("$", "").replace(",", "")
            if s.startswith("(") and s.endswith(")"):
                s = "-" + s[1:-1]
            return float(s)
        raise ValueError(f"Invalid amount type: {type(v)}")

def _remove_thousands_commas_outside_strings(s: str) -> str:
    """
    Remove commas used as thousands separators in JSON numbers, e.g. 1,612.83 -> 1612.83.
    Only removes commas that are between digits and occur outside of string literals.
    """
    out = []
    in_string = False
    escape = False

    for i, ch in enumerate(s):
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        # not in string
        if ch == '"':
            in_string = True
            out.append(ch)
            continue

        # remove comma if it's between digits (thousands separator)
        if ch == ",":
            prev_ch = s[i - 1] if i > 0 else ""
            next_ch = s[i + 1] if i + 1 < len(s) else ""
            if prev_ch.isdigit() and next_ch.isdigit():
                # skip this comma
                continue

        out.append(ch)

    return "".join(out)

