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
  becomes of a prim bound to an older extension's shared `<prim name>_PhysMat`; copies and clones of a prim that has
  its material; the tool's description, `docs/TOOLS.md`, `CHANGELOG.md` with #105's sentence that names #113, and the
  tests, `test_15_02b` among them.
- **Out of scope:**
  - `set_material`'s look material, `/World/Looks/<prim name>`, shared by name the same way: it has `material_path`
    to keep prims apart, and its description says so;
  - the values a call writes and where they start from: #105's R7 and Q8, unchanged;
  - deleting an older extension's shared material once no prim binds it (Q3).

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

Checked on usd-core 26.11 (`113/check-d.py` in the session's scratchpad):

- Each component of a valid prim path is a valid prim name, and so is one with `_PhysMat` added, UTF-8 names
  included; `MakeRelativePath(Sdf.Path.absoluteRootPath)` and `ReplaceName` build A's mirrored path.
- **A child material and clones:** a clone that inherits from `env_0` binds its own composed child,
  `/World/envs/env_1/Robot/link/PhysMat`. A value written on the clone's stays there (`env_0` keeps 0.9); one written
  later on `env_0`'s reaches a clone without a value of its own (0.5) and not one with (0.2). A `CopySpec` copy binds
  its own copy. With A's path outside the tree, an inheriting clone binds `env_0`'s material.
- **An instanceable prim:** USD refuses a child under it (`Tf.ErrorException` from `_ValidateEditPrimAtPath`), while
  `CollisionAPI` applies to it, so today's call works there.
- **Cost of a walk:** a Python walk over a stage of 104,000 prims, reading one relationship of each, took 0.18 s
  (Q3).

## Design

### The path (Q1)

With Q1's D, the material is a child of the prim, named `PhysMat`:

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
  source reaches a clone that has had none, the inheritance the cloner set up.
- **Cleaned up with the prim:** `delete_prim` removes the material with it; `export_prim` and `save_scene` carry it.
- **Refused, with friction or restitution, before anything is written,** mass and density included:
  - an instanceable prim, which USD lets hold no child: the error says so and names its parent;
  - a child named `PhysMat` that isn't a `Material`, which is the user's own: the error names it.
- **Kept:** a `Material` already at the path is the prim's own, as the material at today's path is; one without
  `MaterialAPI` gets it.
- **From the prim:** the path comes from `prim.GetPath()`, not the request's string.

`core/material.py` gains `physics_material_path(prim_path)`, the path, and `own_physics_material(stage, prim)`, which
returns the prim's material, making the `Material` and its `MaterialAPI` when missing, and raises `ValueError` with the
refusal's text, which the handler answers as an error. `start_from`'s comment on a material "shared by a prim of the
same name" says instead: one made by an older extension, or before the prim was bound to another (I4).

**With Q1's A instead:** `/World/PhysicsMaterials/<prim path>_PhysMat`, the levels between as `Scope`s made when
missing. `own_physics_material` defines a `Material` wherever the prim at the path isn't one (P3): when a prim named
`<x>_PhysMat` under `/World` was given its material first, `/World/PhysicsMaterials/World/<x>_PhysMat` is a Scope by
the time `/World/<x>` is called, and a Scope without `MaterialAPI` would be bound and ignored by PhysX.

### A prim bound to an older extension's shared material

No new code: R7's first step reads the prim's values from whatever physics material it is bound to, the shared
`<prim name>_PhysMat` included, `start_from` copies all it holds into the prim's own, the values given are written,
and the binding moves to the prim's own. The shared one is not written again and stays, bound to the prims a call
hasn't reached, which keep their values. It is not deleted: whether another prim still binds it takes a walk over the
stage (Q3). With D, no prim's own path can be an older extension's; with A, a prim at the stage's root can (Risks).

### The answer names the material (Q2)

With Q2's A, the extension's answer carries `material`, the path it bound, and the server prints it between the
values and the APIs:

`Physics on /World/RedCube: friction=0.8 (static and dynamic), restitution=0.3; material /World/RedCube/PhysMat; applied PhysicsMaterial`

A call with only mass or density binds no material and answers none (I3). An older extension's answer has no
`material`, and the server prints none. `PROTOCOL` stays 1.

## Decisions for the maintainer

| # | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | Where does each prim's material go? | **A.** Mirror the path, `/World/PhysicsMaterials/World/Franka_1/panda_leftfinger_PhysMat`, the levels between as Scopes. Unique, nothing written into the user's prim, an instanceable prim takes it; but a copy binds its original's material (C5, Q3), an inheriting clone its source's, a deleted prim leaves its material, the Scopes repeat the names of the prim's ancestors, and a prim at the stage's root gets an older extension's name. **B.** Join the path into one name, `/World/PhysicsMaterials/World_Franka_1_panda_leftfinger_PhysMat`: one level, but `/World/table_top/box` and `/World/table/top_box` join to one name and share again. **C.** The last name and a hash of the path, `panda_leftfinger_3f9a1c07_PhysMat`: short and unique in practice, but it doesn't say whose it is. **D.** A child of the prim, `/World/Franka_1/panda_leftfinger/PhysMat`. A copy takes its own with it and an inheriting clone composes its own, so a call on the original changes no copy (Q3); `delete_prim` removes it with its prim; no Scopes and no older name to meet; Isaac Lab's spawners put a prim's material at a path relative to the prim by default (C9). But it writes a child into the user's prim, an asset's link included, which shows in `get_scene_tree`, Kit's Stage window and saved files; and an instanceable prim, which today's call takes, is refused | D: the issue names cloned environments, and D settles the sharing copies bring as well as the sharing by name, with no walk; the child is an opinion on the prim of the kind the call already writes, an API and a binding. A if a child in the user's prim is a cost not worth taking | |
| Q2 | Does the answer name the material it bound? | **A.** Yes: a `material` field, which the server prints. No tool shows a binding (C6), and an older extension's path differs from the description's. **B.** No: the description gives the rule, which with D is the prim's path and `/PhysMat` | A: one field and one clause, as #104 made the answers say what the call did | |
| Q3 | Does a call walk the stage for other prims bound to the material it writes? With Q1's A, a copy binds its original's material, so a call on the original changes every copy a call hasn't reached; with D, no copy does, and only an inheriting clone follows its source, as the cloner means it to. Either way, an older extension's shared material stays after the last prim leaves it | **A.** No walk: with A, a copy shares its original's material until a call on the copy gives it its own; with D, nothing shares but by inheritance; a shared material no prim binds stays. **B.** A walk each call, 0.18 s per 100,000 prims on usd-core and on Kit's main thread: the answer warns when another prim binds the material, and a shared one no prim binds any more is deleted | A with either Q1 answer: with D, nothing is left for the walk but tidying, and an unbound material changes no body; with A, a copy's binding is the copy's own, as an asset's shared material is | |

## Compatibility

- **One-way doors:** none. The tool's name, schema and annotations stay (`tests/fixtures/mcp-tools.json`;
  `tools/golden.py` leaves descriptions out). The route keeps its path and, with Q2's A, gains the answer field
  `material`.
