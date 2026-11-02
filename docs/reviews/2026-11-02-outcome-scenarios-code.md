---
subject: "Add outcome scenarios to the AI suite, each asked in a user's words and judged by a read-only tester (#146)"
base: main (cff5b01)
head: 27bde7b
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the runner's code and tests; the suite's content and docs. Minors only, so no second round"
verdict: clean
---

# Review: Add outcome scenarios to the AI suite

Read from the branch's diff against `main` at `cff5b01` (12 files, about 1,590 lines with the plan) by two fresh
reviewers, read only, against the approved plan `docs/plans/2026-11-02-outcome-scenarios.md` and its owner-call
answers. Over `review-code`'s 1,500 lines, so the lenses were split: one read `tools/scenarios.py` and its tests, the
other `test_project/`, the skill and the docs, with step 8's run folders. Six minors, no blocker or major; all fixed
in `bf6ab0b`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tools/scenarios.py`, `run_sessions` | An interrupt during the runner's own steps (settle, prepare, a play of up to 18 s) skipped the cut-short records: the judge's record read as finished, and no NOT RUN rows came for the outcomes left, so `compare` exited 0 on a cut run | fixed: settle, prepare and play sit inside the try that writes the cut-short records; `test_an_interrupt_in_an_agent_or_in_the_runners_play_leaves_one_not_run_row_each` |
| F2 | minor | `tests/test_scenario_runs.py` | Nothing pinned one row an outcome: the tests read rows into a dict, so an agent's own row before its judge's would pass, listing each outcome twice and making `compare` exit 1 every run | fixed: `outcome_run` asserts the row list; taking out the agent's `continue` fails 6 tests |
| F3 | minor | `test_project/outcomes.md`, O1; `assistant.md` | No tool sets a stage light's intensity, and Isaac Sim's new light comes at 50,000, so an agent wanting a usable picture turned it down with code, and O1's `no execute_script` WARN measured a missing tool more than a choice; the brief's "Kit's settings ... beyond what the request needs" discouraged the no-code way, `viewport_light` | fixed: the brief says lighting the viewport for a picture asked for is part of the request; the header names each line's tool path, O1's `viewport_light` among them |
| F4 | minor | `.claude/skills/run-scenarios/SKILL.md`, step 1; `--phases` help | "`none` for outcomes alone" was wrong: with `--phases` given and no `--outcomes`, a run held no outcome, only the cleanup | fixed in the code, as the plan's Design says: `--phases none` alone runs every outcome; `test_phases_none_alone_runs_every_outcome`; the dry run in step 1 names `--outcomes` |
| F5 | minor | `test_project/outcomes.md`, O1, Verify | "its bound material's diffuse colour" tied the check to one path: a cube coloured by display colour renders red and would FAIL, against the judging rule that another way passes | fixed: "or with no material its display colour" |
| F6 | minor | `SKILL.md`, step 3 | The cost cited "the outcome plan's step 8", which recorded none, and the totals included the cleanup's session | fixed: the plan's Tests gain step 8's runs, with each outcome's status and the outcomes' cost alone, $1.36 and $1.69; the skill says $1.40 to $1.70 |

**Refuted,** each from the code or the runs:
- **The stdin feeder deadlocks:** it writes in its own thread while another drains stdout; the main loop never waits on
  stdin.
- **A tester that exits without reading stdin breaks the feeder:** `except OSError` covers the write and the close;
  `test_a_tester_that_ends_without_reading_its_prompt_ends_the_session_as_usual` feeds 100,000 characters to one.
- **A judge's prompt reaches `agents[case.id]` before its agent ran:** every path where the agent didn't run sets the
  halt or the outcome's refusal, and an interrupt re-raises.
- **A variadic flag swallows the next argument:** `--allowedTools`, `--disallowedTools` and `--add-dir` are each
  followed by an option or by nothing, and the prompt is no longer on the command line.
- **O4's `no execute_script` is unfair:** `set_physics_properties` says a friction or restitution adds the Collision
  API, and `physics:collisionEnabled` shows only once it is applied.
- **A Verify line the judge can't check:** each is read with the read-only tools, `Read` on the agent's files, or the
  answer.
- **The Givens don't build what the Verify lines assume:** checked by hand in step 8, and by the numbers: O2's 1.9 m
  fall takes 0.622 s; O4's floor top is at 0; O3's 120, 110, 100.
- **16.9's removal breaks something:** `test_16_09` exists, and no doc names 16.9.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Read the play's start time inside the try that pauses | taken: `test_a_failed_read_after_the_play_still_pauses` |
| I2 | results.md's Run Info names the outcomes asked | taken |
| I3 | A stub tester that ends without reading stdin, fed a long prompt | taken |
| I4 | The brief allows what a tool adds to do the job (O4's agent said it changed nothing else, unsure a `PhysMat` was allowed) | taken |
| I5 | `outcomes.md`'s header names each `no execute_script` line's tool path | taken (F3) |

**Not covered:** kit-main-thread, bridge-security and the tool contract, which nothing here touches; the extension and
the client are unchanged.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, this branch's bridge (`main`'s): step 8's runs, in the plan's
Tests; the outcomes again after `bf6ab0b`, below.

After the fixes, `uv run tools/scenarios.py run --phases none` (every outcome, from `--phases none` alone) on a clean
tree at `bf6ab0b`, run `20261102-154924`: O1 WARN, O2 PASS, O3 PASS, O4 WARN, O5 PASS, O6 PASS; $1.27 with the
cleanup, about 4 minutes; `compare`: no regression, no ID not run. O1 and O4 gave the same WARN in all three runs, for
the same calls:

- **O1:** `create_prim` makes the light, which comes at intensity 50,000, and the agent sets it to 3,000 with
  `execute_script`, since no tool sets a light's attributes. It also set `viewport_light` to `stage`, as the brief now
  allows.
- **O4:** the agent reads the prims' applied schemas with `execute_script`, which `get_prim_properties` doesn't list,
  then applies the Collision API with it, where `set_physics_properties` adds it only through a friction or
  restitution.

Both are findings about the tools, not the suite: follow-up issues on the maintainer's word.
