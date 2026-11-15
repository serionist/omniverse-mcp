---
subject: "Step physics by an exact count and read bodies and joints back with sim_control (#198)"
base: main (e96adb3)
head: b8ceef9
date: 2026-11-15
round: 1
tier: "one fresh reviewer on Claude Opus, every lens. Three minors, so no second round"
verdict: clean
---

# Review: Exact steps and the read-back in sim_control

Read from the branch's diff against `main` at `e96adb3` (28 files, about 1,800 lines with the plan) by one fresh
reviewer, read only, against the approved plan `docs/plans/2026-11-15-exact-step.md`. Three minors, fixed in
`f994f6a`; the full gate passed on both commits (2,950 and 2,953 tests).

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | the plan's Progress; `_step`'s `load_steps` | Step 1's measurements aren't in the plan, and a step count Isaac Sim resets on play, not on stop, would give a negative load count | fixed in `f994f6a`: a negative count gives none (`test_a_step_count_reset_by_the_play_gives_no_load_count`); the measurements wait for the live run, which records them in Progress |
| F2 | minor | `_step` | The 90 s limit started after the load from stopped, which cooks a robot's meshes on its first play: a heavy scene could still reach the server's 120 s | fixed in `f994f6a`: the clock starts before the load (`test_the_time_limit_counts_the_load_from_stopped`) |
| F3 | minor | `_step_header` | A step stopped early by a play still said the timeline's time was unchanged | fixed in `f994f6a`: "unchanged" only for a step that ran to its end (`test_a_step_stopped_early_doesnt_say_the_time_stood_still`) |

**Refuted:** the `_body_row` refactor changing `apply_force` (the view's failure still caught with its traceback, the
invalidate in `finally` on the early return, the refusal for a body PhysX doesn't hold the same branch); a race on the
lock (no await between `locked()` and `async with`, one thread); the engine check refusing PhysX (Context7 types it
`Literal[physx, newton, remotesim]`; a Kit without it counts as PhysX); Fabric's update's argument order (dt first, as
omni.physx's guide calls it); `read_joint_states` changing `/robot/joint_states`' answer (same keys and errors);
the live cube touching anything (200 m up, 4.9 m of fall); existing live tests calling `step` (they use the client's
`/sim/control`, kept); a silent contract change (Breaking, the maintainer's agreement in #198, the fixture); Kit called
off the main thread.

**Not covered:** live behaviour, the reviewer having no Kit: Fabric's world matrix after a step on the CPU and under
the Direct GPU API, whether omni.physx.fabric stops USD write-back in the scenario Kit (which would fail the
`usd_written=True` check), the load's warm-up steps, and a Franka's physics view after a 0-step load. The live run
answers them. REVIEW questions on the PR's text wait for the PR.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | `handle_sim_state` repeats the playing, stopped or paused expression `_state(timeline)` now holds | taken |
| I2 | `_check_exact_steps` prints the answer's `load_steps` and `fabric`, so every live run records Step 1's numbers | taken |

## Live run

On Isaac Sim 6.2.0-rc.14 (Kit 110.4.0), `isaacsim.exp.base.kit` headless on Windows 11, port 8212, Z-up, started with
`--/rtx/hydra/supportMultiTickRate=false`, 2026-11-15, on a local merge of this branch and #203's:

- `test_scenarios.py`: 15.17 (the exact step) and 15.18 (the Franka) passed alone; in three full runs, 136 tests
  each, 15.17 failed once, when Isaac Sim's count of the load's steps read 4 instead of 2. The check now measures from
  the speed the load left (`24ba58d`); that version hasn't run on Kit yet.
- `test_integration.py`: 87 passed, 1 failed, `TestCaptureSweepAgents::test_a_stopped_timeline_repeats_an_agent_and_a_time_doesn_t`
  (repeated captures 2.19 of 255 apart against 2.0; its own message says the multi-tick flag the Kit ran with makes
  it about 3.2), not this change's code.
- `test_scenarios.py` 26.03 failed in all three runs (5 RTX view assignments counted in Kit's log for five captures,
  not 2); unsettled whether it is this Kit's launch (another session started it, its log elsewhere, with the
  multi-tick flag) or a change: #198 touches no capture code, #203 does.
- Not run: the GPU suite, Isaac Sim 5.1, USD Composer.
