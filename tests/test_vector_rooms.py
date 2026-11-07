"""D: room rectangle measurement from vector wall lines on synthetic PDFs (scale 1:100)."""
import json

import pymupdf
import pytest

from app.design import vector_measure as vm
from app.design import vector_rooms as vr
from app.design.crosscheck import CONFIRMED_CONF

K = 1 / (25.4 / 72 * 100)   # PDF points per real mm at 1:100


def _rect(shape, x0, y0, x1, y1, width=0.15):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        shape.draw_line(a, b)
        shape.finish(width=width)


def _pdf(tmp_path, rects, text="Scale (U.N.O.): 1:100"):
    path = tmp_path / "r.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    sh = page.new_shape()
    for r in rects:
        _rect(sh, *r)
    sh.commit()
    if text:
        page.insert_text((600, 570), text)
    doc.save(path)
    return path


def _el(id_, bbox, area=None, type_="cabin"):
    props = {} if area is None else {"area": area}
    return {"id": id_, "type": type_, "name": "1 PERS.", "deck": None, "space_type": type_,
            "properties": props,
            "provenance": {"file": "x.pdf", "page": 1, "bbox": list(bbox), "element_id": None,
                           "method": "vision", "confidence": 1.0}}


# room 4000 x 3000 mm at (100,100)
W, H = 4000 * K, 3000 * K
ROOM = (100, 100, 100 + W, 100 + H)
LABEL = (150, 130, 190, 140)


def _run(tmp_path, rects, elements, **kw):
    path = _pdf(tmp_path, rects, **kw)
    facts = {"elements": elements}
    stats = vr.apply_rooms(facts, str(path), 100)
    return facts, stats


def test_measures_known_rectangle(tmp_path):
    facts, stats = _run(tmp_path, [ROOM], [_el("c1", LABEL)])
    p = facts["elements"][0]["properties"]
    assert p["room_long_side"] == pytest.approx(4000, rel=0.01)
    assert p["room_short_side"] == pytest.approx(3000, rel=0.01)
    assert stats["measured"] == 1
    prov = facts["elements"][0]["provenance"]
    assert prov["method"] == "vector"
    assert prov["bbox"] == pytest.approx(list(ROOM), abs=0.5)
    assert prov["confidence"] == vm.CONF_VECTOR


def test_agreeing_area_with_outline_match_confirms(tmp_path):
    outline = (105, 105, 200, 170)   # vision bbox lies inside the rectangle
    facts, stats = _run(tmp_path, [ROOM], [_el("c1", outline, area=12.0)])
    el = facts["elements"][0]
    assert el["provenance"]["confidence"] == CONFIRMED_CONF
    assert el["properties"]["room_area_check"] == "confirmed"
    assert stats["confirmed"] == 1


def test_area_within_tolerance_but_not_exact(tmp_path):
    facts, _ = _run(tmp_path, [ROOM], [_el("c1", LABEL, area=12.9)])   # rectangle is 7 % below
    assert facts["elements"][0]["provenance"]["confidence"] == CONFIRMED_CONF


def test_disagreeing_area_is_capped_and_flagged(tmp_path):
    facts, stats = _run(tmp_path, [ROOM], [_el("c1", LABEL, area=20.0)])
    el = facts["elements"][0]
    assert el["provenance"]["confidence"] <= vm.CONF_VECTOR
    assert el["properties"]["room_area_check"] == "disagree"
    assert stats["disagree"] == 1


def test_area_agrees_but_outline_not_inside_is_not_confirmed(tmp_path):
    # vision bbox sticks far outside the rectangle: area alone cannot pin the short side
    el = _el("c1", (60, 60, 400, 300), area=12.0)
    el["properties"]["text_label_bbox"] = "150,130,190,140"
    facts, _ = _run(tmp_path, [ROOM], [el])
    el = facts["elements"][0]
    assert el["provenance"]["confidence"] < 0.6
    assert el["properties"]["room_area_check"] == "agree_unconfirmed"


def test_rectangle_holding_another_rooms_label_is_skipped(tmp_path):
    other = _el("c2", (180, 150, 200, 160), area=12.0)   # its label sits inside the same rectangle
    facts, stats = _run(tmp_path, [ROOM], [_el("c1", LABEL, area=12.0), other])
    assert "room_long_side" not in facts["elements"][0]["properties"]
    assert stats["skipped_other_label"] == 2


