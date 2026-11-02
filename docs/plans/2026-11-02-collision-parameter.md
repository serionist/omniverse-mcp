---
title: Add set_physics_properties' collision parameter to the tool contract, to give or take away a collider by name
issue: "#150"
status: draft
approved_by:
approved_at:
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

Before anything is written, with `collision` given:

- **Refused** where a collider can't be made or wouldn't collide: an inactive prim, an instance proxy (a prim inside
  an instance), in the words `material_refusal` already uses (C3); and a prim that isn't a `UsdGeom.Gprim` (U4), whose
  error names up to five gprims under it and their count, so the next call can take them one by one (Q4). The other
  values given with it aren't written either, as C3 does for friction.
- **`true`:** apply the Collision API when missing (named in `applied`), and set `physics:collisionEnabled` to true
  when it is authored false; when the prim is a `UsdGeom.Mesh` that moves with a rigid body (its own `RigidBodyAPI` or
  an ancestor's) and has no `physics:approximation` authored, author `convexHull` through `MeshCollisionAPI` (Q3).
- **`false`:** set `physics:collisionEnabled` to false on a prim with the Collision API; a prim without one is left as
  it is, and the answer says it has no collider (Q2).
- **The echo:** `collision` in the result as `true`, `false` or absent; `"approximation": "convexHull"` when the call
  authored it; and `"body"`, the rigid body's path, when the prim is one or lies under one (Q6).

Mass, density, friction and restitution keep their paths: `collision=True` with a friction gives one Collision API,
named once.

### The tool's answer

- `collision=on`, `collision=off` or `collision=off (it had no collider)` beside the other values; `applied
  CollisionAPI` and `approximation convexHull` as the handler says.
- "Nothing set" names `collision` among the values to give.
- **An older extension:** `collision` sent and absent from the echo means the extension dropped it: the answer says
  "collision not set: the Kit extension is X, this server's is Y", with `install_advice()`, as `get_sim_state` does.

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
| Q4 | A prim that isn't a gprim, such as an Xform root over meshes | Refuse, naming up to five gprims under it and their count; a collider for every mesh under it waits for an issue of its own |
| Q5 | An inactive prim, a prim inside an instance | Refuse before anything is written, in `material_refusal`'s words, as friction is; an instanceable gprim itself is editable and takes it |
| Q6 | A gprim under a rigid body, or the rigid body itself | Both take it: under a body it becomes one of the body's shapes, on the body a dynamic collider (U3); the answer names the body |
| Q7 | Whether `collision=True` alone binds a physics material | No: friction or restitution does that; the collider uses the scene's default until then |
| Q8 | The answer | `collision=on`, `collision=off`, `collision=off (it had no collider)`, with `applied CollisionAPI`, `approximation convexHull` and `part of the rigid body <path>` when they apply |

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
| 2 | The handler: refusals, `true`, `false`, the approximation, the echo | `tests/test_physics_handler.py` on a usd-core stage: a static Cube gets the API and no rigid body or material; `false` authors `physics:collisionEnabled` false and keeps the API; `false` on a prim without one writes nothing; a dynamic Mesh gets `convexHull`, a static one no approximation, a Mesh with one authored keeps it; a gprim under a rigid body names the body; an inactive prim, an instance proxy and an Xform are refused with nothing written, the Xform's error naming its gprims; `collision=True` with a friction names the API once |
| 3 | The client and the tool: the parameter, the answer, "Nothing set", the older extension | `tests/test_tools.py`: each answer against the mock bridge, the body sent, an echo without `collision` naming the older extension; `tests/test_client.py`: the body has `collision` only when given |
| 4 | The contract | `uv run tools/golden.py`; `tests/test_contract.py` |
| 5 | Docs | `docs/TOOLS.md`, the `simulate` skill, `outcomes.md`'s O4 path, `CHANGELOG.md` |
| 6 | Live | `tests/test_scenarios.py`: a new `test_15_02c`, a box falling onto a floor made a collider by `collision=True` rests on it, and off again it falls through; the live suites whole on a Z-up and a Y-up stage; `uv run tools/scenarios.py run --phases none --outcomes O4` |
| 7 | `finish-work`: the gate in full, `review-code` | the review record |

## Tests

- **Unit (CI):** step 2's handler tests and step 3's tool and client tests; `test_contract.py` on the new fixture.
- **Live, by hand:** on a headless Isaac Sim 6.2 at 8212 with this branch's bridge: `test_15_02c`, then both suites on
  a Z-up and a Y-up stage; then O4 in an outcome run, whose calls show whether the agent takes `collision`.
- **What neither shows:** PhysX's behaviour on a dynamic Mesh left at `none` elsewhere (Q3 authors `convexHull`, so
  this change never leaves one); Kit apps other than Isaac Sim 6.2.

## Docs

- `docs/TOOLS.md`: the parameter's row and a bullet; the task table's line "set mass or friction" names a collider.
- `plugin/skills/simulate/SKILL.md` step 2: a static collider, such as a floor, with `collision=True`.
- `test_project/outcomes.md`: O4's tool path in the header names `collision=True`.
- `CHANGELOG.md`, Added: the parameter, and that the fix to O4's path is in the Kit extension too.

## Risks

| Risk | What then |
|---|---|
| An agent passes a floor's Xform root, as Isaac Sim's own ground plane and many assets have one, and is refused | Accepted: the error names the gprims under it, so the next calls take them (Q4) |
| `convexHull` changes how a dynamic Mesh collides compared with PhysX's own fallback | Accepted: the fallback is a convex hull too, with a warning; authoring it says so in USD, and an approximation already authored is kept |
| A collider made with `collision=True` and no material uses the scene's default friction | Accepted: as any collider without a material; a friction in the same call binds one |
| A Gprim inside an instance can't take the API | Refused before anything is written, as friction is |

## Plan review

Not reviewed yet.
