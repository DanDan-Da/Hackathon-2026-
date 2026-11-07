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

from app.check.evaluator import evaluate_all
from app.config import settings
from app.ingest.rule_store import read_rules
from app.models import DesignFacts, Finding, Rule

router = APIRouter(prefix="/ui", tags=["ui"])
MOCKS = Path(__file__).resolve().parents[2] / "mocks"


class UICheckRequest(BaseModel):
    facts: DesignFacts
    rules: list[Rule] | None = None   # None -> use the server's compiled rules


@router.get("/demo")
def demo():
    """Mock facts + mock rules, so the UI demo works with no setup."""
    try:
        return {"facts": json.loads((MOCKS / "facts_violation.json").read_text(encoding="utf-8")),
                "rules": json.loads((MOCKS / "rules.json").read_text(encoding="utf-8"))}
    except FileNotFoundError as e:
        raise HTTPException(404, f"Demo data missing: {e.filename}")


@router.post("/check", response_model=list[Finding])
def ui_check(req: UICheckRequest):
    rules = req.rules
    if rules is None:
        rules = read_rules()
        if rules is None:
            raise HTTPException(404, f"No compiled rules at {settings.compiled_rules}. "
                                     "Paste a rules file or run /ingest/rules.")
    return evaluate_all(rules, req.facts)
