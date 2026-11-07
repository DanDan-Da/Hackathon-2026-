"""Room long/short side from the closed wall rectangle around a room label (vector geometry).

For each cabin/toilet element the label position is taken from the facts, axis-aligned wall lines
are collected from the PDF vector paths, and the smallest closed rectangle around the label is
measured. Result: properties `room_long_side` and `room_short_side` (mm). The drawing does not
say which side is "width" and which "depth", so no width/depth is invented.

Confidence: 0.5 (vector_measure.CONF_VECTOR). It is raised to crosscheck.CONFIRMED_CONF only when
the printed area agrees AND the element's own bbox lies inside the rectangle AND the rectangle holds
no other room's label (area alone does not pin the short side). Disagreement is flagged.
Never overwrites an existing value. Tolerances: vector_rooms.json. Accuracy: docs/VECTOR.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from app.design import vector_measure as vm
from app.design.crosscheck import CONFIRMED_CONF

CFG = json.loads((Path(__file__).with_name("vector_rooms.json")).read_text())

Rect = tuple[float, float, float, float]


# ---------- wall lines ----------

def _dark(color) -> bool:
    return color is not None and max(color) <= CFG["max_wall_color_channel"]


def _axis_segments(drawings):
    """Axis-aligned dark segments as ('h', y, x0, x1) / ('v', x, y0, y1)."""
    tol = CFG["axis_tol_pt"]
    out = []
    for d in drawings:
        if not _dark(d.get("color")):
            continue
        for it in d["items"]:
            pts = []
            if it[0] == "l":
                pts = [(it[1].x, it[1].y, it[2].x, it[2].y)]
            elif it[0] in ("re", "qu"):
                r = it[1] if it[0] == "re" else it[1].rect
                pts = [(r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                       (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)]
            for x0, y0, x1, y1 in pts:
                if abs(y1 - y0) <= tol and abs(x1 - x0) > tol:
                    out.append(("h", (y0 + y1) / 2, min(x0, x1), max(x0, x1)))
                elif abs(x1 - x0) <= tol and abs(y1 - y0) > tol:
                    out.append(("v", (x0 + x1) / 2, min(y0, y1), max(y0, y1)))
    return out


def merge_walls(segs, k: float):
    """Merge collinear segments (door gaps up to merge_gap_mm) and keep long ones as walls."""
    tol, gap = CFG["axis_tol_pt"], CFG["merge_gap_mm"] / k
    min_len = CFG["min_wall_edge_mm"] / k
    walls = {"h": [], "v": []}
    for kind in ("h", "v"):
        ss = sorted((s for s in segs if s[0] == kind), key=lambda s: s[1])
        groups: list[list] = []   # segments whose positions lie within tol of the group's first
        for s_ in ss:
            if groups and s_[1] - groups[-1][0][1] <= tol:
                groups[-1].append(s_)
            else:
                groups.append([s_])
        for g in groups:
            pos = sum(x[1] for x in g) / len(g)
            cur = None
            for _, _, lo, hi in sorted(g, key=lambda x: x[2]):
                if cur and lo <= cur[1] + gap:
                    cur[1] = max(cur[1], hi)
                else:
                    cur = [lo, hi]
                    walls[kind].append((pos, cur))
        walls[kind] = [(pos, c[0], c[1]) for pos, c in walls[kind] if c[1] - c[0] >= min_len]
    return walls


# ---------- rectangle search ----------

def _closed_rects(label_c, walls, k):
    """All closed rectangles around the label centre from the nearest candidate lines per side."""
    cx, cy = label_c
    n = CFG["candidates_per_side"]
    ctol = CFG["corner_tol_mm"] / k
    L = sorted((w for w in walls["v"] if w[0] < cx and w[1] - ctol <= cy <= w[2] + ctol), key=lambda w: -w[0])[:n]
    R = sorted((w for w in walls["v"] if w[0] > cx and w[1] - ctol <= cy <= w[2] + ctol), key=lambda w: w[0])[:n]
    T = sorted((w for w in walls["h"] if w[0] < cy and w[1] - ctol <= cx <= w[2] + ctol), key=lambda w: -w[0])[:n]
    B = sorted((w for w in walls["h"] if w[0] > cy and w[1] - ctol <= cx <= w[2] + ctol), key=lambda w: w[0])[:n]
    out = []
    for l in L:
        for r in R:
            for t in T:
                if not (t[1] <= l[0] + ctol and t[2] >= r[0] - ctol):
                    continue
                for b in B:
                    if not (b[1] <= l[0] + ctol and b[2] >= r[0] - ctol):
                        continue
                    y0, y1 = t[0], b[0]
                    if (l[1] <= y0 + ctol and l[2] >= y1 - ctol and r[1] <= y0 + ctol
                            and r[2] >= y1 - ctol):
                        out.append((l[0], y0, r[0], y1))
    return out


def find_room_rect(label_c, walls, k) -> tuple[Rect | None, str]:
    """(rect, reason). reason is 'ok', 'no_rect' or 'ambiguous'."""
    rects = _closed_rects(label_c, walls, k)
    lo, hi = CFG["min_room_side_mm"] / k, CFG["max_room_side_mm"] / k
    rects = [r for r in rects if lo <= r[2] - r[0] <= hi and lo <= r[3] - r[1] <= hi]
    if not rects:
        return None, "no_rect"
    rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    inner = rects[0]
    gap = CFG["min_nest_gap_mm"] / k
    for o in rects[1:]:   # an enclosing rectangle clear of the inner one on every side: which is the room?
        if (inner[0] - o[0] >= gap and inner[1] - o[1] >= gap
                and o[2] - inner[2] >= gap and o[3] - inner[3] >= gap):
            return None, "ambiguous"
    return inner, "ok"


# ---------- facts ----------

def _label_bbox(el) -> Rect | None:
    s = (el.get("properties") or {}).get("text_label_bbox")
    if isinstance(s, str):
        try:
            v = tuple(float(x) for x in s.split(","))
            if len(v) == 4:
                return v
        except ValueError:
            pass
    bb = (el.get("provenance") or {}).get("bbox")
    return tuple(bb) if bb else None


def _inside_frac(inner: Rect, outer: Rect) -> float:
    """Fraction of the inner box's area that lies within the outer box."""
    w = min(inner[2], outer[2]) - max(inner[0], outer[0])
    h = min(inner[3], outer[3]) - max(inner[1], outer[1])
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return max(w, 0) * max(h, 0) / area if area > 0 else 0.0


