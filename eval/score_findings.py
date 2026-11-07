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
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.check.evaluator import evaluate_all
from app.models import DesignFacts, Finding, Rule, Status

DEFAULT_CASES = Path("eval/gold/findings/cases.json")


class Mutation(BaseModel):
    op: Literal["set_property", "set_confidence", "remove_element"]
    element_id: str
    property: str | None = None
    value: float | str | None = None


class Expectation(BaseModel):
    rule_id: str
    element_id: str | None = None      # None for rules that report on the whole design (count rules)
    status: Status


class Case(BaseModel):
    name: str
    mutations: list[Mutation] = Field(default_factory=list)
    expect: list[Expectation]


class Result(BaseModel):
    case: str
    expectation: Expectation
    actual: Status | None
    ok: bool


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
    def false_alarms(self) -> int:
        return sum(not r.ok and r.actual == Status.failed and r.expectation.status == Status.passed
                   for r in self.results)


def load_cases(path: str | Path) -> list[Case]:
    return [Case.model_validate(c) for c in json.loads(Path(path).read_text())]


def apply_mutations(facts: DesignFacts, mutations: list[Mutation | dict]) -> DesignFacts:
    out = facts.model_copy(deep=True)
    for m in map(Mutation.model_validate, mutations):
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
    for c in cases:
        findings = evaluate_all(rules, apply_mutations(facts, c.mutations))
        for exp in c.expect:
            hit = _find(findings, exp)
            actual = hit.status if hit else None
            report.results.append(Result(case=c.name, expectation=exp, actual=actual, ok=actual == exp.status))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the checker on planted violations")
    ap.add_argument("--facts", default="mocks/facts_violation.json")
    ap.add_argument("--rules", default="mocks/rules.json")
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    a = ap.parse_args()
    facts = DesignFacts.model_validate_json(Path(a.facts).read_text())
    rules = [Rule.model_validate(r) for r in json.loads(Path(a.rules).read_text())]
    report = run_cases(load_cases(a.cases), facts, rules)
    for r in report.results:
        mark = "ok   " if r.ok else "WRONG"
        print(f"{mark} {r.case:40} {r.expectation.rule_id}/{r.expectation.element_id}: "
              f"expected {r.expectation.status.value}, got {r.actual.value if r.actual else 'no finding'}")
    n = len(report.results)
    print(f"\nPlanted cases correct: {report.correct}/{n}")
    print(f"MISSED VIOLATIONS:     {report.missed_violations}   (must be 0)")
    print(f"False alarms:          {report.false_alarms}")
    sys.exit(1 if report.missed_violations else 0)


if __name__ == "__main__":
    main()
