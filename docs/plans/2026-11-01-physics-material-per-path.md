---
title: Give each prim its own physics material in set_physics_properties
issue: "#113"
status: draft
approved_by:
approved_at:
---

# Give each prim its own physics material in set_physics_properties

## Goal

`set_physics_properties` binds a physics material named after the prim's last name,
`/World/PhysicsMaterials/<prim name>_PhysMat`, so prims of one name share it: `/World/Franka_1/panda_leftfinger` and
`/World/Franka_2/panda_leftfinger` both bind `panda_leftfinger_PhysMat`. Since #105 (its R7) each call writes all three
values, starting from the body's own, which widens the cross-talk: `friction=1.0` on Franka_1's finger, then
`restitution=0.2` on Franka_2's, writes Franka_2's old friction over Franka_1's 1.0. When this is done, each prim's
material is named after its whole path, and a call on one prim writes only into that prim's material.

- **In scope:** the material's path, from the prim's whole path (the maintainer's choice, #105's Q9 and #113); what
  becomes of a prim bound to an older extension's shared `<prim name>_PhysMat`; the tool's description,
  `docs/TOOLS.md`, `CHANGELOG.md` with #105's sentence that names #113, and the tests, `test_15_02b` among them.
- **Out of scope:**
  - `set_material`'s look material, `/World/Looks/<prim name>`, shared by name the same way: it has `material_path`
    to keep prims apart, and its description says so;
  - the values a call writes and where they start from: #105's R7 and Q8, unchanged;
  - deleting an older extension's shared material once no prim binds it (Q3).

## What the code says

At `f5a27ed`:

| # | What | Where |
|---|---|---|
| C1 | The path is `/World/PhysicsMaterials/{prim_name}_PhysMat`, `prim_name` the request's last component; `UsdShade.Material.Define` and `MaterialAPI` when missing, which makes any missing ancestor a typeless `def` | `handlers/simulation.py:151-157` |
| C2 | Before writing, `physics_source(prim)` finds the physics material bound to the prim (physics purpose, else all-purpose, with `MaterialAPI`), else the physics scene's default, else PhysX's; `start_from` copies its physics attributes into the tool's material, and does nothing when the two are one | `core/material.py` |
| C3 | The binding is replaced on the prim alone, purpose `physics`; a material bound before is never written | `handlers/simulation.py:165-170`; #105's code review, round 2, "I8 reaching other materials" |
| C4 | The answer echoes the values given and the APIs applied, and no material | `handlers/simulation.py:173-183`, `tools/simulation.py` `_physics_values` |
| C5 | `clone_prim` copies the prim's spec with `Sdf.CopySpec`, its binding's target as it is, so a clone binds its original's material | `handlers/scene.py:474` |
| C6 | `get_prim_properties` and `get_scene_tree` show no material binding: the description is where an agent learns the material's path | `core/formatter.py` |
| C7 | The path is written in the tool's description, `docs/TOOLS.md:943`, `CHANGELOG.md:51-52`, `tests/test_material.py`, `tests/test_physics_handler.py` and `test_15_02b`'s cleanup | `tests/test_scenarios.py:1535` |

Checked on usd-core 26.11: each component of a valid prim path is a valid prim name, and so is one with `_PhysMat`
added, UTF-8 names included (`Sdf.Path.IsValidIdentifier("café")`); `MakeRelativePath(Sdf.Path.absoluteRootPath)`
and `ReplaceName` build the mirrored path. A Python walk over a stage of 104,000 prims, reading one relationship of
each, took 0.18 s (Q3).

## Design

### The path (Q1)

With Q1's A, the material mirrors the prim's path under `/World/PhysicsMaterials`, its last name with `_PhysMat`
added:

| Prim | Material |
|---|---|
| `/World/Franka_1/panda_leftfinger` | `/World/PhysicsMaterials/World/Franka_1/panda_leftfinger_PhysMat` |
| `/World/Franka_2/panda_leftfinger` | `/World/PhysicsMaterials/World/Franka_2/panda_leftfinger_PhysMat` |
| `/World/Cube` | `/World/PhysicsMaterials/World/Cube_PhysMat` |

- **Unique:** two prims have two paths, so two materials. The suffix keeps a prim's material apart from the level
  that holds its children's: `.../World/Franka_1_PhysMat` beside `.../World/Franka_1/`.
- **Valid at any length:** each name is the prim's own, or its last with `_PhysMat` added; USD caps neither a name
  nor a path.
- **Grouped:** the levels between `/World/PhysicsMaterials` and the material are `Scope`s, made when missing, so one
  robot's materials sit under one Scope, and deleting it deletes them. `/World/PhysicsMaterials` itself is made a
  Scope when missing; one an older extension made, typeless, stays as it is.
- **From the prim:** the path comes from `prim.GetPath()`, not the request's string.

`core/material.py` gains `physics_material_path(prim_path)`, the path, and `own_physics_material(stage, prim_path)`,
which makes what is missing (the Scopes, the `Material`, its `MaterialAPI`) and returns the material. A `Material`
already there is kept, as today.

### A prim bound to an older extension's shared material

No new code: R7's first step reads the prim's values from whatever physics material it is bound to, the shared
`<prim name>_PhysMat` included, `start_from` copies all it holds into the prim's own, the values given are written,
and the binding moves to the prim's own. The shared one is not written again (Risks: a prim at the stage's root) and
stays, bound to the prims a call hasn't reached, which keep their values. It is not deleted: whether another prim
still binds it takes a walk over the stage (Q3).

