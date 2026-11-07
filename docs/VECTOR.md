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
