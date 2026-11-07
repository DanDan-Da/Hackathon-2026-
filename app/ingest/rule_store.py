"""L4: read / edit the compiled rules file (the "engineer in the loop" step)."""
from __future__ import annotations

import json
import os
import threading

from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.models import Applicability, CheckType, Operator, Rule

_lock = threading.Lock()


class RulePatch(BaseModel):
    """Editable fields of a rule. ``id`` and ``source`` are fixed: the quote must stay verbatim."""
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    check_type: CheckType | None = None
    target: str | None = None
    parameter: str | None = None
    operator: Operator | None = None
    value: float | str | None = None
    unit: str | None = None
    applies_to: Applicability | None = None
    reviewed: bool | None = None


def read_rules() -> list[Rule] | None:
    """None if no compiled file exists yet."""
    path = settings.compiled_rules
    if not path.exists():
        return None
    return [Rule.model_validate(r) for r in json.loads(path.read_text(encoding="utf-8"))]


def _write(rules: list[Rule]) -> None:
    path = settings.compiled_rules
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([r.model_dump(mode="json") for r in rules], indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)


def patch_rule(rule_id: str, patch: RulePatch) -> Rule | None:
    """Apply the fields the caller sent. Any edit marks the rule reviewed unless ``reviewed``
    was sent explicitly. Returns None if the id is unknown. Raises ValueError if the result is invalid."""
    with _lock:
        rules = read_rules() or []
        for i, rule in enumerate(rules):
            if rule.id != rule_id:
                continue
            changes = {k: getattr(patch, k) for k in patch.model_fields_set}
            if "reviewed" not in changes:
                changes["reviewed"] = True
            try:
                updated = Rule.model_validate({**rule.model_dump(), **changes})
            except Exception as e:
                raise ValueError(str(e)) from e
            rules[i] = updated
            _write(rules)
            return updated
        return None
