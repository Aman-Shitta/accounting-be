import os
from pathlib import Path

from dotenv import load_dotenv

# Prefer an explicit env-file path for systemd deployments.
# Falls back to the repo-level .env (same level as manage.py).
ENV_FILE = os.environ.get("AICOUNTING_ENV_FILE", ".env")
if ENV_FILE:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
else:
    load_dotenv(dotenv_path=Path(__file__).resolve(
    ).parent.parent / ".env", override=False)


# - Gemini
GEMINI_MODEL = os.environ.get("GEMINI_MODEL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# - Openai
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_PROJECT_ID = os.environ.get("OPENAI_PROJECT_ID")


# Landing AI
LANDING_AI_API_KEY = os.environ.get("LANDING_AI_API_KEY")
LANDING_AI_ADE_MODEL = os.environ.get("LANDING_AI_ADE_MODEL")

# Anthropic (Claude)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Datalabs
DATALABS_PIPELINE_ID = os.environ.get("DATALABS_PIPELINE_ID")
