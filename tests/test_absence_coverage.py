"""A prohibition ("no X") can only be passed by absence when the design source covers that kind of element."""
import json
from pathlib import Path

import pytest

from app.check.evaluator import evaluate_rule
from app.models import DesignElement, DesignFacts, Provenance, Rule, SourceRef, Status


def _prohibition():
    return Rule(id="no-fuel", title="No fuel tank", check_type="presence", target="fuel_tank", operator="not_exists",
                source=SourceRef(document="d.pdf", regime="X", clause="1", quote="q"))


def _facts(method, with_other=True):
    els = [DesignElement(id="D-1", type="door",
                         provenance=Provenance(file="m", page=1, method=method, confidence=0.9))] if with_other else []
    return DesignFacts(project="p", elements=els)


def _status(facts):
    out = evaluate_rule(_prohibition(), facts)
    assert len(out) == 1
    return out[0].status


@pytest.mark.parametrize("method", ["vision", "pdf_text", "vector", "mesh"])
def test_absence_in_a_read_drawing_is_not_proof(method):
    assert _status(_facts(method)) == Status.needs_review


@pytest.mark.parametrize("method", ["ifc", "manual"])
def test_absence_in_a_fully_modelled_source_passes(method):
    assert _status(_facts(method)) == Status.passed


def test_one_read_element_among_modelled_ones_is_not_full_coverage():
    f = DesignFacts(project="p", elements=[
        DesignElement(id="A", type="door", provenance=Provenance(file="m", page=1, method="ifc", confidence=0.9)),
        DesignElement(id="B", type="door", provenance=Provenance(file="m", page=1, method="vision", confidence=0.9))])
    assert _status(f) == Status.needs_review


def test_empty_design_never_proves_absence():
    assert _status(_facts("ifc", with_other=False)) == Status.needs_review


def test_a_present_prohibited_element_still_fails():
    f = DesignFacts(project="p", elements=[DesignElement(
        id="T", type="fuel_tank", provenance=Provenance(file="m", page=1, method="vision", confidence=0.9))])
    assert _status(f) == Status.failed


def test_coverage_vocabulary_lives_in_a_config_file_not_in_code():
    cfg = json.loads((Path(__file__).parent.parent / "app" / "check" / "absence_coverage.json").read_text())
    assert set(cfg["full_model_methods"]) == {"ifc", "manual"}
