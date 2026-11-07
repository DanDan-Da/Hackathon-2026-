# Vector measurement of door widths (spike, issue #18)

Code: `app/design/vector_measure.py`, tests: `tests/test_vector_measure.py` (synthetic PDFs with a known width).
CLI: `python -m app.design.vector_measure FACTS PDF -o OUT [--add-new]`.

## What the real GA looks like (`designs/demo/ga.pdf`, git-ignored)
- 1 page, 2384 x 3370 pt (A0 at 72 dpi), 304,865 vector paths, no layers. Lines are 0.15 pt black (about 200k), grey 0.36 pt (hatching/furniture), heavier black (0.36 to 0.99 pt) for walls.
- Scale is printed in the title block: `Scale (U.N.O.): 1:150` (found in the text layer). One PDF point = 25.4/72 x 150 = 52.92 mm real.
- Plan-view hinged doors are a quarter-circle swing arc (a polyline of about 25 short `l` segments, sometimes closed by a chord) plus a thin leaf line or rectangle from the hinge to the arc end. The radius equals the leaf length.
- The 4 `door` elements from the vision step (`door-p1-001/005/118/122`) are elevation views (watertight/flush hatches on the profile). They contain no swing arcs, so none can be matched.

## Scale cross-checks (independent of door detection)
- Frame labels 0 to 110 on the shelter deck (frame spacing 600 mm per the particulars): 1247.3 pt for 66,000 mm = 52.91 mm/pt vs 52.92 expected (0.0 % error).
- Hull x-extent of the main deck plan: 1318.6 pt = 69.78 m vs length overall 69.80 m (-0.03 %).

## Door detection on the real drawing
- 143 swing arcs found in 3.2 s (arc fit rms <= 2 % of radius, span 65 to 115 deg, 500 to 1500 mm, leaf line required at the hinge).
- Width histogram (50 mm bins): 500: 5, 550: 2, 600: 1, 650: 18, 750: 74 (mostly 730 to 735), 850: 41 (mostly 830), 950: 1, 1150: 1. These cluster on a few standard leaf sizes (about 730 and 830 mm), which is plausible.
- Visual check: a random 12 doors rendered at 7x (scratchpad only, not committed) were all real door swings (cabin, WC, store, stair-landing and wall-mounted doors). 0 false positives in the sample.
- Internal consistency: the separately drawn leaf/hardware strip next to each hinge was measured independently of the arc fit. Leaf length / arc radius has median 1.002; 129 of 143 (90 %) are within 10 %, 127 (89 %) within 5 %. The rest are contaminated by adjacent wall lines in my crude measurement, not checked one by one.

## What the number means, and its limits (read before trusting it)
- The value is the hinge-to-latch leaf length (swing radius), i.e. the nominal leaf width. It is not the net clear opening, which is smaller by the frame and leaf thickness (typically 50 to 100 mm). A rule on clear width could therefore pass wrongly. For that reason confidence is capped at 0.5 (below the trust threshold), so the evaluator should return needs_review rather than pass/fail from this value alone.
- There is no printed door width in the drawing text, so there is no ground truth. Accuracy is established by (a) the scale cross-checks above (0.0 % and -0.03 %), (b) 12/12 visually confirmed doors, (c) arc/leaf agreement. Measured geometry error is therefore well under 10 %; the error of "leaf length vs true clear width" is unknown and probably 5 to 15 %.
- Only plan-view swing doors are found. Sliding doors, double doors drawn with two arcs (counted as two doors) and elevation hatches are not handled. Passage/corridor widths were not attempted.
- Arcs that merely resemble a door (e.g. a curved stair) are filtered by the leaf-line requirement, but this is a heuristic.

## Wiring decision
- The 4 existing door elements have no matching swing, so the default run changes nothing. With `--add-new` the 143 swings are appended as new `door` elements (`door-vec-NNN`, `method='vector'`, confidence 0.5, bbox). Existing `clear_width` values are never overwritten, ambiguous matches are skipped. `--add-new` is off by default: they have no deck or room link yet (matching to cabins by bbox is a follow-up).

# Room long/short side from wall rectangles (issue #18)

Code: `app/design/vector_rooms.py`, config (all tolerances): `app/design/vector_rooms.json`, tests: `tests/test_vector_rooms.py`.
CLI: `python -m app.design.vector_measure FACTS PDF -o OUT --rooms` (same scale detection, refuses without a stated scale).

