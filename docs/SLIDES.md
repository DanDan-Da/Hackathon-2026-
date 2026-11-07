# Slides outline (8 slides) and judge Q&A

Rule for this file: **no number without a source**. Each figure says where it comes from and what it does NOT prove.

## Figures: what is verified and what is not
| Figure | Source | Status |
|---|---|---|
| Planted violations: 15/15 correct, 0 missed, 0 false alarms | `python -m eval.score_findings` on `eval/gold/findings/cases.json` (12 cases, 15 expectations), mock facts `mocks/facts_violation.json`, rules `mocks/rules.json` | **Re-run while writing this doc: confirmed.** Tests the checking logic, not the AI reading |
| Dana room recall 19/20 (sampled), printed area 19/19 | `python -m eval.score_rooms <facts.json>` against `eval/gold/dana/dana_rooms.json` (20 hand-checked rooms, 4 decks; `eval/gold/dana/README.md` defines the metrics) | **The scores come from a local run on a git-ignored GA; the facts are not in the repo.** To reproduce (needs the Dana PDF from `docs/DATA.md` in `designs/dana/` and an LLM key): `python -m app.design.drawing_vision designs/dana/23007-01-101-0110-01-R2-14-General-arrangement.pdf --out designs/dana/facts.json && python -m eval.score_rooms designs/dana/facts.json`. A new run may differ (model output varies); paste its output before presenting. See `docs/DEPLOY.md` |
| 345 tests | `pytest -q` | **`345 passed`** with the `dev,rag,3d` extras installed (2026-11-07). Re-run before presenting if anything merges after it |
| 19 real compiled rules (NPS) | `mocks/rules_nps_poc.json` | 1 page of one 2-page checklist, 7 targets hand-corrected, `reviewed=false` |
| 170 real compiled rules (UNOLS research-vessel ADA guide) | `mocks/rules_unols_g38.json` | compiled with `gemini-3.8-flash`, 11 targets hand-corrected, `reviewed=false` |
| Real-rule planted evals: 88/90 (NPS), 23/23 (UNOLS), 0 missed | `docs/EVAL.md` (commands there) | **Re-run 2026-11-07: confirmed.** Written by us, not held out |

Caveats that must go on the slide next to the numbers:
- Dana: 20 rooms is a **partial sample**; no precision is reported (detections outside the sample cannot be called false positives); the gold set must not be used for tuning and then called held-out (`eval/gold/dana/README.md`).
- Planted: the cases and the rules were written by us; it shows the evaluator never misses a planted violation, not that real designs are fully covered.

## Slide 1: Title
**RuleCheck**: checks ship designs against the rules and shows its working. Since AI 2026, Meyer Turku challenge. Team of two. One line: "It tells you what fails, which clause says so, and where in the drawing."

## Slide 2: Problem
Compliance review is manual: regulations (SOLAS, MARPOL, DNV, PVAG/ADA ...) run to thousands of clauses and designs are GA drawings, specs and 3D models. An AI that is fluent but wrong is worse than useless here: a missed violation or an invented clause is the failure that matters. Source for the framing: challenge brief via `README.md`.

## Slide 3: Approach, "Rules are files, AI learns them, Python decides"
1. **Rules are files** in `knowledge/rules/<REGIME>/`; regime names come from folder names; no rule value in code.
2. **AI learns them**: compiler turns text into atomic rules; a rule is kept only if its quote is a verbatim substring of the source (`app/ingest/rule_compiler.py`). A person reviews (`PATCH /rules/{id}`).
3. **Python decides**: numeric, presence and count rules are evaluated deterministically (`app/check/evaluator.py`). The LLM judges only qualitative rules, with structured output, and an unverifiable verdict becomes `needs_review`.
4. **Never guess**: missing evidence, confidence below 0.6, or unknown applicability gives `needs_review`.

## Slide 4: Architecture
Diagram: rule files -> loader -> chunk/embed index -> compiler -> `rules.json` (reviewed) / design files (GA PDF, IFC) -> readers -> `DesignFacts` with provenance (file, page, bbox or IFC GlobalId) -> evaluator (+ LLM judge) -> findings citing **both** rule `SourceRef` and design `Provenance` -> web UI with evidence crops. Shared contract: `app/models.py`. One LLM gateway, `get_llm()`: Gemini (default), Claude, or local OpenAI-compatible (`app/providers/`).
GA reader detail: 200 dpi tiles with overlap, tile cache, our own number parser, cross-check against the PDF text layer (`app/design/drawing_vision.py`, `crosscheck.py`).

## Slide 5: Live demo
Follow `docs/DEMO.md`. Beats: real GA (Dana) -> honest result, no fail, needs_review where evidence is missing -> **planted** violation on the same drawing: verbatim quote + red-outlined drawing crop (say it is planted) -> trust scoreboard (15/15) -> user-stated ship type (recorded as manual provenance) -> Ask panel with a verified citation -> IFC reader.

