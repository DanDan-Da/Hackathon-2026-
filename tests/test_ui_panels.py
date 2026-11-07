"""D: /ui/facts, /ui/evidence-available and /ui/regulations (upload) for the UI panels."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import settings

MOCKS = Path(__file__).parent.parent / "mocks"
WEB = Path(__file__).parent.parent / "web"
client = TestClient(app)
FACTS_TEXT = (MOCKS / "facts_violation.json").read_text()


@pytest.fixture
def designs(tmp_path, monkeypatch):
    root = tmp_path / "designs"
    (root / "p1").mkdir(parents=True)
    (root / "p1" / "facts.json").write_text(FACTS_TEXT)
    (root / "p1" / "notfacts.json").write_text('{"nope": 1}')
    (root / "p1" / "broken.json").write_text("{")
    (root / "p1" / "ga.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "secret.json").write_text(FACTS_TEXT)
    monkeypatch.setattr(settings, "designs_dir", root)
    return root


def test_facts_lists_only_valid_design_facts(designs):
    assert client.get("/ui/facts").json() == [{"name": "p1/facts.json", "project": json.loads(FACTS_TEXT)["project"]}]


def test_facts_missing_designs_dir_is_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "designs_dir", tmp_path / "nope")
    assert client.get("/ui/facts").json() == []


def test_facts_load_by_name(designs):
    r = client.get("/ui/facts/load", params={"name": "p1/facts.json"})
    assert r.status_code == 200 and r.json() == json.loads(FACTS_TEXT)


@pytest.mark.parametrize("bad", ["../secret.json", "/etc/passwd", "p1/../../secret.json", "p1/notfacts.json",
                                 "p1/broken.json", "p1/ga.pdf", "p1/none.json", "p1\x00.json"])
def test_facts_load_rejects_bad_names(designs, bad):
    assert client.get("/ui/facts/load", params={"name": bad}).status_code in (400, 404, 422)


def test_evidence_available(designs):
    def f(p):
        return client.get("/ui/evidence-available", params={"file": p}).json()["available"]
    assert f("p1/ga.pdf") is True
    assert f("p1/missing.pdf") is False
    assert f("../secret.json") is False
    assert f("/etc/passwd") is False


@pytest.fixture
def rules_dir(tmp_path, monkeypatch):
    root = tmp_path / "rules"
    monkeypatch.setattr(settings, "rules_dir", root)
    return root


def up(regime, filename, data=b"hello"):
    return client.post("/ui/regulations", params={"regime": regime, "filename": filename}, content=data)


def test_upload_saves_under_regime_folder(rules_dir):
    r = up("MyRegime", "part1.txt", b"abc")
    assert r.status_code == 200
    assert (rules_dir / "MyRegime" / "part1.txt").read_bytes() == b"abc"
    assert r.json()["saved"] == "MyRegime/part1.txt"


def test_upload_does_not_overwrite(rules_dir):
    assert up("R", "a.md").status_code == 200
    assert up("R", "a.md", b"new").status_code == 409
    assert (rules_dir / "R" / "a.md").read_bytes() == b"hello"


@pytest.mark.parametrize("regime", ["..", "../x", "a/b", ".hidden", "a\\b", "a" * 80, "x\x00", "has space"])
def test_upload_rejects_bad_regime(rules_dir, regime):
    assert up(regime, "a.txt").status_code in (400, 422)
    assert not rules_dir.exists() or not any(rules_dir.rglob("*"))


@pytest.mark.parametrize("name", ["../a.txt", "a/b.txt", "..", "a.exe", "a", ".txt", "a.txt.sh", "a\\b.txt",
                                  "/etc/x.txt", "a\x00.txt"])
def test_upload_rejects_bad_filename(rules_dir, name):
    assert up("R", name).status_code in (400, 422)
    assert not rules_dir.exists() or not any(p.is_file() for p in rules_dir.rglob("*"))


def test_upload_rejects_empty_and_oversized(rules_dir, monkeypatch):
    assert up("R", "a.txt", b"").status_code == 400
    from app.api import regulations
    monkeypatch.setattr(regulations, "MAX_BYTES", 5)
    assert up("R", "b.txt", b"123456").status_code == 413


def test_static_panels_present():
    html = (WEB / "index.html").read_text()
    for i in ("tab-rules", "tab-ask", "tab-add", "facts-pick"):
        assert f'id="{i}"' in html
