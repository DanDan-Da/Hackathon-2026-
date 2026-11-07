import json
from pathlib import Path

from app.check.evaluator import evaluate_all
from app.check.units import to_base
from app.models import DesignFacts, Rule, Status

MOCKS = Path(__file__).parent.parent / "mocks"


def load():
    rules = [Rule.model_validate(r) for r in json.loads((MOCKS / "rules.json").read_text())]
    facts = DesignFacts.model_validate_json((MOCKS / "facts_violation.json").read_text())
    return rules, facts


def by(findings, rule_id, element_id=None):
    return [f for f in findings if f.rule_id == rule_id and (element_id is None or f.element_id == element_id)]


def test_units():
    assert to_base(32, "in") == (812.8, "mm")
    assert to_base(1.2, "m") == (1200.0, "mm")


def test_seeded_violations_detected():
    rules, facts = load()
    f = evaluate_all(rules, facts)
    assert by(f, "PVAG-door-clear-width", "D-101")[0].status == Status.failed   # 760 < 812.8
    assert by(f, "PVAG-door-clear-width", "D-102")[0].status == Status.passed   # 850 ok
    assert by(f, "PVAG-route-width", "C-4A")[0].status == Status.passed         # 1100 >= 914.4
    assert by(f, "SOLAS-escape-count")[0].status == Status.failed               # 1 < 2


def test_every_finding_cites_rule_and_evidence():
    rules, facts = load()
    for f in evaluate_all(rules, facts):
        assert f.rule_source.quote and f.rule_source.regime
        if f.status in (Status.passed, Status.failed):
            assert f.evidence, f"{f.rule_id} has no design evidence"


def test_not_applicable_for_cargo_ship():
    rules, facts = load()
    facts.particulars.ship_type = "cargo"
    assert by(evaluate_all(rules, facts), "PVAG-door-clear-width")[0].status == Status.not_applicable


def test_unknown_particulars_needs_review():
    rules, facts = load()
    facts.particulars.ship_type = None
    assert by(evaluate_all(rules, facts), "PVAG-door-clear-width")[0].status == Status.needs_review


def test_low_confidence_needs_review():
    rules, facts = load()
    facts.elements[0].provenance.confidence = 0.4
    assert by(evaluate_all(rules, facts), "PVAG-door-clear-width", "D-101")[0].status == Status.needs_review
