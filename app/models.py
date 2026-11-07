"""Shared data contract between the rules track (Person 1) and the design track (Person 2).

Rules  --(rule_compiler)-->  Rule[]         \
                                              >--(checker)--> Finding[]
Designs --(design readers)--> DesignFacts   /

Change these models only by agreement — both tracks depend on them.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- Rules ----------

class CheckType(str, Enum):
    numeric = "numeric"        # parameter <op> value (e.g. door clear width >= 813 mm)
    presence = "presence"      # something must exist (e.g. emergency generator room)
    count = "count"            # number of elements <op> value (e.g. >= 2 means of escape)
    qualitative = "qualitative"  # needs LLM judgement with evidence


Operator = Literal[">=", ">", "<=", "<", "==", "!=", "exists", "not_exists"]


class Applicability(BaseModel):
    """When a rule applies. Empty / None fields mean 'no restriction'."""
    ship_types: list[str] = Field(default_factory=list, description="e.g. passenger, cargo, research")
    min_length_m: float | None = None
    max_length_m: float | None = None
    min_gross_tonnage: float | None = None
    min_persons_on_board: int | None = None
    max_persons_on_board: int | None = None   # inclusive, for "up to N persons" tiers
    space_types: list[str] = Field(default_factory=list, description="e.g. corridor, cabin, stairway, door")
    condition_text: str | None = Field(None, description="Free-text condition from the source, for review")


class SourceRef(BaseModel):
    document: str              # file name inside knowledge/rules/<regime>/
    regime: str                # folder name: SOLAS, PVAG, DNV ... (never hardcoded)
    page: int | None = None
    clause: str | None = None  # e.g. "V206.2.1" or "II-2/13.3.1"
    quote: str                 # verbatim text the rule was derived from


class Rule(BaseModel):
    id: str
    title: str
    check_type: CheckType
    target: str = Field(..., description="Element type the rule targets: door, corridor, stairway, ship, space ...")
    parameter: str | None = Field(None, description="Normalised parameter name, e.g. clear_width")
    operator: Operator | None = None
    value: float | str | None = None
    unit: str | None = Field(None, description="SI unit after normalisation: mm, m, m2, count, persons ...")
    applies_to: Applicability = Field(default_factory=Applicability)
    source: SourceRef
    reviewed: bool = False     # set by a human in the review UI


# ---------- Design facts ----------

class Provenance(BaseModel):
    """Where in the design a fact came from — every fact must be traceable."""
    file: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = Field(None, description="x0,y0,x1,y1 in PDF points")
    element_id: str | None = Field(None, description="IFC GlobalId / mesh node for 3D")
    method: Literal["pdf_text", "vision", "ifc", "mesh", "manual", "spec_text"] = "manual"
    confidence: float = Field(1.0, ge=0, le=1)


class DesignElement(BaseModel):
    id: str
    type: str = Field(..., description="door, corridor, stairway, cabin, lifeboat, space ...")
    name: str | None = None
    deck: str | None = None
    space_type: str | None = None
    properties: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Normalised to SI: clear_width (mm), area (m2), ...")
    provenance: Provenance


class ShipParticulars(BaseModel):
    name: str | None = None
    ship_type: str | None = None
    length_overall_m: float | None = None
    length_between_perpendiculars_m: float | None = None
    breadth_m: float | None = None
    gross_tonnage: float | None = None
    persons_on_board: int | None = None
    provenance: list[Provenance] = Field(default_factory=list)


class DesignFacts(BaseModel):
    project: str
    particulars: ShipParticulars = Field(default_factory=ShipParticulars)
    elements: list[DesignElement] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)


# ---------- Findings ----------

class Status(str, Enum):
    passed = "pass"
    failed = "fail"
    needs_review = "needs_review"   # missing evidence or low confidence — never guess
    not_applicable = "not_applicable"


class Finding(BaseModel):
    rule_id: str
    status: Status
    element_id: str | None = None
    message: str
    measured: Any | None = None
    required: str | None = None
    rule_source: SourceRef
    evidence: list[Provenance] = Field(default_factory=list)
    method: Literal["deterministic", "llm_judge"] = "deterministic"
    reasoning: str | None = None
