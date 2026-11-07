"""Owner: D. Upload a regulation file into knowledge/rules/<regime>/ (folder name = regime).

Compiling it into rules is a separate step (POST /ingest/rules, uses AI quota). The body is the raw
file; regime and filename come in the query string, so no multipart dependency is needed.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from app.config import settings

router = APIRouter(prefix="/ui", tags=["ui"])
MAX_BYTES = 50 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".txt", ".md", ".html"}
REGIME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.()-]{0,120}$")


def valid_regime(regime: str) -> str:
    if not REGIME_RE.fullmatch(regime) or ".." in regime:
        raise HTTPException(400, "Regime must be 1-40 letters, digits, '_', '-' or '.', and start with a letter or digit")
    return regime


def valid_filename(name: str) -> str:
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not FILENAME_RE.fullmatch(name) or ".." in name or ext not in ALLOWED_EXT:
        raise HTTPException(400, "File name must be plain (no folders) and end in .pdf, .txt, .md or .html")
    return name


@router.post("/regulations")
async def upload_regulation(request: Request, regime: str, filename: str):
    valid_regime(regime)
    valid_filename(filename)
    data = await request.body()
    if not data:
        raise HTTPException(400, "The file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_BYTES // (1024 * 1024)} MB")
    folder = settings.rules_dir / regime
    target = folder / filename
    if not target.resolve().is_relative_to(settings.rules_dir.resolve()):
        raise HTTPException(400, "Invalid path")
    if target.exists():
        raise HTTPException(409, f"{regime}/{filename} already exists; rename the file or remove the old one")
    folder.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"saved": f"{regime}/{filename}", "bytes": len(data)}
