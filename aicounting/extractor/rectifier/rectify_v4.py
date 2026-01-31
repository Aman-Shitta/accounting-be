from __future__ import annotations
from asyncio.log import logger
from decimal import Decimal
from difflib import SequenceMatcher

from google.cloud import documentai_v1 as documentai
import json
import mimetypes
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Set, Union
from collections import Counter

# OLD:
# import google.generativeai as genai

# NEW:
from google import genai


# =========================
# CONFIGURATION
# =========================

# OLD:
# genai.configure(api_key="REDACTED-GOOGLE-API-KEY")
# model = genai.GenerativeModel("gemini-2.5-flash-lite")

# NEW:
client = genai.Client(api_key="REDACTED-GOOGLE-API-KEY")
MODEL_NAME = "gemini-2.5-flash-lite"


# =========================
# DOCUMENT AI HELPERS
# =========================

def extract_text_from_anchor(text_anchor, full_text: str) -> str:
    if not text_anchor.text_segments:
        return ""
    result = []
    for seg in text_anchor.text_segments:
        try:
            start = seg.start_index
            end = seg.end_index
            if start is not None and end is not None:
                result.append(full_text[start:end])
        except Exception:
            continue
    return "".join(result)


def _x0(word: Dict[str, Any]) -> float:
    return min(v["x"] for v in word["bounding_box"])


def _x1(word: Dict[str, Any]) -> float:
    return max(v["x"] for v in word["bounding_box"])


def _y0(word: Dict[str, Any]) -> float:
    return min(v["y"] for v in word["bounding_box"])


def _y1(word: Dict[str, Any]) -> float:
    return max(v["y"] for v in word["bounding_box"])


def _x_center(word: Dict[str, Any]) -> float:
    return (_x0(word) + _x1(word)) / 2.0


def _y_center(word: Dict[str, Any]) -> float:
    return (_y0(word) + _y1(word)) / 2.0


