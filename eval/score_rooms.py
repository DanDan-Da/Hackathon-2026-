"""Score room extraction (facts.json) against the hand-verified Dana gold set.

    python -m eval.score_rooms facts.json [--gold eval/gold/dana/dana_rooms.json]

Sampled room recall = matched gold rooms / total gold rooms.
Area accuracy       = correct printed areas / matched gold rooms.

A gold room matches a detected element when (a) the names agree after
normalisation (case, whitespace, punctuation, embedded area text) AND (b) the
gold label centre lies inside, or within LOCATION_MARGIN_PT of, the element's
provenance bbox on the same page. Name alone is not enough: cabins and other
labels repeat across decks.

No precision is computed: the gold set is a partial inventory, so detections
outside it cannot be called false positives.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.models import DesignElement, DesignFacts

DEFAULT_GOLD = Path("eval/gold/dana/dana_rooms.json")
AREA_TOLERANCE_M2 = 0.5
LOCATION_MARGIN_PT = 10.0

NOTE = (
    "NOTE: gold set = 20-room partial sample. Precision is NOT reported: detections outside\n"
    "the sample are not false positives, and full precision needs an exhaustive inventory.\n"
    "Do not tune a model against these labels and then call the score held-out."
)

_AREA_TEXT = re.compile(r"\d+(?:[.,]\d+)?\s*m\s*[²2](?![\d])", re.IGNORECASE)


def normalise_name(text: str | None) -> list[str]:
    s = (text or "").lower().replace("²", "2")
    s = _AREA_TEXT.sub(" ", s)
    s = re.sub(r"[^\w]+", " ", s.replace("_", " "))
    return s.split()


def names_match(gold_name: str, element_name: str | None) -> bool:
    g, e = normalise_name(gold_name), normalise_name(element_name)
    if not g or not e:
        return False
    return g == e or set(e) <= set(g) or set(g) <= set(e)


def _centre_near(bbox, label, margin: float) -> bool:
    cx, cy = (label[0] + label[2]) / 2, (label[1] + label[3]) / 2
    return bbox[0] - margin <= cx <= bbox[2] + margin and bbox[1] - margin <= cy <= bbox[3] + margin


def _element_area(el: DesignElement) -> float | None:
    v = el.properties.get("area")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


@dataclass
class RoomResult:
    gold_id: str
    name: str
    element_id: str | None
    area_result: str  # correct | wrong | missing | n/a (unmatched)
    gold_area: float | None = None
    detected_area: float | None = None
    duplicate_ids: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    rooms: list[RoomResult]

    @property
    def total(self) -> int:
        return len(self.rooms)

    @property
    def matched(self) -> int:
        return sum(r.element_id is not None for r in self.rooms)

    def _count(self, k: str) -> int:
        return sum(r.area_result == k for r in self.rooms)

    @property
    def area_correct(self) -> int:
        return self._count("correct")

    @property
    def area_wrong(self) -> int:
        return self._count("wrong")

    @property
    def area_missing(self) -> int:
        return self._count("missing")

    @property
    def recall(self) -> float:
        return self.matched / self.total if self.total else 0.0

    @property
    def area_accuracy(self) -> float | None:
        return self.area_correct / self.matched if self.matched else None


def score_rooms(facts: DesignFacts, gold: dict, *, tolerance: float = AREA_TOLERANCE_M2,
                margin: float = LOCATION_MARGIN_PT) -> ScoreResult:
    results: list[RoomResult] = []
    for g in gold["rooms"]:
        label = g["label_bbox_pdf_points"]
        cands = []
        for el in facts.elements:
            p = el.provenance
            if p.bbox is None or p.page != g.get("page", 1):
                continue
            if not names_match(g["room_name_printed"], el.name):
                continue
            if not _centre_near(p.bbox, label, margin):
                continue
            exact = normalise_name(el.name) == normalise_name(g["room_name_printed"])
            size = (p.bbox[2] - p.bbox[0]) * (p.bbox[3] - p.bbox[1])
            cands.append((_element_area(el) is None, not exact, size, el.id, el))
        gold_area = g.get("area_m2")
        if not cands:
            results.append(RoomResult(g["id"], g["room_name_printed"], None, "n/a", gold_area))
            continue
        cands.sort(key=lambda c: c[:4])
        best = cands[0][4]
        area = _element_area(best)
        if area is None:
            res = "missing"
        elif gold_area is not None and abs(area - gold_area) <= tolerance + 1e-9:
            res = "correct"
        else:
            res = "wrong"
        results.append(RoomResult(g["id"], g["room_name_printed"], best.id, res, gold_area, area,
                                  [c[3] for c in cands[1:]]))
    return ScoreResult(results)


def format_report(res: ScoreResult) -> str:
    lines = [f"{'gold id':<14} {'name':<34} {'element':<22} area"]
    for r in res.rooms:
        if r.element_id is None:
            area = "-"
            elem = "MISSING"
        else:
            elem = r.element_id
            det = "none" if r.detected_area is None else f"{r.detected_area:g}"
            area = {"correct": f"correct ({det})", "wrong": f"WRONG (got {det}, gold {r.gold_area:g})",
                    "missing": "MISSING AREA"}[r.area_result]
            if r.duplicate_ids:
                area += f" [+{len(r.duplicate_ids)} duplicate detection(s)]"
        lines.append(f"{r.gold_id:<14} {r.name[:33]:<34} {elem:<22} {area}")
    acc = "n/a" if res.area_accuracy is None else f"{res.area_correct}/{res.matched} = {res.area_accuracy:.0%}"
    lines += [
        "",
        f"Sampled room recall: {res.matched}/{res.total} = {res.recall:.0%}",
        f"Area accuracy:       {acc}  (wrong: {res.area_wrong}, matched but area missing: {res.area_missing})",
        "",
        NOTE,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("facts", type=Path)
    ap.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    args = ap.parse_args(argv)
    facts = DesignFacts.model_validate_json(args.facts.read_text())
    gold = json.loads(args.gold.read_text())
    print(format_report(score_rooms(facts, gold)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
