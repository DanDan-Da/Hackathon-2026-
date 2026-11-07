"""Deterministic post-processing of extracted DesignFacts with the drawing's own printed text.

    python -m app.design.enrich FACTS.json PDF [-o OUT.json] [--report REPORT.json]

1. particulars.ship_type: the vessel-type phrase the drawing prints (never overwritten, never guessed).
2. space_type: from the room name through `enrich_config.json`, only when exactly one entry matches.
3. printed cabin summary ("SHELTER DECK: 6 SINGLE AND 10 DOUBLE CABINS") vs extracted cabin elements,
   as Finding objects (the elements are not altered by this).
All vocabulary lives in the JSON config.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from app.design.pdf_text import TextLine, extract_lines
from app.models import DesignFacts, Finding, Provenance, SourceRef

CONFIG_PATH = Path(__file__).with_name("enrich_config.json")


def load_config(path: str | Path | None = None) -> dict:
    return json.loads(Path(path or CONFIG_PATH).read_text())


def _prov(path, line: TextLine, cfg) -> Provenance:
    return Provenance(file=str(path), page=line.page, bbox=line.bbox, method="pdf_text",
                      confidence=cfg["text_confidence"])


def read_ship_type(path: str | Path, cfg: dict | None = None) -> tuple[str, Provenance] | None:
    """Printed vessel-type words and where they are printed; None if absent or more than one phrase."""
    cfg = cfg or load_config()
    rx = re.compile("|".join(f"(?:{re.escape(p)})" for p in cfg["ship_type_phrases"]), re.I)
    hits = [(m[0], ln) for ln in extract_lines(path) for m in [rx.search(ln.text)] if m]
    if len({h[0].lower() for h in hits}) != 1:
        return None
    text, ln = hits[0]
    return text, _prov(path, ln, cfg)


def _space_type_of(name: str | None, rules: dict[str, list[re.Pattern]]) -> str | None:
    if not name:
        return None
    matched = [st for st, pats in rules.items() if any(p.search(name.strip()) for p in pats)]
    return matched[0] if len(matched) == 1 else None


def enrich(facts: DesignFacts, pdf: str | Path, cfg: dict | None = None) -> DesignFacts:
    cfg = cfg or load_config()
    out = facts.model_copy(deep=True)
    if not out.particulars.ship_type and (st := read_ship_type(pdf, cfg)):
        out.particulars.ship_type = st[0]
        out.particulars.provenance.append(st[1])
    rules = {k: [re.compile(p, re.I) for p in v] for k, v in cfg["space_types"].items()}
    for e in out.elements:
        if e.space_type:
            continue
        if st := _space_type_of(e.name, rules):
            e.space_type = st
            e.properties["space_type_source"] = "name"
    return out


def parse_cabin_summary(pdf: str | Path, cfg: dict | None = None) -> list[dict]:
    """Printed per-deck cabin counts. A header line ending in ':' takes the next line as its text."""
    cfg = (cfg or load_config())["cabin_summary"]
    head = re.compile(cfg["deck_header"], re.I)
    word = re.compile(cfg["cabin_word"], re.I)
    count = re.compile(cfg["count_pattern"], re.I)
    full_cfg = load_config()
    lines = extract_lines(pdf)
    out = []
    for i, ln in enumerate(lines):
        m = head.match(ln.text)
        if not m:
            continue
        rest, quote = m[2].strip(), ln.text
        if not rest and i + 1 < len(lines) and lines[i + 1].page == ln.page and not head.match(lines[i + 1].text):
            rest, quote = lines[i + 1].text, f"{ln.text} {lines[i + 1].text}"
        if not word.search(rest):
            continue
        counts: dict[str, int] = {}
        for c in count.finditer(rest):
            counts[c[2].lower()] = counts.get(c[2].lower(), 0) + int(c[1])
        if counts:
            out.append({"deck": m[1].strip(), "counts": counts, "total": sum(counts.values()),
                        "quote": quote, "provenance": _prov(pdf, ln, full_cfg)})
    return out


def cabin_summary_findings(facts: DesignFacts, pdf: str | Path, cfg: dict | None = None) -> list[Finding]:
    """One finding: printed cabin total vs extracted cabin elements. Empty when nothing is printed."""
    cfg = cfg or load_config()
    c = cfg["cabin_summary"]
    printed = parse_cabin_summary(pdf, cfg)
    if not printed:
        return []
    total = sum(p["total"] for p in printed)
    cabins = [e for e in facts.elements if e.type == c["element_type"]]
    quote = " | ".join(p["quote"] for p in printed)
    match = len(cabins) == total
    msg = (f"Drawing prints {total} cabins ({'; '.join(p['deck'] + ': ' + str(p['total']) for p in printed)}); "
           f"{len(cabins)} extracted. " + ("Counts agree." if match else
           "Counts differ: an extraction miss/extra, or the printed summary is incomplete; review the drawing."))
    return [Finding(
        rule_id=c["rule_id"], status="pass" if match else "needs_review", message=msg,
        measured=len(cabins), required=f"{total} (printed on the drawing)",
        rule_source=SourceRef(document=Path(pdf).name, regime=c["regime"], page=printed[0]["provenance"].page,
                              quote=quote),
        evidence=[e.provenance for e in cabins])]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.design.enrich", description=__doc__.splitlines()[0])
    ap.add_argument("facts")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="write enriched facts here (default: stdout)")
    ap.add_argument("--report", help="write cabin-summary findings (JSON list) here")
    a = ap.parse_args(argv)
    facts = DesignFacts.model_validate_json(Path(a.facts).read_text())
    res = enrich(facts, a.pdf)
    text = res.model_dump_json(indent=2)
    Path(a.out).write_text(text) if a.out else print(text)
    if a.report:
        Path(a.report).write_text(json.dumps([f.model_dump(mode="json")
                                              for f in cabin_summary_findings(facts, a.pdf)], indent=2))
    n = sum(1 for e in res.elements if e.properties.get("space_type_source") == "name")
    print(f"ship_type={res.particulars.ship_type!r}; space_type set on {n} elements", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
