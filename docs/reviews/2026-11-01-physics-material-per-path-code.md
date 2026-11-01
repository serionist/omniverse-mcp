---
subject: "Give each prim its own physics material in set_physics_properties (#113)"
base: main (84acfa5)
head: 5b56cb9
date: 2026-11-01
round: 1
tier: "two fresh reviewers on Claude Opus, read only, the lenses split between them, with usd-core checks; findings checked against the code by the author"
verdict: needs-fixes
---

# Review: Give each prim its own physics material in set_physics_properties

Read from the branch's diff against `main`, rebased onto `84acfa5`, against the approved plan
`docs/plans/2026-11-01-physics-material-per-path.md` (Q1 D, Q2 A, Q3 B, Q4 A). Two reviewers split the lenses:

| Reviewer | Lenses | Checks run |
|---|---|---|
| (a) | implementation, Kit's main thread, the bridge's security, compatibility, simplicity, on the extension | `r113/checks.py`, `checks2.py`, `cost.py` on usd-core |
| (b) | the plan and its intent, the tool contract, tests, docs, the harness | `r113/live15c.py`, a usd-core mirror of `test_15_02c` |

Eight minors, no blocker or major, so no second round. Nothing either found lets the delete remove a material still
bound through a binding the stage composes.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/material.py` `_why_kept`, `drop_old_material` | A `Material` nested under the old one, `/World/PhysicsMaterials/Box_PhysMat/Inner`, bound by `/World/Other`: a call on `/World/Box` answered deleted for the old material and the folder, `Inner` went with them, and `/World/Other`'s binding pointed at nothing. The check read only the binders of the old material's own path, while `RemovePrim` takes the subtree | fixed in `7a41a01`: a material that holds prims of its own is kept, since an older extension never wrote under it; `test_the_material_stays_while_it_holds_a_prim_of_its_own` |
| F2 | minor | `walk_bindings`; the stated cost in `docs/TOOLS.md`, `CHANGELOG.md`, the description | `GetAuthoredProperties` with a Python predicate tested every authored property's name: on 100,000 prims, a quarter bound, 0.55 s with 1 property each, 1.41 s with 15 and 2.00 s with 30, where real meshes carry 10 to 30. The docs said 0.35 s | fixed in `805c0d9`: one read of the `material` namespace holds the all-purpose binding and every other, in C++. Measured on usd-core with 1, 15 and 30 properties: 0.86 to 1.00 s with a quarter bound, 1.1 to 1.5 s with half, flat in the property count, against 0.6 to 2.9 s for the predicate form. The description, `docs/TOOLS.md` and `CHANGELOG.md` say about 1 s per 100,000 prims; the plan in `e891297`. `test_the_walk_reads_the_all_purpose_binding_and_the_physics_one` holds the all-purpose binding |
| F3 | minor | `handle_set_physics_properties`, `material_refusal` | `friction=0.5` on an inactive prim raised "Failed to define UsdPrim </World/Box/PhysMat>" after the Collision API, and any mass with `RigidBodyAPI` and `MassAPI`, and a `def Material` spec were written; the bridge answered a 500 with the writes left. On `main` it succeeded | fixed in `f03564d`: `material_refusal` refuses an inactive prim before anything is written; `test_an_inactive_prim_is_refused`, `test_an_inactive_prim_is_refused_and_not_even_its_mass_is_written` |
| F4 | minor | `walk_bindings`, `unseen` | A binding to the old material in a variant not selected: the walk couldn't see it, the material and the folder were deleted, and switching the variant back left a binding to a deleted prim. `unseen` covered only inactive prims and unloaded payloads | fixed in `805c0d9`: a prim with variant sets is unseen, and the old material stays; `test_the_walk_notes_variant_sets`, `test_a_binding_in_a_variant_not_selected_keeps_the_material`. `test_15_02c`'s mirror of the rule moved with it, checked offline against the walk on six stages |
| F5 | minor | `_only_in`, `_why_kept` | An old material with an inherit, reference or specialize to a template in the edit layer itself was kept, rightly, but the answer said "another layer holds it too: the stage's root layer", the edit layer | fixed in `7a41a01`: `_held_elsewhere` words the arc on its own, `it is composed from /World/Templates/Grip too`; `test_the_material_composed_from_another_path_in_the_edit_layer_says_so` |
| F6 | minor | `tools/simulation.py` `@tool(mcp, EDITS)`; `docs/TOOLS.md`'s hint table | The tool now deletes a prim, while its hint and the table call it not destructive, and the plan's Compatibility said "annotations stay" without weighing the delete | the maintainer chose to keep EDITS (2026-11-01). `e891297` says why in `docs/TOOLS.md` under the hint table and in the plan's Compatibility: it deletes only its own old, unbound material, after its values have moved into the prim's own; nothing is lost |
| F7 | minor | `tests/test_material.py`, `tests/test_physics_handler.py` | Three guards no test pinned: the cap at five named prims, without which 4,096 Isaac Lab environments send 4,096 paths and the server prints them all; the folder's own check for another layer, without which the answer says the folder was deleted while it stays; a descendant of the called prim still binding the old material keeping it | fixed: `test_the_answer_names_five_of_the_clones_and_counts_the_rest` (`5cc0227`), `test_the_folder_stays_while_another_layer_holds_it` and `test_the_material_stays_while_a_descendant_of_the_called_prim_binds_it` (`7a41a01`) |
| F8 | minor | `tests/test_scenarios.py` `test_15_02c` | `CLONE_SCENE`'s `Material.Define` makes `/World/PhysicsMaterials` when there is none, but the cleanups deleted only the test's root and the old material: in the kept branch, or after an early failure, the empty folder stayed | fixed in `5cc0227`: the test reads whether the folder was there first and, when it wasn't, deletes it after the old material (cleanups run last in, first out) |

Refuted:

- **Deleted before the rebinding:** `binding.Bind` comes before `walk_bindings` and `drop_old_material`, `before` is
  read before `own_physics_material`, and a test pins the order.
- **The all-purpose binding missed:** `_is_binding` accepted `material:binding` itself.
- **Bindings that should keep it,** each kept naming the right prim (`checks2.py` a, b, c, j, k, k2, m): a collection
  binding, a GeomSubset's, one only in a sublayer, a class prim's, an internal instance source, an ancestor's, the
  called prim's own leftover all-purpose binding.
- **Another layer, or a sublayer as the edit target:** kept through the layer check. A folder holding anything else is
  kept: `GetAllChildrenNames` counts inactive, over and class children.
- **A user's own material,** another prim's name, or one bound before under another path: never touched.
- **The warning's count:** the strongest spec holding a value decides; a `CopySpec` copy is never counted;
  `HasPrefix(called)` leaves out the called prim and its descendants by path component, so `/World/Box_01` isn't left
  out by `/World/Box`; ghosts are left out; the five named are the first of a sorted list.
- **The refusals** only read, before the mass is written, on `IsInstance()` with the proxy check first.
- **The walk raising partway:** `_reads_from` runs only for targets whose stack holds the new spec; `start_from`'s
  `RemoveProperty` on an inherited attribute returns false; a call on an unloaded payload's root works. #105's R7
  holds: the source is read before any write.
- **Kit's main thread:** the walk runs inline in the async handler, its own task; no route is added and the token check
  stays.
- **A prototype from another file binding the old material:** the plan's accepted risk.
- **`test_15_02c` passing without showing the delete** in its kept branch: the plan chose it, it is pinned on usd-core,
  and the kept branch still fails a wrong delete or a wrong reason.
- **`test_15_02b` and the handler tests on `main`:** `test_15_02b` fails there (the material check, then TwinA slides
  about 1.63 m against Rubber's 0.91); 12 of the 14 handler tests fail, the other two being the mass-only guard and
  `/sim/state`'s.
- **The tool contract:** `mcp-tools.json` is untouched, descriptions are left out of it, the fields are added on both
  sides, `PROTOCOL` stays 1, and an older extension's answer prints as before.
- **The harness:** no harness file, `noqa`, type ignore or skip; the ratchets are unchanged; `instance_of` has two
  callers and no import cycle.
- **The plan's departure to one `unseen`:** the answer gives one reason either way.
- **Up axes and ports:** the twins stand at `point(-210, 0.25, b)` and their travel is read along X; no port is
  written in.
- **Docs and CHANGELOG:** #105's sentence on #113 is gone, and the Fixed bullet names the material, the warning, the
  delete or why it stays, the refusal, the walk's cost and the install; the writing rules hold.

Improvements:

| # | What | Answer |
|---|---|---|
| I1 | `unseen` could pass an inactive prim with nothing under it: Kit deactivates a prim it deletes where it can't remove the spec, so one stray leaf kept every old material on many real stages | taken in `805c0d9`: an inactive prim with no children in any of its specs, no payload and no variant sets hides nothing; `test_the_walk_passes_an_inactive_leaf`, and `test_the_walk_notes_an_inactive_prim_whose_children_a_reference_brings` for the other side |
| I2 | `test_15_02c` also checks the moved box's material, `/World/IntTestClones/Old/IntTestOldBox/PhysMat` | taken in `5cc0227` |
| I3 | After the live run, the plan's last Risks row, "Open until the live `test_15_02b` runs", says the outcome | taken in `e891297`: resolved on Isaac Sim 6.2, Z-up and Y-up |
| I4 | The description also says the answer reports the old material deleted or kept, and why, as the plan's Docs row has it | taken in `e891297` |
| I5 | `docs/TOOLS.md`'s refused bullet and CHANGELOG's "An instance ... is refused" say a call with friction or restitution: a call with only mass on an instance isn't refused | taken in `e891297` |

## Live run

Isaac Sim 6.2.0 headless, Kit 110.4.0, on Windows with an RTX 5090, port 8212, the extension at `5b56cb9`, run by the
main session:

- `tests/test_scenarios.py -k "test_02_01 or test_04_05 or test_15_01 or test_15_02"`: 6 passed on a Z-up stage and 6
  on a Y-up one.
- `test_15_02c` printed both times "clone named, then not; deleted
  ['/World/PhysicsMaterials/IntTestOldBox_PhysMat', '/World/PhysicsMaterials']": the delete fired in Kit, on a stage
  where the walk met nothing it couldn't see.
- `test_15_02b` passed: PhysX reads a physics material that is a child of its prim, and the twins of one name slid as
  their own controls.
- Both live suites whole, from a Z-up stage: 195 passed.

Again after the fixes, on a fresh Kit with the extension at `9030362`:

- The same tests: 6 passed on a Z-up stage and 6 on a Y-up one; `test_15_02c` printed the same "deleted" line both
  times, so the walk's new checks (variant sets, inactive prims) met nothing on the suite's stage and the delete
  still fired.
- Both live suites whole, from a Z-up stage: 195 passed.

Not shown: a stage of Isaac Lab's size in Kit (the walk's cost is measured on usd-core only), Kit's Duplicate, Isaac
Sim 5.x, Linux, or USD Composer.

## Checks

- `uv run tools/gate.py full` at `e891297`: 15 checks passed, 1860 tests passed and 213 skipped, coverage 97.29%.
- The walk's cost on usd-core 26.11 (`113/walk-cost-3.py` and the reviewers' `r113/cost.py` in the session's
  scratchpad), on a shared machine whose figures varied by about a third between runs.
- `test_15_02c`'s mirror of the walk's rule against `walk_bindings` on six usd-core stages (no case, an inactive leaf,
  an inactive parent, an unloaded payload, variant sets, an inactive prim with a reference): the same prim, or none,
  each time.
