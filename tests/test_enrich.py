"""Post-processing of extracted facts with the drawing's own text layer (fake PDFs, no sample files)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf

from app.design.enrich import cabin_summary_findings, enrich, parse_cabin_summary, read_ship_type
from app.models import DesignElement, DesignFacts, Provenance, ShipParticulars


def make_pdf(tmp_path, rows, name="d.pdf"):
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=800)
    y = 50
    for text in rows:
        page.insert_text((50, y), text, fontsize=10)
        y += 20
    path = tmp_path / name
    doc.save(path)
    return path


def el(i, typ, name, conf=0.8, **kw):
    return DesignElement(id=i, type=typ, name=name, **kw,
                         provenance=Provenance(file="x.pdf", page=1, method="vision", confidence=conf))


def test_ship_type_copied_as_printed_with_provenance(tmp_path):
    p = make_pdf(tmp_path, ["BV CLASS:", "Special Service/Research Vessel SP38, ICE CLASS"])
    got = read_ship_type(p)
    assert got is not None
    text, prov = got
    assert text == "Research Vessel"
    assert prov.method == "pdf_text" and prov.confidence == 0.9 and prov.bbox and prov.page == 1


def test_ship_type_absent_or_ambiguous_is_none(tmp_path):
    assert read_ship_type(make_pdf(tmp_path, ["GENERAL ARRANGEMENT"])) is None
    assert read_ship_type(make_pdf(tmp_path, ["Research Vessel", "Passenger Ship"], "b.pdf")) is None


def test_enrich_sets_ship_type_but_never_overwrites(tmp_path):
    p = make_pdf(tmp_path, ["Research Vessel"])
    facts = DesignFacts(project="x")
    out = enrich(facts, p)
    assert out.particulars.ship_type == "Research Vessel"
    assert len(out.particulars.provenance) == 1
    assert facts.particulars.ship_type is None            # input not mutated
    keep = DesignFacts(project="x", particulars=ShipParticulars(ship_type="Cargo Ship"))
    assert enrich(keep, p).particulars.ship_type == "Cargo Ship"


def test_space_type_from_name_only_when_exactly_one_entry_matches(tmp_path):
    p = make_pdf(tmp_path, ["nothing"])
    facts = DesignFacts(project="x", elements=[
        el("a", "cabin", "1 PERS. (CAPTAIN)"),
        el("b", "toilet", "WC"),
        el("c", "space", "SICKBAY"),
        el("d", "space", "MESS / GALLEY"),       # two entries match -> unset
        el("e", "space", "VOID"),                # none -> unset
        el("f", "space", None),
        el("g", "cabin", "1 PERS.", space_type="stateroom"),   # already set -> kept
    ])
    out = {e.id: e for e in enrich(facts, p).elements}
    assert out["a"].space_type == "cabin" and out["a"].properties["space_type_source"] == "name"
    assert out["b"].space_type == "toilet"
    assert out["c"].space_type == "hospital"
    for k in "def":
        assert out[k].space_type is None and "space_type_source" not in out[k].properties
    assert out["g"].space_type == "stateroom"
    assert out["a"].provenance.confidence == 0.8           # unchanged


def test_parse_cabin_summary_same_line_and_split_lines(tmp_path):
    p = make_pdf(tmp_path, ["SHELTER DECK: 6 SINGLE AND 10 DOUBLE CABINS", "FO'C'SLE DECK:",
                            "12 SINGLE CABINS, HOSPITAL"])
    got = parse_cabin_summary(p)
    assert [(g["deck"], g["counts"], g["total"]) for g in got] == [
        ("SHELTER DECK", {"single": 6, "double": 10}, 16),
        ("FO'C'SLE DECK", {"single": 12}, 12)]
    assert all(g["provenance"].method == "pdf_text" and g["provenance"].bbox for g in got)


def test_cabin_findings_match_and_mismatch(tmp_path):
    p = make_pdf(tmp_path, ["SHELTER DECK: 1 SINGLE AND 1 DOUBLE CABINS"])
    ok = DesignFacts(project="x", elements=[el("a", "cabin", "1 PERS."), el("b", "cabin", "2 PERS."),
                                            el("c", "toilet", "WC")])
    f = cabin_summary_findings(ok, p)
    assert len(f) == 1 and f[0].status == "pass" and f[0].measured == 2
    assert f[0].rule_source.quote and "SINGLE" in f[0].rule_source.quote
    assert len(f[0].evidence) == 2
    bad = DesignFacts(project="x", elements=[el("a", "cabin", "1 PERS.")])
    f = cabin_summary_findings(bad, p)
    assert f[0].status == "needs_review" and f[0].measured == 1
    assert cabin_summary_findings(ok, make_pdf(tmp_path, ["nothing"], "n.pdf")) == []


def test_cli_writes_enriched_facts_and_report(tmp_path):
    p = make_pdf(tmp_path, ["Research Vessel", "SHELTER DECK: 1 SINGLE CABINS"])
    fp = tmp_path / "f.json"
    fp.write_text(DesignFacts(project="x", elements=[el("a", "cabin", "1 PERS.")]).model_dump_json())
    out, rep = tmp_path / "o.json", tmp_path / "r.json"
    r = subprocess.run([sys.executable, "-m", "app.design.enrich", str(fp), str(p), "-o", str(out),
                        "--report", str(rep)], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(Path.cwd())})
    assert r.returncode == 0, r.stderr
    data = json.loads(out.read_text())
    assert data["particulars"]["ship_type"] == "Research Vessel"
    assert data["elements"][0]["space_type"] == "cabin"
    assert json.loads(rep.read_text())[0]["status"] == "pass"
