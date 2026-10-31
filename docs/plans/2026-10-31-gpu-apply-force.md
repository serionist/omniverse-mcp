---
title: Push bodies through PhysX's tensor API under the Direct GPU API
issue: "#68"
status: approved
approved_by: serionist
approved_at: 2026-10-31
---

# Push bodies through PhysX's tensor API under the Direct GPU API

## Goal

With GPU dynamics and `/physics/suppressReadback` true, PhysX's Direct GPU API, which Isaac Sim's
`SimulationManager.set_device("cuda:N")` turns on, `apply_force` pushes the body. Today it is refused there (#58's
stopgap): `IPhysxSimulation.apply_force_at_pos` returns and moves nothing under that API, a lone body included (#58's
E8), while PhysX's tensor API, `omni.physics.tensors`' `RigidBodyView`, pushes it exactly.

- **In scope:** under the Direct GPU API, a force or an impulse, at a given world point or at the body's centre of
  mass, on a lone rigid body or an articulation's link, through the tensor API; the refusals that still hold there
  (the simulation stopped, a disabled or kinematic body, a body PhysX doesn't hold, one a fixed joint holds to the
  world); the docs that say it is refused.
- **Out of scope:**
  - the CPU pipeline, where today's call pushes bodies and links exactly in any Kit app with `omni.physx` (#58's E1),
    and stays;
  - GPU dynamics with readback on (`suppressReadback` false), unmeasured: step 1 measures it, and Q4 decides;
  - torques, and pushing several bodies in one call.

## What the code and the sources say

The code, at `a94ef03`:

| # | What | Where |
|---|---|---|
| C1 | `handle_apply_force` reads `/physics/suppressReadback` and, when true, refuses before reading the pose: `refusal(..., direct_gpu=True)` names #68 and says to turn the setting off | `handlers/simulation.py`, `core/force.py` `refusal` |
| C2 | The centre of mass comes from `get_physxunittests_interface().get_mass_information` and the pose from `get_rigidbody_transformation`; `world_point(position, rotation_xyzw, local)` turns a body-frame point into a world one, the quaternion in x, y, z, w order | `handlers/simulation.py`, `core/force.py` |
| C3 | The answer's `method` is `"physx"`; the server prints it when the answer has no `at` (a 0.2.0 extension) | `handlers/simulation.py`, `tools/simulation.py` |
| C4 | The refusal is in the tool's description, TOOLS.md's refusals table, the README's known limits and the `simulate` skill | `tools/simulation.py:145`, `docs/TOOLS.md:943`, `README.md:264`, `plugin/skills/simulate/SKILL.md:35` |

The sources, `omni.physics.tensors` 110.4.4 (Isaac Sim 6.2), and #58's measurements
(`2026-10-30-articulation-link-force.md`):

| # | Fact | Source |
|---|---|---|
| S1 | `create_simulation_view(frontend_name, stage_id=-1, backend="physx")`; frontends `numpy`, `torch`, `tensorflow`, `warp`. numpy can't take a GPU pipeline; warp needs `omni.warp.core`, which Kit ships | `api.py` line 13; #58's alternatives table |
| S2 | `RigidBodyView`: a lone body or an articulation's link. `apply_forces_and_torques_at_position(force_data, torque_data, position_data, indices, is_global)`, `(count, 3)` arrays; forces only, no impulse mode; without points it pushes at the body's origin | `api.py` 3461-3533; #58 fact 4 |
| S3 | `get_transforms()` is `(count, 7)`: x, y, z, then the quaternion qx, qy, qz, qw, in the global frame. `get_coms()` is `(count, 7)`: the centre of mass and its principal axes in the body prim's frame | `api.py` 3287-3313, 3584-3615 |
| S4 | `create_rigid_body_view(pattern)` matches globs per path component; a USD prim name holds no glob character, so a prim's own path matches it alone (#58's E9: one row for `/World/G1/pelvis`) | `api.py` 287 |
| S5 | A force lasts one physics step (E3); an impulse as impulse / dt for one step is exact (E2); a push while paused lands on the next step (E4); a view of our own per push, invalidated straight after, costs 0.016 ms and leaves Isaac Sim's own view valid (E5) | #58's E2 to E5 |
| S6 | Under the Direct GPU API the tensor push lands: +10 N s on a lone cube and on a link, +0.16667 for a 10 N force over one step (E8) | #58's E8 |
| S7 | Isaac Sim's `SimulationManager` makes a warp view at play and drops it at stop; `set_device("cuda:N")` turns on GPU dynamics and `suppressReadback` | #58 fact 7 |

