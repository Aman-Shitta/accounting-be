from openai import OpenAI

class OpeAIClient:
    """Base OpenAI Client."""
    def __init__(self, api_key, project_id="proj_gg8QzOxMs0eazoHjcjWugxyM", model="gpt-4o"):
        self.client = OpenAI(
            api_key=api_key, 
            project=project_id
        )
        self.model = model