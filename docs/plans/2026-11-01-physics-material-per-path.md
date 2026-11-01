---
title: Give each prim its own physics material in set_physics_properties
issue: "#113"
status: approved
approved_by: serionist
approved_at: 2026-11-01
---

# Give each prim its own physics material in set_physics_properties

## Goal

`set_physics_properties` binds a physics material named after the prim's last name,
`/World/PhysicsMaterials/<prim name>_PhysMat`, so prims of one name share it: `/World/Franka_1/panda_leftfinger` and
`/World/Franka_2/panda_leftfinger` both bind `panda_leftfinger_PhysMat`. Since #105 (its R7) each call writes all three
values, starting from the body's own, which widens the cross-talk: `friction=1.0` on Franka_1's finger, then
`restitution=0.2` on Franka_2's, writes Franka_2's old friction over Franka_1's 1.0. When this is done, each prim's
material is its own, a child of the prim, a call on one prim writes only into that prim's material, and the answer
says which other prims a write still reaches.

- **In scope:** the material's path, a child of the prim (Q1's D); what becomes of a prim bound to an older
  extension's shared `<prim name>_PhysMat`, and deleting that one once no prim binds it (Q4's A); copies and clones of
  a prim that has its material, and the warning that names the other prims a write changes (Q3's B); the answer
  naming the material (Q2's A); the tool's description, `docs/TOOLS.md`, `CHANGELOG.md` with #105's sentence that
  names #113, scenario 15.2, and the tests, `test_15_02b` among them.
- **Out of scope:**
  - `set_material`'s look material, `/World/Looks/<prim name>`, shared by name the same way: it has `material_path`
    to keep prims apart, and its description says so;
  - the values a call writes and where they start from: #105's R7 and Q8, unchanged;
  - an older extension's shared material bound to no prim this call moved: Q4 deletes only the one the call moved
    the prim off.

## What the code and the sources say

At `f5a27ed`:

| # | What | Where |
|---|---|---|
| C1 | The path is `/World/PhysicsMaterials/{prim_name}_PhysMat`, `prim_name` the request's last component; `UsdShade.Material.Define` and `MaterialAPI` only when no prim is there (`if not mat_prim.IsValid()`), and Define makes any missing ancestor a typeless `def` | `handlers/simulation.py:151-157` |
| C2 | Before writing, `physics_source(prim)` finds the physics material bound to the prim (physics purpose, else all-purpose, with `MaterialAPI`), else the physics scene's default, else PhysX's; `start_from` copies its physics attributes into the tool's material, and does nothing when the two are one | `core/material.py` |
| C3 | The binding is replaced on the prim alone, purpose `physics`; a material bound before is never written | `handlers/simulation.py:165-170`; #105's code review, round 2, "I8 reaching other materials" |
| C4 | The answer echoes the values given and the APIs applied, and no material | `handlers/simulation.py:173-183`, `tools/simulation.py` `_physics_values` |
| C5 | `clone_prim` copies the prim's spec with `Sdf.CopySpec`, which keeps a binding's target outside the copied tree and maps one inside it to the copy | `handlers/scene.py:474`; checked on usd-core 26.11 (round 1's `check113.py`) |
| C6 | `get_prim_properties` and `get_scene_tree` show no material binding: the description is where an agent learns the material's path | `core/formatter.py` |
| C7 | The path is written in the tool's description, `docs/TOOLS.md:943`, `CHANGELOG.md:51-52`, `tests/test_material.py`, `tests/test_physics_handler.py` and `test_15_02b`'s cleanup | `tests/test_scenarios.py:1535` |
| C8 | Isaac Sim's cloner makes a clone that inherits from its source by default (`inheritPathList.Prepend(source)`), and an `Sdf.CopySpec` copy with `copy_from_source=True`. Isaac Lab's `clone_environments(copy_from_source=False)` is the same: clones "inherit from `/World/envs/env_0` and mirror its changes" | `isaacsim.core.cloner` 6.2, `impl/cloner.py:545-550`; Isaac Lab docs, `isaaclab.scene` (Context7) |
| C9 | Isaac Lab's shape and mesh spawners put a prim's physics material at `physics_material_path`, default `"material"`: "If the path is relative, then it will be relative to the prim's path" | Isaac Lab docs, `isaaclab.sim.spawners` (Context7) |
| C10 | `export_prim` gathers the materials outside the prim from all-purpose bindings only, so a physics-purpose material outside the prim is left out of the file, with the binding still pointing at it | `handlers/usd_advanced.py:99-106` (round 2) |
| C11 | `delete_prim` refuses an instance proxy and names its instance | `core/deletion.py:45-51` |

Checked on usd-core 26.11 (`113/check-d.py` and, for Q3 and Q4, `113/walk-facts.py` and `113/walk-cost-2.py` in the
session's scratchpad):

- Each component of a valid prim path is a valid prim name, and so is one with `_PhysMat` added, UTF-8 names
  included; `MakeRelativePath(Sdf.Path.absoluteRootPath)` and `ReplaceName` build A's mirrored path.
- **A child material and clones:** a clone that inherits from `env_0` binds its own composed child,
  `/World/envs/env_1/Robot/link/PhysMat`, whose prim stack is `env_0`'s spec alone. A value written on the clone's
  stays there (`env_0` keeps 0.9); one written later on `env_0`'s reaches a clone without a value of its own (0.5) and
  not one with (0.2). A `CopySpec` copy binds its own copy. With A's path outside the tree, an inheriting clone binds
  `env_0`'s material.
- **A spec without a value:** a clone's material can hold a spec for `physics:staticFriction` with no value, above
  `env_0`'s in its property stack; the clone still reads `env_0`'s 0.9. So the strongest spec that holds a value says
  where a value comes from, not the strongest spec.
- **An instance:** USD refuses a child under an instance (`Tf.ErrorException` from `_ValidateEditPrimAtPath`), and under
  an instance proxy, while `CollisionAPI` applies to the instance, so today's call works there. A prim flagged
  instanceable with no reference or payload is no instance (`IsInstance()` false) and takes a child.
- **The walk:**
  - `GetAuthoredPropertiesInNamespace("material:binding")` holds `material:binding:physics` but not the all-purpose
    `material:binding`; `GetAuthoredProperties` with a predicate on the name holds both, and every other purpose and
    collection binding.
  - `Usd.PrimRange.Stage` with `PrimAllPrimsPredicate` visits an inactive prim, whose binding reads, and none of its
    children, which aren't composed. A prim whose payload isn't loaded has `IsLoaded()` false and no children.
  - A prim in an instance's prototype can bind a material outside the instance, and the instance's proxies bind it;
    a walk without instance proxies doesn't see that prim when the prototype comes from another file.
  - **Cost:** 104,000 prims, 26,000 bound, took 0.40 s (`113/walk-cost.py`). The walk as built, the predicate form,
    on the same stage with 52,000 bound (a physics binding on a quarter, an all-purpose one on another quarter), took
    0.35 s; the prim stacks of 26,000 bound targets 0.02 s.

## Design

### The path (Q1's D)

The material is a child of the prim, named `PhysMat`:

| Prim | Material |
|---|---|
| `/World/Franka_1/panda_leftfinger` | `/World/Franka_1/panda_leftfinger/PhysMat` |
| `/World/Franka_2/panda_leftfinger` | `/World/Franka_2/panda_leftfinger/PhysMat` |
| `/World/Cube` | `/World/Cube/PhysMat` |

- **Unique:** a prim has one child of a name, so two prims have two materials.
- **Valid at any length:** the prim's own path and one fixed name.
- **Copies and clones (C5, C8):** a copy made with `Sdf.CopySpec`, as `clone_prim` and a cloner's copy make it,
  binds its own copy of the material, so a call on the original leaves the copy as it was. A clone that inherits from
  its source composes its own material from the source's: a call on the clone writes its own, and a call on the
  source reaches a clone that has had none, the inheritance the cloner set up, which the answer names (Q3's B). A and
  D are the same for an inheriting clone; they differ for a copy.
- **Cleaned up and carried with the prim:** `delete_prim` removes the material with it; `save_scene`, `flatten_usd`
  and `export_prim` carry it. `export_prim` keeps it because it is under the prim: it gathers outside materials from
  all-purpose bindings only (C10), so A's material would have been left out of the file.
- **Refused, with friction or restitution, before anything is written,** mass and density included:
  - an instance, `prim.IsInstance()`, which USD lets hold no child; a prim flagged instanceable without a reference
    or payload is no instance and takes its material. The error says why, and that a call on its parent gives the
    parent's material to every prim under the parent that has none of its own, so to the other instances there too:
    `/World/Shelf/CrateA is an instance, which USD lets hold no prim of its own, so it can't hold its own physics
    material, /World/Shelf/CrateA/PhysMat. A call on its parent, /World/Shelf, would give the parent's material to
    every prim under /World/Shelf that has none of its own, not only to this one` (P4);
  - an instance proxy, a prim inside an instance, naming its instance as `delete_prim` does (C11):
    `/World/Shelf/CrateA/Box is inside the instance /World/Shelf/CrateA, whose prims can't be changed one by one`,
    then the instance's sentence;
  - a defined child named `PhysMat` that isn't a `Material`, which is the user's own: the error names it.
- **Kept:** a `Material` already at the path is the prim's own, as the material at today's path is; one without
  `MaterialAPI` gets it. A child with no `def` anywhere (an `over` alone) is defined as the `Material`.
- **From the prim:** the path comes from `prim.GetPath()`, not the request's string.

`core/material.py` gains `physics_material_path(path)`, the path; `material_refusal(prim)`, the refusals' text or
None; and `own_physics_material(stage, prim)`, which returns the prim's material, making the `Material` and its
`MaterialAPI` when missing, and raises `ValueError` with the refusal's text. The handler asks `material_refusal`
before it writes the mass, and answers a refusal as an error. `start_from`'s comment on a material "shared by a prim of
the same name" says instead: one made by an older extension, or before the prim was bound to another (I4).

### The other prims a write changes (Q3's B)

After the write and the rebinding, one walk of the stage, `Usd.PrimRange.Stage` with `PrimAllPrimsPredicate` and no
instance proxies, reads every prim's binding relationships, `material:binding` and every `material:binding:*`, into a
map from each target to the prims that bind it, and notes the first inactive prim and the first prim whose payload
isn't loaded. Prototypes and instance proxies aren't walked (Risks). The map serves the warning and Q4 both.

- **Counted:** the other prims, not the called prim or its descendants, that are on the stage as bodies can be
  (defined, active, not a class), and that bind:
  - the written material itself, as a prim bound to it by hand does; or
  - a material composed from it, whose prim stack holds the written material's spec, as an inheriting clone's does,
    when the write gives it one of its three values: for static friction, dynamic friction or restitution, the
    strongest spec that holds a value is the written one. A clone that a call has given its own three values doesn't
    count.
- **Never counted:** a `CopySpec` copy, which binds its own copy; the called prim's links and other descendants, which
  the call is about.
- **The answer:** `also_changes`, the count and the first five paths, sorted; the server prints
  `also changes 2000 prims: /World/envs/env_1/Robot/link, ... and 1995 more`.

### The older material the call moved the prim off (Q4's A)

The material bound to the prim before the call (`physics_material(prim)`, read before the rebinding) is deleted only
when all of these hold:

- it is exactly `/World/PhysicsMaterials/<the prim's name>_PhysMat`, the path an older extension gave it;
- it is a `Material` with `MaterialAPI`, and every spec of it is in the edit target's layer, at its own path;
- after the rebinding, no prim the walk met binds it or a material composed from it, the called prim and its
  descendants included;
- the walk met no inactive prim and no unloaded payload, under which a prim could bind it unseen.

Otherwise it stays, and the answer says why: `1 prim still binds it: /World/Franka_2/panda_leftfinger`, `another layer
holds it too: <layer>`, `/World/Robot/Visuals is inactive, so a prim under it could bind it`, or `the payload of
/World/Env isn't loaded, so a prim in it could bind it`. `/World/PhysicsMaterials` goes too only when the delete
empties it and it is typeless or a `Scope` with every spec in the edit target's layer. A material bound before under
any other path, a user's own `Foo_PhysMat` elsewhere or a material another prim was bound to, is never looked at.

The answer carries `old_material`: `{"path": ..., "deleted": [the paths deleted]}` or `{"path": ..., "kept":
"<why>"}`, which the server prints as `deleted its old material, /World/PhysicsMaterials/Box_PhysMat, which no prim
binds now` (`, and /World/PhysicsMaterials, left empty`) or `kept its old material, /World/PhysicsMaterials/Box_PhysMat:
1 prim still binds it: /World/Other/Box`. No `old_material` for any other material.

### A prim bound to an older extension's shared material

R7's first step reads the prim's values from whatever physics material it is bound to, the shared
`<prim name>_PhysMat` included, `start_from` copies all it holds into the prim's own, the values given are written, and
the binding moves to the prim's own. The shared one is not written again: it stays, bound to the prims a call hasn't
reached, which keep their values, and goes when the call moved the last prim off it (Q4). With D, no prim's own path
can be an older extension's.

### The answer names the material (Q2's A)

The extension's answer carries `material`, the path it bound, and the server prints it between the values and the
APIs, then `also_changes` and `old_material` when there are any:

`Physics on /World/RedCube: friction=0.8 (static and dynamic), restitution=0.3; material /World/RedCube/PhysMat; applied PhysicsMaterial`

A call with only mass or density binds no material and answers none (I3). An older extension's answer has none of the
three fields, and the server prints none. `PROTOCOL` stays 1.

## Decisions for the maintainer

| # | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | Where does each prim's material go? | **A.** Mirror the path, `/World/PhysicsMaterials/World/Franka_1/panda_leftfinger_PhysMat`, the levels between as Scopes. Unique, nothing written into the user's prim, an instanceable prim takes it; but a copy binds its original's material (C5, Q3), a deleted prim leaves its material, `export_prim` leaves it out (C10), the Scopes repeat the names of the prim's ancestors, and a prim at the stage's root gets an older extension's name. **B.** Join the path into one name, `/World/PhysicsMaterials/World_Franka_1_panda_leftfinger_PhysMat`: one level, but `/World/table_top/box` and `/World/table/top_box` join to one name and share again. **C.** The last name and a hash of the path, `panda_leftfinger_3f9a1c07_PhysMat`: short and unique in practice, but it doesn't say whose it is. **D.** A child of the prim, `/World/Franka_1/panda_leftfinger/PhysMat`. A copy takes its own with it, so a call on the original changes no copy (Q3); `delete_prim` removes it with its prim and `export_prim` carries it (C10); no Scopes and no older name to meet; Isaac Lab's spawners put a prim's material at a path relative to the prim by default (C9). But it writes a child into the user's prim, an asset's link included, which shows in `get_scene_tree`, Kit's Stage window and saved files; and an instance, which today's call takes, is refused. For an inheriting clone A and D are the same: a call on the source reaches each clone a call hasn't (I6) | D: the issue names cloned environments, and D settles the sharing copies bring as well as the sharing by name, with no walk; the child is an opinion on the prim of the kind the call already writes, an API and a binding. A if a child in the user's prim is a cost not worth taking | **D** (2026-11-01): the material is `<prim path>/PhysMat` |
| Q2 | Does the answer name the material it bound? | **A.** Yes: a `material` field, which the server prints. No tool shows a binding (C6), and an older extension's path differs from the description's. **B.** No: the description gives the rule, which with D is the prim's path and `/PhysMat` | A: one field and one clause, as #104 made the answers say what the call did | **A** (2026-11-01): the answer names the material |
| Q3 | Does a call walk the stage for other prims bound to the material it writes? With Q1's A, a copy binds its original's material, so a call on the original changes every copy a call hasn't reached; with D, no copy does, and only an inheriting clone follows its source, as the cloner means it to. Either way, an older extension's shared material stays after the last prim leaves it | **A.** No walk: with A, a copy shares its original's material until a call on the copy gives it its own; with D, nothing shares but by inheritance; a shared material no prim binds stays. **B.** A walk each call, 0.40 s per 104,000 prims on usd-core and on Kit's main thread: the answer warns when another prim binds the material, and a shared one no prim binds any more is deleted | A with either Q1 answer: with D, nothing is left for the walk but tidying, and an unbound material changes no body; with A, a copy's binding is the copy's own, as an asset's shared material is | **B** (2026-11-01): walk on every call, against the recommendation, its cost known; built as Design's two sections say |
| Q4 | With Q3's B, which older shared materials does a call delete? | **A.** Only the one this call moved the prim off, exactly `/World/PhysicsMaterials/<the prim's name>_PhysMat`, a `Material` with `MaterialAPI`, every spec in the edit target, which after the rebinding no prim binds, nor a material composed from it, the walk having met no inactive prim or unloaded payload; else it stays and the answer says why. `/World/PhysicsMaterials` goes only when emptied, typeless or a Scope, with its specs in the edit target. **B.** Every unbound `/World/PhysicsMaterials/*_PhysMat` under the same guards, which deletes a user's own unbound one too. **C.** None: warn only | A: it deletes only what this call made unbound, under the tool's own name | **A** (2026-11-01) |

## Compatibility

- **One-way doors:** none. The tool's name, schema and annotations stay (`tests/fixtures/mcp-tools.json`;
  `tools/golden.py` leaves descriptions out). The route keeps its path and gains the answer fields `material`,
  `also_changes` and `old_material`.
- **What users notice:**
  - A call's material moves from `/World/PhysicsMaterials/<prim name>_PhysMat` to `<prim path>/PhysMat`, a new child
    of the prim. A prim moves to its own on its next call, with the values it had; the old one stays for the prims
    still bound to it, and the call that moves the last of them deletes it, with `/World/PhysicsMaterials` once empty.
  - A call on a source that inheriting clones follow names them: `also changes N prims: ...`.
  - A call with friction or restitution on an instance, or inside one, is refused, where it bound a material.
  - Each call with friction or restitution walks the stage: about 0.35 s per 100,000 prims on usd-core, on Kit's main
    thread.
  - It ships with #105 in 0.4.0, so no release writes all three values into a material prims of one name share.
- **An older extension with this server:** the description names the new path, the extension binds the old one, and
  its answer has none of the new fields; `get_sim_state`'s note already says to install the server's extension.
- **Kit apps:** plain USD, so every Kit app.

## Steps

Each step passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 1 | `core/material.py`: `physics_material_path`, `material_refusal`, `own_physics_material`, `physics_material` made public; `start_from`'s comment (I4) | `tests/test_material.py` |
| 2 | `core/material.py`: the walk, the prims a write changes, and the older material's delete (Q3's B, Q4's A) | `tests/test_material.py` |
| 3 | `handle_set_physics_properties` refuses before writing, binds the prim's own material, walks, deletes the older one when it may, and answers `material`, `also_changes` and `old_material` | `tests/test_physics_handler.py` |
| 4 | The server: the description; the answer's clauses | `tests/test_tools.py`, `tests/test_contract.py` |
| 5 | `test_15_02b`: the twins, the full-path keys, the cleanup; `test_15_02c`, the warning and the delete in Kit | live, run by the main session |
| 6 | The docs (below) | `uv run tools/gate.py full` |

## Tests

| Test | What it shows |
|---|---|
| `tests/test_material.py` | The path of `/World/Franka_1/panda_leftfinger`, `/World/Cube`, a root prim `/Box` and a UTF-8 name; two prims of one name under two parents get two paths. `own_physics_material` makes the `Material` and `MaterialAPI`, keeps a `Material` there, gives one without `MaterialAPI` the API, defines one over an `over` alone, and `material_refusal` refuses an instance, an instance proxy naming its instance, and a defined child `PhysMat` that isn't a `Material`; a prim flagged instanceable with no arc takes its material (I5). The walk reads the all-purpose binding and the physics one, and notes an inactive prim and an unloaded payload. The prims a write changes: none for a `CopySpec` copy; an inheriting clone counted, then not once it holds its own three values, and still counted under a stronger spec without a value; a prim bound by hand counted; the called prim's descendants and a class prim never. The delete: the moved-off material deleted, with `/World/PhysicsMaterials` once empty and typeless, and not when it holds another material; kept while another prim binds it or a material composed from it; kept with a spec in another layer; kept after an inactive prim or an unloaded payload; a user's own `Foo_PhysMat` under another parent, and an older-named material the prim wasn't bound to, never touched |
| `tests/test_physics_handler.py` | `OWN` becomes `/World/Box/PhysMat`. The issue's case: two prims of one name under two parents, `friction=1.0` on one, then `restitution=0.2` on the other; the first keeps its 1.0 and its restitution, each bound to its own material. A prim bound to an older extension's `/World/PhysicsMaterials/Box_PhysMat`, which another prim of its name binds too: it moves to its own, holding the shared one's values and the one given, the shared one is unchanged, still bound to the other, and kept, with the answer's reason; the other's call then deletes it and `/World/PhysicsMaterials`. A `CopySpec` copy, as `clone_prim` makes it, then a call on the original: the copy keeps its values and isn't named. An inheriting clone: a call on the source names it in `also_changes`; a call on it leaves its source as it was. A refusal writes nothing, not even the mass given with it. The answer's `material`, and none for a call with only mass or density (I3) |
| `tests/test_tools.py` | The clauses printed from `material`, `also_changes` (five named and the rest counted) and `old_material` (deleted, deleted with the folder, kept), and none for an older extension's answer without them |
| `tests/test_contract.py` | `test_a_description_says_what_the_tool_now_does` gains `set_physics_properties`' path, and its sentence on copies |
| `test_15_02b` (live) | Two bare boxes of one name under two parents slide on its floor: `friction=0.9` on one, then `restitution=0` on the other. The first slides as the Rubber control (friction 0.9) does, within 0.05, where on `main` the second call wrote PhysX's 0.5 into the material they shared; the second as `SlideBareControl` does (I2). `FRICTION_SCENE` lists the rigid bodies under `ROOT` at any depth, not only its children, and `seen` is keyed by the path under `ROOT`, where the last name made the twins one key (I2). Its other bodies' materials, now children of Cubes, show PhysX reads such a material. The materials go with `ROOT` |
| `test_15_02c` (live) | In Kit: an inheriting clone named by a call on its source and not after a call on itself; a box bound to an older extension's material, built by the test, moves to its own, and the old one is deleted, or kept with the reason the suite's stage gives when it holds an inactive prim or an unloaded payload, which the test reads from the stage itself |

- **Live:** `test_15_01`, `test_15_02`, `test_15_02b` and `test_15_02c` on Isaac Sim 6.2, on either up axis: the path
  doesn't depend on it.
- **What neither shows:** a stage of Isaac Lab's size in Kit; Kit's Duplicate, which goes through
  `omni.usd.duplicate_prim` and wasn't checked; USD Composer.

## Docs

| File | What |
|---|---|
| `src/omniverse_mcp/tools/simulation.py` | The description: a physics material of the prim's own, a child named `PhysMat` (`/World/Cube/PhysMat` for `/World/Cube`), which `delete_prim` removes with it; the sentence on prims of one name goes. On copies (P1): a copy made with `clone_prim` takes a material of its own with it, and a clone that inherits from its source follows the source's until a call on the clone, and the answer names the prims a call changes so. An instance is refused. The answer names the material, and an older shared material it deletes or keeps |
| `docs/TOOLS.md` | `set_physics_properties`: the same, with the path's example and P1's sentence on copies; the warning and its count; a prim bound to an older extension's shared material moves to its own on its next call, and the old one stays for the prims still bound to it until the call that moves the last, which deletes it, with each reason it can stay; the walk's cost; the sentence on an extension of 0.3.0 or older names its path. Returns names the material and the two clauses |
| `CHANGELOG.md` | #105's Fixed bullet loses its sentence "Prims of one name still share the material, ... until #113 gives each prim its own." A Fixed bullet of its own, below (P2) |
| `docs/ARCHITECTURE.md` | The core list's `material.py`: the physics material's path, its refusals, the walk, the warning and the delete too |
| `test_project/scenarios.md` | 15.2's Verify line: the answer says `material /World/RedCube/PhysMat` too (I7) |

The Fixed bullet, as drafted:

- **`set_physics_properties` gives each prim a physics material of its own,** a child of the prim:
  `/World/Franka_1/panda_leftfinger/PhysMat`. It was `/World/PhysicsMaterials/<prim name>_PhysMat`, so prims of one
  name, such as two Frankas' fingers, shared one, and setting one set the other. A copy made with `clone_prim` takes
  its own with it, and `delete_prim` removes it with its prim. A clone that inherits from its source, as Isaac Sim's
  cloner makes them, still follows the source's until a call on the clone, and the answer names the prims a call
  changes so: `also changes 3 prims: ...`. A prim bound to such a shared material moves to its own on its next call,
  with the values it had; the shared one stays for the prims still bound to it, and the call that moves the last of
  them deletes it. An instance, which can hold no child, is refused. The answer names the material: `material
  /World/Cube/PhysMat`. Each call with friction or restitution reads the whole stage, about 0.35 s per 100,000 prims.
  The material is the Kit extension's part, and the answer's clauses need this server too (#113).

## Risks

| Risk | Status |
|---|---|
| With D, an instance is refused, where today's call binds a material to it | Accepted: the error says why, and that a call on its parent reaches every prim under the parent without a material of its own, the other instances there too (P4). A call usually goes to a link or a body, which isn't an instance: no rigid body in the readable `ROBOT_ASSETS` root layers is one (round 2). Giving an instance A's path alone is possible, at the cost of a second rule |
| With D, a child of the user's own named `PhysMat`: one that isn't a `Material` is refused; one that is, such as an asset's bound to other prims too, is taken as the prim's own and written | Accepted: the name is the tool's own, and the refusal leaves the first untouched; the warning names the other prims that bind the second |
| With D, a `Material` child under a gprim such as a Cube | Accepted: USD allows it, the material isn't imageable, and live `test_15_02b`'s Cubes show PhysX reads it |
| With D, an inheriting clone follows its source's material until a call on the clone | Accepted (Q3's B): it is what the cloner's inheritance means, "mirror its changes" (C8), and the answer names each clone a call changes |
| The walk holds Kit's main thread on each call with friction or restitution: 0.40 s per 104,000 prims with 26,000 bound on usd-core 26.11, 0.35 s in the form built with 52,000 bound | Accepted (Q3's B): the maintainer chose it knowing the cost. Kit's Python may be slower than usd-core's; a stage of Isaac Lab's size in Kit wasn't measured |
| The walk doesn't enter instances or their prototypes: a prim in a prototype from another file that binds the written material isn't named, and one that binds the older material doesn't stop its delete | Accepted: such a prototype would bind a path of the stage it is referenced into, which only a file saved from a stage of an older extension's calls holds; an instance root's own binding is walked |
| An inactive prim or an unloaded payload anywhere on the stage keeps every older material | Accepted (Q4's A): what is under them could bind it unseen; the answer says which prim kept it |
| A user's own material at exactly `/World/PhysicsMaterials/<the prim's name>_PhysMat`, bound to this prim alone, is deleted when the call moves the prim off it | Accepted (Q4's A): it is the tool's own name, and its values move into the prim's own first |
| With A, a prim at the stage's root, `/Box`, gets `/World/PhysicsMaterials/Box_PhysMat`, the name an older extension gave every prim named Box | Gone with Q1's D |
| With A, a prim named `<x>_PhysMat` with children, beside a prim named `<x>`: the children's materials sit under `<x>`'s | Gone with Q1's D (P3); D's case, a child `PhysMat` that isn't a `Material`, is refused |
| With A, the Scopes repeat the names of the prim's ancestors, so a search by name finds them | Gone with Q1's D |
| With A, a copy shares its original's material, so a call on the original changes it | Gone with Q1's D |
| Kit's PhysX doesn't read the material where it now sits | Open until the live `test_15_02b` runs |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, read only, with one offline check on usd-core (`check113.py` in the
session's scratchpad), 2026-11-01, on `58c809a`. **Verdict:** approved: no blocker or major, three minors; the
maintainer owes Q1 to Q3. **Now:** P1 to P3 fixed; I1 taken as Q1's option D, which the plan now recommends, so the
design reads with D and a second reader takes it; I2 to I4 taken.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | The new description says each prim gets a physics material of its own, but a `clone_prim` copy binds its original's material (C5), and neither the Docs rows nor `clone_prim` say so. `friction=0.9` on `/World/Cube`, three `clone_prim` copies, then `friction=0.1` on `/World/Cube` alone: all three copies slide at 0.1, and Q2's answer names the material but not who else binds it | fixed: the Docs rows give the description and `docs/TOOLS.md` a sentence on copies, for D and for A; `test_contract.py` checks it |
| P2 | minor | The drafted Fixed bullet doesn't name Q2's new answer clause, which users see, as #104's answer changes had their line; and "The fix is in the Kit extension" leaves out the server's part | fixed: the bullet names the clause and says it needs this server too |
| P3 | minor | Risks row 2's "each still has its own path and values" fails in one order: `/World/Foo_PhysMat/Child` first makes `/World/PhysicsMaterials/World/Foo_PhysMat` a Scope; a call on `/World/Foo` then finds a valid prim there, today's check keeps it, and a Scope without `MaterialAPI` is bound, which PhysX ignores, so the call changes nothing | fixed: with A, `own_physics_material` defines a `Material` wherever the prim at the path isn't one, with a test of that order; with D the case is a child `PhysMat` that isn't a `Material`, refused before anything is written, with a test |

**Refuted:**

- A default prim other than `/World`: C1 fixes `/World/PhysicsMaterials`, `/Env/x` maps to
  `/World/PhysicsMaterials/Env/x_PhysMat`, and a missing `/World` is typeless, as on `main`.
- A referenced layer: the Scopes and the material go in the edit target, and the binding is an opinion on the prim.
- Variant selections: `GetPrimAtPath("/A{v=x}B")` is invalid and refused at the handler's prim check;
  `prim.GetPath()` never holds a selection.
- Instance proxies: applying an API to a proxy raises, as on `main`.
- B's collision example: correct.
- The old shared material: `start_from` writes only its first argument, so the shared one keeps its values; the one
  overlap is a root prim, named in Risks.
- Q2's contract: `golden.py` strips descriptions, the output schema stays, an older extension sends no `material` and
  the server prints none, and `PROTOCOL` 1 for an added field matches #105.
- CHANGELOG: both bullets are under Unreleased, and dropping #105's sentence is honest.
- PhysX reading a material under Scopes: named open, and `test_15_02b` settles it: `SlideRubberGiven` would slide
  about 1.63 m against the control's 0.91, past 0.05.
- The twins in `seen`: keyed by last name they collide, which can only fail with the fix in, never pass falsely (I2).
- Up axes and the writing rules: clean.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Where does each prim's material go: A mirrored, B joined, C hashed, D a child of the prim? | D (the reviewer: A, before D was an option) | D |
| Q2 | Does the answer name the material? | A, yes (the reviewer: A) | A |
| Q3 | Does a call walk the stage for other prims bound to the material? | A, no walk (the reviewer: A, with P1's sentence) | B |

**Improvements:**

| # | What | Answer |
|---|---|---|
| I1 | Q1 gains option D, the material as a child of the prim: `Sdf.CopySpec` maps a target inside the copied tree, so a copy gets its own material, which reverses Q3; no root overlap, no Scopes, no Risks row 2, and `delete_prim` removes it with its prim. Cost: a child in the user's prim, in `get_scene_tree` and exports. Isaac Lab's spawners to be checked before citing | taken: Q1's D, checked against Isaac Lab's docs (C9), Isaac Sim's cloner (C8) and usd-core (inheriting clones, instanceable prims), and recommended |
| I2 | `test_15_02b` keys `seen` by full path and adds the twins to `PATHS`, which `FRICTION_SCENE` takes from `ROOT`'s children only; it may compare the second twin with `SlideBareControl` | taken: Tests |
| I3 | A handler test that a call with only mass or density answers without `material` | taken: Tests |
| I4 | Step 1 updates `start_from`'s comment, "shared by a prim of the same name" | taken: Design and Steps |

### Round 2

**How:** one fresh reviewer, Claude Opus, read only, with offline checks on usd-core (`113-review2/d2.py` and
`inst.py` in the session's scratchpad), 2026-11-01, on `d19dab0`. **Verdict:** approved: no blocker or major, one
minor. **Now:** P4 fixed; I5 to I7 taken. The maintainer answered Q1 D, Q2 A and Q3 B, against the recommendation, and
Q4 A, which Q3's B raised; Design's two new sections build Q3's B and Q4's A, with their tests, docs and risks.

| # | Sev | Finding | Status |
|---|---|---|---|
| P4 | minor | Design's "Refused..." and Risks row 1: the instance's refusal "names its parent", which an agent reads as "call the parent". With an instanceable prop sharing a parent, `/World/Shelf/CrateA` and `CrateB`, a call on `/World/Shelf` binds `/World/Shelf/PhysMat` to every collider under it without a binding of its own, so both crates change; the handler applies `CollisionAPI` to the Shelf Xform too (`handlers/simulation.py:141-144`) | fixed: the error says a call on the parent gives the parent's material to every prim under it that has none of its own, not only to this one (Design, Risks row 1) |

**Refuted:**

- A reference or payload root: the child is an opinion in the edit layer; `save_scene`, `flatten_usd` and `export_prim`
  keep it, and `export_prim`'s copy binds `/Cube/PhysMat` after its `CopySpec`.
- `get_scene_tree` shows a `Material` child, and `compare_prims` nothing new (`_utils.py:261-308`).
- An existing child `PhysMat` that isn't a `Material` is refused, as Isaac Lab's spawner does.
- GeomSubsets: `weakerThanDescendants`, as on `main`.
- An instance link: no rigid body in the readable `ROBOT_ASSETS` root layers is instanceable (franka 22, anymal 30,
  go1 34 and spot 26 instanceable visuals and collisions children; carter, jetbot and ur10 none), so a call on a link
  works.
- Inheriting clones behave the same under A and D.
- `delete_prim`: `CopySpec` and inherits map the binding.
- R7's first step still holds.
- An instance proxy raises before anything is written.
- Tests, docs and the writing rules: clean.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q4 | With Q3's B, which older shared materials does a call delete: A the one it moved the prim off, B every unbound one of the tool's name, C none? | A | A |

**Improvements:**

| # | What | Answer |
|---|---|---|
| I5 | Key the refusal on `prim.IsInstance()`, not `IsInstanceable()`: a prim flagged instanceable with no arc can hold a child. Test both, and refuse an instance proxy naming its instance, as `core/deletion.py:45-51` does | taken: Design and Tests |
| I6 | Credit D with `export_prim` keeping the physics material (`usd_advanced.py:99-106` looks only at all-purpose bindings), and say A and D are the same for inheriting clones | taken: C10, Design and Q1's options |
| I7 | Scenario 15.2's Verify line checks `material /World/RedCube/PhysMat` | taken: Docs |
