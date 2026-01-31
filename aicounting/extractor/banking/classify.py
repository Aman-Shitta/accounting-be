# System imports
import ast
import sys
import time

# Third-party imports
import tiktoken

# Local imports
from aicounting.openai_client import OpeAIClient

from account.models.monthly_accounting_document_model import MonthlyAccountingDocument
from account.models.monthly_document_line_models import MonthlyDocumentBankLineItem


import logging
logger = logging.getLogger(__name__)

class OpeAIThread(OpeAIClient):
    """OpenAI Client with Thread Management."""

    def count_tokens(self, text: str):
        encoding = tiktoken.encoding_for_model(self.model)
        return len(encoding.encode(text))

    # Create Thread
    def create_thread(self, vector_store_ids):
        try:
            thread = self.client.beta.threads.create(
                tool_resources={
                    "file_search": {
                        "vector_store_ids": vector_store_ids
                        }
                    }
            )
            self.thread_id = thread.id
            logger.error(f"Created Thread: {self.thread_id}")
        except Exception as e:
            logger.error(f"Error creating thread: {e}")
            return None
    
    # Create Thread
    def delete_thread(self, thread_id):
        try:
            thread = self.client.beta.threads.delete(
                thread_id=thread_id
            )
            thread_id = thread.id
            logger.error(f"Deleted Thread: {thread_id}")
            return thread_id
        except Exception as e:
            logger.error(f"Error deleting thread: {e}")
            return None

    # Send to Thread
    def send_to_thread(self, payload: str):
        try:
            if not self.thread_id:
                raise Exception("Thread not initialized. Call create_thread() first.")

            # Get latest timestamp before sending
            messages_before = self.client.beta.threads.messages.list(thread_id=self.thread_id, order="desc")
            last_timestamp = messages_before.data[0].created_at if messages_before.data else 0

            # Send user message
            self.client.beta.threads.messages.create(
                thread_id=self.thread_id, role="user", content=payload
            )

            # Start Assistant Run
            run = self.client.beta.threads.runs.create(
                thread_id=self.thread_id, assistant_id=self.assistant_id
            )

            while run.status in ['queued', 'in_progress']:
                time.sleep(2)
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=self.thread_id, run_id=run.id
                )

            if run.status != "completed":
                logger.error(f"Run failed with status: {run.status}")
                return []

            # Fetch new assistant messages after last timestamp
            messages_after = self.client.beta.threads.messages.list(
                thread_id=self.thread_id, order="asc"
            )

            output = []
            for msg in messages_after.data:
                if msg.created_at > last_timestamp and msg.role == "assistant":
                    text = "".join([
                        block.text.value
                        for block in msg.content if block.type == "text"
                    ])
                    output.append(text)

            return output

        except Exception as e:
            logger.error(f"Error sending to thread: {e}")
            return []


