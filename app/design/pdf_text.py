"""D1: text layer of design PDFs -> lines with bboxes, dimensions in mm, ship particulars.

Only reads what is literally in the PDF text layer. GA drawings without a text layer
(vector outlines / scans) return no lines; `has_text_layer()` tells D2 to use vision.
Nothing is guessed: unknown or implausible values stay None (-> needs_review downstream).
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf
from pydantic import BaseModel

from app.check.units import to_base
from app.models import Provenance, ShipParticulars

BBox = tuple[float, float, float, float]

CONF_EXPLICIT_UNIT = 0.95
CONF_ASSUMED_UNIT = 0.5   # unit not printed anywhere; below the evaluator's trust threshold -> needs_review


class TextLine(BaseModel):
    page: int          # 1-based
    text: str
    bbox: BBox         # PDF points, x0, y0, x1, y1 (origin top-left)


# ---------- text layer ----------

def extract_lines(path: str | Path) -> list[TextLine]:
    out: list[TextLine] = []
    with pymupdf.open(path) as doc:
        for pno, page in enumerate(doc, start=1):
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if text:
                        out.append(TextLine(page=pno, text=text, bbox=tuple(line["bbox"])))
    return out


def has_text_layer(path: str | Path) -> bool:
    with pymupdf.open(path) as doc:
        return any(page.get_text().strip() for page in doc)


# ---------- numbers & dimensions ----------

_NUM = r"\d[\d ]*(?:[.,]\d+)?"
_FT_IN = re.compile(r"^(\d+)\s*'\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:\"|'')?$")
_DIM = re.compile(rf"^({_NUM})\s*(mm|cm|m|in|inch|inches|ft|\"|')?\.?$", re.I)


def _to_float(num: str) -> float:
    # spaces are thousand separators ("3 250"); a comma is a decimal comma ("69,80")
    return float(num.replace(" ", "").replace(",", "."))


def _parse_dim(text: str) -> tuple[float, str | None] | None:
    """-> (value in mm, unit as printed or None)."""
    t = text.strip()
    if m := _FT_IN.match(t):
        return int(m[1]) * 304.8 + float(m[2] or 0) * 25.4, "ft-in"
    if m := _DIM.match(t):
        unit = m[2].lower() if m[2] else None
        unit = {'"': "in", "'": "ft"}.get(unit, unit)
        return _to_float(m[1]), unit
    return None


def parse_dimension_mm(text: str, default_unit: str = "mm") -> float | None:
    """'800' -> 800, '0.8 m' -> 800, '69,80 m' -> 69800, '2\\'-8\"' -> 812.8. None if not a dimension."""
    parsed = _parse_dim(text)
    if parsed is None:
        return None
    value, unit = parsed
    if unit == "ft-in":
        return value
    mm, base = to_base(value, unit or default_unit)
    return mm if base == "mm" else None


# ---------- ship particulars ----------

class ParticularValue(BaseModel):
    value: float
    provenance: Provenance


class ParticularsResult(BaseModel):
    length_overall_m: ParticularValue | None = None
    length_between_perpendiculars_m: ParticularValue | None = None
    breadth_m: ParticularValue | None = None
    gross_tonnage: ParticularValue | None = None
    persons_on_board: ParticularValue | None = None

    def to_ship_particulars(self) -> ShipParticulars:
        fields = {k: v for k, v in self if v is not None}
        ship = ShipParticulars(provenance=[v.provenance for v in fields.values()])
        for k, v in fields.items():
            setattr(ship, k, int(v.value) if k == "persons_on_board" else v.value)
        return ship   # ship_type stays None: never inferred from free text


# field -> (label regex, kind, plausible range)
_FIELDS: dict[str, tuple[re.Pattern, str, tuple[float, float]]] = {
    "length_overall_m": (re.compile(r"LENGTH\s*(OVER\s*ALL|O\.?\s*A\b\.?)|\bL\.?O\.?A\b\.?", re.I),
                         "length", (3, 500)),
    "length_between_perpendiculars_m": (re.compile(r"LENGTH\s*(BETWEEN\s*)?P\.?\s*P\b\.?|\bL\.?[BP]\.?P\b\.?", re.I),
                                        "length", (3, 500)),
    "breadth_m": (re.compile(r"\b(BREADTH|BEAM)\b(\s*MLD\b\.?)?", re.I), "length", (1, 80)),
    "gross_tonnage": (re.compile(r"GROSS\s*TONNAGE|\bG\.?T\b\.?", re.I), "number", (1, 300_000)),
    "persons_on_board": (re.compile(r"PERSONS\s*ON\s*BOARD|\bPOB\b|COMPLEMENT", re.I), "number", (1, 10_000)),
}
# full words only: "1 PERS." / "2 PERS." are cabin labels on GA drawings, not the ship total
_PERSONS_INLINE = re.compile(r"(\d+)\s*(PERSONS|BERTHS|PAX)\b", re.I)
_UNIT_ONLY = re.compile(r"^\(?(mm|cm|m|in|inch|inches|ft|feet)\.?\)?$", re.I)
_UNIT_IN_LABEL = re.compile(r"\((mm|cm|m|in|inch|inches|ft|feet)\.?\)", re.I)
_MAX_LABEL_CHARS = 40  # longer lines are prose ("In beam seas, roll ..."), not table labels
_ANY_LABEL = re.compile("|".join(p.pattern for p, _, _ in _FIELDS.values()), re.I)
_MAX_GAP_PT = 400      # max horizontal distance from label to its value


