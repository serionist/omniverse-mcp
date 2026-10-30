---
title: Render capture_viewport and inspect_prim at the size asked for
issue: "#51"
status: draft
approved_by:
approved_at:
---

# Render capture_viewport and inspect_prim at the size asked for

## Goal

A capture's image, its instance segmentation and its screen boxes are one frame at one size: the size the call asked
for, which the answer reports. Today the image and the segmentation come at the viewport's size while the boxes are
scaled to the size asked for, so an assistant that places things by the boxes is off by the ratio of the two (E2).

True when this is done:

| | What | Shown by |
|---|---|---|
| 1 | `capture_viewport(w, h)` returns an image and a segmentation of w by h pixels, boxes in those pixels, and `w`x`h` in its text | `test_12b` (fails on `main`, E2) |
| 2 | `inspect_prim(width=w, height=h)` returns each angle, and its segmentation, at w by h, framed for that size | `test_13b` (fails on `main`, E10) |
| 3 | `capture_viewport(camera_path=...)`'s boxes are that camera's, not the viewport's own camera's (Q3) | `test_12c` (fails on `main`, E5) |
| 4 | Every call puts the viewport's size, render scale, "Viewport"-size mode and camera back as they were, a failed call too | `test_12d`, unit tests |
| 5 | A side above 4096 is refused before the viewport changes | unit tests, `test_12e` |
| 6 | A server talking to an older extension, whose boxes and image differ in size, says so and how to update | unit test |

Why it matters: the boxes file is how an assistant finds things in a capture without opening the image (the plugin's
`scene` skill says to read it first). With the default 640x480 against Isaac Sim's 1280x720 viewport, every box is
half the size and in the wrong place.

- **In scope:** the capture path of `capture_viewport` and `inspect_prim` in the bridge (`handlers/camera.py`,
  `handlers/_utils.py`), Kit-free logic for it in `ovmcp/core/`, recording's tick (it must not record a frame at a
  capture's size), the two tools' text and parameter descriptions, the docs, unit and live tests.
- **Out of scope:** `start_recording`'s camera and size (#25); Replicator render products; how boxes project for
  fisheye cameras or a non-default aperture conform setting; the bridge's protocol number; the extension's version.

## Design

### Where the mismatch comes from

| Fact | Where |
|---|---|
| The image is the active viewport's frame: `capture_viewport_to_file(viewport, file_path=...)` writes the viewport's own render product, at `viewport.resolution`. `width` and `height` never reach it | `handlers/_utils.py` `capture_viewport_png`; `handlers/camera.py` `_capture_frame`, which takes `width` and `height` and does not use them |
| The segmentation is the viewport's too: `syn.sensors.get_instance_segmentation(viewport)` reads the viewport's render product | `camera.py` `_segmentation` |
| The boxes are projected with `get_view_params(viewport)`, the viewport's size, then scaled to the size asked for: `screen_box(projected, (vp_w, vp_h), (img_width, img_height))` | `camera.py` `_compute_screen_bboxes`; `core/bounds.py` `screen_box` |
| The answer's `width` and `height` are the size asked for, and the tool prints them as the image's: `Viewport: 640x480` and the boxes file's header | `handle_capture`; `tools/camera.py` lines 77 and 96 |
| `inspect_prim`'s `width` and `height` only stand in for the viewport's size when it can't be read (`_viewport_resolution`); its images are the viewport's | `camera.py` `_compute_autofit_distance` |
| With `camera_path`, `_capture_frame` puts the viewport's camera back in its `finally`, before the boxes are projected and the segmentation read: the boxes are the viewport's own camera's | `camera.py` `_capture_frame`, then `handle_capture` steps 2 and 3 |

### What Kit does

