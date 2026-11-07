"""D: the endpoints the UI panels call, with fakes (no LLM, no index)."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import main as api
from app.check import ask as ask_module
from app.config import settings

MOCK = Path(__file__).parent.parent / "mocks" / "rules.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "compiled" / "rules.json"
    path.parent.mkdir()
    shutil.copy(MOCK, path)
    monkeypatch.setattr(settings, "compiled_rules", path)
    return TestClient(api.app, raise_server_exceptions=False)


def test_rules_panel_fields_are_present(client):
    r = client.get("/rules").json()
    assert r and {"id", "title", "source", "reviewed", "target", "parameter", "value", "unit"} <= set(r[0])
    assert {"regime", "quote"} <= set(r[0]["source"])


def test_rules_panel_edit_marks_reviewed(client):
    rid = client.get("/rules").json()[0]["id"]
    r = client.patch(f"/rules/{rid}", json={"target": "door", "parameter": "clear_width", "value": 900, "unit": "mm"})
    assert r.status_code == 200 and r.json()["reviewed"] is True


def test_ask_llm_unavailable_is_plain_json(client, monkeypatch):
    class Idx:
        def search(self, *a, **k):
            from app.ingest.index import Hit
            return [Hit(regime="R", document="d.pdf", page=1, clause="1", text="doors are 900 mm", score=1.0)]

        def close(self):
            pass

    class Boom:
        def complete_structured(self, *a, **k):
            raise RuntimeError("no key")

    monkeypatch.setattr(ask_module, "open_index", lambda: Idx())
    monkeypatch.setattr(ask_module, "get_llm", lambda: Boom())
    r = client.post("/ask", json={"question": "door width?"})
    assert r.status_code == 200 and r.json()["status"] == "llm_unavailable" and r.json()["passages"]


def test_ingest_failure_is_a_non_json_500_the_ui_must_cope_with(client, monkeypatch):
    from app.ingest import rule_compiler
    monkeypatch.setattr(rule_compiler, "main", lambda regime=None: (_ for _ in ()).throw(RuntimeError("quota")))
    r = client.post("/ingest/rules", params={"regime": "R"})
    assert r.status_code == 500
    assert len(client.get("/rules").json()) > 0      # existing rules kept
