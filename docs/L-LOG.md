# L's work log (rules, checking, AI)

Hand-off record for a new Claude session or for D. Task definitions are in `docs/tasks/L.md`; this file says
**what actually happened, what state things are in, and why**. Keep it current: add a dated entry whenever
something material changes. Last updated: 2026-11-07.

## Status by task
| Task | State | Notes |
|---|---|---|
| L1 rule loader | merged (#22) | `app/ingest/rules_loader.py`; first-level folder name = regime |
| L2 chunk + embed index | merged (#23) | `app/ingest/index.py`; needs the `rag` extra. `sentence-transformers` is **not installed** here, so real `bge-m3` retrieval has never been run (tests use a fake embedder) |
| L3 rule compiler | merged (#22, #34) | per-chunk cache + `--parallel` / `--fresh` flags (#34). Only 1 real chunk has ever been compiled (see "Gemini history") |
| L4 review endpoints | merged (#24) | `POST /ingest/rules`, `GET /rules`, `PATCH /rules/{id}` |
| L5 LLM judge | merged (#25) | `app/check/llm_judge.py`; no elements -> no LLM call; unverifiable verdict -> `needs_review` |
| L6 local GPU | optional / unavailable | D's #31: Meyer's GPU machine is unavailable. Mention in slides instead |
| L7 `/ask` | **done, PR #40 open (not merged)** | branch `l/ask-chat`; `app/check/ask.py`, route in `app/api/main.py`; tests with fake embedder + fake LLM |
| L8 Docker + `docs/DEPLOY.md` | **not started, on purpose** | deliberately waits until L and D are connected so it can be done once, on one computer |

## Open PRs (pushed 2026-11-07, **not merged yet**: none of this is on `main` until they are)
Stack: `main` <- #39 `l/poc-mocks` <- #40 `l/ask-chat` <- #41 `l/offline-check`; #38 `l/max-persons` is separate, off `main`.
Merge in this order: #38, #39, then retarget #40 to `main` and merge, then #41. After each squash-merge, retarget the next PR
to `main` and merge `main` into its branch (no force-push), as done for #22-#25.
| PR | Branch | Content |
|---|---|---|
| #38 | `l/max-persons` | **`app/models.py` change** (`Applicability.max_persons_on_board`, optional, inclusive) + `applicability.py` + tests. Own PR by the contract rule; **tell D** |
| #39 | `l/poc-mocks` | `mocks/rules_nps_poc.json`, `mocks/facts_nps_poc.json`, `tests/test_poc_pipeline.py`; compiler prompt now says `target` must be a physical element; warning when `target == space_type` |
| #40 | `l/ask-chat` | L7 |
| #41 | `l/offline-check` | `python -m app.check.run` CLI, `mocks/*_synthetic.json`, clearer evaluator messages, this log, and a copy of the `max-persons` commit (identical to #38, merges cleanly in either order) |

## Gemini / API history and decision
- Provider: `LLM_PROVIDER=gemini`, model `gemini-3.8-flash` (the old `gemini-flash-latest` alias returns 404).
  The model name is set in the git-ignored `.env`, whose line is `GEMINI_MODEL=gemini-3.8-flash`.
- Confirmed real responses: a one-word test call, and **page 1** of `NPS-Accessible-Vessels/ACC-Vessel-Standards.pdf`
  -> 19 rules. Page 2 never completed (repeated `503 high demand`, runs were stopped).
- Free tier is about 20 requests/day per model. The limit was hit. **The API key was removed from `.env` on purpose and the
  decision is: make no more API calls.** Work from the 19 real rules as proof of concept plus invented test data.
- Without a key, `get_llm()` still returns a provider; the judge and `/ask` catch the failure and return `needs_review` /
  `llm_unavailable`, they do not crash.

## Local data (all git-ignored; recreate or copy if working on another computer)
- `knowledge/rules/<REGIME>/`: `NPS-Accessible-Vessels` (2-page NPS checklist), `ADA-UNOLS` (37 pp research-vessel
  guide), `BWM` (ballast water convention), `COLREG`. Never committed (`.gitignore`, #35). 138 one-page chunks in total.
- `knowledge/compiled/rules.json`: the 19 real rules (page 1 only). `rules.cache.json`: the same, keyed by prompt+chunk hash.
  Note: the compiler prompt was edited after this was cached, so the cache will **not** be reused; a recompile would call the API again.
- **Committed copies you can rely on:** `mocks/rules_nps_poc.json` (the 19 real rules, see correction below) and `mocks/rules_synthetic.json`.

## Quality findings about the real Gemini output (proof-of-concept lessons)
1. **Target/space mix-up.** For 7 of 19 rules the model put a *place* (accessible_route, deck, entry_deck, walking_surface) in
   `target`. Design facts use `type` = physical element (door, corridor) and `space_type` = where it sits, so such rules never
   match. `mocks/rules_nps_poc.json` has these 7 **hand-corrected by me (not human-reviewed; `reviewed=false`)**.
   `knowledge/compiled/rules.json` still has the uncorrected originals. The evaluator now says so in the finding message.
2. **Count tiers are fine.** The eight "accessible accommodations for N passengers" rules only carry a minimum persons bound,
   but the strictest applicable tier dominates, so results are correct (just several findings for one requirement). New
   `max_persons_on_board` exists for true ranges but these rules do not use it.
3. No rule has a `clause`: the checklist prints none. Quotes for the tier rows are table cells ("26-50 2").
4. `crew` training rule is not checkable from a drawing -> always `needs_review`.
5. `slope` rule is in `%`; unknown units are compared as written, so design facts must use percent too.
6. Property names must match between sides: D's extractor uses `clear_width`, `width`, `height`, `area`...; rules use the same vocabulary.

## How to run things (all offline, no API)
```bash
.venv/Scripts/python.exe -m pytest -q                                   # 181 passed, 1 skipped at last run
.venv/Scripts/python.exe -m app.check.run mocks/facts_nps_poc.json --rules mocks/rules_nps_poc.json
.venv/Scripts/python.exe -m app.check.run mocks/facts_synthetic.json --rules mocks/rules_synthetic.json --status fail,needs_review
.venv/Scripts/python.exe -m app.check.run FACTS.json                    # uses knowledge/compiled/rules.json
```
Add `--llm` to let the judge use the configured provider (needs a key). Exit code is 1 if any finding failed.
(Windows: use `.venv/Scripts/python.exe`; CLAUDE.md shows the Linux path `.venv/bin/`.)

## Open work, in priority order
1. **Checkpoint with D**: real `facts.json` (D's GA extractor output) x reviewed rules through `/check`. Not started by choice.
2. Review/correct the real rules via `PATCH /rules/{id}` (fix targets; only a human sets `reviewed=true`).
3. Compile the remaining pages / the 37-page UNOLS guide **only if a key and quota exist again** (about 40 calls; cache protects partial runs).
4. Build the real index (`pip install -e ".[rag]"`, downloads ~2 GB `bge-m3`) and try `/ask` retrieval on the real PDFs.
5. L8 Docker + `docs/DEPLOY.md` once connected with D.
6. Merge PRs #38-#41 (order above) and tell D about the `models.py` field.

## Rules of the road (from CLAUDE.md, learned the hard way here)
- Never push to `main`; one short branch per task; squash-merge PRs; contract (`app/models.py`) changes in their own PR.
- Nothing hardcoded: regimes come from folder names, rule values from files. Test data lives in `mocks/`.
- Do not claim a rule is human-reviewed unless the user reviewed it.
- Do not run the compiler or `--llm` without checking quota first.
