# Demo script (3-4 minutes)

Every step below was run against the code on `main` on 2026-11-07 (file named next to each claim).
Where something can fail there is a **Fallback** line: say the fallback out loud rather than faking the real thing.

## Before you go on stage (once, ~10 min)
The free Gemini tier allows about 20 requests/day per model (README "AI providers"). Nothing in the live demo
calls the LLM except the Ask panel, so **prepare extraction ahead of time and never run it live**.

| # | Prep | Command / file | Why |
|---|---|---|---|
| 0a | Install and start the app | `uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev,rag,3d]"`, then `.venv/bin/uvicorn app.api.main:app` | UI is static files served at `/` (`app/api/main.py`, `web/`) |
| 0b | Public GA, already extracted | `designs/demo/ga.pdf` (the public Dana GA, see `docs/DATA.md`) and `designs/demo/demo_real_drawing.json` (in git; the PDF is not, add it locally for the crops). To redo: `.venv/bin/python -m app.design.drawing_vision designs/demo/ga.pdf --out designs/demo/demo_real_drawing.json` (needs a key; tiles cached in `designs/demo/.cache`) | Never run extraction live |
| 0c | Planted copy (in git) | `designs/demo/demo_planted_fail.json` = `demo_real_drawing.json` + one element named "PLANTED TEST: edge protection 150 mm high (not from the drawing)", `method=manual`, placed on a real bbox of the drawing | Exactly one change from the real result: 1 `fail` with a real drawing crop, no extra pass. **Always say it is planted** |
| 0d | Rules in place | `cp mocks/rules_nps_poc.json knowledge/compiled/rules.json` | 19 Gemini-compiled NPS rules, 7 targets hand-corrected, **not human-reviewed**. Say so on stage |
| 0e | Index for the Ask panel | put the regulation files in `knowledge/rules/<REGIME>/`, then `.venv/bin/python -m app.ingest.index` | Downloads `bge-m3` (~2 GB) the first time |
| 0f | Offline fallbacks work | `.venv/bin/python -m eval.score_findings` and `.venv/bin/python -m app.check.run mocks/facts_nps_poc.json --rules mocks/rules_nps_poc.json` | No key needed |
| 0g | Only public drawings | | Free-tier Google may train on prompts (README). Never upload confidential drawings |

## Run of show

### 1. The promise (0:00-0:20)
Open `http://localhost:8000`. Point at the tagline: "Every finding cites the rule and the spot in the design. When
evidence is missing it says so instead of guessing." The header chip shows the server is up (`/health`).

### 2. Rules are files (0:20-0:50)
Say: no regulation value lives in code. Regulations sit in `knowledge/rules/<REGIME>/` (regime = folder name,
`app/ingest/rules_loader.py`). Open the **Rules** tab: each rule shows its verbatim quote, document and page, and the
badge "Not reviewed (AI-compiled)".
- Say: the compiler drops any rule whose quote is not a verbatim substring of the source chunk (`rule_compiler.py`).
  Only a person marks a rule reviewed. **Do not click "mark reviewed" on stage**: it writes to the rules file.
- **Do not compile live** ("Compile rules with AI" in "Add a regulation"): it uses the quota and takes minutes. With the
  regime field blank it asks before compiling everything.
- Scale today: 19 NPS rules and 170 UNOLS research-vessel rules compiled (`mocks/`), none human-reviewed.

### 3. Read a real GA drawing (0:50-1:30)
In the facts picker choose `demo/demo_real_drawing.json`, wait for "Loaded ... Press Run check", then **Run check**.
Real result with the NPS rules: **0 fail, 9 needs_review, 10 not_applicable**. Say: the real drawing has no provable
violation, and most rules need evidence a GA does not show, so they go to a person instead of being guessed.
What the reader did (`drawing_vision.py`, `crosscheck.py`):
- rendered each page at 200 dpi, cut it into overlapping tiles, asked the vision model what it **sees**; tiles are cached;
- numbers are converted by our own parser, never by the model; an unparseable value is dropped;
- cross-checked against the PDF text layer: a value found there is **confirmed** (confidence 0.9); one not found is
  **capped at 0.59**, below the 0.6 threshold, so the checker answers `needs_review`.

