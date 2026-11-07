"""D1: PDF text extraction + ship particulars. PDFs are generated in-test (no sample files in git).

Layouts mirror what real GA title blocks do (see docs/DATA.md samples):
- Dana-style: label and value on the same row, value further right, decimal comma ("69,80  m").
- 9281-style: values half a row lower than their labels and without a unit.
- GO SARS-style: no text layer at all (vector/scanned) -> must be reported, not silently empty.
"""
import pymupdf
import pytest

from app.design.pdf_text import (
    extract_lines,
    has_text_layer,
    parse_dimension_mm,
    parse_particulars,
)


def make_pdf(tmp_path, items, name="ga.pdf"):
    """items: list of (x, y, text). Returns path to a one-page PDF."""
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=10)
    path = tmp_path / name
    doc.save(path)
    return path


# ---------- dimension parsing ----------

@pytest.mark.parametrize("text,expected", [
    ("800", 800.0),            # bare number on a drawing = mm
    ("0.8 m", 800.0),
    ("69,80  m", 69800.0),     # decimal comma (European drawings)
    ("32 in", 812.8),
    ('2\'-8"', 812.8),         # feet-inches
    ("1200 mm", 1200.0),
    ("120 cm", 1200.0),
])
def test_parse_dimension_mm(text, expected):
    assert parse_dimension_mm(text) == pytest.approx(expected)


def test_parse_dimension_default_unit_for_bare_numbers():
    assert parse_dimension_mm("60,00", default_unit="m") == pytest.approx(60000.0)


@pytest.mark.parametrize("text", ["", "DAY ROOM", "ESC", "m"])
def test_parse_dimension_rejects_non_dimensions(text):
    assert parse_dimension_mm(text) is None


# ---------- text layer ----------

def test_extract_lines_returns_text_with_page_and_bbox(tmp_path):
    pdf = make_pdf(tmp_path, [(100, 100, "CABIN 101"), (400, 300, "DAY ROOM")])
    lines = extract_lines(pdf)
    texts = {l.text for l in lines}
    assert texts == {"CABIN 101", "DAY ROOM"}
    cabin = next(l for l in lines if l.text == "CABIN 101")
    assert cabin.page == 1
    x0, y0, x1, y1 = cabin.bbox
    assert x0 == pytest.approx(100, abs=2) and y1 == pytest.approx(100, abs=4)


def test_pdf_without_text_layer_is_reported(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 200, 200))  # vector-only drawing
    path = tmp_path / "vector_only.pdf"
    doc.save(path)
    assert has_text_layer(path) is False
    assert has_text_layer(make_pdf(tmp_path, [(10, 10, "X")], "t.pdf")) is True


# ---------- particulars ----------

def test_particulars_same_row_layout(tmp_path):
    pdf = make_pdf(tmp_path, [
        (800, 600, "PRINCIPAL PARTICULARS"),
        (800, 620, "LENGTH OVER ALL :"), (1000, 620, "69,80  m"),
        (800, 640, "LENGTH BETWEEN P.P.  :"), (1000, 640, "67,40  m"),
        (800, 660, "BREADTH MLD :"), (1000, 660, "16,00  m"),
        (800, 700, "ACCOMMODATION FOR 38 PERSONS"),
        (100, 620, "DAY ROOM"),                      # unrelated text on the same row, to the left
    ])
    r = parse_particulars(pdf)
    assert r.length_overall_m.value == pytest.approx(69.80)
    assert r.length_between_perpendiculars_m.value == pytest.approx(67.40)
    assert r.breadth_m.value == pytest.approx(16.00)
    assert r.persons_on_board.value == 38
    assert r.length_overall_m.provenance.method == "pdf_text"
    assert r.length_overall_m.provenance.page == 1
    assert r.length_overall_m.provenance.confidence >= 0.9   # explicit unit


