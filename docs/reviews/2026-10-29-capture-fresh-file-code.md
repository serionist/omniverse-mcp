---
subject: "Give each capture a file of its own, read once it is whole (PR #33, #32)"
base: main (c0c2957)
head: 063f643
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: a file per capture

Read from the pack (the scope diff), the touched files in full, the callers of `_capture_frame`, the recording loop,
and Kit's own `capture.py` in Kit 107 (Isaac Sim 5.1) and Kit 110 (Isaac Sim 6.2), with CI's results on the head
(every leg passed). Two minors, fixed in the commit this record follows; two improvements left for #35.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/_utils.py`, `ovmcp/core/png.py` | `_utils.py` imported `ovmcp.core.png`, which imported numpy at the top: in a Kit app without numpy (one that never enables `omni.kit.pip_archive`), the whole bridge failed to load, `/health` included. Before, only a segmentation capture needed numpy, and `camera.py` imported the PNG writer late to say so. | Fixed: `encode_png` imports numpy when it runs, so the module loads without it; `camera.py` imports it at the top again. `test_the_module_loads_without_numpy` fails on the old module. |
| F2 | minor | `tests/test_integration.py`, `test_15b_inspect_frames_show_their_own_angle` | Its materials went to `/World/Looks/Top_Mat` and `/World/Looks/Bottom_Mat`, which a run with `-k 15b` left in the developer's stage: `tearDownClass` deletes the pair, not `/World/Looks`. | Fixed: the materials go under `/World/IntTestPair/Looks`, so deleting the pair takes them too. |

Refuted, each from the code or Kit's source:

- **A file still being written already ends in IEND:** that needs writes out of order; all 43 Kit-written leftovers
  in the temp folder start with the signature and end with the exact IEND chunk.
- **Leftover files:** none named `ovmcp_capture_*` after the PR's live runs, where the old code left 43; a name that
  leaks is never read again.
- **A ten-second wait inside the recording's update callback:** `_on_update` only schedules `_record_tick` as its own
  task.
- **Recording on a timeout:** the empty marker, its metadata entry and the next frame number, as before.
- **The black-frame retry:** it calls `capture_viewport_png` again, with a fresh path.
- **The deadline loop:** the last read is checked before it raises; `finally` deletes on every path.
- **Kit 107:** its `capture.py` has the same `wait_for_result(completion_frames=2)` and the same
  `capture_viewport_to_file(viewport, file_path=str)`.
- **Kit 110's mechanism:** `save_aov_to_file` hands the write to the renderer and marks the capture done at once, so
  `wait_for_result` returns before the file exists, as the helper's comment says.
- **The live test depends on other tests' state:** it reads the up axis, makes its own previous capture, lights its
  own pair, and passes under the lighting modes the suites leave; only "off" left by a failed test would break it.
- **The test can't tell the bug from the fix:** with captures one behind, top, bottom, top reads bottom, top, bottom,
  and `top_red > top_blue + 5` fails; it did on the old code.

Not covered: no live check on Kit 107 (from its source only). bridge-security found nothing; the uuid names replace
predictable temp names.

Improvements, both left for #35, as each changes how a capture fails and needs a live run:

- **Fail fast on an empty `wait_for_result`,** which today still waits ten seconds per angle.
- **Bound `wait_for_result` itself,** which can hang the capture and the viewport lock on a viewport that never
  renders.

## Live run

On `063f643`, Isaac Sim 6.2.0 (pip, headless) on port 8212, with the extension installed from the branch; the
maintainer's own Isaac Sim on 8211 was not touched. From a cold Kit start, the live suites (`-k "not test_10_ and not
test_14_"`, #5): the first run 110 passed with #6's two and #7's three failing, the second 112 passed with #7's three
failing; `test_15b` passed in each with margins near 50 of 255, and failed on the old capture code.

The fixes (an import moved, the test's material paths) were not run live: the Kit app was stopped on the maintainer's
request to free memory overnight. The module's import without numpy is pinned by a unit test.

## Checks

`uv run tools/gate.py full` passed on `063f643` (665 tests, 93.34%) and on the fixes.
