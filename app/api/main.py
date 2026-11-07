"""FastAPI entry point. Run: uvicorn app.api.main:app --reload"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.check.evaluator import evaluate_all
from app.config import settings
from app.ingest import rule_compiler
from app.ingest.rule_store import RulePatch, patch_rule, read_rules
from app.models import DesignFacts, Finding, Rule

app = FastAPI(title="RuleCheck", description="Class & regulatory compliance checking for ship designs")


def load_rules() -> list[Rule]:
    rules = read_rules()
    if rules is None:
        raise HTTPException(404, f"No compiled rules at {settings.compiled_rules}. "
                                 f"Add files to {settings.rules_dir} and run /ingest/rules.")
    return rules


@app.get("/health")
def health():
    return {"ok": True, "provider": settings.llm_provider}


@app.get("/rules", response_model=list[Rule])
def rules():
    return load_rules()


@app.post("/ingest/rules")
def ingest_rules(regime: str | None = None):
    """Run loader -> LLM compiler -> rules.json. Reviewed rules are kept. Can take minutes."""
    rules = rule_compiler.main(regime)
    return {"rules": len(rules), "reviewed": sum(r.reviewed for r in rules)}


@app.patch("/rules/{rule_id}", response_model=Rule)
def update_rule(rule_id: str, patch: RulePatch):
    try:
        rule = patch_rule(rule_id, patch)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if rule is None:
        raise HTTPException(404, f"Unknown rule {rule_id}")
    return rule


@app.post("/check", response_model=list[Finding])
def check(facts: DesignFacts):
    return evaluate_all(load_rules(), facts)
