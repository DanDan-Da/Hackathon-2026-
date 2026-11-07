"""L7: answer a question about the regulations, citing the passages it used.

Retrieval comes from the L2 index. The LLM may only use the numbered passages it is given and must
quote them; every citation is verified (passage exists, quote is verbatim from that passage). An
answer without a single verified citation is withheld ("Never guess"): the caller gets the retrieved
passages instead. If the LLM is unavailable the passages are still returned.
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.ingest.index import Hit, RuleIndex
from app.providers.llm import LLMProvider, get_llm

log = logging.getLogger(__name__)

SYSTEM = """You answer questions about ship / accessibility regulations using ONLY the numbered passages provided.

- Use no outside knowledge. If the passages do not contain the answer, say so in `answer` and return no citations.
- Every statement of fact must be backed by a citation: `passage` is the passage number, `quote` is copied VERBATIM (contiguous, no paraphrase, no ellipsis) from that passage.
- Keep the answer short and state numbers and units exactly as written in the passage.
"""


class DraftCitation(BaseModel):
    passage: int
    quote: str


class AnswerDraft(BaseModel):
    answer: str
    citations: list[DraftCitation] = Field(default_factory=list)


class Source(BaseModel):
    regime: str
    document: str
    page: int | None = None
    clause: str | None = None
    quote: str


class AskAnswer(BaseModel):
    status: Literal["answered", "needs_review", "no_sources", "llm_unavailable"]
    answer: str | None = None
    citations: list[Source] = Field(default_factory=list)   # verified quotes behind the answer
    passages: list[Source] = Field(default_factory=list)    # what was retrieved (full text)
    note: str | None = None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _source(h: Hit, quote: str | None = None) -> Source:
    return Source(regime=h.regime, document=h.document, page=h.page, clause=h.clause, quote=quote or h.text)


def build_prompt(question: str, hits: list[Hit]) -> str:
    blocks = [f"[{i}] ({h.regime} | {h.document} | page {h.page if h.page is not None else 'n/a'}"
              f" | clause {h.clause or 'n/a'})\n{h.text}" for i, h in enumerate(hits, 1)]
    return f"Question: {question}\n\nPassages:\n\n" + "\n\n".join(blocks)


def ask(question: str, index: RuleIndex, regime: str | None = None, k: int = 6,
        llm: LLMProvider | None = None) -> AskAnswer:
    hits = index.search(question, regime=regime, k=k)
    passages = [_source(h) for h in hits]
    if not hits:
        return AskAnswer(status="no_sources", note="Nothing in the rules index matched the question.")
    try:
        draft = (llm or get_llm()).complete_structured(SYSTEM, build_prompt(question, hits), AnswerDraft)
    except Exception as e:   # no key, rate limit, refusal ...
        log.warning("ask: LLM unavailable: %s", e)
        return AskAnswer(status="llm_unavailable", passages=passages,
                         note=f"No AI answer ({type(e).__name__}); the retrieved passages are shown instead.")

    verified: list[Source] = []
    for c in draft.citations:
        if not 1 <= c.passage <= len(hits):
            log.warning("ask: citation to unknown passage %s dropped", c.passage)
            continue
        hit, quote = hits[c.passage - 1], _norm(c.quote)
        if quote and quote in _norm(hit.text):
            verified.append(_source(hit, quote))
        else:
            log.warning("ask: non-verbatim citation dropped (passage %s)", c.passage)
    if not verified:
        return AskAnswer(status="needs_review", passages=passages,
                         note="The model gave no verifiable citation, so its answer was withheld.")
    return AskAnswer(status="answered", answer=draft.answer, citations=verified, passages=passages)


def open_index() -> RuleIndex:
    """The on-disk index built by ``python -m app.ingest.index``. Raises ImportError without the rag extra."""
    return RuleIndex()