def _contains_point(r: Rect, p) -> bool:
    return r[0] < p[0] < r[2] and r[1] < p[1] < r[3]


def classify(el, rect: Rect, k: float, others: list[tuple[str, tuple[float, float]]]) -> dict:
    """Measurements + checks for one element and its rectangle. Pure: no mutation."""
    w, h = (rect[2] - rect[0]) * k, (rect[3] - rect[1]) * k
    long_, short = max(w, h), min(w, h)
    area_m2 = long_ * short / 1e6
    printed = (el.get("properties") or {}).get(CFG["area_property"])
    allowed = set(CFG["nested_allowed"].get(el["type"], []))
    other_inside = [t for t, c in others if t not in allowed and _contains_point(rect, c)]
    prov_bb = (el.get("provenance") or {}).get("bbox")
    outline_ok = bool(prov_bb) and _inside_frac(tuple(prov_bb), rect) >= CFG["bbox_inside_min_frac"]
    res = {"long": round(long_, 1), "short": round(short, 1), "area_m2": round(area_m2, 2),
           "printed": printed, "err": None, "outline_ok": outline_ok, "other_inside": other_inside}
    if isinstance(printed, (int, float)) and printed > 0:
        res["err"] = area_m2 / printed - 1
        if abs(res["err"]) > CFG["area_tolerance"]:
            res["check"] = "disagree"
        elif outline_ok:
            res["check"] = "confirmed"
        else:
            res["check"] = "agree_unconfirmed"
    else:
        res["check"] = "no_printed_area"
    res["conf"] = CONFIRMED_CONF if res["check"] == "confirmed" else vm.CONF_VECTOR
    return res


def locate_rooms(facts: dict, drawings, scale: int) -> dict[str, tuple]:
    """element id -> (rect | None, reason) for every room-type element with a usable label."""
    k = vm.mm_per_pt(scale)
    walls = merge_walls(_axis_segments(drawings), k)
    out = {}
    for el in facts.get("elements", []):
        if el.get("type") not in CFG["room_types"]:
            continue
        lb = _label_bbox(el)
        if not lb:
            out[el["id"]] = (None, "no_label")
            continue
        out[el["id"]] = find_room_rect(((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2), walls, k)
    return out


def _label_centres(facts):
    out = []
    for el in facts.get("elements", []):
        if el.get("type") in CFG["label_types"]:
            lb = _label_bbox(el)
            if lb:
                out.append((el["id"], el["type"], ((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2)))
    return out


def apply_rooms(facts: dict, pdf: str | Path, scale: int, page: int = 1, located=None) -> dict:
    """Add room_long_side / room_short_side (mm) to cabin/toilet elements. Mutates `facts`."""
    if located is None:
        with pymupdf.open(pdf) as doc:
            located = locate_rooms(facts, doc[page - 1].get_drawings(), scale)
    k = vm.mm_per_pt(scale)
    centres = _label_centres(facts)
    stats = {"rooms": len(located), "measured": 0, "kept_existing": 0, "skipped_no_rect": 0,
             "skipped_ambiguous": 0, "skipped_other_label": 0, "confirmed": 0, "agree_unconfirmed": 0, "disagree": 0,
             "no_printed_area": 0}
    for el in facts.get("elements", []):
        if el["id"] not in located:
            continue
        props = el.setdefault("properties", {})
        if "room_long_side" in props or "room_short_side" in props:
            stats["kept_existing"] += 1
            continue
        rect, why = located[el["id"]]
        if rect is None:
            stats["skipped_ambiguous" if why == "ambiguous" else "skipped_no_rect"] += 1
            continue
        others = [(t, c) for i, t, c in centres if i != el["id"]]
        r = classify(el, rect, k, others)
        if r["other_inside"]:   # the rectangle spans another room: not this room's outline
            stats["skipped_other_label"] += 1
            continue
        old = el.get("provenance") or {}
        props["room_long_side"] = r["long"]
        props["room_short_side"] = r["short"]
        props["room_area_vector_m2"] = r["area_m2"]
        props["room_area_check"] = r["check"]
        if r["err"] is not None:
            props["room_area_error"] = round(r["err"], 3)
        if old.get("bbox"):
            props["prev_provenance"] = (f"{old.get('method')}:{old.get('confidence')}:"
                                        + ",".join(f"{v:.1f}" for v in old["bbox"]))
        el["provenance"] = {"file": str(old.get("file") or pdf), "page": page, "bbox": list(rect),
                            "element_id": None, "method": "vector", "confidence": r["conf"]}
        stats["measured"] += 1
        stats[r["check"]] += 1
    return stats
