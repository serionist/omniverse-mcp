---
title: Read and write joint drive gains, with each joint's tracking error
issue: "#199"
status: draft
approved_by:
approved_at:
---

# Read and write joint drive gains, with each joint's tracking error

## Goal

A robot that oscillates, sags or never reaches its target is a drive-tuning problem, and an agent needs each joint's
gains and how far it is from its target side by side to fix it. Today `get_robot_info` shows each joint's drive type
and, from physics, its position and velocity, but no stiffness, damping, force limit, target or tracking error; its
limits come from USD in degrees beside positions in radians; gains are written one attribute at a time with
`set_prim_attribute`, in units the agent has to know (an angular drive's stiffness is per degree in USD), and whether a
playing simulation takes the change is anyone's guess. whats2000/isaacsim-mcp-server has `get_joint_config` and
`set_drive_params`, with where each value came from and whether the solver took it.

When this is done:
- **Reading:** wherever joint states are read, `get_robot_info` and `sim_control`'s `observe` (#198), each degree of
  freedom also gives its limits, position target, stiffness, damping, force limit and tracking error (target minus
  position), all from physics, in physics' units, which the answer names once.
- **Writing:** `set_joint_drives(prim_path, drives={joint: {stiffness, damping, max_force}})` takes values in those
  same units, so a value read can be written back changed, writes each joint's drive in USD, and says, per joint, what
  it wrote and what the simulation holds after it, read back.

In scope: position drives' gains and force limit; the reads above. Out of scope: velocity targets and drive types
(`set_joint_targets` and USD keep them), friction and armature (no case asks), and Newton (#198 refuses it; here the
read-back says what the simulation holds).

## Design

- **Units, settled from Isaac Sim 6.2's own source** (fit I1): `isaacsim.core.experimental.prims`' `Articulation`
  speaks per radian on both its backends (`impl/articulation.py` in 6.2.0-rc.14, cited by method, round 1, I9): the
  USD branch of `get_dof_gains` converts USD's per-degree gains by 180/pi (`1.0 / np.deg2rad(1.0 / stiffness)`) and
  `set_dof_gains`' does the inverse; `get_dof_position_targets`' and `get_dof_limits`' USD branches give radians
  (`np.deg2rad`); `get_dof_max_efforts`' has no angle in it. Isaac Sim's gain tuner ("stored per degree") and
  omni.physx's tuning guide agree, and whats2000 measured a 6.0 Franka's USD 400 / 80 as 22918.31 / 4583.66 from
  PhysX. So: angular stiffness and damping times 180/pi from USD to physics, linear ones times 1, `max_force` times 1.
  One core helper and its inverse hold the conversion, `to_usd_gain(value, angular)` and `from_usd_gain`, in
  `ovmcp/core/robot.py`, with a round-trip test (round 1, I12).
- **The read:** `handlers/robot.py`'s `read_joint_states` (shared by `/robot/joint_states` and `/sim/step` since #198)
  also reads, from the same `Articulation`, `get_dof_limits()`, `get_dof_position_targets()`, `get_dof_gains()` and
  `get_dof_max_efforts()`, each named in the existing `call` bookkeeping, so a failure says which getter failed (fit
  I5: the four date from the extension's first release, so no per-getter fallback). The tracking error is computed in
  core, `target - position`, only for a DOF whose stiffness from physics is above 0, a position drive; any other
  (a velocity-driven wheel, a damping-only or undriven joint) shows `tracking_error none`, so an agent never tunes a
  joint no position drive controls (round 1, P1).
- **The answer** (fit I8): `get_robot_info`'s joint state lines and the step's `joint.<name>` lines become
  `pos 0.1234, vel 0.0000, target 0.5236, tracking_error 0.4102, limits [-2.8973, 2.8973], kp 57296, kd 5730,
  max_force 87`. `tracking_error`, not `error`, which the step's blocks keep for failures. Each header line says the
  values are the simulation's own, and the units: radians or stage units, `kp` per radian or per stage unit, `kd` the
  same per second; and keeps today's warning that `set_joint_targets` takes degrees, unlike `set_joint_drives`, which
  takes these units (round 1, P2). A value of PhysX's own for "no limit" (infinite, or 1e30 and over, as a continuous
  joint's limits or a drive with no `maxForce` read) prints `unlimited`, unit-tested (round 1, P5). The step's
  `source` line, "the simulated state, not drive targets", becomes "read from PhysX after the last step: positions and
  velocities simulated, targets and gains what PhysX drives with" (noticed by the fit). `get_robot_info`'s description
  and its joint states header name the new columns (noticed by the fit), and say which limits are which: the Joints
  list's in degrees from USD, the joint states' in radians from physics (round 1, I10).
- **The write, a new tool** `set_joint_drives(prim_path, drives)`: `drives` maps a joint's name, as `get_robot_info`
  lists it, to any of `stiffness`, `damping`, `max_force`, **in the read's units** (fit I2), so `kp 57296` read can be
  written back doubled as `114592` with no degrees in the agent's head. Each value is finite and 0 or more, refused
  outside before the tool runs, bounds the tool contract records (round 1, P3). The handler:
  1. converts to USD's units and writes each value to the joint's existing `UsdPhysics.DriveAPI`, angular or linear
     by its type; a joint with no drive is listed as not written, "no drive: set_joint_targets gives it one" (fit I6),
     rather than given one with invented gains; the drive lookup is one helper shared with `_set_drive_target`;
  2. writes USD only (fit I3): omni.physx propagates a USD change to a running simulation ("Once simulation starts
     omni.physx listens to both USD and Fabric changes", its simulation-control guide), as Isaac Sim's own gain tuner
     writes it;
  3. after one update, reads the gains and force limit back from physics, while it holds the robot, and answers per
     joint: the values written to USD (in USD's units, said), and `in_simulation` with the values physics now holds,
     or why there are none (stopped: the next play reads USD; no physics view; not Isaac Sim). A value physics didn't
     take shows as a difference, measured, not inferred.
  Names it doesn't find are listed. Step 1 checks the paused and the playing case; in a state that doesn't take a USD
  write by the update after it, the handler also writes through the view with `set_dof_gains` and
  `set_dof_max_efforts`, one rule for both states (round 1, Q2), and the plan's Progress says so.
- **Alternatives:** gains as parameters of `set_joint_targets`, rejected: targets and gains are tuned apart, its
  `targets` would stop being required, and its list form, in joint order, has no meaning for gains. `set_prim_attribute`
  as it is, rejected: the attribute names and the per-degree arithmetic stay the agent's, which is the issue. A
  second write path through the view, rejected unless Step 1 needs it (I3).

## Compatibility

The tool contract gains a tool, `set_joint_drives`, additive (CHANGELOG's Added; `golden.py`). `/robot/joint_states`'
answer gains keys, additive; an older extension sends none and the lines show what came. A new route,
`/robot/joint_drives`; an older extension's 404 is already "older than this server". No one-way door changes.

## Steps

1. **Check on Kit** (Isaac Sim 6.2): a Franka's `panda_joint1` given stiffness through `set_joint_drives` while
   paused reads back from physics with the new value after one update, and while playing too; its read stiffness is
   USD's times 180/pi, confirming the source. The results go in this plan's Progress.
2. **Core:** the conversion and the tracking error, in `ovmcp/core/robot.py`, with `tests/test_robot.py`.
3. **Extension:** `read_joint_states`' new columns; `handle_set_joint_drives`, its route, and the drive lookup shared
   with `_set_drive_target`; handler tests in `tests/test_robot_handler.py` with a fake `Articulation` (fit I7), since
   the step's and force's handler tests replace `read_joint_states` whole.
4. **Server:** `get_robot_info`'s header, description and joint lines, the step's joint lines and `source` line;
   `set_joint_drives`; `client.set_joint_drives`; `tests/test_tools.py`; `uv run tools/golden.py`.
5. **Live:** in `tests/test_scenarios.py` phase 15, beside 15.18: a Franka's joint given a low stiffness and a
   target, stepped until its tracking error settles (the sag low stiffness leaves); then a high stiffness through
   `set_joint_drives` while paused, stepped again: the settled error shrinks, so the new gain acted, not the time
   (round 1, P4); the answer's `in_simulation` holds the new stiffness, and `get_robot_info` reads it back; a
   velocity-driven wheel (jetbot) shows `tracking_error none`. Isaac Sim 6.2, Z-up.
6. **Docs:** below.

## Tests

- Unit (CI): `tests/test_robot.py`, `tests/test_robot_handler.py`, `tests/test_tools.py`, `tests/test_contract.py`.
- Live: Step 5 on Isaac Sim 6.2.
- Neither shows: Isaac Sim 5.1's copy of `isaacsim.core.experimental.prims` (only 6.2.0-rc.14 is installed here),
  Newton.

## Docs

`docs/TOOLS.md` (`get_robot_info`'s joint lines and units, `sim_control`'s observe lines and `source` line,
`set_joint_drives`), `plugin/skills/simulate/SKILL.md` (tuning a drive: read the tracking error, change the gains,
step, read again), `CHANGELOG.md` (Added: `set_joint_drives`, the new columns; Changed: `get_robot_info`'s and the
step's joint line format and the step's `source` line, round 1, I11).

## Risks

- **A paused simulation may not take a USD write until it steps:** Step 1 checks it; the view write is the fallback,
  and the read-back says the truth either way. Open until Step 1.
- **Isaac Sim 5.1's getters** are read from 6.2's changelog and Context7, not 5.1's source: a missing one fails the
  read with the getter named. Accepted.

## Plan review

### Fit

The plan at `8cd665b`, by a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15, with the change's own question:
is a new tool the right shape, and can the units be settled from Isaac Sim's own source. Answers by the maintainer,
2026-11-15.

| # | Improvement | Answer |
|---|---|---|
| I1 | The units settled from Isaac Sim 6.2's `Articulation` source (angular gains x 180/pi, linear and force x 1, targets radians): no measurement in Step 1, the conversion unit-tested | taken |
| I2 | `set_joint_drives` takes the read's units, converting to USD itself, so a value read can be written back changed | taken |
| I3 | Write USD only and read the result back from physics after one update: `in_simulation` measured, one write path; the view write only a fallback | taken |
| I4 | Limits from physics, in radians, in the read, as the issue asks | taken |
| I5 | No per-getter `missing` list: the existing `call` naming says which getter failed | taken |
| I6 | A joint with no drive is listed as not written, not given invented gains; one drive lookup shared with `_set_drive_target` | taken |
| I7 | Handler tests in `tests/test_robot_handler.py`, which reaches inside `read_joint_states` | taken |
| I8 | `tracking_error`, not `error`, which the step's blocks keep for failures | taken |

Noticed on the way, both fixed in the plan at the maintainer's word: the step's `source` line would turn false with
targets in the joint lines (Design, the answer); `get_robot_info`'s header and description need the new columns (Design,
the answer; Step 4).

### Round 1

**How:** a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15, who checked the cited Isaac Sim source (the units
hold on both backends; the line numbers drift a few lines). **Verdict:** needs-fixes: one major, four minors, all
fixed in the plan. **Now:** P1-P5 applied; a second round on the edits follows the major.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | `tracking_error` for every DOF: a velocity-driven wheel (carter, jetbot) would read `-312.4` and an agent tune a joint no position drive controls | fixed: only where physics' stiffness is above 0, else `none`; live on a jetbot wheel |
| P2 | minor | Targets in radians beside `set_joint_targets`, which takes degrees, with today's warning dropped | fixed: both headers keep it, and say `set_joint_drives` takes the read's units |
| P3 | minor | No bounds on the gains: a negative or NaN would reach USD and PhysX | fixed: finite, 0 or more, in the contract |
| P4 | minor | Step 5's error shrinks with time even if the gain did nothing | fixed: the low-stiffness sag settles first, then the high stiffness must shrink it |
| P5 | minor | Infinite limits and an unset force limit print as `inf` or 3.4e38 | fixed: `unlimited`, unit-tested |

Refuted: "as `set_joint_targets` lists failures" (it doesn't, but the plan lists missing names itself); I7's "reaches
inside" today (Step 3 adds that test); security, the main thread, the protocol number, USD writes while playing (the
read-back measures them); limits shown twice (each line says its units; I10).

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | P1's shape: leave `tracking_error` out for DOFs without a position drive, or show `none`? | `none`: every line keeps its columns | `none`, as recommended |
| Q2 | The view-write fallback for the playing case too, if Step 1 finds a playing simulation doesn't take the USD write? | yes: one rule for both states | yes, as recommended |

| # | Improvement | Answer |
|---|---|---|
| I9 | Cite Isaac Sim's methods by name (`get_dof_gains`' USD branch), not line numbers, which already drift | taken |
| I10 | Say in `get_robot_info`'s description which limits are which (the Joints list's degrees from USD, the states' radians from physics) | taken |
| I11 | A CHANGELOG Changed line beside Added: `get_robot_info`'s state line format and the step's `source` line change | taken |
| I12 | One core `to_usd_gain` and its inverse, with a round-trip test | taken |
