"""Offline evaluator coverage on invented data (mocks/*_synthetic.json, regime SYNTH).

Every expected status below is worked out by hand from the numbers in the mock files: boundary values,
unit conversion (m, ft, ft2), strict vs inclusive operators, applicability by ship type / length / GT,
low confidence, non-numeric and missing properties, and the qualitative path with a fake judge.
"""
import json
from pathlib import Path

from app.check.evaluator import evaluate_all
from app.check.llm_judge import JudgeVerdict
from app.check.run import format_table, main, run_check
from app.models import DesignFacts, Rule, Status
from app.providers.llm import LLMProvider

MOCKS = Path(__file__).resolve().parents[1] / "mocks"
P, F, N, NA = Status.passed, Status.failed, Status.needs_review, Status.not_applicable


def load():
    rules = [Rule.model_validate(r) for r in json.loads((MOCKS / "rules_synthetic.json").read_text(encoding="utf-8"))]
    facts = DesignFacts.model_validate_json((MOCKS / "facts_synthetic.json").read_text(encoding="utf-8"))
    return rules, facts


def by_rule(findings):
    out = {}
    for f in findings:
        out.setdefault(f.rule_id, {})[f.element_id or "-"] = f
    return out


EXPECTED = {
    "SYNTH-1": {"D-1": P, "D-2": F, "D-3": N},     # 800 mm inclusive; D-3 low confidence
    "SYNTH-2": {"D-1": F, "D-2": F, "D-3": N},     # 0.9 m -> 900 mm
    "SYNTH-3": {"K-1": P, "K-2": F},               # 5 ft == 1524 mm exactly
    "SYNTH-4": {"B-1": P, "B-2": F},               # 8 m2
    "SYNTH-5": {"B-1": P, "B-2": P},               # 86 ft2 = 7.9896 m2, so 7.99 passes
    "SYNTH-6": {"-": P},                           # two stairways
    "SYNTH-7": {"-": N},                           # not_exists, none read from a drawing: absence is not proof (see tests/test_absence_coverage.py)
    "SYNTH-8": {"D-1": F, "D-2": P, "D-3": N},     # strict ">": 2000 fails, 2001 passes, missing -> review
    "SYNTH-10": {"-": NA},                         # needs LOA >= 100, ship is 60
    "SYNTH-11": {"-": NA},                         # cargo only, ship is passenger
    "SYNTH-12": {"-": N},                          # GT unknown -> applicability unknown, never guessed
    "SYNTH-13": {"-": N},                          # qualitative, fake judge declines
    "SYNTH-14": {"D-1": N, "D-2": N, "D-3": N},    # "A-60" is text, others missing
}


class DecliningJudge(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        self.calls += 1
        return JudgeVerdict(status="needs_review", reasoning="cannot decide", evidence_ids=[])


def test_synthetic_expected_statuses():
    rules, facts = load()
    judge = DecliningJudge()
    got = by_rule(evaluate_all(rules, facts, judge))
    assert {rid: {k: f.status for k, f in v.items()} for rid, v in got.items()} == EXPECTED
    assert judge.calls == 1


def test_non_numeric_property_is_reported_as_such_not_as_missing():
    rules, facts = load()
    got = by_rule(evaluate_all(rules, facts, DecliningJudge()))["SYNTH-14"]
    assert "present but not a number" in got["D-1"].message and "'A-60'" in got["D-1"].message
    assert "not found in design" in got["D-2"].message


def test_low_confidence_message_formats_numbers_consistently():
    rules, facts = load()
    msg = by_rule(evaluate_all(rules, facts, DecliningJudge()))["SYNTH-1"]["D-3"].message
    assert "clear_width=1000 mm" in msg and "1000.0" not in msg


def test_place_used_as_target_is_called_out():
    rules, facts = load()
    rule = rules[0].model_copy(update={"id": "X", "target": "escape"})   # 'escape' is a space_type, not an element
    [f] = evaluate_all([rule], facts)
    assert f.status == N and "never match" in f.message and "needs review" in f.message


def test_no_place_hint_when_target_simply_absent():
    rules, facts = load()
    rule = rules[0].model_copy(update={"id": "X", "target": "lifeboat"})
    [f] = evaluate_all([rule], facts)
    assert f.status == N and "never match" not in f.message


def test_percent_and_other_units_are_compared_as_written():
    rules, facts = load()
    rule = rules[0].model_copy(update={"id": "X", "target": "corridor", "parameter": "width", "operator": "<=",
                                       "value": 1523.0, "unit": "%"})   # unknown unit: no conversion
    got = {f.element_id: f.status for f in evaluate_all([rule], facts)}
    assert got == {"K-1": F, "K-2": P}


# ---- CLI -----------------------------------------------------------------------------------------

def test_run_check_is_offline_and_orders_failures_first():
    rules, facts = load()
    findings = run_check(rules, facts)                      # no LLM
    assert findings[0].status == F and findings[-1].status == NA
    qual = [f for f in findings if f.rule_id == "SYNTH-13"][0]
    assert qual.status == N and "unavailable" in qual.message


def test_table_has_counts_and_sources():
    rules, facts = load()
    text = format_table(run_check(rules, facts), rules)
    assert "fail: 6" in text and "SYNTH p1 S3" in text


def test_cli_exit_code_and_status_filter(capsys):
    rc = main([str(MOCKS / "facts_synthetic.json"), "--rules", str(MOCKS / "rules_synthetic.json"),
               "--status", "fail", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and {f["status"] for f in out} == {"fail"} and len(out) == 6


def test_cli_exit_zero_without_failures(capsys):
    rc = main([str(MOCKS / "facts_synthetic.json"), "--rules", str(MOCKS / "rules_synthetic.json"),
               "--status", "pass,not_applicable"])
    out = capsys.readouterr().out
    assert rc == 0 and "fail: 0" in out and "needs_review: 0" in out