Unknowns, settled by step 1's probe on Isaac Sim 6.2 headless with `set_device("cuda:0")`, each written here as E12
on, after #58's E1 to E11:

| # | Unknown | How the probe settles it |
|---|---|---|
| U1 | `get_transforms` and `get_coms` under the Direct GPU API: the body's pose and centre of mass | A cube whose centre of mass is moved off its origin (`MassAPI.centerOfMass`), turned 90 degrees: the point built from both rows against the expected one; a push there gives no spin |
| U2 | The step's length for an impulse: the physics scene's `timeStepsPerSecond`, or Isaac Sim's `SimulationManager.get_physics_dt()`, with substeps | Both read, then a 10 N s impulse as impulse / dt; the momentum change, from the tensor API's velocities and masses, is 10 |
| U3 | A warp array on the view's device for the data, and the indices as uint32 | The push lands with arrays made on `view.device` |
| U4 | GPU dynamics with readback on: does today's call push? | Today's call on a lone cube there; the momentum change; the view's `device_ordinal` |
| U5 | The setting true on a CPU scene, as a stage opened after a GPU device can leave it (`core/force.py`'s comment on `direct_gpu`; #58's code review): does the tensor push land, on a view whose device is the CPU? | A stage opened after `set_device("cuda:0")`, its scene on the CPU, the setting still true: the tensor push and its momentum change; `device_ordinal` |
| U6 | The CPU pipeline after the probe's `set_device("cpu")`: Fabric stays on and USD write-back off (`SimulationManager.enable_fabric`, which the CPU branch doesn't undo) | Today's call on a lone cube, and the cube's pose read through USD, before and after; how much of the switch a restart alone undoes |

### Live: E12 to E17

Step 1's probe, 2026-10-31, on Isaac Sim 6.2.0 headless (pip, Windows, RTX 5090), a fresh Kit, #58's helpers: a
5 kg cube with gravity off, `/World/Offset`, turned 90 degrees about Z, its centre of mass at (0.1, 0, 0) in its own
frame; the measure is the momentum from the tensor API's velocities and masses, as in #58.

| # | What | Result | So |
|---|---|---|---|
| E12 | U1, on the Direct GPU API (`set_device("cuda:0")`: device `cuda:0`, `suppressReadback` true, the scene's `physxScene:enableGPUDynamics` true, `updateToUsd` false) | The view of `/World/Offset`: one row, its own path. `get_transforms` (-15, 0, 5) with the quaternion (0, 0, 0.7071, 0.7071); `get_coms` (0.1, 0, 0); the centre of mass built from both, (-15, 0.1, 5), as expected | `tensor_centre_of_mass` from the two rows works there |
| E13 | U2: the step | `physxScene:timeStepsPerSecond` 60, the scene's step 1/60 and Isaac Sim's `get_physics_dt()` 1/60 alike. 10 N s as a force of 10 / dt for one step, at the centre of mass: momentum 0 to 10.0, angular velocity 0 before and after | the impulse as one step's force is exact, and a push at the centre of mass doesn't turn the body |
| E14 | U3: the force and the point as `(1, 3)` float32 and the indices as uint32, made on the view's device, on a view of our own invalidated after | +10.0 again (10 to 20), no turn | the handler's arrays as designed |
| E15 | U4: GPU dynamics with readback on (`set_device("cuda:0")`, then `suppressReadback` false) | Today's call: momentum 0 to 10.0. The view's device reads `cpu` | today's call pushes there: Q4 takes today's call |
| E16 | U5: the setting true on a CPU scene (`set_device("cpu")`, then `suppressReadback` true; `enableGPUDynamics` false) | Today's call: 0 to 10.0; the tensor push too, 10 to 20, on a view whose device is `cpu` | today's call pushes there too: under Q1 the tensor path isn't needed, and the old refusal of the setting alone goes |
| E17 | U6: the CPU pipeline after `set_device("cpu")` | `suppressReadback` false, but `updateToUsd` and `updateVelocitiesToUsd` stay false and `omni.physx.fabric` stays on. Today's call: 0 to 10.0; 30 frames on, PhysX has the cube at x = -9.0 and USD still at -10.0 | the switch back leaves USD stale, as P1 said: the GPU test needs a Kit of its own, restarted after (Q6) |

**What it settles:** today's call moves nothing only with both `suppressReadback` and GPU dynamics on (#58's E8 against
E15 and E16). So the tensor path is taken when `/physics/suppressReadback` is true and the physics scene's
`physxScene:enableGPUDynamics` is true, read the way the step is; every other case keeps today's call, the setting on
its own included, which is no longer refused. Q4 and Q7 resolve that way, under Q1.

