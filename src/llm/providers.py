from agent_project.config.settings import Settings
from agent_project.src.llm.fallback import FallbackLLM
from agent_project.src.llm.gemini_provider import GeminiProvider
from agent_project.src.llm.groq_provider import GroqProvider


def build_default_fallback_llm() -> FallbackLLM:
    if not Settings.GEMINI_API_KEY and not Settings.GROQ_API_KEY:
        raise RuntimeError("No API key configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in your environment before running the extractor.")

    return FallbackLLM([
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash"),
        GeminiProvider(Settings.GEMINI_API_KEY, "gemini-3.5-flash-lite"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-120b"),
        GroqProvider(Settings.GROQ_API_KEY, "openai/gpt-oss-20b"),
    ])