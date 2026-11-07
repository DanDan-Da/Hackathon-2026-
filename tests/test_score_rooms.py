from app.models import DesignElement, DesignFacts, Provenance
from eval.score_rooms import score_rooms


def gold_room(i, name, area, bbox, deck="main"):
    return {"id": i, "deck": deck, "room_name_printed": name, "area_m2": area,
            "page": 1, "label_bbox_pdf_points": bbox}


GOLD = {"rooms": [
    gold_room("g1", "1 PERS. (CAPTAIN)", 25, [100, 100, 140, 120]),
    gold_room("g2", "MESS", 83, [500, 500, 540, 520], deck="upper"),
]}


def el(eid, name, bbox, area=None, page=1, **props):
    p = dict(props)
    if area is not None:
        p["area"] = area
    return DesignElement(id=eid, type="space", name=name, properties=p,
                         provenance=Provenance(file="x.pdf", page=page, bbox=bbox, method="vision"))


def facts(*els):
    return DesignFacts(project="t", elements=list(els))


def by_id(res):
    return {r.gold_id: r for r in res.rooms}


def test_exact_match_and_summary():
    f = facts(el("e1", "1 PERS. (CAPTAIN)", (90, 90, 150, 130), 25.0),
              el("e2", "MESS", (480, 480, 560, 540), 83.2))
    res = score_rooms(f, GOLD)
    assert res.matched == 2 and res.total == 2
    assert res.recall == 1.0 and res.area_accuracy == 1.0
    assert by_id(res)["g1"].element_id == "e1"
    assert by_id(res)["g1"].area_result == "correct"


def test_name_matches_but_wrong_location_not_matched():
    f = facts(el("e1", "1 PERS. (CAPTAIN)", (1000, 1000, 1100, 1100), 25.0))
    res = score_rooms(f, GOLD)
    assert by_id(res)["g1"].element_id is None
    assert by_id(res)["g1"].area_result == "n/a"
    assert res.matched == 0 and res.recall == 0.0
    assert res.area_accuracy is None


def test_repeated_name_on_other_deck_picks_right_one():
    f = facts(el("far", "MESS", (10, 10, 60, 60), 83.0),
              el("near", "MESS", (490, 490, 550, 530), 83.0))
    assert by_id(score_rooms(f, GOLD))["g2"].element_id == "near"


def test_missing_area():
    f = facts(el("e1", "1 PERS. (CAPTAIN)", (90, 90, 150, 130)))
    res = score_rooms(f, GOLD)
    r = by_id(res)["g1"]
    assert r.element_id == "e1" and r.area_result == "missing"
    assert res.area_missing == 1 and res.area_correct == 0 and res.area_accuracy == 0.0


def test_wrong_area_and_tolerance():
    f = facts(el("e1", "1 PERS. (CAPTAIN)", (90, 90, 150, 130), 26.0),
              el("e2", "MESS", (480, 480, 560, 540), 83.5))
    res = score_rooms(f, GOLD)
    assert by_id(res)["g1"].area_result == "wrong"
    assert by_id(res)["g2"].area_result == "correct"  # exactly 0.5 off
    assert res.area_wrong == 1


def test_duplicate_detections_count_once():
    f = facts(el("a", "MESS", (480, 480, 560, 540)),
              el("b", "MESS", (485, 485, 555, 535), 83.0))
    res = score_rooms(f, GOLD)
    r = by_id(res)["g2"]
    assert res.matched == 1
    assert r.element_id == "b"  # the one with area wins
    assert r.duplicate_ids == ["a"]


def test_name_with_embedded_area_text():
    f = facts(el("e1", "MESS 83 m²", (480, 480, 560, 540), 83.0),
              el("e2", "1 pers. (captain)  25 m2", (90, 90, 150, 130), 25.0))
    res = score_rooms(f, GOLD)
    assert res.matched == 2


def test_other_page_not_matched():
    f = facts(el("e1", "MESS", (480, 480, 560, 540), 83.0, page=2))
    assert by_id(score_rooms(f, GOLD))["g2"].element_id is None


def test_wrong_name_at_right_location_not_matched():
    f = facts(el("e1", "GALLEY", (480, 480, 560, 540), 83.0))
    assert by_id(score_rooms(f, GOLD))["g2"].element_id is None


def test_no_precision_reported():
    res = score_rooms(facts(el("x", "OTHER", (0, 0, 5, 5))), GOLD)
    assert not hasattr(res, "precision")
