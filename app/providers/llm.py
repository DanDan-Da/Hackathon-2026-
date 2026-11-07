"""Provider-neutral LLM interface. The rest of the app only talks to `get_llm()`.

Switch with LLM_PROVIDER=gemini | claude | local — same pipeline, so designs can stay on-prem.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMRefusal(RuntimeError):
    """The model declined or returned nothing usable. Callers turn this into needs_review."""


class LLMQuotaExhausted(RuntimeError):
    """A hard quota (e.g. free-tier requests per DAY) is used up. Retrying will not help; say when it resets."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, prompt: str) -> str: ...

    @abstractmethod
    def complete_structured(self, system: str, prompt: str, schema: type[T],
                            images_png: list[bytes] | None = None) -> T:
        """Return a validated instance of `schema`. Optional PNG images for drawings."""


def get_llm() -> LLMProvider:
    from app.config import settings
    if settings.llm_provider == "gemini":
        from app.providers.gemini import GeminiProvider
        return GeminiProvider()
    if settings.llm_provider == "local":
        from app.providers.local import LocalProvider
        return LocalProvider()
    from app.providers.claude import ClaudeProvider
    return ClaudeProvider()