### 4. A violation, with its evidence (1:30-2:20)
Choose `demo/demo_planted_fail.json` and run. **Say first: "this one is planted, to show what a fail looks like."**
Click the **fail** (Edge protection maximum height). Show: why it failed (150 mm vs <= 4 in = 101.6 mm), "what would make
it pass", the verbatim rule quote with document and page, and the **drawing crop with the evidence box in red**
(`/evidence/crop`, `app/api/evidence.py`).
Then click a **needs review** finding: "the evidence is missing or too uncertain, so a person checks this".
- **Fallback** if the crop does not render: the coordinates are shown in text; the crop needs the PDF in `designs/`.

### 5. Ship type is stated, never guessed (2:20-2:40)
Type `passenger` into "Ship type" and run again: on the real file, not_applicable goes 10 -> 7 and needs_review 9 -> 12,
because passenger-tier rules now apply but the drawing does not prove them. Say: the ship type is recorded as `manual`
provenance, "entered in the UI" (`app/api/ui.py` `apply_ship_type`).

### 6. Proof it catches planted violations (2:40-3:10)
Point at the **Trust scoreboard**: 15/15 planted cases correct, 0 missed, 0 false alarms (`/ui/trust`).
Optionally run `.venv/bin/python -m eval.score_findings` in a terminal. On the real compiled rules: 88/90 (NPS) and
23/23 (UNOLS), 0 missed violations in all three (`docs/EVAL.md`). Caveat right away: we wrote the cases; they test the
**checking logic**, not the AI reading the drawing. For the reading: Dana rooms 19/19 printed areas correct on a
20-room hand-checked sample (`python -m eval.score_rooms designs/demo/demo_real_drawing.json`; no precision reported).
- **Load demo** (mock facts + mock rules) shows more fails, but its rule quotes say "[MOCK ...]" and it has no drawing,
  so no crop. If you use it, say "mock data". Picking a design file afterwards switches back to the server's rules.

### 7. Ask the regulations (3:10-3:35)
**Ask** tab. Question: "What is the minimum clear width of an accessible route?", regime `NPS-Accessible-Vessels`
(suggested in the field) or blank. Verified on 2026-11-07: answer "60” wide" with a verbatim citation from
ACC-Vessel-Standards.pdf p1. Say: the model may only use retrieved passages; every citation is checked to be
verbatim, and an answer with no verified citation is withheld (`app/check/ask.py`).
- One question = 1 Gemini request. Ask once, on stage. **Fallback** on quota/503: say so and show `tests/test_ask.py`.

### 8. 3D (3:35-3:50)
`.venv/bin/python scripts/generate_synthetic_ifc.py /tmp/x.ifc && .venv/bin/python -m app.design.ifc_reader /tmp/x.ifc --project synthetic`
prints facts with the IFC GlobalId as element id and `method="ifc"` (`docs/IFC.md`). Say: a **synthetic** model; the
real 305 MB Navisworks `.nwd` cannot be read by open-source tools (`docs/3D-MODELS.md`). The mesh reader cross-checks
the bounding box of a real IFC against the stated particulars (`docs/3D.md`); they do not agree (probable unit issue in
the export), and we report that instead of hiding it.

### 9. Close (3:50-4:00)
"Rules are files. The AI learns them. Python decides. Anything uncertain goes to a person."

## If something breaks
- Server will not start: `.venv/bin/python -m app.check.run mocks/facts_synthetic.json --rules mocks/rules_synthetic.json --status fail,needs_review`.
- LLM quota or 503: only the Ask panel needs the LLM live; the qualitative judge returns `needs_review` without it.
- Crop shows nothing: the provenance file must be inside `designs/`.

## Honest limits to say aloud
Compiled rules are not human-reviewed; no SOLAS/MARPOL/DNV text was available; the real drawing yields no fail (the
demo fail is planted); GA reading used free-tier Gemini/Gemma; no GPU, so no on-prem model; 3D is synthetic IFC only;
Docker (`docker compose up --build`) is tested without the `rag`/`3d` extras.