## Design

### The Kit-free core, `core/force.py`

- `gpu_dynamics(stage)`: whether the stage's physics scene has `physxScene:enableGPUDynamics` true, read by name.
- `refusal(...)` loses `direct_gpu`; a new `gpu_unavailable: str | None` refuses with that reason, naming #68, when the
  tensor path can't run (no `omni.physics.tensors`, no warp). Under the Direct GPU API the `held` fact comes from the
  view's count instead of the pose.
- `one_step_force(force, impulse, dt) -> Vec3`: the force as given, or the impulse over one step, `force / dt`; a
  ValueError for a step that isn't a positive finite number.
- `tensor_centre_of_mass(transform7, com7) -> Vec3`: the world point of the centre of mass from the two rows (S3), by
  `world_point` with the row's quaternion, already in x, y, z, w order.
- `step_seconds(stage)`: the step's length from the stage's physics scene, `1 / physxScene:timeStepsPerSecond`, read by
  the attribute's name (the core imports only `pxr`, and `PhysxSchema` is Kit's), 60 steps a second when it is unset
  or there is no scene, as PhysX defaults; the first scene in stage order when there are several, which the answer
  names. A step that isn't a positive finite number is a ValueError. U2 confirms this is the step PhysX takes,
  substeps included.
- `refusal`'s order stays: the stopped timeline, then `gpu_unavailable`, then the body's own attributes, then `held`.

### The handler, `handlers/simulation.py`

Under the Direct GPU API `handle_apply_force` takes a path of its own, after the same checks of the request, the prim,
the timeline, the body's own attributes and the stage's fixed joints:

1. Import `omni.physics.tensors` and `warp`; either missing refuses with the reason (Q3). Read the step,
   `step_seconds(stage)`, here, before any tensor call: a ValueError from it answers "the physics scene's step
   can't be used: <why>", not as PhysX's.
2. `create_simulation_view("warp", stage_id)`, then `create_rigid_body_view(prim_path)`. A view whose count isn't 1,
   or whose `prim_paths[0]` isn't the prim, refuses as "PhysX holds no rigid body", as today's pose check does.
3. The point: the given one, or `tensor_centre_of_mass` from `get_transforms` and `get_coms`, both read to the host
   (`.numpy()`): `get_coms` lives on the parameters' device, the CPU, and `get_transforms` on the simulation's.
4. The force: `one_step_force` with step 1's step.
5. `apply_forces_and_torques_at_position(force, None, point, indices, is_global=True)`: the force and the point as
   `(1, 3)` float32 and the indices `[0]` as uint32, made on `view.device`.
6. `invalidate()` on the view in a `finally`, as E5 measured harmless.

The tensor API raises a bare `Exception` ("Failed to create simulation view", "Failed to get rigid body transforms",
"Failed to apply forces and torques at pos in backend"), and `create_rigid_body_view` may raise where nothing matches.
So the path catches `Exception` around steps 2 to 5 only, answers "PhysX's tensor API could not push <path>:
<why>", and logs the traceback, since the same catch would hide a slip of ours in the arrays or the point; the CPU
path's catch stays as it is.

Which path a push takes (E15, E16): the tensor path when `/physics/suppressReadback` is true and the physics scene's
`physxScene:enableGPUDynamics` is true, read by `core/force.py` the way the step is; today's call in every other
case, the setting on a CPU scene included, which is no longer refused.

The answer is today's, with `"method": "tensor"`; the CPU path keeps `"physx"`. Nothing awaits between reading the pose
and the push, as today.

### Alternatives

| Alternative | Why not |
|---|---|
| The tensor API for every push | Today's call is exact on the CPU pipeline in any Kit app with `omni.physx`, with no frontend to load (#58's E1, E10). The tensor path adds warp and the step's length, for no gain there |
| Turn `suppressReadback` off for the push | It is the user's pipeline setting, read by PhysX at play; changing it mid-run is unsupported and would slow every step after |
| Isaac Sim's own `SimulationManager` view | 6.2 exposes it, 5.1 keeps it private, and other Kit apps have none (S7) |
| The torch frontend | Torch isn't in every Kit app; warp ships with Kit |
| Set the velocity for an impulse, `v += J / m` | Exact only at the centre of mass: a push at another point also spins the body, which a force over one step gives for free (E2) |

