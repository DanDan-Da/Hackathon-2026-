"""Google Gemini provider (google-genai SDK).

Structured output: the pydantic schema is passed as response_schema and the reply is
validated with pydantic again, so a malformed answer raises instead of being half-used.
Free-tier keys hit per-minute limits: 429 and 5xx are retried with backoff, honouring the
server's RetryInfo delay when it sends one.
"""
from __future__ import annotations

import random
import re
import time
from typing import Callable

from google import genai
from google.genai import errors, types

from app.config import settings
from app.providers.llm import LLMProvider, LLMRefusal, T

MAX_TRIES = 6
BASE_DELAY_S = 2.0
MAX_DELAY_S = 60.0


def _server_delay(err: errors.APIError) -> float | None:
    details = (err.details or {}).get("error", {}).get("details", []) if isinstance(err.details, dict) else []
    for d in details:
        if isinstance(d, dict) and (m := re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))):
            return float(m[1])
    return None


def _retryable(err: Exception) -> bool:
    return isinstance(err, errors.ServerError) or (isinstance(err, errors.ClientError) and err.code == 429)


class GeminiProvider(LLMProvider):
    def __init__(self, client=None, model: str | None = None, sleep: Callable[[float], None] = time.sleep):
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self.model = model or settings.gemini_model
        self.sleep = sleep

    def _generate(self, contents: list, config: types.GenerateContentConfig):
        for attempt in range(1, MAX_TRIES + 1):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as err:
                if not _retryable(err) or attempt == MAX_TRIES:
                    raise
                backoff = min(MAX_DELAY_S, BASE_DELAY_S * 2 ** (attempt - 1))
                self.sleep(max(_server_delay(err) or 0.0, backoff) + random.uniform(0, 1))

    @staticmethod
    def _text(response) -> str:
        text = getattr(response, "text", None)
        if not text:
            feedback = getattr(response, "prompt_feedback", None)
            raise LLMRefusal(f"Gemini returned no text (block_reason={getattr(feedback, 'block_reason', None)})")
        return text

    def complete(self, system: str, prompt: str) -> str:
        config = types.GenerateContentConfig(system_instruction=system, temperature=0)
        return self._text(self._generate([prompt], config))

    def complete_structured(self, system: str, prompt: str, schema: type[T],
                            images_png: list[bytes] | None = None) -> T:
        contents = [types.Part.from_bytes(data=png, mime_type="image/png") for png in images_png or []]
        contents.append(prompt)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,   # keep small drawing text legible
        )
        return schema.model_validate_json(self._text(self._generate(contents, config)))
