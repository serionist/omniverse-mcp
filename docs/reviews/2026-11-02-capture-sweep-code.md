---
subject: "Add capture_sweep, which captures a list of shots with their own cameras, selections and times as a job, a change to the tool contract and the wire protocol's routes (#157)"
base: main (2359c1d)
head: 23fd92c
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the extension's core and handler; the server, the contract, the docs and the live tests. A first live run beside them. Minors only, so no second round"
verdict: needs-fixes
---

# Review: Add capture_sweep

Read from the branch's diff against `main` at `2359c1d` (29 files, about 4,000 lines with the plan) by two fresh
reviewers, read only, against the approved plan `docs/plans/2026-11-02-capture-sweep.md` and the maintainer's
agreement on #157. One read `ovmcp/core/sweep.py`, the job board's changes, `handlers/sweep.py` and their tests,
reproducing each finding on usd-core; the other the server's tool, the contract, `get_job`'s answer, the docs, the
`scene` skill and the live tests. A first live run went beside them. No blocker or major; nine minors from the review,
three failures from the live run, all fixed. The reviewers numbered their findings apart: F for the first, G for the
second; L for the live run.

## The first live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, both live suites on a Z-up stage at `23fd92c`: 218 passed and 4
failed.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| L1 | major | the sweep through a scene camera | Both subtests of `test_a_sweep_takes_its_shots_...`: the root layer changed. RTX wrote two exposure API schemas and three `exposure:` attributes onto the scene camera at the edit target, as it does onto any bare camera it renders through, `capture_viewport` too | fixed by #177 (filed from this run): each camera a feed renders through is noted before and put back with the feed's render product; this branch builds on it |
| L2 | minor | the cancelled sweep | RTX's `over "OmniverseKit_Sweep"` with the three attributes stayed in the root layer after the sweep deleted its camera | fixed by #177, which puts it back with the render |
| L3 | minor | `handlers/sweep.py`, the start's refusal | `TestCaptureSweepAgents` was refused "/OmniverseKit_Sweep is on the stage already" because of L2's over | fixed in `1077fc1`: only a defined prim blocks a start; `test_an_empty_over_left_at_the_sweep_s_camera_blocks_nothing_and_stays` |

