# RuleCheck: Claude Code instructions

Hackathon project (Since AI 2026, Meyer Turku challenge). It checks ship designs (specs, GA drawings, 3D models) against SOLAS, MARPOL, DNV, PVAG/ADA … and explains **why** something fails, citing the rule clause and the spot in the design. Judges care about **accuracy first**: a solid foundation beats polish.

Two people work on this repo. **L** owns the rules, checking and AI. **D** owns design interpretation, the UI and the eval.

## 1. Identify the user (do this first, every session)
1. Read `.claude/whoami`. It contains `L` or `D` and git ignores it.
2. If the file is missing or empty, ask once: "Are you L (rules, checking, AI) or D (design, UI, eval)?" Then write the answer to `.claude/whoami`.
3. Read `docs/tasks/<L|D>.md`, the person's task list and file ownership.
4. Run `gh issue list -l <L|D> --state open` to see which tasks are still open.
5. Work only on that person's tasks and files unless they explicitly ask otherwise. `/my-tasks` repeats steps 1–4 and proposes the next task.

## 2. Hard rules (both people)
- **Nothing hardcoded.** Regulations are files in `knowledge/rules/<REGIME>/` and designs are files in `designs/<project>/`. Regime names come from folder names. Never put rule values, regulation text or example URLs in code. Tests use `mocks/`.
- **Every finding cites both sides:** the rule (`SourceRef`: document, page, clause, verbatim quote) and the design evidence (`Provenance`: file, page, bbox or IFC GlobalId).
- **Never guess.** If evidence is missing, extraction confidence is low, or applicability is unknown, the result is `needs_review`.
- **Deterministic first.** Python checks numeric, presence and count rules (`app/check/evaluator.py`). The LLM only judges qualitative rules, and its output must be structured.
- **Internal units:** lengths in mm, areas in m². Convert with `app/check/units.py`.
- **`app/models.py` is the shared contract between L and D.** Change it only in its own small PR, and tell the user to inform the other person.
- **LLM calls only go through `app/providers/llm.get_llm()`.** Never import `anthropic` or `openai` elsewhere. `LLM_PROVIDER=claude|local` switches between them.
- Never commit `.env`, `Files/`, `*.nwd` or large design PDFs (see `docs/DATA.md`).

## 3. Git workflow
- `main` must always pass `pytest`. **Never push directly to `main`, and never force-push.**
- Make one short-lived branch per task, named `l/<topic>` or `d/<topic>` (e.g. `l/rule-compiler`). Each branch lives 1–3 hours.
- Before opening a PR, run `git pull --rebase origin main` and then `.venv/bin/pytest -q`.
- Open a PR into `main` with `Closes #<issue>` in the body. The author may merge it (squash). Merge at least every 2 hours.
- No long-lived personal branches.

## 4. Commands
```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"   # add ,rag / ,3d extras as needed
.venv/bin/pytest -q
.venv/bin/uvicorn app.api.main:app --reload
```

## 5. Map
- `app/models.py` holds the contract (shared).
- `app/providers/` holds the LLM layer (L).
- `app/ingest/` turns rule files into `rules.json` (L).
- `app/check/` holds the evaluator and LLM judge (L).
- `app/design/` turns design files into `DesignFacts` (D).
- `web/` is the UI (D).
- `eval/` holds the gold set and metrics (D).
- `app/api/` holds the FastAPI routes (each person adds their own).
- `docs/ASSIGNMENTS.md` is the overview, and `docs/3D-MODELS.md` is the 3D plan.
