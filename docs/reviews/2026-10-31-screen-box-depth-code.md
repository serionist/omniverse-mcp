---
subject: "Leave a prim behind the camera out of capture_viewport's boxes (#90)"
base: main (7749c8a)
head: 2440922
date: 2026-10-31
round: 1
tier: standard (one fresh reviewer on Claude Sonnet; findings checked against the code by the author)
verdict: needs-fixes
---

# Review: capture_viewport's boxes and the camera's depth

Read from the branch's diff: `core/bounds.py`'s `project_in_front`, `_compute_screen_bboxes` in `handlers/camera.py`,
the unit tests, the new live test, TOOLS.md and the changelog, against `omni.syntheticdata`'s own projection. One
major, in the live test, and an improvement taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tests/test_integration.py`, `test_12g_a_prim_behind_the_camera_gets_no_screen_box` | `at()` swaps y and z on a Z-up stage, which mirrors the scene: the camera's right is +x on a Y-up stage and -x on a Z-up one, so the long cube at +x sat on the camera's left on Isaac Sim's default Z-up stage, and the test's checks that its box starts right of the middle and ends at the right edge would fail there | fixed in `1406b98`: the cube goes at +x on a Y-up stage and -x on a Z-up one. Live, it passes on both (below) |

Refuted, each from the code:

- **Kit's clip-space convention:** `get_projection_matrix`'s last column is [0, 0, 1, 0], so w is the view-space z;
  the camera looks down -z, so a point in front has w <= -near, for any camera transform, since `get_view_proj_mat`
  inverts `view_to_world`. `clipping_range[0]` is in stage units, as w is.
- **A prim wholly in front:** `project_pinhole` divides by w and maps -1..1 to 0..1 as `_projected` does, so its box is
  as before, y direction included.
- **The near-plane cut:** an edge is cut only where its ends differ, so `wb - wa` is never 0; a corner on the plane
  counts as in front and gives a duplicate point, which is harmless; `_EDGES` holds the 12 edges in `box_corners`'
  bit order.
- **The fisheye branch:** it keeps `world_to_image`; `get_view_proj_mat` is in the same module, so it is there wherever
  `world_to_image` is.
- **The docs:** no added line over 120 columns but the TOOLS.md list line, as the file's others; no banned words.
- **The live test's cleanup:** deleting its root removes the three cubes.

Improvements:

| Improvement | Answer |
|---|---|
| A clipping range from 0 and a box corner at the eye give w = 0, which `_projected` divides by | taken in `1406b98`: `project_in_front` keeps the near distance at least 1e-6; `test_a_near_plane_at_the_eye_divides_no_corner_by_zero` fails without it |

Not covered: the reviewer ran nothing; the live test's geometry was checked by hand and then live.

## Round 2

**Where:** the fixes `2440922..1406b98`, one fresh reviewer on Claude Sonnet, who read them. **Verdict:** clean.

It confirmed F1's fix by redoing the cross products for both up axes and each of the test's checks against Kit's
default camera, and the near guard and its test, which fails without it. No new findings; refuted: the long cube
landing off-screen on a Z-up stage, the right edge's 320.0 depending on rounding, and the guard changing anything for
a camera whose near distance is above 1e-6.

## Live run

Isaac Sim 6.2.0 headless, my own Kit at 8212, fresh each run, `OMNIVERSE_MCP_SIM=1`.

- **`main`'s extension (`7749c8a`), the branch's test:** `test_12g` fails on the fresh Z-up stage, as it should: the
  cube behind the camera got `[104.6, 64.6, 215.4, 175.4]`, near the image's middle, and the long one across the
  camera's plane `[49.1, 113.1, 270.9, 126.9]`, reaching into the left half.
- **The branch at `1406b98`:** `test_12g` on the fresh Z-up stage passed, ahead `[129.2, 89.2, 190.8, 150.8]`, across
  `[257.0, 0.0, 320.0, 240.0]`, behind none; both live suites whole, 183 passed and 16 subtests in 154.49 s; then
  `test_12g` on the Y-up stage the suites leave passed with the same boxes.

Not shown: a fisheye camera, which keeps Kit's projection; other Kit apps.

## Checks

- **The gate:** `uv run tools/gate.py full` passed on `2440922`: 1447 passed and 185 skipped, coverage 96.55%; on
  `1406b98`, 1448 passed and 185 skipped, 96.55%.
- **The old path against the new tests' boxes,** by hand on `_projected`: the box across the camera's plane came out
  `[200.0, 400.0, 650.0, 600.0]`, starting left of where its part in front does, and the box behind
  `[0.0, 250.0, 375.0, 750.0]`; the new path gives `[550.0, 0.0, 1000.0, 1000.0]` and no points.