### The answer names the material (Q2)

With Q2's A, the extension's answer carries `material`, the path it bound, and the server prints it between the
values and the APIs:

`Physics on /World/RedCube: friction=0.8 (static and dynamic), restitution=0.3; material /World/PhysicsMaterials/World/RedCube_PhysMat; applied PhysicsMaterial`

An older extension's answer has no `material`, and the server prints none. `PROTOCOL` stays 1.

## Decisions for the maintainer

| # | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | How does the prim's whole path become the material's? | **A.** Mirror it, `/World/PhysicsMaterials/World/Franka_1/panda_leftfinger_PhysMat`, the levels between as Scopes. Unique by construction, one robot's materials under one Scope; the Scopes repeat the names of the prim's ancestors (`World`, `Franka_1`), so a search by name finds them too, and `get_scene_tree` lists more levels. **B.** Join it into one name, `/World/PhysicsMaterials/World_Franka_1_panda_leftfinger_PhysMat`. One level, readable; but `/World/table_top/box` and `/World/table/top_box` join to one name and share again, and the name grows with the path. **C.** The last name and a hash of the path, `panda_leftfinger_3f9a1c07_PhysMat`. Short and unique in practice, but it doesn't say which Franka's it is | A: unique without a hash or a check, and it reads as the prim's path | |
| Q2 | Does the answer name the material it bound? | **A.** Yes: a `material` field, which the server prints. The path is longer now, no tool shows a binding (C6), and an older extension's path differs from the description's, so the answer is the one place that says it for certain. **B.** No: the description gives the rule | A: one field and one clause, as #104 made the answers say what the call did | |
| Q3 | Does a call walk the stage for other prims bound to the material it writes? A clone from `clone_prim`, Kit's Duplicate or Isaac Lab's cloner binds its original's material (C5), so a call on the original changes a clone a call hasn't reached yet; and an older extension's shared material stays after the last prim leaves it | **A.** No walk: as on `main`, a clone shares its original's material until a call on the clone gives it its own, and a shared material no prim binds stays. **B.** A walk each call, 0.18 s per 100,000 prims on usd-core and on Kit's main thread: the answer warns when another prim binds the prim's own material, and a shared one no prim binds any more is deleted | A: a clone's binding is the copy's own, as an asset's shared material is; the walk costs every call on a large stage, and an unbound material changes no body | |

## Compatibility

- **One-way doors:** none. The tool's name, schema and annotations stay (`tests/fixtures/mcp-tools.json`;
  `tools/golden.py` leaves descriptions out). The route keeps its path and, with Q2's A, gains the answer field
  `material`.
- **What users notice:** a call's material moves from `/World/PhysicsMaterials/<prim name>_PhysMat` to
  `/World/PhysicsMaterials/<prim path>_PhysMat`. A script that read the old path finds the old material, bound to the
  prims no call has reached since the upgrade; a prim moves to its own on its next call, with the values it had. It
  ships with #105 in 0.4.0, so no release writes all three values into a material prims of one name share.
- **An older extension with this server:** the description names the new path, the extension binds the old one, and
  its answer has no `material`; `get_sim_state`'s note already says to install the server's extension.
- **Kit apps:** plain USD, so every Kit app.

## Steps

