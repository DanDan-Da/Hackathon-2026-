# Demo script (3-4 minutes)

Written for issue #16 (D8). Every step below was checked against the code on `main` at the time of writing
(file named next to each claim). Steps that depend on work **not merged yet** are tagged
**[NOT MERGED]** and each has a **Fallback** line. Say the fallback out loud rather than faking the real thing.

## Before you go on stage (do this once, offline, ~10 min)
Nothing here calls an LLM except step 0b. The free Gemini tier allows about 20 requests/day per model
(README "AI providers"), so **prepare the GA extraction ahead of time and never run it live**.

| # | Prep | Command / file | Why |
|---|---|---|---|
| 0a | Install and start the app | `uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev,rag,3d]"` then `.venv/bin/uvicorn app.api.main:app` | UI is static files served at `/` (`app/api/main.py`, `web/`) |
| 0b | Pre-extract one public GA (needs a key, uses quota) | copy a public GA to `designs/demo/ga.pdf`, then `.venv/bin/python -m app.design.drawing_vision designs/demo/ga.pdf` | Writes `designs/demo/facts.json`. Tiles are cached in `designs/demo/.cache`, so an interrupted run resumes (`drawing_vision.py`, `--cache`) |
| 0c | Rules in place | `cp mocks/rules_nps_poc.json knowledge/compiled/rules.json` | 19 real Gemini-compiled rules, 7 targets hand-corrected, **not human-reviewed** (`docs/L-LOG.md`). Say so on stage |
| 0d | Confirm offline fallbacks work | `.venv/bin/python -m eval.score_findings` and `.venv/bin/python -m app.check.run mocks/facts_nps_poc.json --rules mocks/rules_nps_poc.json` | No key needed |
| 0e | Only public drawings | | Free-tier Google may train on prompts (README). Never upload confidential Meyer drawings in the demo |

## Run of show

### 1. The promise (0:00-0:20)
Open `http://localhost:8000`. Point at the tagline: "Every finding cites the rule and the spot in the design. When
evidence is missing it says so instead of guessing." (`web/index.html`). The header chip shows the server is up (`/health`).

### 2. Rules are files (0:20-0:50)
Say: no regulation value lives in code. Show the folder `knowledge/rules/<REGIME>/` (regime = folder name,
`app/ingest/rules_loader.py`). Drop a regulation PDF into it.
- Real path: `POST /ingest/rules` (or `python -m app.ingest.rule_compiler --regime NAME`) compiles it. **Do not run this live**: it calls the LLM and takes minutes.
- Show instead `GET /rules` (or the `mocks/rules_nps_poc.json` file): each rule has a quote, document and page.
- Say: the compiler drops any rule whose quote is not a verbatim substring of the source chunk
  (`rule_compiler.py`, log line "DROPPED (quote not in source)"). Rules carry `reviewed=false` until a person sets it via `PATCH /rules/{id}`.
- **[NOT MERGED] real compiled rules.** Today only page 1 of the NPS checklist (19 rules) was ever compiled for real (`docs/L-LOG.md`); the rest of the library is not compiled because of quota. **Fallback:** "this is a proof-of-concept rule set; the compiler is proven on one real page and by `tests/test_rule_compiler.py`, scaling it is a quota question, not a design question."

### 3. Read a GA drawing (0:50-1:30)
In the UI, "Open facts.json" and pick `designs/demo/facts.json` (from prep 0b).
Say what the reader did (`drawing_vision.py`, `crosscheck.py`):
- rendered each page at 200 dpi, cut it into overlapping tiles, asked the vision model for what it **sees**; tile answers are cached on disk;
- numbers are converted by our own parser, never by the model; an unparseable value is dropped;
- then cross-checked against the PDF's own text layer: a label or dimension found in the text layer is **confirmed** (confidence raised to 0.9); one not found is **capped at 0.59**, just below the 0.6 threshold, so the checker answers `needs_review` (`crosscheck.py` `CONFIRMED_CONF`, `UNCONFIRMED_CAP`; `evaluator.py` `LOW_CONFIDENCE = 0.6`).
- **Fallback if there is no real facts.json:** click **Load demo** (mock facts + mock rules, `GET /ui/demo`). Caveat to state: the mock facts point at a non-existent `ga.pdf`, so **no drawing crop will show** in that mode. Use `mocks/facts_nps_poc.json` for the same reason: it has no drawing either.

