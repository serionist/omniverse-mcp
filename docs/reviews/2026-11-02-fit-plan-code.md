---
subject: "Add a fit-plan step that asks whether a plan is the right one before its review (#160)"
base: main (0cb889c)
head: e62f3a9
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens, the port diffed against simready-forge's #12; no findings"
verdict: clean
---

# Review: Add a fit-plan step

Read from the branch's diff against `main` at `0cb889c` (10 files, about 1,000 lines with the plan) by one fresh
reviewer, read only, with every lens, against the approved plan `docs/plans/2026-11-02-fit-plan.md`, each ported file
diffed against simready-forge's `caa1f56`. No findings.

**Port fidelity:** every difference from `caa1f56` is one the plan lists: `docs/USAGE.md` becomes `docs/TOOLS.md`,
`docs/ARCHITECTURE.md` and the tool contract; who uses the change; the prior-art sources; the examples from this repo's
plans; `start-work`'s list of what needs a plan; `AGENTS.md`'s wording under its cap. `review-plan` differs only in
its Never line, which already named the bridge's security. The gate's functions are the source's word for word; the
only additions are `FIT_SINCE`, its early return and the docstrings saying so. The tests are the source's cases with
fixture names built from `FIT_SINCE`.

**Refuted:**
- **`AGENTS.md` names `fit-plan` without saying when:** the gate checks the name, the line's other loop skills carry
  no gloss, and How a change lands step 3 says when.
- **Two `questions.md` examples aren't fit improvements:** the column says "from this repo's plans", which both are.
- **A merged or in-flight plan fails the check after the merge:** none does; the 26 plans and the branches' plans
  (#150's, #151's, #159's) each have one `## Plan review`, balanced fences and no repeated `I` id.
- **`review-plan` forces a Fit onto a plan with rounds:** later rounds go back to step 3, not step 1, and a merged plan
  changes only its progress log.
- **`approved_by` holds more than a login:** nothing parses it.
- **`fit-plan`'s Done means overstates the gate for plans before `FIT_SINCE`:** the plan's Risks accept it.
- **Test name clashes, a check loosened, stale step numbers, Windows or Python 3.11 trouble:** none; each checked
  against the files. Changing `<` to `<=` at `FIT_SINCE` breaks `test_plan_problems`.

**Improvements:** none worth more than their edit.

**Not covered:** the gate and CI (the reviewer ran neither); the plan's steps 5 and 6, below.

## The plan's steps 5 and 6

- **Step 5, the chain by hand:** this repo's `fit-plan`, from this branch, fitted #159's, #156's and #158's plans
  through fresh agents, each brief naming the skill's two files; #159's Fit and its three taken improvements are in
  its plan (`b4981f2`). That Fit, named from `FIT_SINCE` with a stub `### Round 1` after it, passes `plan_problems`;
  with one row `open` it fails ("the Fit's I1 has no answer"), and with the Fit cut out it fails ("a review round with
  no `### Fit` above it").
- **Codex:** not installed here; `.agents/skills/fit-plan` is a link in git's index (mode 120000, to
  `../../.claude/skills/fit-plan`), which gate quick's `skill links` checks.
- **Step 6, `FIT_SINCE`:** after `git fetch origin` and the rebase onto `a530e05`, the plans any branch adds are all
  dated 2026-11-02 (`git log --all --diff-filter=A --name-only --format= -- docs/plans/`), so `FIT_SINCE` stays
  2026-11-03.
