# src/llm/gemini_provider.py
import json
from google import genai
from google.genai import types
from src.llm.base import BaseLLMProvider, LLMProviderError


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def generate_structured(self, system_prompt, user_prompt, response_schema):
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0,
                ),
            )
        except Exception as e:
            raise LLMProviderError(str(e), is_rate_limit=self._is_rate_limit(e)) from e
        return response_schema.model_validate(json.loads(response.text))

    def _is_rate_limit(self, e):
        msg = str(e).lower()
        return "429" in msg or "resource_exhausted" in msg or "quota" in msg