---
title: Step physics by an exact count and read bodies and joints back in the same call
issue: "#198"
status: approved
approved_by: serionist
approved_at: 2026-11-15
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

In scope: exact stepping from a paused, playing or stopped timeline, the observations, the docs and the `simulate` skill. Out of scope: drive gains and tracking error
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
  holds no bodies: the handler calls `play()`, `commit()`, `pause()` and `commit()` again, then awaits one update, and steps from there
  (fit I1); the commit applies the play at once, as Isaac Sim's own `play(commit=True)` does before tensor reads, so
  the load doesn't rest on when Kit applies the timeline's changes (round 1, I10). `steps=0` from stopped loads physics
  the same way and reads (round 1, I11). whats2000 measured this load at zero steps on Isaac Sim 6.0.1, and asking the agent to play and pause in two
  calls lets physics run free between them (about 1.4 s of fall, measured there). Step 1 counts the steps the load
  takes on 6.2, Isaac Sim's own warm-up in `SimulationManager.initialize_physics` included; if any, the answer says how
  many. The timeline's time doesn't move: the answer gives physics' time stepped (`N * dt`) beside it, and the
  description says recordings, time-sampled animation and Action Graphs on playback ticks don't advance.
- **Observing:** a function beside `articulation_root` in `ovmcp/core/robot.py`, which it calls, sorts each path into
  what it holds, a set of `body` and `articulation`, empty for neither, from what the stage says (`RigidBodyAPI`, `ArticulationRootAPI` at or under it),
  with its tests in `tests/test_robot.py` (fit I8). The handler reads bodies through a PhysX tensor view
  (`omni.physics.tensors`, `create_rigid_body_view`: `get_transforms`, `get_velocities`), which reads true under the
  Direct GPU API too, through one helper drawn out of `apply_force`'s `_push_with_tensors` and used by both: the view
  made on warp, the body's own row found by `prim_paths` (a plain last name matches at any depth), the `invalidate()`
  in `finally`, and the message when omni.physics.tensors or warp is missing (fit I5). Joints through the code
  `handle_get_joint_states` runs, moved into a function both call. A prim that is both a rigid body and an
  articulation root, such as the G1's pelvis, gets the body lines and the joint lines (round 1, P4). A path that is
  neither, or that PhysX holds no body for, gets its reason in its own block; the steps still count.
- **Engine and overlap:** on Isaac Sim, a step is refused when `SimulationManager.get_active_physics_engine()` isn't
  `physx`: omni.physx's `simulate` advances nothing under Newton. The method is read with `getattr`, and a Kit without
  it or without `isaacsim.core.simulation_manager` counts as PhysX; Step 1 records what it reads on 6.2 (round 2,
  P8). Two `/sim/step` calls never interleave at the 50 ms yields: a second while one runs is refused at once, "a
  step is running", as the job board refuses a second job; waiting could outlast the server's 120 s and step physics
  for a caller that has gone (round 1, P7; round 2, P10).
- **Bounds:** `steps` 0 to 1000 (16.7 s of physics at 60 Hz), refused outside before the tool runs; longer runs are
  `play`, or `run_script_job`. `steps=0` pauses if playing and reads without stepping, so a read of a moving body
  doesn't change it (fit I6). `observe` at most 20 paths. The server's `Field` limits, and one check in the handler's
  request parsing, as `force_args` does it (fit I8).