Read in Kit's sources on this machine, Isaac Sim 6.2.0 (`D:\isaac\venv`, Kit 110: `omni.kit.widget.viewport`
110.0.1, `omni.kit.viewport.window` 110.0.5, `omni.kit.viewport.utility` 2.1.2, `omni.kit.capture.viewport` 2.11.1,
`omni.kit.viewport.menubar.settings` 110.0.2, `omni.syntheticdata` 0.6.17) and Isaac Sim 5.1 (`D:\isaacsim5.1`,
Kit 107: `omni.kit.widget.viewport` 107.1.3, `omni.kit.capture.viewport` 1.7.5, `omni.kit.viewport.menubar.settings`
107.0.3, `omni.syntheticdata` 0.6.13), and in NVIDIA's docs through Context7.

| # | Fact | Source |
|---|---|---|
| A1 | `ViewportAPI.resolution = (w, h)` takes the full resolution; the texture renders at it times `resolution_scale`, and the getter returns what the texture renders at. `full_resolution` is the unscaled one. The same on Kit 107 and 110 | `omni/kit/widget/viewport/api.py` lines 281-306, `impl/texture.py` lines 107-139 (110.0.1); 107.1.3 the same |
| A2 | After a resize, "An async renderer may still deliver frames from before this request" | `impl/texture.py` line 133 (110.0.1) |
| A3 | With the API's `fill_frame` on, every sync of the viewport sets the resolution back to the window's size | `api.py` `_sync_viewport_api`, lines 524-531 |
| A4 | The viewport window starts at `/app/renderer/resolution`, 1280x720 in Isaac Sim, or the window's size ("fill_frame") when either is 0 or less; Isaac Sim sets `defaults.fillViewport = false` | `omni/kit/viewport/window/layers.py` lines 116-146; `isaacsim.exp.base.kit` lines 229-239 (6.2), line 245 (5.1) |
| A5 | Kit's own Movie Capture renders at a size of its choosing the same way: it records the viewport's camera, resolution and Fill Viewport, sets `viewport_api.resolution = capture_resolution`, captures, then puts them back. It saves the scaled `resolution` and puts it back as the full one | `omni.kit.capture.viewport` `extension.py` lines 608-650, 910-935, 1030-1045 (2.11.1); lines 540 and 916 (1.7.5) |
| A6 | The widget's own "Viewport"-size and Fill Viewport options resize the viewport only when the window's size changes or the option is set | `omni/kit/widget/viewport/widget.py` lines 570-640 |
| A7 | Kit 110's resolution menu follows a delivered resolution "without applying it back to the viewport or persistent settings". Kit 107's selects the matching preset through `current_index.set_value`, whose handler writes the per-viewport persistent resolution | `menu_item/resolution_collection/model.py` lines 176-177 (110.0.2); `settings_renderer_menu_item.py` lines 361-375 and `model.py` lines 109-114 (107.0.3) |
| A8 | `get_view_params(viewport)` reads the viewport's camera and `viewport.resolution`; `world_to_image` gives fractions of it, a pinhole fitted to the horizontal aperture | `omni/syntheticdata/scripts/helpers.py` lines 251-301, 474-530, 551-569 |
| A9 | `capture_viewport_to_file(..., render_product_path=...)` with another render product swaps it into the viewport for the frame, then back | `omni/kit/viewport/utility/__init__.py` lines 356-440 (2.1.2) |
| A10 | The viewport's settings: Render Resolution, Render Scale ("Upsamples or downsamples your Viewport relative to the specified Render Resolution"), Fill Viewport; Movie Capture's width and height "of the rendered image" | Context7, Omniverse extensions docs: `ext_viewport/controls/settings`, `ext_movie-capture` |

### What Kit did, measured

Isaac Sim 6.2.0 headless (`run_isaac_port.py`, port 8212), 2026-10-30, by the planning session, against `main`
(`765d51c`) with a 1 m cube lit by a dome light; scripts `e51_size.py`, `e51_more.py`, `e51_scale.py`.

