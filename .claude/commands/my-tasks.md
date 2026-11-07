---
description: Show my (L or D) assignments and propose the next task
---
1. Read `.claude/whoami` (`L` or `D`). If it's missing, ask the user whether they are L (rules, checking, AI) or D (design, UI, eval), and write the answer to `.claude/whoami`.
2. Read `docs/tasks/<L|D>.md`.
3. Run `gh issue list -l <L|D> --state open` and `git log --oneline -10 origin/main`.
4. Give a short summary of what's done, what's open and what's blocked (dependencies on the other person).
5. Propose the next task, the highest-priority open one, with its branch name (`l/<topic>` or `d/<topic>`), the files to touch and the tests that count as done. Ask before starting.