- **The answer:** the line `sim_control` gives today, then `stepped = N steps of {dt} s ({N*dt} s of physics); the
  timeline's time is unchanged`, then a prim block per observed path:
  `[/World/Box]` / `position = [...]` / `rotation = [w, x, y, z]` / `linear_velocity = [...] (stage units/s)` /
  `angular_velocity = [...] (deg/s)`, or `joint.<name> = pos ..., vel ...` lines in radians or stage units, the units
  said once, as `get_robot_info` says them. The tensor view gives `[x, y, z, qx, qy, qz, qw]` and rad/s: core
  reorders the quaternion to `[w, x, y, z]`, as `get_prim_properties` gives it, and converts angular velocity to deg/s,
  both unit-tested (round 1, P5). One line says where the values come from: read from PhysX after the last step, the
  simulated state, not drive targets (round 1, P6; targets are #199's).
- **Alternatives:** a new `step_simulation` tool, rejected: `sim_control` already has `step`, and a second tool for
  the same verb splits where an agent looks (fit question: a parameter on an old tool). Playing and counting physics
  step events until `N`, rejected: one update can hold several steps, so the count overshoots. `SimulationManager.step`
  alone, rejected: Isaac Sim only; `omni.physx` is in every Kit app with physics.

## Compatibility

The tool contract changes: `sim_control` gains `steps` and `observe`, and `step` changes meaning from "two updates" to
"exact physics steps, 1 by default", under CHANGELOG's Breaking: a recording's clock and Action Graphs on playback
ticks moved with the old `step` (`docs/TOOLS.md:1283`) and don't with the new. The PR's title names the change to the
tool contract, and the maintainer's agreement is recorded in #198 (round 1, P2). `golden.py` rewrites the fixture. The wire protocol gains `/sim/step`, additive; an older extension answers 404, which
`_bridge.py` already turns into "the Kit extension is older than this MCP server". No other one-way door.

## Steps

1. **Measure on Kit** (Isaac Sim 6.2, by hand with `execute_script`): `simulate`/`fetch_results` on a paused timeline
   move a falling cube by exactly `N` steps (its velocity `g * N * dt`); how many steps `play()` + `pause()` in one
   update takes to load physics (a physics step event counter, Isaac Sim's warm-up in `initialize_physics` included);
   that the tensor view reads the cube after manual steps; Fabric's pose and `get_prim_bounds` after stepping, with
   and without the flush, so the live check below is known to catch a missing flush.
   The results go in this plan's progress notes.
2. **Core:** the sort beside `articulation_root` in `ovmcp/core/robot.py`, tested in `tests/test_robot.py`, a prim
   with both APIs (the G1's pelvis) among its cases (round 2, P9).
3. **Extension:** `handle_sim_step`, the route, the tensor-view helper drawn out of `_push_with_tensors`, the
   joint-state function shared with `/robot/joint_states`; `handle_sim_control`'s `step` left as it is, so an older
   server gets the two updates it asked for (fit I7). Unit tests of `handle_sim_step` with
   `tests/test_force_handler.py`'s FakeKit and `load_simulation`.
4. **Server:** `client.sim_step`, `sim_control`'s parameters, description and answer; `tests/test_tools.py` against
   the mock bridge (answer lines, a `neither` block, `steps` given with `play` refused), `tests/test_client.py`;
   `uv run tools/golden.py`.
5. **Live:** a method of `tests/physics_checks.py`'s mixin, so the scenarios (phase 15) and `test_gpu_force.py` both
   run it (fit I9): a cube dropped from rest, stepped 30 then 30 more, observed: velocity `g * 30 * dt` then
   `g * 60 * dt` within 1 %, Fabric's world transform of the cube (read through usdrt with `execute_script`) matching
   the observed position within the cube's size, which is what the flush writes and what a capture renders, in both
   suites; `get_prim_bounds`' centre, which reads USD, checked as well only where USD write-back is on, so not in the
   GPU suite (fit I3, round 1, P1); the timeline still paused and its time unchanged; `steps=0` reads without moving
   it, from paused and from stopped, where it allows exactly the steps the answer says the load took (round 1, I11). In `test_integration.py`, a Franka stepped with a joint target
   set: its joints observed move toward it. Run on Isaac Sim 6.2, Z-up, and the cube check on 5.1 (round 1, Q2).
6. **Docs:** the list under Docs, below, `test_project/scenarios.md` 5.2 among them (round 1, P3).

## Tests

- Unit (CI): `tests/test_robot.py` (the sort), the handler's tests beside `tests/test_force_handler.py`,
  `tests/test_tools.py`, `tests/test_client.py`, `tests/test_contract.py` through the fixture.
- Live (`OMNIVERSE_MCP_SIM=1`): the tests of Step 5, on Isaac Sim 6.2, Windows, Z-up; the cube check under the Direct
  GPU API when `test_gpu_force.py` runs (`OMNIVERSE_MCP_GPU=1`); the cube check on Isaac Sim 5.1 (Kit 107) in the dev
  server's Linux container (round 1, Q2).
- Neither shows: Kit apps without Isaac Sim (USD Composer with physics), Newton.

## Docs

- `docs/TOOLS.md`: `sim_control`; the recording clock (`:1283`), which no longer moves with `step`; "play or step the
  simulation first" (`:854`, `:1533`) and raycast's description, true still; `mcp.sim_control` (`:1722`), whose
  `step` keeps its two updates, said there (round 1, I12).
- `docs/ARCHITECTURE.md` (the route); `CHANGELOG.md` (Added: `steps`, `observe`; Breaking: `step`'s meaning).
- `plugin/skills/simulate/SKILL.md` (the debug loop: step, observe, adjust); `plugin/skills/script/SKILL.md` and
  `docs/AI_GUIDE.md:47`, which send many physics steps to `run_script_job`: up to 1000 is now a `step`.
- `test_project/scenarios.md` 5.2, which checks `time` moved by a step's two updates: it checks the step count and
  that `time` stayed; `test_project/AGENTS.md:55` and `test_project/assistant.md:19`, pointed at `steps` and `observe`
  (round 1, P3).

## Risks

- **Manual stepping and Kit's own loop disagree** (a stage change between steps, the timeline unpaused by someone):
  the handler checks the timeline is still paused before each batch and stops with what it stepped. Accepted.
- **Fabric and the viewport don't show the new state** after manual steps: the Fabric flush after the last step, as
  Isaac Sim's own does it; the live test's Fabric check fails if a later Kit stops flushing, once Step 1 shows it
  fails without the flush. Accepted until Step 1. USD tools such as `get_prim_bounds` see the stepped pose only where
  PhysX writes USD, as with any play today: the description says so. Note: `ovmcp/core/formatter.py:116` says
  BBoxCache reads through Fabric, which it doesn't; the comment is corrected in this change.
- **The stopped case's load takes steps** on some Kit: the answer says how many. Accepted.
- **Long steps block Kit:** bounded at 1000 steps, yielding every 50 ms, and capped at 90 s of wall clock with
  "stepped k of N". Resolved.

## Progress

- **Fabric's update, from omni.physx's guide** to manual stepping (`simulation_control.html`): `omni.physxfabric`'s
  `get_physx_fabric_interface().update(dt, current_time)` after each `fetch_results()`, not once after the last step
  with `(t, dt)` as Design first said; the code follows the guide.
- **The Franka check** went to `tests/test_scenarios.py` (15.18), beside phase 15's own Franka test, rather than
  `test_integration.py`, so it reuses that phase's setup.
- **Step 1, measured live** on Isaac Sim 6.2.0 (Kit 110.4, `isaacsim.exp.base.kit`, Windows, 2026-11-15), through
  the live tests rather than by hand: stepping by hand moves the cube exactly the steps asked for (its speed `g * n *
  dt` within 1 %); the load from stopped took 2 steps in three runs and 4 in one, by Isaac Sim's count, so the answer
  says how many and the live check measures from the speed the load left; `get_active_physics_engine` reads `physx`;
  omni.physx.fabric isn't loaded in that experience (`fabric = False`), and Fabric's world matrix, read through usdrt,
  still matched the stepped pose; the Franka's joint moved toward its target.

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

### Round 1

**How:** a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15; P1 checked by a second fresh agent, which
confirmed it. **Verdict:** needs-fixes. **Now:** every finding fixed in the plan; Q1, Q2 and I10-I12 answered by the
maintainer, 2026-11-15.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | The bounds check in the shared mixin fails in the GPU suite (USD write-back off, `get_prim_bounds` reads USD) and can't see the Fabric flush in either suite | fixed: Fabric's world transform checked through usdrt in both suites, USD bounds only where write-back is on; Step 1 measures with and without the flush; Risk back to Accepted; `formatter.py:116`'s comment corrected |
| P2 | minor | `step`'s new meaning breaks callers (the recording clock, `TOOLS.md:1283`; Action Graphs on ticks): Breaking, not Changed; the title and the maintainer's agreement | fixed: Compatibility |
| P3 | minor | `test_project/scenarios.md` 5.2 and other lines that name the old `step` are missing from Docs | fixed: Docs, Step 6 |
| P4 | minor | A prim both rigid body and articulation root (the G1's pelvis) gets one block | fixed: Observing |
| P5 | minor | The tensor view's xyzw and rad/s converted without the plan saying so | fixed: The answer |
| P6 | minor | The issue's "where each value came from" unmet | fixed: The answer |
| P7 | minor | Under Newton `simulate` moves nothing; two steps interleave at the yields | fixed: Engine and overlap |

Refuted: no answer without omni.physics.tensors or warp (I5 covers it); no unit test of `handle_sim_step` (Step 3 has
it); Action Graphs as a finding of its own (in P2); the route's security (same route table, same checks); the protocol
number (additive, and a 404 is already "older extension").

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Does the maintainer agree to the contract change, recorded in #198, the title naming it? | yes, under Breaking | yes; recorded in #198 |
| Q2 | Run the cube check on Isaac Sim 5.1 too? | yes, where available | yes, on the dev server's Linux container |

| # | Improvement | Answer |
|---|---|---|
| I10 | `timeline.commit()` between `play()` and `pause()` from stopped | taken |
| I11 | Say and test what `steps=0` does from stopped | taken |
| I12 | Say in `TOOLS.md` that `mcp.sim_control("step")` keeps its two updates | taken |

### Round 2

**How:** a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15, on the edits since `748df57` and Round 1's
findings. **Verdict:** approved: P1-P7 fixed, no blocker or major, the three minors below fixed. **Now:** all applied.

| # | Sev | Finding | Status |
|---|---|---|---|
| P8 | minor | `get_active_physics_engine` unconfirmed on Isaac Sim 5.1: without a fallback every step there fails | fixed: read with `getattr`, missing counts as PhysX; Step 1 records what 6.2 reads |
| P9 | minor | The sort still returns one of three, against P4's fix | fixed: it returns a set; the G1's pelvis a test case |
| P10 | minor | A queued second step can outlast the server's 120 s and step for a caller that has gone | fixed: refused at once, as a second job is |

Refuted: `steps=0` from stopped contradicting the load's steps (the check now allows exactly the count the answer
gives); `timeline.commit()` missing (it exists, and Isaac Sim's `play(commit=True)` uses it); debug-draw expiry (real
time); an older extension (404, already reported as such).

| # | Improvement | Answer |
|---|---|---|
| I13 | `commit()` again after `pause()` from stopped, so the awaited update can't step physics | taken |