| # | Measured |
|---|---|
| E1 | The headless viewport renders at 1280x720, render scale 1, `fill_frame` off; its window is 1440x896 |
| E2 | On `main`, `capture_viewport(320, 240)`: image 1280x720, segmentation 1280x720, the answer says 320x240, the cube's box `[84.3, 32.5, 247.8, 240.0]` while its pixels span `[337, 98, 991, 720]`. At `(1280, 720)` the box `[337.3, 97.5, 991.0, 720.0]` matches its pixels `[337, 98, 991, 720]`: the boxes are right when the two sizes are equal |
| E3 | `viewport.resolution = (640, 480)`: `resolution` and `get_view_params` give it at once; the segmentation sensor delivers 480x640 on the next frame (0.08 s), with no re-enable; so does 1920x1080, and back to 1280x720 each time. The first capture after a set, with no frame waited for, is at the new size (320x240, then 1280x720 back) and as bright as the capture after it (640x480, 333x251, 1024x1024: means 214.1, 214.2, 217.6 both times). A resize and its capture take 0.1 to 0.2 s |
| E4 | With the viewport at the size, `main`'s own `handle_capture` gives image, segmentation and boxes that agree: 640x480 box `[168.6, 108.8, 495.5, 432.1]`, pixels `[169, 109, 495, 432]`; 640x360 `[168.6, 48.8, 495.5, 360.0]` and `[169, 49, 495, 360]`; 320x240 `[84.3, 54.4, 247.8, 216.1]` and `[84, 54, 248, 216]` |
| E5 | `capture_viewport(camera_path=<a camera beside the cube>)`: its segmentation shows the cube at `[301, 21, 979, 699]`, its box is `[406.8, 126.8, 873.2, 593.2]`, the viewport's own camera's. With that camera made the viewport's own, the box is `[300.6, 20.6, 979.4, 699.4]` |
| E6 | With `fill_frame` on, the viewport goes to the window's 1440x896, and a resize to 640x480 is undone within 3 frames. With it off, a resize holds through a camera move |
| E7 | Render scale 0.5 halves the capture (640x480 asked, 320x240 written). `frame_info["resolution"]` still said 1280x720 a frame after the resize, so it is no signal to wait on; the PNG's own header is |
| E8 | 3840x2160: the capture 0.66 s; `handle_capture` 0.8 s with segmentation and boxes |
| E9 | A Replicator render product at 640x480 with an `rgb` annotator, timeline stopped: 0.49 s cold, 0.22 s warm, for its creation and three `step_async` |
| E10 | On `main`, `inspect_prim(width=320, height=240)` and `(640, 480)` both return 1280x720 images, at the same fitted distance (2.8763 m) |

### The fix: the viewport renders at the size asked for, for the length of the call

As Kit's Movie Capture does (A5): the bridge puts the active viewport at the size asked for, captures, projects the
boxes and reads the segmentation from that same viewport, then puts the viewport back. Image, segmentation and boxes
then come from one render product at one size, which E3 and E4 show takes one frame headless and agrees to under a
pixel.

**Kit-free, `ovmcp/core/`:**

- `png.png_size(data) -> tuple[int, int] | None`: the width and height in a PNG's header; None for anything else.
- `capture.MAX_SIDE = 4096` and `capture.capture_size(body) -> tuple[int, int] | None`: the `width` and `height` of
  a request, whole numbers from 1 to `MAX_SIDE`; both or neither; None when neither is given. The `ValueError` says
  which and why. `framing.inspect_args` takes its size from it, so its 800x600 default goes.
- `capture.ViewportAtSize(viewport, size)`, a context manager over any object with `resolution`, `full_resolution`,
  `resolution_scale` and `fill_frame` (a `ViewportAPI` in Kit, a fake in the tests):
  - on entry it records the four, then, unless the viewport already renders at `size` at scale 1 with `fill_frame`
    off, sets `fill_frame` off (A3, E6), `resolution_scale` to 1 (E7) and `resolution` to `size` (A1);
  - on exit it puts back the scale, then the recorded full resolution, then `fill_frame`, each in its own `try`, so
    one that fails doesn't keep the others; what failed is returned for the bridge to log. Restoring the full
    resolution, not the scaled one, keeps a render scale other than 1 as it was (A5 gets this wrong);
  - `capture.resized()` says whether one is holding a viewport at another size, for recording.
