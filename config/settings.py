import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Settings:
    LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
    TANITJOBS_EMAIL = os.getenv("TANITJOBS_EMAIL", "")
    TANITJOBS_PASSWORD = os.getenv("TANITJOBS_PASSWORD", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME = "gemini-3.5-flash"
    GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
    GROQ_MODEL_NAME: str = "openai/gpt-oss-120b"
    CEREBRAS_API_KEY: str = os.environ["CEREBRAS_API_KEY"]
    CEREBRAS_MODEL_NAME: str = "gpt-oss-120b"
    MIN_OVERALL_SCORE_FOR_AUTO_LETTER = 0.5
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")