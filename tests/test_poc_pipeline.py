"""End-to-end, offline: real Gemini output (NPS accessible-vessel checklist) x mock design facts.

mocks/rules_nps_poc.json is the 19 rules Gemini extracted from page 1 of the checklist, with the
`target` / `space_types` of seven rules corrected by hand (the model had put the place into `target`).
mocks/facts_nps_poc.json is invented design data with known violations. No API is ever called: the
LLM is a fake, and the expected results below are computed by hand from the numbers in the mocks.
"""
import json
from pathlib import Path

from app.check.evaluator import evaluate_all
from app.check.llm_judge import JudgeVerdict
from app.models import DesignFacts, Rule, Status
from app.providers.llm import LLMProvider

MOCKS = Path(__file__).resolve().parents[1] / "mocks"


class FakeJudge(LLMProvider):
    def __init__(self):
        self.calls = 0

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        self.calls += 1
        return JudgeVerdict(status="needs_review", reasoning="fake judge: cannot decide", evidence_ids=[])


def run():
    rules = [Rule.model_validate(r) for r in json.loads((MOCKS / "rules_nps_poc.json").read_text(encoding="utf-8"))]
    facts = DesignFacts.model_validate_json((MOCKS / "facts_nps_poc.json").read_text(encoding="utf-8"))
    judge = FakeJudge()
    return rules, {r.id: [f for f in evaluate_all([r], facts, judge)] for r in rules}, judge


def statuses(findings):
    return {f.element_id or "-": f.status for f in findings}


def test_poc_rules_are_real_and_cite_their_source():
    rules, _, _ = run()
    assert len(rules) == 19
    for r in rules:
        assert r.source.regime == "NPS-Accessible-Vessels" and r.source.page == 1 and r.source.quote


def test_expected_findings_per_rule():
    rules, out, judge = run()
    P, F, N, NA = Status.passed, Status.failed, Status.needs_review, Status.not_applicable
    expect = {
        0: {"-": P},                                   # a corridor sits in the accessible route (rule target is now an element)
        1: {"C-1": F, "C-2": P, "C-3": N},             # width >= 60 in (1524 mm); C-3 low confidence
        2: {"C-1": P, "C-2": F, "C-3": N},             # headroom >= 80 in (2032 mm)
        4: {"W-1": F, "W-2": P},                       # slope <= 8.33 %
        5: {"-": P},                                   # handrail exists
        6: {"E-1": F},                                 # edge protection height <= 4 in
        7: {"E-1": P},                                 # edge protection width <= 2 in
        8: {"-": N},                                   # crew training: nothing in a drawing to judge
        9: {"-": NA}, 10: {"-": NA}, 11: {"-": NA}, 12: {"-": NA},   # tiers up to 100 persons end below the 120 on board
        13: {"-": F},                                  # 101-150 persons needs 5
        14: {"-": NA}, 15: {"-": NA}, 16: {"-": NA},   # tiers above 120 persons do not apply
        17: {"-": N},                                  # no entry_deck element extracted
        18: {"-": P},                                  # at least one deck
    }
    for i, want in expect.items():
        assert statuses(out[rules[i].id]) == want, (i, rules[i].title)


def test_every_finding_cites_rule_and_design_evidence():
    rules, out, _ = run()
    for r in rules:
        for f in out[r.id]:
            assert f.rule_source.quote and f.rule_source.document
            if f.status in (Status.passed, Status.failed) and r.check_type.value != "count":
                assert f.evidence and f.evidence[0].file == "ga.pdf"


def test_qualitative_rule_reaches_judge_only_when_elements_match():
    rules, out, judge = run()
    assert judge.calls == 1                            # only 'non-slip surface' (rule 3) has matching corridors
    assert all(f.status == Status.needs_review for f in out[rules[3].id])
