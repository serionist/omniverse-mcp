---
title: Add set_physics_properties' collision parameter to the tool contract, to give or take away a collider by name
issue: "#150"
status: approved
approved_by: serionist
approved_at: 2026-11-02
---

# Add set_physics_properties' collision parameter to the tool contract, to give or take away a collider by name

`set_physics_properties` gains an optional `collision`: `true` makes the prim a collider (the Collision API, applied
when missing, and `physics:collisionEnabled` on), `false` turns its collision off, and left out it stays as it is.
Today a collider comes only as a side effect of a friction or restitution value, and nothing turns one off; the
outcome scenarios' O4 showed agents applying the API with `execute_script` instead (#146, #150).

## Goal

When this is done:

- **A collider by name:** `set_physics_properties("/World/Floor", collision=True)` makes the floor a static collider,
  with no rigid body and no physics material; `collision=False` turns a collider's collision off and keeps its API.
- **The answer says what changed:** `collision=on`, with `applied CollisionAPI` when the call added it; `collision=off`;
  or why nothing changed.
- **An older extension is named:** a server with this change and a Kit extension without it says the collision wasn't
  set and how to install the server's extension, where the old handler would drop the key silently.
- **O4 has a tool path:** an outcome run of O4 shows whether the agent takes it.

Why, from #150: an agent that wants "a collider" doesn't reach for friction, and `create_prim(enable_physics=True)`
gives a rigid body too, which makes a floor fall.

| In scope | Out of scope |
|---|---|
| The parameter, the client, the handler, the tool's answer and description, the contract fixture | Removing the Collision API (Q2) |
| A Mesh's collision approximation when it moves with a rigid body (Q3) | Setting an approximation by parameter; contact and rest offsets |
| `docs/TOOLS.md`, the `simulate` skill, `outcomes.md`'s O4 tool path, `CHANGELOG.md` | Friction's own Collision API side effect, which stays as it is |
| | A collider for every mesh under an Xform (Q4) |

## What the code says

Read at `6a6982c`.

| # | Finding | Where |
|---|---|---|
| C1 | The tool takes `mass`, `density`, `friction` and `restitution`, each `None` by default, and sends only those given | `src/omniverse_mcp/tools/simulation.py:141-174`; `src/omniverse_mcp/client.py:535-551` |
| C2 | The answer lists each value the extension echoes (`_physics_values`), then the material, the APIs applied, the other prims changed and the old material; with no value echoed it says "Nothing set on ...: give mass, density, friction or restitution" | `tools/simulation.py:25-39`, `:176-191` |
| C3 | The handler refuses an inactive prim, an instance or a prim inside one, and a non-Material child named `PhysMat`, before anything is written, but only when friction or restitution is given (`material_refusal`) | `handlers/simulation.py:140-143`; `ovmcp/core/material.py:179-204` |
| C4 | Friction or restitution applies `UsdPhysics.CollisionAPI` when missing and names it in `applied` | `handlers/simulation.py:167-170` |
| C5 | Mass or density applies `RigidBodyAPI` and `MassAPI`, naming both | `handlers/simulation.py:146-157` |
| C6 | `create_prim(enable_physics=True)` applies `RigidBodyAPI` and `CollisionAPI` on the prim itself; the meshes under an Xform get none | `handlers/scene.py:348-350`; the tool's description |
| C7 | An unknown key in the request body is ignored: the 0.4.1 handler would answer success for `collision` alone, and the tool would say "Nothing set" | `handlers/simulation.py:123-207` |
| C8 | Unit tests: the handler on a usd-core stage with a fake Kit (`BOX` is a Cube with `RigidBodyAPI`); the tool's answers against the mock bridge; the live 15.1 to 15.3 | `tests/test_physics_handler.py`; `tests/test_force_handler.py:30`, `:144-146`; `tests/test_tools.py:700-830`; `tests/test_scenarios.py:1762-1886` |
| C9 | The `simulate` skill says `create_prim(..., enable_physics=True)` gives a rigid body and collision, `set_physics_properties` sets mass, density, friction and restitution, and "Without a collider an object falls through the ground" | `plugin/skills/simulate/SKILL.md:22-24` |

