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
and, from physics, its position and velocity, but no stiffness, damping, force limit, target or tracking error; gains
are written one attribute at a time with `set_prim_attribute`, in units the agent has to know (an angular drive's
stiffness is per degree in USD), and whether a playing simulation takes the change is anyone's guess.
whats2000/isaacsim-mcp-server has `get_joint_config` and `set_drive_params`, with where each value came from and
whether the solver took it.

When this is done:
- **Reading:** wherever joint states are read, `get_robot_info` and `sim_control`'s `observe` (#198), each degree of
  freedom also gives its position target, stiffness, damping, force limit and tracking error (target minus position),
  all from physics, in one set of units the answer names.
- **Writing:** `set_joint_drives(prim_path, drives={joint: {stiffness, damping, max_force}})` writes each joint's drive
  in USD, in its own units, and, while physics holds the robot, sets the same values in the running simulation; the
  answer says, per joint, what was written and whether the simulation took it.

In scope: position drives' gains and force limit; the reads above. Out of scope: velocity targets and drive types
(`set_joint_targets` and USD keep them), friction and armature (no case asks), and Newton (#198 refuses it; here a
write under Newton says the simulation didn't take it).

## Design

- **The read:** `handlers/robot.py`'s `read_joint_states` (shared by `/robot/joint_states` and `/sim/step` since #198)
  also reads, from the same `isaacsim.core.experimental.prims.Articulation`, `get_dof_position_targets()`,
  `get_dof_gains()` (stiffnesses, dampings) and `get_dof_max_efforts()`: Isaac Sim 6.x's API (Context7,
  `isaacsim.core.experimental.prims` `python_api.md`). Each is read on its own, so one an older Isaac Sim lacks costs
  only its column, named in a `missing` list. The tracking error is computed in core, `target - position`, per DOF.
- **Units:** physics gives positions in radians or metres; Step 1 measures what the tensor API's gains are per (per
  radian, or per degree as USD has them) by writing a known stiffness to USD and reading it back from physics. The
  answer then gives all of a joint's values in one system, the one physics uses, said once in the header line, as
  `get_robot_info` says it for positions today.
- **The answer:** `get_robot_info`'s joint state lines and the step's `joint.<name>` lines become
  `pos 0.1234, vel 0.0000, target 0.5236, error 0.4102, kp 1000, kd 100, max_force 87`. The header says the values
  are the simulation's own, not USD's: what PhysX drives with now.
- **The write, a new tool** `set_joint_drives(prim_path, drives)`: `drives` maps a joint's name, as `get_robot_info`
  lists it, to any of `stiffness`, `damping`, `max_force`, in USD's units (per degree for angular drives, as USD and
  `set_joint_targets`' degrees have them). The handler:
  1. writes each value to the joint's `UsdPhysics.DriveAPI` (angular or linear by the joint's type), applying the API
     with today's defaults when the joint has none, as `set_joint_targets` does;
  2. when the simulation is playing or paused and Isaac Sim's articulation view is valid, also sets the same values,
     converted to physics' units, with `set_dof_gains` and `set_dof_max_efforts` for those DOFs only;
  3. answers per joint: the values written, and `applied_to_simulation: true`, or `false` with why (stopped: the next
     play reads USD; no physics view; not Isaac Sim).
  Names it doesn't find are listed, as `set_joint_targets` lists failures.
- **Alternatives:** gains as parameters of `set_joint_targets`, rejected: targets and gains are tuned apart, and its
  `targets` would stop being required. A write to USD alone, rejected: whether a playing simulation picks up a
  `DriveAPI` change is what the issue asks the answer to say, and Isaac Sim's own tuning writes through the view.

## Compatibility

The tool contract gains a tool, `set_joint_drives`, additive (CHANGELOG's Added; `golden.py`). `/robot/joint_states`'
answer gains keys, additive; an older extension sends none and the lines show what came. A new route,
`/robot/joint_drives`; an older extension's 404 is already "older than this server". No one-way door changes.

## Steps

1. **Measure on Kit** (Isaac Sim 6.2): a Franka's `panda_joint1` given stiffness 1000 per degree in USD reads back
   from `get_dof_gains` as what, so the unit is known; that `set_dof_gains` on a playing robot changes how it tracks a
   target (its error after 60 steps with low and high stiffness); that a USD write alone, while playing, doesn't. The
   results go in this plan's Progress.
2. **Core:** the tracking error and the unit conversion, with `tests/test_robot.py`.
3. **Extension:** `read_joint_states`' new columns; `handle_set_joint_drives` and its route; handler tests beside
   `tests/test_step_handler.py`'s fake Kit.
4. **Server:** `get_robot_info`'s and the step's joint lines; `set_joint_drives`; `client.set_joint_drives`;
   `tests/test_tools.py`; `uv run tools/golden.py`.
5. **Live:** in `tests/test_scenarios.py` phase 15, beside 15.18: a Franka's joint stepped toward a target with low
   stiffness, then high through `set_joint_drives` while paused; its error after the same steps shrinks, and
   `get_robot_info` reads the new stiffness back from physics. Isaac Sim 6.2, Z-up.
6. **Docs:** below.

## Tests

- Unit (CI): `tests/test_robot.py`, the handler tests, `tests/test_tools.py`, `tests/test_contract.py`.
- Live: Step 5 on Isaac Sim 6.2.
- Neither shows: Isaac Sim 5.1, whose `isaacsim.core.experimental.prims` may lack a getter (the `missing` list covers
  it), Newton.

## Docs

`docs/TOOLS.md` (`get_robot_info`'s joint lines, `sim_control`'s observe lines, `set_joint_drives`),
`plugin/skills/simulate/SKILL.md` (tuning a drive: read the error, change the gains, step, read again),
`CHANGELOG.md` (Added).

## Risks

- **The tensor API's gain units** may differ from USD's per degree: Step 1 measures them; the conversion and its test
  follow what it finds. Open until Step 1.
- **A write through the view and USD disagreeing** after a stop: the next play reads USD, which this writes too, so
  they agree. Accepted.

## Plan review

None yet.
