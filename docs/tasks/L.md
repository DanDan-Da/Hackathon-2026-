# L: Rules, checking and AI infrastructure

> **Read [`docs/L-LOG.md`](../L-LOG.md) first:** what is actually done, unpushed branches, API/quota decisions, known rule-quality problems and open work.

**You own:** `app/ingest/`, `app/check/`, `app/providers/`, `app/config.py`, the `/ingest/rules`, `/rules`, `/check` and `/ask` routes in `app/api/main.py`, plus `docker-compose.yml` and `Dockerfile`.
**Read-only for you:** `app/design/`, `web/` and `eval/`, which belong to D. Change `app/models.py` only by agreement with D.
**Work against:** `mocks/facts_violation.json`, which stands in for D's output until real `DesignFacts` exist.
**You deliver to D:** `knowledge/compiled/rules.json` (a list of `Rule`) and `POST /check`, which turns `DesignFacts` into `Finding[]`.

Tasks are in priority order. Each one has a GitHub issue labelled `L`.

## L1 Rule loader (≈0.5h)
`app/ingest/rules_loader.py` scans `settings.rules_dir` recursively. The first-level folder name is the regime, and the files can be `.pdf`, `.txt`, `.md` or `.html`.
- It yields `(regime, document, page, text)` chunks, using PyMuPDF for PDFs.
- **Done:** unit test with a temp folder of 2 regimes and 3 files. No regime names appear in code.

## L2 Chunk + embed index (≈1h, `rag` extra)
`app/ingest/index.py` stores chunks with page and clause metadata, embeds them with `BAAI/bge-m3`, and saves them to Qdrant (local mode, on disk).
- `search(query, regime=None, k=8)` returns the chunks with their metadata.
- **Done:** a test with mocked embeddings. Retrieval returns source document and page.

## L3 Rule compiler, the "learning" step (≈2h, core)
`app/ingest/rule_compiler.py` sends each chunk to `get_llm().complete_structured(..., schema=RuleBatch)`, where `RuleBatch` is `{rules: list[Rule]}`.
- The prompt tells the model to:
  - extract only atomic, checkable requirements
  - copy `source.quote` **verbatim**
  - normalise the parameter names (`clear_width`, `height`, `area`, `count` …)
  - put the unit as written (the evaluator converts it)
  - use `qualitative` when the requirement can't be measured
- Post-validation drops any rule whose `quote` isn't a substring of the chunk text, since that means a hallucinated quote. Log the dropped rules.
- Deduplicate on (regime, clause, parameter) and write `settings.compiled_rules`.
- Start with PVAG/ADA, because they're full public text with concrete numbers.
- **Done:** `python -m app.ingest.rule_compiler` turns the rules folder into `rules.json`. Tests use a fake `LLMProvider` and cover the quote check and deduplication.

## L4 Rule review endpoint (≈0.5h)
- `POST /ingest/rules` runs L1–L3.
- `GET /rules` lists the rules.
- `PATCH /rules/{id}` edits a rule or sets `reviewed=true`. This is the "engineer in the loop" part.

## L5 LLM judge for qualitative rules (≈1.5h)
`app/check/llm_judge.py` takes a qualitative `Rule`, the relevant `DesignElement`s and the retrieved clause context, and returns a structured `{status, reasoning, evidence_ids, clause_quote}`.
- Wire it into `evaluate_rule` for `CheckType.qualitative`.
- `status` must be `needs_review` if `evidence_ids` is empty, and any `evidence_ids` that don't exist are rejected.
- **Done:** tests with a fake provider.

> **Provider note:** the team uses **Gemini** (`LLM_PROVIDER=gemini`, `app/providers/gemini.py`, added by D). L3 and L5 get it automatically through `get_llm()`. Free-tier limits are per model. Use `LLM_MAX_RPM=4` and `LLM_MAX_PARALLEL=2`; see the README for model choices and daily limits.

## L6 Local provider on the GPU (optional / not available)
- Meyer's GPU machine is unavailable; the team has no GPU. This task is optional and cannot currently be run.
- Keep `LLM_PROVIDER=local` as a possible path if suitable hardware becomes available. Then run `vllm serve Qwen/Qwen2.5-VL-32B-Instruct --port 8001` on that machine.
- Verify that `app/providers/local.py` structured output works, then run L3 with `LLM_PROVIDER=local`.
- Write down the setup in `docs/DEPLOY.md`.

## L7 `/ask` regulations chat (≈0.5h, cut first if late)
It answers questions from the L2 index with citations.

## L8 Deployment (≈1h, last block)
- `Dockerfile` and `docker-compose.yml`: api, qdrant, and an optional vllm profile.
- Finish `docs/DEPLOY.md`. The brief explicitly asks for deployment docs.

## Checkpoints with D
- **About 5h:** real `rules.json` against D's real `DesignFacts` from one GA.
- **About 8h:** full pipeline plus D's eval numbers. Fix the rules that cause false positives.

> D's hand-off notes for L (changes in your files, open asks) are in `docs/D-LOG.md`.
