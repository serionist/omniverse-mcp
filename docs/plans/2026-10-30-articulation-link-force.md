---
title: Let apply_force push articulation links again, and refuse a base fixed to the world
issue: "#58"
status: draft
approved_by:
approved_at:
---

# Let apply_force push articulation links again, and refuse a base fixed to the world

#58 says PhysX's push doesn't reach an articulation's links, so `apply_force` refuses them (#59). Measured again on
Isaac Sim 6.2, it does: today's call, `IPhysxSimulation.apply_force_at_pos`, changed a free-falling G1's momentum
by 100.19 N s for a 100 N s push on its pelvis (E1). On a knee it added 100.00002 N s within one step (E11), and
standing on the ground, as in #59, it added 93 N s within the step against the feet's friction (E10). #59's evidence
was a misread test. Its log says the pushed pelvis moved 0.133 along X and the unpushed one -0.102, so the push moved
it 0.235 further. The 0.152 the issue quotes as the unpushed drift was the test's threshold, |-0.102| + 0.05
(fact 2). This plan drops the link refusal
and refuses only the base of a fixed-base articulation, which a fixed joint holds to the world and no force moves
(E6). Its live test measures a robot's change of momentum against the push, not drift against a threshold. PhysX's
tensor API, the issue's proposed fix, was measured too (E2 to E5, E8). It is kept here as the evidence for a
follow-up: on the GPU pipeline, today's call moves nothing at all, even a lone cube, and the tensor API pushes there
(E8).

## Goal

**When this is done:**

- `apply_force` on a link of a floating robot, its pelvis or any other, changes the robot's momentum by the impulse,
  or by force times the physics step. The live suite measures this within 2%, as `test_15_06` measures a cube: on
  the G1's pelvis, and on a link of a free two-cube articulation.
- The point is the link's own centre of mass unless `position` is given, as for a lone body. The tool's description
  and TOOLS.md say the robot moves as a whole: its speed changes by the impulse over the robot's mass.
- A link of a fixed-base robot that a joint lets move, such as the Franka's hand, is pushed. The base, held to the
  world by a fixed joint, is refused, and so is a link welded to that base by fixed joints, since no force moves
  either.
- The README's Known issues, the tool's description, TOOLS.md, CHANGELOG and the simulate skill no longer say links
  can't be pushed.

**In scope:** `ovmcp/core/force.py` and the `apply_force` handler; the server's description of `apply_force`; the unit
and live tests; the docs.

**Out of scope:**

- The GPU pipeline, where today's call pushes nothing, lone bodies included (E8). It gets its own issue, with E2 to E5
  and E8 as the evidence for moving pushes to the tensor API (Design, Alternatives).
- Refusing a lone body that a fixed joint welds to the world: today's push can't move one either, but that isn't
  #58's subject.
