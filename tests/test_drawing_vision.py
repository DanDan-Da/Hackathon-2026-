"""D2: GA drawing vision extraction. Uses a fake LLM provider — no network, deterministic."""
import json

import pymupdf
import pytest

from app.design.drawing_vision import (
    TileElement,
    TileExtraction,
    TileProperty,
    extract_drawing,
    render_tiles,
)
from app.models import DesignFacts
from app.providers.llm import LLMProvider


class FakeVision(LLMProvider):
    """Returns a scripted TileExtraction per tile, keyed by the tile's page/origin."""

    def __init__(self, script=None, default=None):
        self.script = script or {}
        self.default = default or TileExtraction(elements=[])
        self.calls = []

    def complete(self, system, prompt):
        raise NotImplementedError

    def complete_structured(self, system, prompt, schema, images_png=None):
        assert schema is TileExtraction
        assert images_png and images_png[0][:8] == b"\x89PNG\r\n\x1a\n"
        self.calls.append(prompt)
        for key, value in self.script.items():
            if key in prompt:
                return value
        return self.default


def make_ga(tmp_path, w=1200, h=800, marks=((100, 100),)):
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    for x, y in marks:
        page.draw_rect(pymupdf.Rect(x, y, x + 60, y + 30))   # something to "see" (non-blank)
    path = tmp_path / "ga.pdf"
    doc.save(path)
    return path


def box(px, tile_w=800, tile_h=800):
    """Pixel bbox (x0, y0, x1, y1) in a tile -> Gemini-style box_2d [ymin, xmin, ymax, xmax] in 0..1000."""
    x0, y0, x1, y1 = px
    return [y0 / tile_h * 1000, x0 / tile_w * 1000, y1 / tile_h * 1000, x1 / tile_w * 1000]


def door(name="Cabin 101 door", bbox=(10, 10, 50, 30), width_text="760", conf=0.9, tile_w=800, tile_h=800):
    return TileElement(type="door", name=name, space_type="accessible_route", box_2d=box(bbox, tile_w, tile_h),
                       properties=[TileProperty(name="clear_width", text=width_text)],
                       evidence_text=f"D {width_text}", confidence=conf)


# ---------- tiling ----------

def test_render_tiles_cover_page_with_overlap(tmp_path):
    pdf = make_ga(tmp_path, marks=[(x, y) for x in range(0, 1200, 150) for y in range(0, 800, 150)])
    tiles = render_tiles(pdf, dpi=144, tile_px=800, overlap_px=100)   # 2 px per pt -> 2400x1600 px
    assert {t.page for t in tiles} == {1}
    xs = sorted({t.origin_pt[0] for t in tiles})
    ys = sorted({t.origin_pt[1] for t in tiles})
    assert xs[0] == 0 and ys[0] == 0
    assert len(xs) >= 3 and len(ys) >= 2                       # 2400/700 -> 4 cols, 1600/700 -> 3 rows
    step_pt = xs[1] - xs[0]
    assert step_pt == pytest.approx((800 - 100) / 2)           # overlap honoured
    for t in tiles:
        assert t.png[:8] == b"\x89PNG\r\n\x1a\n"
        assert t.pt_per_px == pytest.approx(0.5)


def test_blank_tiles_are_skipped(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])                  # one mark in the top-left corner only
    tiles = render_tiles(pdf, dpi=144, tile_px=800, overlap_px=100)
    assert len(tiles) == 1 and tiles[0].origin_pt == (0, 0)


# ---------- extraction ----------

def test_element_bbox_mapped_to_pdf_points_and_dimension_to_mm(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision(default=TileExtraction(elements=[door(bbox=(100, 200, 140, 220), width_text="760")]))
    facts = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100)
    assert isinstance(facts, DesignFacts)
    [el] = facts.elements
    assert el.type == "door"
    assert el.properties["clear_width"] == pytest.approx(760)
    assert el.provenance.method == "vision"
    assert el.provenance.page == 1
    assert el.provenance.bbox == pytest.approx((50, 100, 70, 110))   # px * 0.5 pt/px + origin (0,0)
    assert el.provenance.file.endswith("ga.pdf")
    assert el.provenance.confidence == pytest.approx(0.9)


def test_unparseable_dimension_is_dropped_not_guessed(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision(default=TileExtraction(elements=[door(width_text="see detail A")]))
    [el] = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100).elements
    assert "clear_width" not in el.properties          # evaluator will then say needs_review


def test_duplicates_from_overlapping_tiles_are_merged(tmp_path):
    # mark sits in the overlap band of two horizontally adjacent tiles
    pdf = make_ga(tmp_path, w=800, h=300, marks=[(330, 100)])
    # tile 0 origin x=0, tile 1 origin x=350 pt (dpi 144, 800 px tiles, 100 px overlap)
    llm = FakeVision(script={
        "origin=(0,0)": TileExtraction(elements=[door(bbox=(680, 200, 760, 260), conf=0.8, tile_h=600)]),
        "origin=(350,0)": TileExtraction(elements=[door(bbox=(-20, 200, 60, 260), conf=0.95, tile_h=600)]),
    })
    facts = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100)
    doors = [e for e in facts.elements if e.type == "door"]
    assert len(doors) == 1
    assert doors[0].provenance.confidence == pytest.approx(0.95)   # keep the better read


