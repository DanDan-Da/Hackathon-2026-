"""D7: planted-violation eval. Uses the mock facts and rules; no network."""
import json
from pathlib import Path

import pytest

from eval.score_findings import Case, apply_mutations, load_cases, run_cases
from app.models import DesignFacts, Rule

ROOT = Path(__file__).resolve().parent.parent
FACTS = DesignFacts.model_validate_json((ROOT / "mocks/facts_violation.json").read_text())
RULES = [Rule.model_validate(r) for r in json.loads((ROOT / "mocks/rules.json").read_text())]
DOOR_RULE = "PVAG-door-clear-width"   # >= 32 in = 812.8 mm


def case(name, mutations, status, element="D-102", rule=DOOR_RULE):
    return Case.model_validate({"name": name, "mutations": mutations,
                                "expect": [{"rule_id": rule, "element_id": element, "status": status}]})


def set_width(element, mm):
    return {"op": "set_property", "element_id": element, "property": "clear_width", "value": mm}


def test_mutation_does_not_change_the_base_facts():
    out = apply_mutations(FACTS, [set_width("D-102", 1)])
    assert next(e for e in out.elements if e.id == "D-102").properties["clear_width"] == 1
    assert next(e for e in FACTS.elements if e.id == "D-102").properties["clear_width"] == 850


def test_unknown_element_in_a_mutation_is_an_error_not_silently_ignored():
    with pytest.raises(ValueError, match="D-999"):
        apply_mutations(FACTS, [set_width("D-999", 1)])


def test_planted_violation_is_caught():
    r = run_cases([case("narrow door", [set_width("D-102", 700)], "fail")], FACTS, RULES)
    assert r.correct == 1 and r.wrong == 0 and r.missed_violations == 0


def test_missed_violation_is_counted_separately_and_is_the_worst_error():
    # the evaluator says passed (850 >= 812.8) but the case claims it must fail
    r = run_cases([case("wrongly expected", [], "fail")], FACTS, RULES)
    assert r.wrong == 1 and r.missed_violations == 1


def test_false_alarm_is_counted_but_is_not_a_missed_violation():
    r = run_cases([case("expected pass but narrow", [set_width("D-102", 700)], "pass")], FACTS, RULES)
    assert r.wrong == 1 and r.false_alarms == 1 and r.missed_violations == 0


def test_low_confidence_must_not_pass_or_fail_silently():
    low = {"op": "set_confidence", "element_id": "D-102", "value": 0.3}
    r = run_cases([case("blurry read", [low], "needs_review")], FACTS, RULES)
    assert r.correct == 1


def test_boundary_value_exactly_at_the_limit_passes_and_just_under_fails():
    cases = [case("at limit", [set_width("D-102", 812.8)], "pass"),
             case("just under", [set_width("D-102", 812.7)], "fail")]
    r = run_cases(cases, FACTS, RULES)
    assert r.correct == 2


def test_removed_element_is_needs_review_not_a_pass():
    gone = [{"op": "remove_element", "element_id": "D-101"}, {"op": "remove_element", "element_id": "D-102"}]
    r = run_cases([Case.model_validate({"name": "no doors", "mutations": gone, "expect": [
        {"rule_id": DOOR_RULE, "element_id": None, "status": "needs_review"}]})], FACTS, RULES)
    assert r.correct == 1


def test_expected_finding_that_is_not_produced_counts_as_wrong():
    r = run_cases([case("wrong rule id", [], "fail", rule="NO-SUCH-RULE")], FACTS, RULES)
    assert r.wrong == 1 and r.missed_violations == 1   # a violation nobody reported is a missed violation


def test_load_cases_reads_a_json_file(tmp_path):
    p = tmp_path / "cases.json"
    p.write_text(json.dumps([{"name": "n", "mutations": [], "expect": [
        {"rule_id": DOOR_RULE, "element_id": "D-102", "status": "pass"}]}]))
    assert [c.name for c in load_cases(p)] == ["n"]


def test_shipped_planted_cases_have_no_missed_violations():
    r = run_cases(load_cases(ROOT / "eval/gold/findings/cases.json"), FACTS, RULES)
    assert r.results and r.missed_violations == 0 and r.wrong == 0
