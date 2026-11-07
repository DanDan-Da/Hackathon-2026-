"""Unit normalisation. Rules and design facts are both normalised to these base units."""
from __future__ import annotations

_LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4,
                 "ft": 304.8, "feet": 304.8, "foot": 304.8}
_AREA_TO_M2 = {"m2": 1.0, "m²": 1.0, "ft2": 0.09290304, "sq ft": 0.09290304, "mm2": 1e-6}

BASE_UNIT = {**{u: "mm" for u in _LENGTH_TO_MM}, **{u: "m2" for u in _AREA_TO_M2}}


def to_base(value: float, unit: str | None) -> tuple[float, str | None]:
    """Convert value to base unit (mm for length, m2 for area). Unknown units pass through."""
    if unit is None:
        return value, None
    u = unit.strip().lower()
    if u in _LENGTH_TO_MM:
        return value * _LENGTH_TO_MM[u], "mm"
    if u in _AREA_TO_M2:
        return value * _AREA_TO_M2[u], "m2"
    return value, u
