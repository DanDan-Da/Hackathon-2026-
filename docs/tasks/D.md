# D: Design interpretation, UI and evaluation

**You own:** `app/design/`, `web/`, `eval/`, the `/ingest/design` and `/findings` routes in `app/api/main.py`, plus the demo video and slides.
**Read-only for you:** `app/ingest/`, `app/check/` and `app/providers/`, which belong to L. Change `app/models.py` only by agreement with L.
**Work against:** `mocks/rules.json` and `POST /check`, which already run with the mock rules.
**You deliver to L:** `DesignFacts` JSON for each project in `designs/<project>/facts.json`. Every element needs a `Provenance` (file, page, bbox, method, confidence).

Tasks are in priority order. Each one has a GitHub issue labelled `D`.

## D1 PDF text extractor (≈1h)
`app/design/pdf_text.py` uses PyMuPDF to pull words with bboxes for each page.
- Parse ship particulars (LOA, LPP, breadth, GT, persons on board, ship type) from title blocks or specs into `ShipParticulars`, with provenance.
- Parse dimension strings like `800`, `0.8 m` or `2'-8"` into mm.
- **Done:** tests on a small generated PDF (create it in the test with PyMuPDF; don't commit the sample PDFs).

## D2 GA drawing vision extractor (≈2.5h, core)
`app/design/drawing_vision.py` renders each page at about 200 DPI and tiles it with overlap, so the text stays readable.
- For each tile, call `get_llm().complete_structured(prompt, schema=TileExtraction, images_png=[tile])`. `TileExtraction` is `{elements: list[...]}` with type, name, space_type, properties and a bbox in tile pixels.
- Map tile pixels back to PDF points, then merge duplicates that appear in overlapping tiles.
- `confidence` comes from the model, and the cross-check in D3 caps it.
- Start with one real GA from `Files/`, such as the GO SARS GA.
- **Done:** `python -m app.design.drawing_vision designs/demo/ga.pdf` writes `facts.json`. Tests use a fake provider.

## D3 Cross-check against the PDF text layer (≈0.5h)
- If a vision-extracted label or dimension also appears in the PDF text layer near the same bbox, raise confidence and use the exact value.
- If it doesn't, cap confidence at 0.6. Below 0.6 the evaluator returns `needs_review`.

## D4 3D: try converting the NWD (≤1h, then stop)
See `docs/3D-MODELS.md`. Try a Navisworks Manage or Simulate export to IFC/FBX.
- **If it fails within 1h, generate a synthetic IFC** with `ifcopenshell` instead: one deck with a corridor, cabins, doors and two stairs, including planted violations.

## D5 IFC reader (≈1h, `3d` extra)
`app/design/ifc_reader.py` maps IfcDoor (OverallWidth, or clear width from a property set), IfcSpace, IfcStair, IfcStairFlight and IfcSlab/IfcBuildingStorey (deck) to `DesignElement`s.
- Set `provenance.method="ifc"` and `element_id` to the GlobalId, and convert to mm.
- **Done:** test on the synthetic IFC from D4.

## D6 Findings UI (≈2h)
`web/` is a single page served by FastAPI (static files).
- Upload a design, then run the check.
- Show a findings table that can be filtered by status (fail / needs_review / pass) and regime.
- Clicking a finding shows the drawing page with the bbox highlighted next to the verbatim rule quote and clause.
- Keep it simple and clear. Usability is a plus, but accuracy matters more.

## D7 Gold set + metrics (≈1.5h, essential for judging)
- `eval/gold_cases.yaml` lists variants of `DesignFacts`, or of GA PDFs, that contain planted violations, each with its expected finding (rule_id, element_id, status).
- `eval/run_eval.py` runs the pipeline and prints precision and recall, plus the needs_review rate, for each provider (`LLM_PROVIDER=claude` and `local`).
- **Done:** one command prints a table that goes into the slides.

## D8 Demo video + slides (last 2h)
- A 2–3 minute video: drop the rule files in, let it learn the rules, upload a GA, show the findings, click one to see the cited clause and the highlighted drawing, then show the eval numbers.
- Slides: problem, approach (deterministic + LLM, citations, no guessing), accuracy numbers, local/on-prem mode, roadmap.

## Checkpoints with L
- **About 5h:** your real `facts.json` from one GA against L's real `rules.json`.
- **About 8h:** full pipeline plus eval numbers.