What the APIs say (usd-core 26.11, read in this worktree; Isaac Sim's physics docs through Context7):

| # | Fact | Source |
|---|---|---|
| U1 | `physics:collisionEnabled` falls back to true: an applied, unauthored Collision API collides | `UsdPhysics.CollisionAPI.GetCollisionEnabledAttr()` |
| U2 | `physics:approximation` (MeshCollisionAPI) falls back to `none`, a triangle mesh; also `convexHull`, `convexDecomposition`, `boundingSphere`, `boundingCube`, `meshSimplification` | `UsdPhysics.MeshCollisionAPI.GetApproximationAttr()`'s allowed tokens |
| U3 | The Collision API alone is a static collider; with `RigidBodyAPI` on the same prim, a dynamic one | Isaac Sim's physics-simulation skill (Context7, `/isaac-sim/isaacsim`) |
| U4 | `CollisionAPI.CanApply` is true on an Xform, where PhysX makes no shape: only a gprim collides | usd-core; UsdPhysics' collision schema |

## Design

### The parameter

`collision: bool | None = None`, described as "true makes the prim a collider (the Collision API); false turns its
collision off; left out, as it is". The client sends it only when given, as the other four (C1).

### The handler

The rules that need no Kit (which prims may take a collider, the approximation, the echo) live in a new
`ovmcp/core/collision.py`, tested on usd-core; the handler calls them. Before anything is written, with `collision`
given:

- **Refused** where a collider can't be made or wouldn't collide, in words of its own (not `material_refusal`'s, which
  speak of physics materials and would refuse an instanceable gprim, against Q5):
  - an inactive prim: activate it first;
  - an instance proxy (a prim inside an instance): its colliders belong in the referenced asset, or the instance
    needs `instanceable` turned off; the error names the instance;
  - a prim whose type PhysX makes no shape for: only `Cube`, `Sphere`, `Capsule`, `Cylinder`, `Cone`, `Mesh` and
    `Plane` collide (U4; usd-core also counts curves and `TetMesh` as gprims). An Xform's error names up to five such
    prims under it and their count, so the next calls can take them; when they lie inside an instance, it says so
    instead, since those calls would be refused too (Q4).

  The other values given with it aren't written either, as C3 does for friction.
- **The order:** mass and density first, then friction and restitution, then `collision`, so a body or a Collision
  API the same call makes counts: a Mesh given `mass` and `collision=True` together gets its approximation, and a
  `collision=False` with a friction ends with the API, from friction, and collision off.
- **`true`:** apply the Collision API when missing (named in `applied`), and set `physics:collisionEnabled` to true
  when it is authored false; when the prim is a `UsdGeom.Mesh` that moves with a rigid body (its own `RigidBodyAPI` or
  an ancestor's), the body isn't kinematic (PhysX keeps triangle meshes on a kinematic body), and no
  `physics:approximation` is authored, author `convexHull` through `MeshCollisionAPI` (Q3).
- **`false`:** set `physics:collisionEnabled` to false on a prim with the Collision API; a prim without one is left as
  it is (Q2).
- **The echo:** `collision`, the composed `physics:collisionEnabled` read back after the write, so a stronger layer's
  opinion shows as it stands; `"collider": false` when `false` met a prim with no Collision API, so "had none" isn't
  read as an older extension; `"approximation": "convexHull"` when the call authored it; and `"body"`, the rigid
  body's path, when the prim is one or lies under one (Q6).

Friction with `collision=True` gives one Collision API, named once.

### The tool's answer

- `collision=on`, `collision=off` or `collision=off (it had no collider)` (from `"collider": false`) beside the other
  values; `applied CollisionAPI` and `approximation convexHull` as the handler says.
- "Nothing set" names `collision` among the values to give.
- **An older extension:** `collision` sent and absent from the echo means the extension dropped it: the answer gains
  `WARNING: collision not set: the Kit extension is X, this server's is Y`, with `install_advice()`, as the camera and
  recording tools write their warnings; when a friction or restitution was sent too, it adds that the old extension
  did apply the Collision API for it.
- **The description's lead line** names a collider: "Set a prim's mass or density, friction or restitution, or make it
  a collider or turn its collision off, for PhysX", so an agent that wants a collider finds it.

### Alternatives

| Alternative | Taken? | Why |
|---|---|---|
| A tool of its own, `set_collision` | No | Another tool for the agent to find; the physics values already live here, and the description already talks of the Collision API |
| `create_prim`'s `enable_physics` on an existing prim | No | It applies a rigid body too (C6), which makes a floor fall |
| `false` removes the Collision API | No (Q2) | Removing an API a referenced layer applied writes a delete in the edit layer, and loses any collision attributes' meaning; disabling is the schema's own switch and undoes cleanly |
| Leave a dynamic Mesh's approximation to PhysX | No (Q3) | PhysX can't simulate a triangle mesh on a moving body; leaving `none` relies on its fallback, with a warning in the log |

### Decisions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | The parameter's name and type | `collision: bool \| None = None`, left out meaning unchanged, as the other four; the USD attribute's own word, and short |
| Q2 | What `false` does | Turn `physics:collisionEnabled` off and keep the API: the schema's own switch, undone by `true`; a prim without the API is left as it is and the answer says so |
| Q3 | A Mesh | A static Mesh keeps PhysX's `none`, an exact triangle mesh; a Mesh that moves with a rigid body, its own or an ancestor's, and has no approximation authored gets `convexHull`, which PhysX can simulate; an approximation already authored is kept |
| Q4 | A prim PhysX makes no shape for, such as an Xform root over meshes | Refuse, naming up to five prims under it that collide and their count, or saying they lie inside an instance; a collider for every mesh under it waits for an issue of its own |
| Q5 | An inactive prim, a prim inside an instance | Refuse before anything is written, in words of their own (activate it; the instance's colliders belong in its asset); an instanceable gprim itself is editable and takes it |
| Q6 | A gprim under a rigid body, or the rigid body itself | Both take it: under a body it becomes one of the body's shapes, on the body a dynamic collider (U3); the answer names the body |
| Q7 | Whether `collision=True` alone binds a physics material | No: friction or restitution does that; the collider uses the scene's default until then |
| Q8 | The answer | `collision=on`, `collision=off`, `collision=off (it had no collider)` (an echo key of its own), with `applied CollisionAPI`, `approximation convexHull` and `part of the rigid body <path>` when they apply |

## Compatibility

**One-way door: the tool contract** (`AGENTS.md`): `set_physics_properties` gains a parameter in its schema.
`tests/fixtures/mcp-tools.json` is rewritten with `uv run tools/golden.py`, and `CHANGELOG.md` names it under Added; an
added optional parameter breaks no call. The PR's title names the tool contract.

**The extension:** the server sends `collision` only when given, so a call without it is unchanged on any extension; a
call with it on an extension of 0.4.1 or older gets the answer that names the older extension (C7). The extension's
settings, routes and protocol are unchanged.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | `ovmcp/core/collision.py` and the handler: refusals, the order, `true`, `false`, the approximation, the echo | `tests/test_collision.py` (the core, on usd-core) and `tests/test_physics_handler.py`: a static Cube gets the API and no rigid body or material; `false` authors `physics:collisionEnabled` false and keeps the API; `false` on a prim without one writes nothing and echoes `"collider": false`; a dynamic Mesh gets `convexHull`, a kinematic or static one none, a Mesh with one authored keeps it; a Mesh given `mass` and `collision=True` in one call gets `convexHull`; `collision=False` with a friction ends with the API and collision off; a gprim under a rigid body names the body; an inactive prim, an instance proxy, a `BasisCurves` and an Xform are refused with nothing written, the Xform's error naming its colliding prims, or the instance when they lie inside one; `collision=True` with a friction names the API once |
| 3 | The client and the tool: the parameter, the answer, the description's lead line, "Nothing set", the older extension; the contract with it | `tests/test_tools.py`: each answer against the mock bridge, the body sent, an echo without `collision` giving the `WARNING` line and, with a friction, the API it did apply; `tests/test_client.py`: the body has `collision` only when given; `uv run tools/golden.py` in this step, so the fixture never lags the tool |
| 4 | The contract checked | `tests/test_contract.py` |
| 5 | Docs | `docs/TOOLS.md`, the `simulate` skill, `outcomes.md`'s O4 path, `CHANGELOG.md` |
| 6 | Live | `tests/test_scenarios.py`: a new `test_15_02d` (`test_15_02c` is taken), a box falling onto a floor made a collider by `collision=True` rests on it, and off again it falls through; the live suites whole on a Z-up and a Y-up stage; `uv run tools/scenarios.py run --phases none --outcomes O4` |
| 7 | `finish-work`: the gate in full, `review-code` | the review record |

## Tests

- **Unit (CI):** step 2's handler tests and step 3's tool and client tests; `test_contract.py` on the new fixture.
- **Live, by hand:** on a headless Isaac Sim 6.2 at 8212 with this branch's bridge: `test_15_02d`, then both suites on
  a Z-up and a Y-up stage; then O4 in an outcome run, whose calls show whether the agent takes `collision`.
- **What neither shows:** PhysX's behaviour on a dynamic Mesh left at `none` elsewhere (Q3 authors `convexHull`, so
  this change never leaves one); Kit apps other than Isaac Sim 6.2.

## Docs

- `docs/TOOLS.md`: the parameter's row and a bullet; the task table's line "set mass or friction" names a collider;
  raycast's "Colliders only" bullet names `collision=True`.
- `README.md`'s Physics row ("Mass, friction and bounce; push an object; cast a ray") names a collider.
- `plugin/skills/simulate/SKILL.md`: step 2, a static collider, such as a floor, with `collision=True`; its
  description's lead names colliders, so an agent with a collider to make loads it.
- `AGENTS.md`'s `ovmcp/core` list and `docs/ARCHITECTURE.md`, where they list the core's modules: `collision.py`.
- `test_project/outcomes.md`: O4's tool path in the header names `collision=True`.
- `CHANGELOG.md`, Added: the parameter, and that the fix to O4's path is in the Kit extension too.

## Risks

| Risk | What then |
|---|---|
| An agent passes a floor's Xform root, as Isaac Sim's own ground plane and many assets have one, and is refused | Accepted: the error names the gprims under it, so the next calls take them (Q4) |
| `convexHull` changes how a dynamic Mesh collides compared with PhysX's own fallback | Accepted: the fallback is a convex hull too, with a warning; authoring it says so in USD, and an approximation already authored is kept |
| A collider made with `collision=True` and no material uses the scene's default friction | Accepted: as any collider without a material; a friction in the same call binds one |
| A Gprim inside an instance can't take the API | Refused before anything is written, naming the instance |
| A Mesh made a collider, then given a mass in a later call, keeps no approximation, and PhysX falls back to a convex hull with a warning | Accepted: the same call orders them (mass first); a later mass call is mass's own path, which this change leaves as it is |
| A stronger layer's `physics:collisionEnabled` hides the write | The echo reads the composed value back, so the answer shows it as it stands |

## Plan review

### Round 1

**How:** one fresh reviewer on Claude Opus 5.5, every lens, 2026-11-02, at `8103572` (drafted by a fork of the main
session, reviewed by an agent that had seen neither). **Verdict:** needs-fixes, minors only, so no second round.
**Now:** every finding fixed; the owner calls wait for the maintainer, and with them the agreement the one-way door
needs.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | The approximation looked for a rigid body before the same call's `mass` made one: a Mesh given `mass` and `collision=True` together got no `convexHull`, and the answer named no body | fixed: the order is mass and density, then friction and restitution, then `collision`; step 2 tests the Mesh case; a later mass call is a Risks row |
| P2 | minor | The echo had no way to say "had no collider": leaving `collision` out would read as an older extension | fixed: `"collider": false` |
| P3 | minor | `material_refusal`'s words speak of physics materials, send the agent to the parent, and would refuse an instanceable gprim, against Q5 | fixed: refusals of their own |
| P4 | minor | An instanced Xform root's error named gprims the next call would refuse, or none | fixed: the error says they lie inside an instance |
| P5 | minor | `collision=False` with a friction: friction applies the API after `false`, so the answer said "no collider" and the prim collided | fixed: `collision` runs last, so the prim ends with the API and collision off |
| P6 | minor | `test_15_02c` is taken | fixed: `test_15_02d` |
| P7 | minor | `README.md`'s Physics row wasn't in Docs | fixed |

**Refuted:** the older extension's detection fails (the 0.4.1 handler builds its result from fixed keys and never
echoes `collision`, so the tool's check fires); a weaker layer's `collisionEnabled` false hides the write (the edit
target's opinion is stronger; a stronger layer is a Risks row, and the echo now reads the composed value back);
`collision=True` with a friction applies the API twice (both paths check first); a protocol bump is needed (an
optional key, as #105 and #113 added, leaves `PROTOCOL` alone); the handler blocks Kit's loop (it stays async, no
executor).

**Owner calls:** Q1 to Q8, in Design, Decisions for the maintainer; the reviewer agrees with each, as amended by P1,
P2, P3 and P4. **The one-way door** needs the maintainer's agreement on #150 (`AGENTS.md`, One-way doors), beside
`approved_by`.

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 to Q8 | Design's table | As recommended there | As recommended, and the tool contract's new parameter agreed (serionist, 2026-11-02) |

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Name a collider in the description's lead line, the `simulate` skill's description and TOOLS.md's raycast bullet, so an agent finds the parameter | taken |
| I2 | Accept only the shapes PhysX collides (curves and `TetMesh` are gprims too) | taken |
| I3 | No `convexHull` on a kinematic body, where PhysX keeps triangle meshes | taken |
| I4 | Echo the composed `physics:collisionEnabled` read back | taken |
| I5 | The older-extension note as a `WARNING:` line, and saying friction's API was applied | taken |
| I6 | The Kit-free rules in `ovmcp/core/collision.py`, listed in `AGENTS.md` and ARCHITECTURE | taken |
| I7 | `golden.py` in step 3, with the parameter | taken |