- **What users notice:**
  - A call's material moves from `/World/PhysicsMaterials/<prim name>_PhysMat` to, with D, `<prim path>/PhysMat`, a
    new child of the prim. A script that read the old path finds the old material, bound to the prims no call has
    reached since the upgrade; a prim moves to its own on its next call, with the values it had.
  - With D, a call with friction or restitution on an instanceable prim is refused, where it bound a material.
  - It ships with #105 in 0.4.0, so no release writes all three values into a material prims of one name share.
- **An older extension with this server:** the description names the new path, the extension binds the old one, and
  its answer has no `material`; `get_sim_state`'s note already says to install the server's extension.
- **Kit apps:** plain USD, so every Kit app.

## Steps

Each step passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 1 | `core/material.py`: `physics_material_path`, `own_physics_material` and its refusals; `start_from`'s comment (I4) | `tests/test_material.py` |
| 2 | `handle_set_physics_properties` refuses before writing, binds the prim's own material, and with Q2's A answers `material` | `tests/test_physics_handler.py` |
| 3 | The server: the description; with Q2's A, the answer's clause | `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | `test_15_02b`: the twins, the full-path keys, the cleanup | live, run by the main session |
| 5 | The docs (below) | `uv run tools/gate.py full` |

## Tests

| Test | What it shows |
|---|---|
| `tests/test_material.py` | The path of `/World/Franka_1/panda_leftfinger`, `/World/Cube`, a root prim `/Box` and a UTF-8 name; two prims of one name under two parents get two paths. `own_physics_material` makes the `Material` and `MaterialAPI`, keeps a `Material` there, gives one without `MaterialAPI` the API, and refuses an instanceable prim and a child `PhysMat` that isn't a `Material`. With A: the Scopes, an existing typeless `/World/PhysicsMaterials` left as it is, and P3's order, `/World/Foo_PhysMat/Child` before `/World/Foo`, ending with a `Material` with `MaterialAPI` at Foo's path |
| `tests/test_physics_handler.py` | `OWN` becomes `/World/Box/PhysMat`. The issue's case: two prims of one name under two parents, `friction=1.0` on one, then `restitution=0.2` on the other; the first keeps its 1.0 and its restitution, each bound to its own material. A prim bound to an older extension's `/World/PhysicsMaterials/Box_PhysMat`, which another prim of its name binds too: it moves to its own, holding the shared one's values and the one given, and the shared one is unchanged and still bound to the other. A `CopySpec` copy, as `clone_prim` makes it, then a call on the original: the copy keeps its values (with A: they change, Q3). An inheriting clone: a call on it leaves its source as it was. A refusal writes nothing, not even the mass given with it. With Q2's A, the answer's `material`, and none for a call with only mass or density (I3) |
| `tests/test_tools.py` | With Q2's A: the clause printed from `material`, and none for an older extension's answer without it |
| `tests/test_contract.py` | `test_a_description_says_what_the_tool_now_does` gains `set_physics_properties`' path, and its sentence on copies |
| `test_15_02b` (live) | Two bare boxes of one name under two parents slide on its floor: `friction=0.9` on one, then `restitution=0` on the other. The first slides as the Rubber control (friction 0.9) does, within 0.05, where on `main` the second call wrote PhysX's 0.5 into the material they shared; the second as `SlideBareControl` does (I2). `FRICTION_SCENE` lists the rigid bodies under `ROOT` at any depth, not only its children, and `seen` is keyed by the path under `ROOT`, where the last name made the twins one key (I2). Its other bodies' materials, now children of Cubes, show PhysX reads such a material. With D the materials go with `ROOT`; with A its cleanup deletes `/World/PhysicsMaterials/World/IntTestFriction` |

- **Live:** `test_15_01`, `test_15_02` and `test_15_02b` on Isaac Sim 6.2, on either up axis: the path doesn't
  depend on it.
- **What neither shows:** a stage of Isaac Lab's size; Kit's Duplicate, which goes through
  `omni.usd.duplicate_prim` and wasn't checked; USD Composer.

## Docs

| File | What |
|---|---|
| `src/omniverse_mcp/tools/simulation.py` | The description: a physics material of the prim's own, with D `<prim path>/PhysMat` (`/World/Cube/PhysMat` for `/World/Cube`), a child that `delete_prim` removes with it; the sentence on prims of one name goes. On copies (P1), with D: a copy made with `clone_prim` takes a material of its own with it, and a clone that inherits from its source follows the source's until a call on the clone; with A: a copy binds its original's material until a call on the copy gives it its own. With D, an instanceable prim is refused |
| `docs/TOOLS.md` | `set_physics_properties`: the same, with the path's example and P1's sentence on copies; a prim bound to an older extension's shared material moves to its own on its next call, and the old one stays for the prims still bound to it; the sentence on an extension of 0.3.0 or older names its path. With Q2's A, Returns names the material |
| `CHANGELOG.md` | #105's Fixed bullet loses its sentence "Prims of one name still share the material, ... until #113 gives each prim its own." A Fixed bullet of its own, below (P2) |
| `docs/ARCHITECTURE.md` | The core list's `material.py`: the physics material's path too |

The Fixed bullet, as drafted for D and Q2's A:

- **`set_physics_properties` gives each prim a physics material of its own,** a child of the prim:
  `/World/Franka_1/panda_leftfinger/PhysMat`. It was `/World/PhysicsMaterials/<prim name>_PhysMat`, so prims of one
  name, such as two Frankas' fingers, shared one, and setting one set the other. A copy made with `clone_prim` takes
  its own with it, and `delete_prim` removes it with its prim. A prim bound to such a shared material moves to its own
  on its next call, with the values it had; the shared one stays for the prims still bound to it. An instanceable
  prim, which can hold no child, is refused. The answer names the material: `material /World/Cube/PhysMat`. The
  material is the Kit extension's part, and the answer's clause needs this server too (#113).

## Risks

| Risk | Status |
|---|---|
| With D, an instanceable prim is refused, where today's call binds a material to it | Accepted with D: the error says why and names its parent. A call usually goes to a link or a body, which isn't instanceable; giving such a prim A's path alone is possible, at the cost of a second rule |
| With D, a child of the user's own named `PhysMat`: one that isn't a `Material` is refused; one that is, such as an asset's bound to other prims too, is taken as the prim's own and written | Accepted: the name is the tool's own, and the refusal leaves the first untouched |
| With D, a `Material` child under a gprim such as a Cube | Accepted: USD allows it, the material isn't imageable, and live `test_15_02b`'s Cubes show PhysX reads it |
| With D, an inheriting clone follows its source's material until a call on the clone | Accepted (Q3): it is what the cloner's inheritance means, "mirror its changes" (C8) |
| With A, a prim at the stage's root, `/Box`, gets `/World/PhysicsMaterials/Box_PhysMat`, the name an older extension gave every prim named Box | Accepted with A: Isaac Sim and USD Composer put a scene under `/World`; a call on each other Box prim moves it to its own. D has no such case |
| With A, a prim named `<x>_PhysMat` with children, beside a prim named `<x>`: the children's materials sit under `<x>`'s | Fixed with A (P3): `own_physics_material` defines a `Material` wherever the prim at the path isn't one, and a test calls them in that order |
| With A, the Scopes repeat the names of the prim's ancestors, so a search by name finds them | Accepted with A: they hold no geometry, body or articulation, and PhysX's tensor views take only the rigid bodies or articulations a pattern matches (`omni.physics.tensors` 110.4.4, `api.py`, `create_rigid_body_view`) |
| With A, a copy shares its original's material, so a call on the original changes it | Q3 |
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
| Q1 | Where does each prim's material go: A mirrored, B joined, C hashed, D a child of the prim? | D (the reviewer: A, before D was an option) | |
| Q2 | Does the answer name the material? | A, yes (the reviewer: A) | |
| Q3 | Does a call walk the stage for other prims bound to the material? | A, no walk (the reviewer: A, with P1's sentence) | |

**Improvements:**

| # | What | Answer |
|---|---|---|
| I1 | Q1 gains option D, the material as a child of the prim: `Sdf.CopySpec` maps a target inside the copied tree, so a copy gets its own material, which reverses Q3; no root overlap, no Scopes, no Risks row 2, and `delete_prim` removes it with its prim. Cost: a child in the user's prim, in `get_scene_tree` and exports. Isaac Lab's spawners to be checked before citing | taken: Q1's D, checked against Isaac Lab's docs (C9), Isaac Sim's cloner (C8) and usd-core (inheriting clones, instanceable prims), and recommended |
| I2 | `test_15_02b` keys `seen` by full path and adds the twins to `PATHS`, which `FRICTION_SCENE` takes from `ROOT`'s children only; it may compare the second twin with `SlideBareControl` | taken: Tests |
| I3 | A handler test that a call with only mass or density answers without `material` | taken: Tests |
| I4 | Step 1 updates `start_from`'s comment, "shared by a prim of the same name" | taken: Design and Steps |
