"""L2: chunk + embed the rules folder into an on-disk Qdrant index (needs the ``rag`` extra).

Every stored passage keeps regime, document, page and (when detectable) clause so retrieval
can cite its source. Embeddings come from a pluggable ``Embedder``; the default is
sentence-transformers with ``settings.embedding_model`` (BAAI/bge-m3), imported lazily.

Run:  python -m app.ingest.index   (rebuilds the whole index from the rules folder)
"""
from __future__ import annotations

import argparse
import logging
import re
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol

from app.config import settings
from app.ingest.rules_loader import Chunk, load_chunks

log = logging.getLogger(__name__)

COLLECTION = "rules"
MAX_PASSAGE_CHARS = 1200
# A clause number at the start of a line: "4.2.1", "3.1.2.4", "Reg. 12" is NOT matched (kept generic).
_CLAUSE_RE = re.compile(r"^\s*(\d+(?:\.\d+)+|\d+)[.)]?\s+\S")


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Passage(NamedTuple):
    regime: str
    document: str
    page: int | None
    clause: str | None
    text: str


class Hit(NamedTuple):
    score: float
    regime: str
    document: str
    page: int | None
    clause: str | None
    text: str


class SentenceTransformerEmbedder:
    """Default embedder. Loads the model on first use so importing this module stays cheap."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self._model = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer   # rag extra
            self._model = SentenceTransformer(self.model_name)
        return self._model.encode(list(texts), normalize_embeddings=True).tolist()


def split_passages(chunk: Chunk, max_chars: int = MAX_PASSAGE_CHARS) -> list[Passage]:
    """Split a page into passages of at most ~max_chars on line boundaries.

    The clause attached to a passage is the last clause number seen at or before its start,
    so a passage continuing a clause across a split keeps that clause.
    """
    passages: list[Passage] = []
    buf: list[str] = []
    size = 0
    clause: str | None = None       # clause in effect at the current line
    buf_clause: str | None = None   # clause in effect at the start of the buffer

    def flush() -> None:
        nonlocal buf, size, buf_clause
        text = "\n".join(buf).strip()
        if text:
            passages.append(Passage(chunk.regime, chunk.document, chunk.page, buf_clause, text))
        buf, size, buf_clause = [], 0, clause

    buf_clause = None
    for line in chunk.text.splitlines():
        m = _CLAUSE_RE.match(line)
        if m:
            clause = m.group(1)
            if not buf:
                buf_clause = clause
        if buf and size + len(line) > max_chars:
            flush()
            if m:
                buf_clause = clause
        buf.append(line)
        size += len(line) + 1
    flush()
    return passages


def _point_id(p: Passage, n: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{p.regime}|{p.document}|{p.page}|{n}"))


class RuleIndex:
    def __init__(self, path: Path | str | None = None, embedder: Embedder | None = None,
                 collection: str = COLLECTION) -> None:
        from qdrant_client import QdrantClient   # rag extra
        path = Path(path or settings.index_dir)
        path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(path=str(path))
        self.embedder = embedder or SentenceTransformerEmbedder()
        self.collection = collection

    def close(self) -> None:
        self.client.close()

    def rebuild(self, chunks: Iterable[Chunk], batch_size: int = 32) -> int:
        """Replace the whole index with the given chunks. Returns the number of passages stored."""
        from qdrant_client import models as qm
        passages: list[Passage] = []
        for chunk in chunks:
            passages.extend(split_passages(chunk))
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        if not passages:
            return 0
        counters: dict[tuple, int] = {}
        total = 0
        for i in range(0, len(passages), batch_size):
            batch = passages[i:i + batch_size]
            vectors = self.embedder.embed([p.text for p in batch])
            if i == 0:
                self.client.create_collection(
                    self.collection,
                    vectors_config=qm.VectorParams(size=len(vectors[0]), distance=qm.Distance.COSINE))
                # qdrant local mode resurrects the old points of a deleted collection on re-create
                self.client.delete(self.collection, qm.FilterSelector(filter=qm.Filter()))
            points = []
            for p, vec in zip(batch, vectors):
                key = (p.regime, p.document, p.page)
                counters[key] = counters.get(key, 0) + 1
                points.append(qm.PointStruct(id=_point_id(p, counters[key]), vector=vec, payload=p._asdict()))
            self.client.upsert(self.collection, points)
            total += len(points)
        return total

    def search(self, query: str, regime: str | None = None, k: int = 8) -> list[Hit]:
        from qdrant_client import models as qm
        if not self.client.collection_exists(self.collection):
            return []
        flt = None
        if regime is not None:
            flt = qm.Filter(must=[qm.FieldCondition(key="regime", match=qm.MatchValue(value=regime))])
        vec = self.embedder.embed([query])[0]
        res = self.client.query_points(self.collection, query=vec, query_filter=flt, limit=k,
                                       with_payload=True)
        return [Hit(score=pt.score, **{f: pt.payload[f] for f in Passage._fields}) for pt in res.points]


def main() -> int:
    index = RuleIndex()
    try:
        n = index.rebuild(load_chunks())
    finally:
        index.close()
    log.info("Indexed %d passages into %s", n, settings.index_dir)
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(description="Embed the rules folder into the local Qdrant index").parse_args()
    main()
