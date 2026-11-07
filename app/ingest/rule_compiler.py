"""L3: the "learning" step. Regulation text -> atomic, checkable ``Rule`` objects.

For every chunk from the rules loader the LLM extracts requirements as structured output.
Provenance fields (regime, document, page) are NOT asked from the model; they are copied
from the chunk so they can't be hallucinated. The one thing the model must copy is the
quote, and it is verified to be a substring of the chunk text; otherwise the rule is dropped.

Run:  python -m app.ingest.rule_compiler [--regime NAME]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

from pydantic import BaseModel, Field

from app.config import settings
from app.ingest.rules_loader import Chunk, load_chunks
from app.models import Applicability, CheckType, Operator, Rule, SourceRef
from app.providers.llm import LLMProvider, get_llm

log = logging.getLogger(__name__)

MIN_CHUNK_CHARS = 40

SYSTEM = """You extract machine-checkable requirements from ship / accessibility regulation text.

Rules for extraction:
- Extract ONLY atomic, checkable requirements that are explicitly stated in the text. One requirement per item. Never invent, infer or generalise.
- If the text contains no checkable requirement (definitions, scoping, commentary), return an empty list.
- `quote` MUST be copied VERBATIM from the text (a contiguous passage, no paraphrase, no ellipsis) and must contain the requirement.
- `clause` is the clause / section number exactly as printed near the requirement, or null if none is visible.
- check_type:
  numeric      = a measurable parameter compared with a number (width, height, area, slope, force ...)
  count        = a required number of elements (e.g. at least two exits)
  presence     = something must (or must not) exist; use operator "exists" / "not_exists"
  qualitative  = a real requirement that cannot be measured (e.g. "shall be readily accessible"). No operator/value.
- `target` = the kind of design element the rule is about (door, corridor, stairway, ramp, space, ship ...), lower case singular.
- `parameter` = short snake_case measured property (clear_width, height, area, slope, count ...), consistent across rules.
- `value_number` = the number exactly as written; `unit` = the unit exactly as written in the text (e.g. "in", "mm", "m", "m2", "count"). Do NOT convert units. For "at least"/"minimum" use ">=", for "at most"/"maximum" use "<=".
- Put conditions of applicability (ship type, size, space type) in `applies_to`; copy any condition wording into `condition_text`. Leave unknown fields empty rather than guessing.
"""


class ExtractedRule(BaseModel):
    """What the model returns. Deliberately has no regime/document/page/id."""
    title: str
    check_type: CheckType
    target: str
    parameter: str | None = None
    operator: Operator | None = None
    value_number: float | None = None
    value_text: str | None = None
    unit: str | None = None
    applies_to: Applicability = Field(default_factory=Applicability)
    clause: str | None = None
    quote: str


class ExtractedBatch(BaseModel):
    rules: list[ExtractedRule] = Field(default_factory=list)


class RuleBatch(BaseModel):
    rules: list[Rule] = Field(default_factory=list)


def _norm(s: str) -> str:
    """Collapse whitespace so line breaks from PDF extraction don't defeat the substring check."""
    return re.sub(r"\s+", " ", s).strip()


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "x"


def _structurally_valid(r: ExtractedRule) -> str | None:
    """Return a reason string if the rule can't be evaluated as declared, else None."""
    value = r.value_number if r.value_number is not None else r.value_text
    if r.check_type in (CheckType.numeric, CheckType.count):
        if not r.parameter and r.check_type == CheckType.numeric:
            return "numeric rule without parameter"
        if r.operator is None or value is None:
            return "numeric/count rule without operator or value"
        if r.operator in ("exists", "not_exists"):
            return "numeric/count rule with presence operator"
    elif r.check_type == CheckType.presence:
        if r.operator not in ("exists", "not_exists"):
            return "presence rule without exists/not_exists"
    return None


