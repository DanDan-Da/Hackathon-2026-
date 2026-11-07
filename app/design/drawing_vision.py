"""D2: GA drawing -> DesignFacts via a vision LLM.

Pipeline: render each page at `dpi`, cut into overlapping tiles (labels on a tile edge are
whole in the neighbour), skip blank tiles, ask the vision model for structured elements per
tile, map tile pixels back to PDF points, merge duplicates from the overlap bands.

Accuracy rules:
- The model reports what it SEES, including the verbatim text (`evidence_text`).
- Numbers are converted by our own parser (pdf_text.parse_dimension_mm), never by the model;
  an unparseable value is dropped -> the evaluator says needs_review, it never guesses.
- Ship particulars come from the PDF text layer (D1) when there is one.

CLI:  python -m app.design.drawing_vision designs/<project>/ga.pdf [--dpi 200]
      -> writes designs/<project>/facts.json
"""
from __future__ import annotations

import argparse
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field

from app.check.units import to_base
from app.config import settings
from app.design.pdf_text import extract_lines, has_text_layer, parse_dimension_mm, parse_particulars
from app.models import DesignElement, DesignFacts, Provenance
from app.providers.llm import LLMProvider, get_llm

DEFAULT_DPI = 200
DEFAULT_TILE_PX = 1568      # Claude's max long edge; larger images are downscaled anyway
DEFAULT_OVERLAP_PX = 200
MERGE_IOU = 0.3
MERGE_CONTAINMENT = 0.9     # same-named boxes where one lies (almost) inside the other are one element
COUNT_PROPERTIES = {"capacity", "persons", "count", "steps", "berths"}
AREA_PROPERTIES = {"area", "floor_area", "deck_area"}
_AREA = re.compile(r"^\s*(\d[\d ]*(?:[.,]\d+)?)\s*(m2|m²|m\^2|sq\.?\s*m|ft2|ft²|sq\.?\s*ft)?\s*$", re.I)


# ---------- structured output schema (what the model must return per tile) ----------

class TileProperty(BaseModel):
    name: str = Field(description="Normalised name: clear_width, width, length, height, area, capacity …")
    text: str = Field(description="The value exactly as printed on the drawing, e.g. '800', '0.8 m', '2\\'-8\"'")


class TileElement(BaseModel):
    type: str = Field(description="door, corridor, stairway, cabin, lifeboat, liferaft, muster_station, "
                                  "space, toilet, elevator … (lowercase, singular)")
    name: str | None = Field(None, description="Label as printed, e.g. 'CABIN 101', 'DAY ROOM'")
    space_type: str | None = Field(None, description="Use only if the drawing states it, e.g. "
                                                     "'accessible_route', 'escape', 'accommodation'")
    deck: str | None = Field(None, description="Deck name/number if printed on this tile")
    box_2d: list[float] = Field(description="[ymin, xmin, ymax, xmax] of the element in THIS tile image, "
                                            "normalised to 0-1000")
    properties: list[TileProperty] = Field(default_factory=list,
                                           description="Only dimensions/values that are printed")
    evidence_text: str = Field(description="Verbatim text you read for this element ('' if none)")
    confidence: float = Field(description="0..1, how sure you are of type, location and values")


class TileExtraction(BaseModel):
    elements: list[TileElement]


SYSTEM_PROMPT = """You read ship General Arrangement (GA) drawings for a class & regulatory
compliance checker. Accuracy matters more than completeness.

Rules:
- Report only elements you can actually see on this tile: doors, corridors, stairways, cabins,
  lifeboats/liferafts, muster stations, toilets, elevators and other labelled spaces.
- box_2d must tightly enclose the element: [ymin, xmin, ymax, xmax] normalised to 0-1000
  of THIS tile image.
- properties: only values printed on the drawing (dimension strings, capacities). Copy the
  value text exactly as printed; do not convert units, do not estimate from scale.
- space_type / deck: only when stated on the drawing; otherwise null.
- evidence_text: the exact label/dimension text you read.
- confidence: lower it for blurry, partly cut-off or ambiguous items. Elements cut by the tile
  edge are fine — the neighbouring tile overlaps.
- If the tile has nothing relevant, return an empty list."""


# ---------- tiling ----------

class Tile(BaseModel):
    page: int                          # 1-based
    origin_pt: tuple[float, float]     # top-left of the tile in PDF points
    pt_per_px: float
    size_px: tuple[int, int]
    png: bytes


