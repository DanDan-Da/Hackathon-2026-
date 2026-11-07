"""L1: scan the rules folder and yield text chunks tagged with regime, document and page.

Layout: ``<rules_dir>/<REGIME>/**/<file>``. The first-level folder name *is* the regime;
nothing here knows any regime name. Supported files: .pdf, .txt, .md, .html/.htm.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

import pymupdf

from app.config import settings

log = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".txt", ".md", ".html", ".htm"}


class Chunk(NamedTuple):
    regime: str
    document: str      # path relative to the regime folder (posix), e.g. "sub/pvag.pdf"
    page: int | None   # 1-based for PDFs; None for formats without pages
    text: str


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        else:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return "\n".join(line.strip() for line in "".join(p.parts).splitlines() if line.strip())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _pages(path: Path) -> Iterator[tuple[int | None, str]]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        with pymupdf.open(path) as doc:
            for i, page in enumerate(doc, start=1):
                yield i, page.get_text()
    elif ext in {".html", ".htm"}:
        yield None, _html_to_text(_read_text(path))
    else:
        yield None, _read_text(path)


def load_chunks(rules_dir: Path | None = None, regime: str | None = None) -> Iterator[Chunk]:
    """Yield one Chunk per PDF page / per text file. Empty pages are skipped.

    ``regime`` restricts the scan to one first-level folder. Unreadable files are logged
    and skipped so one bad document doesn't stop an ingest run.
    """
    root = Path(rules_dir or settings.rules_dir)
    if not root.is_dir():
        return
    for regime_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if regime is not None and regime_dir.name != regime:
            continue
        for path in sorted(p for p in regime_dir.rglob("*") if p.is_file()):
            if path.suffix.lower() not in SUPPORTED:
                continue
            document = path.relative_to(regime_dir).as_posix()
            try:
                for page, text in _pages(path):
                    text = text.strip()
                    if text:
                        yield Chunk(regime_dir.name, document, page, text)
            except Exception:
                log.exception("Skipping unreadable rules file %s", path)
