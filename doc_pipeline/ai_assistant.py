import requests
import time

categorize_items = []


class OpenAIAssistantClient:
    def __init__(self, api_key: str, assistant_id: str):
        self.api_key = api_key
        self.assistant_id = assistant_id
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }

    def create_thread(self):
        """Create a new thread."""
        try:
            resp = requests.post(
                "https://api.openai.com/v1/threads",
                headers=self.headers,
                json={}
            )
            resp.raise_for_status()
            thread_id = resp.json()["id"]
            print(f"Created thread: {thread_id}")
            return thread_id
        except Exception as e:
            print(f"Error creating thread: {e}")
            return None

    def list_threads(self):
        """List existing threads (Not officially documented in v2 yet)."""
        # Currently, OpenAI API v2 doesn't support thread listing via API.
        # Placeholder for when it's supported in future.
        print("Thread listing is not supported yet via OpenAI API v2.")
        return []

    def send_to_thread(self, payload: dict, thread_id: str):
        """Send message to an existing thread and get response."""
        try:
            # Send message to thread
            msg_resp = requests.post(
                f"https://api.openai.com/v1/threads/{thread_id}/messages",
                headers=self.headers,
                json={"role": "user", "content": str(payload)}
            )
            msg_resp.raise_for_status()

            # Run assistant
            run_resp = requests.post(
                f"https://api.openai.com/v1/threads/{thread_id}/runs",
                headers=self.headers,
                json={"assistant_id": self.assistant_id}
            )
            run_resp.raise_for_status()
            run_id = run_resp.json()["id"]

            # Poll until completed
            while True:
                poll_resp = requests.get(
                    f"https://api.openai.com/v1/threads/{thread_id}/runs/{run_id}",
                    headers=self.headers
                )
                poll_resp.raise_for_status()
                status = poll_resp.json()["status"]
                if status == "completed":
                    break
                elif status == "failed":
                    raise Exception("OpenAI run failed")
                time.sleep(1)

            # Fetch messages
            messages_resp = requests.get(
                f"https://api.openai.com/v1/threads/{thread_id}/messages",
                headers=self.headers
            )
            messages_resp.raise_for_status()
            messages = messages_resp.json().get("data", [])

            output_list = []
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content_text = ""
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            text_block = block.get("text", "")
                            if isinstance(text_block, dict):
                                content_text += text_block.get("value", "")
                            elif isinstance(text_block, str):
                                content_text += text_block
                    output_list.append(content_text)
            return output_list

        except Exception as e:
            print(f"Error in Assistant interaction: {e}")
            return []


if __name__ == "__main__":
    assistant = OpenAIAssistantClient(
        api_key="REDACTED-OPENAI-API-KEY", 
        assistant_id="asst_9SbHYIoj1MnurVtE9UkoAWke"
    )

    import requests

    url = "http://aicountingdevserver:8000/api/v1/document/02943fe5-1852-4337-8bb6-882067ce8da7/"


    payload = {}
    headers = {}

    response = requests.request("GET", url, headers=headers, data=payload)

    data = response.json()

    api_data =  data.get("data")

    data_payload = api_data.get("extracted_data")
    
    thread_id = None
    # Create thread once
    if not thread_id:
        thread_id = assistant.create_thread()
        print("thread_id :: ", thread_id)

    # Get data from API
    url = "http://aicountingdevserver:8000/api/v1/document/02943fe5-1852-4337-8bb6-882067ce8da7/"
    response = requests.get(url)
    api_data = response.json().get("data", {})
    extracted_data = api_data.get("extracted_data", {})

    if thread_id and extracted_data:
        for page, page_data in extracted_data.items():
            line_items = page_data.get("line_items", {})
            for line_num, line_obj in line_items.items():
                results = assistant.send_to_thread(line_obj, thread_id)
                print(f"\n🔹 Categorized Result for Line {line_num}:")
                for r in results:
                    print(r)
