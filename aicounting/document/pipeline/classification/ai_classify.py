import ast
import sys
sys.stdout.reconfigure(encoding='utf-8')

from openai import OpenAI
import time
import math
from tqdm import tqdm
from datetime import datetime
import tiktoken
import requests
import json


class OpeAIClient:
    """Base OpenAI Client."""
    def __init__(self, api_key, project_id="proj_gg8QzOxMs0eazoHjcjWugxyM", model="gpt-4o"):
        self.client = OpenAI(
            api_key=api_key, 
            project=project_id
        )
        self.model = model

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
            print(f"Created Thread: {self.thread_id}")
        except Exception as e:
            print(f"Error creating thread: {e}")
            return None
    
    # Create Thread
    def delete_thread(self, thread_id):
        try:
            thread = self.client.beta.threads.delete(
                thread_id=thread_id
            )
            thread_id = thread.id
            print(f"Deleted Thread: {thread_id}")
            return thread_id
        except Exception as e:
            print(f"Error deleting thread: {e}")
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
                print(f"Run failed with status: {run.status}")
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
            print(f"Error sending to thread: {e}")
            return []


class GLClassifier(OpeAIClient):
    def __init__(self, api_key, assistant_id, vector_store_ids=None):
        super().__init__(api_key)
        self.assistant_id = assistant_id
        self.vector_store_ids = vector_store_ids or []
        self.thread_id = None

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

        return "\n".join(lines)

    @staticmethod
    def fetch_extracted_data(document_id: str):
        """
        Fetch extracted data using the ClassifyDocumentDataSerializer logic.
        """
        from document.models.dim_aic_doc_model import DimAICDocument
        from document.serializers import ClassifyDocumentDataSerializer
        try:
            doc = DimAICDocument.objects.get(doc_id=document_id)
            serializer = ClassifyDocumentDataSerializer(doc)
            extracted_data = serializer.data.get("extracted_data")
            return extracted_data

        except DimAICDocument.DoesNotExist:
            print(f"Document with id {document_id} not found.")
            return None
        except Exception as e:
            print(f"Error fetching extracted data: {e}")
            return None

    def classify(self, document_id: str):

        extracted_data = self.fetch_extracted_data(document_id)

        if not extracted_data:
            print("No extracted data found.")
            return {}

        self.create_thread(self.vector_store_ids)

        results = {}

        for page_num, page_data in extracted_data.items():
            try:
                line_items = page_data.get("line_items", {})
                if not line_items:
                    print(f"[DEBUG] No line items found for page {page_num}")
                    continue

                payload = self.format_line_items(line_items)

                print(f"[DEBUG] Payload for page {page_num}:\n{payload}")

                page_results = self.send_to_thread(payload)

                print(f"[DEBUG] Page results for page {page_num}: {page_results}")

                if (
                    page_results
                    and isinstance(page_results, list)
                    and isinstance(ast.literal_eval(page_results[0]), dict)
                ):
                    classified_data = ast.literal_eval(page_results[0]).get("schema")
                    results[page_num] = classified_data

                time.sleep(5)
            except Exception as e:
                print(f"[ERROR] Exception processing page {page_num}: {e}")
                continue  # Skip to next page on error

        self.delete_thread(self.thread_id)
        return results
