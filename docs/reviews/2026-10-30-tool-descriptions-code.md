---
subject: "Rewrite the tool descriptions so an agent picks and calls each one right (#78)"
base: main (584d6e9)
head: 0714306
date: 2026-10-30
round: 1
tier: standard (one fresh reviewer on Claude; findings checked against the code by the author)
verdict: clean
---

# Review: the tool descriptions

Read from the branch's diff, each tool's server function, the client's call and the bridge's handler behind it. No
blocker or major; eight minors, each a description that said more or other than the code does, all fixed in
`649cdb6`. The change stays to wording: the code fixes the reviewer suggested went to #82.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `capture_viewport`; `docs/TOOLS.md`, its note on `omni.syntheticdata` | "Without omni.syntheticdata the image and boxes still come" is wrong: `_compute_screen_bboxes` imports it (bridge `camera.py:307-308`), and `handle_capture` answers `screen_bboxes: []` when that fails (`804-809`), which the server prints as "none (no visible prims)" | fixed in `649cdb6`: without it only the image comes, the boxes and segmentation need it; TOOLS.md's note says the same |
| F2 | minor | `clone_prim` | With `offset`, every copy it places, and a single copy, goes through `_apply_xform`, which keeps only translate, rotateXYZ, orient and scale, counted from the source's translate or `[0, 0, 0]` without one (bridge `scene.py:459-469`, `_utils.py:301-336`): a matrix-placed source's copies lose that placement, which the description didn't say | fixed in `649cdb6`, description and TOOLS.md |
| F3 | minor | `get_scene_tree` and its `max_depth` | "A branch cut at max_depth shows how many children it holds" and "0 for root alone" don't match text mode, the only one the tool asks for (bridge `scene.py:49-58`). The reviewer read it as no count at all; the code prints `children = N (truncated)` for each prim of the next level that has children, and drops that level's childless prims and everything deeper. So `max_depth=0` lists the root and those of its children that have children | fixed in `649cdb6` as the code reads: the level after `max_depth` lists only prims with children, with their count; the parameter and TOOLS.md say so |
| F4 | minor | `get_recording_frame`, `session_dir` | The bridge joins `session_dir` against Kit's working folder (handler `recording.py:389-391`), while `start_recording` and `stop_recording` print the folder relative to the server's, so the folder they name may not be found | fixed in `649cdb6`: pass an absolute path, or one relative to Kit's working folder |
| F5 | minor | `inspect_prim` | It moves whichever camera the viewport looks through (bridge `camera.py:625`), a scene camera included, and doesn't put it back; the description said "the viewport's own camera" | fixed in `649cdb6` with `set_camera`'s words, and TOOLS.md |
| F6 | minor | `create_prim`, `enable_physics` | Both APIs go on the prim itself (bridge `scene.py:316-318`): under an Xform or a referenced file's root, the meshes get no Collision API, so "a rigid body with a collider" overstated it. Not checked live | fixed in `649cdb6`, worded as the code does it: the meshes under an Xform or a referenced file's root get no Collision API of their own |
| F7 | minor | `set_joint_targets`, `get_joint_states` | They said metres for prismatic joints, where `get_robot_info` says stage units, as USD and PhysX work | fixed in `649cdb6`: stage units, in both descriptions and TOOLS.md |
| F8 | minor | `raycast`, `direction` | "It is normalised" is not so: the handler passes it to `raycast_closest` as given (bridge `simulation.py:304`), whose parameter omni.physx calls `unitDir`. This was in the parameter's text before #78 | fixed in `649cdb6`: a unit vector, which PhysX takes as given; TOOLS.md too |

Refuted, each from the code:

- **The `tool()` registration:** `_annotations.tool` passes the hints and `inspect.cleandoc(fn.__doc__)` to
  `MCPServer.tool`, whose `Tool.from_function` (mcp 2.3.0) uses `description or fn.__doc__`; cleandoc changes nothing
  of a docstring Python 3.13 already stripped. `tests/fixtures/mcp-tools.json` is unchanged and `test_contract.py`
  passes.
- **`set_prim_transform`'s matrix qualifier:** `_apply_xform` reads only translate, rotateXYZ, orient and scale ops,
  then clears the op order (`_utils.py:262-336`), so a matrix op goes, as the description says.
