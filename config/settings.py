import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(os.path.join(BASE_DIR, ".env"))

class Settings:
    LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL_NAME = "gemini-3.5-flash"
    GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
    GROQ_MODEL_NAME: str = "openai/gpt-oss-120b"