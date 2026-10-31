---
subject: "Make twelve tools do what their answers say (#82)"
base: main (f26642c)
head: b611899
date: 2026-10-31
round: 1
tier: split (three fresh reviewers on Claude Sonnet, by area; findings checked against the code by the author, the major reproduced on usd-core)
verdict: needs-fixes
---

# Review: twelve tools whose answers didn't match what they did

Read from the branch's diff, 34 files and +3685/-391, split by area: the transform writer (`core/xform.py`) and its
callers; the camera; the other rows (delete, dump and tree, material, recording, raycast) and the docs. One major,
reproduced on usd-core before it was fixed, and eight minors; the live run found two more, both in the tests.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `core/deletion.py`, `why_kept` | A prim whose referenced file has arcs of its own was refused. `/World/Robot` references `robot.usda`, whose `/Robot` has a reference, a payload or an inherit of its own, as a robot made of parts does: `delete_prim("/World/Robot")` answered "robot.usda gives it a reference to part.usda" and deleted nothing, where `main` deletes it. The check compared each arc's introducing layer with the edit layer, so an arc the file itself authors counted. A usd-core script refused all three cases | fixed in `6c72fb7`: only an arc introduced in the stage's own layer stack (`IsIntroducedInRootLayerStack`) keeps a prim, since a file's own arcs go with the reference that brings the file. An ancestral refusal now names the stage prim the arc hangs from (`core/usd.py`, `stage_prim_of`), where it named a path inside the file. `test_a_prim_whose_file_has_arcs_of_its_own_goes_with_its_reference` and `test_a_part_a_files_own_arc_brings_names_the_stage_prim`, each for a reference, a payload and an inherit; all 6 fail against the old `deletion.py` |
| F2 | minor | `core/xform.py`, `Snapshot.restore` | A camera with no authored `xformOpOrder` wasn't put back. A bare `UsdGeom.Camera` as the viewport's camera, `set_camera` straight down a Y-up stage: Isaac Sim's call authors a translate, a scale of about 3.4e38 and the order; `restore` wrote the order only when there had been one and set only the ops that were there, so the scale stayed and the call answered that the camera could not be aimed | fixed in `29e8d1f`: with no order before, the order's opinion in that layer is cleared, and so is each op attribute the call added. `test_a_snapshot_of_a_bare_camera_clears_what_the_call_authored`, `test_a_bare_scene_camera_isaac_sims_call_broke_is_put_back_without_ops_and_aimed` |
| F3 | minor | `core/xform.py`, `look_at` | Looking straight up, `inspect_prim`'s bottom view, the camera was rolled 180 degrees: its up was minus the front axis, as from above, where the docstring promised the up the camera has as it comes over from the front, which from below is plus the front axis | fixed in `29e8d1f`: the sign follows which way the camera looks. `test_look_at_straight_down_and_up_tips_the_cameras_up_as_it_comes_over_from_the_front` on both up axes, `test_inspect_prim_top_and_bottom_come_over_from_the_front_not_rolled` |
| F4 | minor | `handlers/scene.py`, `handle_create_prim` | `usd_path` on a prim already there, with a transform the prim can't take: the refusal took away only what the call made, so the reference it added stayed, and each retry stacked another | fixed in `33f8944`: a reference the prim didn't hold before is removed, and the error says it was not added. `test_create_prim_over_a_prim_that_was_there_keeps_no_reference_it_refused`; `test_create_prim_that_refuses_keeps_a_reference_the_prim_already_held` guards the other side |
| F5 | minor | `handlers/scene.py`, `handle_clone_prim` | The rollback when a later copy is refused had no test | fixed in `33f8944`: `test_clone_prim_whose_later_copy_refuses_leaves_none_of_its_copies`. No usd-core stage makes a copy refuse what its source took (`CopySpec` carries the root layer's opinions, and another layer's at the copy's path would make the path taken), so the refusal is faked on the third copy, after two are made |
| F6 | minor | `core/xform.py`, `_blocker` | Time samples in a weaker layer, an animated asset's, were refused as "would override the animation and freeze it" even when the written layer already held a default, which had frozen it before, so the write froze nothing new | fixed in `29e8d1f`: a default at or above the written layer lets such samples through. `test_samples_in_a_weaker_layer_under_a_default_already_held_are_let_through` |
| F7 | minor | `tools/simulation.py`, `_unit` | `raycast` took the direction's length as the root of a sum of squares: `[1e-200, 0, 0]` underflowed and was refused as zero, `[1e200, 0, 0]` overflowed and sent `[0, 0, 0]`, and a NaN or infinite part passed | fixed in `44e1d56`: `math.hypot`, and a part or a length that isn't finite is an error. `test_a_tiny_or_huge_direction_is_still_scaled_to_length_1`, `test_a_direction_with_no_finite_length_is_refused` |
| F8 | minor | `docs/TOOLS.md`, comments across the change | Lines the change made longer ran past 120 columns (`dump_scene`'s Returns, `set_material`), `get_scene_tree`'s description had a stray short line, and comments named the plan's ids ("#82's E8", "round 1's P5", "(R7)") without the reason in their own words | fixed in `d3c08a2` and `092c0a5` |
| F9 | minor | `tools/scene.py`, `docs/TOOLS.md`, `delete_prim` | Its description said twice that `set_visibility` hides a prim | fixed in `d3c08a2`: once |
| F10 | minor | `handlers/scene.py`, `handle_clone_prim` | The source's transform is checked against opinions its copies won't carry: a session-layer opinion on the source's ops refuses the clone, though the copies get only the root layer's | wontfix: it refuses on the safe side, nothing is written, and only for a source whose ops a layer stronger than the root holds |
| F11 | minor | `tests/test_integration.py`, `test_12f` | Found by the live run. The count of Isaac Sim's recorded calls imported `isaacsim.core.utils.viewports`, which the test had just made unimportable, so it failed at its count with "import of isaacsim.core.utils.viewports halted; None in sys.modules". Before that line `set_camera`, `look_at_prim` and `inspect_prim` had all aimed within 0.5 degrees | fixed in `fd6f4f9`: the recorder keeps its count on `sys` |
| F12 | minor | `tests/test_integration.py`, `test_03b` | Found by the live run. It read `/World`, which a fresh Kit's stage hasn't got until an earlier test makes one, so run first it failed with "Prim not found: /World" | fixed in `fd6f4f9`: it makes prims of its own and checks the tree at depth 0 and 1 |

Refuted, each from the code:

- **The transform writer and its callers:** Kit's triple of translate, orient and scale; the ops landing where they
  should; Euler angles and quaternions kept as given; `!resetXformStack!`; the identity filter; a singular matrix;
  refusals by layer; anything left behind by a refusal; `clone_prim` writing in the root layer; leftovers of
  `_apply_xform`; USD off the main thread; `look_at`'s maths away from the poles.
- **The camera:** the catch of Isaac Sim's scale of about 3.4e38; a position equal to the target; the session layer;
  a camera under a moved parent; the centre of interest; whether `test_12f` tells its two paths apart; USD off the
  main thread; `inspect_prim`'s error for each angle; `_set_camera_xform`'s removal; `set_camera` answering an error
  when Isaac Sim's call raises.
- **The other rows and the docs:** `set_material` against an older extension; the tree's and the dump's counts; the
  extra `IsDefined`; `delete_prim`'s `checked` marker; `get_recording_frame`'s paths; the order of the recording
  refusals; the maintainer's ask that eight tools #77 will merge change only by what each fix needs; the one-way
  doors.

Improvements:

| Improvement | Answer |
|---|---|
| Handler tests of `inspect_prim`'s top and bottom views, which only the core's `look_at` covered | taken in `29e8d1f`, with F3 |
| A note in `CAMERA_AIM` (`tests/conftest.py`) that a scene camera's `omni:kit:centerOfInterest` may land in the root layer, which the live check doesn't look at | taken in `fd6f4f9` |
| Take `_aim_camera`'s snapshot only when Isaac Sim's module loads | left: it is restored only after Isaac Sim's call already; taking it reads the camera's ops, nothing more |
| `_call` in place of the older tests' own client setup in `tests/test_tools.py`; `format_scene_tree` sharing a helper with `format_prim_block` | left: refactors outside the fix |
| `clone_prim` with `offset=[]` is now an error, where it was taken as no offset | left: an empty offset is malformed, and the error says what it takes |

Not covered: the reviewers ran nothing. The transform reviewer didn't look APIs up in Context7, and the live tests
were read, not run, by the reviewers; the live run ran them (below).

## Round 2

**Where:** the fixes since round 1, `b611899..092c0a5`, and what merging `main` (#89) changed beyond `main`
(`88e9484`, `a56c807`), at `a56c807`. One fresh reviewer on Claude Sonnet, who read the fixes and the record and ran
nothing. **Verdict:** clean.

It confirmed each fix of F1 to F9, F11 and F12, naming its test and the line it exercises, and agreed with F10's
wontfix.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F13 | minor | `docs/ARCHITECTURE.md`, the formatter's functions | F8's re-wrap joined `format_frame_state()`'s bullet to the one before it, so it read as part of `format_scene_tree()`'s | fixed in `cdc31fe` |

Refuted, each from the code:

- **`stage_prim_of` for an arc deeper in, a variant or an inherit the file authors:** the walk climbs to the node
  under the root and takes the path it was introduced at. Tested since `cdc31fe` for a variant the file authors and a
  reference three files deep, both for the delete and for the refusal's words.
- **`Pcp.NodeRef.parent` at the root:** the walk never starts there, since an arc of the stage's own layers doesn't
  walk.
- **The new skip letting through a prim the stage's own layers bring:** a sublayer's arc is introduced in the root
  layer stack, so it still reaches the check and is refused.
- **The ancestral branch running before the skip:** a part a file's own arc brings stays after `RemovePrim`, so it is
  refused, as it should be.
- **`Snapshot.restore` removing an op the user had:** it removes only op attributes the prim didn't have when the
  snapshot was taken, and `xformOpOrder` isn't one of them.
- **`_blocker`'s `frozen`:** a stronger layer's default refuses earlier in the loop, which runs strongest first.
- **`look_at` at both poles:** derived by hand on both up axes; they match the docstring.
- **`create_prim`'s `held`:** `GetAddedOrExplicitItems` applies the list's edits, so prepended, appended and explicit
  items all count; a reference with another prim path or offset is another reference, and only the one added goes.
- **`_unit`:** the tool's schema makes the parts floats before it runs; large finite parts are scaled.
- **The live tests' changes:** the count on `sys` is reset at each use; the merge's stub names the handler's imports
  exactly.

Improvements:

| Improvement | Answer |
|---|---|
| Test arcs deeper than one file and a variant the file authors | taken in `cdc31fe`: a variant, and a reference inside a reference inside a reference, for the delete and the refusal; each new case but the variant's delete fails against `b611899`'s `deletion.py`, and that one was right already, since a variant on `/Robot` doesn't define `/Robot` |
| `delete_prim`'s refusal said "a inherit" | taken in `cdc31fe`: each arc's name carries its article, and the test checks the words for each kind |
| `GetAppliedItems` in place of the deprecated `GetAddedOrExplicitItems` | left: the old name is in every USD this supports; the new one's Python binding is unchecked on Kit 107 |

Not covered: Pcp's behaviour for an implied class arc, and for an internal reference whose target carries a
sublayer's reference, which the docs didn't settle; the likely failure there is a refusal, not a "Deleted" that
leaves the prim.

## Live run

Isaac Sim 6.2.0 headless (pip, Windows, RTX 5090), my own Kit at 8212, a fresh Kit for each run,
`OMNIVERSE_MCP_SIM=1`, through a script in three steps: (1) the new and changed integration tests alone (`test_03b`,
`test_07b`, `test_08b`, `test_11`, `test_12`, `test_12f`, `test_21b`); (2) both live suites whole; (3) step 1 again,
on the Y-up stage the suites leave.

- **On `b611899`:** step 1, 5 passed and 2 failed (F11, F12); step 2, 178 passed and 11 subtests, 1 failed (F11), in
  154.59 s; step 3, 6 passed and 1 failed (F11).
- **On `a56c807`, the fixes and the merge of `main`:** step 1, 7 passed; step 2, 182 passed and 16 subtests in
  164.03 s. Step 3: Kit hung (below).
- **On `cdc31fe`, the head:** step 1, 7 passed; step 2, 182 passed and 16 subtests in 170.61 s. Step 3: Kit hung at
  the same point.
- **What printed,** each step: the tree at depth 0 and 1; `delete_prim` refusing a part of a referenced file, "it
  comes through a reference on /World/IntTestRef"; a pivot kept and a matrix moved in place; the camera at its
  position 0.000 degrees off, and straight down a Y-up stage 0.000 degrees off with a scale of 1; `look_at_prim`
  0.000 degrees off; "Aimed through USD with Isaac's call left undone, and without Isaac Sim"; 3 copies, each its
  matrix kept and moved by its offsets.

**The hang.** Both times in step 3's `test_12f`, at the first capture after Isaac Sim's module is hidden; every call
after it timed out.

- Kit's log ends right after that capture deleted its render product, with no error.
- `py-spy dump --native`, twice ten minutes apart on the first hung Kit and once on the second: the main thread
  active, holding the GIL, in `omni.behavior.scripting.core`'s `ScriptManager._pending_sync_task_handler`
  (`script_manager.py:325`), `GetPrimsWithAppliedAPIName("OmniScriptingAPI")` on its `usdrt` stage, spinning inside
  `usdrt.population` and `omni.fabric`. No frame of the bridge on any stack. That sync runs after any prim is added
  or removed, so after every capture, whose render product is a prim.
- Not reproduced in pieces on a fresh Kit, each run clean:
  - a stage opened from a file whose folder is then deleted, as scenario 17.7 leaves it, then aims and captures
    with Isaac's module and without it;
  - the same on the stage the suites leave, after both suites;
  - after both suites, `test_12f` alone; then `test_03b`, `test_07b` and `test_08b`, then `test_12f`; then
    `test_11` and `test_12`, then `test_12f`; then step 3's seven tests together.
- Those runs skipped step 1 before the suites; the two that hung ran it. A third run of the whole script on
  `cdc31fe`: steps 1 and 2 the same (7; 182 and 16 subtests in 161.78 s), and step 3 hung at the same line, the same
  frame on the stack.
- **The script with `test_12f` left out of step 1,** on `cdc31fe` and a fresh Kit: step 1, 6 passed; step 2, 182
  passed and 16 subtests in 160.73 s; step 3, all 7 passed, `test_12f` among them.
- **So the hang needs `test_12f` run on a fresh Kit, then the suites, then `test_12f` again.** What `test_12f` adds on
  a fresh Kit is the test's own patching, not product code: it puts a recorder in place of Isaac Sim's
  `set_camera_view` and makes `isaacsim.core.utils.viewports` unimportable. The aims without Isaac Sim write the
  same values in the session layer that `test_11`'s straight-down aim writes, and `test_11` ran in that clean step 1.
- The same class as #54: Kit's main thread spinning in NVIDIA's native code during a long live run, with none of
  the bridge's code on the stack. The script's order is the only one known to set it off; the suites alone, the
  usual run, pass.

Not shown: Kit 107 (Isaac Sim 5.x), USD Composer and the Isaac Sim GUI. The path USD Composer runs, without Isaac
Sim's module, was forced live by hiding it.

## Checks

- **The gate,** `uv run tools/gate.py full`: on `5560f67`, the code `b611899` reviewed, 1403 passed and 181 skipped,
  coverage 96.48%; on `092c0a5`, 1425 passed and 181 skipped, 96.45%; on `a56c807`, after merging `main`, 1440
  passed and 184 skipped, 96.49%; on `cdc31fe`, 1444 passed and 184 skipped, 96.52%.
- **Each fix's new tests against the file before it,** swapped in from `b611899` one file at a time: `deletion.py`,
  all 6 of F1's fail; `xform.py`, 6 of F2, F3 and F6's 7 fail, the top view, right already, passing; `scene.py`,
  F4's test fails, its guard of a reference already held passing; `simulation.py`, 5 of F7's 6 fail, the direction
  of length 1 passing. After round 2, against `a56c807`'s `deletion.py`, the inherit's words fail.
- **The merge of `main` (#89):** `CHANGELOG.md`'s Unreleased conflicted, and both sides are kept. #89's new handler
  test faked the handler's `_utils` with the names it imported before this change, which replaced `_apply_xform`
  with `_first_missing`: fixed in `a56c807`.