def test_nested_toilet_inside_cabin_does_not_block(tmp_path):
    wc = _el("t1", (120, 105, 135, 115), type_="toilet")
    facts, _ = _run(tmp_path, [ROOM], [_el("c1", LABEL, area=12.0), wc])
    assert facts["elements"][0]["provenance"]["confidence"] == CONFIRMED_CONF


def test_no_printed_area_stays_capped(tmp_path):
    facts, _ = _run(tmp_path, [ROOM], [_el("c1", LABEL)])
    assert facts["elements"][0]["properties"]["room_area_check"] == "no_printed_area"
    assert facts["elements"][0]["provenance"]["confidence"] == vm.CONF_VECTOR


def test_concentric_nesting_is_ambiguous_and_skipped(tmp_path):
    outer = (ROOM[0] - 40, ROOM[1] - 40, ROOM[2] + 40, ROOM[3] + 40)
    facts, stats = _run(tmp_path, [ROOM, outer], [_el("c1", LABEL, area=12.0)])
    assert "room_long_side" not in facts["elements"][0]["properties"]
    assert stats["skipped_ambiguous"] == 1


def test_double_line_wall_is_not_ambiguous(tmp_path):
    thin = 1.0   # ~35 mm... a thin double wall face
    outer = (ROOM[0] - thin, ROOM[1] - thin, ROOM[2] + thin, ROOM[3] + thin)
    facts, stats = _run(tmp_path, [ROOM, outer], [_el("c1", LABEL)])
    assert stats["measured"] == 1
    assert facts["elements"][0]["properties"]["room_long_side"] == pytest.approx(4000, rel=0.02)


def test_open_box_is_skipped(tmp_path):
    path = tmp_path / "o.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    sh = page.new_shape()
    x0, y0, x1, y1 = ROOM
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x0, y1), (x0, y0))):   # bottom wall missing
        sh.draw_line(a, b)
        sh.finish(width=0.15)
    sh.commit()
    page.insert_text((600, 570), "Scale (U.N.O.): 1:100")
    doc.save(path)
    facts = {"elements": [_el("c1", LABEL)]}
    stats = vr.apply_rooms(facts, str(path), 100)
    assert stats["skipped_no_rect"] == 1


def test_short_furniture_lines_are_not_walls(tmp_path):
    furn = (110, 110, 110 + 700 * K, 110 + 500 * K)   # 0.7 m piece inside the room
    facts, _ = _run(tmp_path, [ROOM, furn], [_el("c1", (160, 140, 170, 150))])
    assert facts["elements"][0]["properties"]["room_long_side"] == pytest.approx(4000, rel=0.01)


def test_never_overwrites_existing_values(tmp_path):
    el = _el("c1", LABEL)
    el["properties"]["room_long_side"] = 9999.0
    facts, stats = _run(tmp_path, [ROOM], [el])
    assert facts["elements"][0]["properties"]["room_long_side"] == 9999.0
    assert "room_short_side" not in facts["elements"][0]["properties"]
    assert facts["elements"][0]["provenance"]["method"] == "vision"
    assert stats["kept_existing"] == 1


def test_uses_text_label_bbox_property_when_present(tmp_path):
    el = _el("c1", (0, 0, 10, 10))   # vision bbox elsewhere
    el["properties"]["text_label_bbox"] = "150,130,190,140"
    facts, _ = _run(tmp_path, [ROOM], [el])
    assert facts["elements"][0]["properties"]["room_long_side"] == pytest.approx(4000, rel=0.01)


def test_other_types_ignored(tmp_path):
    facts, stats = _run(tmp_path, [ROOM], [_el("d1", LABEL, type_="door")])
    assert "room_long_side" not in facts["elements"][0]["properties"]


def test_cli_refuses_without_scale(tmp_path):
    pdf = _pdf(tmp_path, [ROOM], text="")
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"elements": [_el("c1", LABEL)]}))
    out = tmp_path / "o.json"
    assert vm.main([str(f), str(pdf), "-o", str(out), "--rooms"]) == 2
    assert not out.exists()


def test_cli_rooms_writes_facts(tmp_path):
    pdf = _pdf(tmp_path, [ROOM])
    f = tmp_path / "f.json"
    f.write_text(json.dumps({"elements": [_el("c1", LABEL, area=12.0)]}))
    out = tmp_path / "o.json"
    assert vm.main([str(f), str(pdf), "-o", str(out), "--rooms"]) == 0
    got = json.loads(out.read_text())
    assert got["elements"][0]["properties"]["room_long_side"] == pytest.approx(4000, rel=0.01)
