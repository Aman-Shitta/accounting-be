import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_PROJECT_ID = os.environ.get("OPENAI_PROJECT_ID")
GEMINI_MODEL= os.environ.get("GEMINI_MODEL")

# Azure Storage Configuration
AZURE_ACCOUNT_NAME = os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')
AZURE_ACCOUNT_KEY = os.environ.get('AZURE_STORAGE_ACCOUNT_KEY')
AZURE_CONTAINER_NAME = os.environ.get('AZURE_CONTAINER_NAME', 'client-documents')

