import json

import pytest

from app.design.cross_check import cross_check, main
from app.models import DesignElement, DesignFacts, Provenance, Status


def mesh(length=60000.0, beam=15000.0, height=30000.0):
    return DesignFacts(project="m", source_files=["m.ifc"], elements=[DesignElement(
        id="ship_extent", type="ship_extent",
        properties={"length_overall": length, "beam": beam, "height": height},
        provenance=Provenance(file="m.ifc", method="mesh", confidence=0.6))])


def stated(**vals):
    els = [DesignElement(
        id=f"stated:{k}", type="stated_particular",
        properties={"parameter": k, "value": v, "unit": "mm", "quote": f"{k} {v}"},
        provenance=Provenance(file="p.pdf", page=2, bbox=(1, 2, 3, 4), method="pdf_text", confidence=0.9))
        for k, v in vals.items()]
    return DesignFacts(project="s", elements=els, source_files=["p.pdf"])


def by_param(findings):
    return {f.rule_id.rsplit(".", 1)[1]: f for f in findings}


def test_within_tolerance_passes_and_cites_both_sides():
    f = by_param(cross_check(mesh(length=62000), stated(length_overall=60000.0)))["length_overall"]
    assert f.status == Status.passed
    files = {e.file for e in f.evidence}
    assert files == {"m.ifc", "p.pdf"}
    assert f.rule_source.document == "p.pdf" and f.rule_source.page == 2
    assert "60000" in f.rule_source.quote
    assert f.method == "deterministic"


def test_difference_is_needs_review_never_fail():
    f = by_param(cross_check(mesh(length=80000), stated(length_overall=60000.0)))["length_overall"]
    assert f.status == Status.needs_review
    assert "mast" in f.message.lower() and "appendage" in f.message.lower()
    assert f.status != Status.failed


def test_tolerance_parameter():
    assert by_param(cross_check(mesh(length=62000), stated(length_overall=60000.0),
                                tolerance=0.01))["length_overall"].status == Status.needs_review


def test_missing_stated_value_is_needs_review():
    out = by_param(cross_check(mesh(), stated(length_overall=60000.0)))
    assert out["beam"].status == Status.needs_review
    assert "no stated" in out["beam"].message.lower()


def test_height_compared_with_draft_plus_air_draft():
    out = by_param(cross_check(mesh(height=30000), stated(draft=4000.0, air_draft=26000.0)))
    assert out["height"].status == Status.passed
    # only one component stated -> cannot compare
    out = by_param(cross_check(mesh(height=30000), stated(draft=4000.0)))
    assert out["height"].status == Status.needs_review


def test_cli(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(mesh().model_dump_json())
    b.write_text(stated(length_overall=60000.0, beam=15000.0).model_dump_json())
    assert main([str(a), str(b)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {f["status"] for f in out} >= {"pass", "needs_review"}