## Compatibility

No one-way door moves: the tool's name, schema and annotations are as they are; `tests/fixtures/mcp-tools.json`
stays. The route's body is unchanged; its answer's `method` can now be `"tensor"`.

- **Users notice:** a push under the Direct GPU API that was refused now moves the body.
- **Mixed releases:** a new server on an older extension gets the refusal; the description changes only in what it
  says of the Direct GPU API.
- **Kit apps:** live on Isaac Sim 6.2 only. Isaac Sim 5.1 has the same tensor signature (#58 fact 4), untried live.

## Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | The tensor path only under the Direct GPU API, or for every push | Only there: today's call is exact elsewhere | As recommended (2026-10-31) |
| Q2 | The frontend | warp: Kit ships it | As recommended (2026-10-31) |
| Q3 | Under the Direct GPU API without `omni.physics.tensors` or warp | Refuse as today, saying which is missing | As recommended (2026-10-31) |
| Q4 | GPU dynamics with readback on | Decided by U4: the tensor path there too if today's call moves nothing, else today's call | As recommended (2026-10-31) |
| Q5 | The answer's `method` for the new path | `"tensor"`, so a caller and the logs can tell the paths apart | As recommended (2026-10-31) |
| Q6 | The live test switches the Kit app to the GPU device, which `set_device("cpu")` can't fully undo (Fabric stays on, USD write-back off): in the default live run, or only when asked | Only when asked: `OMNIVERSE_MCP_GPU=1` with `OMNIVERSE_MCP_SIM=1`, on a Kit of its own, restarted after; the default suites never change the device | As recommended (2026-10-31) |
| Q7 | The setting true on a CPU scene | The tensor path, if U5 shows the push lands; otherwise today's refusal, which says how to turn the setting off | As recommended (2026-10-31) |

## Steps

1. **Probe** U1 to U6 live in one Kit session (a scratch script through `execute_script`, run by the maintainer's
   session on its own Kit), and write E12 on into this plan. A result that breaks the design comes back to the
   maintainer first.
2. **The core:** `one_step_force`, `tensor_centre_of_mass`, `step_seconds` and the new `refusal`, with unit tests in
   `tests/test_force.py`.
3. **The handler's GPU path,** with a new `tests/test_force_handler.py` that loads `handlers/simulation.py` from its
   file with Kit's modules, `omni.physics.tensors` and warp faked in `sys.modules`, as
   `tests/test_recording_handler.py` does. No test covers `handle_apply_force` today, so it pins the CPU path too
   (`"method": "physx"`, its refusals) before the handler splits. The GPU path: the push's arrays, their dtypes and
   device, the point, the step, the view invalidated after a failure, view creation that raises, a view of the wrong
   count, each refusal.
4. **The live test,** a module of its own, `tests/test_gpu_force.py`, marked `gpu` and `sim` (Q6):
   - `tests/conftest.py`'s collection hook is reordered so the rule for `gpu` holds whatever `OMNIVERSE_MCP_SIM` is:
     a `gpu` test runs only with `OMNIVERSE_MCP_SIM=1` and `OMNIVERSE_MCP_GPU=1`, and with `OMNIVERSE_MCP_GPU=1`
     every other live test skips, so a GPU run has its Kit to itself; `gpu` joins `pyproject.toml`'s markers, as
     `strict_markers` asks. The branch takes `main` first, for #94's guard in the same file: being marked `sim`, the
     module is covered by it, and a Kit the switch leaves unanswering ends the run at its first timeout;
   - its first test checks the Kit is on the CPU pipeline (`/physics/suppressReadback` false), so a Kit left on the
     GPU by an earlier run fails at once, with what to do;
   - then, in Kit, `warp.get_cuda_device_count()` and `SimulationManager`'s import: none skips the module before any
     setting changes;
   - then `set_device("cuda:0")`, a lone cube and a two-body articulation built in the module, a force and an
     impulse, at a point and at the centre of mass, each checked by its momentum change, measured as
     `test_scenarios.py`'s phase 15 does. Its helpers are `TestScenarios`' methods (`_force_body`, `_force_pair`,
     `_physx_pose`, `_speed_along_x`, `_physics_step`, `_start_physics`, `_run_frames` and the rest, with
     `_SPEED_ALONG_X` and `_RUN_FRAMES`), so they move to a mixin, `PhysicsChecks` in a new `tests/physics_checks.py`,
     which both classes inherit; the scenarios' 31 calls stay as they are. `_physics_step` stays the live check's
     own, apart from the `step_seconds` it checks;
   - its cleanup stops the timeline and calls `set_device("cpu")`; CONTRIBUTING says to restart Kit after it (U6).
5. **Docs,** below.
6. **finish-work:** `uv run tools/gate.py full`, `review-code` until clean, the live runs above, the PR.

## Tests

- **Unit (CI):** the core's helpers and refusal; the handler's GPU path on fakes, including a view of the wrong count,
  a missing module, and an invalidate after an exception.
- **Live (by hand, Isaac Sim 6.2):** step 4's module on a fresh Kit with `OMNIVERSE_MCP_GPU=1`; both suites whole on
  another fresh Kit, on the CPU pipeline, so nothing changes there.
- **Not shown:** Isaac Sim 5.1 and other Kit apps; more than one GPU; the newton backend.

## Docs

- `src/omniverse_mcp/tools/simulation.py`: the description's sentence on the Direct GPU API.
- `docs/TOOLS.md`: the refusals table loses its Direct GPU row; `apply_force`'s section says how it pushes there; its
  Returns line names `method` `tensor` beside `physx`; the `dt` row says where the step's length comes from.
- `CONTRIBUTING.md`: `OMNIVERSE_MCP_GPU=1`, which runs the GPU module alone, and to restart Kit after it.
- `AGENTS.md`'s table: `tests/physics_checks.py`, within its 150 lines.
- `README.md`: the known limit goes.
- `plugin/skills/simulate/SKILL.md`: the line on the Direct GPU API.
- `docs/ARCHITECTURE.md`: the module list's `force.py` entry.
- `CHANGELOG.md`, Fixed: `apply_force` pushes under the Direct GPU API, with "The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit", as #58's line has it (#68).

## Risks

| Risk | Answer |
|---|---|
| The live test leaves Kit on the GPU pipeline, with Fabric on and USD write-back off, which `set_device("cpu")` doesn't undo | It runs only when asked, on a Kit of its own, restarted after (Q6); U6 measures what the switch back leaves |
| The step's length differs from the one PhysX uses (substeps, Isaac Sim's own dt) | U2 measures it; the impulse's momentum check in the live test catches a wrong one |
| Warp's API or the tensor API changes in later Kit versions | The imports and the view sit in one function, and a failure answers an error naming PhysX's tensor API; accepted |
| A view of our own while Isaac Sim's runs | E5 measured it harmless on 6.2; the live test pushes during play with Isaac Sim's view live |

