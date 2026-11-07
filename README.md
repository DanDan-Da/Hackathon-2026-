# RuleCheck: compliance checking for ship designs

Since AI Hackathon 2026 · Meyer Turku challenge. Checks design documents (specs, GA drawings, 3D models) against SOLAS, MARPOL, DNV, PVAG/ADA … and explains **why** something fails, citing the clause and the place in the design.

## How it works
1. **Rules are files, not code.** Drop regulation documents into `knowledge/rules/<REGIME>/`. The rule compiler (LLM) turns them into atomic, checkable rules in `knowledge/compiled/rules.json`, each one with its source quote, page and clause. An engineer reviews them.
2. **Designs are files.** Put them in `designs/<project>/`. Readers turn PDFs, drawings and IFC into `DesignFacts`, and every fact records where it came from (file, page, bbox).
3. **Checking.** Numeric, presence and count rules are evaluated **deterministically** (`app/check/evaluator.py`). Qualitative rules go to an LLM judge. If evidence is missing or extraction confidence is low, the result is `needs_review`. The checker never guesses.

The data contract shared by everything lives in `app/models.py`.

## Quick start
```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
cp .env.example .env            # add ANTHROPIC_API_KEY
.venv/bin/pytest                # evaluator tests on mock data
cp mocks/rules.json knowledge/compiled/rules.json
.venv/bin/uvicorn app.api.main:app --reload
curl -X POST localhost:8000/check -H 'content-type: application/json' -d @mocks/facts_violation.json
```

## AI providers
`LLM_PROVIDER=claude` (default, `claude-opus-5-5`) or `LLM_PROVIDER=local` (any OpenAI-compatible server):
```bash
vllm serve Qwen/Qwen2.5-VL-32B-Instruct --port 8001 --max-model-len 32768
```

## 3D models
IFC is read with `ifcopenshell`. Navisworks `.nwd` is proprietary, so export it to IFC/FBX from Navisworks first.

## Team split: L and D
- **L** works on rules, checking and AI: `app/ingest/`, `app/check/`, `app/providers/` and deployment. See [docs/tasks/L.md](docs/tasks/L.md).
- **D** works on design interpretation, the UI and the eval: `app/design/`, `web/` and `eval/`. See [docs/tasks/D.md](docs/tasks/D.md).

[docs/ASSIGNMENTS.md](docs/ASSIGNMENTS.md) has the overview and timeline. The GitHub issues are labelled `L` and `D`.
If you use Claude Code, start it in the repo and run `/my-tasks`.

Other docs: [3D models](docs/3D-MODELS.md) · [sample data](docs/DATA.md)
