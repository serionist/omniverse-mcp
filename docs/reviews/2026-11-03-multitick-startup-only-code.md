---
subject: "Say NVIDIA's multi-tick-rate workaround works only on Kit's command line, not from a script (#189)"
base: main (36821f9)
head: 138f169
date: 2026-11-03
round: 1
tier: "one fresh reviewer on Claude Opus, every lens that applies. One minor, so no second round"
verdict: clean
---

# Review: the workaround works only on Kit's command line

Read from the branch's diff against `main` at `36821f9` (4 files, 9 lines added) by one fresh reviewer, read only,
against issue #189 and the Isaac Sim 6.2 sources it cites: `isaacsim.core.simulation_manager`'s
`TestSimulationManagerMultiTickRendering` and `omni.replicator.core` 1.13.38's `orchestrator.py`. A trivial change:
no plan. One minor; fixed in the next commit, with the improvements below.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `README.md`, Known issues | "Kit reads the flag only as it starts ... Replicator ... then acts as if it were off" says more than the sources show: NVIDIA's comment covers the render pipeline only, and the Python reads are in Replicator's `step()` and `step_async()`, while its `run()` path reads none; someone tracing Replicator's output after a runtime set would take it as true of `run()` too | fixed: "Kit's renderer reads the flag only as it starts", "misleads Replicator's `step()`, which reads it on each call" |

**Refuted:** "reads it on each step" (both step functions read `carb.settings` on every call, uncached); "doesn't
reconfigure the renderer" (the test's comment, and the setting reads back `False` after a runtime set); another doc or
skill that tells agents to set Kit settings from a script (none; the setup skill and the assistant brief already say
not to touch Kit's settings); "Only Kit's command line takes it" against `extra_args` and the launcher script (both
are start-up arguments); the writing rules and the commit's form.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | SETUP.md's "as Isaac Sim's own tests say" points nowhere, and the evidence is a comment in a test's `setUp`: link #189 and say "a comment" | taken |
| I2 | Say it in the error too: agents without the plugin see only `KIT_SILENT` | taken: "It works only on Kit's command line: set from a script while Kit runs, it doesn't reconfigure the renderer", with its assertion in `tests/test_tools.py` |
| I3 | Other DLLs carry the setting's name, so "changes nothing" says more than the evidence; "doesn't reconfigure the renderer" doesn't | taken in the README, SETUP.md, the CHANGELOG and the skill |

**Not covered:** the gate, which the reviewer didn't run (quick passed at `138f169` and on the fixes); CI, before the
PR.

**Live suites:** not run. Text only, and an error that needs a real hang to show; the unit test checks it.
