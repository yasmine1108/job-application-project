# src/llm/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel


class LLMProviderError(Exception):
    def __init__(self, message: str, is_rate_limit: bool = False):
        super().__init__(message)
        self.is_rate_limit = is_rate_limit


class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    def generate_structured(self, system_prompt: str, user_prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        """Single generic entrypoint. Used for extraction AND matching —
        callers just pass a different schema/prompt."""
        ...