"""D6: static UI, /ui/demo, /ui/check and /evidence/crop."""
import json
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import settings

MOCKS = Path(__file__).parent.parent / "mocks"
WEB = Path(__file__).parent.parent / "web"
client = TestClient(app)


def test_index_served_and_api_routes_intact():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert client.get("/health").json()["ok"] is True
    assert client.get("/openapi.json").status_code == 200


def test_static_assets_have_no_remote_urls():
    files = [f for f in WEB.glob("*") if f.suffix in {".html", ".js", ".css"}]
    assert files
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f


def test_demo_returns_mock_facts_and_rules():
    d = client.get("/ui/demo").json()
    assert d["facts"] == json.loads((MOCKS / "facts_violation.json").read_text())
    assert d["rules"] == json.loads((MOCKS / "rules.json").read_text())


def test_ui_check_with_inline_rules():
    d = client.get("/ui/demo").json()
    r = client.post("/ui/check", json=d)
    assert r.status_code == 200
    statuses = {(f["rule_id"], f["element_id"]): f["status"] for f in r.json()}
    assert statuses[("PVAG-door-clear-width", "D-101")] == "fail"
    assert statuses[("PVAG-door-clear-width", "D-102")] == "pass"


def test_ui_check_without_rules_uses_server_rules(tmp_path, monkeypatch):
    p = tmp_path / "rules.json"
    p.write_text((MOCKS / "rules.json").read_text())
    monkeypatch.setattr(settings, "compiled_rules", p)
    facts = json.loads((MOCKS / "facts_violation.json").read_text())
    assert len(client.post("/ui/check", json={"facts": facts}).json()) > 0


def test_ui_check_no_server_rules_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "compiled_rules", tmp_path / "none.json")
    facts = json.loads((MOCKS / "facts_violation.json").read_text())
    assert client.post("/ui/check", json={"facts": facts}).status_code == 404


def test_ui_check_rejects_invalid_facts():
    assert client.post("/ui/check", json={"facts": {"nope": 1}}).status_code == 422


@pytest.fixture
def design(tmp_path, monkeypatch):
    root = tmp_path / "designs"
    (root / "p1").mkdir(parents=True)
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "GA test")
    doc.save(root / "p1" / "ga.pdf")
    (tmp_path / "secret.pdf").write_bytes((root / "p1" / "ga.pdf").read_bytes())
    monkeypatch.setattr(settings, "designs_dir", root)
    return root


def test_crop_renders_png(design):
    r = client.get("/evidence/crop", params={"file": "p1/ga.pdf", "page": 1, "bbox": "40,80,200,120"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("bad", ["../secret.pdf", "/etc/passwd", "p1/../../secret.pdf", "..%2Fsecret.pdf"])
def test_crop_rejects_traversal(design, bad):
    r = client.get("/evidence/crop", params={"file": bad, "page": 1})
    assert r.status_code in (400, 404)
    assert r.headers["content-type"].startswith("application/json")


def test_crop_rejects_bad_input(design):
    (design / "p1" / "a.txt").write_text("x")
    assert client.get("/evidence/crop", params={"file": "p1/a.txt", "page": 1}).status_code == 400
    assert client.get("/evidence/crop", params={"file": "p1/ga.pdf", "page": 9}).status_code == 404
    assert client.get("/evidence/crop", params={"file": "p1/ga.pdf", "page": 1, "bbox": "1,2"}).status_code == 400
    assert client.get("/evidence/crop", params={"file": "p1/missing.pdf", "page": 1}).status_code == 404
