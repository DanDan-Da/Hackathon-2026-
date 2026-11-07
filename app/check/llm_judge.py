"""L5: LLM judge for qualitative rules (anything that can't be measured).

The model only sees one rule plus the design elements pre-selected in Python, and must answer in a
fixed schema. Its answer is then verified; anything unverifiable becomes ``needs_review``:
- no cited evidence                    -> needs_review
- a cited id we did not supply         -> whole verdict rejected (needs_review)
- pass/fail without a verbatim quote   -> needs_review
- pass/fail resting on low-confidence design data -> needs_review
- LLM error / refusal                  -> needs_review (never a default pass)
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.models import DesignElement, Rule, Status
from app.providers.llm import LLMProvider, get_llm

log = logging.getLogger(__name__)

MAX_ELEMENTS = 60

SYSTEM = """You are a strict ship-regulation compliance reviewer judging ONE qualitative requirement against listed design elements.

- Use ONLY the requirement text and the design elements provided. Never use outside knowledge about this ship.
- status "pass": the elements positively show the requirement is met. "fail": they show it is not met. "needs_review": the evidence is missing, ambiguous or insufficient. When in doubt answer "needs_review".
- `evidence_ids`: the ids of the design elements your verdict rests on, copied exactly from the list. Cite at least one for pass/fail. Never invent an id.
- `clause_quote`: a contiguous passage copied VERBATIM from the requirement text that your verdict applies. No paraphrase.
- `reasoning`: 1-3 sentences stating which element facts lead to the verdict.
"""


class JudgeVerdict(BaseModel):
    """What the model returns."""
    status: Literal["pass", "fail", "needs_review"]
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    clause_quote: str | None = None


class JudgeResult(BaseModel):
    """Verified outcome handed to the evaluator."""
    status: Status
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    clause_quote: str | None = None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _review(reason: str, evidence_ids: list[str] | None = None) -> JudgeResult:
    return JudgeResult(status=Status.needs_review, reasoning=reason, evidence_ids=evidence_ids or [])


def _element_line(e: DesignElement) -> str:
    props = ", ".join(f"{k}={v}" for k, v in e.properties.items()) or "no properties"
    where = ", ".join(x for x in (e.name, f"deck {e.deck}" if e.deck else None,
                                  f"space_type {e.space_type}" if e.space_type else None) if x)
    return f"- id={e.id} | type={e.type} | {where or 'unnamed'} | {props}"


def build_prompt(rule: Rule, elements: list[DesignElement], context: list[str]) -> str:
    ctx = "\n".join(f"[{i}] {c}" for i, c in enumerate(context, 1)) or "(none)"
    return (f"Regulation: {rule.source.regime}, clause {rule.source.clause or 'n/a'}\n"
            f"Requirement: {rule.title}\n"
            f"Verbatim requirement text:\n{rule.source.quote}\n\n"
            f"Additional clause context:\n{ctx}\n\n"
            f"Design elements ({len(elements)}):\n" + "\n".join(_element_line(e) for e in elements))


def judge(rule: Rule, elements: list[DesignElement], context: list[str] | None = None,
          llm: LLMProvider | None = None, min_confidence: float = 0.6) -> JudgeResult:
    context = context or []
    if not elements:
        return _review("No matching design elements to judge against.")
    if len(elements) > MAX_ELEMENTS:
        return _review(f"{len(elements)} elements match; too many to judge reliably in one pass.")
    try:
        verdict = (llm or get_llm()).complete_structured(SYSTEM, build_prompt(rule, elements, context),
                                                         JudgeVerdict)
    except Exception as e:   # refusal, rate limit exhausted, missing API key ...
        log.warning("LLM judge failed for %s: %s", rule.id, e)
        return _review(f"LLM judge unavailable ({type(e).__name__}); needs engineer review.")

    by_id = {e.id: e for e in elements}
    unknown = [i for i in verdict.evidence_ids if i not in by_id]
    if unknown:
        log.warning("LLM judge cited unknown ids %s for %s", unknown, rule.id)
        return _review(f"Judge cited element ids not in the design ({', '.join(unknown)}); verdict rejected.")
    if verdict.status == "needs_review":
        return _review(verdict.reasoning, verdict.evidence_ids)
    if not verdict.evidence_ids:
        return _review("Judge gave a verdict without citing any design element.")

    sources = _norm(" ".join([rule.source.quote, *context]))
    quote = _norm(verdict.clause_quote or "")
    if not quote or quote not in sources:
        return _review("Judge's clause quote is missing or not verbatim from the rule text; verdict rejected.",
                       verdict.evidence_ids)
    low = [i for i in verdict.evidence_ids if by_id[i].provenance.confidence < min_confidence]
    if low:
        return _review(f"Verdict rests on low-confidence extraction ({', '.join(low)}); {verdict.reasoning}",
                       verdict.evidence_ids)
    return JudgeResult(status=Status(verdict.status), reasoning=verdict.reasoning,
                       evidence_ids=verdict.evidence_ids, clause_quote=quote)
