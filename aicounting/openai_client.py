from django.conf import settings
from openai import OpenAI


class OpeAIClient:
    """Base OpenAI Client."""

    def __init__(self, project_id="", model="gpt-4o"):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            project=settings.OPENAI_PROJECT_ID
        )
        self.model = model