## Slide 6: Accuracy and honesty (numbers above, with caveats printed on the slide)
- Planted violations: **15/15 correct, 0 missed, 0 false alarms** (12 cases; checking logic only).
- Dana GA reading: **19/20 sampled rooms found, 19/19 printed areas right** (partial sample, no precision, local run; re-verify before showing).
- Tests: **345 passed** (`pytest -q`). Planted-violation evals: 15/15 (mock rules), 88/90 (19 real NPS rules), 23/23 (UNOLS research-vessel rules), 0 missed violations in all three; written by us, not held out.
- Behaviour we can show rather than count: low-confidence reads become `needs_review` (cases "blurry read of a passing/failing door"); a door at exactly 812.8 mm passes, 812.7 fails.
- "Zero missed violations" is a property of the planted set, not a promise for all designs.

## Slide 7: Limits and what we did not do
- No GPU: Meyer's GPU machine was unavailable, so no local/on-prem model run (`README.md`). The `local` provider path exists but is untested on real hardware.
- Free-tier Gemini/Gemma: about 20 requests/day per model; vision boxes from Gemma and flash-lite are weaker (`README.md`). Only public drawings are safe on the free tier.
- Rules: 19 NPS rules (one page) and 170 UNOLS rules compiled, targets partly hand-corrected, **none human-reviewed**. No SOLAS/MARPOL/DNV text was obtained.
- Real drawing: on the Dana GA the checker finds **no fail**; most rules come back `needs_review` because a GA does not show the required evidence. The fail in the demo is planted and labelled.
- Retrieval: `/ask` runs on a real `bge-m3` index (86 passages from the two regulation folders) and answered a test question with a verified citation; not evaluated beyond that.
- 3D: IFC reader proven on a synthetic model only; the 305 MB `.nwd` was not converted (`docs/3D-MODELS.md`, `docs/IFC.md`). The reader uses explicit properties and does not derive clearances from geometry.
- Not done: Docker with the `rag`/`3d` extras (the base image is tested), BCF export, SOLAS/MARPOL/DNV text (not obtained), a precision metric for full-drawing extraction.

## Slide 8: Next steps
1. Compile and human-review the full rule libraries with a paid key; target a reviewed-rule percentage on the slide.
2. Exhaustive gold inventory for Dana to report precision and a true held-out score.
3. Real NWD to IFC export (Navisworks) and geometry-based clearance checks.
4. On-prem model on suitable GPU for confidential drawings.
5. BCF export so findings open in Navisworks/Revit (`docs/3D-MODELS.md`).

---

# Judge Q&A (honest answers)

**1. How do you stop hallucination?**
Three layers. Rules: a compiled rule is dropped unless its quote is a verbatim substring of the source text. Verdicts: numeric, presence and count rules are computed by Python, not the LLM; the judge's output is structured and an unverifiable verdict becomes `needs_review`. Answers: `/ask` verifies every citation is verbatim from a retrieved passage and withholds the answer if none verifies. What we cannot claim: the vision model can still misread a drawing; that is why the PDF text-layer cross-check caps unconfirmed values at confidence 0.59 so they go to a person.

**2. Is anything hardcoded?**
Rule values, regulation text and regime names are not in code; regimes are folder names, rules are JSON, tests use `mocks/`. What is in code: the evaluator's logic, the 0.6 confidence threshold, unit conversion, and the property vocabulary (`clear_width`, `area` ...) shared by rule and design sides. A mismatch there (we hit one: places in `target`) silently stops a rule matching, and the evaluator now says so in the finding.

**3. How do you prove accuracy?**
Two instruments, both with limits: 15/15 planted cases with 0 missed (logic only, our own cases), and Dana 19/20 rooms, 19/19 areas on a 20-room hand-checked sample (partial, no precision, not held-out if tuned). We have no end-to-end precision/recall on real regulations yet and say so.

**4. Confidentiality? Meyer's drawings are sensitive.**
On the free Gemini tier Google may train on prompts, so we use only public sample drawings and tell users the same. The architecture has one LLM gateway and a `local` provider (OpenAI-compatible server) for on-prem use, but we had no GPU, so it is designed, not demonstrated. The deterministic checker needs no LLM at all.

**5. Why not just ask an LLM?**
An LLM gives fluent answers with no guaranteed arithmetic, no verbatim quote and no pointer into the drawing. Here the number comparison is code, the quote is checked against the source, the design evidence is a bbox you can see, and uncertainty is an explicit state. An LLM is still used where it is good: reading drawings and compiling rules.

**6. Does it scale?**
Not proven. Rule compile and GA extraction are one LLM call per chunk/tile, cached and resumable, but the free tier is about 20 requests/day, so we compiled one page and extracted a few drawings. Evaluation itself is cheap and deterministic. Scaling means a paid key and a rule-review workflow; we have not measured throughput or cost.

**7. What is missing?**
Human-reviewed rules (189 compiled, none reviewed), real 3D (synthetic IFC only), on-prem model run, full-drawing precision, SOLAS/MARPOL/DNV coverage, Docker with the ML extras, an evaluation of `/ask` answers.

**8. What happens when the rules or the drawing are ambiguous?**
The result is `needs_review`, never pass or fail: unknown ship type (the user can state it; it is logged as manual provenance, never inferred), low extraction confidence, missing elements, or rules not checkable from a drawing (e.g. crew training). This is a design choice: a person looking at one extra finding costs less than a missed violation.
