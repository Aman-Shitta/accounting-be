# System imports
import ast
import logging

# Local imports
from aicounting.openai_client import OpeAIClient
from extractor.classification.prompts import GL_ASSISITANT_INSTRUCTION_SET

logger = logging.getLogger(__name__)


class GLClassifier(OpeAIClient):
    """
    GL Account Classifier using OpenAI Responses API with file_search.

    Each API call is completely stateless and isolated — no shared threads
    or context between requests, making it safe for concurrent multi-client
    processing.
    """

    def __init__(
        self,
        vector_store_ids=None,
        model="gpt-4o",
        instructions=None,
        response_schema=None,
        temperature=0.1,
        top_p=0.9,
        special_rules="",
    ):
        super().__init__(model=model)
        self.vector_store_ids = vector_store_ids or []
        self.instructions = instructions or GL_ASSISITANT_INSTRUCTION_SET
        self.response_schema = response_schema
        self.temperature = temperature
        self.top_p = top_p
        self.rules = special_rules

        # Append special rules to instructions if provided
        if self.rules and self.rules.strip():
            self.instructions += f"\n**Special Rules**:\n{self.rules}"

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

    # Reasoning models that don't support temperature/top_p
    REASONING_MODEL_PREFIXES = ("o1", "o3", "o3-mini", "o4-mini")

    def send_to_responses(self, payload: str) -> list:
        """
        Send a classification request using the Responses API.

        Each call is completely independent and stateless — no shared context
        or threads between requests.

        Args:
            payload: Formatted line items string to classify

        Returns:
            list: List of response text strings from the model
        """
        try:
            # Build the responses.create parameters
            response_params = {
                "model": self.model,
                "instructions": self.instructions,
                "input": [{"role": "user", "content": payload}],
                "tools": [{
                    "type": "file_search",
                    "vector_store_ids": self.vector_store_ids
                }],
            }

            # Reasoning models don't support temperature/top_p
            if not self.model.startswith(self.REASONING_MODEL_PREFIXES):
                response_params["temperature"] = self.temperature
                response_params["top_p"] = self.top_p

            schema = self.response_schema.get("schema") if self.response_schema else None
            name = self.response_schema.get("name") if self.response_schema else None
            strict = self.response_schema.get("strict", False) if self.response_schema else False

            # Add structured output format if schema is available
            if self.response_schema:
                response_params["text"] = {
                    "format": {
                        "type": "json_schema",
                        "schema": schema,
                        "name": name,
                        "strict": strict
                    },

                    "verbosity": "low" if self.model != "gpt-4o" else "medium"
                }

            # Use streaming to ensure we capture the complete response
            output_text = ""
            with self.client.responses.stream(**response_params) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        output_text += event.delta

            logger.info(f"[DEBUG] Streamed output length: {len(output_text)}")
            return output_text

        except Exception as e:
            logger.error(f"Error calling Responses API: {e}")
            return ""

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

        results = {}
        MAX_RETRIES = 3

        for page_num, page_data in extracted_data.items():
            try:
                line_items = page_data.get("line_items", {})
                if not line_items:
                    logger.error(
                        f"[DEBUG] No line items found for page {page_num}")
                    continue

                expected_count = len(line_items)
                payload = self.format_line_items(line_items)

                logger.info(
                    f"[DEBUG] Payload for page {page_num}:\n{payload}")

                best_classified = []

                for attempt in range(1, MAX_RETRIES + 1):
                    page_results = self.send_to_responses(payload)

                    logger.info(
                        f"[DEBUG] Page results for page {page_num} "
                        f"(attempt {attempt}): {page_results}")

                    classified_data = []
                    if page_results and isinstance(page_results, str):
                        parsed = ast.literal_eval(page_results)
                        if isinstance(parsed, dict):
                            classified_data = parsed.get("schema", [])

                    # Keep the attempt with the most classified items
                    if len(classified_data) > len(best_classified):
                        best_classified = classified_data

                    if len(classified_data) == expected_count:
                        logger.info(
                            f"Page {page_num}: count matched on attempt "
                            f"{attempt} ({len(classified_data)}/{expected_count})")
                        break

                    logger.warning(
                        f"Page {page_num}: count mismatch on attempt {attempt} "
                        f"— got {len(classified_data)}, expected {expected_count}")
                else:
                    logger.warning(
                        f"Page {page_num}: using best attempt after "
                        f"{MAX_RETRIES} tries ({len(best_classified)}/{expected_count})")

                if best_classified:
                    results[page_num] = best_classified

                logger.info(
                    f" classified_data @ page : {page_num} :: {best_classified}")

            except Exception as e:
                logger.error(
                    f"[ERROR] Exception processing page {page_num}: {e}")
                continue  # Skip to next page on error

        return results