class GLClassifier(OpeAIThread):
    def __init__(self, assistant_id, vector_store_ids=None, special_rules=""):
        super().__init__()
        self.assistant_id = assistant_id
        self.vector_store_ids = vector_store_ids or []
        self.thread_id = None
        self.rules = special_rules

    def format_line_items(self, line_items: dict) -> str:
        """
        Formats line items into a clean, pipe-separated table string suitable for LLM input.

        Args:
            line_items (dict): Dictionary with line numbers as keys.
                Each value is a dict containing:
                    - description (str)
                    - debit_amount (float or None)
                    - credit_amount (float or None)

        Returns:
            str: A table-like string representation, e.g.,
                id | description         | transaction_type
                -------------------------------------------
                1  | Office Supplies     | debit
                2  | Product Sales       | credit
        """
        lines = []
        header = f"{'id':<3} | {'description':<20} | transaction_type"
        separator = "-" * len(header)
        lines.append(header)
        lines.append(separator)

        for line_id, line in line_items.items():
            txn_type = "debit" if line.get("debit_amount") else "credit"
            desc = line.get("description", "").strip()
            line_str = f"{line_id:<3} | {desc:<20} | {txn_type}"
            lines.append(line_str)

        return "\n".join(lines) + f"\n\n**PS: {self.rules}**" if self.rules.strip() else "\n".join(lines)

    @staticmethod
    def fetch_extracted_data(document_id: str):
        """Build extracted data structure from MonthlyAccountingDocument line items.

        Returns a dict shaped like:
        {
            page_number: {
                "line_items": {
                    line_number: {
                        "id": line_number,
                        "description": str,
                        "debit_amount": float|None,
                        "credit_amount": float|None,
                        "transaction_type": "debit"|"credit"
                    }, ...
                }
            }, ...
        }
        This mimics the legacy serializer output the classifier prompt expects.
        """
        if not MonthlyAccountingDocument or not MonthlyDocumentBankLineItem:
            logger.error("Monthly accounting models not available (possibly during migration).")
            return None
        try:
            doc = MonthlyAccountingDocument.objects.get(id=document_id)
        except MonthlyAccountingDocument.DoesNotExist:
            logger.error(f"MonthlyAccountingDocument with id {document_id} not found.")
            return None
        except Exception as e:
            logger.error(f"Error retrieving MonthlyAccountingDocument: {e}")
            return None

        extracted = {}
        # Fetch related line items ordered by page/line
        line_qs = MonthlyDocumentBankLineItem.objects.filter(document=doc).order_by('page_number', 'line_number')
        for li in line_qs:
            page_dict = extracted.setdefault(li.page_number, {"line_items": {}})
            txn_type = li.transaction_type
            # Derive debit/credit raw fields for compatibility if missing
            debit_amount = None
            credit_amount = None
            if txn_type == 'debit':
                debit_amount = float(li.amount) if li.amount is not None else None
            elif txn_type == 'credit':
                credit_amount = float(li.amount) if li.amount is not None else None
            else:
                # Fallback heuristic: if description suggests deposit vs withdrawal could be added here
                if li.amount is not None:
                    debit_amount = float(li.amount)

            page_dict["line_items"][li.line_number] = {
                "id": li.line_number,  # Using line_number as stable within page id
                "description": li.description or "",
                "debit_amount": debit_amount,
                "credit_amount": credit_amount,
                "transaction_type": txn_type or ("debit" if debit_amount else "credit")
            }
        return extracted

    def classify(self, document_id: str):
        extracted_data = self.fetch_extracted_data(document_id)

        if not extracted_data:
            logger.error("No extracted data found.")
            return {}

        return self.classify_extracted_data(extracted_data)

    def classify_extracted_data(self, extracted_data: dict):
        """
        Classify GL accounts for pre-built extracted data.
        
        Args:
            extracted_data: Dict structured as {page_number: {"line_items": {...}}}
            
        Returns:
            Dict of classified results by page
        """
        if not extracted_data:
            logger.error("No extracted data provided.")
            return {}

        self.create_thread(self.vector_store_ids)

        results = {}

        for page_num, page_data in extracted_data.items():
            try:
                line_items = page_data.get("line_items", {})
                if not line_items:
                    logger.error(f"[DEBUG] No line items found for page {page_num}")
                    continue

                payload = self.format_line_items(line_items)

                logger.error(f"[DEBUG] Payload for page {page_num}:\n{payload}")

                page_results = self.send_to_thread(payload)

                logger.error(f"[DEBUG] Page results for page {page_num}: {page_results}")
                classified_data = []
                if (
                    page_results
                    and isinstance(page_results, list)
                    and isinstance(ast.literal_eval(page_results[0]), dict)
                ):
                    classified_data = ast.literal_eval(page_results[0]).get("schema")
                    results[page_num] = classified_data

                logger.error(f" classified_data @ page : {page_num} :: ", classified_data)

                time.sleep(1)  # shorter sleep; adjust if rate limits encountered
            except Exception as e:
                logger.error(f"[ERROR] Exception processing page {page_num}: {e}")
                continue  # Skip to next page on error

        self.delete_thread(self.thread_id)
        return results
