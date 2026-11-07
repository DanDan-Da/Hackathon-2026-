# Planted-violation eval

`python -m eval.score_findings [--facts F] [--rules R] [--cases C]` runs the real evaluator
(`app/check/evaluator.py`) on a base design with one small change per case (set a property, set a
confidence, remove an element, change a ship particular) and compares each finding with the status the
regulation semantics demand. No network, no LLM (qualitative rules come out as `needs_review`).

Suites:

| Cases | Facts | Rules |
|---|---|---|
| `eval/gold/findings/cases.json` | `mocks/facts_violation.json` | `mocks/rules.json` |
| `eval/gold/findings/cases_nps_poc.json` | `mocks/facts_nps_base.json` | `mocks/rules_nps_poc.json` |

## What is measured
- Per case: does the finding for (rule, element) have the expected status (pass, fail, needs_review, not_applicable)?
- **Missed violation** (worst error): a case that must `fail` but came back `pass` or with no finding. The CLI exits 1 on any.
- False alarms, and a breakdown per rule type (numeric / count / presence / qualitative).
- Covered: boundaries (at the limit, just under), inch rules fed with mm values (60 in = 1524 mm), low confidence,
  missing or non-numeric properties, removed elements, persons-on-board tiers, wrong or unknown ship type.

## What this is not
- The cases are **synthetic and written by us**, from reading the rules; they are not held-out and not from a
  real classification-society review. They test the checking logic, not design extraction (D's gold set) or rule
  compilation quality.
- The NPS rules are `reviewed=false` Gemini compilations. Expected statuses come from the regulation text, not
  from evaluator output. Where the evaluator disagrees, the expectation stays and the case carries
  `known_disagreement`; it counts as wrong and is listed separately. Fix the evaluator or the rule, then drop the flag.
