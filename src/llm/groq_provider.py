# src/llm/groq_provider.py
import json
from src.llm.openai_strict_schema import make_strict_schema
from groq import Groq
from src.llm.base import BaseLLMProvider, LLMProviderError

class GroqProvider(BaseLLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model_name: str = "openai/gpt-oss-120b"):
        self.client = Groq(api_key=api_key, timeout=60)
        self.model_name = model_name
        self.name = f"groq:{model_name}"

    def generate_structured(self, system_prompt, user_prompt, response_schema):
        schema = make_strict_schema(response_schema.model_json_schema())
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": response_schema.__name__,"strict": True, "schema": schema},
                },
            )
        except Exception as e:
            raise LLMProviderError(str(e), is_rate_limit=self._is_rate_limit(e)) from e
        return response_schema.model_validate(json.loads(response.choices[0].message.content))