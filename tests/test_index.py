"""L2: chunking + index with a fake embedder (no model download)."""
import hashlib

import pytest

pytest.importorskip("qdrant_client")

from app.ingest.index import RuleIndex, split_passages
from app.ingest.rules_loader import Chunk

DIM = 64


class FakeEmbedder:
    """Hashed bag-of-words: texts sharing words get similar vectors."""

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIM] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / norm for x in v])
        return out


CHUNKS = [
    Chunk("REG_A", "doors.pdf", 3, "4.2.1 Door clear width shall be at least 800 mm.\nApplies to all doors."),
    Chunk("REG_A", "ramps.pdf", 7, "5.1 Ramp slope shall not exceed 1:12 for wheelchair users."),
    Chunk("REG_B", "fire.txt", None, "Fire doors shall be self closing and fitted with a smoke seal."),
]


@pytest.fixture
def index(tmp_path):
    idx = RuleIndex(path=tmp_path / "idx", embedder=FakeEmbedder())
    yield idx
    idx.close()


def test_search_returns_source_document_page_and_clause(index):
    assert index.rebuild(CHUNKS) == 3
    hit = index.search("door clear width 800 mm", k=1)[0]
    assert (hit.regime, hit.document, hit.page, hit.clause) == ("REG_A", "doors.pdf", 3, "4.2.1")
    assert "800 mm" in hit.text


def test_regime_filter(index):
    index.rebuild(CHUNKS)
    hits = index.search("doors", regime="REG_B", k=8)
    assert hits and {h.regime for h in hits} == {"REG_B"}
    assert hits[0].page is None


def test_rebuild_replaces_and_empty_index_searches_empty(index):
    assert index.search("anything") == []
    index.rebuild(CHUNKS)
    index.rebuild(CHUNKS[:1])
    assert len(index.search("door", k=8)) == 1


def test_long_page_split_keeps_clause_across_passages():
    lines = ["3.4 Stairway requirements"] + [f"line {i} " + "x" * 90 for i in range(30)] + ["3.5 Next clause"] + [f"more {i} " + "y" * 90 for i in range(10)]
    ps = split_passages(Chunk("R", "d.txt", 1, "\n".join(lines)), max_chars=500)
    assert len(ps) > 2
    assert ps[0].clause == "3.4" and ps[1].clause == "3.4"
    assert ps[-1].clause == "3.5"   # a later passage starts inside clause 3.5
    assert all(len(p.text) <= 600 for p in ps)
