---
subject: "Render capture_viewport and inspect_prim at the size asked for (#51, #70)"
base: main (a724ca9)
head: ad47884
date: 2026-10-30
round: 1
tier: standard (two fresh reviewers, Claude: the Kit side; the server and docs; checked by the author)
verdict: clean
---

# Review: captures at the size asked for, through a feed of their own

The plan `docs/plans/2026-10-30-capture-at-the-size-asked-for.md`, built on `51-capture-size` after #57 and #25
landed. Read from the diff of `ad47884` against `a724ca9`, with `00193b4`, made after it, read too. No blocker or
major; six minors, all fixed, with a test each where code changed. Both reviewers confirmed that no one-way door
moved. The reviewers' own ids are the finding ids.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| K1 | minor | `handlers/camera_feed.py`, `release` and `_release_step` | An error of omni.syntheticdata's skipped the whole teardown: `SyntheticDataException` derives from `Exception` alone, outside `_RELEASE_ERRORS`, and `disable_sensors` raises it when `get_stage()` is None (`deactivate_node_template`, 0.6.17 lines 1752-1755). The release then left before `drop()` and before the `finally` that hands the feed to the leftovers: a stage closed during a segmented capture gave a 500 and a feed that rendered on and carried its render product onto the next stage. | Fixed in `8fda424`: the sensor is left alone without a stage (omni.syntheticdata reset its graphs as it closed); `SyntheticDataException` is caught by name where omni.syntheticdata loads; the drop, the graph free, the two updates and the leftovers sit behind a `finally`. `test_omni_syntheticdata_s_own_error_leaves_the_rest_of_the_release_to_run`, `test_with_the_stage_closed_the_sensor_is_left_alone_and_the_feed_still_goes`, `test_an_error_no_step_expects_still_drops_the_feed_and_its_render_product` |
| K2 | minor | `AGENTS.md`, Traps | The `d688f31` row said the sensor is made at startup and enabled again when empty, which captures no longer rely on; the #32 row named `capture_viewport_png`, where the guard is now `capture_file_png`. | Fixed in `8f51b2f`: "Sensor turned on for each capture's own feed", and `capture_file_png`; still 150 lines |
| K3 | minor | `tests/test_capture.py`, `test_colouring_a_4096_a_side_capture_is_one_pass` | At 50 ids the old mask-per-id loop would pass too, in about 2 to 4 s against the 10 s bound. | Fixed in `56e4384`: 2,000 ids, which a mask per id couldn't finish in the bound; the one-pass colouring takes under a second |
| D1 | minor | `CHANGELOG.md` | A plain `capture_viewport` now sets Kit's unsaved-edits flag, as TOOLS.md says, where on `main` only a capture with `camera_path` did. | Fixed in `8f51b2f`: a clause in the Fixed line |
| D2 | minor | `CHANGELOG.md`, Changed | The stricter size check went unnamed: a `width` or `height` that isn't a whole number, or a request with one of the two alone, is refused through `mcp.*` in `execute_script` or the HTTP routes. | Fixed in `8f51b2f`: a Changed line |
| D3 | minor | `docs/TOOLS.md`, `capture_viewport` | The older-extension `WARNING` wasn't documented, as `start_recording`'s is. | Fixed in `8f51b2f`: a note under `capture_viewport`, and a sentence under `inspect_prim` for its own warning |

Refuted, or checked and found right, by both:

- **The one-way doors:** none moved: tool names, schemas and annotations as `tests/fixtures/mcp-tools.json` holds
  them (only descriptions changed, which `tools/golden.py` strips), the wire paths, the auth header, the output
  folder.

Refuted, or checked and found right, on the Kit side:

- **The teardown's order:** as E16 measured: the sensor off, the feed dropped, the graphs popped and reset under a
  session-layer `EditContext`, two updates, then the leftovers. Replicator pops and resets the same way, with the
  same rule for which graphs are the render product's.
- **A release on every path:** `handle_capture` releases in a `finally` once a feed exists; `handle_camera_inspect`
  in an inner `finally` around the isolate restore (`ad47884`); a cancelled call still hands its feed to the removal
  list; a stage change waits for `OPENED`. The lines between `_new_feed` and the `try` in `handle_camera_inspect`
  can't raise.
- **The private registry fails closed:** `enable_segmentation` checks for `_nodeGraphs` and `_reset_node_graph` first
  and gives the reason as `segmentation_error`; both names exist in omni.syntheticdata 0.6.13 and 0.6.17.
- **No growth in the registry per capture:** turning the sensor off pops `_graphNodes` and `_activatedNodePaths`;
  the free pops `_nodeGraphs`.
- **Render vars stay out of the user's file:** `activate_node_template` runs under the session layer.
- **The main thread:** no executor and no thread; `_on_frame` does no USD work.
- **The waits are bounded,** through `frames`, `bounded` and `poll`: at worst 80 s for a capture and 90 s for an
  inspection, under the client's 120 s.
- **The boxes:** `get_view_params` reads only `camera_path` and `resolution`, nothing assigns `viewport.camera_path`
  any more, and `screen_box` scales by 1 at the PNG's size.
