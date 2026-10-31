---
title: Push bodies through PhysX's tensor API under the Direct GPU API
issue: "#68"
status: draft
approved_by:
approved_at:
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

Unknowns, settled by step 1's probe on Isaac Sim 6.2 headless with `set_device("cuda:0")`, each written here as E1 on:

| # | Unknown | How the probe settles it |
|---|---|---|
| U1 | `get_transforms` and `get_coms` under the Direct GPU API: the body's pose and centre of mass | A cube whose centre of mass is moved off its origin (`MassAPI.centerOfMass`), turned 90 degrees: the point built from both rows against the expected one; a push there gives no spin |
| U2 | The step's length for an impulse: the physics scene's `timeStepsPerSecond`, or Isaac Sim's `SimulationManager.get_physics_dt()`, with substeps | Both read, then a 10 N s impulse as impulse / dt; the momentum change, from the tensor API's velocities and masses, is 10 |
| U3 | A warp array on the view's device for the data, and the indices as uint32 | The push lands with arrays made on `view.device` |
| U4 | GPU dynamics with readback on: does today's call push? | Today's call on a lone cube there; the momentum change |

## Design

### The Kit-free core, `core/force.py`

- `refusal(...)` loses `direct_gpu`; a new `gpu_unavailable: str | None` refuses with that reason, naming #68, when the
  tensor path can't run (no `omni.physics.tensors`, no warp). Under the Direct GPU API the `held` fact comes from the
  view's count instead of the pose.
- `one_step_force(force, impulse, dt) -> Vec3`: the force as given, or the impulse over one step, `force / dt`; a
  ValueError for a step that isn't a positive finite number.
- `tensor_centre_of_mass(transform7, com7) -> Vec3`: the world point of the centre of mass from the two rows (S3), by
  `world_point` with the row's quaternion, already in x, y, z, w order.
- `step_seconds(steps_per_second)`: `1 / steps_per_second` with PhysX's default of 60 when unset, if U2 shows the
  scene's attribute is what the step uses.

### The handler, `handlers/simulation.py`

Under the Direct GPU API `handle_apply_force` takes a path of its own, after the same checks of the request, the prim,
the timeline, the body's own attributes and the stage's fixed joints:

1. Import `omni.physics.tensors` and `warp`; either missing refuses with the reason (Q3).
2. `create_simulation_view("warp", stage_id)`, then `create_rigid_body_view(prim_path)`. A view whose count isn't 1,
   or whose `prim_paths[0]` isn't the prim, refuses as "PhysX holds no rigid body", as today's pose check does.
3. The point: the given one, or `tensor_centre_of_mass` from `get_transforms` and `get_coms`.
4. The force: `one_step_force` with the step from U2.
5. `apply_forces_and_torques_at_position(force, None, point, [0], is_global=True)`, the arrays on the view's device.
6. `invalidate()` on the view in a `finally`, as E5 measured harmless.

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

| # | Question | Recommendation |
|---|---|---|
| Q1 | The tensor path only under the Direct GPU API, or for every push | Only there: today's call is exact elsewhere |
| Q2 | The frontend | warp: Kit ships it |
| Q3 | Under the Direct GPU API without `omni.physics.tensors` or warp | Refuse as today, saying which is missing |
| Q4 | GPU dynamics with readback on | Decided by U4: the tensor path there too if today's call moves nothing, else today's call |
| Q5 | The answer's `method` for the new path | `"tensor"`, so a caller and the logs can tell the paths apart |

## Steps

1. **Probe** U1 to U4 live (a scratch script through `execute_script`, run by the maintainer's session on its own
   Kit), and write E1 on into this plan. A result that breaks the design comes back to the maintainer first.
2. **The core:** `one_step_force`, `tensor_centre_of_mass`, `step_seconds` and the new `refusal`, with unit tests in
   `tests/test_force.py`.
3. **The handler's GPU path,** with handler tests on a fake `omni.physics.tensors` and warp in
   `tests/test_simulation_handler.py` (or the file the force handler's tests live in): the push's arrays, the point,
   the step, the view invalidated after a failure, each refusal.
4. **The live test:** a class in `tests/test_integration.py` that turns GPU dynamics on through `SimulationManager`,
   pushes a lone cube and a link, a force and an impulse, at a point and at the centre of mass, and checks the
   momentum change; it puts the CPU device back in its cleanup, and skips without CUDA or Isaac Sim's
   `SimulationManager`.
5. **Docs,** below.
6. **finish-work:** `uv run tools/gate.py full`, `review-code` until clean, the live runs above, the PR.

## Tests

- **Unit (CI):** the core's helpers and refusal; the handler's GPU path on fakes, including a view of the wrong count,
  a missing module, and an invalidate after an exception.
- **Live (by hand, Isaac Sim 6.2):** step 4's class, and both suites whole on the CPU pipeline, so nothing changes
  there; the new class run before and after the suites.
- **Not shown:** Isaac Sim 5.1 and other Kit apps; more than one GPU; the newton backend.

## Docs

- `src/omniverse_mcp/tools/simulation.py`: the description's sentence on the Direct GPU API.
- `docs/TOOLS.md`: the refusals table loses its Direct GPU row; `apply_force`'s section says how it pushes there.
- `README.md`: the known limit goes.
- `plugin/skills/simulate/SKILL.md`: the line on the Direct GPU API.
- `docs/ARCHITECTURE.md`: the module list's `force.py` entry.
- `CHANGELOG.md`, Fixed: `apply_force` pushes under the Direct GPU API (#68).

## Risks

| Risk | Answer |
|---|---|
| The live class leaves Kit on the GPU pipeline for the tests after it | Its cleanup puts the CPU device back, and it runs last in `test_integration.py` before `TestColdCook`; accepted |
| The step's length differs from the one PhysX uses (substeps, Isaac Sim's own dt) | U2 measures it; the impulse's momentum check in the live test catches a wrong one |
| Warp's API or the tensor API changes in later Kit versions | The imports and the view sit in one function, and a failure answers an error naming PhysX's tensor API; accepted |
| A view of our own while Isaac Sim's runs | E5 measured it harmless on 6.2; the live test pushes during play with Isaac Sim's view live |

## Plan review
