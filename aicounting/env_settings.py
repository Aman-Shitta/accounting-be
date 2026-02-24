import os
from pathlib import Path

from dotenv import load_dotenv

# Prefer an explicit env-file path for systemd deployments.
# Falls back to the repo-level .env (same level as manage.py).
ENV_FILE = os.environ.get("AICOUNTING_ENV_FILE")
if ENV_FILE:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
else:
    load_dotenv(dotenv_path=Path(__file__).resolve(
    ).parent.parent / ".env", override=False)

# LLM

# - Gemini
GEMINI_MODEL = os.environ.get("GEMINI_MODEL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# - Openai
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_PROJECT_ID = os.environ.get("OPENAI_PROJECT_ID")


# Azure Storage Configuration
AZURE_ACCOUNT_NAME = os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')
AZURE_ACCOUNT_KEY = os.environ.get('AZURE_STORAGE_ACCOUNT_KEY')
AZURE_CONTAINER_NAME = os.environ.get('AZURE_CONTAINER_NAME')

# Landing AI
LANDING_AI_API_KEY = os.environ.get("LANDING_AI_API_KEY")
LANDING_AI_ADE_MODEL = os.environ.get("LANDING_AI_ADE_MODEL")

# Document AI

DOCUMENT_AI_PROJECT_ID = os.environ.get('DOCUMENT_AI_PROJECT_ID')
DOCUMENT_AI_PROCESSOR_ID = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')
DOCUMENT_AI_LOCATION = os.environ.get('DOCUMENT_AI_LOCATION')
