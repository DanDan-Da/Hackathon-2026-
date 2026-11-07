"""Score the checker on planted violations.

    python -m eval.score_findings [--facts mocks/facts_violation.json]
                                  [--rules mocks/rules.json]
                                  [--cases eval/gold/findings/cases.json]

Each case changes the base facts (set a property, set a confidence, remove an element) and states the
status the checker must return for a given rule and element. The real evaluator is run, so this tests
the checking logic, not a copy of it.

Worst error: a MISSED VIOLATION, a case that must `fail` but came back `pass` or produced no finding.
A false alarm (`fail` where `pass` was expected) is wrong but safe; `needs_review` where `fail` was
expected counts as wrong, but is not a missed violation, because a human still looks at it.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.check.evaluator import evaluate_all
from app.check.run import OfflineLLM
from app.models import DesignFacts, Finding, Rule, Status

DEFAULT_CASES = Path("eval/gold/findings/cases.json")


class Mutation(BaseModel):
    op: Literal["set_property", "set_confidence", "remove_element", "set_particular"]
    element_id: str | None = None      # not used by set_particular (property names a ShipParticulars field)
    property: str | None = None
    value: float | str | None = None


class Expectation(BaseModel):
    rule_id: str
    element_id: str | None = None      # None for rules that report on the whole design (count rules)
    status: Status
    # Set when the semantics and the evaluator are known to disagree; the case stays WRONG but is listed apart.
    known_disagreement: str | None = None


class Case(BaseModel):
    name: str
    mutations: list[Mutation] = Field(default_factory=list)
    expect: list[Expectation]


class Result(BaseModel):
    case: str
    expectation: Expectation
    actual: Status | None
    ok: bool
    check_type: str = "unknown"


class Report(BaseModel):
    results: list[Result] = Field(default_factory=list)

    @property
    def correct(self) -> int:
        return sum(r.ok for r in self.results)

    @property
    def wrong(self) -> int:
        return len(self.results) - self.correct

    @property
    def missed_violations(self) -> int:
        return sum(not r.ok and r.expectation.status == Status.failed and r.actual != Status.needs_review
                   for r in self.results)

    @property
    def known_disagreements(self) -> int:
        return sum(not r.ok and r.expectation.known_disagreement is not None for r in self.results)

    def by_check_type(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.results:
            d = out.setdefault(r.check_type, {"total": 0, "correct": 0, "missed_violations": 0})
            d["total"] += 1
            d["correct"] += r.ok
            d["missed_violations"] += (not r.ok and r.expectation.status == Status.failed
                                       and r.actual != Status.needs_review)
        return out

    @property
    def false_alarms(self) -> int:
        return sum(not r.ok and r.actual == Status.failed and r.expectation.status == Status.passed
                   for r in self.results)


def load_cases(path: str | Path) -> list[Case]:
    return [Case.model_validate(c) for c in json.loads(Path(path).read_text(encoding="utf-8"))]


def apply_mutations(facts: DesignFacts, mutations: list[Mutation | dict]) -> DesignFacts:
    out = facts.model_copy(deep=True)
    for m in map(Mutation.model_validate, mutations):
        if m.op == "set_particular":
            if m.property not in type(out.particulars).model_fields:
                raise ValueError(f"unknown ship particular {m.property!r}")
            setattr(out.particulars, m.property, m.value)
            continue
        el = next((e for e in out.elements if e.id == m.element_id), None)
        if el is None:
            raise ValueError(f"mutation refers to unknown element {m.element_id!r}")
        if m.op == "remove_element":
            out.elements.remove(el)
        elif m.op == "set_property":
            el.properties[m.property or ""] = m.value
        else:
            el.provenance.confidence = float(m.value)
    return out


def _find(findings: list[Finding], exp: Expectation) -> Finding | None:
    return next((f for f in findings if f.rule_id == exp.rule_id and f.element_id == exp.element_id), None)


def run_cases(cases: list[Case], facts: DesignFacts, rules: list[Rule]) -> Report:
    report = Report()
    types = {r.id: r.check_type.value for r in rules}
    for c in cases:
        # qualitative rules are never sent to a real LLM here: they come out as needs_review
        findings = evaluate_all(rules, apply_mutations(facts, c.mutations), OfflineLLM())
        for exp in c.expect:
            hit = _find(findings, exp)
            actual = hit.status if hit else None
            report.results.append(Result(case=c.name, expectation=exp, actual=actual, ok=actual == exp.status,
                                         check_type=types.get(exp.rule_id, "unknown")))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the checker on planted violations")
    ap.add_argument("--facts", default="mocks/facts_violation.json")
    ap.add_argument("--rules", default="mocks/rules.json")
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    a = ap.parse_args()
    logging.getLogger("app.check.llm_judge").setLevel(logging.CRITICAL)   # offline refusals are expected here
    facts = DesignFacts.model_validate_json(Path(a.facts).read_text(encoding="utf-8"))
    rules = [Rule.model_validate(r) for r in json.loads(Path(a.rules).read_text(encoding="utf-8"))]
    report = run_cases(load_cases(a.cases), facts, rules)
    for r in report.results:
        mark = "ok   " if r.ok else "WRONG"
        print(f"{mark} {r.case:40} {r.expectation.rule_id}/{r.expectation.element_id}: "
              f"expected {r.expectation.status.value}, got {r.actual.value if r.actual else 'no finding'}")
    n = len(report.results)
    print(f"\nPlanted cases correct: {report.correct}/{n}")
    print(f"MISSED VIOLATIONS:     {report.missed_violations}   (must be 0)")
    print(f"False alarms:          {report.false_alarms}")
    print(f"Known disagreements:   {report.known_disagreements}   (wrong cases flagged in the case file)")
    print("\nBy rule type:")
    for t, d in sorted(report.by_check_type().items()):
        print(f"  {t:12} {d['correct']}/{d['total']} correct, missed violations {d['missed_violations']}")
    sys.exit(1 if report.missed_violations else 0)


if __name__ == "__main__":
    main()
