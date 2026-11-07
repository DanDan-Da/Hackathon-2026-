from __future__ import annotations

import base64

import anthropic

from app.config import settings
from app.providers.llm import LLMProvider, LLMRefusal, T


def _content(prompt: str, images_png: list[bytes] | None) -> list[dict]:
    blocks: list[dict] = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.b64encode(img).decode()}}
        for img in images_png or []
    ]
    blocks.append({"type": "text", "text": prompt})
    return blocks


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str | None = None, effort: str = "high"):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = model or settings.claude_model
        self.effort = effort

    def complete(self, system: str, prompt: str) -> str:
        with self.client.messages.stream(
            model=self.model,
            max_tokens=64000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise LLMRefusal(str(msg.stop_details))
        return "".join(b.text for b in msg.content if b.type == "text")

    def complete_structured(self, system: str, prompt: str, schema: type[T],
                            images_png: list[bytes] | None = None) -> T:
        msg = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            messages=[{"role": "user", "content": _content(prompt, images_png)}],
            output_format=schema,
        )
        if msg.stop_reason == "refusal":
            raise LLMRefusal(str(msg.stop_details))
        if msg.parsed_output is None:
            raise ValueError(f"No structured output (stop_reason={msg.stop_reason})")
        return msg.parsed_output