def _value(text: str, kind: str, unit_hint: str | None = None) -> tuple[float, float] | None:
    """-> (value in field units, confidence) or None. unit_hint: unit printed in the label or
    in a separate cell, used when the value itself carries no unit."""
    t = text.strip().lstrip(":=-. ").strip()
    if kind == "number":
        return (_to_float(t), CONF_EXPLICIT_UNIT) if re.fullmatch(_NUM, t) else None
    parsed = _parse_dim(t)
    if parsed is None:
        return None
    value, unit = parsed
    if unit is None and unit_hint:
        unit = {"feet": "ft"}.get(unit_hint.lower(), unit_hint.lower())
    if unit is None:   # nothing printed: assume metres (title-block convention), flag as uncertain
        return value, CONF_ASSUMED_UNIT
    mm = value if unit == "ft-in" else to_base(value, unit)[0]
    return mm / 1000.0, CONF_EXPLICIT_UNIT


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def parse_particulars(path: str | Path) -> ParticularsResult:
    lines = extract_lines(path)
    result = ParticularsResult()
    used: set[int] = set()

    def prov(page: int, bbox: BBox, conf: float) -> Provenance:
        return Provenance(file=str(path), page=page, bbox=bbox, method="pdf_text", confidence=conf)

    def accept(field: str, val: tuple[float, float], page: int, bbox: BBox) -> bool:
        lo, hi = _FIELDS[field][2]
        if not lo <= val[0] <= hi:
            return False   # implausible -> leave unknown rather than store a misparse
        setattr(result, field, ParticularValue(value=val[0], provenance=prov(page, bbox, val[1])))
        return True

    for i, line in enumerate(lines):
        if result.persons_on_board is None and (m := _PERSONS_INLINE.search(line.text)):
            accept("persons_on_board", (float(m[1]), CONF_EXPLICIT_UNIT), line.page, line.bbox)

        for field, (pattern, kind, _) in _FIELDS.items():
            if getattr(result, field) is not None or not (m := pattern.search(line.text)):
                continue
            # 1) value printed after the label in the same line: "LOA: 75.5 m"
            inline = _value(line.text[m.end():], kind)
            if inline and accept(field, inline, line.page, line.bbox):
                break
            # 2) value in a separate text line to the right. It belongs to this label when its
            #    top edge lies within the label's height (handles values printed half a row
            #    lower, which would otherwise also overlap the next label).
            if len(line.text) > _MAX_LABEL_CHARS:
                break
            x0, y0, x1, y1 = line.bbox
            row = [(j, c, c.bbox[0] - x1) for j, c in enumerate(lines)
                   if j != i and c.page == line.page and -2 <= c.bbox[0] - x1 <= _MAX_GAP_PT
                   and y0 - 2 <= c.bbox[1] <= y1 - 1]
            label_unit = _UNIT_IN_LABEL.search(line.text)
            best: tuple[float, int, tuple[float, float]] | None = None
            for j, cand, gap in row:
                if j in used or _ANY_LABEL.search(cand.text):
                    continue
                # a unit-only cell ("ft") between label and value applies to the value
                cell_units = sorted((g, u.text) for _, u, g in row if g < gap and _UNIT_ONLY.match(u.text))
                hint = (_UNIT_ONLY.match(cell_units[-1][1])[1] if cell_units
                        else label_unit[1] if label_unit else None)
                val = _value(cand.text, kind, hint)
                if val and (best is None or gap < best[0]):
                    best = (gap, j, val)
            if best and accept(field, best[2], line.page, _union(line.bbox, lines[best[1]].bbox)):
                used.add(best[1])
            break   # one field per label line
    return result
