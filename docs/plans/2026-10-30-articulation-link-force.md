---
title: Let apply_force push articulation links again, and refuse a body fixed to the world
issue: "#58"
status: approved
approved_by: serionist
approved_at: 2026-10-30
---

# Let apply_force push articulation links again, and refuse a body fixed to the world

#58 says PhysX's push doesn't reach an articulation's links, so `apply_force` refuses them (#59). Measured again on
Isaac Sim 6.2, it does reach them.

- **In free fall:** today's call, `IPhysxSimulation.apply_force_at_pos`, changed a G1's momentum by 100.19 N s for
  100 N s on its pelvis (E1), and by 100.00002 N s within one step on a knee (E11).
- **On the ground, as in #59:** one frame after the push, the robot carried 98.3 N s more than an unpushed one (E10).
- **#59's evidence was a misread test.** Its log says the pushed pelvis moved 0.133 along X and the unpushed one
  -0.102, so the push moved it 0.235 further. The 0.152 the issue quotes as the unpushed drift was the test's
  threshold, |-0.102| + 0.05 (fact 2).

This plan drops the link refusal. In its place it refuses a body that an enabled fixed joint holds to the world, or
one welded to such a body, whether articulated or not, since no force moves either (E6, E11). Its live tests compare
a change of momentum with the push, not drift with a threshold.

PhysX's tensor API, the issue's proposed fix, was measured too (E2 to E5, E8), and is kept here as evidence for a
follow-up. With GPU dynamics and `/physics/suppressReadback` set (the Direct GPU API), today's call moves nothing,
not even a lone cube, while the tensor API pushes there (E8).

## Goal

**When this is done:**

- `apply_force` on a link of a floating robot, its pelvis or any other, changes the robot's momentum by the impulse,
  or by force times the physics step. The live suite measures it within 2%, on the G1's pelvis and on a link of a
  free two-cube articulation.
- The point is the link's own centre of mass unless `position` is given, as for a lone body. The tool's description
  and TOOLS.md say the robot moves as a whole: its speed changes by the impulse over the robot's mass.
- A body that an enabled fixed joint holds to the world is refused, and so is one welded to it through enabled fixed
  joints, articulated or not. Examples: the Franka's base, a link welded to a fixed base, a cube bolted to the world.
  A link that a joint lets move, such as the Franka's hand, is pushed.
- Under PhysX's Direct GPU API (`/physics/suppressReadback` true) every push is refused, naming #68, since none
  moves anything there (E8; Q6).
- The README's Known issues, the tool's description, TOOLS.md, CHANGELOG and the simulate skill no longer say links
  can't be pushed.

**In scope:**

- `ovmcp/core/force.py` and the `apply_force` handler;
- the server's description of `apply_force`;
- the unit and live tests, and the docs.

**Out of scope:**

- **GPU dynamics with `/physics/suppressReadback`,** the Direct GPU API. Today's call pushes nothing there, lone
  bodies included (E8). It gets its own issue, with E2 to E5 and E8 as the evidence for moving pushes to the tensor
  API (Design, Alternatives); it is #68. Meanwhile this PR refuses a push there (Q6).
