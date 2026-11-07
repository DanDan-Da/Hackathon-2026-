"""Labelled values from particulars-style PDFs (generated in-test, no sample files)."""
import json

import pymupdf
import pytest

from app.design.particulars_text import read_stated_particulars


def make_pdf(tmp_path, rows, name="p.pdf"):
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    y = 50
    for text in rows:
        page.insert_text((50, y), text, fontsize=10)
        y += 20
    path = tmp_path / name
    doc.save(path)
    return path


def by_param(facts):
    return {e.properties["parameter"]: e for e in facts.elements if e.type == "stated_particular"}


def test_table_layout_label_unit_value_on_separate_lines(tmp_path):
    p = make_pdf(tmp_path, ["Length (overall)", "ft", "199.5", "Beam (at Main Deck)", "ft", "41",
                            "Beam (overall)", "ft", "50", "Air Draft", "ft", "88.5"])
    got = by_param(read_stated_particulars(p, project="x"))
    assert got["length_overall"].properties["value"] == pytest.approx(199.5 * 304.8)
    assert got["beam"].properties["value"] == pytest.approx(50 * 304.8)   # overall, not main deck
    assert got["air_draft"].properties["value"] == pytest.approx(88.5 * 304.8)
    prov = got["length_overall"].provenance
    assert prov.method == "pdf_text" and prov.page == 1 and prov.bbox is not None
    assert prov.file == str(p)
    assert "199.5" in got["length_overall"].properties["quote"]


def test_same_line_feet_inches_with_dot_leaders(tmp_path):
    p = make_pdf(tmp_path, ["Length Overall ......................... 192' - 10\"",
                            "Design Draft ........................ 12' - 6\"",
                            "Depth, Baseline to Main Deck ............. 19' - 0\""])
    got = by_param(read_stated_particulars(p))
    assert got["length_overall"].properties["value"] == pytest.approx((192 * 12 + 10) * 25.4)
    assert got["draft"].properties["value"] == pytest.approx((12 * 12 + 6) * 25.4)
    assert got["depth"].properties["value"] == pytest.approx(19 * 12 * 25.4)


def test_metres_with_unit_after_value(tmp_path):
    p = make_pdf(tmp_path, ["Beam, overall 15,2 m"])
    assert by_param(read_stated_particulars(p))["beam"].properties["value"] == pytest.approx(15200)


def test_value_without_unit_is_not_guessed(tmp_path):
    p = make_pdf(tmp_path, ["Length overall", "199.5", "Other thing"])
    facts = read_stated_particulars(p)
    assert by_param(facts) == {}


def test_labels_come_from_config(tmp_path):
    cfg = tmp_path / "labels.json"
    cfg.write_text(json.dumps({"fields": {"length_overall": ["laenge ueber alles"]}}))
    p = make_pdf(tmp_path, ["Laenge ueber alles 60 m", "Length overall 5 m"])
    got = by_param(read_stated_particulars(p, labels_path=cfg))
    assert list(got) == ["length_overall"]
    assert got["length_overall"].properties["value"] == pytest.approx(60000)