- `capture.capture_sized(capture_once, size, next_frame, budget, clock)`: a capture whose PNG is another size (a
  frame from before the resize, A2) is taken again after a frame, within `FRAME_SECONDS` and the budget; then a
  `CaptureError` names both sizes. Headless, the first is already right (E3).

**Kit, `handlers/camera.py`:**

- **`handle_capture`:** the size is checked first, and a refusal leaves the viewport alone; a body without one is
  captured as the viewport stands, with no resize. Then, inside `ViewportAtSize` and with the viewport on
  `camera_path` for the whole block: the image (`_capture_frame`, through `capture_sized`, its black retry as now),
  the boxes and the segmentation, all before anything is put back. `_capture_frame` no longer switches the camera
  itself: the handler does, before the size, and puts it back after (Q3).
- **The boxes** are projected for the image's own size, the PNG's, which is the viewport's now: `screen_box` scales
  by 1.
- **`_segmentation`** waits for data of the image's size, not any data (E3: one frame).
- **`handle_camera_inspect`:** the viewport is held at the size from before `isolate` hides anything until after its
  restore and settle; the fitted distance uses the size asked for, so `_viewport_resolution` goes. Each angle's
  settle and capture are as now, through `capture_sized`.
- **The answers** report the PNG's size as `width` and `height`; `inspect_prim`'s answer gains them.

**Kit, `handlers/recording.py`:** `_record_tick` takes no frame while `capture.resized()`, so a capture during a
recording leaves a gap, which `metadata.json`'s `sim_time` shows, rather than frames of another size. Recording's
own size and camera stay #25's.

**Server, `tools/camera.py`:**

- The `Viewport:` line and the boxes file's header give the image's own size, read from its PNG header; an image
  whose header can't be read keeps the answer's. When the answer's size differs from the image's, the bridge is
  older than this fix, and the tool adds `WARNING: The image is 1280x720 but its boxes are for 640x480: the Kit
  extension is older than this server. Install this server's, <install_command()>, then restart Kit.`
- `inspect_prim`'s first line gives the size captured.
- `Width` and `Height` say what they do now: "Image width in pixels, at most 4096. The viewport renders at this size
  for the capture, then returns to its own." The docstrings say so too. Descriptions are prose, which the contract
  file leaves out (`tools/golden.py`, `PROSE`).

### How each way out behaves