- **A torque, or a force held over many steps.** `apply_force` has neither today.
- **Newton physics, deformable bodies, point instancers.**
- **Isaac Sim 5.x live.** It crashes in its own start on this machine (#59), so 5.1 is read from its installed source
  (owner call Q7).

## What the code and the sources say

These are read from the code and from the sources installed here: Isaac Sim 6.2.0 under `D:\isaac\venv` (Kit 110.4,
`omni.physx` and `omni.physics.tensors` 110.4.4) and Isaac Sim 5.1 under `D:\isaacsim5.1` (Kit 107.3, 107.3.26).
Kit's and Isaac Sim's docs are read through Context7, and UsdPhysics's parser is probed in the repo's usd-core.

| # | Fact | Source |
|---|---|---|
| 1 | The handler pushes with `get_physx_simulation_interface().apply_force_at_pos(stage_id, sdfPathToInt(path), Float3 force, Float3 pos, mode)`, mode `Impulse` or `Force`. Before that it refuses, in order: a stopped timeline; `physics:rigidBodyEnabled` false; a kinematic body; a body PhysX doesn't hold, by `get_rigidbody_transformation`'s `ret_val`; a body `articulation_holding` finds in an articulation. Without `position`, it pushes at the centre of mass from `get_physxunittests_interface().get_mass_information` | `handlers/simulation.py` lines 183-275; `core/force.py` `refusal`; `omni/physx/bindings/_physx.pyi` (110.4.4) line 1207 |
| 2 | #59's live run on `a9e3182` printed `Along X in 0.2 s: -0.102 without the push, 0.133 with it`. The test asserted `pushed > abs(unpushed) + 0.05`, which failed as `0.13294577598571777 not greater than 0.15211944580078124`. The review record and #58 then gave 0.152 as the unpushed drift. The G1 stood on the ground, so friction and the robot's fall were in the measure | the run's log, kept outside the repo; `git show a9e3182:tests/test_scenarios.py`, `test_15_11`; `docs/reviews/2026-10-29-apply-force-code.md`, F2; issue #58 |
| 3 | `articulation_holding(stage, body)` reads an articulation as UsdPhysics's parser does: the bodies joined through joints to the prim carrying `ArticulationRootAPI`. A joint end that is the world or a static prim joins nothing; `_body_of` counts any prim with `RigidBodyAPI` as a body, a disabled one too. A unit test checks the links against `UsdPhysicsLoadStageFromPrimRange` in usd-core | `core/force.py`; `tests/test_force.py` |
| 4 | `RigidBodyView`: "A rigid object can be either an articulation link or an individual rigid body". Its `apply_forces_and_torques_at_position(force_data, torque_data, position_data, indices, is_global)` takes `(count, 3)` forces and world points, forces only, with no impulse mode. Without points it pushes at the body's origin, not its centre of mass. 5.1 has the same signature | `omni/physics/tensors/api.py` (110.4.4) lines 3237-3247, 3461-3508; (107.3.26) `impl/api.py` line 3521 |
| 5 | `create_simulation_view(frontend_name, stage_id=-1, backend="physx")` in 110.4.4, `(frontend_name, stage_id=-1)` in 107.3.26. The numpy frontend raises on a GPU pipeline. A view's pattern is a glob whose plain last component matches every descendant of that name ("recursive leaf"), so a view of one path can hold more rows | `api.py` (110.4.4) lines 13-76, 287-320; (107.3.26) `impl/api.py` lines 5-40 |
| 6 | `isaacsim.core.experimental.prims.RigidPrim(paths)` applies `UsdPhysics.RigidBodyAPI` and `PhysxSchema.PhysxRigidBodyAPI` to each prim that lacks them, which edits the user's stage. Its force method wraps fact 4's call. The experimental `Articulation` has no force method | `isaacsim.core.experimental.prims` (6.2) `rigid_prim.py` lines 101-175, 634-705; `prim.py` lines 177-217 |
| 7 | Isaac Sim's `SimulationManager` makes a tensor view with the warp frontend at play and invalidates it at stop. 6.2 exposes it as `get_physics_simulation_view()`; 5.1 keeps it private. `set_device("cuda:N")` turns on GPU dynamics and sets `/physics/suppressReadback`, the Direct GPU API | `isaacsim.core.simulation_manager` (6.2) `simulation_manager.py` lines 711-820, 878-894, 1024-1060; (5.1) lines 45, 178-190 |
| 8 | `ArticulationView.shared_metatype.fixed_base`: "A boolean indicating if the base link is fixed (True) or floating (False)" | `api.py` (110.4.4) line 734 |
| 9 | `PhysxSchema.PhysxForceAPI` pushes a body through USD attributes, at its centre of mass only, for the next step unless `retainAccelerations` is set | Kit's rigid body guide, "Apply Force to a Rigid Body" |
| 10 | The tool contract, `tests/fixtures/mcp-tools.json`, holds each tool's name, input schema and annotations. `tools/golden.py` strips descriptions | `tests/test_contract.py`; `docs/reviews/2026-10-29-apply-force-code.md` |
| 11 | UsdPhysics's parser, probed on three arms. (a) An arm whose base a fixed joint holds to the world: the articulation is rooted at that joint, its bodies include the world (`""`), and a sensor welded to the base is among them. (b) An arm held by a fixed joint excluded from articulations: the parser still lists that joint among the articulated joints and the world among the bodies. (c) A disabled body (`physics:rigidBodyEnabled` false) in a chain: the parser reads it as static, and lists none of its neighbours as articulated bodies | a probe script on the repo's usd-core, kept outside the repo (`UsdPhysicsLoadStageFromPrimRange`; `ArticulationDesc.rootPrims`, `articulatedBodies`, `articulatedJoints`) |

## Findings

On Isaac Sim 6.2.0 headless with the bridge on port 8212, each run on a fresh Kit. The main session ran them from the
scripts in this session's scratchpad (`e58_kit.py`, `e58/s*.py`), outside the repo: E1 to E9 and s9 in one run, E10
and E11 in a second.

**The stage:**

- a physics scene at 60 steps a second, Z up, metres, CPU pipeline;
- the G1 at z = 5 with no ground, so nothing but a push changes its momentum along X;
- the Franka, fixed base;
- `/World/Pair`: two 5 kg cubes on a revolute joint, the articulation root on their Xform, gravity off;
- `/World/PairFixed`: the same, with a fixed joint from the world to A;
- `/World/Lone`: a lone 5 kg cube, gravity off.

**The measure:** the total momentum, Σ m·v over the bodies, from the tensor API's velocities and masses (s9 checks it
another way).

