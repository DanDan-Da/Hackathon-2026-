"""D3: cross-check vision-extracted elements against the PDF's own text layer.

The vision model can misread numbers or place boxes slightly off, and some models (Gemma)
report confidence 1.0 for everything. The text layer is exact, so it is the referee.
Applied only when the PDF has a text layer (the caller checks `has_text_layer`).

Per element, text lines whose centre lies in the element's bbox grown by a margin
(`MARGIN_PT` + `MARGIN_FRAC` of its size, to tolerate boxes that are slightly off) are candidates.
  1. CONFIRMED when a line equals the element's printed name (an area token on the same line is
     ignored for that comparison), or an area line equals the element's vision area, or a
     dimension line equals a vision dimension. Confidence is raised to at least CONFIRMED_CONF.
     `Provenance.method` stays "vision" (no change to the shared model). The vision bbox is kept;
     the confirming label's bbox is recorded in `properties["text_label_bbox"]` ("x0,y0,x1,y1").
     A label of a different room that merely lies nearby never confirms.
  2. DISAGREEMENT: area printed in the text layer for this element (on the name label's line, else
     the area line nearest to the name label) differs from the vision area -> text value wins,
     vision value kept as `area_vision_value`. Without a matching name label, an area line is only
     used to confirm an equal value, never to overwrite (ownership would be a guess).
     Same for a single bare dimension number strictly inside the bbox vs a vision dimension
     (`<prop>_vision_value`). The element is then confirmed only if its name matched.
  3. UNCONFIRMED -> confidence capped at UNCONFIRMED_CAP (just below the evaluator's
     LOW_CONFIDENCE, so the evaluator answers needs_review). Never raised, never lowered below
     what it already was.
  4. Text lines no element used are returned as `unmatched_labels`; no elements are invented.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.check.evaluator import LOW_CONFIDENCE
from app.design.drawing_vision import AREA_PROPERTIES, COUNT_PROPERTIES
from app.design.pdf_text import BBox, TextLine, parse_dimension_mm
from app.models import DesignFacts

CONFIRMED_CONF = 0.9
UNCONFIRMED_CAP = round(LOW_CONFIDENCE - 0.01, 2)   # strictly below the evaluator threshold
MARGIN_PT = 10.0
MARGIN_FRAC = 0.1
AREA_TOL_M2 = 0.05
DIM_TOL_MM = 0.5
MAX_LABEL_CHARS = 40

_UNIT = re.compile(r"\d\s*(?:mm|cm|m|ft|in)\b|['\"]", re.I)
MAX_BARE_RATIO = 2.0   # a bare number may only fix a near miss (760 -> 800), never a wildly different value
_AREA_TOKEN = re.compile(r"(\d[\d ]*(?:[.,]\d+)?)\s*(?:m2|m²|m\^2|sq\.?\s*m)\b", re.I)


class Correction(BaseModel):
    element_id: str
    property: str
    vision_value: float
    text_value: float
    text: str


class CrossCheckReport(BaseModel):
    confirmed: list[str] = Field(default_factory=list)
    capped: list[str] = Field(default_factory=list)       # unconfirmed (confidence capped or already lower)
    corrections: list[Correction] = Field(default_factory=list)
    unmatched_labels: list[TextLine] = Field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.casefold()).strip()


def _area_of(text: str) -> float | None:
    m = _AREA_TOKEN.search(text)
    return float(m[1].replace(" ", "").replace(",", ".")) if m else None


def _name_part(text: str) -> str:
    return _norm(_AREA_TOKEN.sub("", text))


def _center(b: BBox) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _inside(pt: tuple[float, float], b: BBox) -> bool:
    return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


def _grow(b: BBox) -> BBox:
    m = MARGIN_PT + MARGIN_FRAC * max(b[2] - b[0], b[3] - b[1])
    return (b[0] - m, b[1] - m, b[2] + m, b[3] + m)


def _dist(a: BBox, b: BBox) -> float:
    (ax, ay), (bx, by) = _center(a), _center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def crosscheck(facts: DesignFacts, lines: list[TextLine]) -> tuple[DesignFacts, CrossCheckReport]:
    """Returns (new facts, report). The input facts are not modified."""
    facts = facts.model_copy(deep=True)
    report = CrossCheckReport()
    used: set[int] = set()

    for el in facts.elements:
        prov = el.provenance
        if prov.bbox is None or prov.page is None:
            _cap(el, report)
            continue
        wide = _grow(prov.bbox)
        near = [(i, l) for i, l in enumerate(lines)
                if l.page == prov.page and _inside(_center(l.bbox), wide)]
        confirmed_by: list[tuple[int, TextLine]] = []

        # name
        name_line = None
        if el.name and _name_part(el.name):
            want = _name_part(el.name)       # vision names may embed the area, e.g. "MESS 83 m²"
            cands = [(i, l) for i, l in near if _name_part(l.text) == want and len(l.text) <= MAX_LABEL_CHARS]
            if cands:
                name_line = min(cands, key=lambda c: _dist(c[1].bbox, prov.bbox))
                confirmed_by.append(name_line)

        # area: text value belonging to this element
        v_area = next((el.properties[k] for k in AREA_PROPERTIES if k in el.properties), None)
        area_key = next((k for k in AREA_PROPERTIES if k in el.properties), None)
        area_line = None
        if area_key is not None:
            area_cands = [(i, l) for i, l in near if _area_of(l.text) is not None]
            if name_line is not None:
                # same line as the name, else the nearest area line to the name label
                if _area_of(name_line[1].text) is not None:
                    area_line = name_line
                elif area_cands:
                    area_line = min(area_cands, key=lambda c: _dist(c[1].bbox, name_line[1].bbox))
            else:
                inner = [(i, l) for i, l in area_cands if _inside(_center(l.bbox), prov.bbox)]
                matching = [c for c in inner if abs(_area_of(c[1].text) - v_area) <= AREA_TOL_M2]
                if matching:
                    area_line = matching[0]
        if area_line is not None:
            t_area = _area_of(area_line[1].text)
            if abs(t_area - v_area) <= AREA_TOL_M2:
                if area_line not in confirmed_by:
                    confirmed_by.append(area_line)
            elif name_line is not None:
                report.corrections.append(Correction(element_id=el.id, property=area_key, vision_value=v_area,
                                                     text_value=t_area, text=area_line[1].text))
                el.properties[f"{area_key}_vision_value"] = v_area
                el.properties[area_key] = t_area
                used.add(area_line[0])

        # other dimensions: bare numbers strictly inside the bbox
        dim_lines = [(i, l, parse_dimension_mm(l.text)) for i, l in near
                     if _inside(_center(l.bbox), prov.bbox) and _area_of(l.text) is None
                     and parse_dimension_mm(l.text) is not None]
        for key, val in list(el.properties.items()):
            if (key in AREA_PROPERTIES or key in COUNT_PROPERTIES or key.endswith("_vision_value")
                    or not isinstance(val, float)):
                continue
            hit = next(((i, l) for i, l, mm in dim_lines if abs(mm - val) <= DIM_TOL_MM), None)
            if hit:
                confirmed_by.append(hit)
            elif len(dim_lines) == 1 and name_line is not None and _plausible_fix(val, dim_lines[0]):
                i, l, mm = dim_lines[0]
                report.corrections.append(Correction(element_id=el.id, property=key, vision_value=val,
                                                     text_value=mm, text=l.text))
                el.properties[f"{key}_vision_value"] = val
                el.properties[key] = mm
                used.add(i)

        if confirmed_by:
            used.update(i for i, _ in confirmed_by)
            prov.confidence = max(prov.confidence, CONFIRMED_CONF)
            lb = confirmed_by[0][1].bbox
            el.properties["text_label_bbox"] = ",".join(f"{v:.1f}" for v in lb)
            report.confirmed.append(el.id)
        else:
            _cap(el, report)

    report.unmatched_labels = [l for i, l in enumerate(lines) if i not in used and len(l.text) <= MAX_LABEL_CHARS]
    return facts, report


def _plausible_fix(vision_value: float, dim_line: tuple) -> bool:
    """A printed unit makes the number a dimension. A bare number (frame ruler, deck number...) may only
    correct the vision value when it is a near miss; otherwise replacing it would be a guess."""
    _, line, mm = dim_line
    if _UNIT.search(line.text):
        return True
    return vision_value > 0 and 1 / MAX_BARE_RATIO <= mm / vision_value <= MAX_BARE_RATIO


def _cap(el, report: CrossCheckReport) -> None:
    el.provenance.confidence = min(el.provenance.confidence, UNCONFIRMED_CAP)
    report.capped.append(el.id)
