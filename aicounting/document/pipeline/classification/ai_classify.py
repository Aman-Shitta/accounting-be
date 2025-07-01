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
            thread_id = thread.id
            print(f"Created Thread: {self.thread_id}")
            return thread_id
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

            with tqdm(desc="Waiting for Run", total=0, bar_format="{l_bar}{bar} | {elapsed}") as pbar:
                while run.status in ['queued', 'in_progress']:
                    time.sleep(2)
                    run = self.client.beta.threads.runs.retrieve(
                        thread_id=self.thread_id, run_id=run.id
                    )
                    pbar.set_description(f"Status: {run.status}")
                    pbar.update(1)

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

    def format_line_items(self, line_items: dict):
        header = "id|description|transaction_type\n"
        lines = []

        for line_num, line_obj in line_items.items():
            txn_type = "debit" if line_obj.get('debit_amount') else "credit"
            line = f"{line_num}|{line_obj.get('description')}|{txn_type}"
            lines.append(line)

        return header + "\n".join(lines)

    @staticmethod
    def fetch_extracted_data(document_id: str):
        """
        Fetch extracted data using the DocumentDataSerializer logic.
        """
        from document.models.dim_aic_doc_model import DimAICDocument
        from document.serializers import DocumentDataSerializer
        try:
            doc = DimAICDocument.objects.get(doc_id=document_id)
            serializer = DocumentDataSerializer(doc)
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

        if not self.thread_id:
            self.create_thread()

        results = {}

        for page_num, page_data in extracted_data.items():
            line_items = page_data.get("line_items", {})
            if not line_items:
                continue

            print(f"\n Processing Page {page_num} with {len(line_items)} lines...")

            payload = self.format_line_items(line_items)
            token_count = self.count_tokens(payload)
            print(f"Token count for page {page_num}: {token_count}")

            print("payload :: ", payload)
            chunk_size = 15
            max_tokens = 25000
            page_results = []

            # if token_count <= max_tokens:
            #     result = self.send_to_thread(payload)
            #     page_results.extend(result or [])
            # else:
            #     total_chunks = math.ceil(len(line_items) / chunk_size)
            #     keys = list(line_items.keys())

            #     for i in range(total_chunks):
            #         chunk_keys = keys[i * chunk_size : (i + 1) * chunk_size]
            #         chunk_items = {k: line_items[k] for k in chunk_keys}
            #         chunk_payload = self.format_line_items(chunk_items)

            #         print(f"Sending chunk {i + 1}/{total_chunks}...")
            #         result = self.send_to_thread(chunk_payload)
            #         page_results.extend(result or [])

            results[page_num] = page_results

        return results