def _starts(total: int, tile: int, step: int) -> list[int]:
    return list(range(0, max(total - (tile - step), 1), step)) or [0]


def render_tiles(path: str | Path, dpi: int = DEFAULT_DPI, tile_px: int = DEFAULT_TILE_PX,
                 overlap_px: int = DEFAULT_OVERLAP_PX) -> list[Tile]:
    if overlap_px >= tile_px:
        raise ValueError("overlap_px must be smaller than tile_px")
    scale = dpi / 72.0
    step = tile_px - overlap_px
    tiles: list[Tile] = []
    with pymupdf.open(path) as doc:
        for pno, page in enumerate(doc, start=1):
            w_px, h_px = int(page.rect.width * scale), int(page.rect.height * scale)
            for y in _starts(h_px, tile_px, step):
                for x in _starts(w_px, tile_px, step):
                    clip = pymupdf.Rect(x / scale, y / scale,
                                        min(x + tile_px, w_px) / scale, min(y + tile_px, h_px) / scale)
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
                    samples = pix.samples
                    if not samples.strip(samples[:1]):   # one colour only (blank margin): skip
                        continue                          # (C-speed; pix.is_unicolor is ~50x slower)
                    tiles.append(Tile(page=pno, origin_pt=(x / scale, y / scale), pt_per_px=1 / scale,
                                      size_px=(pix.width, pix.height), png=pix.tobytes("png")))
    return tiles


# ---------- extraction ----------

def _tile_prompt(tile: Tile) -> str:
    w, h = tile.size_px
    return (f"Tile of page={tile.page}, origin=({tile.origin_pt[0]:.0f},{tile.origin_pt[1]:.0f}) pt, "
            f"size {w}x{h} px. Extract the GA elements on this tile.")


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _area_m2(text: str) -> float | None:
    m = _AREA.match(text)
    if not m:
        return None
    value = float(m[1].replace(" ", "").replace(",", "."))
    unit = (m[2] or "m2").lower().replace("²", "2").replace("^", "").replace(" ", "").replace(".", "")
    return to_base(value, {"sqm": "m2", "sqft": "ft2"}.get(unit, unit))[0]


