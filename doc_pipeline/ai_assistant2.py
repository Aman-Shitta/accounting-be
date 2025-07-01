
import sys
sys.stdout.reconfigure(encoding='utf-8')

from openai import OpenAI
import time


# List to store categorized items (global as per original code)
categorize_items = []

class OpeAIClient:
    """Base client for OpenAI interactions."""
    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key, project="proj_gg8QzOxMs0eazoHjcjWugxyM")

class OpenAIAssistantClient(OpeAIClient):
    """
    Client for interacting with OpenAI Assistants.
    Uses the OpenAI Python SDK for thread creation and message handling.
    """
    def __init__(self, api_key: str, assistant_id: str):
        super().__init__(api_key) # Initialize the base OpenAI client
        self.api_key = api_key
        self.assistant_id = assistant_id

    def create_thread(self, vector_store_ids):
        """
        Creates a new thread using the OpenAI SDK.
        Returns the thread ID on success, None on failure.
        """
        try:
            thread = self.client.beta.threads.create(
            tool_resources={
                "file_search": {
                    "vector_store_ids": vector_store_ids
                }
            }
        )
            
            thread_id = thread.id
            print(f"Created thread: {thread_id}")
            return thread_id
        except Exception as e:
            print(f"Error creating thread: {e}")
            return None

    def send_to_thread(self, payload: dict, thread_id: str):
        """
        Sends a message to an existing thread and retrieves ONLY the assistant's reply
        to this message, not the full thread history.
        """
        try:
            from tqdm import tqdm
            import time
            from datetime import datetime

            # Get the latest timestamp before sending
            messages_before = self.client.beta.threads.messages.list(thread_id=thread_id, order="desc")
            last_timestamp = 0
            if messages_before.data:
                last_timestamp = messages_before.data[0].created_at

            # Send the user message
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=str(payload)
            )

            # Create and run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant_id
            )

            # Poll until completion
            start_time = datetime.now()

            with tqdm(desc="Waiting for Run to Complete", bar_format="{l_bar}{bar} | {elapsed}", total=0) as pbar:
                while run.status in ['queued', 'in_progress', 'cancelling']:
                    time.sleep(2.5)
                    run = self.client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run.id
                    )
                    pbar.set_description(f"Status: {run.status}")
                    pbar.update(1)

            elapsed_time = datetime.now() - start_time
            print(f"Run completed in {elapsed_time}")

            # If run completed, fetch only new messages after the last timestamp
            if run.status == "completed":
                messages_after = self.client.beta.threads.messages.list(
                    thread_id=thread_id,
                    order="asc"  # oldest to newest for proper filtering
                )
                output_list = []

                for msg in messages_after.data:
                    if msg.created_at > last_timestamp and msg.role == "assistant":
                        content_text = ""
                        for content_block in msg.content:
                            if content_block.type == "text":
                                content_text += content_block.text.value
                        output_list.append(content_text)

                return output_list
            else:
                print(f"Run ended with status: {run.status}")
                return []

        except Exception as e:
            print(f"Error in Assistant interaction: {e}")
            return []



if __name__ == "__main__":
    # IMPORTANT: Replace with your actual OpenAI API Key and Assistant ID
    # This will not work without valid credentials.
    
    from openai import OpenAI
    import requests
    import tiktoken  # For token counting
    import math

    # Initialize Assistant
    assistant = OpenAIAssistantClient(
        api_key="REDACTED-OPENAI-API-KEY", 
        assistant_id="asst_kU6Jl2GsjwGUu3Qof5IkxnIh"
    )

    # Function to estimate token count (basic, depends on model)
    def count_tokens(text: str, model="gpt-4o"):
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))

    # Fetch Data
    url = "http://aicountingdevserver:8000/api/v1/document/02943fe5-1852-4337-8bb6-882067ce8da7/"

    try:
        response = requests.get(url)
        response.raise_for_status()
        req_data = response.json()

        api_data = req_data.get("data")
        extracted_data = api_data.get("extracted_data")

        thread_id = None
        vector_store_ids = ["vs_6862ae7e625c81918ece89a316d1861b"]

        if not thread_id:
            thread_id = assistant.create_thread(vector_store_ids)
            print("thread_id :: ", thread_id)

        final_results = {}

        if thread_id and extracted_data:
            for page_num, page_data in extracted_data.items():
                line_items = page_data.get("line_items", {})
                print(f"\n▶ Processing Page {page_num} with {len(line_items)} lines...")

                # Format all line items for this page
                formatted_lines = []
                for line_num, line_obj in line_items.items():
                    line = f"{line_num}|{line_obj.get('description')}|{'debit' if line_obj.get('debit_amount') else 'credit'}"
                    formatted_lines.append(line)

                # Prepare full page payload
                header = "id|description|transaction_type\n"
                full_payload = header + "\n".join(formatted_lines)

                # Check token count
                token_count = count_tokens(full_payload)
                print(f"Token count for page {page_num}: {token_count}")

                chunk_size = 15
                max_tokens = 25000

                # Process based on token count
                results_for_page = []

                if token_count <= max_tokens:
                    print("Sending full page...", full_payload)
                    results = assistant.send_to_thread(full_payload, thread_id)
                    results_for_page.extend(results if results else [])
                else:
                    print("Page too big, chunking into batches...")
                    total_chunks = math.ceil(len(formatted_lines) / chunk_size)

                    for i in range(total_chunks):
                        chunk_lines = formatted_lines[i * chunk_size : (i + 1) * chunk_size]
                        chunk_payload = header + "\n".join(chunk_lines)
                        print(f"🚀 Sending chunk {i + 1}/{total_chunks} with {len(chunk_lines)} lines...")
                        print("Chubnk Payload :: ", chunk_payload)
                        results = assistant.send_to_thread(chunk_payload, thread_id)
                        results_for_page.extend(results if results else [])

                # Save results per page
                final_results[page_num] = results_for_page

        else:
            print("Failed to create thread or no extracted data available.")

        # Final output result
        print("\n🎯 Final Processed Output:")
        for page, outputs in final_results.items():
            print(f"\n--- Page {page} ---")
            for output in outputs:
                print(output)
        
        import datetime
        import json
        output_filename = f"assistant_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_results, f, indent=4, ensure_ascii=False)
            print(f"\n💾 Results saved to {output_filename}")
        except Exception as e:
            print(f"Error saving results to file: {e}")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from API: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
