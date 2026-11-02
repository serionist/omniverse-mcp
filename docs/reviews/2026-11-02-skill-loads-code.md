---
subject: "Point the server's instructions at the plugin's skills (#152)"
base: main (6a6982c)
head: 4e97d06
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; no finding"
verdict: clean
---

# Review: Point the server's instructions at the plugin's skills

Read from the branch's diff against `main` at `6a6982c` (3 files, about 25 lines) by one fresh reviewer, read only,
with every lens. There is no plan: the PR is `Trivial`. No finding; two improvements taken after `4e97d06`.

**Refuted:**
- **The line misleads a client without the plugin:** it opens "With the omniverse-mcp plugin", which the test pins;
  such a client reaches the skills through `docs/AI_GUIDE.md`'s workflows table.
- **The glosses don't match the skills:** each is in the skill's description or body (`scene`'s "Light and black
  captures", `simulate`'s colliders, `geometry`'s face counts and USD files, `script`'s `execute_script`).
- **`docs/AI_GUIDE.md` must move with it:** its Context is for clients without the plugin, and its workflows table,
  which the gate checks, already links every skill.
- **The test misses a renamed skill:** the file check fails on a renamed folder, and the gate holds a skill's `name`
  to its folder.
- **"Before you change the stage" leaves read-only work without a skill load:** true in the runs (O3 loaded none, O5
  once in two), but both passed both times, so no wrong result: improvement I3.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | The test finds the workflow skills from the plugin's folders, so a new one fails it until the instructions name it; `write-skill` says so | taken |
| I2 | Reuse `conftest.REPO_ROOT` | taken |
| I3 | "Load its skill for the work first" rather than "before you change the stage" | left: the two runs measured this wording; the read-only outcomes passed without a skill, and a load before a one-call read costs more than it gives |
