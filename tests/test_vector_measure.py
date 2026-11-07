"""D: vector measurement of door swings on synthetic PDFs with a known width."""
import math

import pymupdf
import pytest

from app.design import vector_measure as vm

PT_MM = 25.4 / 72  # one PDF point on paper, in mm


def _pt_per_mm(scale: int) -> float:
    return 1 / (PT_MM * scale)


def _door(shape, hinge, w_pt, a0=0.0, a1=90.0, leaf=True, n=24):
    """Quarter-circle swing polyline around `hinge`, leaf drawn at the closed position."""
    hx, hy = hinge
    pts = [(hx + w_pt * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
            hy - w_pt * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    shape.draw_polyline(pts)
    shape.finish(width=0.2)
    if leaf:
        shape.draw_line(hinge, pts[0])
        shape.finish(width=0.2)


def _pdf(tmp_path, build, text="Scale (U.N.O.): 1:100"):
    path = tmp_path / "t.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    shape = page.new_shape()
    build(shape)
    shape.commit()
    if text:
        page.insert_text((600, 570), text)
    doc.save(path)
    return path


def test_parse_scale():
    assert vm.parse_scale("Scale (U.N.O.): 1:150") == 150
    assert vm.parse_scale("1 : 50") == 50
    assert vm.parse_scale("no scale here") is None
    assert vm.parse_scale("ratio 3:1") is None


def test_mm_per_pt():
    assert vm.mm_per_pt(100) == pytest.approx(35.2778, rel=1e-4)
    assert vm.mm_per_pt(150) == pytest.approx(52.9167, rel=1e-4)


def test_find_scale_in_text_layer(tmp_path):
    path = _pdf(tmp_path, lambda s: None)
    assert vm.find_scale(path) == 100


def test_find_scale_missing(tmp_path):
    path = _pdf(tmp_path, lambda s: None, text="")
    assert vm.find_scale(path) is None


def test_detects_door_swing_with_known_width(tmp_path):
    w = 900 * _pt_per_mm(100)
    path = _pdf(tmp_path, lambda s: _door(s, (300, 300), w))
    doors = vm.measure_doors(path, 100)
    assert len(doors) == 1
    assert doors[0].width_mm == pytest.approx(900, rel=0.03)
    x0, y0, x1, y1 = doors[0].bbox
    assert x0 == pytest.approx(300, abs=1) and x1 == pytest.approx(300 + w, abs=1)


@pytest.mark.parametrize("width_mm", [700, 800, 1000, 1200])
def test_widths_scale_with_stated_scale(tmp_path, width_mm):
    w = width_mm * _pt_per_mm(50)
    path = _pdf(tmp_path, lambda s: _door(s, (200, 200), w))
    doors = vm.measure_doors(path, 50)
    assert [round(d.width_mm / 10) for d in doors] == [round(width_mm / 10)]


def test_bezier_arc_is_detected(tmp_path):
    w = 800 * _pt_per_mm(100)

    def build(s):
        k = 0.5523 * w  # quarter circle as one cubic bezier
        s.draw_bezier((300 + w, 300), (300 + w, 300 - k), (300 + k, 300 - w), (300, 300 - w))
        s.finish(width=0.2)
        s.draw_line((300, 300), (300 + w, 300))
        s.finish(width=0.2)

    path = _pdf(tmp_path, build)
    doors = vm.measure_doors(path, 100)
    assert len(doors) == 1 and doors[0].width_mm == pytest.approx(800, rel=0.03)


def test_arc_without_leaf_is_rejected(tmp_path):
    w = 900 * _pt_per_mm(100)
    path = _pdf(tmp_path, lambda s: _door(s, (300, 300), w, leaf=False))
    assert vm.measure_doors(path, 100) == []


def test_full_circle_is_not_a_door(tmp_path):
    w = 900 * _pt_per_mm(100)

    def build(s):
        s.draw_circle((300, 300), w)
        s.finish(width=0.2)
        s.draw_line((300, 300), (300 + w, 300))
        s.finish(width=0.2)

    assert vm.measure_doors(_pdf(tmp_path, build), 100) == []


def test_implausible_sizes_are_rejected(tmp_path):
    tiny = 100 * _pt_per_mm(100)    # 100 mm
    huge = 4000 * _pt_per_mm(100)   # 4 m
    path = _pdf(tmp_path, lambda s: (_door(s, (100, 100), tiny), _door(s, (300, 400), huge)))
    assert vm.measure_doors(path, 100) == []


def test_flat_shallow_arc_is_rejected(tmp_path):
    w = 900 * _pt_per_mm(100)
    path = _pdf(tmp_path, lambda s: _door(s, (300, 300), w, a0=0, a1=30))
    assert vm.measure_doors(path, 100) == []


def test_fit_circle_recovers_radius():
    pts = [(10 + 5 * math.cos(t / 10), 20 + 5 * math.sin(t / 10)) for t in range(0, 15)]
    cx, cy, r, rms = vm.fit_circle(pts)
    assert (cx, cy, r) == pytest.approx((10, 20, 5), abs=1e-6) and rms < 1e-6


def test_scale_check_against_known_dimension():
    # a 69.80 m dimension drawn at 1:150 spans 69800/52.9167 pt
    span_pt = 69800 / vm.mm_per_pt(150)
    assert vm.scale_error(span_pt, 69_800, 150) == pytest.approx(0, abs=1e-6)
    assert vm.scale_error(span_pt * 1.05, 69_800, 150) == pytest.approx(0.05, abs=1e-6)


def _cand(bbox, w=800.0):
    return vm.DoorCandidate(width_mm=w, bbox=bbox, center=(bbox[0], bbox[3]), radius_pt=10,
                            span_deg=90, rms_frac=0.001)


def _facts(props=None):
    return {"elements": [{"id": "d1", "type": "door", "properties": props or {},
                          "provenance": {"file": "x", "bbox": [100, 100, 120, 120], "method": "vision",
                                         "confidence": 0.59}}]}


def test_apply_fills_missing_clear_width_with_capped_confidence():
    f = _facts()
    st = vm.apply_to_facts(f, [_cand((105, 105, 125, 125))], "ga.pdf")
    el = f["elements"][0]
    assert st["filled"] == 1 and el["properties"]["clear_width"] == 800.0
    assert el["provenance"]["method"] == "vector" and el["provenance"]["confidence"] <= 0.6


def test_apply_never_overwrites_existing_value():
    f = _facts({"clear_width": 900.0})
    st = vm.apply_to_facts(f, [_cand((105, 105, 125, 125))], "ga.pdf")
    assert st["kept_existing"] == 1
    assert f["elements"][0]["properties"]["clear_width"] == 900.0
    assert f["elements"][0]["provenance"]["method"] == "vision"


def test_apply_ambiguous_match_is_skipped():
    f = _facts()
    vm.apply_to_facts(f, [_cand((105, 105, 125, 125)), _cand((110, 110, 130, 130))], "ga.pdf")
    assert "clear_width" not in f["elements"][0]["properties"]


def test_unmatched_added_only_on_request():
    f = _facts()
    c = [_cand((500, 500, 520, 520))]
    assert vm.apply_to_facts(f, c, "ga.pdf")["unmatched"] == 1 and len(f["elements"]) == 1
    assert vm.apply_to_facts(f, c, "ga.pdf", add_new=True)["added"] == 1 and len(f["elements"]) == 2


def test_cli_roundtrip(tmp_path):
    import json
    w = 900 * _pt_per_mm(100)
    pdf = _pdf(tmp_path, lambda s: _door(s, (300, 300), w))
    fp = tmp_path / "f.json"
    fp.write_text(json.dumps(_facts()))
    out = tmp_path / "o.json"
    assert vm.main([str(fp), str(pdf), "-o", str(out), "--add-new"]) == 0
    els = json.loads(out.read_text())["elements"]
    assert len(els) == 2 and els[1]["properties"]["clear_width"] == pytest.approx(900, rel=0.03)


def test_cli_refuses_without_scale(tmp_path):
    import json
    pdf = _pdf(tmp_path, lambda s: None, text="")
    fp = tmp_path / "f.json"
    fp.write_text(json.dumps(_facts()))
    assert vm.main([str(fp), str(pdf), "-o", str(tmp_path / "o.json")]) == 2