## Plan review

### Round 1

**How:** one fresh reviewer on Claude Sonnet, 2026-10-31, on `0a96a2f`, reading the plan, #58's plan, the code it
names and the installed tensor API and `SimulationManager`. **Verdict:** needs-fixes (one major). **Now:** every
finding folded into the plan; Q6 and Q7 wait for the maintainer.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | The live class's cleanup, `set_device("cpu")`, doesn't undo `set_device("cuda:0")`: the GPU branch turns Fabric on and USD write-back off (`enable_fabric`), and the CPU branch turns neither back, so every test after it in the same Kit could read stale poses through USD. Checked in `simulation_manager.py` by the author | fixed, pending Q6: the live test is a module of its own, run only with `OMNIVERSE_MCP_GPU=1` on a Kit of its own, restarted after; U6 measures what the switch back leaves |
| P2 | minor | The tensor API raises a bare `Exception`, which the handler's catch of `AttributeError`, `RuntimeError`, `TypeError` and `KeyError` lets through | fixed: the tensor path catches `Exception` around its steps 2 to 5 only, and a handler test makes view creation raise |
| P3 | minor | The setting true on a CPU scene, which a stage opened after a GPU device can leave, was neither designed nor measured | fixed: U5 probes it, Q7 decides |
| P4 | minor | If U4 shows today's call moves nothing under GPU dynamics with readback on, the plan had no way to tell GPU dynamics | fixed: the scene's `physxScene:enableGPUDynamics`, read as the step is, in that case |
| P5 | minor | Which physics scene gives the step's length, with none or several, was unsaid | fixed: `step_seconds(stage)`, the first scene in stage order, 60 steps a second without one or unset |
| P6 | minor | `tests/test_simulation_handler.py` doesn't exist, and nothing tests `handle_apply_force`'s CPU path, which step 3 splits | fixed: a new `tests/test_force_handler.py` in `test_recording_handler.py`'s pattern, pinning the CPU path too |
| P7 | minor | The live test's file, its CUDA check and its place against `TestColdCook` were unsaid, and the live force tests' helpers are in `test_scenarios.py` | fixed: `tests/test_gpu_force.py`, a Kit-side CUDA check before any setting changes, the helpers moved to `tests/conftest.py` |
| P8 | minor | Docs: CHANGELOG's line on installing the extension, TOOLS.md's `method` and `dt` rows, CONTRIBUTING | fixed: in Docs |

