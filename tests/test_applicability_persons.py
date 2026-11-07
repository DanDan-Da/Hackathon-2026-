from app.check.applicability import applies_to_ship
from app.models import Applicability, CheckType, Rule, ShipParticulars, SourceRef


def rule(lo=None, hi=None):
    return Rule(id="r", title="t", check_type=CheckType.count, target="x", operator=">=", value=1, unit="count",
                applies_to=Applicability(min_persons_on_board=lo, max_persons_on_board=hi),
                source=SourceRef(document="d", regime="R", quote="q"))


def ship(n):
    return ShipParticulars(persons_on_board=n)


def test_tier_bounds_are_inclusive():
    tier = rule(26, 50)
    assert [applies_to_ship(tier, ship(n)) for n in (25, 26, 50, 51)] == [False, True, True, False]


def test_max_only():
    assert applies_to_ship(rule(hi=25), ship(25)) is True
    assert applies_to_ship(rule(hi=25), ship(26)) is False


def test_unknown_persons_needs_review_not_guess():
    assert applies_to_ship(rule(26, 50), ship(None)) is None


def test_no_bounds_means_no_restriction():
    assert applies_to_ship(rule(), ship(None)) is True