def extract_chunk(chunk: Chunk, llm: LLMProvider) -> list[Rule]:
    """Compile one chunk. Rules with an unverifiable quote or invalid structure are dropped."""
    prompt = (f"Regulation: {chunk.regime}\nDocument: {chunk.document}\n"
              f"Page: {chunk.page if chunk.page is not None else 'n/a'}\n\n--- TEXT ---\n{chunk.text}\n--- END ---")
    batch = llm.complete_structured(SYSTEM, prompt, ExtractedBatch)
    haystack = _norm(chunk.text)
    out: list[Rule] = []
    for r in batch.rules:
        quote = _norm(r.quote)
        if not quote or quote not in haystack:
            log.warning("DROPPED (quote not in source) %s p%s: %r", chunk.document, chunk.page, r.title)
            continue
        if reason := _structurally_valid(r):
            log.warning("DROPPED (%s) %s p%s: %r", reason, chunk.document, chunk.page, r.title)
            continue
        out.append(Rule(
            id="",  # assigned after dedup
            title=r.title.strip(),
            check_type=r.check_type,
            target=r.target.strip().lower(),
            parameter=r.parameter,
            operator=r.operator,
            value=r.value_number if r.value_number is not None else r.value_text,
            unit=r.unit,
            applies_to=r.applies_to,
            source=SourceRef(document=chunk.document, regime=chunk.regime, page=chunk.page,
                             clause=(r.clause or None), quote=quote),
        ))
    return out


def _dedup_key(r: Rule) -> tuple:
    if r.source.clause:
        return (r.source.regime, r.source.clause, r.parameter, r.target)
    return (r.source.regime, None, r.parameter, r.target, r.source.quote)   # no clause: only identical quotes merge


def deduplicate(rules: Iterable[Rule]) -> list[Rule]:
    """First occurrence wins; ids become <regime>-<clause|title>-<parameter>, unique."""
    seen: dict[tuple, Rule] = {}
    for r in rules:
        seen.setdefault(_dedup_key(r), r)
    used: set[str] = set()
    result = []
    for r in seen.values():
        base = "-".join(_slug(p) for p in (r.source.regime, r.source.clause or r.title, r.parameter or r.target))
        rid, n = base, 2
        while rid in used:
            rid, n = f"{base}-{n}", n + 1
        used.add(rid)
        result.append(r.model_copy(update={"id": rid}))
    return result


def compile_rules(chunks: Iterable[Chunk], llm: LLMProvider | None = None,
                  max_parallel: int | None = None) -> list[Rule]:
    llm = llm or get_llm()
    todo = [c for c in chunks if len(c.text) >= MIN_CHUNK_CHARS]

    def run(c: Chunk) -> list[Rule]:
        try:
            return extract_chunk(c, llm)
        except Exception:   # one bad chunk (refusal, rate limit exhausted) must not lose the run
            log.exception("Chunk failed, skipped: %s p%s", c.document, c.page)
            return []

    workers = max(1, max_parallel or settings.llm_max_parallel)
    with ThreadPoolExecutor(workers) as pool:
        per_chunk = list(pool.map(run, todo))          # map keeps chunk order -> deterministic output
    return deduplicate(r for rules in per_chunk for r in rules)


def keep_reviewed(new: list[Rule], existing: list[Rule]) -> list[Rule]:
    """Human-reviewed rules are never overwritten by a recompile."""
    reviewed = {r.id: r for r in existing if r.reviewed}
    merged = [reviewed.pop(r.id, r) for r in new]
    return merged + list(reviewed.values())


def write_rules(rules: list[Rule]) -> None:
    path = settings.compiled_rules
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump(mode="json") for r in rules], indent=2, ensure_ascii=False),
                    encoding="utf-8")


def main(regime: str | None = None) -> list[Rule]:
    chunks = list(load_chunks(regime=regime))
    log.info("Compiling %d chunks", len(chunks))
    rules = compile_rules(chunks)
    path = settings.compiled_rules
    if path.exists():
        existing = [Rule.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]
        if regime is not None:   # partial run: keep other regimes' rules untouched
            rules += [r for r in existing if r.source.regime != regime]
        rules = keep_reviewed(rules, existing)
    write_rules(rules)
    log.info("Wrote %d rules to %s", len(rules), path)
    return rules


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Compile regulation files into knowledge/compiled/rules.json")
    ap.add_argument("--regime", help="only this folder under the rules dir")
    main(ap.parse_args().regime)