Refuted: the frontend's device, the indices' dtype, `is_global` and the arrays' shapes against `api.py`; `get_coms`
and `get_transforms` on different devices (both read to the host before the push, now said); the quaternion's order;
glob characters in a prim path; stale `get_rigidbody_transformation` or `get_mass_information` on the GPU path, which
the design no longer reads there; the refusals before the GPU path, which read no PhysX state; the impulse as one
step's force; a view of our own beside Isaac Sim's; a tool-contract change; the writing rules.

Owner calls: Q6 and Q7, in Decisions for the maintainer.

Improvements:

| Improvement | Answer |
|---|---|
| Say the point is read to the host before the push, so "on the view's device" covers the push's arrays only | taken |
| Record the view's `device_ordinal` in step 1's probe, which settles U4 and U5 in the same run | taken |
| Number the probe's results after #58's E1 to E11 | taken: E12 on |
| A unit test that `refusal`'s order stays the same with `gpu_unavailable` | taken, in step 2 |

### Round 2

**How:** one fresh reviewer on Claude Sonnet, 2026-10-31, on `b1451f2`, reading the plan against round 1's table,
`tests/conftest.py` on the branch and on `main` (with #94), `tests/test_scenarios.py`, `pyproject.toml` and Isaac Sim's
`simulation_manager.py` and `physics_scene.py`. **Verdict:** needs-fixes (minors only), then needs-answers once they
are folded in. **Now:** P9 to P12 folded in; no further round, as none is a blocker or a major.

P1 to P8 settled as written, P1 pending Q6: the design no longer depends on `set_device("cpu")` undoing anything.

| # | Sev | Finding | Status |
|---|---|---|---|
| P9 | minor | The collection hook returns early when `OMNIVERSE_MCP_SIM=1`, so a `GPU` rule after it never runs: a plain `uv run pytest` with `SIM=1` would collect the GPU module and switch the maintainer's Kit to the GPU. A new marker needs `pyproject.toml`'s list under `strict_markers` | fixed: a `gpu` marker, the hook reordered so its rule holds whatever `SIM` is, `GPU=1` running the GPU module alone; the marker listed in `pyproject.toml`; the branch takes `main` first for #94's guard, which covers the module through `sim` |
| P10 | minor | A bad step from `step_seconds` fell inside the tensor block's catch and read as PhysX's failure | fixed: the step is read before any tensor call, with its own message; the catch logs the traceback |
| P11 | minor | Isaac Sim's `PhysicsScene.get_dt()` gives 60 only with `PhysxSceneAPI` applied and the attribute unset, and 1/1000 without the API, so "as Isaac Sim's own get_dt does" was wrong | fixed: dropped; the attribute's name and PhysX's default of 60 stand |
| P12 | minor | Phase 15's helpers are `TestScenarios`' methods, with 31 calls, not functions to move to `tests/conftest.py` | fixed: a `PhysicsChecks` mixin in `tests/physics_checks.py` that both classes inherit; `_physics_step` stays the live check's own |

Refuted: reading `physxScene:timeStepsPerSecond` by name or its default of 60 being wrong; `set_device("cpu")`
leaving `suppressReadback` on; the catch of `Exception` hiding a cancellation, which is a `BaseException`;
`from .<module> import` failing in the tests' package; `strict_markers` refusing a module marked only `sim`.

Improvements:

| Improvement | Answer |
|---|---|
| The GPU module's first test checks the Kit is on the CPU pipeline, so a Kit left on the GPU fails clearly | taken, in step 4 |
| U6 in the same probe session as U1 to U5 | taken, in step 1 |

**Approved** by the maintainer on 2026-10-31, Q1 to Q7 as recommended.