| Way | Headless | In the GUI | Render time | Tool contract |
|---|---|---|---|---|
| **Resize the viewport for the call** (this plan) | Works: the first capture after a resize is at the new size, not black (E3, E4) | The viewport shows the asked size for the call's length, then its own again: some 0.2 s for `capture_viewport`, the orbit's length for `inspect_prim`, whose camera already moves the user's view. "Viewport"-size mode is turned off and back (E6). Kit 107's menu may write the size to its persistent setting meanwhile (A7, R2) | 0.1 to 0.2 s for the resize and back (E3); the default 640x480 renders a third of today's 1280x720 pixels | No change |
| A Replicator render product of the size (#25's plan) | Works stopped, with a step (E9) | Nothing visible, but each step applies Replicator's capture settings (grid, outlines, selection cleared) and runs every writer anyone attached; a cancelled step can leave the timeline frozen (#25's plan, F20 and round 3's P17) | 0.2 to 0.5 s a call (E9), plus a second render product | No change, but segmentation moves to an annotator and the boxes need a projection of a product that isn't a viewport (A8), and a Kit app without Replicator, such as USD Composer, needs today's path besides |
| Report the viewport's size and scale the boxes to it | Works | Nothing visible | None: the image stays the viewport's size, 1280x720 by default or the window's in "Viewport"-size mode | `width` and `height` would do nothing: removing them is Breaking (a one-way door), keeping them means documenting two ignored parameters |

### Alternatives

| Alternative | Why not |
|---|---|
| A Replicator render product, as #25's plan has for recording | Above: Replicator's global capture settings and the frozen-timeline risk #25 deferred, a second segmentation and projection path, and no Replicator in some Kit apps |
| Report the viewport's size, boxes scaled to it, `width` and `height` ignored or removed | Above: the cheapest, but the parameters stop meaning anything, and `include_image` costs the viewport's size in context |
| Resize the PNG after the capture | Distorts the aspect, or letterboxes it; upscaling blurs; the segmentation needs its own nearest-neighbour resize; the full-size render is still paid for |
| A second viewport window at the size (`create_viewport_window`) | A window pops up in the GUI; each new viewport is a cold renderer (#27's black first frames); its texture renders every frame until destroyed |
| `capture_viewport_to_file(render_product_path=...)` with a product of the size (A9) | Swaps the viewport's product for the frame, as visible as a resize, plus a prim to make and remove; `get_view_params` and the segmentation sensor still read the viewport's own product |
| Wait on `frame_info["resolution"]` after a resize | It lags the frames by more than a frame (E7); the PNG's header is the size that matters |
| Set Movie Capture's persistent Fill Viewport setting off too | A persistent setting outlives a crash; the widget's own options act only on a window resize (A6), which the PNG check catches |

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Which fix: resize the viewport for the call, a Replicator render product, or report the viewport's size and drop the size asked for? | Resize the viewport, as Kit's Movie Capture does: one render path for image, segmentation and boxes, measured at a frame headless, no contract change | |
| Q2 | The cap on a side: refused in the bridge only, the schema unchanged, or also `maximum: 4096` in both tools' schemas? | The bridge only, said in the descriptions: a schema bound is a contract change (Breaking in 0.x), and nobody could get more than the viewport's size before | |
| Q3 | Fix `camera_path`'s boxes (E5) in this change? | Yes, under an issue of its own that this PR closes too: the same disagreement between boxes and image, and the restructure that fixes #51 fixes it | |
| Q4 | In the GUI, the user's viewport shows the size asked for while a capture runs. Acceptable? | Yes: Movie Capture does the same, `camera_path` and `inspect_prim` already move the view, and a capture at the viewport's own size changes nothing | |
| Q5 | The GUI can't be tested here (port 8211 is yours). Run `test_12b` to `test_13b` once on the GUI Isaac Sim before merging, with "Viewport" size and with Fill Viewport on? | Yes, by you, the PR saying what it showed; or merge on the headless run with R1 and R2 accepted | |

## Compatibility

- **One-way doors:** none. Tool names, schemas and annotations stay as `tests/fixtures/mcp-tools.json` holds them:
  `width` and `height` keep their type, default and `minimum`, and only their descriptions change, which the file
  leaves out. `capture_viewport` stays read-only: it puts the viewport's camera and size back, as it already did the
  camera. The wire paths, the auth header, the output folder and the protocol number are unchanged.
- **What users notice:**
  - Captures come at the size asked for: 640x480 by default, where they came at the viewport's 1280x720 (Isaac Sim's
    default) or the window's size. Boxes, segmentation and image agree. Framing at 4:3 by default shows a little
    less to the sides than 16:9 did.
  - `inspect_prim`'s fitted distance follows the size asked for, so it changes with the aspect.
  - A side above 4096 is an error; `inspect_prim` at 20 pixels or fewer a side was refused already
    (`fit_distance`), now judged on the size asked for.
  - In the GUI, the viewport shows the asked size while a capture runs (Q4).
- **The bridge's answers:** `/sim/capture`'s `width` and `height` are the image's real size (they were the size asked
  for); `/camera/inspect` gains them. A body without `width` and `height` captures at the viewport's size, as every
  capture did; the bridge's 1280x720 and 800x600 defaults go. Only direct HTTP callers can omit them: the server and
  `execute_script`'s `mcp.*` always send them.
- **Versions:** an older extension with this server works, and the tool warns that its boxes don't match (Design);
  this extension with an older server works, its answers keeping their fields. Users update the extension as each
  release says. Kit 107 and 110 have the same resize API (A1); only Isaac Sim 6.2 runs live here.

