# D's work log (design, UI, eval): hand-off notes for L

Last updated: 2026-11-07. Task definitions are in `docs/tasks/D.md`; L's own record is `docs/L-LOG.md`.

## Changes that touch L's files (please review)
| PR | File | What changed |
|---|---|---|
| #47 | `app/check/evaluator.py` | Count and presence rules no longer decide on low-confidence reads. The verdict is computed with all matched elements and with only the confident ones; if they differ the result is `needs_review`. A certain fail stays a fail. Tests: `tests/test_count_confidence.py`. |
| #47 | `mocks/rules_nps_poc.json` | The 8 passenger-tier rules now carry `max_persons_on_board` (taken from each rule's own `condition_text`); the "route to boarding area" rule targets `corridor` with `space_types: [accessible_route]`. Still `reviewed=false`. |
| #52 | `app/api/main.py` | One import and one `include_router` line for `app/api/regulations.py` (upload endpoint for the UI). |
| #48 | `app/models.py` | `Provenance.method` also accepts `"vector"` (values measured from PDF vector geometry). Additive. |

## Things for L to do
- `/ingest/rules` and `/ask` return a bare HTTP 500 when they fail (no key, quota, index missing). The UI copes, but a JSON `detail` would be better.
- #8 Docker + deployment: D wrote `docs/DEPLOY.md`, `Dockerfile`, `docker-compose.yml` (PR #51). **The Docker files are untested** (docker was not run). Please verify or replace them, then close #8.
- #7 `/ask` is merged but the issue is still open: close it.
- `/ask` retrieval has never run on the real PDFs (`sentence-transformers` / `bge-m3` not installed). Try `pip install -e ".[rag]"`.
- The compiler puts a place in `target` for some rules (see the SUSPICIOUS warnings). The rule compiler prompt could say it more strongly, or `rule_compiler` could refuse such rules.
- Review the corrected rules and set `reviewed=true` only after a human has read them.

## What D added (all on `main`)
- GA drawing reader with tile cache, duplicate fix, text-layer cross-check, room scorer (`eval/score_rooms.py`).
- `app/design/enrich.py`: ship type as printed on the drawing, `space_type` from room names (config file), cabin-count cross-check (`docs/DANA.md`).
- `app/design/vector_measure.py`: door leaf widths from vector geometry, confidence capped at 0.5 (`docs/VECTOR.md`).
- `app/design/mesh_reader.py`, `cross_check.py`: IFC bounding box vs stated particulars (`docs/3D.md`). The real IFC does not agree with the documents (probable unit issue in the export).
- UI: findings, evidence crops, ship type field, "what would make it pass", trust scoreboard, rules / ask / add-a-regulation panels.
- Evals: `eval/score_findings.py` with planted-violation cases against the mock rules (15/15) and the real NPS rules (88/90), 0 missed violations (`docs/EVAL.md`).

## Rules compiled by D with free Gemma (in progress)
`knowledge/compiled/rules_gemma.json` is being written by `python -m app.ingest.rule_compiler --regime ADA-UNOLS` using `gemma-4-31b-it`. It is slow (many HTTP 500s). The result will be reviewed and committed as `mocks/rules_unols_gemma.json`.
