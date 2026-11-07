"""L4: rule review endpoints, against a temp copy of mocks/rules.json."""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import main as api
from app.config import settings
from app.models import Rule

MOCK = Path(__file__).parent.parent / "mocks" / "rules.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "compiled" / "rules.json"
    path.parent.mkdir()
    shutil.copy(MOCK, path)
    monkeypatch.setattr(settings, "compiled_rules", path)
    return TestClient(api.app)


def first_id():
    return json.loads(MOCK.read_text(encoding="utf-8"))[0]["id"]


def test_list_rules_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "compiled_rules", tmp_path / "none.json")
    assert TestClient(api.app).get("/rules").status_code == 404


def test_patch_edits_value_and_marks_reviewed_and_persists(client):
    rid = first_id()
    r = client.patch(f"/rules/{rid}", json={"value": 36, "unit": "in"})
    assert r.status_code == 200
    assert r.json()["value"] == 36 and r.json()["reviewed"] is True
    again = {x["id"]: x for x in client.get("/rules").json()}[rid]
    assert again["value"] == 36 and again["reviewed"] is True


def test_patch_cannot_touch_source_or_id(client):
    rid = first_id()
    assert client.patch(f"/rules/{rid}", json={"source": {}}).status_code == 422
    assert client.patch(f"/rules/{rid}", json={"id": "x"}).status_code == 422


def test_patch_explicit_reviewed_false_and_null_clears_field(client):
    rid = first_id()
    r = client.patch(f"/rules/{rid}", json={"unit": None, "reviewed": False}).json()
    assert r["unit"] is None and r["reviewed"] is False


def test_patch_invalid_value_422_and_unknown_404(client):
    rid = first_id()
    assert client.patch(f"/rules/{rid}", json={"operator": "bogus"}).status_code == 422
    assert client.patch("/rules/nope", json={"value": 1}).status_code == 404
    unchanged = {x["id"]: x for x in client.get("/rules").json()}[rid]
    assert unchanged["operator"] == ">=" and unchanged["reviewed"] is False   # failed patch wrote nothing


def test_ingest_runs_compiler_and_reports_counts(client, monkeypatch):
    rules = [Rule.model_validate(r) for r in json.loads(MOCK.read_text(encoding="utf-8"))]
    seen = {}

    def fake_main(regime=None):
        seen["regime"] = regime
        return rules
    monkeypatch.setattr(api.rule_compiler, "main", fake_main)
    r = client.post("/ingest/rules", params={"regime": "PVAG"})
    assert r.status_code == 200 and r.json() == {"rules": len(rules), "reviewed": 0}
    assert seen["regime"] == "PVAG"