Each case starts from a fresh play.

| # | What | Measured | Means |
|---|---|---|---|
| E1 | **Today's call on links**, impulse at the centre of mass: 100 N s on the G1's pelvis; 10 N s on Pair's B; 10 N s on the lone cube | G1: X momentum 0.000 to 100.19 ten frames later. It is unchanged straight after the call, since a link's push lands at the next step. Pair: 0 to 10.000, both cubes at 1.000 m/s. Lone: 0 to 10.000 | PhysX's push reaches links. #58's premise is wrong (fact 2) |
| E2 | The tensor API, `RigidBodyView` of the one body, the impulse as impulse / dt for one step, at the centre of mass | G1 99.99998 after one frame, 100.19 after 11. Pair 10.000. Lone 10.000 | exact. The 0.19 the G1 gains in E1 and E2 alike is the robot's own, not either call's |
| E3 | The tensor API, a force for one step: 100 N on the pelvis, 10 N on B | 1.66667 and 0.16667 after one frame (100 × 1/60, 10 × 1/60), unchanged 20 frames later | a force lasts one step, as today's `Force` mode |
| E4 | Paused: the tensor push on B, then play. Then two pushes while paused. Today's call on the lone cube while paused | Unchanged while paused, +10 after play. Two pushes: +20 (they add). Lone: +10 after play | a push while paused lands on the next step, through either API |
| E5 | A tensor view of our own per push, invalidated straight after | The push lands (+10). Isaac Sim's own view stays valid and the same object. 0.016 ms per view. `get_joint_states` answers after (43 DOF) | a view per call is cheap and harmless |
| E6 | Fixed base, through the tensor API: impulse on PairFixed's A, 1 N s sideways on its B; 100 N s on the Franka's `panda_link0`, 20 N s sideways on `panda_hand` | A: position and velocity exactly unchanged. B: 0.144 m/s sideways about its hinge. `panda_link0` unchanged to 1e-8. `panda_hand` 0.012 sideways after 15 frames against 0.00008 unpushed, pulled back to 0.001 by its drives after 45 | a fixed base doesn't move; its other links do. The tensor API reports `fixed_base` true for the Franka and PairFixed, false for the G1 and Pair |
| E7 | `get_mass_information` on links | The pelvis: 3.814 kg, the tensor API's mass for it too, and a centre of mass (0, 0, -0.076) in its frame. B: 5 kg at its origin. s9: the G1's mass, 34.2363 kg, is the same both ways, and the centre of mass built from poses and `get_mass_information` moves at the tensor API's momentum over mass, to 1e-5 | today's centre-of-mass path works for links unchanged |
| E8 | GPU dynamics with `/physics/suppressReadback` (the Direct GPU API), through `SimulationManager.set_device("cuda:0")`: today's call on the lone cube; the tensor API (warp) on the lone cube and on B | Today's call: 0, nothing moves. Tensor: +10 on the lone cube; +10 on B, then +0.16667 for a 10 N force | with the Direct GPU API, today's call pushes nothing, lone bodies included: a follow-up issue, which the tensor API fixes. GPU dynamics without `suppressReadback` was not measured |
| E9 | The rows of a tensor view of `/World/G1/pelvis` | 1, no other path | (for the follow-up) |
| E10 | #59's setup: the G1 standing on a ground, 100 N s on the pelvis half a second after play, the pelvis's travel along X over the next 12 frames. Cases: no push; today's call; the tensor push; today's call after an `Articulation` is made, as `get_joint_states` makes one; today's call after 2 s, the G1 lying down | No push: X momentum -13.3, then -18.4 one frame later and -28.0 after 12; pelvis -0.136. Today's call: -13.3 to +79.9 one frame later, 98.3 above the unpushed robot; pelvis +0.476. The tensor push: the same numbers to the last digit. After an `Articulation`: -18.7 to +73.6; pelvis +0.429. After 2 s: +0.5 to +97.8; pelvis +0.488. PhysX never had the body asleep | the push lands on a robot on the ground too, by either API. Friction takes a few N s within the step |
| E11 | Today's call on links in each mode, in free fall: 100 N s on the left knee; 100 N for one step on the pelvis; 100 N s on the pelvis while paused; 10 N s on PairFixed's A and 100 N s on the Franka's base; 10 N s on B at a point 0.1 off its centre of mass | Knee: 100.00002 after one frame, then 105.25 ten frames later. Force: 1.66667, still 1.66667 twenty frames later. Paused: unchanged while paused, 100.18 three frames after play. PairFixed's A and the Franka's base: positions unchanged to 1e-8, velocity 0. Off centre: momentum 9.999996, the cubes at 1.675 and 0.325 m/s along X, turning | today's call pushes links in every mode `apply_force` offers. A fixed base takes the push and doesn't move, so it needs the refusal. After a push, the G1's own joints change its momentum: by 0.2% in 10 frames after one on the pelvis, through either API (E1, E2), and by 5% after one on a knee. The two cubes keep theirs exact |
| s9 | The live test's measure, without the tensor API: the G1's centre of mass along X from PhysX's poses and `get_mass_information`, over 12 frames after E2's push, inside one script | 2.92655 m/s, against the tensor API's momentum over mass, 2.92656. Mass 34.2363 kg both ways | the live test can measure momentum from poses alone |

