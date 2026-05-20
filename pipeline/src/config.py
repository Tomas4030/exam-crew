import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# OpenRouter config
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "qwen/qwen3-vl-235b-a22b-instruct"

# LiteLLM/CrewAI config — use openai/ prefix to route through OPENAI_API_BASE
os.environ["OPENAI_API_BASE"] = OPENROUTER_BASE_URL
os.environ["OPENAI_API_KEY"] = OPENROUTER_API_KEY

# For LiteLLM: openai/<model> sends to OPENAI_API_BASE with that model name
MODELS = {
    "text_extraction": f"openai/{OPENROUTER_MODEL}",
    "vision": f"openai/{OPENROUTER_MODEL}",
    "structuring": f"openai/{OPENROUTER_MODEL}",
}

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = BASE_DIR / "data" / "uploads"
EXTRACTED_DIR = BASE_DIR / "data" / "extracted"
OUTPUT_DIR = BASE_DIR / "data" / "output"

# Constants
MAX_PDF_SIZE_MB = 50
MAX_PAGES = 50
MIN_IMAGE_SIZE_PX = 50
