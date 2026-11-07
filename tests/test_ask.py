"""L7: /ask with a fake embedder and a fake LLM (no model download, no API)."""
import pytest

pytest.importorskip("qdrant_client")

from fastapi.testclient import TestClient

from app.api.main import app
from app.check import ask as ask_mod
from app.check.ask import AnswerDraft, DraftCitation, ask
from app.ingest.index import RuleIndex
from app.ingest.rules_loader import Chunk
from app.providers.llm import LLMProvider
from tests.test_index import CHUNKS, FakeEmbedder


class FakeLLM(LLMProvider):
    def __init__(self, draft=None, fail=False):
        self.draft, self.fail, self.prompts = draft, fail, []

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("no api key")
        return self.draft


@pytest.fixture
def index(tmp_path):
    idx = RuleIndex(path=tmp_path / "idx", embedder=FakeEmbedder())
    idx.rebuild(CHUNKS)
    yield idx
    idx.close()


GOOD = AnswerDraft(answer="Door clear width must be at least 800 mm.",
                   citations=[DraftCitation(passage=1, quote="Door clear width shall be at least 800 mm.")])


def test_answer_with_verified_citation(index):
    out = ask("what is the door clear width", index, llm=FakeLLM(GOOD), k=1)
    assert out.status == "answered" and "800 mm" in out.answer
    c = out.citations[0]
    assert (c.regime, c.document, c.page, c.clause) == ("REG_A", "doors.pdf", 3, "4.2.1")
    assert c.quote == "Door clear width shall be at least 800 mm."


def test_prompt_contains_passage_and_its_source(index):
    llm = FakeLLM(GOOD)
    ask("door clear width", index, llm=llm, k=1)
    assert "[1] (REG_A | doors.pdf | page 3 | clause 4.2.1)" in llm.prompts[0]


def test_invented_quote_withholds_answer(index):
    bad = AnswerDraft(answer="Doors must be 900 mm.", citations=[DraftCitation(passage=1, quote="Doors must be 900 mm.")])
    out = ask("door clear width", index, llm=FakeLLM(bad), k=1)
    assert out.status == "needs_review" and out.answer is None and out.passages


def test_unknown_passage_number_dropped(index):
    bad = AnswerDraft(answer="x", citations=[DraftCitation(passage=9, quote="Door clear width")])
    assert ask("door clear width", index, llm=FakeLLM(bad), k=1).status == "needs_review"


def test_answer_without_citations_withheld(index):
    out = ask("door clear width", index, llm=FakeLLM(AnswerDraft(answer="800 mm")), k=1)
    assert out.status == "needs_review" and out.answer is None


def test_llm_failure_still_returns_passages(index):
    out = ask("ramp slope", index, llm=FakeLLM(fail=True), k=1)
    assert out.status == "llm_unavailable" and out.answer is None
    assert out.passages[0].document == "ramps.pdf" and "1:12" in out.passages[0].quote


def test_empty_index_is_no_sources(tmp_path):
    idx = RuleIndex(path=tmp_path / "empty", embedder=FakeEmbedder())
    llm = FakeLLM(GOOD)
    out = ask("anything", idx, llm=llm)
    idx.close()
    assert out.status == "no_sources" and llm.prompts == []      # no LLM call without sources


def test_regime_filter_limits_retrieval(index):
    out = ask("doors", index, regime="REG_B", llm=FakeLLM(fail=True), k=5)
    assert {p.regime for p in out.passages} == {"REG_B"}


def test_route_returns_verified_answer(tmp_path, monkeypatch):
    idx = RuleIndex(path=tmp_path / "idx", embedder=FakeEmbedder())
    idx.rebuild(CHUNKS)
    monkeypatch.setattr(ask_mod, "open_index", lambda: idx)
    monkeypatch.setattr(ask_mod, "get_llm", lambda: FakeLLM(GOOD))
    r = TestClient(app).post("/ask", json={"question": "door clear width", "k": 1})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    assert r.json()["citations"][0]["page"] == 3


def test_route_503_without_rag_extra(monkeypatch):
    def boom():
        raise ImportError("sentence_transformers")
    monkeypatch.setattr(ask_mod, "open_index", boom)
    r = TestClient(app).post("/ask", json={"question": "door width"})
    assert r.status_code == 503 and "rag" in r.json()["detail"]


def test_route_rejects_short_question():
    assert TestClient(app).post("/ask", json={"question": "x"}).status_code == 422
