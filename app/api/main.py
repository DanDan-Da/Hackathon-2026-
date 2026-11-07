"""FastAPI entry point. Run: uvicorn app.api.main:app --reload"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException

from app.check.evaluator import evaluate_all
from app.config import settings
from app.models import DesignFacts, Finding, Rule

app = FastAPI(title="RuleCheck", description="Class & regulatory compliance checking for ship designs")


def load_rules() -> list[Rule]:
    path = settings.compiled_rules
    if not path.exists():
        raise HTTPException(404, f"No compiled rules at {path}. Add files to {settings.rules_dir} and run /ingest/rules.")
    return [Rule.model_validate(r) for r in json.loads(path.read_text())]


@app.get("/health")
def health():
    return {"ok": True, "provider": settings.llm_provider}


@app.get("/rules", response_model=list[Rule])
def rules():
    return load_rules()


@app.post("/check", response_model=list[Finding])
def check(facts: DesignFacts):
    return evaluate_all(load_rules(), facts)
