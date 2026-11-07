"""Google Gemini provider (google-genai SDK).

Structured output: the pydantic schema is passed as response_schema and the reply is
validated with pydantic again, so a malformed answer raises instead of being half-used.
Free-tier keys hit per-minute limits: LLM_MAX_RPM paces requests up front, and 429/5xx are retried with backoff, honouring the
server's RetryInfo delay when it sends one.
"""
from __future__ import annotations

import random
import re
import threading
import time
from typing import Callable

from google import genai
from google.genai import errors, types

from app.config import settings
from app.providers.llm import LLMProvider, LLMQuotaExhausted, LLMRefusal, T

MAX_TRIES = 10
BASE_DELAY_S = 2.0
MAX_DELAY_S = 60.0


def _server_delay(err: errors.APIError) -> float | None:
    details = (err.details or {}).get("error", {}).get("details", []) if isinstance(err.details, dict) else []
    for d in details:
        if isinstance(d, dict) and (m := re.fullmatch(r"(\d+(?:\.\d+)?)s", str(d.get("retryDelay", "")))):
            return float(m[1])
    return None


def _daily_quota(err: errors.APIError) -> tuple[str, str] | None:
    """(limit, reset text) when a per-DAY quota is exhausted: waiting a minute will not fix that."""
    details = (err.details or {}).get("error", {}).get("details", []) if isinstance(err.details, dict) else []
    for d in details:
        for v in d.get("violations", []) if isinstance(d, dict) else []:
            if "PerDay" in str(v.get("quotaId", "")):
                secs = _server_delay(err)
                reset = f"{int(secs // 3600)}h{int(secs % 3600 // 60):02d}m" if secs else "tomorrow"
                return str(v.get("quotaValue", "?")), reset
    return None


_FENCE = re.compile(r"\A\s*```(?:json)?\s*\n(.*?)\n?```\s*\Z", re.S)


def _unfence(text: str) -> str:
    """Gemma models have no strict JSON mode and may wrap the answer in a ``` fence. Only a fence around the
    WHOLE reply is removed; prose around the JSON is not guessed at (validation then fails loudly)."""
    m = _FENCE.match(text)
    if m:
        return m[1]
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("```"):      # seen in real replies: lone closing fence
        return stripped[:-3].rstrip()
    return text


def _retryable(err: Exception) -> bool:
    return isinstance(err, errors.ServerError) or (isinstance(err, errors.ClientError) and err.code == 429)


class GeminiProvider(LLMProvider):
    def __init__(self, client=None, model: str | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_rpm: int | None = None, clock: Callable[[], float] = time.monotonic):
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self.model = model or settings.gemini_model
        self.sleep = sleep
        self.clock = clock
        rpm = settings.llm_max_rpm if max_rpm is None else max_rpm
        self._interval = 60.0 / rpm if rpm > 0 else 0.0   # 0 = no pacing
        self._next_slot = 0.0
        self._lock = threading.Lock()

    def _pace(self) -> None:
        """Reserve the next request slot (thread-safe) and wait for it, so a per-minute quota is never hit."""
        if not self._interval:
            return
        with self._lock:
            now = self.clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        if slot > now:
            self.sleep(slot - now)

    def _generate(self, contents: list, config: types.GenerateContentConfig):
        for attempt in range(1, MAX_TRIES + 1):
            self._pace()
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except errors.APIError as err:
                if isinstance(err, errors.ClientError) and err.code == 429 and (q := _daily_quota(err)):
                    raise LLMQuotaExhausted(
                        f"{self.model}: daily free-tier quota of {q[0]} requests is used up; resets in about {q[1]}. "
                        f"Use another model (GEMINI_MODEL) or wait.") from err
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
        return schema.model_validate_json(_unfence(self._text(self._generate(contents, config))))
