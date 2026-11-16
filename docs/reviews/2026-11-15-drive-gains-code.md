---
subject: "Read each joint's drive from physics, and set drive gains with set_joint_drives (#199)"
base: main (2532cc9)
head: 2b57e1d
date: 2026-11-15
round: 1
tier: "one fresh reviewer on Claude Opus, every lens. Four minors, so no second round"
verdict: clean
---

# Review: Drive gains and tracking error

Read from the branch's diff against `main` at `2532cc9` (16 files, about 1,470 lines with the plan) by one fresh
reviewer, read only, against the approved plan `docs/plans/2026-11-15-drive-gains.md` and Isaac Sim 6.2's
`Articulation` source on disk. Four minors: three fixed in `1ae8355`, one by the live run below.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/robot.py` `_held_by_physics` | A written joint the first articulation holds no DOF for (another robot's under `prim_path`) went to the view write, whose `dof_names.index` raised after USD was written: a 500 | fixed: left out of the view write, answered "the articulation at ... holds no DOF named ..." (`test_a_joint_the_articulation_holds_no_dof_for_is_written_and_said_so`) |
| F2 | minor | `_held_by_physics`, `_drive_lines` | Stopped, each joint repeated the read's error, and the tool's stopped note could never show | fixed: one `in_simulation_note` for the call (`test_without_a_physics_view_...`, the tool test on the handler's real shape) |
| F3 | minor | docs | `TOOLS.md`'s examples and the step's source line, `ARCHITECTURE.md`'s route table and robot paragraph, the README's Robots row | fixed |
| F4 | minor | the plan | Step 1's Kit check and the live result unrecorded | fixed: the plan's Progress and the live run below |

**Refuted:** the `_existing_drive` refactor (same loop and test); the getters' tuple returns and `.numpy()` on each;
`_write_through_view`'s shapes and `dof_indices` (broadcast to one DOF on both backends); `_took`'s tolerance;
NaN and infinity (null, then the empty refusal, and `allow_inf_nan`); an older extension's answer (guarded by
`"targets" in r`); `unlimited` at 1e30; the fixture against `DriveValues`; the main thread; the units.

**Not covered:** harness integrity (no harness file); bridge security lightly (the new route sits in the same
token-checked table).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | 15.19's settle loop says whether it settled | taken |
| I2 | 15.19 asserts the wheel step's status before indexing it | taken |
| I3 | `JOINT_UNITS`: kd is per rad/s, not per radian | taken |
| I4 | Reflow `get_robot_info`'s cut-short docstring line | taken |
| I5 | `_took` already counts two values past 1e30 as equal (done with F1); the tool's line for a `max_force` at float32's top is `unlimited` | taken |

## Live run

On Isaac Sim 6.2.0-rc.14 (Kit 110.4.0), headless `isaacsim.exp.base.kit`, Windows 11, port 8212, Z-up, with
`--/rtx/hydra/supportMultiTickRate=false`, the bridge from this branch's worktree with F1 and F2's fixes on disk,
2026-11-15, started by another session:

- `test_scenarios.py`: 135 of 137. 15.19 passed: `panda_joint2` held out at 60 degrees settled 0.4343 rad from its
  target at kp 300 per radian and 0.0011 rad at kp 30000, the stiffness read back from physics both times; the jetbot's
  wheels read `tracking_error none`. 15.17 and 15.18 (#198) passed. 14.05 failed on the old `pos=` line format it
  matched, updated since (`1ae8355`, test only). 26.03 failed as on `main` (#211).
- `test_integration.py`: started, then stopped by Claude Code when the PC ran critically low on memory (another
  session's work beside this Kit); not run to its end. The joint and step paths it shares with the scenarios ran there.
- Not shown: whether a paused simulation took the USD write without the view (the answer's `through_view` wasn't
  printed); Isaac Sim 5.1; a prismatic drive's units live.
