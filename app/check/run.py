"""Run the checker from the command line: rules x design facts -> findings table. No server, no API.

    python -m app.check.run facts.json                    # uses settings.compiled_rules
    python -m app.check.run facts.json --rules my.json --status fail,needs_review
    python -m app.check.run facts.json --llm              # let the LLM judge qualitative rules (needs a key)

By default qualitative rules are NOT sent to an LLM: they come out as needs_review, so a run is
reproducible, free and works offline. Numeric / presence / count rules are always deterministic.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from app.check.evaluator import evaluate_all
from app.config import settings
from app.ingest.rule_store import read_rules
from app.models import DesignFacts, Finding, Rule, Status
from app.providers.llm import LLMProvider, LLMRefusal

ORDER = [Status.failed, Status.needs_review, Status.passed, Status.not_applicable]


class OfflineLLM(LLMProvider):
    """Stand-in used when --llm is not given: every call is refused, which the judge turns into needs_review."""

    def complete(self, system: str, prompt: str) -> str:
        raise LLMRefusal("offline run (no --llm)")

    def complete_structured(self, system, prompt, schema, images_png=None):
        raise LLMRefusal("offline run (no --llm)")


def load_rules(path: Path | None) -> list[Rule]:
    if path is None:
        rules = read_rules()
        if rules is None:
            raise SystemExit(f"No compiled rules at {settings.compiled_rules}; pass --rules FILE.")
        return rules
    return [Rule.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def run_check(rules: list[Rule], facts: DesignFacts, use_llm: bool = False) -> list[Finding]:
    findings = evaluate_all(rules, facts, None if use_llm else OfflineLLM())
    return sorted(findings, key=lambda f: ORDER.index(f.status))   # stable: fail first, rule order kept


def _cell(s: str | None, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def format_table(findings: list[Finding], rules: list[Rule]) -> str:
    title = {r.id: r.title for r in rules}
    rows = [("STATUS", "RULE", "ELEMENT", "RESULT", "SOURCE")]
    for f in findings:
        src = f"{f.rule_source.regime} p{f.rule_source.page}" + (f" {f.rule_source.clause}" if f.rule_source.clause else "")
        rows.append((f.status.value, _cell(title.get(f.rule_id, f.rule_id), 38), f.element_id or "-",
                     _cell(f.message, 110), src))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    counts = Counter(f.status for f in findings)
    lines.append("")
    lines.append("  ".join(f"{s.value}: {counts.get(s, 0)}" for s in ORDER))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("facts", type=Path, help="DesignFacts JSON")
    ap.add_argument("--rules", type=Path, help="rules JSON (default: the compiled rules file)")
    ap.add_argument("--status", help="comma list to show, e.g. fail,needs_review")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("--llm", action="store_true", help="use the configured LLM for qualitative rules")
    a = ap.parse_args(argv)

    if not a.llm:   # offline: the judge refusing every call is expected, not a warning
        logging.getLogger("app.check.llm_judge").setLevel(logging.ERROR)
    facts = DesignFacts.model_validate_json(a.facts.read_text(encoding="utf-8"))
    rules = load_rules(a.rules)
    findings = run_check(rules, facts, use_llm=a.llm)
    if a.status:
        want = {s.strip() for s in a.status.split(",")}
        findings = [f for f in findings if f.status.value in want]
    if a.json:
        print(json.dumps([f.model_dump(mode="json") for f in findings], indent=2, ensure_ascii=False))
    else:
        print(format_table(findings, rules))
    return 1 if any(f.status == Status.failed for f in findings) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
