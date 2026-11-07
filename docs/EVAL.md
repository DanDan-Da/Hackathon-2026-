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

## UNOLS research-vessel rules (cases_unols.json)
`python -m eval.score_findings --rules mocks/rules_unols_g38.json --facts mocks/facts_unols_base.json --cases eval/gold/findings/cases_unols.json`
23 planted cases on the rules a general arrangement can decide: door clear width >= 32 in, passageway clear width >= 36 in and width >= 4 ft, toilet compartment 60 x 56 in. They cover exact boundaries in mm against inch rules (812.8 / 914.4 / 1524 / 1422.4 mm pass, one mm less fails), low-confidence reads (needs_review), missing values and removed elements (needs_review, never pass). Result: 23/23 correct, 0 missed violations, 0 false alarms. Written by us from the regulation values, not held out; the rules are reviewed=false and 11 of 170 had their target corrected by hand.
