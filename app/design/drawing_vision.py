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
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from pydantic import BaseModel, Field

from app.check.units import to_base
from app.design.pdf_text import has_text_layer, parse_dimension_mm, parse_particulars
from app.models import DesignElement, DesignFacts, Provenance
from app.providers.llm import LLMProvider, get_llm

DEFAULT_DPI = 200
DEFAULT_TILE_PX = 1568      # Claude's max long edge; larger images are downscaled anyway
DEFAULT_OVERLAP_PX = 200
MERGE_IOU = 0.3
MAX_PARALLEL = 6
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
    bbox_px: list[float] = Field(description="[x0, y0, x1, y1] in pixels of THIS tile image")
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
- bbox_px must tightly enclose the element in THIS image's pixel coordinates.
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
        if len(el.bbox_px) != 4:
            continue
        x0, y0, x1, y1 = el.bbox_px
        bbox = (ox + min(x0, x1) * s, oy + min(y0, y1) * s, ox + max(x0, x1) * s, oy + max(y0, y1) * s)
        conf = min(1.0, max(0.0, el.confidence))
        out.append((el, Provenance(file=file, page=tile.page, bbox=bbox, method="vision", confidence=conf)))
    return out


def _merge(cands: list[tuple[TileElement, Provenance]]) -> list[tuple[TileElement, Provenance]]:
    """Same element seen in two overlapping tiles -> keep the more confident read."""
    kept: list[tuple[TileElement, Provenance]] = []
    for el, prov in sorted(cands, key=lambda c: -c[1].confidence):
        dup = any(k.type.lower() == el.type.lower() and kp.page == prov.page
                  and _iou(kp.bbox, prov.bbox) >= MERGE_IOU for k, kp in kept)
        if not dup:
            kept.append((el, prov))
    return kept


def extract_drawing(path: str | Path, project: str, llm: LLMProvider | None = None,
                    dpi: int = DEFAULT_DPI, tile_px: int = DEFAULT_TILE_PX,
                    overlap_px: int = DEFAULT_OVERLAP_PX) -> DesignFacts:
    llm = llm or get_llm()
    file = str(path)
    tiles = render_tiles(path, dpi=dpi, tile_px=tile_px, overlap_px=overlap_px)

    def ask(tile: Tile) -> TileExtraction:
        return llm.complete_structured(SYSTEM_PROMPT, _tile_prompt(tile), TileExtraction,
                                       images_png=[tile.png])

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        results = list(pool.map(ask, tiles))

    cands = [c for tile, res in zip(tiles, results) for c in _to_candidates(tile, res, file)]
    merged = sorted(_merge(cands), key=lambda c: (c[1].page, c[1].bbox[1], c[1].bbox[0]))

    elements = []
    for i, (el, prov) in enumerate(merged):
        etype = el.type.strip().lower()
        elements.append(DesignElement(
            id=f"{etype}-p{prov.page}-{i:03d}", type=etype, name=el.name, deck=el.deck,
            space_type=el.space_type, properties=_properties(el.properties), provenance=prov))

    particulars = parse_particulars(path).to_ship_particulars() if has_text_layer(path) else None
    facts = DesignFacts(project=project, elements=elements, source_files=[file])
    if particulars is not None:
        facts.particulars = particulars
    return facts


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract DesignFacts from a GA drawing PDF")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--project", default=None, help="defaults to the PDF's parent folder name")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    ap.add_argument("--out", type=Path, default=None, help="defaults to <pdf folder>/facts.json")
    args = ap.parse_args()
    facts = extract_drawing(args.pdf, project=args.project or args.pdf.parent.name, dpi=args.dpi)
    out = args.out or args.pdf.parent / "facts.json"
    out.write_text(facts.model_dump_json(indent=2))
    print(f"{len(facts.elements)} elements -> {out}")


if __name__ == "__main__":
    main()
