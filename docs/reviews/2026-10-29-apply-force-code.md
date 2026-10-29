---
subject: "Push apply_force through PhysX, at a point or the centre of mass (#25)"
base: main (b818449)
head: 8855653
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer, Claude Opus 5.5)
verdict: clean
---

# Review: apply_force through PhysX

PR 2 of the plan for #7 and #25 (`docs/plans/2026-10-29-debug-draw-and-ignored-parameters.md`, on PR 1's branch).
Read from the diff of `8855653` against `b818449`, the touched files in full, and the PhysX, USD and Kit stubs and
tests installed with Isaac Sim 5.1 (Kit 107.3, `omni.physx` 107.3.26) and 6.2.0 (Kit 110.4, `omni.physx` 110.4.4).
One minor, fixed; three improvements, all taken. The branch was then rebased onto `7afa9e4` (#52), whose README line
for #25 it resolves to `start_recording`'s alone: `8855653` became `1948e73`, and the fixes are `84af853`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_scenarios.py`, `test_15_11_apply_force_to_a_robot_link` | It can't tell a push PhysX took on a G1 link from one it ignored: `apply_force_at_pos` returns None either way, and the test checked only the answer. | Fixed in `84af853`: 100 N s along X on the pelvis, and the link's PhysX pose must move further along X in about 0.2 s than it does without the push (`drift_along_x`). |

Refuted, or checked and found right, each from the code or the installed source:

- **The PhysX call and its modes:** `IPhysxSimulation.apply_force_at_pos(stage_id: int, body_path: int, force:
  Float3, pos: Float3, mode: str = 'Force')`, "Force (default), Impulse, Velocity, Acceleration", the same in
  107.3.26 (`_physx.pyi` line 1254) and 110.4.4 (line 1207). `PhysX` has no such method, which is why 0.2.0 always
  took its velocity fallback.
- **The stage id:** `UsdContext.get_stage_id()`, "the UsdStage Id that can be queried with Usd.StageCache", the id
  NVIDIA's own callers build with `UsdUtils.StageCache.Get().GetId(stage).ToLongInt()`.
- **The body path:** `pxr.PhysicsSchemaTools.sdfPathToInt`, from `omni.usd.schema.physx` in both versions, as
  NVIDIA's `test_physics_kinematic_apply_force` calls it.
- **The pose's order:** `get_rigidbody_transformation` gives `rotation` as "quat - x,y,z,w" (107.3.26 line 1656,
  110.4.4 line 1609); `world_point` reads it so, and its unit tests turn a point a quarter about Z and Y and a half
  about X.
- **`com`'s frame:** NVIDIA's mass tests scale the expected centre of mass by the prim's scale before comparing
  (`massTestBase.py`), so it is in the body's frame as PhysX holds it, which the pose maps to world;
  `test_15_08` checks the point lands 0.15 off the origin for 0.5 authored on a 0.3-scaled cube.
- **The world-point maths:** `v + 2w (u x v) + 2 u x (u x v)` for a unit quaternion, normalised first; a zero
  quaternion is an error.
- **The refusal order:** stopped first, since PhysX holds no bodies then and the rest says nothing; then what the
  prim says of itself; then whether PhysX holds it.
- **No Python callback:** `get_mass_information` is synchronous; `query_prim`, whose callbacks Kit may call from a
  worker thread (#5), is not used. Nothing awaits between the pose, the centre of mass and the push.
- **The contract:** only descriptions moved, which `tools/golden.py` strips; `tests/fixtures/mcp-tools.json` is
  unchanged and `tests/test_contract.py` passes.
- **The live tests:** each fails on `main`, whose handler answers success with `method: velocity` and no `at` for
  every one of them, and moves nothing through PhysX; each leaves the stage as it found it, its own body deleted
  and the simulation stopped, in `addCleanup`.

Improvements:

| Improvement | Answer |
|---|---|
| Name the way to hold a push over MCP, where one call can't last past a physics step | taken in `84af853`: "for a sustained push, give an impulse of force times seconds", in the tool, TOOLS.md, CHANGELOG and the simulate skill |
| Import `get_physxunittests_interface` only for a push without a point, with an error that names it | taken in `84af853`: a push at a given point works without it |
| Refuse a body whose `physics:rigidBodyEnabled` is false, beside a kinematic one | taken in `84af853`: PhysX holds such a body as a static rigid, as NVIDIA's `test_rigid_body_api_update` counts it (`numDynamicRigids` 0, `numStaticRigids` 1; 107.3.26 lines 498-501, 110.4.4 lines 530-533), and nothing moves one. `test_a_disabled_rigid_body_is_refused_before_a_kinematic_one` and live `test_15_12` |

Not covered: Isaac Sim 5.x live. Isaac Sim 5.1 crashes in its own start on this machine, so 5.x is checked against
its installed source only; the docs this change touches claim nothing of 5.x, and the README already says it is
untested.

## Live run

Not yet: the live suites wait for #5's fix on `main` (the plan's R11), and the main session runs them then, on Isaac
Sim 6.2.0 with the extension installed from this branch. They must show:

| Test | Shows |
|---|---|
| `test_15_04` | `method` is `physx`, `at` is `centre of mass` |
| `test_15_06` | 10 N s on 5 kg gives about 2 units/s along X (within 25%); 10 N gives `10 * dt / 5` (within 50%), a force for one physics step, as the descriptions say. A held force would fail it, and the descriptions would change to match. |
| `test_15_07` | under 2 degrees pushed at the centre of mass, over 5 at a point 0.2 above it |
| `test_15_08` | the point 0.15 off the origin; under 2 degrees without `position`, over 5 at the origin |
| `test_15_09`, `test_15_10`, `test_15_12` | errors naming the stopped simulation, the kinematic body, the disabled body |
| `test_15_11` | the G1's pelvis pushed at its centre of mass, and further along X than without the push. If `ret_val` is false for a link, the plan drops that check. |
| both suites in full | no failures beyond `main`'s on the same Kit |

## Checks

`uv run tools/gate.py full` passed on `8855653` (758 tests, 94.02%) and on `84af853` (767 tests, 94.16%).
