"""What would make a failed finding pass: pure, deterministic arithmetic on rule + finding."""
import pytest

from app.api.remedy import remedy
from app.models import CheckType, Finding, Rule, SourceRef, Status

SRC = SourceRef(document="d.pdf", regime="X", quote="q")


def rule(op, value, unit="mm", ct=CheckType.numeric, param="clear_width"):
    return Rule(id="r", title="t", check_type=ct, target="door", parameter=param, operator=op,
                value=value, unit=unit, source=SRC)


def fnd(measured, status=Status.failed):
    return Finding(rule_id="r", status=status, message="m", measured=measured, rule_source=SRC)


def count_rule(op, value):
    return rule(op, value, unit=None, ct=CheckType.count, param=None)


def test_ge_shortfall():
    r = remedy(rule(">=", 800), fnd(780))
    assert r["delta"] == 20 and r["direction"] == "increase"
    assert r["text"] == "clear_width 780 mm -> needs >= 800 mm (+20 mm)"


def test_ge_boundary_value_is_not_a_failure_but_still_arithmetic_is_exact():
    assert remedy(rule(">=", 800), fnd(799.5))["delta"] == 0.5


def test_gt_is_strict():
    r = remedy(rule(">", 800), fnd(800))
    assert r["strict"] is True and r["delta"] == 0
    assert r["text"] == "clear_width 800 mm -> needs > 800 mm (more than +0 mm)"


def test_le_excess():
    r = remedy(rule("<=", 1000), fnd(1250))
    assert r["delta"] == -250 and r["direction"] == "decrease"
    assert r["text"] == "clear_width 1250 mm -> needs <= 1000 mm (-250 mm)"


def test_lt_is_strict():
    r = remedy(rule("<", 1000), fnd(1000))
    assert r["strict"] is True and "needs < 1000 mm" in r["text"]


def test_eq_and_ne():
    assert remedy(rule("==", 800), fnd(790))["text"].startswith("clear_width 790 mm -> needs == 800 mm")
    assert "must not equal 800 mm" in remedy(rule("!=", 800), fnd(800))["text"]


def test_rule_unit_converted_to_base_mm():
    r = remedy(rule(">=", 0.8, unit="m"), fnd(780))
    assert r["required"] == 800 and r["delta"] == 20 and r["unit"] == "mm"


def test_area_unit_shown_as_m2():
    r = remedy(rule(">=", 2, unit="m2", param="area"), fnd(1.5))
    assert r["unit"] == "m2" and r["delta"] == 0.5 and "(+0.5 m2)" in r["text"]


def test_float_noise_is_rounded():
    assert remedy(rule(">=", 0.3, unit="m2", param="area"), fnd(0.1))["delta"] == 0.2


def test_count_ge():
    r = remedy(count_rule(">=", 2), fnd(1))
    assert r["direction"] == "increase" and r["delta"] == 1
    assert r["text"] == "door count 1 -> needs >= 2 (+1)"


def test_count_gt_needs_one_more_than_value():
    assert remedy(count_rule(">", 2), fnd(2))["delta"] == 1


def test_count_le_and_lt_reduce():
    assert remedy(count_rule("<=", 2), fnd(5))["delta"] == -3
    assert remedy(count_rule("<", 2), fnd(2))["delta"] == -1


def test_presence_and_not_exists():
    pres = rule("exists", None, unit=None, ct=CheckType.presence, param=None)
    assert remedy(pres, fnd(0))["delta"] == 1
    r = remedy(rule("not_exists", None, unit=None, ct=CheckType.presence, param=None), fnd(2))
    assert r["delta"] == -2 and r["direction"] == "decrease"


@pytest.mark.parametrize("status", [Status.passed, Status.needs_review, Status.not_applicable])
def test_only_failures_get_a_remedy(status):
    assert remedy(rule(">=", 800), fnd(780, status)) is None


def test_no_remedy_when_not_computable():
    assert remedy(rule(">=", 800), fnd(None)) is None
    assert remedy(rule(">=", 800), fnd("wide")) is None
    assert remedy(rule(">=", "big"), fnd(780)) is None
    assert remedy(rule(None, 800), fnd(780)) is None
    assert remedy(rule(">=", 800, ct=CheckType.qualitative), fnd(780)) is None
    assert remedy(None, fnd(780)) is None
