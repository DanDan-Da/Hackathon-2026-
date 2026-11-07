"""D4: overall extent of a geometry-only IFC mesh -> DesignFacts (`ship_extent`).

The real RCRV export is ~300 MB with 84k anonymous IfcBuildingElementProxy parts, each an
IfcTriangulatedFaceSet. Building geometry (ifcopenshell iterator) is far too slow for that, so
the file is streamed as text: only IfcCartesianPointList3D coordinates (per-list min/max) and the
IfcLocalPlacement chain are read. The bounding box of a point list's 8 corners is transformed by
the owning element's placement, so rotated placements are handled conservatively (the box can
only be as large or larger than the true one).

Limits: it is a bounding box of ALL parts, so masts, antennas, cranes and other appendages are
included. Unreferenced points in a list count too. Mapped items / swept solids are not read.
Confidence is therefore capped at CONF_BBOX. Result is cached in .cache/ by file size + mtime.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np

from app.check.units import to_base
from app.models import DesignElement, DesignFacts, Provenance

CONF_BBOX = 0.6   # a bbox incl. appendages is not "length overall" of the hull
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / ".cache"

_HEAD = re.compile(r"#(\d+)\s*=\s*(IFC\w+)\s*\(")
_REFS = re.compile(r"#(\d+)")
_PRODUCT = re.compile(
    r"'[^']*',(?:#\d+|\$),(?:'[^']*'|\$),(?:'[^']*'|\$),(?:'[^']*'|\$),(#\d+|\$),(#\d+|\$)")
_PREFIX = {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, "KILO": 1e3, None: 1.0}


def _numbers(text: str) -> np.ndarray:
    return np.fromstring(re.sub(r"[()]", " ", text), sep=",")


def _entities(path: Path):
    """Yield (id, NAME, argument text) per entity; statements may wrap over several lines."""
    buf: list[str] = []
    with open(path, "r", errors="replace", buffering=1 << 20) as fh:
        for line in fh:
            if not buf and not line.startswith("#"):
                continue
            buf.append(line.rstrip("\r\n"))
            if line.rstrip().endswith(";"):
                text = "".join(buf)
                buf = []
                m = _HEAD.match(text)
                if m:
                    yield int(m[1]), m[2], text[m.end():]


def _matrix(loc, z, x) -> np.ndarray:
    m = np.eye(4)
    if z is not None or x is not None:
        zv = np.array(z if z is not None else (0, 0, 1), float)
        xv = np.array(x if x is not None else (1, 0, 0), float)
        zv = zv / np.linalg.norm(zv)
        xv = xv - zv * xv.dot(zv)
        n = np.linalg.norm(xv)
        if n < 1e-9:   # degenerate ref direction: fall back to any perpendicular
            xv = np.cross(zv, (0, 1, 0) if abs(zv[1]) < 0.9 else (1, 0, 0)); n = np.linalg.norm(xv)
        xv = xv / n
        m[:3, 0], m[:3, 1], m[:3, 2] = xv, np.cross(zv, xv), zv
    if loc is not None:
        m[:3, 3] = loc
    return m


def _scan(path: Path) -> dict:
    scale = 1.0   # file length unit -> mm
    unit_seen = False
    points, dirs, axes, places = {}, {}, {}, {}
    plist: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    fset: dict[int, int] = {}
    reps: dict[int, list[int]] = {}      # shape rep / product def shape -> child ids
    elems: list[tuple[int, int | None, int | None]] = []
    n_coords = 0
    for eid, name, args in _entities(path):
        if name == "IFCCARTESIANPOINTLIST3D":
            a = _numbers(args[: args.find("))") + 2] if "))" in args else args)
            if a.size >= 3 and a.size % 3 == 0:
                a = a.reshape(-1, 3)
                plist[eid] = (a.min(axis=0), a.max(axis=0))
                n_coords += len(a)
        elif name == "IFCTRIANGULATEDFACESET":
            m = _REFS.match(args)
            if m:
                fset[eid] = int(m[1])
        elif name == "IFCSIUNIT" and ".LENGTHUNIT." in args:
            pre = re.search(r"\.(MILLI|CENTI|DECI|KILO)\.", args)
            if ".METRE." not in args:
                raise ValueError("unsupported length unit in IFC")
            scale = to_base(_PREFIX[pre[1] if pre else None], "m")[0]
            unit_seen = True
        elif name == "IFCCARTESIANPOINT":
            points[eid] = _numbers(args.rstrip(");"))
        elif name == "IFCDIRECTION":
            dirs[eid] = _numbers(args.rstrip(");"))
        elif name == "IFCAXIS2PLACEMENT3D":
            r = [None if t == "$" else int(t[1:]) for t in re.findall(r"#\d+|\$", args)[:3]]
            axes[eid] = r
        elif name == "IFCLOCALPLACEMENT":
            r = re.findall(r"#\d+|\$", args)[:2]
            places[eid] = tuple(None if t == "$" else int(t[1:]) for t in r)
        elif name in ("IFCSHAPEREPRESENTATION", "IFCPRODUCTDEFINITIONSHAPE"):
            tail = args[args.rfind("(") :]
            reps[eid] = [int(i) for i in _REFS.findall(tail)]
        else:
            m = _PRODUCT.match(args)
            if m and name != "IFCPROJECT":
                pl = None if m[1] == "$" else int(m[1][1:])
                rp = None if m[2] == "$" else int(m[2][1:])
                if rp is not None:
                    elems.append((eid, pl, rp))
    if not plist:
        raise ValueError(f"no IfcCartesianPointList3D geometry found in {path}")

    cache: dict[int, np.ndarray] = {}

    def axis_m(aid):
        loc, z, x = axes.get(aid, [None] * 3)
        g = lambda d, i: None if i is None or i not in d else d[i][:3] if len(d[i]) >= 3 else np.append(d[i], 0.0)
        pt = points.get(loc)
        return _matrix(None if pt is None else np.append(pt, [0.0] * (3 - len(pt)))[:3], g(dirs, z), g(dirs, x))

    def place_m(pid):
        if pid is None or pid not in places:
            return np.eye(4)
        if pid not in cache:
            chain, cur = [], pid
            while cur is not None and cur in places and cur not in cache:
                chain.append(cur); cur = places[cur][0]
            base = cache[cur] if cur in cache else np.eye(4)
            for p in reversed(chain):
                base = base @ axis_m(places[p][1]); cache[p] = base
        return cache[pid]

    lo = np.full(3, np.inf); hi = np.full(3, -np.inf)
    used = 0
    for _eid, pl, rp in elems:
        ids = [c for r in reps.get(rp, []) for c in (reps.get(r, [r]) if r in reps else [r])]
        boxes = [plist[fset[i]] for i in ids if i in fset and fset[i] in plist]
        if not boxes:
            continue
        m = place_m(pl)
        for bmin, bmax in boxes:
            corners = np.array([[x, y, z, 1.0] for x in (bmin[0], bmax[0])
                                for y in (bmin[1], bmax[1]) for z in (bmin[2], bmax[2])])
            w = (corners @ m.T)[:, :3]
            lo = np.minimum(lo, w.min(axis=0)); hi = np.maximum(hi, w.max(axis=0))
        used += 1
    if used == 0:
        raise ValueError(f"no element with mesh geometry found in {path}")
    return {"min": (lo * scale).tolist(), "max": (hi * scale).tolist(), "parts": used,
            "points": n_coords, "unit_declared": unit_seen}


def _cache_file(path: Path, cache_dir: Path) -> Path:
    st = path.stat()
    key = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:12]
    return cache_dir / f"mesh_{key}_{st.st_size}_{st.st_mtime_ns}.json"


def read_mesh_extent(path: str | Path, project: str | None = None,
                     cache_dir: str | Path | None = None) -> DesignFacts:
    import json

    path = Path(path)
    cdir = Path(cache_dir) if cache_dir else DEFAULT_CACHE
    cf = _cache_file(path, cdir)
    if cf.exists():
        scan = json.loads(cf.read_text())
    else:
        scan = _scan(path)
        cdir.mkdir(parents=True, exist_ok=True)
        cf.write_text(json.dumps(scan))
    ext = [h - l for l, h in zip(scan["min"], scan["max"])]
    # Horizontal axis with the larger extent is taken as the ship's length (no heading metadata).
    ax = 0 if ext[0] >= ext[1] else 1
    props = {"length_overall": ext[ax], "beam": ext[1 - ax], "height": ext[2],
             "length_axis": "XY"[ax], "part_count": float(scan["parts"]),
             "note": "bounding box of all mesh parts incl. masts and appendages"}
    el = DesignElement(
        id="ship_extent", type="ship_extent", name="Mesh bounding box",
        properties=props,
        provenance=Provenance(file=str(path), method="mesh", confidence=CONF_BBOX))
    return DesignFacts(project=project or path.stem, elements=[el], source_files=[str(path)])
