"""Owner: D. Endpoints backing the web UI (web/): demo data and a check that accepts inline rules.

The existing POST /check (L) only reads the server's compiled rules; the UI also needs to check
against a rules file the user pastes or the bundled mocks, so this adds POST /ui/check without
touching /check.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.remedy import remedy
from app.check.evaluator import LOW_CONFIDENCE, evaluate_all
from app.config import settings
from app.ingest.rule_store import read_rules
from app.models import DesignFacts, Finding, Provenance, Rule
from eval.score_findings import load_cases, run_cases

router = APIRouter(prefix="/ui", tags=["ui"])
ROOT = Path(__file__).resolve().parents[2]
MOCKS = ROOT / "mocks"
EVAL_CASES = ROOT / "eval" / "gold" / "findings" / "cases.json"
TRUST_STATEMENT = "Anything not provable is marked needs review, never guessed."


class FindingOut(Finding):
    """A finding plus what would make it pass (None unless it is a failed, computable finding)."""
    remedy: dict | None = None


class UICheckRequest(BaseModel):
    facts: DesignFacts
    rules: list[Rule] | None = None   # None -> use the server's compiled rules
    ship_type: str | None = None      # stated by the user: drawings rarely print it and we never infer it


def apply_ship_type(facts: DesignFacts, ship_type: str | None) -> DesignFacts:
    """Return a copy of the facts with the user's ship type, recorded as manual provenance."""
    ship_type = (ship_type or "").strip()
    if not ship_type:
        return facts
    out = facts.model_copy(deep=True)
    out.particulars.ship_type = ship_type
    out.particulars.provenance.append(Provenance(file="entered in the UI", method="manual", confidence=1.0))
    return out


@router.get("/demo")
def demo():
    """Mock facts + mock rules, so the UI demo works with no setup."""
    try:
        return {"facts": json.loads((MOCKS / "facts_violation.json").read_text(encoding="utf-8")),
                "rules": json.loads((MOCKS / "rules.json").read_text(encoding="utf-8"))}
    except FileNotFoundError as e:
        raise HTTPException(404, f"Demo data missing: {e.filename}")


@router.post("/check", response_model=list[FindingOut])
def ui_check(req: UICheckRequest):
    rules = req.rules
    if rules is None:
        rules = read_rules()
        if rules is None:
            raise HTTPException(404, f"No compiled rules at {settings.compiled_rules}. "
                                     "Paste a rules file or run /ingest/rules.")
    by_id = {r.id: r for r in rules}
    findings = evaluate_all(rules, apply_ship_type(req.facts, req.ship_type))
    return [FindingOut(**f.model_dump(), remedy=remedy(by_id.get(f.rule_id), f)) for f in findings]


def planted_eval() -> dict | None:
    """Run the planted-violation cases on the bundled mocks, live. None if the files are unavailable."""
    try:
        facts = DesignFacts.model_validate_json((MOCKS / "facts_violation.json").read_text(encoding="utf-8"))
        rules = [Rule.model_validate(r) for r in json.loads((MOCKS / "rules.json").read_text(encoding="utf-8"))]
        report = run_cases(load_cases(EVAL_CASES), facts, rules)
    except (FileNotFoundError, ValueError):
        return None
    return {"total": len(report.results), "correct": report.correct, "wrong": report.wrong,
            "missed_violations": report.missed_violations, "false_alarms": report.false_alarms}


@router.get("/trust")
def trust():
    """Inputs for the trust scoreboard that are not in the findings themselves."""
    return {"eval": planted_eval(), "low_confidence_threshold": LOW_CONFIDENCE, "statement": TRUST_STATEMENT}
