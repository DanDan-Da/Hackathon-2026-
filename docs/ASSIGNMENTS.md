# Assignments: L and D

| | **L**: rules, checking, AI | **D**: design, UI, eval |
|---|---|---|
| Turns | regulation files into `rules.json` | design files into `DesignFacts` |
| Owns | `app/ingest/`, `app/check/`, `app/providers/`, deploy | `app/design/`, `web/`, `eval/`, demo |
| Detailed tasks | [tasks/L.md](tasks/L.md) | [tasks/D.md](tasks/D.md) |
| Issues | `gh issue list -l L` | `gh issue list -l D` |

**Hand-off point:** `app/models.py`. The two halves meet in `POST /check`, which turns rules plus facts into findings. Until the real pipelines produce data, each of you works against `mocks/`.

## Timeline (about 1 day)
| Block | L | D |
|---|---|---|
| 0–1.5h | ✅ done: skeleton, models, evaluator, providers | ✅ done |
| 1.5–5h | L1–L3 rule loader, index, compiler | D1–D3 PDF text, GA vision, cross-check |
| **~5h** | **Checkpoint: real rules × real facts** | |
| 5–8h | L4–L5 review endpoint, LLM judge | D4–D6 3D, IFC reader, UI |
| **~8h** | **Checkpoint: full pipeline + eval** | |
| 8–10h | L6–L7 local GPU mode, /ask | D7 gold set + metrics |
| 10–12h | Integration + accuracy fixes (together) | |
| last 2h | L8 Docker + DEPLOY.md | D8 video + slides |

## If you're behind, cut in this order
1. `/ask` chat (L7)
2. Local GPU mode (L6). Mention it in the slides instead.
3. Real NWD conversion. Use the synthetic IFC.
4. UI polish

**Never cut:** citations, `needs_review` behaviour, and the eval numbers.

## Git
Make short-lived `l/<topic>` or `d/<topic>` branches and open a PR into `main` with `Closes #n`. Merge at least every 2 hours. See `CLAUDE.md` §3.