def test_particulars_offset_values_without_unit(tmp_path):
    # values sit ~half a row lower than labels and carry no unit (9281-style)
    pdf = make_pdf(tmp_path, [
        (800, 600, "LENGTH O.A"),  (1050, 606, "60,00"),
        (800, 620, "LENGTH P.P."), (1050, 626, "52.20"),
        (800, 640, "BREADTH"),     (1050, 646, "15.00"),
    ])
    r = parse_particulars(pdf)
    assert r.length_overall_m.value == pytest.approx(60.0)
    assert r.length_between_perpendiculars_m.value == pytest.approx(52.2)
    assert r.breadth_m.value == pytest.approx(15.0)
    # unit was assumed (metres) -> lower confidence, so the evaluator can flag it
    assert r.breadth_m.provenance.confidence < 0.9


def test_particulars_inline_value(tmp_path):
    pdf = make_pdf(tmp_path, [(100, 100, "LOA: 75.5 m"), (100, 120, "Gross tonnage 3 250")])
    r = parse_particulars(pdf)
    assert r.length_overall_m.value == pytest.approx(75.5)
    assert r.gross_tonnage.value == pytest.approx(3250)


def test_missing_particulars_are_none_not_guessed(tmp_path):
    pdf = make_pdf(tmp_path, [(100, 100, "LENGTH OVER ALL :")])   # label without any value
    r = parse_particulars(pdf)
    assert r.length_overall_m is None
    ship = r.to_ship_particulars()
    assert ship.length_overall_m is None
    assert ship.ship_type is None     # never inferred from free text


def test_to_ship_particulars_keeps_provenance(tmp_path):
    pdf = make_pdf(tmp_path, [(800, 620, "LENGTH OVER ALL :"), (1000, 620, "69,80  m")])
    ship = parse_particulars(pdf).to_ship_particulars()
    assert ship.length_overall_m == pytest.approx(69.80)
    assert len(ship.provenance) == 1
    assert ship.provenance[0].file.endswith("ga.pdf")
    assert ship.provenance[0].bbox is not None


# ---------- regressions found on the real sample drawings ----------

def test_cabin_labels_are_not_persons_on_board(tmp_path):
    # Dana GA: hundreds of "1 PERS." / "2 PERS." cabin labels, total is in the title block
    pdf = make_pdf(tmp_path, [(100, 100, "1 PERS."), (200, 100, "2 PERS."),
                              (800, 700, "ACCOMMODATION FOR 38 PERSONS")])
    assert parse_particulars(pdf).persons_on_board.value == 38


def test_unit_in_separate_cell_between_label_and_value(tmp_path):
    # RCRV particulars table: "Beam (at Main Deck) | ft | 41"
    pdf = make_pdf(tmp_path, [(100, 100, "Beam (at Main Deck)"), (300, 100, "ft"), (350, 100, "41")])
    b = parse_particulars(pdf).breadth_m
    assert b.value == pytest.approx(41 * 0.3048)
    assert b.provenance.confidence >= 0.9


def test_unit_in_label_parentheses(tmp_path):
    pdf = make_pdf(tmp_path, [(100, 100, "Beam, Overall (ft.)"), (300, 100, "50")])
    assert parse_particulars(pdf).breadth_m.value == pytest.approx(50 * 0.3048)


def test_assumed_unit_falls_below_evaluator_trust_threshold(tmp_path):
    from app.check.evaluator import LOW_CONFIDENCE
    pdf = make_pdf(tmp_path, [(100, 100, "BREADTH"), (300, 100, "15.00")])
    assert parse_particulars(pdf).breadth_m.provenance.confidence < LOW_CONFIDENCE


def test_prose_mentioning_beam_is_not_a_label(tmp_path):
    pdf = make_pdf(tmp_path, [(100, 100, "In beam seas, roll of the monohull can be as much as"),
                              (500, 100, "28")])
    assert parse_particulars(pdf).breadth_m is None
