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
One minor, fixed; three improvements, all taken. The branch was then rebased onto `76b0f75` (#52, #53, #55, #56),
README's line for #25 resolved to `start_recording`'s alone and the lists merged with main's: `8855653` became
`f0623d7`, and the fixes are `81f9da7`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_scenarios.py`, `test_15_11_apply_force_to_a_robot_link` | It can't tell a push PhysX took on a G1 link from one it ignored: `apply_force_at_pos` returns None either way, and the test checked only the answer. | Fixed in `81f9da7`: 100 N s along X on the pelvis, and the link's PhysX pose must move further along X in about 0.2 s than it does without the push (`drift_along_x`). |

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
| Name the way to hold a push over MCP, where one call can't last past a physics step | taken in `81f9da7`: "for a sustained push, give an impulse of force times seconds", in the tool, TOOLS.md, CHANGELOG and the simulate skill |
| Import `get_physxunittests_interface` only for a push without a point, with an error that names it | taken in `81f9da7`: a push at a given point works without it |
| Refuse a body whose `physics:rigidBodyEnabled` is false, beside a kinematic one | taken in `81f9da7`: PhysX holds such a body as a static rigid, as NVIDIA's `test_rigid_body_api_update` counts it (`numDynamicRigids` 0, `numStaticRigids` 1; 107.3.26 lines 498-501, 110.4.4 lines 530-533), and nothing moves one. `test_a_disabled_rigid_body_is_refused_before_a_kinematic_one` and live `test_15_12` |

Not covered: Isaac Sim 5.x live. Isaac Sim 5.1 crashes in its own start on this machine, so 5.x is checked against
its installed source only; the docs this change touches claim nothing of 5.x, and the README already says it is
untested.

## Live run

On `a9e3182`, Isaac Sim 6.2.0 headless, a fresh Kit with the extension installed from the branch, both suites with
nothing excluded, #5's fix on `main`: 145 passed, 1 failed. The plain bodies measured as the descriptions say:

| Test | Measured |
|---|---|
| `test_15_06` | 10 N s on 5 kg: 2.000 units/s along X. 10 N: 0.0333 units/s, one step of 0.0167 s, so a force lasts one physics step |
| `test_15_07` | 0.00 degrees pushed at the centre of mass, 15.74 at a point 0.2 above it |
| `test_15_08` | the point 0.150 off the origin; 16.49 degrees pushed at the origin |
| `test_15_04`, `test_15_09`, `test_15_10`, `test_15_12` | passed: PhysX did the push; the stopped simulation, the kinematic body and the disabled body refused |
| `test_15_11` | failed: `0.13294577598571777 not greater than 0.15211944580078124` |

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F2 | major | `handlers/simulation.py`, `handle_apply_force` | A push on a robot's link reports success and moves nothing. 100 N s along X on the G1's pelvis, which PhysX holds (`ret_val` true): it moved 0.133 along X in 0.2 s, against 0.152 without the push, where about half a metre was expected. `IPhysxSimulation.apply_force_at_pos` takes a push on an articulation's link and ignores it. Found by the live run, which the review couldn't make. | Fixed in `4646bf3`: refused after the checks that PhysX holds the body, naming #58, which tracks pushing a link. A link is read from the stage as UsdPhysics's own parser reads an articulation: every body joined through joints to the body, joint or prim that carries `ArticulationRootAPI` (`articulation_holding` in `core/force.py`; the G1's links are its pelvis's siblings, the root on the pelvis). Unit tests on robots shaped as Isaac Sim builds them, one checking the links against UsdPhysics's parser in usd-core; `test_15_11` now expects the refusal on the pelvis and on another link. |

F2 is a major, so `review-code` reads `4646bf3` in a round 2. The refusal has not run live yet: `test_15_11` must
show the error, naming the articulation at the pelvis and #58, for both links, and the rest of both suites as above.

## Checks

`uv run tools/gate.py full` passed on `8855653` (758 tests, 94.02%), on the fixes before the last rebase (767
tests, 94.16%), on `81f9da7` rebased onto `76b0f75` (944 tests, 95.29%), with the guard in `tests/test_logs.py`
finding no Python hook on Kit's logging, and on `4646bf3` (958 tests, 95.38%).
