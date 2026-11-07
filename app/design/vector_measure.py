"""Spike: measure door-swing widths from the vector geometry of a GA drawing.

A plan-view hinged door is drawn as a quarter-circle swing arc whose radius equals the
leaf length, plus a thin leaf line from the hinge to one end of the arc. The radius
(hinge to latch) is the nominal door width. Everything is geometric and approximate:
results are low-confidence candidates (never above CONF_MAX) and only fill clear_width
when no value exists. Scale comes from the stated drawing scale in the text layer.
Limits and measured accuracy: docs/VECTOR.md.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pymupdf
from pydantic import BaseModel

BBox = tuple[float, float, float, float]

PT_MM = 25.4 / 72          # one PDF point on paper, in mm
CONF_MAX = 0.6
MIN_WIDTH_MM, MAX_WIDTH_MM = 500.0, 1500.0   # sanity limits for a single door leaf
MIN_SPAN_DEG, MAX_SPAN_DEG = 65.0, 115.0     # swing arcs are quarter circles
MAX_RMS_FRAC = 0.02                          # circle-fit residual / radius
LEAF_TOL_FRAC = 0.1


class DoorCandidate(BaseModel):
    width_mm: float
    bbox: BBox                    # PDF points
    center: tuple[float, float]   # hinge, PDF points
    radius_pt: float
    span_deg: float
    rms_frac: float


# ---------- scale ----------

def parse_scale(text: str) -> int | None:
    """'Scale (U.N.O.): 1:150' -> 150. Only 1:N reductions are accepted."""
    m = re.search(r"(?<![\d:])1\s*:\s*(\d{1,4})(?!\d)", text)
    return int(m.group(1)) if m else None


def mm_per_pt(scale: int) -> float:
    """Real-world mm represented by one PDF point at 1:`scale`."""
    return PT_MM * scale


def find_scale(path: str | Path) -> int | None:
    """Scale stated next to a 'Scale' label in the text layer (never guessed)."""
    with pymupdf.open(path) as doc:
        for page in doc:
            words = page.get_text("words")
            for w in words:
                if w[4].lower().startswith("scale"):
                    near = [v for v in words if abs(v[1] - w[1]) < 15 and 0 <= v[0] - w[0] < 400]
                    near.sort(key=lambda v: v[0])
                    s = parse_scale(" ".join(v[4] for v in near))
                    if s:
                        return s
    return None


def scale_error(span_pt: float, known_mm: float, scale: int) -> float:
    """Relative error of a measured span vs a known printed dimension (+ = drawing too long)."""
    return span_pt * mm_per_pt(scale) / known_mm - 1


# ---------- geometry ----------

def fit_circle(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Algebraic (Kasa) circle fit -> cx, cy, r, rms radial residual."""
    a = np.asarray(pts, float)
    A = np.c_[2 * a[:, 0], 2 * a[:, 1], np.ones(len(a))]
    b = (a ** 2).sum(1)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0], sol[1]
    r = math.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0))
    rms = float(np.sqrt(np.mean((np.hypot(a[:, 0] - cx, a[:, 1] - cy) - r) ** 2)))
    return float(cx), float(cy), r, rms


def _bezier(p0, p1, p2, p3, n=6):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def path_points(items) -> list[tuple[float, float]] | None:
    """Ordered points of a path made only of connected 'l'/'c' items, else None."""
    pts: list[tuple[float, float]] = []
    for it in items:
        if it[0] == "l":
            seg = [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "c":
            seg = _bezier(*[(q.x, q.y) for q in it[1:5]])
        else:
            return None
        if pts and math.dist(pts[-1], seg[0]) > 0.5:
            return None
        pts.extend(seg if not pts else seg[1:])
    return pts or None


def _span_deg(pts, c) -> float:
    ang = np.unwrap([math.atan2(y - c[1], x - c[0]) for x, y in pts])
    return abs(math.degrees(float(ang[-1] - ang[0])))


def arc_from_points(pts) -> tuple[float, float, float, float, float] | None:
    """(cx, cy, r, span_deg, rms_frac) if the points form a single circular arc, else None."""
    if len(pts) > 4 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]  # path closed back onto its start by a chord: drop the chord
    if len(pts) < 4 or math.dist(pts[0], pts[-1]) < 1e-6:
        return None
    cx, cy, r, rms = fit_circle(pts)
    if r <= 0 or rms / r > MAX_RMS_FRAC:
        return None
    return cx, cy, r, _span_deg(pts, (cx, cy)), rms / r


def _thin_rect_axis(r):
    w, h = r.width, r.height
    if min(w, h) > 0.2 * max(w, h):
        return None
    if w >= h:
        return (r.x0, (r.y0 + r.y1) / 2), (r.x1, (r.y0 + r.y1) / 2)
    return ((r.x0 + r.x1) / 2, r.y0), ((r.x0 + r.x1) / 2, r.y1)


def _straight_segments(drawings, rmin, rmax):
    """Straight segments (and thin rectangles as their centre line) of plausible leaf length."""
    segs = []
    for d in drawings:
        for it in d["items"]:
            if it[0] == "l":
                ab = ((it[1].x, it[1].y), (it[2].x, it[2].y))
            elif it[0] == "qu":
                ab = _thin_rect_axis(it[1].rect)
            elif it[0] == "re":
                ab = _thin_rect_axis(it[1])
            else:
                continue
            if ab and rmin * 0.8 <= math.dist(*ab) <= rmax * 1.2:
                segs.append(ab)
    return segs


