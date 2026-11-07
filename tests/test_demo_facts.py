"""The two committed demo files (designs/demo/demo_*.json) give the results docs/DEMO.md promises.

Offline: no LLM (qualitative rules become needs_review), NPS rules from mocks/. The drawing PDF itself is
not in git, so these tests never need it.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from app.check.evaluator import evaluate_all
from app.models import DesignFacts, Rule, Status

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "designs" / "demo"
RULES = [Rule.model_validate(r) for r in json.loads((ROOT / "mocks" / "rules_nps_poc.json").read_text(encoding="utf-8"))]


def _counts(name: str) -> Counter:
    facts = DesignFacts.model_validate_json((DEMO / name).read_text(encoding="utf-8"))
    return Counter(f.status for f in evaluate_all(RULES, facts))


def test_real_drawing_has_no_fail():
    c = _counts("demo_real_drawing.json")
    assert c[Status.failed] == 0
    assert c[Status.needs_review] == 9 and c[Status.not_applicable] == 10


def test_planted_copy_adds_exactly_one_fail():
    real, planted = _counts("demo_real_drawing.json"), _counts("demo_planted_fail.json")
    assert planted[Status.failed] == 1
    assert planted[Status.passed] == real[Status.passed]


def test_planted_element_says_it_is_planted():
    real = json.loads((DEMO / "demo_real_drawing.json").read_text(encoding="utf-8"))
    planted = json.loads((DEMO / "demo_planted_fail.json").read_text(encoding="utf-8"))
    ids = {e["id"] for e in real["elements"]}
    extra = [e for e in planted["elements"] if e["id"] not in ids]
    assert len(extra) == 1 and extra[0]["name"].startswith("PLANTED TEST")
    assert extra[0]["provenance"]["method"] == "manual"
