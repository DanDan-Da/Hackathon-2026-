"""D4: labelled principal dimensions (length overall, beam, draft ...) from a particulars PDF.

Reads the text layer only. Label spellings live in `particulars_labels.json`. A value needs a
unit (printed on the value or on a separate unit line); a bare number is skipped, never guessed.
Each hit becomes a `stated_particular` DesignElement (value in mm) with page + bbox provenance
and the verbatim line as `quote`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.check.units import to_base
from app.design.pdf_text import extract_lines
from app.models import DesignElement, DesignFacts, Provenance

LABELS_PATH = Path(__file__).with_name("particulars_labels.json")
CONF_TEXT = 0.9
LOOKAHEAD = 3

_DASH = str.maketrans({"–": "-", "—": "-", "’": "'", "′": "'", "”": '"', "″": '"'})


def load_labels(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or LABELS_PATH).read_text())


def _label_regexes(cfg: dict) -> list[tuple[str, re.Pattern, int]]:
    out = []
    for field, labels in cfg["fields"].items():
        for lab in labels:
            toks = re.findall(r"[^\W_]+", lab.lower())
            if toks:
                rx = re.compile(r"^\W*" + r"[\W_]+".join(map(re.escape, toks)) + r"(?![^\W_])", re.I)
                out.append((field, rx, len(lab)))
    return sorted(out, key=lambda t: -t[2])   # longest label first


def _value_mm(text: str, units: re.Pattern, default_unit: str | None) -> tuple[float, str | None] | None:
    """-> (mm, unit used) or None when no number, or no unit anywhere."""
    t = text.translate(_DASH).strip().lstrip(".… :=").strip()
    if m := re.match(r"^(\d+)\s*'\s*-?\s*(\d+(?:[.,]\d+)?)?\s*(?:\"|'')?\s*$", t):
        ft = to_base(float(m[1]), "ft")[0]
        inch = to_base(float(m[2].replace(",", ".")), "in")[0] if m[2] else 0.0
        return ft + inch, "ft-in"
    if m := re.match(rf"^(\d[\d]*(?:[.,]\d+)?|\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?)\s*({units.pattern})?\.?$", t, re.I):
        num = m[1]
        num = num.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", num) else num.replace(",", ".")
        unit = (m[2] or default_unit)
        if unit is None:
            return None
        mm, base = to_base(float(num), unit)
        return (mm, unit) if base == "mm" else None
    return None


def read_stated_particulars(path: str | Path, project: str | None = None,
                            labels_path: str | Path | None = None) -> DesignFacts:
    path = Path(path)
    cfg = load_labels(labels_path)
    labels = _label_regexes(cfg)
    units = re.compile("|".join(sorted(map(re.escape, cfg.get("units", ["mm", "m", "ft"])), key=len, reverse=True)))
    unit_line = re.compile(rf"^\(?({units.pattern})\.?\)?$", re.I)
    lines = extract_lines(path)
    elements: dict[str, DesignElement] = {}

    def label_of(text):
        for field, rx, _ in labels:
            if m := rx.match(text):
                return field, text[m.end():]
        return None

    for i, ln in enumerate(lines):
        hit = label_of(ln.text)
        if not hit or hit[0] in elements:
            continue
        field, rest = hit
        unit_hint = None
        quote_parts = [ln.text]
        value = _value_mm(rest, units, None) if rest.strip(" .…:") else None
        if value is None:
            for nxt in lines[i + 1 : i + 1 + LOOKAHEAD]:
                if nxt.page != ln.page or label_of(nxt.text):
                    break
                if um := unit_line.match(nxt.text.strip()):
                    unit_hint = um[1].lower(); quote_parts.append(nxt.text); continue
                if value is None and (v := _value_mm(nxt.text, units, unit_hint)):
                    value = v; quote_parts.append(nxt.text)
                    break
        if value is None:
            continue
        elements[field] = DesignElement(
            id=f"stated:{field}", type="stated_particular", name=field,
            properties={"parameter": field, "value": value[0], "unit": "mm", "quote": " | ".join(quote_parts)},
            provenance=Provenance(file=str(path), page=ln.page, bbox=ln.bbox,
                                  method="pdf_text", confidence=CONF_TEXT))
    return DesignFacts(project=project or path.stem, elements=list(elements.values()),
                       source_files=[str(path)])