## Steps

| # | Step | Test that proves it |
|---|---|---|
| 1 | Kit-free core: `png.png_size`; `capture.MAX_SIDE`, `capture_size`, `ViewportAtSize`, `resized`, `capture_sized`; `inspect_args` through `capture_size` | `tests/test_png.py`, `tests/test_capture.py`, `tests/test_framing.py`; `uv run tools/gate.py quick` |
| 2 | The bridge: `handle_capture` and `handle_camera_inspect` hold the viewport's size (and `camera_path`) over image, boxes and segmentation; `_segmentation` waits for data of the size; `_viewport_resolution` goes; the answers' size; recording's tick skips while resized | live: `test_12b` to `test_12e`, `test_13b`, then both live suites whole on Isaac Sim 6.2 headless |
| 3 | The server: the image's own size in the text, the warning for an older extension, `inspect_prim`'s size, the parameter descriptions | `tests/test_tools_camera.py`; `tests/test_contract.py` passing unchanged shows no schema moved |
| 4 | The docs (Docs) | `uv run tools/gate.py full` |

## Tests

**Unit (CI):**

| Test | What it holds |
|---|---|
| `test_png.py`: `png_size` | An `encode_png` image's size; None for `b""`, a short header, and something that isn't a PNG |
| `test_capture.py`: `capture_size` | None without a size; both given; one alone, 0, a negative, 4097, a bool, a fraction and text refused, naming 4096 where it applies; 4096 taken |
| `test_capture.py`: `ViewportAtSize` | On a fake viewport: `fill_frame` off, scale 1 and the size set on entry; scale, full resolution and `fill_frame` put back in that order on exit, after an exception in the block too; nothing set when already at the size; a setter that fails on exit doesn't keep the others, and is returned; a scale of 0.5 comes back with the full resolution; `resized()` true only inside |
| `test_capture.py`: `capture_sized` | Two captures of the old size, then one of the new: the third is returned after two frames; always the old size: a `CaptureError` naming both sizes after `FRAME_SECONDS` on a fake clock; a spent budget: `OutOfTimeError` |
| `test_framing.py` | `inspect_args` without a size gives None (its 800x600 default goes), and refuses 5000 |
| `test_tools_camera.py` | `capture_viewport`'s text gives the PNG's size, not the answer's; a mismatch adds the `WARNING` with the install command; an unreadable header keeps the answer's size; `inspect_prim` prints its size |
| `test_contract.py` | Unchanged and passing: no tool's name, schema or annotations moved |

**Live, `tests/test_integration.py`** (Isaac Sim 6.2 headless, `OMNIVERSE_MCP_SIM=1`), each a test that would have
caught #51:

| Test | What it shows |
|---|---|
| `test_12b_capture_is_the_size_asked_for` (new) | At 320x240, 640x360 and 360x640, on `/World/IntTestCube` from `test_12`: the image's and the segmentation's PNG headers and the answer all give the size, and the cube's box matches its pixels in the segmentation (decoded in Kit, as `_red_and_blue` does) within 2 px a side. Fails on `main` (E2) |
| `test_12c_capture_from_a_camera_path_boxes_that_camera` (new) | A camera prim aimed at the cube from another side: with `camera_path`, the box matches the cube's pixels within 2 px; the viewport's camera is the one from before. Fails on `main` (E5) |
| `test_12d_a_capture_puts_the_viewport_back` (new) | The viewport's full resolution, scale, `fill_frame` and camera are the same after a capture at 320x240 with `camera_path`; after one that fails (Kit's capture wrapped to finish empty, `_FINISHED_CAPTURE`); and with `fill_frame` on, where the image is still 320x240 and `fill_frame` comes back on |
| `test_12e_an_oversized_capture_is_refused` (new) | `capture_viewport(4097, 240)` and `inspect_prim(width=5000)` answer errors naming 4096; the viewport's size is unchanged |
| `test_13b_inspect_is_the_size_asked_for` (new) | `inspect_prim(width=320, height=240, include_segmentation=True)`: each image and segmentation 320x240; the viewport back at its size. Fails on `main` (E10) |
| `test_10`, `test_13` to `test_15f` | Pass as they are; `test_15b` now renders its 160x120, and `test_15f`'s viewport with updates off still fails fast and comes back at its size |
| `tests/test_scenarios.py` `test_03_01_viewport_capture` | Also checks the PNG is the 640x480 it asks for |