Each step passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 1 | `core/material.py`: `physics_material_path`, `own_physics_material` | `tests/test_material.py` |
| 2 | `handle_set_physics_properties` binds the prim's own material; with Q2's A, answers `material` | `tests/test_physics_handler.py` |
| 3 | The server: the description; with Q2's A, the answer's clause | `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | `test_15_02b`: the twins and the cleanup | live, run by the main session |
| 5 | The docs (below) | `uv run tools/gate.py full` |

## Tests

| Test | What it shows |
|---|---|
| `tests/test_material.py` | The path of `/World/Franka_1/panda_leftfinger`, `/World/Cube`, a root prim `/Box` and a UTF-8 name; two prims of one name under two parents get two paths. `own_physics_material` makes the Scopes, the `Material` and `MaterialAPI`, keeps a material already there, and leaves an existing typeless `/World/PhysicsMaterials` as it is |
| `tests/test_physics_handler.py` | `OWN` becomes `/World/PhysicsMaterials/World/Box_PhysMat`. The issue's case: two prims of one name under two parents, `friction=1.0` on one, then `restitution=0.2` on the other; the first keeps its 1.0 and its restitution, each bound to its own material. A prim bound to an older extension's `/World/PhysicsMaterials/Box_PhysMat`, which another prim of its name binds too: it moves to its own, holding the shared one's values and the one given, and the shared one is unchanged and still bound to the other. With Q2's A, the answer's `material` |
| `tests/test_tools.py` | With Q2's A: the clause printed from `material`, and none for an older extension's answer without it |
| `tests/test_contract.py` | `test_a_description_says_what_the_tool_now_does` gains `set_physics_properties`' path |
| `test_15_02b` (live) | Two bare boxes of one name under two parents slide on its floor: `friction=0.9` on one, then `restitution=0` on the other. The first slides as the Rubber control (friction 0.9) does, within 0.05, where on `main` the second call wrote PhysX's 0.5 into the material they shared. Its other bodies' materials, now at mirrored paths, show PhysX reads a material under Scopes. Its cleanup deletes `/World/PhysicsMaterials/World/IntTestFriction` |

- **Live:** `test_15_01`, `test_15_02` and `test_15_02b` on Isaac Sim 6.2, on either up axis: the path doesn't
  depend on it.
- **What neither shows:** a stage of Isaac Lab's size; USD Composer.

## Docs

| File | What |
|---|---|
| `src/omniverse_mcp/tools/simulation.py` | The description: a physics material of the prim's own, `/World/PhysicsMaterials/<prim path>_PhysMat` (`/World/PhysicsMaterials/World/Cube_PhysMat` for `/World/Cube`); the sentence on prims of one name goes |
| `docs/TOOLS.md` | `set_physics_properties`: the path with an example; a prim bound to an older extension's shared material moves to its own on its next call, and the old one stays for the prims still bound to it; the sentence on an extension of 0.3.0 or older names its path. With Q2's A, Returns names the material |
| `CHANGELOG.md` | #105's Fixed bullet loses its sentence "Prims of one name still share the material, ... until #113 gives each prim its own." A Fixed bullet of its own, below |
| `docs/ARCHITECTURE.md` | The core list's `material.py`: the physics material's path too |

The Fixed bullet, as drafted:

- **`set_physics_properties` gives each prim a physics material of its own,** named after its whole path:
  `/World/PhysicsMaterials/World/Franka_1/panda_leftfinger_PhysMat`. It was named after the prim's last name, so
  prims of one name, such as two Frankas' fingers, shared one, and setting one set the other. A prim bound to such a
  shared material moves to its own on its next call, with the values it had; the shared one stays for the prims still
  bound to it. The fix is in the Kit extension (#113).

## Risks

| Risk | Status |
|---|---|
| A prim at the stage's root, `/Box`, gets `/World/PhysicsMaterials/Box_PhysMat`, the name an older extension gave every prim named Box: a call on `/Box` writes into it while other Box prims an older extension bound still use it. B has the same case, C not | Accepted: Isaac Sim and USD Composer put a scene under `/World`; it takes a root prim and another of its name given physics before the upgrade, and a call on that other prim moves it to its own |
| A prim named `<x>_PhysMat` with children, beside a prim named `<x>`: the children's materials sit under `<x>`'s material | Accepted: each still has its own path and values, and such a name is the tool's own suffix |
| The Scopes repeat the names of the prim's ancestors, so a search by name finds them (Q1) | Accepted with Q1's A: they hold no geometry, body or articulation, and PhysX's tensor views take only the rigid bodies or articulations a pattern matches (`omni.physics.tensors` 110.4.4, `api.py`, `create_rigid_body_view`) |
| A clone shares its original's material, so a call on the original changes it | Q3 |
| Kit's PhysX doesn't read a material under Scopes | Open until the live `test_15_02b` runs |

## Plan review

Not yet reviewed.