## Design

### The push on a link

The handler drops the link refusal. A link goes through `IPhysxSimulation.apply_force_at_pos`, as a lone body does,
with the same point, mode and answer (E1, E7, E10, E11). Nothing else in the push changes.

### What stays refused, and what's new

Today's refusals stay, in today's order: stopped, disabled, kinematic, not held. One comes in after the first, as Q6
answered: PhysX's Direct GPU API, read as `/physics/suppressReadback` true, where a push moves nothing (E8, #68).
The last changes from "a link" to "a body held to the world":

- **The rule, one for every body:** a body is refused when an enabled (`physics:jointEnabled`) `UsdPhysics.FixedJoint`
  holds it to the world. That is, the joint's other end is one of:
  - the world (no target);
  - a static prim;
  - a disabled body (`physics:rigidBodyEnabled` false), which PhysX holds as static (`core/force.py` line 65), as
    UsdPhysics's parser reads it (fact 11c).

  So is a body welded to such a body through more enabled fixed joints. It doesn't matter whether the body is
  articulated, or whether the joint is excluded from articulations (`physics:excludeFromArticulation`). This covers
  an articulation's fixed base, the case PhysX's `fixed_base` names (E6, E11), a link welded to that base, and a cube
  bolted to the world.
- **Where it is decided:** `held_to_world(stage, body_path) -> str | None` in `core/force.py`, from the stage, so
  usd-core unit-tests it. It returns the body the world joint holds: the body itself, or the base it is welded to.
  - **One traversal:** `held_to_world` and `articulation_holding` share a joint index, which collects each joint's
    type, ends and enabled flag.
  - **Disabled bodies:** an end in a disabled body counts as static for both functions (P4).
- **The messages,** with the root named when the body is an articulation's link (`articulation_holding`):
  - held: `"<path> is held to the world by a fixed joint[, as the base of the articulation at <root>]: no force
    moves it"`;
  - welded: `"<path> is welded to its fixed base <base>, which a fixed joint holds to the world[, in the
    articulation at <root>]: no force moves it"`.
- **Not refused:**
  - a joint of another type to the world, such as a revolute one, since the body moves about it;
  - a disabled fixed joint, which holds nothing.
- **`refusal`'s signature:** it takes `direct_gpu: bool` and `fixed_base: str | None` (what `held_to_world`
  returns), and keeps `articulation: str | None`, now only to name the root in the message. The handler reads
  neither PhysX's pose nor the joints under the Direct GPU API.

### The server

