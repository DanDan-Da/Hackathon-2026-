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


def test_crop_accepts_the_path_exactly_as_the_extractor_stores_it(design, monkeypatch):
    # readers store provenance.file as given on their command line, e.g. "designs/p1/ga.pdf" (relative to cwd)
    monkeypatch.chdir(design.parent)
    monkeypatch.setattr(settings, "designs_dir", Path("designs"))
    r = client.get("/evidence/crop", params={"file": "designs/p1/ga.pdf", "page": 1, "bbox": "40,80,200,120"})
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_crop_accepts_an_absolute_path_inside_the_designs_folder(design):
    r = client.get("/evidence/crop", params={"file": str(design / "p1" / "ga.pdf"), "page": 1})
    assert r.status_code == 200


@pytest.mark.parametrize("bad", ["designs/../secret.pdf", "designs/p1/../../secret.pdf"])
def test_crop_still_rejects_traversal_in_the_extractor_form(design, monkeypatch, bad):
    monkeypatch.chdir(design.parent)
    monkeypatch.setattr(settings, "designs_dir", Path("designs"))
    assert client.get("/evidence/crop", params={"file": bad, "page": 1}).status_code in (400, 404)


# ---------- ship type stated by the user (drawings rarely print it, and we never infer it) ----------

def _unknown_ship_request(**extra):
    d = client.get("/ui/demo").json()
    d["facts"]["particulars"]["ship_type"] = None
    return {**d, **extra}


def _by_status(resp):
    """Statuses of the PVAG rules, the mock rules that only apply to passenger ships."""
    out = {}
    for f in resp.json():
        if f["rule_id"].startswith("PVAG"):
            out.setdefault(f["status"], []).append(f)
    return out


def test_unknown_ship_type_stays_needs_review():
    by = _by_status(client.post("/ui/check", json=_unknown_ship_request()))
    assert set(by) == {"needs_review"}


def test_user_stated_ship_type_lets_matching_rules_decide():
    by = _by_status(client.post("/ui/check", json=_unknown_ship_request(ship_type="passenger")))
    assert {f["element_id"] for f in by["fail"]} == {"D-101"}
    assert "pass" in by


def test_user_stated_ship_type_that_does_not_match_makes_rules_not_applicable():
    by = _by_status(client.post("/ui/check", json=_unknown_ship_request(ship_type="cargo")))
    assert set(by) == {"not_applicable"}


def test_blank_ship_type_is_ignored_not_treated_as_a_type():
    by = _by_status(client.post("/ui/check", json=_unknown_ship_request(ship_type="   ")))
    assert set(by) == {"needs_review"}


def test_user_stated_ship_type_is_recorded_as_manual_provenance():
    from app.api.ui import UICheckRequest, apply_ship_type
    req = UICheckRequest.model_validate(_unknown_ship_request(ship_type=" Passenger "))
    facts = apply_ship_type(req.facts, req.ship_type)
    assert facts.particulars.ship_type == "Passenger"
    assert facts.particulars.provenance[-1].method == "manual"
    assert req.facts.particulars.ship_type is None          # the request's own facts are not mutated


# ---------- remedy on findings, trust scoreboard ----------

def test_ui_check_adds_remedy_for_failed_numeric_findings_only():
    res = client.post("/ui/check", json=client.get("/ui/demo").json()).json()
    by = {(f["rule_id"], f["element_id"]): f for f in res}
    bad = by[("PVAG-door-clear-width", "D-101")]
    assert bad["remedy"]["text"].startswith("clear_width ") and "needs >=" in bad["remedy"]["text"]
    assert bad["remedy"]["delta"] > 0
    assert by[("PVAG-door-clear-width", "D-102")]["remedy"] is None
    assert {"rule_id", "status", "message", "rule_source", "evidence"} <= set(bad)   # existing shape intact


def test_trust_reports_live_planted_eval():
    t = client.get("/ui/trust").json()
    e = t["eval"]
    assert e["total"] > 0 and e["correct"] + e["wrong"] == e["total"]
    assert e["missed_violations"] == 0
    assert 0 < t["low_confidence_threshold"] < 1
    assert t["statement"] == "Anything not provable is marked needs review, never guessed."


def test_trust_eval_is_computed_not_hardcoded(tmp_path, monkeypatch):
    from app.api import ui
    cases = json.loads(Path(ui.EVAL_CASES).read_text())[:1]
    p = tmp_path / "cases.json"
    p.write_text(json.dumps(cases))
    monkeypatch.setattr(ui, "EVAL_CASES", p)
    assert client.get("/ui/trust").json()["eval"]["total"] == len(cases[0]["expect"])


def test_trust_eval_unavailable_is_null_not_an_error(tmp_path, monkeypatch):
    from app.api import ui
    monkeypatch.setattr(ui, "EVAL_CASES", tmp_path / "missing.json")
    t = client.get("/ui/trust")
    assert t.status_code == 200 and t.json()["eval"] is None