- **`SegmentationWaits` and its 1 s retry hold:** the sensor is turned on some 15 updates before the feed's first
  frame (E12), and a read with data clears the record.
- **`colour_instances`:** the same image and legend as before; an id with no name, or an empty one, reads
  `instance_<id>`; `.reshape(-1)` handles NumPy 2.0; its cost doesn't grow with the number of ids.
- **`_get_stage()` outside `handle_capture`'s `try`:** without a stage the call fails with that message before
  anything is made.
- **The settle after isolate's restore:** bounded by `CLEANUP_SECONDS`, and it only warns.

Refuted, or checked and found right, on the server and the docs:

- **The boxes file's header** prints the answer's size, which is right: it names the frame the boxes are in, and with
  this extension it is the PNG's.
- **`_sizes` can't print `NonexNone`:** every `/sim/capture` answer has carried `width` and `height`.
- **`test_tools.py`'s capture case doesn't trip the warning:** its PNG is the 8-byte signature alone, so `_png_size`
  gives None.
- **`inspect_prim` reports the size asked for,** which is right: the feed renders at that size by construction.
- **The stricter size check over HTTP isn't a door broken:** the wire protocol's door is its paths, the auth header
  and the token file's place; the MCP schema stays `int`, `ge=1`; on `main` a width sent as text already failed,
  without saying so.
- **Old and new together:** an older extension with this server gets the warning, and an older `inspect_prim` answer
  without `width` and `height` is guarded and tested; this extension with an older server keeps every field its
  answers had.
- **`00193b4`:** with an 18 mm lens the cube sits inside `test_12c`'s frame, so the test now shows which camera the
  boxes came from (#70).

Improvements:

| Improvement | Answer |
|---|---|
| Drop the viewport capture path nothing calls any more: `capture_viewport_png`, `capture_png`'s `next_frame`, `FRESH_FRAMES`, `Png.fresh_seconds`, the slow-capture log's always-0 fresh frames, their tests, with the guard over what the handlers call adjusted | taken in `56e4384`: the guard now checks that recording and both capture handlers capture from a feed and that no handler calls `capture_viewport_to_file`; ARCHITECTURE no longer says the viewport path stays. `_next_frame` and `_viewport_frames` stay for the settles |
| Drop the viewport's sensor enabled at startup (`extension.py`, `_init_sensors`) | later: the main session opens an issue for it |
| A fake-Kit test that both handlers release their feed on success, on a capture that raises, and on an isolate restore that raises, as `tests/test_debug_draw_handler.py` loads its handler | taken in `1f2f1bb`: `tests/test_camera_handler.py`; its isolate case fails on `227a3cb`'s handler, before `ad47884`'s fix |
| `inspect_prim`'s older-extension warning, comparing the first image's size with `width` x `height` | taken in `d9c9ea7`, with its tests |
| Clearer live failures in `test_12b` and `test_13b`: say which output is missing before reading its size | taken in `8f51b2f` |
| `plugin/skills/scene/SKILL.md`'s trap "A capture right after a camera move shows the old view" no longer holds for `capture_viewport` (E14) | taken in `8f51b2f`: the trap is now code of one's own that reads the viewport in `execute_script`; the two capture tools render the camera afresh |

Not covered: the bridge's security (no route, header or token changed), the GUI (the viewport and its menus left as
they were, plan Q5), Kit 107.

## Live run

On `ad47884`, Isaac Sim 6.2.0 headless, a fresh Kit at port 8212 with the branch's extension, run by the main session
with `build-51-live.sh`:

- **The new and changed capture tests** (`test_integration.py -k "test_12 or test_13 or test_15"`): 13 passed in
  38.89 s.
- **Both live suites, nothing excluded:** 163 passed in 138.73 s, no failures.

| Test | Measured |
|---|---|
| `test_12b` | The cube's box against its segmentation pixels, within a pixel at every size: 320x240 `[72.9, 43.8, 247.1, 222.0]` and `[73, 44, 247, 222]`; 640x360 `[145.8, 27.7, 494.2, 360.0]` and `[146, 28, 494, 360]`; 360x640 `[82.0, 234.3, 278.0, 434.7]` and `[82, 234, 278, 434]`, so the plan's R5 doesn't arise |
| `test_12c` | `/World/IntTestCam`: box `[0, 0, 640, 480]`, its pixels the same; the cube filled the frame, which `00193b4` changes |
| `test_12d` | 14 paths under `/Render` before and after both a capture and a failed one |
| `test_15c` | segmentation after 16 reads, the 15 empty ones the test injects and then Kit's |
| `test_15d` | 2 angles, each saying why, in 6.5 s |
| `test_15f` | `set_camera`, `inspect_prim` and the isolated `inspect_prim` each answered in 3.0 s, with `FRAME_SECONDS` at 3 |
| `test_16_08`, `test_16_09` | drawn and captured at once through a feed, 5 of 5 each: 840 and 1048 strongly red pixels, 0.16 to 0.22 s a capture |
| `test_17_06` | two captures, a new stage, a third: segmentation each time, nothing in Kit's log |

Not shown: Kit 107 (Isaac Sim 5.1 crashes in its own start on this machine), the GUI, and the commits after
`ad47884` (`00193b4` and the fixes above), which wait for the live re-run.