def _estimate_y_eps(words: List[Dict[str, Any]]) -> float:
    """
    Estimate row height tolerance (normalized y units).
    """
    ys = sorted(set(round(_y_center(w), 4) for w in words))
    if len(ys) < 3:
        return 0.015
    deltas = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    deltas_sorted = sorted(deltas)
    med = deltas_sorted[len(deltas_sorted) // 2]
    # clamp to sane bounds; statements vary a lot
    return max(0.006, min(0.03, med * 0.9))


def cluster_words_into_rows(words: List[Dict[str, Any]], y_eps: Optional[float] = None) -> List[List[Dict[str, Any]]]:
    """
    Group tokens into rows by y-center quantization.
    """
    if not words:
        return []
    if y_eps is None:
        y_eps = _estimate_y_eps(words)

    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for w in words:
        key = int(round(_y_center(w) / y_eps))
        buckets.setdefault(key, []).append(w)

    # Return rows top-to-bottom
    rows = [buckets[k] for k in sorted(buckets.keys())]
    return rows


def split_row_into_cells(
    row_words: List[Dict[str, Any]],
    min_abs_gap: float = 0.02,
    gap_mult: float = 6.0,
) -> List[str]:
    """
    Split a single row into cells by detecting large horizontal gaps between adjacent tokens.

    Dynamic threshold:
      threshold = max(min_abs_gap, median_gap * gap_mult)
    """
    if not row_words:
        return []

    row_words = sorted(row_words, key=_x0)

    # compute gaps between consecutive tokens
    gaps = []
    for i in range(len(row_words) - 1):
        right = _x1(row_words[i])
        left_next = _x0(row_words[i + 1])
        gaps.append(max(0.0, left_next - right))

    if gaps:
        gaps_sorted = sorted(gaps)
        med = gaps_sorted[len(gaps_sorted) // 2]
    else:
        med = 0.0

    threshold = max(min_abs_gap, med * gap_mult)

    cells: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = [row_words[0]]

    for i in range(len(row_words) - 1):
        if gaps[i] > threshold:
            cells.append(current)
            current = [row_words[i + 1]]
        else:
            current.append(row_words[i + 1])

    if current:
        cells.append(current)

    # Build cell text
    cell_texts = []
    for cell in cells:
        # Keep internal ordering stable
        cell = sorted(cell, key=_x0)
        text = " ".join(w["text"] for w in cell if w.get("text"))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cell_texts.append(text)

    return cell_texts


def build_rows_with_cells(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Returns:
      [
        {"row_index": 1, "cells": ["...", "...", ...], "text": "cell1 | cell2 | ..."},
        ...
      ]
    """
    rows = cluster_words_into_rows(words)
    out: List[Dict[str, Any]] = []

    for idx, row_words in enumerate(rows, start=1):
        cells = split_row_into_cells(row_words)
        if not cells:
            continue
        out.append({
            "row_index": idx,
            "cells": cells,
            "text": " | ".join(cells),
        })

    return out


def process_document_ai(
    file_path: str = None,
    file_bytes: bytes = None,
    project_id: str = None,
    location: str = None,
    processor_id: str = None,
    service_account_json: str= None,
) -> Dict[str, Any]:
    if service_account_json:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = service_account_json
    client_docai = documentai.DocumentProcessorServiceClient()

    file_content = None

    if file_bytes:
        file_content = file_bytes
        mime_type = "application/pdf"
    if file_path and not file_content:
        with open(file_path, "rb") as f:
            file_content = f.read()
            mime_type, _ = mimetypes.guess_type(file_path)

    if not mime_type:
        raise ValueError(f"Could not determine mime type for {file_path}")

    name = f"projects/{project_id}/locations/{location}/processors/{processor_id}"
    raw_document = {"content": file_content, "mime_type": mime_type}
    request = {"name": name, "raw_document": raw_document}
    result = client_docai.process_document(request=request)
    doc = result.document

    full_text = doc.text or ""
    output: Dict[str, Any] = {"pages": []}

    for page_num, page in enumerate(doc.pages, start=1):
        words_on_page: List[Dict[str, Any]] = []

        for token in page.tokens:
            token_text = extract_text_from_anchor(token.layout.text_anchor, full_text).strip()
            if not token_text:
                continue

            bounding_box = [
                {"x": v.x / page.dimension.width, "y": v.y / page.dimension.height}
                for v in token.layout.bounding_poly.vertices
            ]

            words_on_page.append({"text": token_text, "bounding_box": bounding_box})

        rows = build_rows_with_cells(words_on_page)

        output["pages"].append({
            "page_number": page_num,
            "rows": rows,
        })

    return output
    # return result


# =========================
# GEMINI EXTRACTION
# =========================

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


# --- PATCH: helpers to stitch split rows (date/desc in one row, amount in next) ---

_DATE_RE = re.compile(
    r"(\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b)|"
    r"(\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b)",
    re.IGNORECASE,
)

_AMOUNT_TOKEN_RE = re.compile(r"\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\)?")

def _row_text(row: Dict[str, Any]) -> str:
    return (row.get("text") or " | ".join(row.get("cells", []) or [])).strip()

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


# --- PATCH: more robust Gemini response text extraction ---

def _gemini_response_to_text(resp) -> str:
    # google.genai responses typically expose `.text` directly.
    text = getattr(resp, "text", None)
    if isinstance(text, str) and text.strip():
        return text

    # Fallback: try to reconstruct from candidates/parts if present.
    candidates = getattr(resp, "candidates", None)
    if candidates:
        try:
            parts = candidates[0].content.parts
            chunks = []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    chunks.append(t)
            out = "".join(chunks)
            return out
        except Exception:
            pass

    return ""


def call_gemini(prompt: str, retries: int = 3, delay: float = 2.0) -> str:
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            # OLD:
            # resp = model.generate_content(prompt)

            # NEW:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
            )

            text = _gemini_response_to_text(resp)
            if not text or not text.strip():
                raise ValueError("Gemini returned empty response")
            return text
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay * attempt)
    raise RuntimeError(f"Gemini call failed after {retries} attempts: {last_err}")


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


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


def parse_gemini_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # PATCH: sanitize thousands separators like 1,612.83 -> 1612.83
    text = _remove_thousands_commas_outside_strings(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_OBJECT_RE.search(text)
        if not m:
            # raise ValueError("No JSON object found in Gemini response")
            print("No JSON object found in Gemini response")
            return {}
        else: 
            return json.loads(m.group(0))


def _coerce_amount(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace("$", "").replace(",", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return float(s)
    raise ValueError(f"Invalid amount type: {type(v)}")


def validate_transactions_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    txns = payload.get("transactions")
    if not isinstance(txns, list):
        return []

    cleaned: List[Dict[str, Any]] = []

    for t in txns:
        if not isinstance(t, dict):
            continue

        page_number = t.get("page_number")
        date = t.get("date")
        desc = t.get("description")
        amt = t.get("amount")
        txn_type = t.get("type")
        check_nbr = t.get("check_nbr")

        if not isinstance(page_number, int):
            continue
        if not isinstance(date, str) or not date.strip():
            continue
        if not isinstance(desc, str) or not desc.strip():
            continue
        if amt is None:
            continue

        # Validate type
        if not isinstance(txn_type, str):
            continue
        txn_type_norm = txn_type.strip().lower()
        if txn_type_norm not in {"debit", "credit"}:
            continue

        # Coerce amount to a positive number
        try:
            amount = abs(_coerce_amount(amt))
        except Exception:
            continue

        cleaned.append({
            "page_number": page_number,
            "date": date.strip(),
            "description": desc.strip(),
            "amount": amount,
            "type": txn_type_norm,
            "check_nbr": check_nbr
        })

    return cleaned


def send_to_gemini_paginated(
    json_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Sends ALL pages in a single Gemini request (instead of per-page).
    """
    all_transactions: List[Dict[str, Any]] = []
    global_id = 1

    # Stitch split rows per page before sending
    stitched_pages: List[Dict[str, Any]] = []
    for page in json_data.get("pages", []) or []:
        page = dict(page)
        page["rows"] = stitch_split_rows(page.get("rows", []) or [])
        stitched_pages.append(page)

    payload = {"pages": stitched_pages}
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

    prompt = GEMINI_PREFIX + "\n\nPAGE_CONTENT:\n" + payload_json

    # with open(output_txt_path, "a", encoding="utf-8") as gemini_log:
    #     print(f"\n📤 Sending {len(stitched_pages)} pages to Gemini in one request...")
    #     raw = call_gemini(prompt)
    #     print("\n📥 Gemini response:")
    #     print(raw)
    #     gemini_log.write(raw + "\n")

    raw = call_gemini(prompt)

    parsed = parse_gemini_json(raw)

    validated = validate_transactions_payload(parsed)

    seen: set[tuple] = set()
    
    # Track local_id per page (resets to 1 for each new page_number)
    page_local_id_counter: Dict[int, int] = {}

    for t in validated:
        key = (
            t["date"].strip(),
            " ".join(t["description"].split()).lower(),  # normalize whitespace + case
            round(float(t["amount"]), 2),                # normalize cents
            t["type"].strip().lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        
        page_num = t["page_number"]
        # Initialize or increment local_id for this page
        if page_num not in page_local_id_counter:
            page_local_id_counter[page_num] = 1
        local_id = page_local_id_counter[page_num]
        page_local_id_counter[page_num] += 1

        all_transactions.append({
            "id": local_id,                    # local id per page (resets for each page)
            "global_id": global_id,            # overall sequential id
            "local_id": local_id,              # explicit local_id field  
            "page_number": page_num,           # keep it, but NOT part of dedupe
            "date": t["date"],
            "description": t["description"],
            "amount": t["amount"],
            "type": t["type"],
            "check_nbr": t["check_nbr"]
        })
        global_id += 1

    return all_transactions

    # return parsed


def chk_img_validate_transactions_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    txns = payload.get("transactions")
    if not isinstance(txns, list):
        return []

    cleaned: List[Dict[str, Any]] = []

    for t in txns:
        if not isinstance(t, dict):
            continue

        date = t.get("date")
        check_nbr = t.get("check_nbr")
        payee = t.get("payee")
        check_written_date = t.get("check_written_date")
        amt = t.get("amount")
        for_memo = t.get("for_memo")

        # Require all 3 fields
        if not isinstance(date, str) or not date.strip():
            continue
        if not isinstance(check_nbr, str) or not check_nbr.strip():
            continue
        if not isinstance(payee, str) or not payee.strip():
            continue
        if not isinstance(check_written_date, str) or not check_written_date.strip():
            continue
        if amt is None:
            continue

        # Coerce amount; if it fails, skip
        try:
            amount = _coerce_amount(amt)
        except Exception:
            continue

        cleaned.append({
            "date": date.strip(),
            "check_nbr": check_nbr.strip(),
            "payee": payee.strip(),
            "check_written_date": check_written_date.strip(),
            "amount": amount,
            "for_memo": for_memo
        })

    return cleaned


# this is for parsing out information from the checks.  we send one page at a time here so we can classify each page
def chk_img_send_to_gemini_paginated(
    json_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    all_transactions: List[Dict[str, Any]] = []
    global_id = 1

    # with open(output_txt_path, "a", encoding="utf-8") as gemini_log:
    for page in json_data.get("pages", []):
        # --- PATCH: stitch split rows on this page before sending to Gemini ---
        page = dict(page)
        page["rows"] = stitch_split_rows(page.get("rows", []) or [])

        page_payload = {"page": page}
        page_json = json.dumps(page_payload, ensure_ascii=False, indent=2)

        prompt = GEMINI_CHK_IMG_PREFIX + "\n\nPAGE_CONTENT:\n" + page_json

        # print(f"\n📤 Sending page {page.get('page_number')} to Gemini...")
        # raw = call_gemini(prompt)
        # print("\n📥 Gemini response:")
        # print(raw)
        # gemini_log.write(raw + "\n")

        raw = call_gemini(prompt)

        parsed = parse_gemini_json(raw)
        validated = chk_img_validate_transactions_payload(parsed)

        for t in validated:
            all_transactions.append({
                "id": global_id,
                "page_number": page.get("page_number"),
                "date": t["date"],
                "check_nbr": t["check_nbr"],
                "payee": t["payee"],
                "check_written_date": t["check_written_date"],
                "amount": t["amount"],
                "for_memo": t["for_memo"]
            })
            global_id += 1
        time.sleep(15)

    return all_transactions
    # return parsed


def remove_pages_with_high_check_counts(
    checks_json: Union[Dict[str, Any], List[Dict[str, Any]]],
    page_txn_json: Union[Dict[str, Any], List[Dict[str, Any]]],
    *,
    checks_page_field: str = "page_number",
    page_txn_page_field: str = "page_number",
    threshold: int = 5,
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Counts page occurrences in checks_json and removes from page_txn_json any transaction
    whose page number appears >= threshold times in checks_json.

    Accepts either:
      - dict: {"transactions": [...]}
      - list: [...]
    Returns the same container type as page_txn_json (dict or list).
    """

    # Normalize checks list
    if isinstance(checks_json, list):
        checks_txns = checks_json
    elif isinstance(checks_json, dict):
        checks_txns = checks_json.get("transactions", []) or []
    else:
        checks_txns = []

    # Normalize page_txn list
    page_txn_is_list = isinstance(page_txn_json, list)
    if page_txn_is_list:
        page_txns = page_txn_json
    elif isinstance(page_txn_json, dict):
        page_txns = page_txn_json.get("transactions", []) or []
    else:
        page_txns = []

    # Count pages in checks
    page_counter = Counter()
    for txn in checks_txns:
        if not isinstance(txn, dict):
            continue
        page = txn.get(checks_page_field)
        if isinstance(page, int):
            page_counter[page] += 1

    excluded_pages: Set[int] = {p for p, c in page_counter.items() if c >= threshold}

    # Filter page-based txns
    filtered = [
        txn for txn in page_txns
        if not (isinstance(txn, dict) and txn.get(page_txn_page_field) in excluded_pages)
    ]

    # Return in same shape as input page_txn_json
    if page_txn_is_list:
        return filtered

    if isinstance(page_txn_json, dict):
        out = dict(page_txn_json)
        out["transactions"] = filtered
        return out

    # Fallback
    return {"transactions": filtered}



def process(document_path: str):
    file_path = "Dec 2025 bank statement.pdf"
    project_id = "574468961041"
    location = "us"
    processor_id = "2bb41ba31124bd77"
    service_account_json = "aicounting-2025v1-5a38719e49c0.json"

    result_json = process_document_ai(
        file_path=file_path,
        project_id=project_id,
        location=location,
        processor_id=processor_id,
        service_account_json=service_account_json,
    )

    transactions = send_to_gemini_paginated(result_json)

    chk_img_transactions = chk_img_send_to_gemini_paginated(result_json)

    filtered_page_txns = remove_pages_with_high_check_counts(
        checks_json=chk_img_transactions,
        page_txn_json=transactions,
        checks_page_field="page_number",
        page_txn_page_field="page_number",
        threshold=1,
    )

    return filtered_page_txns


def process_bytes(file_bytes: str):
    project_id = "574468961041"
    location = "us"
    processor_id = "2bb41ba31124bd77"
    # service_account_json = "aicounting-2025v1-5a38719e49c0.json"

    result_json = process_document_ai(
        file_bytes=file_bytes,
        project_id=project_id,
        location=location,
        processor_id=processor_id,
        # service_account_json=service_account_json,
    )

    transactions = send_to_gemini_paginated(result_json)

    chk_img_transactions = chk_img_send_to_gemini_paginated(result_json)

    filtered_page_txns = remove_pages_with_high_check_counts(
        checks_json=chk_img_transactions,
        page_txn_json=transactions,
        checks_page_field="page_number",
        page_txn_page_field="page_number",
        threshold=1,
    )

    return filtered_page_txns


class TransactionRectifierV3:
    """
    V3 Transaction Rectifier that uses Gemini extraction via process_bytes
    and compares with Landing AI master_data to rectify transactions.
    """

    def rectify_document(
        self,
        file_bytes: bytes,
        master_data: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process and rectify the document using Gemini extraction.
        
        Args:
            file_bytes: Raw PDF bytes to process
            master_data: List of transactions from Landing AI extraction
        
        Returns:
            Tuple of (rectified_transactions, rectifier_items)
            - rectified_transactions: Master data updated with rectified amounts
            - rectifier_items: Raw items extracted by Gemini rectifier
        """
        rectified_transactions = []
        rectifier_items = []
        
        try:
            # Step 1: Extract transactions using Gemini via process_bytes
            print(f"Processing document with Gemini rectifier...")
            rectifier_items = process_bytes(file_bytes)
            print(f"Gemini extracted {len(rectifier_items)} transactions")
            
            # Step 2: Normalize master_data (from Landing AI)
            line_items = self._normalize_master_data(master_data)
            print(f"Landing AI has {len(line_items)} transactions")
            
            if not rectifier_items:
                print("No transactions extracted by Gemini, returning original data")
                return line_items, rectifier_items
            
            # Step 3: Compare and rectify
            rectified_transactions = self._compare_and_rectify(line_items, rectifier_items)
            print(f"Rectification complete: {len(rectified_transactions)} transactions")
            
        except Exception as e:
            import sys
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(f"Exception in rectify_document: {exc_type}, File: {fname}, Line: {exc_tb.tb_lineno}")
            print(f"Error: {e}")
            # Return original master_data on error
            rectified_transactions = self._normalize_master_data(master_data)
        
        return rectified_transactions, rectifier_items

    def _normalize_master_data(
        self,
        master_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize master_data from Landing AI to a consistent format.
        Adds required fields like is_rectified, was_missing, etc.
        """
        if not master_data:
            return []
        
        master_data = sorted(master_data, key=lambda x: (x.get('page_number', 1), x.get('global_id', 0)))
        normalized = []
        for idx, item in enumerate(master_data):
            normalized_item = {
                'id': item.get('id', idx + 1),
                'page_number': item.get('page_number', 1),
                'date': str(item.get('date', '')).strip(),
                'description': str(item.get('description', '')).strip(),
                'amount': self._get_amount(item),
                'type': str(item.get('type', '')).strip().lower(),
                'check_number': item.get('check_number', item.get('check_nbr', '')),
                'is_check_transaction': item.get('is_check_transaction', False),
                'is_rectified': False,
                'was_missing': False,
            }
            # Preserve any additional fields from master_data
            for key in ['grounding', 'global_id', 'local_id', 'y_coord']:
                if key in item:
                    normalized_item[key] = item[key]
            
            normalized.append(normalized_item)
        
        return normalized

    def _group_by_page(self, items: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
        """Group items by page_number."""
        pages: Dict[int, List[Dict[str, Any]]] = {}
        for item in items:
            page_num = item.get('page_number', 1)
            if page_num not in pages:
                pages[page_num] = []
            pages[page_num].append(item)
        return pages

    def _compare_and_rectify(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Compare line_items with gemini_items and rectify PAGE BY PAGE.
        
        Logic:
        1. Group both line_items and gemini_items by page_number
        2. For each page, perform rectification independently
        3. Combine results and reassign global IDs
        """

        if not gemini_items:
            return line_items
        
        # If no line_items (no Landing AI data), use gemini items directly
        if not line_items:
            print("No master data from Landing AI, using Gemini items directly")
            return self._convert_gemini_to_line_items(gemini_items)
        
        # Group items by page
        line_pages = self._group_by_page(line_items)
        gemini_pages = self._group_by_page(gemini_items)
        
        # Get all unique page numbers from both sources
        all_pages = sorted(set(line_pages.keys()) | set(gemini_pages.keys()))
        
        print(f"Processing {len(all_pages)} pages: {all_pages}")
        
        # Rectify each page independently
        all_rectified: List[Dict[str, Any]] = []
        
        for page_num in all_pages:
            page_line_items = line_pages.get(page_num, [])
            page_gemini_items = gemini_pages.get(page_num, [])
            
            print(f"Page {page_num}: {len(page_line_items)} line items, {len(page_gemini_items)} gemini items")
            
            # Rectify this page
            page_rectified = self._rectify_page(page_line_items, page_gemini_items, page_num)

            all_rectified.extend(page_rectified)
        
        # Reassign global IDs
        for idx, item in enumerate(all_rectified):
            item['global_id'] = idx + 1
        
        return all_rectified

    def _rectify_page(
        self,
        page_line_items: List[Dict[str, Any]],
        page_gemini_items: List[Dict[str, Any]],
        page_num: int
    ) -> List[Dict[str, Any]]:
        """
        Rectify a single page.
        
        Logic:
        1. If page_line_items is empty: use page_gemini_items directly
        2. If lengths are same: index-by-index match
        3. If gemini has more: find and insert missing items
        4. If line_items has more: just update amounts where matched
        """
        if not page_gemini_items:
            # No gemini data for this page, return line items as-is
            return page_line_items
        
        if not page_line_items:
            # No line items for this page, convert gemini items
            print(f"Page {page_num}: No Landing AI data, using Gemini items")
            return self._convert_gemini_to_line_items(page_gemini_items)
        
        len_line = len(page_line_items)
        len_gemini = len(page_gemini_items)

        print(f"Page {page_num}: Line items = {len_line}, Gemini items = {len_gemini}")
        
        if len_line == len_gemini:
            # Same length - simple index-by-index comparison
            return self._rectify_same_length(page_line_items, page_gemini_items)
        elif len_gemini > len_line:
            # Gemini has more - find and insert missing items
            return self._rectify_gemini_has_more(page_line_items, page_gemini_items)
        else:
            # Line items has more - just update amounts where matched
            return self._rectify_line_items_has_more(page_line_items, page_gemini_items)

    def _rectify_same_length(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Rectify when both lists have same length using alignment (order-preserving).
        
        Old approach: index-by-index comparison (line[0] vs gemini[0], etc.)
        Problem: Order drift causes cascading mismatches when items swap positions
        
        New approach: Use alignment to find best pairings even with reordering
        """
        return self._rectify_with_alignment(line_items, gemini_items)

    def _rectify_gemini_has_more(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Rectify when gemini has more items using alignment (order-preserving).
        
        Old approach: Greedy matching with lookahead, inserted "missing" items
        Problem: Lookahead didn't advance to matched position, causing drift
        
        New approach: Alignment handles insertions naturally via gap scoring
        """
        return self._rectify_with_alignment(line_items, gemini_items)

    def _rectify_line_items_has_more(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Rectify when line_items has more using alignment (order-preserving).
        
        Old approach: Sequential matching, only advancing gemini_idx on match
        Problem: Single mismatch causes all subsequent comparisons to be wrong
        
        New approach: Alignment treats extra line items as gaps naturally
        """
        return self._rectify_with_alignment(line_items, gemini_items)

    def _items_match(self, line_item: Dict, gemini_item: Dict) -> bool:
        """Check if two items match by description and date."""
        # Compare dates
        line_date = str(line_item.get('date', '')).strip()
        gemini_date = str(gemini_item.get('date', '')).strip()
        
        if line_date and gemini_date:
            if not self._dates_match(line_date, gemini_date):
                return False
        
        # Compare descriptions using fuzzy matching
        line_desc = str(line_item.get('description', '')).strip().lower() if not line_item.get('is_check_transaction', False) else f'Check {line_item.get("check_number", "")}'
        gemini_desc = str(gemini_item.get('description', '')).strip().lower()
        
        if line_desc and gemini_desc:
            similarity = SequenceMatcher(None, line_desc, gemini_desc).ratio()
            if similarity < 0.6:
                return False
        
        return True

    def _normalize_desc(self, item: Dict[str, Any]) -> str:
        """
        Normalize description for comparison.
        
        Check transactions get special handling to match 'Check XXXX' format.
        Regular transactions use lowercase description text.
        """
        if item.get('is_check_transaction', False):
            return f"check {item.get('check_number', '')}".strip().lower()
        return str(item.get('description', '')).strip().lower()

    def _pair_score(self, line_item: Dict[str, Any], gemini_item: Dict[str, Any]) -> float:
        """
        Calculate similarity score between a line item and gemini item.
        
        Scoring weights:
        - Date match: +3.0 (mismatch: -5.0) - Strong indicator
        - Amount match (within 1 cent): +3.0 (mismatch: -2.0)
        - Check number match: +4.0 (mismatch: -3.0) - Strongest indicator
        - Description similarity: -1.0 to +1.0 (scaled from 0-1 ratio)
        
        Positive scores indicate good match, negative scores indicate mismatch.
        Used by alignment algorithm to find best pairings.
        """
        score = 0.0

        # Date matching: critical field with high weight
        line_date = str(line_item.get('date', '')).strip()
        gemini_date = str(gemini_item.get('date', '')).strip()
        if line_date and gemini_date:
            if self._dates_match(line_date, gemini_date):
                score += 3.0
            else:
                score -= 5.0  # Heavy penalty for date mismatch

        # Amount matching: important for verification
        line_amount = self._get_amount(line_item)
        gemini_amount = self._get_amount(gemini_item)
        if line_amount is not None and gemini_amount is not None:
            if abs(line_amount - gemini_amount) <= 0.01:  # Tolerance for rounding
                score += 3.0
            else:
                score -= 2.0

        # Check number matching: unique identifier, strongest signal
        line_check = str(line_item.get('check_number', '') or '').strip()
        gemini_check = str(gemini_item.get('check_nbr', '') or '').strip()
        if line_check and gemini_check:
            if line_check == gemini_check:
                score += 4.0  # Highest weight - unique identifier
            else:
                score -= 3.0

        # Description similarity: fuzzy matching with lower weight
        line_desc = self._normalize_desc(line_item)
        gemini_desc = self._normalize_desc(gemini_item)
        if line_desc and gemini_desc:
            similarity = SequenceMatcher(None, line_desc, gemini_desc).ratio()
            # Map 0-1 similarity to -1 to +1 score range
            score += (similarity - 0.5) * 2.0

        return score

    def _align_items(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]],
        gap_penalty: float = -2.0,
        min_match_score: float = 1.0,
    ) -> List[Tuple[Optional[int], Optional[int]]]:
        """
        Order-preserving alignment using dynamic programming (Needleman-Wunsch style).
        
        This algorithm finds the optimal alignment between two sequences while:
        1. Preserving relative order (no reordering)
        2. Allowing items to be unmatched (gaps)
        3. Maximizing total match score
        
        Args:
            line_items: List of Landing AI extracted items
            gemini_items: List of Gemini extracted items
            gap_penalty: Score penalty for leaving an item unmatched
            min_match_score: Minimum score to consider items matched
            
        Returns:
            List of (line_idx, gemini_idx) pairs where None indicates gap/unmatched.
            Example: [(0, 0), (1, None), (2, 1)] means:
            - line[0] matched with gemini[0]
            - line[1] has no match (gap in gemini)
            - line[2] matched with gemini[1]
        """
        n = len(line_items)
        m = len(gemini_items)

        # DP table: dp[i][j] = best score for aligning line_items[0:i] with gemini_items[0:j]
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        # Backtracking: tracks which move gave the best score
        back = [[None] * (m + 1) for _ in range(n + 1)]

        # Initialize: aligning with empty sequence incurs gap penalties
        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + gap_penalty
            back[i][0] = 'up'  # Skip line_item[i-1]
        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + gap_penalty
            back[0][j] = 'left'  # Skip gemini_item[j-1]

        # Fill DP table
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # Option 1: Match line[i-1] with gemini[j-1]
                match_score = self._pair_score(line_items[i - 1], gemini_items[j - 1])
                diag = dp[i - 1][j - 1] + match_score
                
                # Option 2: Skip line[i-1] (unmatched in line_items)
                up = dp[i - 1][j] + gap_penalty
                
                # Option 3: Skip gemini[j-1] (unmatched in gemini_items)
                left = dp[i][j - 1] + gap_penalty

                # Choose best option
                best = diag
                move = 'diag'
                if up > best:
                    best = up
                    move = 'up'
                if left > best:
                    best = left
                    move = 'left'

                dp[i][j] = best
                back[i][j] = move

        # Backtrack to recover alignment
        aligned: List[Tuple[Optional[int], Optional[int]]] = []
        i, j = n, m
        while i > 0 or j > 0:
            move = back[i][j]
            if move == 'diag':
                li = i - 1
                gi = j - 1
                # Check if match is strong enough to pair them
                if self._pair_score(line_items[li], gemini_items[gi]) >= min_match_score:
                    aligned.append((li, gi))  # Pair them
                else:
                    # Weak match - treat as separate gaps
                    aligned.append((li, None))
                    aligned.append((None, gi))
                i -= 1
                j -= 1
            elif move == 'up':
                # Line item has no match
                aligned.append((i - 1, None))
                i -= 1
            else:  # move == 'left'
                # Gemini item has no match
                aligned.append((None, j - 1))
                j -= 1

        aligned.reverse()  # We built it backwards
        return aligned

    def _update_amount_from_gemini(
        self,
        rectified_item: Dict[str, Any],
        line_item: Dict[str, Any],
        gemini_item: Dict[str, Any],
    ) -> None:
        """
        Update amount in rectified item using Gemini's extracted value.
        
        Logic:
        1. If Gemini has no amount, keep original (no update)
        2. If Landing AI has no amount, use Gemini's (fill missing)
        3. If amounts differ by > 1 cent, use Gemini's (correction)
        
        Modifies rectified_item in place, sets is_rectified flag on update.
        """
        line_amount = self._get_amount(line_item)
        gemini_amount = self._get_amount(gemini_item)

        # Nothing to update if Gemini has no amount
        if gemini_amount is None:
            return

        # Fill missing amount from Landing AI
        if line_amount is None:
            rectified_item['amount'] = gemini_amount
            rectified_item['is_rectified'] = True
            return

        # Correct differing amount (beyond rounding tolerance)
        if abs(line_amount - gemini_amount) > 0.01:
            rectified_item['amount'] = gemini_amount
            rectified_item['is_rectified'] = True

    def _rectify_with_alignment(
        self,
        line_items: List[Dict[str, Any]],
        gemini_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Unified rectification using alignment-based matching.
        
        Replaces the old index-by-index comparison with intelligent alignment that:
        - Handles order drift (items swapped or slightly out of sequence)
        - Tolerates missing items in either source
        - Updates amounts from Gemini when matched
        - Inserts missing non-check transactions from Gemini
        
        Process:
        1. Align items using dynamic programming to find best pairings
        2. For matched pairs: update amount from Gemini if needed
        3. For unmatched line items: keep as-is (Landing AI extraction)
        4. For unmatched Gemini items: insert if not check transaction
        5. Reassign sequential IDs
        """
        rectified: List[Dict[str, Any]] = []
        alignment = self._align_items(line_items, gemini_items)

        print(f"Alignment result: {alignment}")

        for li, gi in alignment:
            if li is not None and gi is not None:

                # Both matched: update amount from Gemini
                line_item = line_items[li]
                gemini_item = gemini_items[gi]

                # print(f"Matched Line ID ``{line_item['description']} | {line_item['amount']}` with Gemini ID {gemini_item['description']} | {gemini_item['amount']}`")

                rectified_item = line_item.copy()
                rectified_item['is_rectified'] = False
                rectified_item['was_missing'] = False
                self._update_amount_from_gemini(rectified_item, line_item, gemini_item)
                rectified.append(rectified_item)
            elif li is not None:
                # Line item has no match: keep original from Landing AI
                rectified_item = line_items[li].copy()
                rectified_item['is_rectified'] = False
                rectified_item['was_missing'] = False
                rectified.append(rectified_item)
            else:
                # Gemini item has no match: insert if not a check
                # Skip check transactions to avoid duplicates from check image processing
                gemini_item = gemini_items[gi]
                if gemini_item.get('is_check_transaction', False) or gemini_item.get('check_nbr'):
                    continue
                new_item = self._create_item_from_gemini(gemini_item, line_items[0] if line_items else {})
                new_item['is_rectified'] = True
                new_item['was_missing'] = True
                # print("Inserting missing item from Gemini:", new_item)
                rectified.append(new_item)

        # Reassign sequential IDs after alignment
        for idx, item in enumerate(rectified, start=1):
            item['id'] = idx

        return rectified

    def _dates_match(self, date1: str, date2: str) -> bool:
        """
        Check if two date strings represent the same date.
        
        Stricter matching compared to previous version to reduce false positives:
        - If either date is missing, consider it a match (permissive for missing data)
        - Extract numeric parts and compare in order (not sorted) to avoid 01/02 == 02/01
        - Fallback: compare normalized strings (removing separators)
        
        This prevents matching dates like "12/01" with "01/12" which was possible
        in the old sorted comparison.
        """
        if not date1 or not date2:
            return True  # If either is missing, consider it a match (permissive)
        
        # Extract numeric parts in order (not sorted to avoid swapping month/day)
        nums1 = re.findall(r'\d+', date1)
        nums2 = re.findall(r'\d+', date2)

        # Exact sequence match (e.g., ['12', '01', '2025'] == ['12', '01', '2025'])
        if nums1 and nums2 and nums1 == nums2:
            return True

        # Fallback: normalized string comparison
        return date1.replace('/', '').replace('-', '') == date2.replace('/', '').replace('-', '')

    def _get_amount(self, item: Dict) -> Optional[float]:
        """Extract amount from line item."""
        amount = item.get('amount')
        if amount is None:
            return None
        if isinstance(amount, Decimal):
            return float(amount)
        try:
            return float(amount)
        except (ValueError, TypeError):
            return None

    def _create_item_from_gemini(self, gemini_item: Dict, template: Dict) -> Dict:
        """Create a line item from gemini item using template structure."""
        new_item = {
            'id': gemini_item.get('id', 0),
            'page_number': gemini_item.get('page_number', template.get('page_number', 1)),
            'date': gemini_item.get('date', ''),
            'description': gemini_item.get('description', ''),
            'amount': gemini_item.get('amount'),
            'type': gemini_item.get('type', '').lower(),
            'is_check_transaction': bool(gemini_item.get('check_nbr')),
            'check_number': gemini_item.get('check_nbr', ''),
            'is_rectified': False,
            'was_missing': False,
        }
        return new_item

    def _convert_gemini_to_line_items(
        self,
        gemini_items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert Gemini items to standard line item format.
        Used when no Landing AI master data is available.
        """
        converted = []
        for idx, gemini_item in enumerate(gemini_items):
            item = {
                'id': idx + 1,
                'page_number': gemini_item.get('page_number', 1),
                'date': gemini_item.get('date', ''),
                'description': gemini_item.get('description', ''),
                'amount': gemini_item.get('amount'),
                'type': gemini_item.get('type', '').lower(),
                'is_check_transaction': bool(gemini_item.get('check_nbr')),
                'check_number': gemini_item.get('check_nbr', ''),
                'is_rectified': False,
                'was_missing': True,  # All items are "missing" from Landing AI perspective
            }
            converted.append(item)
        return converted


def get_rectifier():
    return TransactionRectifierV3()


def main():
    file_path = "/home/aman/Downloads/20260122_163930_Dec_2025_Bank_Statement.pdf"

    file_bytes = open(file_path, "rb").read()

    # Simulate master_data from Landing AI (would come from pipeline_landing_v1)
    # In production, this comes from: self.extracted_data.get("transactions", [])
    sample_master_data = []  # Empty for testing; in production comes from Landing AI

    rect = get_rectifier()
    rectified, rectifier_items = rect.rectify_document(file_bytes, sample_master_data)
    
    print(f"\n=== Rectification Results ===")
    print(f"Rectified transactions: {len(rectified)}")
    print(f"Rectifier items (from Gemini): {len(rectifier_items)}")
    
    # Show sample rectified items
    if rectified:
        print(f"\nSample rectified item:")
        print(json.dumps(rectified[0], indent=2))


if __name__ == "__main__":
    main()