"""GeminiProvider with a fake google-genai client: no network, no API key needed."""
from types import SimpleNamespace

import pytest
from google.genai import errors, types
from pydantic import BaseModel

from app.providers.llm import LLMQuotaExhausted, LLMRefusal
from app.providers.gemini import MAX_TRIES, GeminiProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"fake"


class Answer(BaseModel):
    label: str
    width_text: str


class FakeModels:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(text):
    return SimpleNamespace(text=text, prompt_feedback=None, candidates=[SimpleNamespace(finish_reason="STOP")])


def provider(*replies, sleeps=None):
    fake = SimpleNamespace(models=FakeModels(replies))
    p = GeminiProvider(client=fake, model="gemini-test", sleep=(sleeps.append if sleeps is not None else lambda s: None))
    return p, fake.models


def rate_limited(delay="7s"):
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                                              "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                                           "retryDelay": delay}]}})


def test_structured_request_has_image_schema_and_system():
    p, models = provider(reply('{"label": "CABIN 101", "width_text": "800"}'))
    out = p.complete_structured("SYS", "read this tile", Answer, images_png=[PNG])
    assert out == Answer(label="CABIN 101", width_text="800")
    [call] = models.calls
    assert call.model == "gemini-test"
    image, text = call.contents
    assert image.inline_data.data == PNG and image.inline_data.mime_type == "image/png"
    assert text == "read this tile"
    assert call.config.system_instruction == "SYS"
    assert call.config.response_mime_type == "application/json"
    assert call.config.response_schema is Answer
    assert call.config.temperature == 0
    assert call.config.media_resolution == types.MediaResolution.MEDIA_RESOLUTION_HIGH


def test_rate_limit_is_retried_using_server_delay():
    sleeps = []
    p, models = provider(rate_limited("7s"), reply('{"label": "A", "width_text": "1"}'), sleeps=sleeps)
    assert p.complete_structured("S", "P", Answer).label == "A"
    assert len(models.calls) == 2
    assert sleeps and sleeps[0] >= 7


def test_server_error_is_retried():
    p, models = provider(errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}}),
                         reply('{"label": "A", "width_text": "1"}'))
    assert p.complete_structured("S", "P", Answer).label == "A"
    assert len(models.calls) == 2


def test_gives_up_after_max_tries():
    p, models = provider(*[rate_limited("1s")] * MAX_TRIES)
    with pytest.raises(errors.ClientError):
        p.complete_structured("S", "P", Answer)
    assert len(models.calls) == MAX_TRIES


def test_client_error_other_than_429_is_not_retried():
    p, models = provider(errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}}))
    with pytest.raises(errors.ClientError):
        p.complete_structured("S", "P", Answer)
    assert len(models.calls) == 1


def test_empty_or_blocked_reply_raises_refusal():
    p, _ = provider(SimpleNamespace(text=None, prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
                                    candidates=[]))
    with pytest.raises(LLMRefusal):
        p.complete_structured("S", "P", Answer)


def test_invalid_json_raises_instead_of_guessing():
    p, _ = provider(reply('{"label": "A"}'))      # missing required field
    with pytest.raises(ValueError):
        p.complete_structured("S", "P", Answer)


def test_complete_returns_text():
    p, models = provider(reply("hello"))
    assert p.complete("S", "P") == "hello"
    assert models.calls[0].config.response_mime_type is None


def test_get_llm_selects_gemini(monkeypatch):
    from app.config import settings
    from app.providers import llm
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    assert isinstance(llm.get_llm(), GeminiProvider)


def test_max_rpm_spaces_calls_so_the_free_tier_limit_is_never_hit():
    now = [100.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        now[0] += s

    fake = SimpleNamespace(models=FakeModels([reply("a"), reply("b"), reply("c")]))
    p = GeminiProvider(client=fake, model="m", sleep=sleep, max_rpm=5, clock=lambda: now[0])
    for _ in range(3):
        p.complete("sys", "hi")
    # 5 requests/minute = one every 12 s: no wait before the first call, then 12 s between calls
    assert sleeps == pytest.approx([12.0, 12.0])
    assert len(fake.models.calls) == 3


def test_no_pacing_by_default():
    sleeps = []
    fake = SimpleNamespace(models=FakeModels([reply("a"), reply("b")]))
    p = GeminiProvider(client=fake, model="m", sleep=sleeps.append, max_rpm=0)
    p.complete("s", "x"); p.complete("s", "x")
    assert sleeps == []


def daily_quota_exhausted(delay="72209s"):
    return errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
                                              "details": [
                                                  {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                                   "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                                                   "quotaValue": "20"}]},
                                                  {"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                                   "retryDelay": delay}]}})


def test_daily_quota_fails_fast_instead_of_retrying_for_hours():
    sleeps = []
    p, models = provider(daily_quota_exhausted(), reply("never reached"), sleeps=sleeps)
    with pytest.raises(LLMQuotaExhausted) as exc:
        p.complete("S", "P")
    assert len(models.calls) == 1 and sleeps == []
    assert "20" in str(exc.value) and "20h" in str(exc.value)     # says the limit and when it resets


def test_json_wrapped_in_a_markdown_fence_is_accepted():
    # Gemma models have no strict JSON mode and sometimes wrap the answer in a code fence
    fenced = '```json\n{"label": "MESS", "width_text": "83"}\n```\n'
    p, _ = provider(reply(fenced))
    assert p.complete_structured("S", "P", Answer) == Answer(label="MESS", width_text="83")


def test_text_around_a_json_object_is_not_guessed_at():
    p, _ = provider(reply('Sure! {"label": "MESS", "width_text": "83"}'))
    with pytest.raises(Exception):
        p.complete_structured("S", "P", Answer)
