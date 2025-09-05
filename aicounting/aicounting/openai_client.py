from openai import OpenAI
from django.conf import settings

class OpeAIClient:
    """Base OpenAI Client."""
    def __init__(self, project_id="", model="gpt-4o"):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            project=project_id
        )
        self.model = model