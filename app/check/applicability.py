"""Decide whether a rule applies to the ship and to a given element."""
from __future__ import annotations

from app.models import DesignElement, Rule, ShipParticulars


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def applies_to_ship(rule: Rule, ship: ShipParticulars) -> bool | None:
    """True/False, or None if a required particular is unknown (-> needs_review)."""
    a = rule.applies_to
    checks: list[bool | None] = []
    if a.ship_types:
        checks.append(None if ship.ship_type is None
                      else _norm(ship.ship_type) in {_norm(t) for t in a.ship_types})
    loa = ship.length_overall_m
    if a.min_length_m is not None:
        checks.append(None if loa is None else loa >= a.min_length_m)
    if a.max_length_m is not None:
        checks.append(None if loa is None else loa <= a.max_length_m)
    if a.min_gross_tonnage is not None:
        gt = ship.gross_tonnage
        checks.append(None if gt is None else gt >= a.min_gross_tonnage)
    if a.min_persons_on_board is not None:
        pob = ship.persons_on_board
        checks.append(None if pob is None else pob >= a.min_persons_on_board)
    if any(c is False for c in checks):
        return False
    if any(c is None for c in checks):
        return None
    return True


def element_matches(rule: Rule, el: DesignElement) -> bool:
    if _norm(el.type) != _norm(rule.target):
        return False
    if rule.applies_to.space_types:
        wanted = {_norm(s) for s in rule.applies_to.space_types}
        return _norm(el.space_type) in wanted
    return True
