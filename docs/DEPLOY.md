# Deployment and operation

Everything here was checked by reading the code (`pyproject.toml`, `app/config.py`, the `argparse` blocks and `app/api/main.py`). Anything not run is marked **not verified**. No LLM call was made while writing this.

## Prerequisites
- Python 3.12 (`pyproject.toml` allows >= 3.11; the repo is developed on 3.12) and [uv](https://docs.astral.sh/uv/).
- A Gemini key for the default provider (free key: https://aistudio.google.com/apikey), or an Anthropic key, or a local OpenAI-compatible server (see Providers).
- Optional: Docker (see the last section).

## Install
```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
```
Extras, added to the same command, for example `-e ".[dev,rag,3d]"`:
- `rag`: `qdrant-client`, `sentence-transformers`. Needed for the regulation index (`app.ingest.index`) and `POST /ask`. Without it `/ask` returns 503. The first index build downloads the `BAAI/bge-m3` embedding model.
- `3d`: `ifcopenshell`, `trimesh`. Needed for the IFC reader (`app/design/ifc_reader.py`).
- `dev`: `pytest`.

## Configuration (`.env`)
```bash
cp .env.example .env
```
`.env` is git-ignored. Never commit it and never paste real keys into docs. Variables (defaults from `app/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `claude` or `local` |
| `LLM_MAX_PARALLEL` | `2` | parallel AI requests; keep 1-2 on a free key |
| `LLM_MAX_RPM` | `0` (`.env.example` sets `4`) | requests per minute, `0` = unlimited |
| `GEMINI_API_KEY` | empty | key for `gemini` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | `-latest` aliases do not work for new keys |
| `ANTHROPIC_API_KEY` | empty | key for `claude` |
| `CLAUDE_MODEL` / `CLAUDE_FAST_MODEL` | `claude-opus-5-5` / `claude-haiku-5-5` | |
| `LOCAL_BASE_URL` / `LOCAL_MODEL` | `http://localhost:8001/v1` / `Qwen/Qwen2.5-VL-32B-Instruct` | OpenAI-compatible server |
| `RULES_DIR` | `knowledge/rules` | regulation files, one folder per regime |
| `COMPILED_RULES` | `knowledge/compiled/rules.json` | output of the compiler |
| `DESIGNS_DIR` | `designs` | design files, one folder per project |

`app/config.py` also has `INDEX_DIR` (`knowledge/index`, on-disk Qdrant) and `EMBEDDING_MODEL` (`BAAI/bge-m3`). Relative paths resolve against the directory you start the process in, so start everything from the repo root.

## Run the API and UI
```bash
.venv/bin/uvicorn app.api.main:app --reload            # http://localhost:8000
```
The UI in `web/` is served by the same process at `/`. API routes: `GET /health`, `GET /rules`, `POST /ingest/rules`, `PATCH /rules/{id}`, `POST /check`, `POST /ask`, plus the UI routes in `app/api/ui.py` (`/demo`, `/check`, `/trust`) and `app/api/evidence.py`. Quick smoke test with mock data and no key:
```bash
cp mocks/rules.json knowledge/compiled/rules.json
curl -X POST localhost:8000/check -H 'content-type: application/json' -d @mocks/facts_violation.json
```
(`knowledge/compiled/*.json` is git-ignored.) The demo script is `docs/DEMO.md`.

## Where regulations go
Put regulation files in `knowledge/rules/<REGIME>/`. The first-level folder name is the regime (nothing in code knows regime names). Supported: `.pdf`, `.txt`, `.md`, `.html`, `.htm`, subfolders allowed (`app/ingest/rules_loader.py`). Regulation files are git-ignored and stay local; sources are listed in `docs/DATA.md`. Designs go in `designs/<project>/` (PDFs are git-ignored too).

## Compile rules (uses the LLM)
```bash
.venv/bin/python -m app.ingest.rule_compiler [--regime NAME] [--parallel N] [--fresh]
```
- `--regime NAME`: only that folder; other regimes' rules in `rules.json` are kept.
- `--parallel N`: overrides `LLM_MAX_PARALLEL` (`1` = sequential).
- `--fresh`: ignore and do not write the per-chunk cache (default is to cache, so an interrupted run resumes).

Rules already marked `reviewed` are kept. A rule survives only if its quote is a verbatim substring of the source. Humans review via `PATCH /rules/{id}`. The same compile can be triggered with `POST /ingest/rules?regime=NAME` (can take minutes).

Regulation index for `/ask` (needs `rag`, downloads the embedding model, **not verified here**):
```bash
.venv/bin/python -m app.ingest.index
```

## Extract facts from a GA drawing (uses the LLM)
```bash
.venv/bin/python -m app.design.drawing_vision designs/<project>/<drawing>.pdf [--project NAME] [--dpi N] [--out facts.json] [--cache DIR]
```
Defaults: project = the PDF's parent folder name, output = `<pdf folder>/facts.json`, tile cache = `<pdf folder>/.cache` (a stopped run resumes from it). It renders tiles, asks the LLM for elements with boxes, and cross-checks against the PDF text layer when there is one.

Other readers:
```bash
.venv/bin/python -m app.design.ifc_reader model.ifc [--project NAME]                  # needs [3d]; prints DesignFacts JSON
.venv/bin/python -m app.design.cross_check <mesh.ifc> <stated.pdf> [--tolerance X]    # mesh extent vs stated particulars
.venv/bin/python scripts/generate_synthetic_ifc.py out.ifc [--millimetres]            # test IFC; needs [3d]
```
Details: `docs/IFC.md`, `docs/3D.md`, `docs/3D-MODELS.md`. Navisworks `.nwd` must be exported to IFC first.

## Run the checks (no server, no key)
```bash
.venv/bin/python -m app.check.run designs/<project>/facts.json [--rules rules.json] [--status fail,needs_review] [--json] [--llm]
```
Without `--llm` qualitative rules become `needs_review`, so the run is free, offline and reproducible. `--llm` lets the configured provider judge them. Offline example that works from a clean checkout (run while writing this doc):
```bash
.venv/bin/python -m app.check.run mocks/facts_violation.json --rules mocks/rules.json --status fail
```

## Tests and evals
```bash
.venv/bin/pytest -q
.venv/bin/python -m eval.score_findings [--facts F] [--rules R] [--cases C]   # planted violations, deterministic, no key
.venv/bin/python -m eval.score_rooms facts.json [--gold eval/gold/dana/dana_rooms.json]
```
`score_findings` defaults: `mocks/facts_violation.json`, `mocks/rules.json`, `eval/gold/findings/cases.json`. `score_rooms` needs a `facts.json` produced from the Dana GA drawing (git-ignored, see `docs/DATA.md`); to regenerate it (needs an LLM key):
```bash
.venv/bin/python -m app.design.drawing_vision designs/dana/23007-01-101-0110-01-R2-14-General-arrangement.pdf --out designs/dana/facts.json
.venv/bin/python -m eval.score_rooms designs/dana/facts.json
```
Metric definitions and limits: `eval/gold/dana/README.md`, `docs/EVAL.md`.

## Providers and on-prem
Switch with `LLM_PROVIDER=gemini|claude|local`. All LLM calls go through `app/providers/llm.get_llm()`.
- `gemini` (default): free tier is per model; for `gemini-3.8-flash` it is 5 requests/minute and 20 requests/day (README). Use `LLM_MAX_RPM=4`, `LLM_MAX_PARALLEL=2`. The tile cache makes extraction resumable. On the free tier Google may train on prompts: **use only public drawings**.
- `claude`: set `ANTHROPIC_API_KEY`. Paid.
- `local`: any OpenAI-compatible server at `LOCAL_BASE_URL`, for example `vllm serve Qwen/Qwen2.5-VL-32B-Instruct --port 8001 --max-model-len 32768`. It needs a GPU. **We have none (Meyer's GPU machine was unavailable), so this path is designed but never run.**

On-prem story: one process, no external service besides the LLM endpoint. Designs and rules live in local folders and the app does not upload them anywhere except to the configured LLM provider. The deterministic checker (`app.check.run` without `--llm`) needs no network. Confidential drawings are therefore safe only with `local` on suitable hardware (not demonstrated) or a paid provider under suitable terms.

## Docker (untested: docker not run here)
`Dockerfile` and `docker-compose.yml` were written by reading `pyproject.toml` only. They have **not been built or run**.
```bash
cp .env.example .env
docker compose up --build        # http://localhost:8000
```
Design choices to check if it fails: editable install (`pip install -e`) because `app/api/main.py` finds `web/` relative to the source tree; `knowledge/` and `designs/` are bind-mounted so regulations and designs stay on the host; extras via the `EXTRAS` build arg (for example `"[rag,3d]"`; `rag` pulls in large ML packages and the embedding model downloads at first use). The `local` provider on `localhost` inside a container needs `LOCAL_BASE_URL` pointed at the host. There is no `.dockerignore`; the build copies only `pyproject.toml`, `app/`, `web/` and `mocks/`, so `.env` and `Files/` do not enter the image.

## Not verified
Docker files; the `--help` output of each module (read from the `argparse` code instead); `app.ingest.index` and `/ask` with real `bge-m3`; the `local` provider; any live LLM call.
