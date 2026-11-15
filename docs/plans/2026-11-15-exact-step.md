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
  nothing on those updates. After the last step, one update, so Fabric and the viewport show the new state.
- **The timeline:** playing, it is paused first and the answer says so (today's `step` pauses too). Stopped, physics
  holds no bodies: Step 1 measures whether `play()` then `pause()` in one update loads physics without a step; if it
  does, the handler does that and says so; if not, a stopped timeline is refused with "play, then pause, then step".
  The timeline's time doesn't move: the answer gives physics' time stepped (`N * dt`) beside it, and the description
  says recordings and time-sampled animation don't advance.
- **Observing:** a pure core module, `ovmcp/core/observe.py`, sorts each path into `body`, `articulation` or
  `neither` from what the stage says (`RigidBodyAPI`, `ArticulationRootAPI` at or under it, through
  `ovmcp.core.robot.articulation_root`) and formats nothing Kit-bound. The handler reads bodies through one PhysX tensor
  view (`omni.physics.tensors`, `create_rigid_body_view`: `get_transforms`, `get_velocities`), the API `apply_force`'s
  tensor path already uses and which reads true under the Direct GPU API too; joints through the code
  `handle_get_joint_states` runs, moved into a function both call. A path that is neither, or that PhysX holds no body
  for, gets its reason in its own block; the steps still count.
- **Bounds:** `steps` 1 to 1000 (16.7 s of physics at 60 Hz), refused outside before the tool runs; longer runs are
  `play`, or `run_script_job`. `observe` at most 20 paths. Each in the tool contract.
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
   move a falling cube by exactly `N` steps (its velocity `g * N * dt`); whether `play()` + `pause()` in one update
   loads physics with zero steps (a physics step event counter); that the tensor view reads the cube after manual
   steps. The results go in this plan's progress notes and decide the stopped case.
2. **Core:** `ovmcp/core/observe.py` with `tests/test_observe.py`: the sorting, the bounds, the units line.
3. **Extension:** `handle_sim_step`, the route, the joint-state function shared with `/robot/joint_states`;
   `handle_sim_control` keeps `step` only as a redirect for a server that sends it (none after this).
4. **Server:** `client.sim_step`, `sim_control`'s parameters, description and answer; `tests/test_tools.py` against
   the mock bridge (answer lines, a `neither` block, `steps` given with `play` refused), `tests/test_client.py`;
   `uv run tools/golden.py`.
5. **Live:** `test_integration.py`: a cube dropped from rest, stepped 30 then 30 more, observed: velocity
   `g * 30 * dt` then `g * 60 * dt` within 1 %, the timeline still paused and its time unchanged; a Franka stepped
   with a joint target set: its joints observed move toward it. Run on Isaac Sim 6.2, Z-up.
6. **Docs:** `docs/TOOLS.md` (`sim_control`), `docs/ARCHITECTURE.md` (the route), `plugin/skills/simulate`, CHANGELOG.

## Tests

- Unit (CI): `tests/test_observe.py`, `tests/test_tools.py`, `tests/test_client.py`, `tests/test_contract.py` through
  the fixture.
- Live (`OMNIVERSE_MCP_SIM=1`): the two tests of Step 5, on Isaac Sim 6.2, Windows, Z-up.
- Neither shows: the GPU pipeline under the Direct GPU API (the tensor read is the path `test_gpu_force.py` proves
  for pushes; a stepped read there is left to that suite's next run), Kit apps without Isaac Sim (USD Composer with
  physics), Newton.

## Docs

`docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `plugin/skills/simulate/SKILL.md` (the debug loop: step, observe, adjust),
`docs/AI_GUIDE.md` where it names `sim_control`, `CHANGELOG.md` (Added: `steps`, `observe`; Changed: `step`'s meaning).

## Risks

- **Manual stepping and Kit's own loop disagree** (a stage change between steps, the timeline unpaused by someone):
  the handler checks the timeline is still paused before each batch and stops with what it stepped. Accepted.
- **Fabric and the viewport don't show the new state** after manual steps: the update after the last step is meant to
  flush them; Step 1 checks a capture after stepping shows the cube moved. Open until Step 1.
- **The stopped case** may not load without a step: then it is refused, which costs the agent one `play` and `pause`.
  Accepted.
- **Long steps block Kit:** bounded at 1000 steps and yielding every 50 ms; a scene whose single step takes over 120 ms
  can still reach the server's 120 s limit at 1000 steps; the answer's error says to use fewer. Accepted.

## Plan review

None yet.