## What it does
- For every `cabin`/`toilet` element (types from the config) the label position is taken (`properties.text_label_bbox` if present, else the provenance bbox). Axis-aligned dark lines are collected from the vector paths, collinear pieces are merged over door gaps (1.2 m), lines shorter than 1.5 m are dropped (furniture). The smallest closed rectangle around the label is measured.
- Output properties (mm): `room_long_side`, `room_short_side`. The drawing does not say which is "width" and which "depth", so none is invented. Also `room_area_vector_m2`, `room_area_check` (`confirmed` | `agree_unconfirmed` | `disagree` | `no_printed_area`), `room_area_error` (fraction vs the printed area) and `prev_provenance`.
- Provenance becomes `method='vector'`, bbox = the rectangle, confidence 0.5 (`vector_measure.CONF_VECTOR`). Existing `room_*` values are never overwritten.
- Independent check with the printed area (the vision extraction reads it from the label): within +-10 % (`area_tolerance`) AND at least 80 % of the element's own bbox inside the rectangle AND no other room's label inside (a toilet label inside a cabin is allowed) raises confidence to `crosscheck.CONFIRMED_CONF` (0.9). Area agreement alone is not enough because it does not pin the short side. Disagreement stays at 0.5 and is flagged. Agreement without the outline match stays at 0.5 (`agree_unconfirmed`).
- Skipped (counted, nothing written): no closed rectangle, concentric nesting (an enclosing closed rectangle clear of the inner one by >= 400 mm on all four sides), or a rectangle that contains another room's label (it spans several rooms).

## Walls in this drawing
Room walls are NOT heavier lines: cabin walls, partitions and furniture are all 0.15 pt black. Only the hull line and some WC boxes are 0.72 pt. So a weight filter does not work; length (>= 1.5 m after merging) and closure are what separate walls from furniture. Walls are drawn as double lines about 100 to 200 mm apart, hence the 400 mm nest gap.

## Measured on designs/demo/ga.pdf (1:150), 65 cabin/toilet elements
- Rectangle written: 35. Skipped: 3 no closed rectangle, 8 ambiguous nesting, 19 rectangle spans another room's label (22 of the 36 toilets, 8 of 29 cabins; the WC boxes are chamfered, not rectangles, so most fall through to the enclosing cabin and are rightly rejected).
- 29 rooms (all cabins) have a printed area: rectangle written for 21; 16 of those 21 within 10 % (13 confirmed at 0.9, 3 agree-but-unconfirmed), 5 disagree (flagged at 0.5). Area error on the 21: median -1.4 %, median absolute 5.1 %, range -63 % to +6 %. The 8 without a rectangle are skipped, not guessed.
- Caution: the printed areas are nominal (12, 15, 20, 25 m2), so the 10 % check is a coarse independent check, not a precise one.
- 14 toilets got a rectangle; they have no printed area, so they stay at 0.5 (needs_review). Not verified one by one beyond a few crops.

## What the crops showed (scratchpad only, not committed)
- Correct: cabin-p1-027 (15 m2, rectangle on the cabin walls incl. the WC corner, +1.5 %), cabin-p1-089 and neighbours (2-person cabins, within 1.5 %), toilet-p1-035 (rectangle around the WC box).
- Wrong and flagged: cabin-p1-029, -034, -064, -076 (printed 20/12/12/15, rectangle 12.0/6.3/8.7/5.5 m2). The smallest closed rectangle was bounded by a furniture outline (a bed or desk) instead of the real bulkhead, or the cabin is not rectangular. These are exactly the cases the printed area catches; they stay at 0.5.
- Correctly skipped: cabin-p1-025 (machine chief, angled hull side, not a rectangle).
- Known weakness: a room without a printed area (all toilets) can get a furniture-bounded rectangle that nothing detects. That is why unconfirmed results are capped at 0.5 and give needs_review.

## Side effect to know about
Writing the measurement replaces the element's provenance (vision, confidence 1.0) with the vector one (0.5, or 0.9 when confirmed). A rule on the printed `area` of an unconfirmed or disagreeing cabin therefore becomes needs_review instead of using the label value at 1.0. This is conservative; the old method/confidence/bbox are kept in `prev_provenance`. Not wired into any default pipeline: run `--rooms` explicitly.
