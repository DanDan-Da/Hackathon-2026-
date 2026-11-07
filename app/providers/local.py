"""Local / on-prem provider: any OpenAI-compatible server (vLLM, Ollama, LM Studio).

Example (NVIDIA GPU):
  vllm serve Qwen/Qwen2.5-VL-32B-Instruct --port 8001 --max-model-len 32768
"""
from __future__ import annotations

import base64

from openai import OpenAI

from app.config import settings
from app.providers.llm import LLMProvider, T


class LocalProvider(LLMProvider):
    def __init__(self):
        self.client = OpenAI(base_url=settings.local_base_url, api_key="local")
        self.model = settings.local_model

    def complete(self, system: str, prompt: str) -> str:
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return r.choices[0].message.content or ""

    def complete_structured(self, system: str, prompt: str, schema: type[T],
                            images_png: list[bytes] | None = None) -> T:
        content: list[dict] = [
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()}}
            for img in images_png or []
        ]
        content.append({"type": "text", "text": prompt})
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            # vLLM guided decoding: output is forced to match the JSON schema
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema.__name__,
                                             "schema": schema.model_json_schema()}},
        )
        return schema.model_validate_json(r.choices[0].message.content or "{}")
