"""Deterministic rule evaluation: numeric, presence and count rules.

No LLM for numeric/presence/count — results are exact and reproducible. Qualitative rules are
handed to llm_judge. Missing evidence always yields needs_review, never a guess.
"""
from __future__ import annotations

import operator as op

from app.check.applicability import applies_to_ship, element_matches
from app.check.llm_judge import judge
from app.check.units import to_base
from app.models import CheckType, DesignFacts, Finding, Rule, Status
from app.providers.llm import LLMProvider

_OPS = {">=": op.ge, ">": op.gt, "<=": op.le, "<": op.lt, "==": op.eq, "!=": op.ne}
LOW_CONFIDENCE = 0.6


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
                         f"No '{rule.target}' elements found in the design to check.")]
    req, req_unit = to_base(float(rule.value), rule.unit)  # type: ignore[arg-type]
    cmp = _OPS[rule.operator]  # type: ignore[index]
    out: list[Finding] = []
    for el in targets:
        raw = el.properties.get(rule.parameter or "")
        if raw is None or isinstance(raw, (bool, str)):
            out.append(_finding(rule, Status.needs_review,
                                f"{el.type} '{el.name or el.id}': '{rule.parameter}' not found in design.",
                                element_id=el.id, evidence=[el.provenance]))
            continue
        # design properties are stored in base units already (mm, m2)
        ok = cmp(float(raw), req)
        label = f"{el.type} '{el.name or el.id}'"
        if el.provenance.confidence < LOW_CONFIDENCE:
            status, msg = Status.needs_review, (
                f"{label}: {rule.parameter}={raw} {req_unit or ''} (low extraction confidence "
                f"{el.provenance.confidence:.0%}); required {rule.operator} {req:g} {req_unit or ''}.")
        elif ok:
            status, msg = Status.passed, f"{label}: {rule.parameter}={raw:g} {req_unit or ''} OK."
        else:
            status, msg = Status.failed, (
                f"{label}: {rule.parameter}={raw:g} {req_unit or ''} but {rule.source.regime} "
                f"{rule.source.clause or ''} requires {rule.operator} {req:g} {req_unit or ''}.")
        out.append(_finding(rule, status, msg, element_id=el.id, measured=raw, evidence=[el.provenance]))
    return out


def _count(rule: Rule, facts: DesignFacts) -> list[Finding]:
    targets = [e for e in facts.elements if element_matches(rule, e)]
    n = len(targets)
    evidence = [e.provenance for e in targets]
    oper = rule.operator or "exists"
    if oper == "exists":
        ok = n > 0
    elif oper == "not_exists":
        ok = n == 0
    else:
        ok = _OPS[oper](n, float(rule.value))  # type: ignore[arg-type]
    if not ok and n == 0 and oper != "not_exists":
        # absence in an extracted model may be an extraction gap, not a design error
        return [_finding(rule, Status.needs_review,
                         f"No '{rule.target}' found; verify it is absent from the design, not just unextracted.",
                         measured=0)]
    status = Status.passed if ok else Status.failed
    msg = (f"Found {n} '{rule.target}' — "
           + ("OK." if ok else f"{rule.source.regime} {rule.source.clause or ''} requires {oper} {rule.value}."))
    return [_finding(rule, status, msg, measured=n, evidence=evidence)]


def evaluate_all(rules: list[Rule], facts: DesignFacts, llm: LLMProvider | None = None) -> list[Finding]:
    return [f for r in rules for f in evaluate_rule(r, facts, llm)]