- A torque, or a force held over many steps. `apply_force` has neither today.
- Newton physics, deformable bodies, point instancers.
- Isaac Sim 5.x live. It crashes in its own start on this machine (#59), so 5.1 is read from its installed source.

## What the code and the sources say

These are read from the code and from the sources installed here: Isaac Sim 6.2.0 under `D:\isaac\venv` (Kit 110.4,
`omni.physx` and `omni.physics.tensors` 110.4.4) and Isaac Sim 5.1 under `D:\isaacsim5.1` (Kit 107.3, 107.3.26).
Kit's and Isaac Sim's docs are read through Context7.

| # | Fact | Source |
|---|---|---|
| 1 | The handler pushes with `get_physx_simulation_interface().apply_force_at_pos(stage_id, sdfPathToInt(path), Float3 force, Float3 pos, mode)`, mode `Impulse` or `Force`. Before that it refuses, in order: a stopped timeline; `physics:rigidBodyEnabled` false; a kinematic body; a body PhysX doesn't hold, by `get_rigidbody_transformation`'s `ret_val`; a body `articulation_holding` finds in an articulation. Without `position`, it pushes at the centre of mass from `get_physxunittests_interface().get_mass_information` | `handlers/simulation.py` lines 183-275; `core/force.py` `refusal`; `omni/physx/bindings/_physx.pyi` (110.4.4) line 1207 |
| 2 | #59's live run on `a9e3182` printed `Along X in 0.2 s: -0.102 without the push, 0.133 with it`. The test asserted `pushed > abs(unpushed) + 0.05`, which failed as `0.13294577598571777 not greater than 0.15211944580078124`. The review record and #58 then gave 0.152 as the unpushed drift. The G1 stood on the ground, so friction and the robot's fall were in the measure | the run's log, kept outside the repo; `git show a9e3182:tests/test_scenarios.py`, `test_15_11`; `docs/reviews/2026-10-29-apply-force-code.md`, F2; issue #58 |
| 3 | `articulation_holding(stage, body)` reads an articulation as UsdPhysics's parser does: the bodies joined through joints to the prim carrying `ArticulationRootAPI`. A joint end that is the world or a static prim joins nothing. A unit test checks it against `UsdPhysicsLoadStageFromPrimRange` in usd-core | `core/force.py`; `tests/test_force.py` |
| 4 | `RigidBodyView`: "A rigid object can be either an articulation link or an individual rigid body". Its `apply_forces_and_torques_at_position(force_data, torque_data, position_data, indices, is_global)` takes `(count, 3)` forces and world points, forces only, with no impulse mode. Without points it pushes at the body's origin, not its centre of mass. 5.1 has the same signature | `omni/physics/tensors/api.py` (110.4.4) lines 3237-3247, 3461-3508; (107.3.26) `impl/api.py` line 3521 |
| 5 | `create_simulation_view(frontend_name, stage_id=-1, backend="physx")` in 110.4.4, `(frontend_name, stage_id=-1)` in 107.3.26. The numpy frontend raises on a GPU pipeline. A view's pattern is a glob whose plain last component matches every descendant of that name ("recursive leaf"), so a view of one path can hold more rows | `api.py` (110.4.4) lines 13-76, 287-320; (107.3.26) `impl/api.py` lines 5-40 |
| 6 | `isaacsim.core.experimental.prims.RigidPrim(paths)` applies `UsdPhysics.RigidBodyAPI` and `PhysxSchema.PhysxRigidBodyAPI` to each prim that lacks them, which edits the user's stage. Its force method wraps fact 4's call. The experimental `Articulation` has no force method | `isaacsim.core.experimental.prims` (6.2) `rigid_prim.py` lines 101-175, 634-705; `prim.py` lines 177-217 |
| 7 | Isaac Sim's `SimulationManager` makes a tensor view with the warp frontend at play and invalidates it at stop. 6.2 exposes it as `get_physics_simulation_view()`; 5.1 keeps it private. `set_device("cuda:N")` turns on GPU dynamics and sets `/physics/suppressReadback` | `isaacsim.core.simulation_manager` (6.2) `simulation_manager.py` lines 711-820, 878-894, 1024-1060; (5.1) lines 45, 178-190 |
| 8 | `ArticulationView.shared_metatype.fixed_base`: "A boolean indicating if the base link is fixed (True) or floating (False)" | `api.py` (110.4.4) line 734 |
| 9 | `PhysxSchema.PhysxForceAPI` pushes a body through USD attributes, at its centre of mass only, for the next step unless `retainAccelerations` is set | Kit's rigid body guide, "Apply Force to a Rigid Body" |
| 10 | The tool contract, `tests/fixtures/mcp-tools.json`, holds each tool's name, input schema and annotations. `tools/golden.py` strips descriptions | `tests/test_contract.py`; `docs/reviews/2026-10-29-apply-force-code.md` |

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
| E7 | `get_mass_information` on links | The pelvis: 3.814 kg, centre of mass (0, 0, -0.076) in its frame, the tensor API's mass and point to 1e-6. B: 5 kg at its origin | today's centre-of-mass path works for links unchanged |
| E8 | The GPU pipeline, `SimulationManager.set_device("cuda:0")` (`suppressReadback` true): today's call on the lone cube; the tensor API (warp) on the lone cube and on B | Today's call: 0, nothing moves. Tensor: +10 on the lone cube; +10 on B, then +0.16667 for a 10 N force | today's call pushes nothing on the GPU pipeline, lone bodies included: a follow-up issue, which the tensor API fixes |
| E9 | The rows of a tensor view of `/World/G1/pelvis` | 1, no other path | (for the follow-up) |
| E10 | #59's setup: the G1 standing on a ground, 100 N s on the pelvis half a second after play, the pelvis's travel along X over the next 12 frames. Cases: no push; today's call; the tensor push; today's call after an `Articulation` is made, as `get_joint_states` makes one; today's call after 2 s, the G1 lying down | No push: X momentum -13.3 to -28.0, pelvis -0.136. Today's call: -13.3 to +79.9 after one frame, pelvis +0.476. The tensor push: the same numbers to the last digit. After an `Articulation`: +92.3, pelvis +0.429. After 2 s: +97.3, pelvis +0.488. PhysX never had the body asleep | the push lands on a robot on the ground too, by either API. Friction takes a few N s within the step |
| E11 | Today's call on links in each mode, in free fall: 100 N s on the left knee; 100 N for one step on the pelvis; 100 N s on the pelvis while paused; 10 N s on PairFixed's A and 100 N s on the Franka's base; 10 N s on B at a point 0.1 off its centre of mass | Knee: 100.00002 after one frame, then 105.25 ten frames later. Force: 1.66667, still 1.66667 twenty frames later. Paused: unchanged while paused, 100.18 three frames after play. PairFixed's A and the Franka's base: positions unchanged to 1e-8, velocity 0. Off centre: momentum 9.999996, the cubes at 1.675 and 0.325 m/s along X, turning | today's call pushes links in every mode `apply_force` offers. A fixed base takes the push and doesn't move, so it needs the refusal. After a push, the G1's own joints change its momentum: by 0.2% in 10 frames after one on the pelvis, through either API (E1, E2), and by 5% after one on a knee. The two cubes keep theirs exact |
| s9 | The live test's measure, without the tensor API: the G1's centre of mass along X from PhysX's poses and `get_mass_information`, over 0.2 s after E2's push | 2.92655 m/s, against the tensor API's momentum over mass, 2.92656. Mass 34.2363 kg both ways | the live test can measure momentum from poses alone |

## Design

### The push on a link

The handler drops the link refusal. A link goes through `IPhysxSimulation.apply_force_at_pos`, as a lone body does,
with the same point, mode and answer (E1, E7, E10, E11). Nothing else in the handler changes.

### What stays refused, and what's new

Today's refusals stay, in today's order: stopped, disabled, kinematic, not held. The fifth changes from "a link" to
"a fixed base":

- **The rule:** a link of an articulation is refused when a fixed joint holds it to the world. That is a
  `UsdPhysics.FixedJoint`, enabled (`physics:jointEnabled`) and not excluded from articulations
  (`physics:excludeFromArticulation`), whose other end is the world (no target) or a static prim. It is the case
  that makes PhysX build the articulation with a fixed base (E6, `fixed_base`). So is a link welded to such a link
  through more of those fixed joints, since a fixed joint inside an articulation leaves it no freedom.
- **Where it is decided:** in `core/force.py`, from the stage, beside `articulation_holding`, so usd-core unit-tests
  it. A new `held_to_world(stage, body_path) -> bool` shares that function's joint index: one stage traversal
  collects each joint's type, ends and exclusion for both.
- **The message:** `"<path> is held to the world: a fixed joint holds it to the world as the base of the
  articulation at <root>, so no force moves it"`.
- **Not refused:**
  - a joint of another type to the world, such as a revolute one, since the body moves about it;
  - a fixed joint excluded from articulations, which leaves the articulation's base floating and holds the body
    with a separate joint (not measured here, so it errs towards the push);
  - a disabled fixed joint (`physics:jointEnabled` false), which holds nothing;
  - a lone body welded to the world (out of scope).
- **`refusal`'s signature:** `articulation: str | None` becomes `fixed_base: str | None`, the root's path when the
  body is a held link.

### The server

`apply_force`'s description says links are pushed and the robot moves as a whole, and names the fixed base among the
refusals. Its parameters, bounds and hints don't change, and neither does its answer line.

### Alternatives

| Alternative | Why not |
|---|---|
| **The tensor API for links**, the issue's proposal: a `RigidBodyView` of the link, the impulse as impulse / dt for one step | It works (E2 to E5), but today's call already pushes links exactly (E1), and in any Kit app with `omni.physx`. The tensor API adds `omni.physx.tensors`, a frontend (numpy can't take the GPU pipeline, warp needs `omni.warp.core`), the step's length for an impulse, and a row lookup for its glob paths (fact 5) |
| **The tensor API for every body** | It fixes the GPU pipeline too (E8), so it is the follow-up's candidate. Here it would change how a lone body is pushed, the impulse included, for a defect that isn't #58's. That needs its own issue and its own live runs on both pipelines |
| `isaacsim.core.experimental.prims.RigidPrim` | It applies schemas to the user's prims (fact 6) and wraps the same tensor call |
| `PhysxSchema.PhysxForceAPI` | It edits the stage, and pushes at the centre of mass only (fact 9) |
| **The fixed base from PhysX at run time**, the tensor API's `fixed_base` | It needs the tensor API for a refusal, and the root of an articulation whose `ArticulationRootAPI` sits on a joint has no view to ask. The stage gives the same answer for the cases E6 measured, and usd-core tests it |
| No fixed-base refusal | A push on the Franka's base would answer success and move nothing, the silent no-op #59 removed for other bodies |

### For the maintainer

| Call | Recommendation |
|---|---|
| Push links with today's call, or move links to the tensor API as #58 proposed | Today's call: it pushes links exactly in every mode (E1, E10, E11), with nothing new to depend on |
| Refuse a fixed base | Yes. Otherwise a push on the Franka's base answers success and moves nothing (E11) |
| The GPU pipeline, where no push moves anything (E8) | Its own issue, with this plan's tensor API measurements; not this PR |
| #58's title and body, which state a cause the Findings disprove | A comment from the main session linking this plan's Findings, and a title such as "apply_force refuses articulation links that PhysX pushes" |
| AGENTS.md's Traps row (Docs), which fills the file to the gate's 150 lines | Take it: a misread live check is the trap this repo paid for here |

### Files

| File | Change |
|---|---|
| `extension/ovmcp.bridge/ovmcp/core/force.py` | `refusal` takes `fixed_base`; the fixed-base message replaces the link message; `held_to_world`, sharing a joint index with `articulation_holding`; the module docstring |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/simulation.py` | `handle_apply_force` passes `fixed_base` (the root, when `held_to_world`), not `articulation`; its docstring |
| `src/omniverse_mcp/tools/simulation.py` | `apply_force`'s description |
| `tests/test_force.py` | as in Tests |
| `tests/test_scenarios.py` | `test_15_11` rewritten; `test_15_14` and `test_15_15` new; the helpers `_centre_of_mass_along_x` and `_force_pair` |
| docs | as in Docs |

## Compatibility

No one-way door moves.

- **The tool contract:** the name, parameters, defaults, bounds and annotations stay. Only the description changes,
  which `tools/golden.py` strips, so `tests/fixtures/mcp-tools.json` doesn't change.
- **The wire protocol:** `/physics/apply_force` keeps its path, request and answer.
- **What users notice:**
  - A push on an articulation's link works again, where 0.2.1 and 0.2.2 refused it.
  - A push on the base of a fixed-base articulation is still refused, with a message that says why.
  - The fix is in the Kit extension: `uvx omniverse-mcp extension install`, then restart Kit. A new server with a
    0.2.2 extension still gets 0.2.2's refusal, passed through as an error.
- **Kit apps:** as today, any Kit 107+ app with `omni.physx`. Nothing new is needed.

## Steps

1. **The evidence.** Done: E1 to E11 and s9 (Findings).
2. **The core.** `held_to_world` and the joint index, and `refusal`'s new fifth case. Proved by `tests/test_force.py`.
3. **The handler.** It passes `fixed_base`. Proved by the live `test_15_11`, `test_15_14` and `test_15_15`, and by
   the unchanged `test_15_04` to `test_15_12`.
4. **The server.** The description. Proved by `tests/test_contract.py`, unchanged, and `tests/test_tools.py`.
5. **The docs** (Docs), and `test_project/scenarios.md`'s 15.11, 15.14 and 15.15.
6. **The gate,** `uv run tools/gate.py full`; both live suites on Isaac Sim 6.2; then review-code.
7. **The follow-up issue,** opened by the main session: on the GPU pipeline `apply_force` moves nothing and reports
   success (E8), with E2 to E5 and E8 as the tensor API's evidence.

## Tests

**Unit, in CI** (`tests/test_force.py`):

- **The fifth refusal:** a held link is refused with the message above; it comes after "PhysX holds no rigid body"; a
  link that isn't held is pushed. `test_an_articulation_s_link_is_refused_naming_its_issue` goes. The other refusal
  tests pass `fixed_base=None` where they pass `articulation=None` today.
- **`held_to_world` on the `robots` fixture,** with fixed joints added beside its revolute ones:
  - held: a fixed arm's base, which a fixed joint holds to the world; a sensor welded to that base by a second fixed
    joint; the Crane's base, whose `ArticulationRootAPI` is on its fixed joint; a base fixed to a static wall prim,
    which counts as the world;
  - not held: the fixed arm's link beyond a revolute joint; the G1's links, floating; a base held only by a fixed
    joint excluded from articulations, or by a disabled one (`physics:jointEnabled` false); an arm on a revolute
    joint to the world.
- **The parser check stays:** the links `articulation_holding` finds are the articulated bodies UsdPhysics parses.

**`tests/test_tools.py`:** the existing `apply_force` cases pass unchanged.

**Live** (`tests/test_scenarios.py`, by hand on Isaac Sim 6.2):

The live checks compare the change of momentum with the push, never drift with a threshold: #59's lesson. The
measure is `_centre_of_mass_along_x(links)`, through `execute_script`. It reads each link's PhysX pose and
`get_mass_information`, and returns the bodies' centre of mass along X, their mass and the simulation time. s9
checked it against the tensor API's momentum to 1e-5. A speed is its change over 0.3 s of simulation.

- **`test_15_11`, rewritten: a push on the G1's pelvis moves the robot by the push.**
  - Stopped, the G1 is moved 20 units up its stage's up axis, and put back in cleanup. It then falls with nothing to
    touch for about 2 s. Then play.
  - The robot's speed along X is taken before and after `apply_force(pelvis, [100, 0, 0], impulse=True)`. The
    change must be 100 / mass within 2%, about 2.92 m/s (E1: 0.2% drift after a pelvis push).
  - A knee is pushed too, from a fresh play. Its check is looser, the speed's change within 10% of 100 / mass,
    since the G1's joints move its momentum by about 5% after a knee push (E11). The exact check on a link that
    isn't the root is `test_15_14`'s.
- **`test_15_14`, new: a push on a link of a free articulation moves it exactly.**
  - `_force_pair(name, fixed)` builds a two-cube articulation of the test's own, as `_force_body` builds a cube.
    The cubes are 5 kg each on a revolute joint about the up axis, with the root on their Xform, gravity off, away
    from the scene. It is deleted after, with the simulation stopped.
  - Play. `apply_force(second cube, [10, 0, 0], impulse=True)`: the pair's speed along X changes by 1.0 within 2%
    (E1, E11: exact).
- **`test_15_15`, new: a fixed base is refused, and the link beside it is pushed.**
  - `_force_pair(name, fixed=True)` adds a fixed joint from the world to the first cube. Play.
  - `apply_force` on the first cube errors with "held to the world" and the root's path.
  - `apply_force` on the second, sideways: success. The second cube's PhysX pose moves more than 0.01 in 0.5 s,
    while the first cube's stays within 1e-4 (E6).
- `test_15_04` to `test_15_10` and `test_15_12` pass unchanged.

**What neither can show:** Isaac Sim 5.x; the GPU pipeline (E8, the follow-up); every robot's joint layout. The fixed
base rule is tested on the stage shapes the fixture builds, and live on the two-cube articulation. E6 and E11 measured
the Franka.

## Docs

| File | Change |
|---|---|
| `docs/TOOLS.md`, `apply_force` | It pushes a rigid body or an articulation's link. A push on a link moves the whole robot: the robot's momentum changes by the impulse, so its speed changes by impulse / the robot's mass, and the link turns about its joints as well. The refusal table loses the link row and gains the fixed-base row. It says the push is tested on the CPU pipeline, and names the GPU pipeline's issue |
| `README.md`, Known issues | The #58 line goes. A line for the GPU pipeline's issue comes in, once it has a number |
| `CHANGELOG.md`, Unreleased, Fixed | `apply_force` pushes an articulation's links again, such as a robot's. 0.2.1 refused them on a misread measurement: PhysX's push reaches them. A base that a fixed joint holds to the world is still refused. The fix is in the Kit extension (install line) (#58) |
| `plugin/skills/simulate/SKILL.md` | The sentence that it can't push links goes. It says a link moves the robot as a whole, and a fixed base is refused |
| `docs/ARCHITECTURE.md` | `core/force.py`'s entry: "its refusals" names the fixed base |
| `test_project/scenarios.md` | 15.11 rewritten as `test_15_11`; 15.14 and 15.15 added |
| `AGENTS.md`, Traps | A row: a live test's threshold read as a measurement refused pushes PhysX makes (#58); the guard is that force tests compare the change of momentum with the push. 149 lines become 150, the gate's limit |

## Risks

| Risk | Status |
|---|---|
| Today's call misses a link in some mode or state | Resolved by E1, E10 and E11: impulse, force, paused, at a point, in free fall and on the ground, on the root and on other links |
| A robot's own joints move its momentum after a push, so a tight check on a robot can fail on a correct push | Resolved: the G1's checks allow for what E1 and E11 measured (2% on the pelvis, 10% on the knee), and the exact check runs on the two-cube articulation |
| The fixed-base rule differs from what omni.physx builds: a fixed joint to a static prim, a breakable one (`physics:breakForce` finite), `ArticulationRootAPI` on the joint | Accepted. E6 measured a fixed joint to the world, on the Franka and on PairFixed. In the other cases the rule errs towards a refusal, never towards a success that moved nothing; a breakable joint counts as holding |
| The GPU pipeline: today's call pushes nothing on any body and reports success (E8) | Accepted here, the follow-up issue. TOOLS.md says the push is tested on the CPU pipeline |
| A traversal of the whole stage per call grows with the stage | Accepted, as today: `articulation_holding` already traverses it. The shared index keeps it to one traversal |
| Isaac Sim 5.x untested live | Accepted, as for #59. The calls are the same in 107.3.26's stubs |
| #59's own error again: a live check that passes or fails for the wrong reason | Resolved by measuring the change of momentum against the push, within 2% |

## Plan review

Not reviewed yet.