## Code review

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/sweep.py` `switch`, through `variants.switch` | Nested variant sets failed by a shot's place: `{A: {state: open}, A/Door: {color: blue}}` was refused "Prim not found" when A started closed, and after open, open+blue, closed+blue, two empty shots were refused "/World/A/Door has no variant set 'color'" | fixed in `a51edca`: reverts written unchecked; a shot's own selections outermost first, each level checked after the one above is written, a refusal taking back all of the shot's writes; both cases in `test_sweep.py` |
| F2 | minor | `handlers/sweep.py` `_put_stage_back`, `teardown` | The end put 400 snapshots back one change block each, 2.51 s on usd-core against 0.10 s in one | fixed in `a51edca`: one change block; `test_every_selection_comes_back_in_one_change` |
| F3 | minor | `_Sweep._begin`, `_end` | A feed whose first frame never came was handed back healthy and kept, so the next capture waited 30 s on it | fixed in `a51edca`: released, not kept; a cancel during the wait keeps it; two handler tests |
| F4 | minor | `_take` | A stage opened synchronously at a shot boundary could get a shot's writes, never undone | fixed in `a51edca`: the stage is checked before a shot writes and after its waits; `stop_for_stage` in `handlers/jobs.py`; three tests |
| F5 | minor | `tests/test_sweep_handler.py` | No test pinned the end's order against a second cancel: the fake `hand_back` never awaited | fixed in `a51edca`: it awaits, and a second cancel there still leaves the manifest and the last line |
| G1 | minor | `core/sweep.py` `read_shots`, the description, the skill, `docs/TOOLS.md` | A rerun from a manifest used the default 1280x720: a 640x480 manifest was refused with aperture advice, a 1920x1080 one rendered at 1280x720 | fixed in `1077fc1`: Kit refuses a manifest taken at another size, naming it; the docs say to give the first sweep's size; `test_a_manifest_taken_at_another_size_is_refused_naming_its_own` |
| G2 | minor | `tools/sweep.py` `Shot.horizontal_aperture` | Its description said 20.955 when left out, where with only a vertical aperture it is fitted to it | fixed in `1077fc1` |
| G3 | minor | `TestCaptureSweepAgents` | Failed on Isaac Sim 5.1, whose agent extension has no `api` module, instead of skipping | fixed in `1077fc1`: skips when Kit can't find `isaacsim.replicator.agent.core.api` |
| G4 | minor | `TestCaptureSweepAgents` | Left the agent extension enabled | fixed in `1077fc1`: turned off again when the test turned it on |

**Refuted,** from the code and from measurements: the shutdown teardown and the task's own end undoing twice; the
sweep jumping the viewport lock's queue; the dead-feed count read before the lock; a stage-change cancel putting the
old state onto the new stage; the route reachable without the token; script jobs changed by the board's changes; a
cancel during `hand_back` after a completed sweep; files left by a refused start; the server's `Shot` and the core's
fields drifting; the request and answer shapes; `shots=[]`; the skill's `allowed-tools`; a cancelled sweep losing its
folder; two unnamed sweeps in one second; a remote Kit's paths; the writing rules.

**The build's departures,** each judged sound: `_same_stage()` decides the end, not the cancel's reason; the end's
order; a dead feed ending the sweep; the manifest written at the start; `clipping_range` a shot field; a camera_path
shot's vertical aperture recorded as Kit's match-horizontal fit; the extra start refusals.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | `refusals` checks each (prim, set, variant) once, not once per shot | taken in `a51edca`: `test_refusals_check_each_selection_once_however_many_shots_ask_for_it` |
| I2 | The camera counts as made right after `Define`, so a failed clipping write still deletes it | taken in `a51edca` |
| I3 | A unit test pinning the server's `Shot` fields and `MAX_SHOTS` to the core's | taken in `1077fc1`: `test_the_server_s_shot_takes_the_fields_and_count_kit_reads` |
| I4 | `sweep_line` reuses the bridge's summary, the folder made output-relative | taken in `1077fc1` |
| I5 | Read `shots_file` as `utf-8-sig` | taken in `1077fc1` |
| I6 | The live test's "renders apart" by the share of pixels changed, not a whole-frame mean | taken in `1077fc1`: over 0.2% of pixels changed by more than 16 of 255 |

**Found while fixing:** with #177's first approach (a session-layer shield), a shield and a selection's snapshot could
each leave an empty over the other made; a prune was added (`a51edca`), then removed with that approach (`02be640`),
since #177's marks write nothing into the session layer and 3,000 random sweeps of nested, blocked and named
selections left it exact without one.

**Not covered:** Kit 107, Kit's own cost per change, whether 30 s a shot is enough under Path Tracing on a slow scene,
whether a switch's loading wait is ever needed (every switch measured 0.0 s on the test's small file).

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, on a Z-up stage, each run on a
fresh Kit:

- **At `23fd92c`,** the build: 218 passed and 4 failed (L1 to L3 above).
- **With round 1's fixes on #177's marks** (`f6f13a1`): both live suites, 221 passed. `TestCaptureSweep` makes its own
  Y-up then Z-up stage: six shots at 1280 x 720 with the case's lens (open, closed and the starting state, through a
  yaw and pitch and through a scene camera) in 1.9 s; the root layer, the session layer and the timeline as before
  once the kept render is released; the manifest matching the PNGs; the sweep taken again from its manifest within
  0.058 of 255 of its twins (Y-up; 0.021 on Z-up); every switch's loading wait 0.0 s; a 50-shot sweep cancelled after
  shot 5 putting everything back, its manifest saying what it took. `TestCaptureSweepAgents`, Isaac Sim's warehouse
  with one walking worker: a stopped timeline gave twins 1.141 of 255 apart; the same time after the worker walked
  changed 1.01% of the pixels.
- **On #177's final code** (`16c1db3`): the integration suite passed whole again (twins within 0.068 of 255, the
  agents test 1.185 of 255 and 1.13%); the scenario suite then failed test after test from `test_05_03` until the run
  was stopped for the machine's low memory (other sessions' Isaac Sim apps and WSL held some 21 GB). A scenario run
  just after failed 45 tests, stages closing under recordings and calls finding no stage; on the same Kit the scenario
  suite then passed 134 on `main`, 134 on #177's final code, and 134 on this branch's unchanged code, so that run was
  the machine's state at the time, not this change.
- **Rebased onto `391ee94`** (#177's merge): no conflict, the extension the same as `16c1db3`'s.

**What it couldn't show:** Kit 107 (Isaac Sim 5.1 fails in its own start-up on this machine); a bechtel-sized scene's
sweep time; whether 30 s a shot is enough under Path Tracing on a slow scene.