- **The rest, each read against its handler and found as described:**
  - `save_scene`: an export keeps the stage tied to its own file, and a stage never saved is refused;
  - `flatten_usd` and `export_prim_as_file`: each clears an open layer of its path's name first;
  - `set_variant_selection`: 40 app updates with Fabric Scene Delegate, 5 without;
  - `look_at_prim`: 2.5 times the largest side, the azimuth's axes, and aiming only in Isaac Sim;
  - `set_camera`: the target defaults to the origin;
  - `inspect_prim`: its 80 s (`CALL_SECONDS`);
  - `get_mesh_stats`: meshes only, inside instances, each mesh listed up to 20;
  - `set_material` and `set_physics_properties`: the material paths named after the prim;
  - `dump_scene`: one file, replaced by the next dump;
  - `create_variant_structure`: an existing set or variant kept, and the default's fallback;
  - `compare_prims`: which mode wins, names unchecked, the selection put back;
  - `manage_extensions`: the first 50, a search by name or id;
  - `get_recording_frame`: the last recording's folder, a failed frame's empty file, and the time only after stop;
  - `execute_script`: the main thread, the `str` fallback, the 120 s;
  - `get_sim_state`: `fps` is time codes per second;
  - `apply_force`: its refusals;
  - `create_robot`: its naming and refusals.
- **The inspection cluster:** `get_scene_tree`, `dump_scene`, `get_prim_properties`, `get_prim_bounds`,
  `get_mesh_stats`, `get_prim_face_count_tree` and `compare_prims` name each other consistently, and say which see
  inside instances (`TraverseInstanceProxies`) and which don't (`GetChildren`).
- **The writing rules:** no em dash, none of the banned words, British spelling, in the descriptions, TOOLS.md and the
  CHANGELOG line.

Improvements:

| Improvement | Answer |
|---|---|
| Cut what the server's instructions or a parameter already say, about 1.3k characters: `get_sim_state`'s "Call it first", `execute_script`'s Context7 sentence, `get_logs`' "when any tool fails", `capture_viewport`'s `include_image` sentence, `apply_force`'s "(#68)", `get_joint_states`' "tested on 6.2", the module name in `set_camera` and `look_at_prim`, `inspect_prim`'s render sentence, `draw_debug`'s backends down to the side effect, `start_recording`'s state-file format | taken in `649cdb6`. The fixes above add back about 1.1k, so the descriptions come to 23,692 characters, from 23,889 at `0714306` and 9,714 on `main` |
| The indentation test compares each description with its `inspect.cleandoc`, so an indent of the text's own passes | taken in `649cdb6`; `execute_script`'s example stays inline, which reads as well and is shorter |
| `capture_viewport`'s boxes: "each visible mesh or shape", since Xforms are skipped (bridge `camera.py:330-336`) | taken in `649cdb6`, and TOOLS.md |
| `set_prim_transform`: `get_prim_bounds` gives a box's centre, not the prim's origin; `get_prim_properties`' `pos` is the origin | taken in `649cdb6`, and TOOLS.md |
| `dump_scene`: what sets it apart from `get_scene_tree` is the properties and depths beyond 15, not a scene's size | taken in `649cdb6`, and TOOLS.md |
| Regenerate the list of every description from the final head | taken: written outside the repo, for the coordinating session |

Not covered: the Kit main thread and bridge security, since no bridge code changed; the live suites, since no tool's
behaviour changed (the Checks below took the claims that rest on Kit).

## Checks

- **Five claims about Kit and USD, live:** checked by a script the author wrote (`e78_claims.py`), which the
  coordinating session ran on a fresh Kit at 8212 with `main`'s bridge, through the tools themselves: phase 1, then a
  clean stop and restart, then phase 2. Its outputs are `e78-phase1.txt` and `e78-phase2.txt`, outside the repo. All
  five confirmed:
  - an extension enabled through `manage_extensions` stays on until Kit restarts, and isn't saved: `omni.debugdraw`
    stayed on with no persistent setting naming it, and was off after the restart, with `user.config.json` not
    naming it;
  - stop puts PhysX's bodies back: a cube fell 48.412; after stop and a step it was 0.0272 from its start, and USD
    was back at the start after the stop;
  - `raycast` names a static collider itself (`/World/E78/Static`), names the rigid body rather than its shape
    (`/World/E78/Body`), and passes a cube with no collider ("No hit"); before any step since the colliders were
    made it answered "No hit", as the description warns;
  - `delete_prim` leaves a child a reference brings in and answers "Deleted", while a prim of the edit layer goes;
  - Kit's undo doesn't record `update_material_paths`: the undo stack was unchanged, 1 entry, the same last one.
- **The indentation test:** it failed on Python 3.12 before `tool()` stripped the docstrings in `0714306`.
- **The gate:** `uv run tools/gate.py full` passed on `649cdb6`: 15 checks, 1168 passed and 165 skipped, coverage
  95.86%.