def _index(segs, cell):
    grid = defaultdict(list)
    for a, b in segs:
        for p in (a, b):
            grid[(int(p[0] // cell), int(p[1] // cell))].append((a, b))
    return grid


def _has_leaf(grid, cell, center, tips, r) -> bool:
    tol = LEAF_TOL_FRAC * r + 0.8
    cx, cy = int(center[0] // cell), int(center[1] // cell)
    for gx in (cx - 1, cx, cx + 1):
        for gy in (cy - 1, cy, cy + 1):
            for a, b in grid.get((gx, gy), ()):
                for p, q in ((a, b), (b, a)):
                    if math.dist(p, center) <= tol and any(math.dist(q, t) <= tol for t in tips):
                        return True
    return False


def detect_door_arcs(drawings, scale: int) -> list[DoorCandidate]:
    """Quarter-circle swing arcs with a leaf line, sized as a plausible door at `scale`."""
    k = mm_per_pt(scale)
    rmin, rmax = MIN_WIDTH_MM / k, MAX_WIDTH_MM / k
    cands = []
    for d in drawings:
        r0 = d["rect"]
        if not (rmin * 0.7 <= max(r0.width, r0.height) <= rmax * 1.2):
            continue
        pts = path_points(d["items"])
        if pts is None:
            continue
        arc = arc_from_points(pts)
        if arc is None:
            continue
        cx, cy, r, span, rms = arc
        if not (rmin <= r <= rmax and MIN_SPAN_DEG <= span <= MAX_SPAN_DEG):
            continue
        cands.append((cx, cy, r, span, rms, pts))
    if not cands:
        return []
    cell = max(rmax, 5.0)
    grid = _index(_straight_segments(drawings, rmin, rmax), cell)
    out = []
    for cx, cy, r, span, rms, pts in cands:
        if not _has_leaf(grid, cell, (cx, cy), (pts[0], pts[-1]), r):
            continue
        xs = [cx] + [p[0] for p in pts]
        ys = [cy] + [p[1] for p in pts]
        out.append(DoorCandidate(
            width_mm=round(r * k, 1), bbox=(min(xs), min(ys), max(xs), max(ys)),
            center=(cx, cy), radius_pt=r, span_deg=span, rms_frac=rms))
    return out


def measure_doors(path: str | Path, scale: int, page_no: int = 1) -> list[DoorCandidate]:
    with pymupdf.open(path) as doc:
        return detect_door_arcs(doc[page_no - 1].get_drawings(), scale)


# ---------- facts ----------

CONF_VECTOR = 0.5   # nominal leaf size from the swing radius, not a net clear opening: below trust, needs_review


def _overlap(a, b, margin=2.0) -> bool:
    return a[0] < b[2] + margin and b[0] < a[2] + margin and a[1] < b[3] + margin and b[1] < a[3] + margin


def apply_to_facts(facts: dict, cands: list[DoorCandidate], file: str, page: int = 1,
                   add_new: bool = False) -> dict:
    """Add clear_width to door elements whose bbox meets a candidate; never overwrite a value.

    Candidates matching no door element are appended as new door elements only if `add_new`.
    Returns counts. Mutates `facts`.
    """
    stats = {"filled": 0, "kept_existing": 0, "added": 0, "unmatched": 0}
    used: set[int] = set()
    n = 0
    for el in facts.get("elements", []):
        if el.get("type") != "door":
            continue
        bb = (el.get("provenance") or {}).get("bbox")
        hits = [i for i, c in enumerate(cands) if bb and _overlap(c.bbox, tuple(bb))]
        if len(hits) != 1:
            continue  # none or ambiguous: never guess
        used.add(hits[0])
        props = el.setdefault("properties", {})
        if "clear_width" in props:
            stats["kept_existing"] += 1
            continue
        c = cands[hits[0]]
        props["clear_width"] = c.width_mm
        el["provenance"] = {"file": file, "page": page, "bbox": list(c.bbox), "element_id": None,
                            "method": "vector", "confidence": min(CONF_VECTOR, CONF_MAX)}
        stats["filled"] += 1
    for i, c in enumerate(cands):
        if i in used:
            continue
        if not add_new:
            stats["unmatched"] += 1
            continue
        n += 1
        facts.setdefault("elements", []).append({
            "id": f"door-vec-{n:03d}", "type": "door", "name": None, "deck": None, "space_type": None,
            "properties": {"clear_width": c.width_mm},
            "provenance": {"file": file, "page": page, "bbox": list(c.bbox), "element_id": None,
                           "method": "vector", "confidence": min(CONF_VECTOR, CONF_MAX)}})
        stats["added"] += 1
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Add vector-measured door widths to a facts JSON")
    ap.add_argument("facts")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--scale", type=int, help="override; default: read from the drawing text layer")
    ap.add_argument("--add-new", action="store_true", help="append unmatched swings as new door elements")
    a = ap.parse_args(argv)
    scale = a.scale or find_scale(a.pdf)
    if not scale:
        print("no stated scale found; refusing to measure (pass --scale to override)")
        return 2
    facts = json.loads(Path(a.facts).read_text())
    cands = measure_doors(a.pdf, scale, a.page)
    stats = apply_to_facts(facts, cands, a.pdf, a.page, a.add_new)
    Path(a.out).write_text(json.dumps(facts, indent=2))
    print(f"scale 1:{scale}; {len(cands)} swings; {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