### 4. The user states the ship type (1:30-1:50)
Leave "Ship type" blank and click **Run check**: ship-type-dependent rules come back `needs_review` (the drawing does not say it and we never infer it, `app/check/applicability.py`). Type `passenger` into "Ship type" and run again. Say: it is recorded in the facts as a `manual` provenance, "entered in the UI", confidence 1.0 (`app/api/ui.py` `apply_ship_type`). Whether rules flip depends on the applicability fields of the loaded rules: check this rehearsal-side, do not promise a specific flip.

### 5. Findings and evidence (1:50-2:40)
- Use the status chips (fail / needs review / pass) and the Regime filter (`web/app.js`).
- Click a **fail** finding. Show: the verbatim rule quote with document/page/clause, the design value, and the **drawing crop with the evidence box outlined in red** (`/evidence/crop`, `app/api/evidence.py`; two crops load automatically, others on "Show drawing crop").
- Click a **needs review** finding. Say: "the evidence is missing or too uncertain, so a person has to check this", shown in the red-bordered note (`web/app.js`). This is the product's honesty feature.
- Needs `designs/demo/ga.pdf` to exist locally so the crop can render. **Fallback:** show the quote and the evidence coordinates in text and say the crop needs the PDF on disk.
- **[NOT MERGED] trust scoreboard (PR `d/ui-trust`).** If merged, show the summary of how many findings are pass / fail / unsure at the top. **Fallback:** point at the existing counts bar and colored summary (`#counts`, `#bar` in `web/index.html`).

### 6. Proof it catches planted violations (2:40-3:10)
In a terminal: `.venv/bin/python -m eval.score_findings`. Expected output ends with
`Planted cases correct: 15/15`, `MISSED VIOLATIONS: 0 (must be 0)`, `False alarms: 0` (run and confirmed while writing this doc; 12 cases in `eval/gold/findings/cases.json`).
State the caveat immediately: the cases test the **checking logic** on mock facts and mock rules (limit edge cases like 812.8 vs 812.7 mm, blurry reads becoming `needs_review`, missing elements). They do not test the AI reading the drawing.
Then: `.venv/bin/python -m eval.score_rooms designs/demo/facts.json` scores room reading against the 20-room hand-checked Dana gold set (`eval/gold/dana/`). It only works if the demo drawing is the Dana GA; otherwise skip it and quote the slide figure with its caveat (see `docs/SLIDES.md`).

### 7. Ask the regulations (3:10-3:35)
`POST /ask` with `{"question": "...", "regime": "..."}` (Swagger at `/docs`). Say: the model may use only the retrieved passages; every citation is verified as a verbatim quote from a retrieved passage, and an answer with no verified citation is withheld and the raw passages returned instead (`app/check/ask.py`).
- Needs the `rag` extra and a built index; `sentence-transformers` was **not installed** on L's machine, so real `bge-m3` retrieval has never run (`docs/L-LOG.md`). **Fallback:** skip live, show `tests/test_ask.py` passing and say retrieval is tested with a fake embedder only. There is no /ask panel in the UI.

### 8. 3D (3:35-3:50)
`.venv/bin/python scripts/generate_synthetic_ifc.py /tmp/x.ifc && .venv/bin/python -m app.design.ifc_reader /tmp/x.ifc --project synthetic` prints facts with the IFC GlobalId as the element id and `method="ifc"` (`docs/IFC.md`). Say: this is a **synthetic** model with semantics only; the real 305 MB Navisworks `.nwd` cannot be read by any open-source tool and was not converted (`docs/3D-MODELS.md`). Overall door width is never treated as clear width.
- **[NOT MERGED] 3D mesh bbox cross-check (PR `d/mesh-bbox`).** **Fallback:** say "geometry-derived clearances are the next step; today the IFC reader trusts explicit properties only" (`docs/IFC.md`).

### 9. Close (3:50-4:00)
"Rules are files. The AI learns them. Python decides. Anything uncertain goes to a person."

## If something breaks
- Server will not start: run the offline CLI instead, `python -m app.check.run mocks/facts_synthetic.json --rules mocks/rules_synthetic.json --status fail,needs_review`.
- LLM quota or 503: nothing in the live path needs the LLM except `/ask` and `--llm`; the judge returns `needs_review` when the LLM is unavailable (`docs/L-LOG.md`).
- Crop shows nothing: the provenance file must be inside `designs/`; check the path in the finding.

## Honest limits to say aloud
Rules were compiled for one real page; the compiled rules are not human-reviewed; GA reading used free-tier Gemini/Gemma; no GPU, so no on-prem model; 3D is synthetic IFC only.
