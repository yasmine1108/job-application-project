# src/llm/fallback.py
import time
from src.llm.base import BaseLLMProvider, LLMProviderError


class FallbackLLM:
    def __init__(self, providers: list[BaseLLMProvider]):
        self.providers = [{"provider": p, "blocked_until": 0} for p in providers]

    def generate_structured(self, system_prompt, user_prompt, response_schema):
        last_error = None
        for entry in self.providers:
            if time.time() < entry["blocked_until"]:
                continue
            try:
                return entry["provider"].generate_structured(system_prompt, user_prompt, response_schema)
            except LLMProviderError as e:
                last_error = e
                if e.is_rate_limit:
                    entry["blocked_until"] = time.time() + 60
                    print(f"{entry['provider'].name} unavailable/rate-limited, falling back...")
                    print(f"{entry['provider'].name} Last error:", e)
                else:
                    print(f"{entry['provider'].name} failed (non-rate-limit): {e}")
        raise RuntimeError(f"All LLM providers exhausted. Last error: {last_error}")