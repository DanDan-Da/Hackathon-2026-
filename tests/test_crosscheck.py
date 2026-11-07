"""D3: cross-check vision values against the PDF text layer. Fake LLM, PDFs made with pymupdf."""
import pymupdf

from app.check.evaluator import LOW_CONFIDENCE
from app.design.crosscheck import CONFIRMED_CONF, UNCONFIRMED_CAP, crosscheck
from app.design.drawing_vision import (
    TileElement, TileExtraction, TileProperty, extract_drawing,
)
from app.design.pdf_text import extract_lines
from app.models import DesignElement, DesignFacts, Provenance
from app.providers.llm import LLMProvider


class FakeVision(LLMProvider):
    def __init__(self, extraction):
        self.extraction = extraction

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        return self.extraction


def make_pdf(tmp_path, labels, name="ga.pdf"):
    """labels: [(text, x, y)] baseline positions in points."""
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    for text, x, y in labels:
        page.insert_text((x, y), text, fontsize=10)
    path = tmp_path / name
    doc.save(path)
    return path


def room(id, name, bbox, conf=0.95, **props):
    return DesignElement(id=id, type="space", name=name, properties=props,
                         provenance=Provenance(file="ga.pdf", page=1, bbox=bbox, method="vision", confidence=conf))


def run(tmp_path, labels, elements):
    pdf = make_pdf(tmp_path, labels)
    facts = DesignFacts(project="p", elements=elements)
    return crosscheck(facts, extract_lines(pdf))


MESS = [("MESS", 120, 150), ("83 m²", 120, 170)]


def test_confirmed_name_and_area(tmp_path):
    facts, rep = run(tmp_path, MESS, [room("a", "Mess", (100, 120, 220, 200), conf=0.7, area=83.0)])
    el = facts.elements[0]
    assert rep.confirmed == ["a"] and not rep.capped and not rep.corrections
    assert el.provenance.confidence >= CONFIRMED_CONF
    assert el.provenance.bbox == (100, 120, 220, 200)          # vision bbox kept
    assert el.properties["area"] == 83.0 and "text_label_bbox" in el.properties
    assert rep.unmatched_labels == []


def test_wrong_vision_area_replaced_and_recorded(tmp_path):
    facts, rep = run(tmp_path, MESS, [room("a", "MESS", (100, 120, 220, 200), area=38.0)])
    el = facts.elements[0]
    assert el.properties["area"] == 83.0
    assert el.properties["area_vision_value"] == 38.0
    assert rep.corrections[0].element_id == "a" and rep.corrections[0].text_value == 83.0
    assert rep.confirmed == ["a"] and el.provenance.confidence >= CONFIRMED_CONF


def test_decimal_comma_area(tmp_path):
    labels = [("GALLEY", 120, 150), ("12,5 m²", 120, 170)]
    facts, rep = run(tmp_path, labels, [room("a", "GALLEY", (100, 120, 220, 200), area=12.5)])
    assert rep.confirmed == ["a"] and not rep.corrections
    facts, rep = run(tmp_path, labels, [room("a", "GALLEY", (100, 120, 220, 200), area=125.0)])
    assert facts.elements[0].properties["area"] == 12.5


def test_no_text_confirmation_caps_confidence(tmp_path):
    facts, rep = run(tmp_path, MESS, [room("a", "BRIDGE", (100, 120, 220, 200), conf=1.0)])
    assert rep.capped == ["a"]
    assert facts.elements[0].provenance.confidence == UNCONFIRMED_CAP < LOW_CONFIDENCE


def test_never_lowers_already_low_confidence(tmp_path):
    facts, _ = run(tmp_path, MESS, [room("a", "BRIDGE", (100, 120, 220, 200), conf=0.2)])
    assert facts.elements[0].provenance.confidence == 0.2


def test_slightly_off_bbox_still_confirms(tmp_path):
    # box shifted left/up: label centre is outside the box but inside the tolerance margin
    facts, rep = run(tmp_path, MESS, [room("a", "MESS", (60, 100, 124, 160), area=83.0)])
    assert rep.confirmed == ["a"]


def test_label_of_other_room_does_not_confirm(tmp_path):
    labels = [("CABIN 1", 120, 150), ("CABIN 2", 320, 150)]
    els = [room("a", "CABIN 2", (100, 120, 220, 200)),      # named CABIN 2 but the box is room 1
           room("b", "CABIN 2", (300, 120, 420, 200))]
    facts, rep = run(tmp_path, labels, els)
    assert rep.confirmed == ["b"] and rep.capped == ["a"]
    assert facts.elements[0].provenance.confidence == UNCONFIRMED_CAP
    assert [l.text for l in rep.unmatched_labels] == ["CABIN 1"]


def test_longer_name_does_not_confirm_shorter(tmp_path):
    facts, rep = run(tmp_path, [("OFFICERS MESS", 120, 150)], [room("a", "MESS", (100, 120, 260, 200))])
    assert rep.capped == ["a"]


def test_door_width_corrected_from_text(tmp_path):
    labels = [("D1", 120, 150), ("800", 120, 165)]
    door = DesignElement(id="d", type="door", name="D1", properties={"clear_width": 760.0},
                         provenance=Provenance(file="ga.pdf", page=1, bbox=(100, 120, 160, 175),
                                               method="vision", confidence=0.9))
    facts, rep = run(tmp_path, labels, [door])
    assert facts.elements[0].properties["clear_width"] == 800.0
    assert facts.elements[0].properties["clear_width_vision_value"] == 760.0


def test_does_not_mutate_input(tmp_path):
    el = room("a", "BRIDGE", (100, 120, 220, 200), conf=1.0)
    facts = DesignFacts(project="p", elements=[el])
    crosscheck(facts, extract_lines(make_pdf(tmp_path, MESS)))
    assert el.provenance.confidence == 1.0


# ---------- wired into extract_drawing ----------

def _tile_elem(name, bbox, area):
    x0, y0, x1, y1 = bbox
    return TileElement(type="space", name=name,
                       box_2d=[y0 / 800 * 1000, x0 / 1200 * 1000, y1 / 800 * 1000, x1 / 1200 * 1000],
                       properties=[TileProperty(name="area", text=area)], evidence_text=name, confidence=1.0)


def test_extract_drawing_applies_crosscheck_with_text_layer(tmp_path):
    pdf = make_pdf(tmp_path, MESS)
    llm = FakeVision(TileExtraction(elements=[_tile_elem("MESS", (100, 120, 220, 200), "38 m2"),
                                              _tile_elem("GHOST", (500, 500, 600, 560), "10 m2")]))
    facts = extract_drawing(pdf, "p", llm=llm, dpi=72, tile_px=1568)
    by = {e.name: e for e in facts.elements}
    assert by["MESS"].properties["area"] == 83.0 and by["MESS"].provenance.confidence >= CONFIRMED_CONF
    assert by["GHOST"].provenance.confidence == UNCONFIRMED_CAP


def test_extract_drawing_without_text_layer_unchanged(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    page.draw_rect(pymupdf.Rect(100, 120, 220, 200))
    pdf = tmp_path / "scan.pdf"
    doc.save(pdf)
    llm = FakeVision(TileExtraction(elements=[_tile_elem("MESS", (100, 120, 220, 200), "38 m2")]))
    facts = extract_drawing(pdf, "p", llm=llm, dpi=72, tile_px=1568)
    el = facts.elements[0]
    assert el.provenance.confidence == 1.0 and el.properties == {"area": 38.0}
