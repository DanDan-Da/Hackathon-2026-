# RuleCheck: compliance checking for ship designs

Since AI Hackathon 2026 · Meyer Turku challenge "Automated class and regulatory compliance checking".

RuleCheck checks design documents (GA drawings, specs, 3D models) against regulations and explains **why** something
fails: every finding cites the rule (document, page, clause, verbatim quote) **and** the spot in the design (file, page,
bounding box or IFC GlobalId). When the evidence is missing or uncertain, the answer is `needs_review`, never a guess.

## Results (all reproducible, see [docs/EVAL.md](docs/EVAL.md))
| What | Result | What it does not prove |
|---|---|---|
| Planted violations, mock rules | 15/15 correct, 0 missed, 0 false alarms | Written by us; tests the checking logic only |
| Planted violations, real compiled rules | 88/90 (NPS, 19 rules), 23/23 (UNOLS, 170 rules), 0 missed | Same; rules are AI-compiled and not human-reviewed |
| Reading a real GA (Dana, public) | 19/19 printed room areas correct on a 20-room hand-checked sample | Partial sample, no precision reported |
| Real GA against the NPS rules | 0 fail, 9 needs_review, 10 not applicable | A GA does not show most of the required evidence, so those go to a person |
| Tests | `pytest -q`: 345 passed (with `dev,rag,3d` extras) | |

## How it works
1. **Rules are files, not code.** Put regulation documents in `knowledge/rules/<REGIME>/` (the folder name is the
   regime). The rule compiler (LLM) turns them into atomic, checkable rules in `knowledge/compiled/rules.json`, each with
   its source quote, page and clause. A rule is dropped if its quote is not verbatim in the source. A person reviews.
2. **Designs are files.** Put them in `designs/<project>/`. Readers turn PDFs, GA drawings and IFC into `DesignFacts`;
   every fact records where it came from. GA values are cross-checked against the PDF text layer; unconfirmed values are
   capped below the confidence threshold.
3. **Python decides.** Numeric, presence and count rules are evaluated deterministically (`app/check/evaluator.py`).
   Only qualitative rules go to an LLM judge, with structured output. Missing evidence, low confidence or unknown
   applicability give `needs_review`.
4. **Ask the regulations.** `/ask` answers from retrieved regulation passages only, and every citation is checked to be
   a verbatim quote.

The data contract shared by all parts is `app/models.py`.

```
knowledge/rules/<REGIME>/*.pdf --compiler--> rules.json ─┐
designs/<project>/ (GA PDF, IFC) --readers--> DesignFacts ┴─> evaluator (+ LLM judge) ─> findings ─> web UI + evidence crops
```

## Open the project (first time, ~5 min, no API key needed)
You need Python 3.12 and [uv](https://docs.astral.sh/uv/) (`brew install uv` or `pip install uv`).
```bash
git clone https://github.com/DanDan-Da/Hackathon-2026-.git && cd Hackathon-2026-
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"   # install
cp mocks/rules_nps_poc.json knowledge/compiled/rules.json      # put the demo rules in place
.venv/bin/uvicorn app.api.main:app                             # start; leave this window open
```
Open **http://localhost:8000**. Pick `demo/demo_real_drawing.json` or `demo/demo_planted_fail.json` in the
facts picker and press **Run check**, or click **Load demo** for mock data. Stop the server with Ctrl+C.
Next time only the last line is needed (run it from the project folder).

## Quick start (commands; run the last two in a second terminal while the server runs)
```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
.venv/bin/pytest -q
cp mocks/rules_nps_poc.json knowledge/compiled/rules.json      # 19 real compiled NPS rules
.venv/bin/uvicorn app.api.main:app                             # open http://localhost:8000, click "Load demo"
.venv/bin/python -m eval.score_findings                         # planted-violation eval
.venv/bin/python -m app.check.run mocks/facts_nps_poc.json --rules mocks/rules_nps_poc.json
```

### Try the real-drawing demo (no API key)
Two extracted facts files of the public Dana GA are in the repo, so anyone can run the demo without extracting:
- `designs/demo/demo_real_drawing.json`: what the reader extracted from the real drawing (0 fail, 9 needs review,
  10 not applicable with the NPS rules above).
- `designs/demo/demo_planted_fail.json`: the same file plus **one planted element** (marked "PLANTED TEST") that
  shows what a fail looks like. It is not from the drawing.

Pick either one in the UI's facts picker and press **Run check**. The red evidence crops also need the drawing
itself: put the Dana GA at `designs/demo/ga.pdf` (step 2 below). Without it the findings still work; the crop
shows coordinates as text.

### Run it on a real drawing (needs an API key)
The design and regulation PDFs are public but not stored in git (licence and size). See [docs/DATA.md](docs/DATA.md).
1. `cp .env.example .env` and set `GEMINI_API_KEY`.
2. Put the public Dana GA (`23007-01-101-0110-01-R2-14-General-arrangement.pdf`, linked in the challenge brief) at
   `designs/demo/ga.pdf` and run `.venv/bin/python -m app.design.drawing_vision designs/demo/ga.pdf --out designs/demo/facts.json`.
3. In the UI, pick `demo/facts.json` and press **Run check**.
4. For the Ask panel: install `.[rag]`, put the regulation PDFs in `knowledge/rules/<REGIME>/` (we used the NPS
   "Accessible Passenger Vessel Standards" checklist and the UNOLS "ADA Guidelines for UNOLS Research Vessels", 2008),
   and run `.venv/bin/python -m app.ingest.index`.

## Deployment
Install, configuration, running, compiling rules, extracting drawings, providers and on-prem use:
**[docs/DEPLOY.md](docs/DEPLOY.md)**. Or with Docker: `cp .env.example .env && docker compose up --build` (tested without extras).

## AI providers
All LLM calls go through one gateway, `app/providers/llm.get_llm()`. `LLM_PROVIDER=gemini` (default) with
`GEMINI_MODEL=gemini-3.8-flash` (best tested; `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite` and
`gemma-4-31b-it` also work; the aliases `gemini-flash-latest` / `gemini-pro-latest` do not work for new keys).
Free-tier limits are per model, e.g. 5 requests/minute and 20/day; recommended `LLM_MAX_RPM=4`, `LLM_MAX_PARALLEL=2`.
The tile cache in `designs/**/.cache` makes interrupted extraction resumable.

On the free tier Google may use prompts to improve its models: use **only public drawings**.

Alternatives: `LLM_PROVIDER=claude`, or `LLM_PROVIDER=local` with an OpenAI-compatible server for on-prem use of
confidential drawings (implemented in `app/providers/local.py` but never run: no GPU was available), e.g.
`vllm serve Qwen/Qwen2.5-VL-32B-Instruct --port 8001 --max-model-len 32768`.

## Limits
Compiled rules are not human-reviewed; no SOLAS/MARPOL/DNV text was available to us; 3D is proven on a synthetic IFC
(the Navisworks `.nwd` cannot be read by open-source tools); no on-prem model run; Docker image tested only without the `rag`/`3d` extras.

## Docs
[Demo script](docs/DEMO.md) · [Evaluation](docs/EVAL.md) · [Deployment](docs/DEPLOY.md) · [Slides and Q&A](docs/SLIDES.md) ·
[Sample data](docs/DATA.md) · [GA reading on Dana](docs/DANA.md) · [Vector measurement](docs/VECTOR.md) ·
[IFC reader](docs/IFC.md) · [3D models](docs/3D-MODELS.md) · [3D mesh cross-check](docs/3D.md)