def _properties(props: list[TileProperty]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in props:
        key = re.sub(r"\W+", "_", p.name.strip().lower()).strip("_")
        if key in AREA_PROPERTIES:
            value = _area_m2(p.text)
        elif key in COUNT_PROPERTIES:
            m = re.fullmatch(r"\s*(\d+)\s*\w*\s*", p.text)
            value = float(m[1]) if m else None
        else:
            value = parse_dimension_mm(p.text)   # drawings are in mm unless a unit is printed
        if value is not None:
            out[key] = value
    return out


def _to_candidates(tile: Tile, extraction: TileExtraction, file: str) -> list[tuple[TileElement, Provenance]]:
    ox, oy = tile.origin_pt
    s = tile.pt_per_px
    out = []
    for el in extraction.elements:
        if len(el.box_2d) != 4:
            continue
        w_px, h_px = tile.size_px                       # edge tiles are smaller: use the real size
        ymin, xmin, ymax, xmax = (min(1000.0, max(0.0, v)) for v in el.box_2d)
        xa, xb = sorted((xmin, xmax))
        ya, yb = sorted((ymin, ymax))
        bbox = (ox + xa / 1000 * w_px * s, oy + ya / 1000 * h_px * s,
                ox + xb / 1000 * w_px * s, oy + yb / 1000 * h_px * s)
        conf = min(1.0, max(0.0, el.confidence))
        out.append((el, Provenance(file=file, page=tile.page, bbox=bbox, method="vision", confidence=conf)))
    return out


_AREA_IN_NAME = re.compile(r"\d[\d ]*(?:[.,]\d+)?\s*(?:m2|m²|m\^2|sq\.?\s*m)\b", re.I)


def _name_key(name: str | None) -> str:
    """Vision names may embed the area ("DAY ROOM 39 m²"); compare on the label alone."""
    return re.sub(r"[^\w]+", " ", _AREA_IN_NAME.sub("", name or "").casefold()).strip()


def _containment(a, b) -> float:
    """Overlap as a share of the smaller box (1.0 = one box lies fully inside the other)."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / smaller if smaller > 0 else 0.0


def _same_element(a: tuple[TileElement, Provenance], b: tuple[TileElement, Provenance]) -> bool:
    (ea, pa), (eb, pb) = a, b
    if ea.type.lower() != eb.type.lower() or pa.page != pb.page:
        return False
    na, nb = _name_key(ea.name), _name_key(eb.name)
    if na and nb and na != nb:
        return False                    # two differently named elements are never one element
    if _iou(pa.bbox, pb.bbox) >= MERGE_IOU:
        return True
    return bool(na) and na == nb and _containment(pa.bbox, pb.bbox) >= MERGE_CONTAINMENT


def _merge(cands: list[tuple[TileElement, Provenance]]) -> list[tuple[TileElement, Provenance]]:
    """Same element seen twice (overlapping tiles, or read twice with different boxes) -> keep the
    fuller read (more properties), then the more confident one."""
    kept: list[tuple[TileElement, Provenance]] = []
    for cand in sorted(cands, key=lambda c: (-len(c[0].properties), -c[1].confidence)):
        if not any(_same_element(k, cand) for k in kept):
            kept.append(cand)
    return kept


def _cache_key(pdf_hash: str, model: str, tile: Tile, dpi: int) -> str:
    """Changes whenever the drawing, model, prompt or tile geometry changes, so stale reads are impossible."""
    parts = [pdf_hash, model, hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), str(dpi),
             str(tile.page), *map(str, tile.origin_pt), *map(str, tile.size_px)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def extract_drawing(path: str | Path, project: str, llm: LLMProvider | None = None,
                    dpi: int = DEFAULT_DPI, tile_px: int = DEFAULT_TILE_PX,
                    overlap_px: int = DEFAULT_OVERLAP_PX, cache_dir: str | Path | None = None) -> DesignFacts:
    """`cache_dir` makes a run resumable: each tile's AI answer is stored there and reused on a rerun."""
    llm = llm or get_llm()
    file = str(path)
    tiles = render_tiles(path, dpi=dpi, tile_px=tile_px, overlap_px=overlap_px)
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        pdf_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        model = str(getattr(llm, "model", type(llm).__name__))

    def ask(tile: Tile) -> TileExtraction:
        entry = cache / f"{_cache_key(pdf_hash, model, tile, dpi)}.json" if cache else None
        if entry is not None and entry.exists():
            return TileExtraction.model_validate_json(entry.read_text())
        result = llm.complete_structured(SYSTEM_PROMPT, _tile_prompt(tile), TileExtraction,
                                         images_png=[tile.png])
        if entry is not None:
            entry.write_text(result.model_dump_json())
        return result

    with ThreadPoolExecutor(max_workers=max(1, settings.llm_max_parallel)) as pool:
        results = list(pool.map(ask, tiles))

    cands = [c for tile, res in zip(tiles, results) for c in _to_candidates(tile, res, file)]
    merged = sorted(_merge(cands), key=lambda c: (c[1].page, c[1].bbox[1], c[1].bbox[0]))

    elements = []
    for i, (el, prov) in enumerate(merged):
        etype = el.type.strip().lower()
        elements.append(DesignElement(
            id=f"{etype}-p{prov.page}-{i:03d}", type=etype, name=el.name, deck=el.deck,
            space_type=el.space_type, properties=_properties(el.properties), provenance=prov))

    text_layer = has_text_layer(path)
    particulars = parse_particulars(path).to_ship_particulars() if text_layer else None
    facts = DesignFacts(project=project, elements=elements, source_files=[file])
    if text_layer:   # D3: the text layer is exact; confirm, correct or cap the vision reads
        from app.design.crosscheck import crosscheck   # late import: crosscheck reads constants from here
        facts, _report = crosscheck(facts, extract_lines(path))
    if particulars is not None:
        facts.particulars = particulars
    return facts


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract DesignFacts from a GA drawing PDF")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--project", default=None, help="defaults to the PDF's parent folder name")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--out", type=Path, default=None, help="defaults to <pdf folder>/facts.json")
    ap.add_argument("--cache", type=Path, default=None,
                    help="tile cache folder, defaults to <pdf folder>/.cache (a stopped run resumes from it)")
    args = ap.parse_args()
    facts = extract_drawing(args.pdf, project=args.project or args.pdf.parent.name, dpi=args.dpi,
                            cache_dir=args.cache or args.pdf.parent / ".cache")
    out = args.out or args.pdf.parent / "facts.json"
    out.write_text(facts.model_dump_json(indent=2))
    print(f"{len(facts.elements)} elements -> {out}")


if __name__ == "__main__":
    main()
