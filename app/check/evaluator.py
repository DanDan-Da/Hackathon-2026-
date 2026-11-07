"""Deterministic rule evaluation: numeric, presence and count rules.

No LLM for numeric/presence/count — results are exact and reproducible. Qualitative rules are
handed to llm_judge. Missing evidence always yields needs_review, never a guess.
"""
from __future__ import annotations

import json
import operator as op
from functools import lru_cache
from pathlib import Path

from app.check.applicability import applies_to_ship, element_matches
from app.check.llm_judge import judge
from app.check.units import to_base
from app.models import CheckType, DesignFacts, Finding, Rule, Status
from app.providers.llm import LLMProvider

_OPS = {">=": op.ge, ">": op.gt, "<=": op.le, "<": op.lt, "==": op.eq, "!=": op.ne}
LOW_CONFIDENCE = 0.6


@lru_cache(maxsize=1)
def _full_model_methods() -> frozenset[str]:
    cfg = json.loads((Path(__file__).parent / "absence_coverage.json").read_text(encoding="utf-8"))
    return frozenset(cfg["full_model_methods"])


def _absence_is_proof(facts: DesignFacts) -> bool:
    """True only when every design element comes from a source that models the whole design."""
    return bool(facts.elements) and all(e.provenance.method in _full_model_methods() for e in facts.elements)


def _place_hint(rule: Rule, facts: DesignFacts) -> str:
    """If the rule's target is the name of a place that design elements sit in, say so: the rule
    (not the design) is probably wrong, since a target must be a physical element type."""
    wanted = rule.target.strip().lower()
    inside = [e for e in facts.elements if (e.space_type or "").strip().lower() == wanted]
    if not inside:
        return ""
    return (f" Note: {len(inside)} element(s) are located in a '{rule.target}' space, but the rule targets "
            f"'{rule.target}' as an element type, so it can never match; the rule's target needs review.")


def _required_text(rule: Rule) -> str:
    return f"{rule.parameter or rule.target} {rule.operator} {rule.value} {rule.unit or ''}".strip()


def _finding(rule: Rule, status: Status, msg: str, **kw) -> Finding:
    return Finding(rule_id=rule.id, status=status, message=msg, rule_source=rule.source,
                   required=_required_text(rule), **kw)


def evaluate_rule(rule: Rule, facts: DesignFacts, llm: LLMProvider | None = None) -> list[Finding]:
    ship_ok = applies_to_ship(rule, facts.particulars)
    if ship_ok is False:
        return [_finding(rule, Status.not_applicable, "Rule does not apply to this ship.")]
    if ship_ok is None:
        return [_finding(rule, Status.needs_review,
                         "Ship particulars needed to decide applicability are missing.",
                         evidence=facts.particulars.provenance)]

    if rule.check_type == CheckType.numeric:
        return _numeric(rule, facts)
    if rule.check_type in (CheckType.presence, CheckType.count):
        return _count(rule, facts)
    return [_qualitative(rule, facts, llm)]


def _qualitative(rule: Rule, facts: DesignFacts, llm: LLMProvider | None) -> Finding:
    targets = [e for e in facts.elements if element_matches(rule, e)]
    res = judge(rule, targets, llm=llm, min_confidence=LOW_CONFIDENCE)
    cited = [e for e in targets if e.id in set(res.evidence_ids)]
    source = rule.source.model_copy(update={"quote": res.clause_quote or rule.source.quote})
    return Finding(rule_id=rule.id, status=res.status, message=res.reasoning, reasoning=res.reasoning,
                   rule_source=source, required=rule.title, method="llm_judge",
                   element_id=cited[0].id if len(cited) == 1 else None,
                   evidence=[e.provenance for e in cited])