`apply_force`'s description says links are pushed and the robot moves as a whole. It names a body fixed to the world
among the refusals. The parameters, bounds, hints and answer line don't change.

### Alternatives

| Alternative | Why not |
|---|---|
| **The tensor API for links**, the issue's proposal: a `RigidBodyView` of the link, the impulse as impulse / dt for one step | It works (E2 to E5), but today's call already pushes links exactly (E1), in any Kit app with `omni.physx`. The tensor API would add `omni.physx.tensors`, a frontend (numpy can't take a GPU pipeline, warp needs `omni.warp.core`), the step's length for an impulse, and a row lookup for its glob paths (fact 5) |
| **The tensor API for every body** | It fixes the Direct GPU API too (E8), so it is the follow-up's candidate. Here it would change how a lone body is pushed, the impulse included, for a defect that isn't #58's. That needs its own issue and its own live runs on both pipelines |
| `isaacsim.core.experimental.prims.RigidPrim` | It applies schemas to the user's prims (fact 6) and wraps the same tensor call |
| `PhysxSchema.PhysxForceAPI` | It edits the stage, and pushes at the centre of mass only (fact 9) |
| **The fixed base from PhysX at run time**, the tensor API's `fixed_base` | It needs the tensor API for a refusal. It says nothing of a lone body bolted to the world, or of an articulation whose `ArticulationRootAPI` sits on a joint and has no view to ask. The stage gives the same answer for the cases E6 and E11 measured, and usd-core tests it against the parser |
| No new refusal | A push on the Franka's base would answer success and move nothing (E11), the silent no-op #59 removed for other bodies |

The calls for the maintainer are Q1 to Q8, in Plan review, Round 1.

### Files

| File | Change |
|---|---|
| `extension/ovmcp.bridge/ovmcp/core/force.py` | the joint index shared by `articulation_holding` and the new `held_to_world`, a disabled body's end as static; `refusal`'s fifth case and its two messages; the module docstring |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/simulation.py` | `handle_apply_force` passes `fixed_base` and `articulation`; its docstring |
| `src/omniverse_mcp/tools/simulation.py` | `apply_force`'s description |
| `tests/test_force.py` | as in Tests |
| `tests/test_scenarios.py` | `test_15_11` rewritten; `test_15_14`, `test_15_15` and `test_15_16` new; the helpers `_speed_along_x_in_kit` and `_force_pair` |
| docs | as in Docs |

## Compatibility

No one-way door moves.

- **The tool contract:** the name, parameters, defaults, bounds and annotations stay. Only the description changes,
  which `tools/golden.py` strips, so `tests/fixtures/mcp-tools.json` doesn't change.
- **The wire protocol:** `/physics/apply_force` keeps its path, request and answer.
- **What users notice:**
  - A push on an articulation's link works again, where 0.2.1 and 0.2.2 refused it.
  - A push on a body a fixed joint holds to the world is refused with a message that says why. A link of a fixed
    base was refused before as a link. A lone body bolted to the world answered success and moved nothing.
  - Under PhysX's Direct GPU API every push is refused, naming #68, where a lone body's answered success and moved
    nothing (E8).
  - The fix is in the Kit extension: `uvx omniverse-mcp extension install`, then restart Kit. A new server with a
    0.2.2 extension still gets 0.2.2's refusal, passed through as an error.
- **Kit apps:** as today, any Kit 107+ app with `omni.physx`. Nothing new is needed.

## Steps

1. **The evidence.** Done: E1 to E11 and s9 (Findings), and the parser probe (fact 11).
2. **The core.** The joint index, `held_to_world`, and `refusal`'s fifth case. Proved by `tests/test_force.py`.
3. **The handler.** It passes `fixed_base` and `articulation`. Proved by the live `test_15_11` and `test_15_14` to
   `test_15_16`, and by the unchanged `test_15_04` to `test_15_12`.
4. **The server.** The description. Proved by `tests/test_contract.py`, unchanged, and `tests/test_tools.py`.
5. **The follow-up issue,** the one the session opens: with the Direct GPU API, `apply_force` moves nothing and
   reports success (E8), with E2 to E5 and E8 as the tensor API's evidence. It comes before the docs, which name it.
   Done: #68.
6. **The docs** (Docs), and `test_project/scenarios.md`'s 15.11 and 15.14 to 15.16.
7. **The gate,** `uv run tools/gate.py full`; both live suites on Isaac Sim 6.2; then `review-code`.

## Tests

**Unit, in CI** (`tests/test_force.py`):

- **The Direct GPU API's refusal:** after a stopped timeline, before the rest. Live, nothing toggles the setting:
  it changes how PhysX runs for the whole Kit.
- **The last refusal:**
  - each message, held and welded, with the root and without;
  - it comes after "PhysX holds no rigid body";
  - a body that isn't held is pushed;
  - `test_an_articulation_s_link_is_refused_naming_its_issue` goes. The other refusal tests pass `fixed_base=None`.
- **`held_to_world` on the `robots` fixture,** with fixed joints added beside its revolute ones:
  - **held:**
    - a fixed arm's base, held to the world by a fixed joint;
    - a sensor welded to that base by a second fixed joint (welded, naming the base);
    - the Crane's base, whose `ArticulationRootAPI` is on its fixed joint;
    - a base fixed to a static wall prim;
    - a base held by a fixed joint excluded from articulations;
    - a lone box bolted to the world.
  - **not held:** the fixed arm's link beyond a revolute joint; the G1's links, floating; a base on a disabled fixed
    joint; an arm on a revolute joint to the world; the loose box.
- **A disabled body (P4),** in a fixture of its own: a link fixed to a disabled body is held, naming the disabled
  body as its base. Neither function joins through the disabled body. It stays out of the `robots` fixture: the
  parser lists no articulated body around a disabled one (fact 11c), and the parser checks keep to shapes both read
  alike.
- **Against UsdPhysics's parser** (improvement 4), on the `robots` fixture:
  - the links `articulation_holding` finds are the articulated bodies the parser reads, as today;
  - the articulated bodies `held_to_world` holds are the ones the parser's articulations join to the world (`""`)
    through enabled fixed joints among their articulated joints, and the ones welded to those through such joints
    (fact 11a, 11b).

**`tests/test_tools.py`:** the existing `apply_force` cases pass unchanged.

**Live** (`tests/test_scenarios.py`, by hand on Isaac Sim 6.2):

The live checks compare a change of momentum with the push, never drift with a threshold: #59's lesson.

**The measure:** `_speed_along_x_in_kit(paths, frames)`, one `execute_script` that runs in Kit's frames, not the
wall clock (P1):

- It plays, waits `frames` updates (`next_update_async`), and pauses.
- Before and after the wait it reads each body's PhysX pose and `get_mass_information`. It returns the bodies' speed
  along X as their centre of mass's change over the simulation time between, their mass, and the last sample's
  simulation time.
- s9 measured it this way, against the tensor API's momentum to 1e-5.
- Each push goes through `apply_force` while paused, between two measures, and lands at the next step (E11:
  100.18 three frames after play). So the time a robot falls is counted in frames, whatever the machine's speed.

The tests:

- **`test_15_11`, rewritten: a push on the G1's pelvis moves the robot by the push.**
  - Stopped, the G1 is moved 20 units up its stage's up axis, and put back in cleanup.
  - Its speed along X over 12 frames; `apply_force(pelvis, [100, 0, 0], impulse=True)`; one frame, then its speed
    over 12 frames.
  - The change must be 100 / mass within 2%, about 2.92 m/s (E1: 0.2% drift after a pelvis push).
  - The last sample's simulation time must be under the 2.0 s the G1 takes to fall 20 units, about 0.5 s here.
  - The knee case goes (P2): `test_15_14` checks a link that isn't the root exactly.
- **`test_15_14`, new: a push on a link of a free articulation moves it exactly.**
  - `_force_pair(name, fixed)` builds a two-cube articulation of the test's own, as `_force_body` builds a cube:
    5 kg cubes on a revolute joint about the up axis, the root on their Xform, gravity off, away from the scene.
    It is deleted after, with the simulation stopped.
  - `apply_force(second cube, [10, 0, 0], impulse=True)` between two measures: the pair's speed along X changes by
    1.0 within 2% (E1, E11: exact).
- **`test_15_15`, new: a body fixed to the world is refused; the link beside it is pushed.**
  - `_force_pair(name, fixed=True)` adds a fixed joint from the world to the first cube.
  - `apply_force` on the first cube errors with "held to the world by a fixed joint" and the root's path.
  - `apply_force` on the second, sideways, while paused: success. Over 30 frames the second cube's PhysX pose moves
    more than 0.01, and the first cube's stays within 1e-4 (E6).
  - A lone cube of its own, bolted to the world by a fixed joint: refused.
- **`test_15_16`, new: the stock Franka** (improvement 3).
  - `create_robot("franka", ...)` from Isaac Sim's assets, away from the scene, deleted after. Play.
  - `apply_force` on `panda_link0` errors with "held to the world by a fixed joint", naming the articulation's root.
  - `apply_force` on `panda_hand` succeeds.
- `test_15_04` to `test_15_10` and `test_15_12` pass unchanged.

**What neither can show:** Isaac Sim 5.x (Q7); the Direct GPU API (E8, the follow-up); every robot's joint layout. The
rule is tested on the stage shapes the fixtures build, against the parser, and live on the two-cube articulation, a
bolted cube and the stock Franka.

## Docs

| File | Change |
|---|---|
| `docs/TOOLS.md`, `apply_force` | It pushes a rigid body or an articulation's link. A push on a link moves the whole robot: the robot's momentum changes by the impulse, so its speed changes by impulse / the robot's mass, and the link turns about its joints as well. The refusal table loses the link row and gains the rows for the Direct GPU API (#68) and for a body fixed to the world. It says the push is measured on Isaac Sim 6.2's CPU pipeline |
| `README.md`, Known issues | The #58 line goes. A line for #68 comes in: `apply_force` is refused under PhysX's Direct GPU API |
| `CHANGELOG.md`, Unreleased, Fixed | `apply_force` pushes an articulation's links again, such as a robot's. 0.2.1 refused them on a misread measurement: PhysX's push reaches them. A body a fixed joint holds to the world is refused, where a lone one answered success and moved nothing, and so is every push under PhysX's Direct GPU API, where none moves anything (#68). The fix is in the Kit extension (install line) (#58) |
| `plugin/skills/simulate/SKILL.md` | The sentence that it can't push links goes. It says a link moves the robot as a whole, and a body fixed to the world is refused |
| `docs/ARCHITECTURE.md` | `core/force.py`'s entry: "its refusals" names a body fixed to the world |
| `test_project/scenarios.md` | 15.11 rewritten as `test_15_11`; 15.14 to 15.16 added |
| `AGENTS.md`, Traps | A row: a live test's threshold read as a measurement refused pushes PhysX makes (#58). The guard: force tests compare the change of momentum with the push. #57 takes the 150th line, the gate's limit, so the row merges into an existing one or another line is shortened (Q5) |

## Risks

| Risk | Status |
|---|---|
| Today's call misses a link in some mode or state | Resolved by E1, E10 and E11: impulse, force, paused, at a point, in free fall and on the ground, on the root and on other links |
| A robot's own joints move its momentum after a push, so a tight check on a robot can fail on a correct push | Resolved: the G1's check is on its pelvis, where E1 measured 0.2%; the exact check on another link runs on the two-cube articulation |
| A live check timed by the wall clock, while Kit updates unthrottled, runs past the robot's fall | Resolved: the measure counts Kit's frames, the push lands while paused, and the test asserts the last sample's simulation time (P1) |
| The rule differs from what omni.physx does: a fixed joint to a static prim or a disabled body, a breakable one (`physics:breakForce` finite), `ArticulationRootAPI` on the joint | Accepted. E6 and E11 measured a fixed joint to the world, on the Franka and on PairFixed. In the other cases the rule errs towards a refusal, never towards a success that moved nothing; a breakable joint counts as holding |
| The Direct GPU API: today's call pushes nothing on any body and reports success (E8). With the link refusal gone, 0.2.2's error for a robot there becomes a silent success | Resolved here by the refusal Q6 approved; #68 makes the push work there |
| A traversal of the whole stage per call grows with the stage | Accepted, as today: `articulation_holding` already traverses it. The shared index keeps it to one traversal |
| Isaac Sim 5.x untested live for links (`omni.physx` 107.3) | Accepted (Q7): TOOLS.md says the push is measured on 6.2. The call is the same in 107.3.26's stubs |
| #59's own error again: a live check that passes or fails for the wrong reason | Resolved by measuring the change of momentum against the push, within 2% |

## Plan review

### Round 1

**How:** `review-plan`, a fresh reviewer (Claude), 2026-10-30, on `0dd9b60`. The reviewer checked the Findings and
the reading of #59's log against the runs' raw output and #59's live log.
**Verdict:** `needs-answers`: no blockers or majors, six minors, eight owner calls open. `approved` once the
maintainer answered Q1 to Q8, all as recommended, on 2026-10-30.
**Now:** the six minors fixed and improvements 1 to 6 taken, in the commit after `0dd9b60`.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | `test_15_11` timed its windows with wall-clock sleeps while SimulationApp runs updates unthrottled (`rateLimitEnabled` false, `manualModeEnabled` true in `isaacsim.exp.base.kit`), so on a fast machine the G1 lands before the after-window ends | fixed: `_speed_along_x_in_kit` measures in Kit's frames inside one `execute_script`, the push lands while paused, and the test asserts the last sample's simulation time is under the fall (Tests, Risks) |
| P2 | minor | The knee's 10% tolerance wasn't backed by a measurement over the test's own window: E11 sampled 11 frames | fixed: the knee case goes; `test_15_14` checks a link that isn't the root exactly |
| P3 | minor | A fixed joint to the world excluded from articulations contradicted the Risks row ("errs towards a refusal"): a push on that base would answer success and move nothing | fixed by improvement 2: one rule for every body, excluded joint or not; the fixture's excluded base is held |
| P4 | minor | A body with `physics:rigidBodyEnabled` false is static to PhysX (`core/force.py` line 65), but `_body_of` counted only `RigidBodyAPI` | fixed: in the shared joint index a disabled body's end counts as static, as the parser reads it (fact 11c); a fixture case of its own (Tests) |
| P5 | minor | E8 measured the Direct GPU API (`set_device("cuda:0")` sets `/physics/suppressReadback`), not GPU dynamics in general | fixed: "GPU dynamics with `/physics/suppressReadback` (the Direct GPU API)" wherever E8 is cited; E8 says GPU dynamics without it wasn't measured |
| P6 | minor | The follow-up GPU issue must exist before the docs that name it | fixed: Steps 5, "the issue the session opens", before the docs |

**Refuted:** none.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Push links with today's call, or move links to the tensor API as #58 proposed? | Today's call: it pushes links exactly in every mode (E1, E10, E11), with nothing new to depend on | As recommended (2026-10-30) |
| Q2 | Refuse a body that a fixed joint holds to the world? | Yes. Otherwise a push on the Franka's base answers success and moves nothing (E11) | As recommended (2026-10-30) |
| Q3 | The Direct GPU API, where no push moves anything (E8): this PR or its own issue? | Its own issue, with this plan's tensor API measurements | As recommended (2026-10-30) |
| Q4 | #58's title and body state a cause the Findings disprove | A comment from the session linking this plan's Findings, and a title such as "apply_force refuses articulation links that PhysX pushes" | As recommended (2026-10-30) |
| Q5 | AGENTS.md's Traps row (Docs) fills the file to the gate's 150 lines | Take it: a misread live check is the trap this repo paid for here | As recommended (2026-10-30) |
| Q6 | A Direct GPU API guard now: dropping the link refusal turns 0.2.2's error for a robot there into a silent success. Refuse while `/physics/suppressReadback` is true, here or as the follow-up's first step? | Here, as a cheap refusal (the reviewer's recommendation) | As recommended (2026-10-30) |
| Q7 | Isaac Sim 5.x is unmeasured for links (`omni.physx` 107.3): accept and say "measured on 6.2" in TOOLS.md, or keep the link refusal below Kit 110? | Accept, and say so | As recommended (2026-10-30) |
| Q8 | Should the PR say `Closes #58`, since the fix isn't the tensor API the issue proposed? | Yes, with #58 retitled as Q4 says | As recommended (2026-10-30) |

| Improvement | Answer |
|---|---|
| 1. Measure in frames inside Kit for `test_15_11`, `test_15_14` and `test_15_15` | taken (P1) |
| 2. One rule for every body held to the world by an enabled fixed joint, articulated or not, excluded or not; the same message, the root named when there is one | taken (P3): Design, Goal, Compatibility, Tests |
| 3. Check the stock Franka once live | taken: `test_15_16` |
| 4. Cross-check the rule against UsdPhysics's parser in usd-core, as the links are | taken: Tests; the parser's reading probed (fact 11) |
| 5. A message for a welded link, "welded to its fixed base" | taken: Design, The messages |
| 6. Factual slips: `test_15_06` allows 25% and 50%, not 2%; E10 is about 98.3 above the unpushed robot; E7's point to 1e-6 isn't in s1's output | taken: the Goal no longer compares with `test_15_06`; E10 gives 98.3; E7 cites s9 |
