"""What would make a failed finding pass: plain arithmetic on the rule and the finding.

Deterministic, no AI. Only failed numeric, count and presence findings get a remedy; everything
else (pass, needs_review, qualitative, anything not computable) returns None rather than a guess.
Lengths are in mm and areas in m2 (the internal units), the same units `Finding.measured` is in.
"""
from __future__ import annotations

from app.check.units import to_base
from app.models import CheckType, Finding, Rule, Status


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _g(x: float) -> str:
    return f"{round(x, 6):g}"


def _signed(x: float) -> str:
    return ("+" if x >= 0 else "-") + _g(abs(x))


def remedy(rule: Rule | None, finding: Finding) -> dict | None:
    if rule is None or finding.status != Status.failed or rule.operator is None:
        return None
    if rule.check_type not in (CheckType.numeric, CheckType.count, CheckType.presence):
        return None
    measured = _num(finding.measured)
    if measured is None:
        return None
    op = rule.operator
    is_count = rule.check_type != CheckType.numeric

    if op in ("exists", "not_exists"):
        required, unit = (1.0 if op == "exists" else 0.0), None
    else:
        value = _num(rule.value)
        if value is None:
            return None
        required, unit = to_base(value, rule.unit) if not is_count else (value, None)
    unit = None if unit == "count" else unit
    u = f" {unit}" if unit else ""
    what = f"{rule.target} count" if is_count else (rule.parameter or rule.target)

    strict = op in (">", "<")
    if op in ("exists", ">=", ">"):
        # integer counts under a strict bound need one more than the value
        target = required + 1 if (is_count and op == ">") else required
        delta = target - measured
        direction = "increase"
    elif op in ("not_exists", "<=", "<"):
        target = required - 1 if (is_count and op == "<") else required
        delta = target - measured
        direction = "decrease"
    else:  # == or !=
        delta = required - measured
        direction = "increase" if delta > 0 else "decrease"
    delta = round(delta, 6)

    if op == "exists":
        need = "needs >= 1"
    elif op == "not_exists":
        need = "needs none"
    elif op == "!=":
        need = f"must not equal {_g(required)}{u}"
    else:
        need = f"needs {op} {_g(required)}{u}"
    change = f"{_signed(delta)}{u}"
    if strict and not is_count:
        change = f"more than {change}" if direction == "increase" else f"less than {change}"
    text = f"{what} {_g(measured)}{u} -> {need} ({change})"
    if op == "!=":
        text = f"{what} {_g(measured)}{u} -> {need}"
        delta = 0.0
    return {"text": text, "parameter": rule.parameter, "measured": measured, "operator": op,
            "required": required, "unit": unit, "delta": delta, "direction": direction, "strict": strict}
