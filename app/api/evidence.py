"""Read-only evidence crops: render a bbox region of a design PDF page as PNG.

The file path (as stored in provenance.file) must resolve to a file inside settings.designs_dir.
"""
from __future__ import annotations

from pathlib import Path

import fitz
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.config import settings

router = APIRouter(prefix="/evidence", tags=["evidence"])
PAD_PT = 40        # context around the bbox, PDF points
SCALE = 2.0


def resolve_design_file(rel: str) -> Path:
    """Accept the file as readers store it in provenance.file: relative to the designs folder, relative
    to the working directory (e.g. "designs/p1/ga.pdf"), or absolute. Whatever the form, the resolved
    path must lie inside the designs folder."""
    root = settings.designs_dir.resolve()
    if "\x00" in rel:
        raise HTTPException(400, "Invalid file path")
    given = Path(rel)
    candidates = [given] if given.is_absolute() else [root / given, given]
    inside = [p.resolve() for p in candidates if p.resolve().is_relative_to(root)]
    if not inside:
        raise HTTPException(400, "File must be inside the designs folder")
    path = next((p for p in inside if p.is_file()), inside[0])
    if path.suffix.lower() != ".pdf":
        raise HTTPException(400, "Only PDF files can be rendered")
    if not path.is_file():
        raise HTTPException(404, "Design file not found")
    return path


def parse_bbox(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError:
        raise HTTPException(400, "bbox must be 'x0,y0,x1,y1'")
    return x0, y0, x1, y1


@router.get("/crop")
def crop(file: str, page: int = Query(1, ge=1), bbox: str | None = None):
    """PNG of the page (1-based) around bbox, with the bbox outlined; whole page if no bbox."""
    path = resolve_design_file(file)
    box = parse_bbox(bbox) if bbox else None
    try:
        doc = fitz.open(path)
    except Exception:
        raise HTTPException(400, "Could not open PDF")
    with doc:
        if page > doc.page_count:
            raise HTTPException(404, f"Page {page} not in document ({doc.page_count} pages)")
        pg = doc[page - 1]
        clip = None
        if box:
            rect = fitz.Rect(*box)
            pg.draw_rect(rect, color=(0.85, 0.1, 0.1), width=1.5)
            clip = (rect + (-PAD_PT, -PAD_PT, PAD_PT, PAD_PT)) & pg.rect
            if clip.is_empty:
                clip = None
        png = pg.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=clip).tobytes("png")
    return Response(png, media_type="image/png")
