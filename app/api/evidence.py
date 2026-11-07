"""Owner: D. Read-only evidence crops: render a bbox region of a design PDF page as PNG.

The file path is resolved against settings.designs_dir and must stay inside it.
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
    root = settings.designs_dir.resolve()
    if "\x00" in rel or Path(rel).is_absolute():
        raise HTTPException(400, "Invalid file path")
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(400, "File must be inside the designs folder")
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