def _numeric(rule: Rule, facts: DesignFacts) -> list[Finding]:
    targets = [e for e in facts.elements if element_matches(rule, e)]
    if not targets:
        return [_finding(rule, Status.needs_review,
                         f"No '{rule.target}' elements found in the design to check."
                         + _place_hint(rule, facts))]
    req, req_unit = to_base(float(rule.value), rule.unit)  # type: ignore[arg-type]
    cmp = _OPS[rule.operator]  # type: ignore[index]
    out: list[Finding] = []
    for el in targets:
        raw = el.properties.get(rule.parameter or "")
        if raw is None or isinstance(raw, (bool, str)):
            why = ("not found in design" if raw is None
                   else f"present but not a number ({raw!r}), cannot compare numerically")
            out.append(_finding(rule, Status.needs_review,
                                f"{el.type} '{el.name or el.id}': '{rule.parameter}' {why}.",
                                element_id=el.id, evidence=[el.provenance]))
            continue
        # design properties are stored in base units already (mm, m2)
        ok = cmp(float(raw), req)
        label = f"{el.type} '{el.name or el.id}'"
        if el.provenance.confidence < LOW_CONFIDENCE:
            status, msg = Status.needs_review, (
                f"{label}: {rule.parameter}={float(raw):g} {req_unit or ''} (low extraction confidence "
                f"{el.provenance.confidence:.0%}); required {rule.operator} {req:g} {req_unit or ''}.")
        elif ok:
            status, msg = Status.passed, f"{label}: {rule.parameter}={raw:g} {req_unit or ''} OK."
        else:
            status, msg = Status.failed, (
                f"{label}: {rule.parameter}={raw:g} {req_unit or ''} but {rule.source.regime} "
                f"{rule.source.clause or ''} requires {rule.operator} {req:g} {req_unit or ''}.")
        out.append(_finding(rule, status, msg, element_id=el.id, measured=raw, evidence=[el.provenance]))
    return out


def _count_ok(rule: Rule, n: int) -> bool:
    oper = rule.operator or "exists"
    if oper == "exists":
        return n > 0
    if oper == "not_exists":
        return n == 0
    return _OPS[oper](n, float(rule.value))  # type: ignore[arg-type]


def _count(rule: Rule, facts: DesignFacts) -> list[Finding]:
    targets = [e for e in facts.elements if element_matches(rule, e)]
    n = len(targets)
    confident = [e for e in targets if e.provenance.confidence >= LOW_CONFIDENCE]
    evidence = [e.provenance for e in targets]
    oper = rule.operator or "exists"
    ok = _count_ok(rule, n)
    if n == 0 and (not ok or (oper == "not_exists" and not _absence_is_proof(facts))):
        # absence in a drawing read may be an extraction gap or something the drawing never shows:
        # neither a fail for a missing element nor a pass for a prohibited one is proven
        return [_finding(rule, Status.needs_review,
                         f"No '{rule.target}' found; verify it is absent from the design, not just unextracted."
                         + _place_hint(rule, facts),
                         measured=0)]
    if len(confident) < n and _count_ok(rule, len(confident)) != ok:
        # the verdict flips depending on whether the doubtful reads are real: do not guess
        required = f"{oper} {rule.value}" if rule.value is not None else oper
        return [_finding(rule, Status.needs_review,
                         f"Found {n} '{rule.target}', but {n - len(confident)} of them were read with low "
                         f"extraction confidence (< {LOW_CONFIDENCE:.0%}) and the result depends on them; "
                         f"required {required}. Verify in the drawing.",
                         measured=n, evidence=evidence)]
    status = Status.passed if ok else Status.failed
    msg = (f"Found {n} '{rule.target}' — "
           + ("OK." if ok else f"{rule.source.regime} {rule.source.clause or ''} requires {oper} {rule.value}."))
    return [_finding(rule, status, msg, measured=n, evidence=evidence)]


def evaluate_all(rules: list[Rule], facts: DesignFacts, llm: LLMProvider | None = None) -> list[Finding]:
    return [f for r in rules for f in evaluate_rule(r, facts, llm)]
