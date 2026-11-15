---
title: Step physics by an exact count and read bodies and joints back in the same call
issue: "#198"
status: draft
approved_by:
approved_at:
---

# Step physics by an exact count and read bodies and joints back in the same call

## Goal

`sim_control("step")` plays the timeline for two app updates and pauses (`handle_sim_control`,
`ovmcp/bridge/handlers/simulation.py:70`). How many physics steps that is depends on the frame rate, so an agent can't
say "advance 60 steps, then tell me where the box is", and reading the result takes `get_prim_bounds` and
`get_robot_info` calls after it. Nothing reads a rigid body's velocity at all.

When this is done, `sim_control(action="step", steps=N, observe=[...])` advances physics exactly `N` steps of the
physics scene's `dt`, and answers with the state of each prim in `observe`: a rigid body's world position, rotation,
linear and angular velocity; an articulation root's joint positions and velocities, as `get_robot_info` reads them.
That is the step, look, adjust loop whats2000/isaacsim-mcp-server leads with (`step_simulation`), in one call.

In scope: exact stepping from a paused timeline (and from a stopped one, when physics can be loaded without a step;
Step 1 measures it), the observations, the docs and the `simulate` skill. Out of scope: drive gains and tracking error
(#199), which will add to the joint lines this writes; rendering each step; advancing the timeline's time.

## Design

- **A route of its own, `/sim/step`** (`handle_sim_step`, `handlers/simulation.py`), so `/sim/control` stays the
  timeline's play, pause and stop. `sim_control`'s `step` calls it; the server's client gets `sim_step(steps, observe)`.
- **Stepping** is PhysX's own manual loop, as Isaac Sim's `isaacsim.replicator.grasping` (`simulate_physics_async`)
  and `SimulationManager.step` do it: `get_physx_simulation_interface().simulate(dt, t)` then `fetch_results()`, `N`
  times, with the timeline paused, so Kit's update loop steps nothing of its own in between. `dt` is
  `ovmcp.core.force.step_seconds(stage)`, which `apply_force` already reads. Between steps the handler awaits one app
  update every 50 ms of stepping, so Kit's UI and the bridge's other requests aren't starved; a paused timeline steps
  nothing on those updates. After the last step, Fabric is flushed as Isaac Sim's `SimulationManager.step(update_fabric=True)`
  flushes it (`omni.physxfabric.get_physx_fabric_interface().update(t, dt)`, when omni.physxfabric is loaded), since
  manual `simulate()` doesn't write Fabric; then one update, so the viewport, `get_prim_bounds` and captures show the
  pose `observe` reports (fit I2). A wall-clock cap of 90 s, the limit `get_performance` stops at, ends the loop early
  with "stepped k of N" and the observations, rather than the server's 120 s timeout (fit I4).
- **The timeline:** playing, it is paused first and the answer says so (today's `step` pauses too). Stopped, physics
  holds no bodies: the handler calls `play()` and `pause()` together, then awaits one update, and steps from there (fit
  I1). whats2000 measured this load at zero steps on Isaac Sim 6.0.1, and asking the agent to play and pause in two
  calls lets physics run free between them (about 1.4 s of fall, measured there). Step 1 counts the steps the load
  takes on 6.2, Isaac Sim's own warm-up in `SimulationManager.initialize_physics` included; if any, the answer says how
  many. The timeline's time doesn't move: the answer gives physics' time stepped (`N * dt`) beside it, and the
  description says recordings, time-sampled animation and Action Graphs on playback ticks don't advance.
- **Observing:** a function beside `articulation_root` in `ovmcp/core/robot.py`, which it calls, sorts each path into
  `body`, `articulation` or `neither` from what the stage says (`RigidBodyAPI`, `ArticulationRootAPI` at or under it),
  with its tests in `tests/test_robot.py` (fit I8). The handler reads bodies through a PhysX tensor view
  (`omni.physics.tensors`, `create_rigid_body_view`: `get_transforms`, `get_velocities`), which reads true under the
  Direct GPU API too, through one helper drawn out of `apply_force`'s `_push_with_tensors` and used by both: the view
  made on warp, the body's own row found by `prim_paths` (a plain last name matches at any depth), the `invalidate()`
  in `finally`, and the message when omni.physics.tensors or warp is missing (fit I5). Joints through the code
  `handle_get_joint_states` runs, moved into a function both call. A path that is neither, or that PhysX holds no body
  for, gets its reason in its own block; the steps still count.
- **Bounds:** `steps` 0 to 1000 (16.7 s of physics at 60 Hz), refused outside before the tool runs; longer runs are
  `play`, or `run_script_job`. `steps=0` pauses if playing and reads without stepping, so a read of a moving body
  doesn't change it (fit I6). `observe` at most 20 paths. The server's `Field` limits, and one check in the handler's
  request parsing, as `force_args` does it (fit I8).
- **The answer:** the line `sim_control` gives today, then `stepped = N steps of {dt} s ({N*dt} s of physics); the
  timeline's time is unchanged`, then a prim block per observed path:
  `[/World/Box]` / `position = [...]` / `rotation = [w, x, y, z]` / `linear_velocity = [...] (stage units/s)` /
  `angular_velocity = [...] (deg/s)`, or `joint.<name> = pos ..., vel ...` lines in radians or stage units, the units
  said once, as `get_robot_info` says them.
- **Alternatives:** a new `step_simulation` tool, rejected: `sim_control` already has `step`, and a second tool for
  the same verb splits where an agent looks (fit question: a parameter on an old tool). Playing and counting physics
  step events until `N`, rejected: one update can hold several steps, so the count overshoots. `SimulationManager.step`
  alone, rejected: Isaac Sim only; `omni.physx` is in every Kit app with physics.

## Compatibility

The tool contract changes: `sim_control` gains `steps` and `observe`, and `step` changes meaning from "two updates" to
"exact physics steps, 1 by default", under CHANGELOG's Changed (the old meaning had no number anyone could rely on).
`golden.py` rewrites the fixture. The wire protocol gains `/sim/step`, additive; an older extension answers 404, which
`_bridge.py` already turns into "the Kit extension is older than this MCP server". No other one-way door.

## Steps

1. **Measure on Kit** (Isaac Sim 6.2, by hand with `execute_script`): `simulate`/`fetch_results` on a paused timeline
   move a falling cube by exactly `N` steps (its velocity `g * N * dt`); how many steps `play()` + `pause()` in one
   update takes to load physics (a physics step event counter, Isaac Sim's warm-up in `initialize_physics` included);
   that the tensor view reads the cube after manual steps, and that `get_prim_bounds` agrees after the Fabric flush.
   The results go in this plan's progress notes.
2. **Core:** the sort beside `articulation_root` in `ovmcp/core/robot.py`, tested in `tests/test_robot.py`.
3. **Extension:** `handle_sim_step`, the route, the tensor-view helper drawn out of `_push_with_tensors`, the
   joint-state function shared with `/robot/joint_states`; `handle_sim_control`'s `step` left as it is, so an older
   server gets the two updates it asked for (fit I7). Unit tests of `handle_sim_step` with
   `tests/test_force_handler.py`'s FakeKit and `load_simulation`.
4. **Server:** `client.sim_step`, `sim_control`'s parameters, description and answer; `tests/test_tools.py` against
   the mock bridge (answer lines, a `neither` block, `steps` given with `play` refused), `tests/test_client.py`;
   `uv run tools/golden.py`.
5. **Live:** a method of `tests/physics_checks.py`'s mixin, so the scenarios (phase 15) and `test_gpu_force.py` both
   run it (fit I9): a cube dropped from rest, stepped 30 then 30 more, observed: velocity `g * 30 * dt` then
   `g * 60 * dt` within 1 %, `get_prim_bounds`' centre matching the observed position within the cube's size (fit I3),
   the timeline still paused and its time unchanged; `steps=0` reads without moving it. In `test_integration.py`, a
   Franka stepped with a joint target set: its joints observed move toward it. Run on Isaac Sim 6.2, Z-up.
6. **Docs:** `docs/TOOLS.md` (`sim_control`), `docs/ARCHITECTURE.md` (the route), `plugin/skills/simulate`, CHANGELOG.

## Tests

- Unit (CI): `tests/test_robot.py` (the sort), the handler's tests beside `tests/test_force_handler.py`,
  `tests/test_tools.py`, `tests/test_client.py`, `tests/test_contract.py` through the fixture.
- Live (`OMNIVERSE_MCP_SIM=1`): the tests of Step 5, on Isaac Sim 6.2, Windows, Z-up; the cube check under the Direct
  GPU API when `test_gpu_force.py` runs (`OMNIVERSE_MCP_GPU=1`).
- Neither shows: Kit apps without Isaac Sim (USD Composer with physics), Newton.

## Docs

`docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `plugin/skills/simulate/SKILL.md` (the debug loop: step, observe, adjust),
`docs/AI_GUIDE.md` where it names `sim_control`, `CHANGELOG.md` (Added: `steps`, `observe`; Changed: `step`'s meaning).

## Risks

- **Manual stepping and Kit's own loop disagree** (a stage change between steps, the timeline unpaused by someone):
  the handler checks the timeline is still paused before each batch and stops with what it stepped. Accepted.
- **Fabric and the viewport don't show the new state** after manual steps: the Fabric flush after the last step, as
  Isaac Sim's own does it; the live test's `get_prim_bounds` check fails if a later Kit stops flushing. Resolved.
- **The stopped case's load takes steps** on some Kit: the answer says how many. Accepted.
- **Long steps block Kit:** bounded at 1000 steps, yielding every 50 ms, and capped at 90 s of wall clock with
  "stepped k of N". Resolved.

## Plan review

### Fit

The plan at `0800855`, by a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15, with the change's own question:
does reusing `sim_control` serve agents better, and is the stopped-timeline handling the simplest that works. Answers
by the maintainer, 2026-11-15.

| # | Improvement | Answer |
|---|---|---|
| I1 | From stopped, `play()` and `pause()` together, one update, then step; no refusal, which would make the agent play and pause in two calls with physics free in between | taken |
| I2 | Flush Fabric after the last step as `SimulationManager.step(update_fabric=True)` does, so bounds and captures show the stepped pose | taken |
| I3 | The live test checks `get_prim_bounds` against the observed position, replacing a by-hand capture check | taken |
| I4 | A 90 s wall-clock cap answering "stepped k of N" instead of the server's timeout | taken |
| I5 | One tensor-view helper drawn out of `_push_with_tensors` for both handlers (the leaf-name match, `invalidate()`, the missing-extension message) | taken |
| I6 | `steps` from 0: pause and read without stepping | taken |
| I7 | Leave `/sim/control`'s `step` as it is, no redirect | taken |
| I8 | No `core/observe.py`: the sort beside `articulation_root` in `core/robot.py`, bounds as `force_args` checks them | taken |
| I9 | The cube test in `tests/physics_checks.py`'s mixin, so the GPU suite runs it too | taken |

Noticed on the way, for Round 1: Compatibility (the title doesn't name the contract and route change; `step`'s meaning
belongs under Breaking; no maintainer agreement in the issue); Design, Observing (a prim both a rigid body and the
articulation root, such as the G1's pelvis, gets one block); Design and Risks (under Newton, omni.physx's `simulate`
advances nothing); Design (Action Graphs on playback ticks don't run during manual steps); Design, The answer (the
issue asks where each value came from); Design, Observing (no stated answer without omni.physics.tensors or warp);
Steps 3 (no unit test of `handle_sim_step`); Docs (`test_project/scenarios.md` 5.2, `test_project/AGENTS.md:55`,
`test_project/assistant.md:19`, `docs/TOOLS.md:1283`, `:854`, `:1533`, raycast's description, `plugin/skills/script`,
`docs/AI_GUIDE.md:47`); Tests (Isaac Sim 5.x not run).