Both live suites run whole before the PR. `tearDownClass` deletes the new camera prim.

**What neither shows:** the GUI, where "Viewport"-size mode, Fill Viewport, a window resized during a capture and Kit
107's resolution menu act (Q5, R1, R2); Kit 107 (Isaac Sim 5.x) live, since 5.1 doesn't start on this machine; USD
Composer; a GPU that can't allocate a 4096-a-side render.

## Docs

- `docs/TOOLS.md`: `capture_viewport` and `inspect_prim`, the `width` and `height` rows (rendered at that size, at
  most 4096, the viewport back after), the boxes in the image's pixels from the camera captured; the hints table's
  read-only row says a capture sets the viewport's camera and size for its frame and puts them back.
- `docs/ARCHITECTURE.md`: Viewport Capture: how the bridge holds the viewport at a size (what it sets and puts back,
  in which order), the PNG check, recording's skip; the `/sim/capture` answer's `width` and `height`.
- `README.md`: the #51 line leaves Known issues.
- `CHANGELOG.md`, Unreleased, Fixed: "`capture_viewport` and `inspect_prim` render at the `width` and `height` asked
  for, 640x480 by default, so the image, its segmentation and its boxes agree; with a `camera_path`, the boxes are
  that camera's (#51)", and that the extension must be installed again.
- `AGENTS.md`, Traps: a row, "A capture came at the viewport's size while its boxes used the size asked for | #51 |
  The viewport renders at the size for the call and comes back (`ovmcp.core.capture`), and the PNG's own size is
  checked" (149 to 150 lines, the gate's limit).
- `plugin/skills/scene/SKILL.md`: none; its "some 400 tokens at the default 640x480" becomes true.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | In the GUI, the widget's own "Viewport"-size or Fill Viewport resizes the viewport if the window's size changes during a capture (A6) | Accepted: `capture_sized` sees the PNG's size and captures again, then fails naming both sizes, never boxes for another size; Q5's GUI run checks the modes |
| R2 | Kit 107's resolution menu writes the asked size to the persistent per-viewport resolution when it matches a preset, and the restored size after (A7); a crash in between keeps the asked size for the next start | Accepted: Kit 110's menu doesn't; Movie Capture has the same exposure; the user resets it in the menu |
| R3 | A crash or an error mid-call leaves the viewport at the asked size | Resolved: the restore runs on exit, an exception included (`test_12d`); a resolution and `fill_frame` set through the API are not saved, so a restart resets them on Kit 110 |
| R4 | The boxes come from `omni.syntheticdata`'s pinhole fitted to the horizontal aperture (A8); measured right at 16:9 and 4:3 (E2, E4), not yet portrait or another aperture conform setting | Open: `test_12b` includes 360x640. If portrait disagrees, that case goes to an issue of its own and the test keeps landscape sizes, said in the review record |
| R5 | A capture during a recording leaves a gap in it while it holds the viewport (some 0.2 s; `inspect_prim`'s whole orbit) | Accepted: a gap `sim_time` shows beats frames of another size; #25's render product removes it |
| R6 | A large size costs memory and time: 3840x2160 took 0.8 s (E8), and `inspect_prim` at 4096 a side for 14 angles answers with hundreds of megabytes | Accepted, capped at 4096 a side (Q2) |
| R7 | A GPU that can't allocate the asked size: what Kit does then is unknown | Accepted: `capture_sized` fails rather than return another size, and the viewport is put back |

## Plan review

None yet: `review-plan` writes each round here.