def test_same_type_far_apart_are_not_merged(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision(default=TileExtraction(elements=[
        door(name="Cabin 101 door", bbox=(10, 10, 50, 30)),
        door(name="Cabin 102 door", bbox=(600, 10, 640, 30))]))
    facts = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100)
    assert len(facts.elements) == 2
    assert len({e.id for e in facts.elements}) == 2


def test_confidence_is_clamped(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision(default=TileExtraction(elements=[door(conf=1.7)]))
    [el] = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100).elements
    assert el.provenance.confidence == 1.0


def test_particulars_come_from_text_layer_when_present(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=1200, height=800)
    page.insert_text((800, 620), "LENGTH OVER ALL :", fontsize=10)
    page.insert_text((1000, 620), "69,80  m", fontsize=10)
    path = tmp_path / "ga.pdf"
    doc.save(path)
    facts = extract_drawing(path, project="demo", llm=FakeVision(), dpi=72, tile_px=800, overlap_px=100)
    assert facts.particulars.length_overall_m == pytest.approx(69.8)
    assert facts.source_files == [str(path)]


def test_facts_json_round_trips(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision(default=TileExtraction(elements=[door()]))
    facts = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100)
    again = DesignFacts.model_validate(json.loads(facts.model_dump_json()))
    assert again == facts


def test_each_tile_prompt_states_its_origin_and_page(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    llm = FakeVision()
    extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100)
    assert llm.calls and all("page=1" in c and "origin=(" in c for c in llm.calls)


@pytest.mark.parametrize("text,expected", [("15 m2", 15.0), ("15 m²", 15.0), ("83 m^2", 83.0), ("12,5 m2", 12.5)])
def test_area_property_parsed_to_m2(tmp_path, text, expected):
    # Dana GA prints room areas as "15 m²" next to the room name
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    cabin = TileElement(type="cabin", name="2 PERS.", box_2d=[0, 0, 50, 50],
                        properties=[TileProperty(name="area", text=text)], evidence_text=f"2 PERS. {text}",
                        confidence=0.9)
    llm = FakeVision(default=TileExtraction(elements=[cabin]))
    [el] = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100).elements
    assert el.properties["area"] == pytest.approx(expected)


def test_box_2d_uses_each_tiles_own_size_and_yx_order(tmp_path):
    # 800x300 pt page at 144 dpi -> 1600x600 px; first tile is 800 px wide but only 600 px high
    pdf = make_ga(tmp_path, w=800, h=300, marks=[(50, 50)])
    el = TileElement(type="stairway", box_2d=[500, 250, 1000, 500], evidence_text="UP", confidence=0.9)
    llm = FakeVision(script={"origin=(0,0)": TileExtraction(elements=[el])})
    [st] = extract_drawing(pdf, project="demo", llm=llm, dpi=144, tile_px=800, overlap_px=100).elements
    # x: 250/1000*800 px = 200 px -> 100 pt ; y: 500/1000*600 px = 300 px -> 150 pt
    assert st.provenance.bbox == pytest.approx((100, 150, 200, 300))


def test_box_2d_outside_tile_is_clamped(tmp_path):
    pdf = make_ga(tmp_path, marks=[(50, 50)])
    el = TileElement(type="door", box_2d=[-30, -30, 1200, 500], evidence_text="", confidence=0.9)
    [d] = extract_drawing(pdf, project="demo", llm=FakeVision(default=TileExtraction(elements=[el])),
                          dpi=144, tile_px=800, overlap_px=100).elements
    assert d.provenance.bbox == pytest.approx((0, 0, 200, 400))   # clamped to the 800x800 px tile


# ---------- resumable runs (tile cache) ----------

def test_cached_rerun_makes_no_llm_calls(tmp_path):
    pdf = make_ga(tmp_path)
    cache = tmp_path / "cache"
    first = FakeVision(default=TileExtraction(elements=[door()]))
    first.model = "m1"
    facts1 = extract_drawing(pdf, "demo", llm=first, dpi=72, tile_px=2000, cache_dir=cache)
    assert len(first.calls) >= 1

    second = FakeVision()          # would return nothing if it were asked
    second.model = "m1"
    facts2 = extract_drawing(pdf, "demo", llm=second, dpi=72, tile_px=2000, cache_dir=cache)
    assert second.calls == []
    assert facts2 == facts1


def test_cache_is_per_model(tmp_path):
    pdf = make_ga(tmp_path)
    cache = tmp_path / "cache"
    a = FakeVision(default=TileExtraction(elements=[door()]))
    a.model = "model-a"
    extract_drawing(pdf, "demo", llm=a, dpi=72, tile_px=2000, cache_dir=cache)

    b = FakeVision(default=TileExtraction(elements=[]))
    b.model = "model-b"
    facts_b = extract_drawing(pdf, "demo", llm=b, dpi=72, tile_px=2000, cache_dir=cache)
    assert len(b.calls) >= 1 and facts_b.elements == []


def test_cache_is_per_pdf_content(tmp_path):
    cache = tmp_path / "cache"
    pdf1 = make_ga(tmp_path, marks=((100, 100),))
    a = FakeVision(default=TileExtraction(elements=[door()]))
    a.model = "m"
    extract_drawing(pdf1, "demo", llm=a, dpi=72, tile_px=2000, cache_dir=cache)

    pdf1.unlink()
    pdf2 = make_ga(tmp_path, marks=((300, 300),))      # same filename, different drawing
    b = FakeVision()
    b.model = "m"
    extract_drawing(pdf2, "demo", llm=b, dpi=72, tile_px=2000, cache_dir=cache)
    assert len(b.calls) >= 1
