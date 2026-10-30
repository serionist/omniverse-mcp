---
title: Render capture_viewport and inspect_prim at the size asked for
issue: "#51"
status: draft
approved_by:
approved_at:
---

# Render capture_viewport and inspect_prim at the size asked for

## Goal

A capture's image, its instance segmentation and its screen boxes are one frame, from one camera, at one size: the
size the call asked for, which the answer reports. Today the image and the segmentation come at the viewport's size
while the boxes are scaled to the size asked for, so an assistant that places things by the boxes is off by the ratio
of the two (E2).

True when this is done:

| | What | Shown by |
|---|---|---|
| 1 | `capture_viewport(w, h)` returns an image and a segmentation of w by h pixels, boxes in those pixels, and `w`x`h` in its text | `test_12b` (fails on `main`, E2) |
| 2 | `inspect_prim(width=w, height=h)` returns each angle, and its segmentation, at w by h, framed for that size | `test_13b` (fails on `main`, E10) |
| 3 | `capture_viewport(camera_path=...)`'s boxes are that camera's, not the viewport's own camera's (Q3) | `test_12c` (fails on `main`, E5) |
| 4 | A call leaves the viewport's camera, size and render settings as they were, and nothing of its own in the stage or in omni.syntheticdata | `test_12d`, unit tests |
| 5 | A side above 4096 or a frame above 3840x2160 is refused before anything is made | unit tests, `test_12e` |
| 6 | A server talking to an older extension, whose boxes and image differ in size, says so and how to update | unit test |

Why it matters: the boxes file is how an assistant finds things in a capture without opening the image (the plugin's
`scene` skill says to read it first). With the default 640x480 against Isaac Sim's 1280x720 viewport, every box is
half the size and in the wrong place.

- **In scope:** the capture path of `capture_viewport` and `inspect_prim` in the bridge (`handlers/camera.py`,
  `handlers/_utils.py`), #25's camera feed (`handlers/camera_feed.py`) as these two use it, Kit-free logic in
  `ovmcp/core/`, the two tools' text and parameter descriptions, the docs, unit and live tests.
- **Out of scope:** `start_recording` (#25, which this change follows); Replicator; fisheye cameras and a non-default
  aperture conform setting; the bridge's protocol number; the extension's version.

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
`omni.kit.viewport.menubar.settings` 110.0.2, `omni.syntheticdata` 0.6.17, `omni.replicator.core` 1.13.38) and Isaac
Sim 5.1 (`D:\isaacsim5.1`, Kit 107: `omni.kit.widget.viewport` 107.1.3, `omni.kit.capture.viewport` 1.7.5,
`omni.kit.viewport.menubar.settings` 107.0.3, `omni.syntheticdata` 0.6.13), and in NVIDIA's docs through Context7.
#25's plan (`docs/plans/2026-10-30-recording-camera.md` on its branch, `39c1e8b`) holds the camera feed's facts: its
F1-F5 and E1-E15 are cited as #25's.

| # | Fact | Source |
|---|---|---|
| A1 | `ViewportAPI.resolution = (w, h)` takes the full resolution; the texture renders at it times `resolution_scale`. The same on Kit 107 and 110 | `omni/kit/widget/viewport/api.py` lines 281-306, `impl/texture.py` lines 107-139 (110.0.1); 107.1.3 the same |
| A2 | After a resize, "An async renderer may still deliver frames from before this request" | `impl/texture.py` line 133 (110.0.1) |
| A3 | With the API's `fill_frame` on, every sync of the viewport sets the resolution back to the window's size | `api.py` `_sync_viewport_api`, lines 524-531 |
| A4 | The viewport window starts at `/app/renderer/resolution`, 1280x720 in Isaac Sim, or the window's size when either is 0 or less; Isaac Sim sets `defaults.fillViewport = false` | `omni/kit/viewport/window/layers.py` lines 116-146; `isaacsim.exp.base.kit` lines 229-239 (6.2), line 245 (5.1) |
| A5 | Kit's own Movie Capture renders at a size of its choosing by resizing the viewport and putting it back after | `omni.kit.capture.viewport` `extension.py` lines 608-650, 910-935, 1030-1045 (2.11.1); lines 540 and 916 (1.7.5) |
| A6 | The widget's own "Viewport"-size and Fill Viewport options resize the viewport when the window's size changes or the option is set; in a GUI the settings menu turns the API's `fill_frame` off and drives the widget's options instead | `omni/kit/widget/viewport/widget.py` lines 570-640 (110.0.1); `settings_renderer_menu_item.py` lines 72-85 (107.0.3) |
| A7 | Kit 107's resolution menu follows a delivered resolution by selecting the matching preset with `current_index.set_value`, whose handler writes the per-viewport persistent resolution and calls the widget's `set_resolution`, which takes the widget out of "Viewport"-size mode. Kit 110's follows it "without applying it back to the viewport or persistent settings" | 107.0.3: `settings_renderer_menu_item.py` lines 361-375, `resolution_collection/model.py` lines 109-115; 107.1.3 `widget.py` lines 575-581; 110.0.2 `model.py` lines 176-177 |
| A8 | Kit 110's render-scale menu follows a delivered scale the same way as Kit 107's resolution menu: `__sync_model` selects the matching item, which writes `/persistent/app/viewport/<id>/resolutionScale` | 110.0.2 `settings_renderer_menu_item.py` lines 115-140 and 361-375 |
| A9 | omni.syntheticdata reads three attributes of what it is given as a viewport: `get_view_params` and `world_to_image` its `camera_path` and `resolution`; `enable_sensors`, `disable_sensors` and `get_sensor_array` its `render_product_path` | `omni/syntheticdata/scripts/helpers.py` lines 474-530 and 551-569; `sensors.py` lines 116-205 (0.6.17) |
| A10 | Enabling a sensor on a render product makes a graph of omni.syntheticdata's under it (`<render product>/PostRender/SDGPipeline`), kept in its registry `SyntheticData._nodeGraphs`. Replicator's own render product teardown pops each graph under the render product from that registry and resets it (`_reset_node_graph`), then deletes the prim from every layer. omni.syntheticdata resets its registry at every stage CLOSING and OPENED | `omni.replicator.core` `scripts/utils/viewport_manager.py` lines 123-165; `omni.syntheticdata` `scripts/SyntheticData.py` lines 1336-1350 and 1582-1606, `scripts/extension.py` lines 97-107; E16 |
| A11 | #25's camera feed: `create_hydra_texture(name, w, h, "", camera, "rtx", is_async=False)` renders a camera at a size into a texture of its own, read as the viewport reads its own; Kit writes its render product into the root layer whatever the edit target; first frame 0.17 s after creation; frames on Kit's main thread | #25's F1-F5, E1, E4, E12 |
| A12 | The viewport's settings, Render Resolution, Render Scale and Fill Viewport; Movie Capture's width and height "of the rendered image"; Replicator's `render_product(camera, resolution)` | Context7, Omniverse extensions docs: `ext_viewport/controls/settings`, `ext_movie-capture`, `ext_replicator` |

### What Kit did, measured

Three runs on Isaac Sim 6.2.0 headless at port 8212, 2026-10-30, all against `main`'s bridge (`765d51c`), with a lit
1 m cube: run 1 by the planning session (`e51_size.py`, `e51_more.py`, `e51_scale.py`), runs 2 and 3 by the main
session on a fresh Kit each (`e51_compare.py`, `e51_teardown.py`, the planning session's scripts, with a red cube and
`/World/E51/Cam` aimed at it). MAD is the mean absolute difference of two images' RGB, 0 to 255.

| # | Measured |
|---|---|
| E1 | The headless viewport renders at 1280x720, render scale 1, `fill_frame` off; its window is 1440x896 |
| E2 | On `main`, `capture_viewport(320, 240)`: image 1280x720, segmentation 1280x720, the answer says 320x240, the cube's box `[84.3, 32.5, 247.8, 240.0]` while its pixels span `[337, 98, 991, 720]`. At `(1280, 720)` the box `[337.3, 97.5, 991.0, 720.0]` matches its pixels `[337, 98, 991, 720]`: the boxes are right when the two sizes are equal |
| E3 | `viewport.resolution = (640, 480)`: `resolution` and `get_view_params` give it at once; the segmentation sensor delivers 480x640 on the next frame (0.08 s), with no re-enable; so does 1920x1080, and back to 1280x720 each time. The first capture after a set, with no frame waited for, is at the new size (320x240, then 1280x720 back) |
| E4 | With the viewport at the size, `main`'s own `handle_capture` gives image, segmentation and boxes that agree: 640x480 box `[168.6, 108.8, 495.5, 432.1]`, pixels `[169, 109, 495, 432]`; 640x360 and 320x240 the same within a pixel |
| E5 | `capture_viewport(camera_path=<a camera beside the cube>)`: its segmentation shows the cube at `[301, 21, 979, 699]`, its box is `[406.8, 126.8, 873.2, 593.2]`, the viewport's own camera's. With that camera made the viewport's own, the box is `[300.6, 20.6, 979.4, 699.4]` |
| E6 | With `fill_frame` on, the viewport goes to the window's 1440x896, and a resize to 640x480 is undone within 3 frames. With it off, a resize holds through a camera move |
| E7 | Render scale 0.5 halves a viewport capture (640x480 asked, 320x240 written). `frame_info["resolution"]` still said 1280x720 a frame after a resize |
| E8 | 3840x2160 through the viewport: the capture 0.66 s; `handle_capture` 0.8 s with segmentation and boxes |
| E9 | A Replicator render product at 640x480 with an `rgb` annotator, timeline stopped: 0.49 s cold, 0.22 s warm, for its creation and three `step_async` |
| E10 | On `main`, `inspect_prim(width=320, height=240)` and `(640, 480)` both return 1280x720 images, at the same fitted distance (2.8763 m) |
| E11 | (a) the viewport resized and (b) a feed of `/World/E51/Cam`, each at 320x240 and 640x480: image and segmentation at the size, the same box from both (`[222.8, 147.0, 414.0, 347.4]` at 640x480); box against the cube's segmentation pixels 0.4 px (0.7 at 320x240), its red pixels in the image against its segmentation 1 px. omni.syntheticdata segments the feed's render product, given the feed as its viewport (A9) |
| E12 | Cost to image, segmentation and boxes at 640x480: (b) 0.19 s: creation under 0.01 s, first frame 0.094 s, image 0.125 s, segmentation 0.047 s (2 updates); a second capture from the same feed 0.031 s. (a) 0.11 s: image 0.11 s, segmentation at once. At 320x240 within 0.02 s of those |
| E13 | After a save, the root layer is clean and the stage has no unsaved edits. Each of these makes both true again: (b) a feed made (its render product a `def` in the root layer, an `over` in the session layer), still after its render product is deleted from every layer; (a) a resize, which writes the viewport render product's `resolution` into the root layer (`(640, 480)`, then `(1280, 720)` back); and `main`'s `camera_path` switch. A new stage starts with both true |
| E14 | The first capture against a settled one at 640x480, by app updates waited. RT 2.0 (noise floor 0.05-0.08): after a resize 0.23 at 0, 0.09 at 100; a new feed's first capture against its own 100 updates later 0.21-0.24, and 0.07 from 100 to 130; the viewport after a camera move, as `main` captures: 7.1 at 0 and 1 (the previous view), 0.29 at 3, 0.08 at 100; a feed kept alive after a camera move: 10.7 at 0 and 1, 0.45 at 3, 0.09 at 100. Path Tracing, with Isaac Sim's 64 samples a frame and 64 in all: 0.0 from the first capture after a resize or of a new feed; 7.0 at 0 and 1 after a camera move, 0.0 from 3 |
| E15 | A feed's image is not the viewport's to the pixel: a settled feed against the settled viewport, same camera, size and mode, MAD 2.0 in RT 2.0 and 1.95 in Path Tracing; two feeds made one after the other, first frames 0.09 apart (RT 2.0) and 0.0 (PT) |
| E16 | A segmented feed torn down as #25's feed does (drop the texture, delete the render product from every layer) leaves its graph `<render product>/PostRender/SDGPipeline` in omni.syntheticdata's registry, and Kit then logs `ValueError: Invalid object in Py_Graph in getWrappedGraphFromNode` 380 times in the 2 s after, 400 more around a save, until a new stage resets the registry (2 more). Torn down as Replicator does (A10), the graph leaves the registry, and nothing is logged at the teardown, the save or the new stage. The viewport's own segmentation worked on the next stage after either |
| E17 | Setting `/rtx/rendermode` to `RaytracedLighting` (RTX Real-Time 1.0) didn't take on 6.2: it stayed `RealTimePathTracing`, Isaac Sim 6.2's default, so Real-Time 1.0 is unmeasured |
| E18 | At 320x240, by either way, Kit warns "DLSS increasing input dimensions: Render resolution of (160, 120) is below minimal input resolution of 300" |

### Q1: three ways to make the boxes and the image agree

| | (a) Resize the viewport for the call | (b) A camera feed for the call, #25's | (c) Report the viewport's size |
|---|---|---|---|
| The size asked for | Yes | Yes | No: `width` and `height` do nothing |
| Image, segmentation and boxes agree | Within a pixel (E4, E11) | Within a pixel, the same boxes as (a) (E11) | Yes, at the viewport's size |
| Time to image, segmentation and boxes, 640x480 | 0.11 s (E12) | 0.19 s; 0.03 s for each further capture of the call (E12) | As today |
| Settling after the frame is made | None needed: RT 2.0 0.23 from settled, Path Tracing converged (E14) | The same (E14) | As today |
| `camera_path` | The viewport's camera switched as today; a capture an update after a camera change shows the previous view (E14), and the switch waits two | The feed renders the camera from its first frame; the viewport's camera never moves | As today |
| The user's viewport, in the GUI | Shows the asked size for the call. Kit 107: a preset size goes to the persistent resolution and takes "Viewport"-size mode off (A7). Kit 110: a render scale other than 1 goes to the persistent setting (A8) unless avoided | Untouched | Untouched |
| The stage | Root layer dirty, unsaved edits (E13), as `main`'s `camera_path` already leaves it | The same (E13); its render product is in the stage for the call (A11) | As today |
| What it relies on | `ViewportAPI`'s public properties | #25's camera feed; omni.syntheticdata's registry for the teardown (`_nodeGraphs`, `_reset_node_graph`), private, as Replicator's own teardown uses it (A10); without it Kit logs hundreds of errors a second until the next stage (E16) | Nothing new |
| Render cost | None extra; 640x480 renders a third of 1280x720's pixels | A second render for the call's length (#25's E7: within noise at 640x480 headless) | None |
| What the assistant sees | The viewport's own render | Another view's render, 2/255 from the viewport's on average (E15) | The viewport's own render |
| Recording | No interplay once #25 lands: its frames come from a feed of its own | None | None |
| Merge order | Any | After #25, whose feed it reuses | Any |
| Tool contract | No change | No change | Removing the parameters is Breaking (a one-way door); keeping them means two documented no-ops |

**Recommendation: (b).** It meets the issue as (a) does, at 0.08 s more a call, leaves the user's viewport and its
menus alone on both Kit versions, fixes `camera_path`'s stale first frame on the way, and is the direction the
maintainer took for #25 (its Q6 in `2026-10-29-debug-draw-and-ignored-parameters.md`: #51 "can reuse PR 3's render
product"); #25 rejects resizing the viewport for the same GUI reasons. Its cost is one private call into
omni.syntheticdata, which NVIDIA's Replicator makes for the same teardown and which E16 shows is needed and enough. (a)
is the fallback if #25 doesn't land first or the maintainer won't depend on that call; (c) gives up the parameters.

### The design, for (b)

**What it builds on, from #25:** `handlers/camera_feed.py`'s `CameraFeed(name, camera_path, width, height)` with
`schedule`, `withdraw`, `first_frame(seconds)`, `drop()` and `remove_render_product(stage)`, and `_utils.py`'s
`capture_file_png` with `capture_feed_png(feed, budget)` on it. This change merges after #25 (Q6).

**Kit-free, `ovmcp/core/`:**

- `png.png_size(data) -> tuple[int, int] | None`: the width and height in a PNG's header; None for anything else.
- **One size limit for every frame the bridge renders (Q2):** #25's `MAX_SIDE = 4096` and `MAX_PIXELS = 3840 * 2160`
  move from `core/recording.py` to `core/capture.py`, with `frame_size_error(width, height) -> str | None`, which
  `recording_args` and the new `capture_size` both call.
- `capture.capture_size(body) -> tuple[int, int] | None`: the `width` and `height` of a request, whole numbers, not
  booleans, within `frame_size_error`; both or neither; None when neither is given. The `ValueError` says which and
  why. `framing.inspect_args` takes its size from it, so its 800x600 default goes.
- `capture.settle_frames(render_mode, spp, total_spp) -> int`: the feed's frames to wait after its first before a
  capture. Path Tracing accumulates `spp` samples a frame up to `total_spp`, so it waits until the total is reached
  (`ceil(total_spp / spp) - 1`, at most 255): 0 with Isaac Sim's 64 and 64 (E14). Other modes 0: RT 2.0's first
  capture is 0.21-0.24 from settled, against a noise floor of 0.07 (E14), which no reader of a 640x480 image sees.

**Kit, `handlers/camera_feed.py` (additions to #25's feed):**

- The three attributes omni.syntheticdata reads (A9): `render_product_path`, `camera_path` (an `Sdf.Path`) and
  `resolution`, plus `usd_context`, which `_segmentation`'s key reads. A feed then goes wherever a viewport went in
  `get_view_params`, `world_to_image`, `enable_sensors` and `get_instance_segmentation`.
- `frames(count, budget)`: waits for `count` of the feed's frames, each bounded as `_viewport_frames` bounds the
  viewport's (`capture.frames` on the drawable-changed event), for the settle after a camera move and for the black
  retry.
- **Segmentation's teardown,** in `drop()` before the texture goes, when segmentation was enabled on it: the sensor
  disabled, then each graph under the feed's render product popped from `SyntheticData.Get()._nodeGraphs` and reset
  with `_reset_node_graph`, as Replicator's `viewport_manager.destroy` does (A10). Without the registry (an
  omni.syntheticdata that renamed it), a warning once, and the teardown goes on. Then #25's
  `remove_render_product`.

**Kit, `handlers/camera.py`:**

- **`handle_capture`:** the size is checked first, and a refusal makes nothing. A body without a size takes the
  viewport's resolution. The camera is `camera_path`, or the active viewport's when empty, checked with #25's
  `camera_error`. Then, in a `try` whose `finally` drops the feed (with its teardown above): a feed of that camera at
  that size, its first frame (10 s, as #25's start), `settle_frames` more, then the image (`capture_feed_png` within
  the call's budget, its black retry resetting the renderer and waiting on the feed's frames), the boxes and the
  segmentation, all from the feed. The viewport is not touched, so `_capture_frame`'s camera switch goes.
- **The boxes:** `_compute_screen_bboxes(feed, w, h)`, projected with `get_view_params(feed)` at the feed's own size,
  so `screen_box` scales by 1, from the camera captured (Q3).
- **`_segmentation(feed, budget)`:** as now, given the feed; it waits for data of the feed's size. Its waits are kept
  per (stage, render product) as now, so within an `inspect_prim` call the second angle doesn't wait again; each
  call's feed has a name of its own, so a new call waits afresh.
- **`handle_camera_inspect`:** one feed for the call, of the camera the viewport looks through, which the orbit moves
  as now (the user still sees it move). It is made before `isolate` hides anything and dropped after its restore. The
  fitted distance uses the size asked for, so `_viewport_resolution` goes. Each angle's settle is
  `CAMERA_SETTLE_FRAMES` of the feed's frames: a camera move needs 3 (E14), and 20 keeps today's margin.
  Segmentation is enabled on the feed only when `include_segmentation` asks for it.
- **The answers** report the PNG's size as `width` and `height`; `inspect_prim`'s answer gains them.
- The viewport's sensor, enabled at startup (`extension.py` `_init_sensors`), stays: nothing in this change reads it,
  and removing it is a change of its own.

**Server, `tools/camera.py`:**

- The `Viewport:` line and the boxes file's header give the image's own size, read from its PNG header; an image
  whose header can't be read keeps the answer's size, and an answer without one (an older extension's
  `inspect_prim`) prints none. When the answer's size differs from the image's, the extension is older than this fix,
  and the tool adds `WARNING: The image is 1280x720 but its boxes are for 640x480: the Kit extension is older than
  this server. Install this server's, <install_command()>, then restart Kit.`
- `inspect_prim`'s first line gives the size captured, when the answer has it.
- `Width` and `Height` say what they do now: "Image width in pixels, up to 4096 (3840x2160 in all), rendered at that
  size from the camera". The docstrings say so too. Descriptions are prose, which the contract file leaves out
  (`tools/golden.py`, `PROSE`).

**The `mcp.capture_viewport(width=1280)` example** (`tools/misc.py` line 32, `handlers/_mcp_bridge.py` line 9,
`docs/TOOLS.md` line 849, `docs/ARCHITECTURE.md` line 297) would now give 1280x480: it becomes
`mcp.capture_viewport(width=1280, height=720)`.

### If Q1 is (a)

`ViewportAtSize(viewport, size)` in `core/capture.py`, a context manager that records `fill_frame`,
`resolution_scale` and `full_resolution`, turns `fill_frame` off (E6), and sets the full resolution so that it times
the user's scale gives the size, rather than setting the scale to 1, so Kit 110's scale menu writes nothing (A8); a
size that scale can't reach (a scale above 1 and an odd side) sets the scale too. On exit it puts the full resolution,
then the scale, then `fill_frame` back. The handlers hold it over image, boxes and segmentation, with the camera
switched for the whole of it and 3 updates after the switch (E14). A capture whose PNG is the wrong size is taken
again up to 3 frames later, then fails with both sizes named, and that failure stops an `inspect_prim` call as
`NoFrameError` does. A7's Kit 107 menu writes stay (R-a below). No recording change: after #25 its frames don't come
from the viewport.

### Alternatives

| Alternative | Why not |
|---|---|
| (a) and (c) | Q1 above |
| A Replicator render product with annotators | Replicator's capture settings and play-every-frame on the user's session, a step cancelled at its bound freezes the timeline, no frame while stopped without a step (#25's F6); and no Replicator in some Kit apps |
| A feed kept alive between calls, per camera and size | Its render product stays in the stage, saved with the user's scene, and renders every frame until dropped; a call's feed costs 0.19 s (E12) |
| Leave the render product's graphs to omni.syntheticdata's next reset | Hundreds of errors a second in Kit's log until the next stage (E16) |
| Resize the PNG after the capture | Distorts the aspect, or letterboxes it; upscaling blurs; the segmentation needs its own nearest-neighbour resize |
| A second viewport window (`create_viewport_window`) | A window opens in the GUI; a hidden one may stop rendering (#25's candidates) |
| `capture_viewport_to_file(render_product_path=...)` with a product of the size | The viewport shows the other product for the frame, as visible as a resize, and its sensor and `get_view_params` still describe the viewport's own |

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Which way: (a) resize the viewport for the call, (b) a camera feed for the call, #25's, or (c) report the viewport's size and give up `width` and `height`? | (b): the comparison above. (a) if #25 doesn't land first or the private omni.syntheticdata call is unwanted | |
| Q2 | The size limit: one for every frame the bridge renders, #25's 4096 a side and 3840x2160 in all, refused by the extension, the schema unchanged? | Yes: a schema `maximum` is a contract change (Breaking in 0.x) for no gain, and one limit in one place | |
| Q3 | Fix `camera_path`'s boxes (E5) in this change? | Yes, under an issue of its own that this PR closes too: the same disagreement between boxes and image, and (b) fixes it by construction | |
| Q4 | Only if Q1 is (a): in the GUI, the user's viewport shows the size asked for while a capture runs, and on Kit 107 a preset size reaches the persistent resolution (A7). Acceptable? | Yes for (a), as Movie Capture does it; moot for (b) | |
| Q5 | The GUI can't be tested here (port 8211 is yours). Run `test_12b` to `test_13b` once on the GUI Isaac Sim before merging? | Yes, by you, the PR saying what it showed. For (b) it shows the viewport and its menus untouched; for (a), "Viewport" size and Fill Viewport | |
| Q6 | Merge after #25? | Yes, (b) needs its camera feed; this plan's branch is rebased on `main` once #25 is in, before any code | |
| Q7 | `capture_viewport` stays `readOnlyHint: true`, though for its length it makes a render product in the stage and leaves Kit's unsaved-edits flag set (E13)? | Yes: the stage holds nothing more after the call, `main`'s `camera_path` already sets the flag, and the hint is a one-way door; TOOLS.md says what a capture leaves | |
| Q8 | Merge without a live run on Kit 107 (Isaac Sim 5.x), which doesn't start on this machine? | Yes, as #25 and the PRs before it: #25's feed handles Kit 107's event form, and the unit tests run both | |

## Compatibility

- **One-way doors:** none. Tool names, schemas and annotations stay as `tests/fixtures/mcp-tools.json` holds them:
  `width` and `height` keep their type, default and `minimum`, and only their descriptions change, which the file
  leaves out; `capture_viewport` stays read-only (Q7). The wire paths, the auth header, the output folder and the
  protocol number are unchanged.
- **What users notice:**
  - Captures come at the size asked for: 640x480 by default, where they came at the viewport's 1280x720 (Isaac Sim's
    default) or the window's size. Boxes, segmentation and image agree. Framing at 4:3 by default shows a little less
    to the sides than 16:9 did.
  - `inspect_prim`'s fitted distance follows the size asked for, so it changes with the aspect.
  - A side above 4096 or a frame above 3840x2160 is an error; `inspect_prim` at 20 pixels or fewer a side was refused
    already (`fit_distance`), now judged on the size asked for.
  - A capture's image is rendered by a view of its own: 2/255 from the viewport's on average (E15), not pixel for
    pixel what the user's viewport shows.
  - A capture with `camera_path` no longer switches the user's viewport to that camera for its length.
- **The bridge's answers:** `/sim/capture`'s `width` and `height` are the image's real size (they were the size asked
  for); `/camera/inspect` gains them. A body without `width` and `height` captures at the viewport's resolution; the
  bridge's 1280x720 and 800x600 defaults go. Only direct HTTP callers can omit them: the server and
  `execute_script`'s `mcp.*` always send them.
- **Versions:** an older extension with this server works, and the tool warns that its boxes don't match (Design);
  this extension with an older server works, its answers keeping their fields. Users update the extension as each
  release says. Kit 107 and 110 through #25's feed; only Isaac Sim 6.2 runs live here (Q8).

## Steps

| # | Step | Test that proves it |
|---|---|---|
| 0 | The live runs E1-E18, before any code: done, and the Design follows them (the teardown from E16, the settle from E14) | What Kit did, measured |
| 1 | This plan, the branch's first commit; once #25 is on `main`, the branch rebased on it (Q6) | `review-plan`, then the maintainer |
| 2 | Kit-free core: `png.png_size`; the size limit moved to `core/capture.py` with `frame_size_error`, `recording_args` on it; `capture_size`; `settle_frames`; `inspect_args` through `capture_size` | `tests/test_png.py`, `tests/test_capture.py`, `tests/test_framing.py`, #25's `tests/test_recording.py` unchanged and passing; `uv run tools/gate.py quick` |
| 3 | The feed's additions: the view attributes, `frames`, the segmentation teardown | `tests/test_camera_feed.py` |
| 4 | The handlers: `handle_capture` and `handle_camera_inspect` on a feed; `_segmentation` and `_compute_screen_bboxes` given one; `_viewport_resolution` and the camera switch gone; the answers' size; the `mcp.capture_viewport` example | live: `test_12b` to `test_12e`, `test_13b`, `test_17_06`, then both live suites whole on Isaac Sim 6.2 headless |
| 5 | The server: the image's own size in the text, the warning for an older extension, `inspect_prim`'s size, the parameter descriptions, the example in `tools/misc.py` | `tests/test_tools_camera.py`; `tests/test_contract.py` passing unchanged shows no schema moved |
| 6 | The docs (Docs) | `uv run tools/gate.py full` |

## Tests

**Unit (CI):**

| Test | What it holds |
|---|---|
| `test_png.py`: `png_size` | An `encode_png` image's size; None for `b""`, a short header, and something that isn't a PNG |
| `test_capture.py`: `frame_size_error`, `capture_size` | None without a size; both given; one alone, 0, a negative, 4097 a side, 3840x2161, a bool, a fraction and text refused, naming the limit; 4096x2160 and 3840x2160 taken |
| `test_capture.py`: `settle_frames` | Path Tracing at 64 and 64: 0; at 1 and 64: 63; at 4 and 10: 2; a total of 0 or a huge one: at most 255; Real-Time modes and an unknown mode: 0 |
| `test_camera_feed.py` (#25's, extended) | Against its fake Kit: the feed carries `render_product_path`, `camera_path` and `resolution`; `frames(3)` returns after three drawable events and raises `NoFrameError` when none comes; `drop()` of a segmented feed disables the sensor, pops and resets each registry graph under its render product, and only those, before the texture goes; a registry without `_nodeGraphs` warns once and the drop still completes |
| `test_framing.py` | `inspect_args` without a size gives None (its 800x600 default goes), and refuses 5000 |
| `test_tools_camera.py` | `capture_viewport`'s text gives the PNG's size, not the answer's; a mismatch adds the `WARNING` with the install command; an unreadable header keeps the answer's size; `inspect_prim` prints its size, and an answer without `width` and `height` (an older extension) prints the line without one |
| `test_contract.py` | Unchanged and passing: no tool's name, schema or annotations moved |

**Live, `tests/test_integration.py`** (Isaac Sim 6.2 headless, `OMNIVERSE_MCP_SIM=1`), each a test that would have
caught #51:

| Test | What it shows |
|---|---|
| `test_12b_capture_is_the_size_asked_for` (new) | At 320x240, 640x360 and 360x640, on `/World/IntTestCube` from `test_12`: the image's and the segmentation's PNG headers and the answer all give the size, and the cube's box matches its pixels in the segmentation (decoded in Kit, as `_red_and_blue` does) within 2 px a side. Fails on `main` (E2) |
| `test_12c_capture_from_a_camera_path_boxes_that_camera` (new) | A camera prim aimed at the cube from another side: with `camera_path`, the box matches the cube's pixels within 2 px. Fails on `main` (E5) |
| `test_12d_a_capture_leaves_nothing` (new) | Around a capture at 320x240 with `camera_path`, and around one that fails (Kit's capture wrapped to finish empty, `_FINISHED_CAPTURE`): the viewport's camera, resolution, scale and `fill_frame` as before; nothing new under `/Render` in any layer; no graph of the capture's left in omni.syntheticdata's registry; no `Invalid object in Py_Graph` in Kit's log (`get_logs(search="Py_Graph")`) |
| `test_12e_an_oversized_capture_is_refused` (new) | `capture_viewport(4097, 240)`, `capture_viewport(3840, 2161)` and `inspect_prim(width=5000)` answer errors naming the limit; nothing new under `/Render` |
| `test_13b_inspect_is_the_size_asked_for` (new) | `inspect_prim(width=320, height=240, include_segmentation=True)`: each image and segmentation 320x240; nothing left under `/Render` or in the registry. Fails on `main` (E10) |
| `test_10`, `test_13` to `test_15f` | `test_10` to `test_15d` pass as they are: `test_15b` now renders its 160x120; `test_15c` and `test_15d` wrap `get_instance_segmentation`, which the feed's reads go through. `test_15e` wraps the viewport's `capture_viewport_to_file`, which these tools no longer call: it gives the same empty result through what `capture_feed_png` schedules. `test_15f` turns the viewport's updates off so no frame comes; the captures no longer read the viewport, so it makes the feed's textures with updates off instead (wrapping `create_hydra_texture` in Kit) and asserts as before |
| `tests/test_scenarios.py` `test_03_01_viewport_capture` | Also checks the PNG is the 640x480 it asks for |
| `tests/test_scenarios.py` `test_17_06_segmentation_after_captures_and_a_new_stage` (new) | Two captures with segmentation, `new_scene`, a third: its segmentation is there, and Kit's log has no `Py_Graph` error (E16) |

Both live suites run whole before the PR. `tearDownClass` deletes the new camera prim.

**What neither shows:** the GUI, where the viewport and its menus must stay as they were (Q5); Kit 107 (Isaac Sim
5.x) live (Q8); USD Composer; a GPU that can't allocate a 4096-a-side render.

## Docs

- `docs/TOOLS.md`: `capture_viewport` and `inspect_prim`, the `width` and `height` rows (rendered at that size, up to
  4096 a side and 3840x2160 in all), the boxes in the image's pixels from the camera captured, a render of its own;
  the hints table's read-only row says a capture leaves Kit's unsaved-edits flag set (Q7); the `mcp.capture_viewport`
  example.
- `docs/ARCHITECTURE.md`: Viewport Capture: a feed per call, segmentation and boxes from it, the teardown and why
  (E16); the `/sim/capture` answer's `width` and `height`; the example.
- `README.md`: the #51 line leaves Known issues.
- `CHANGELOG.md`, Unreleased, Fixed: "`capture_viewport` and `inspect_prim` render at the `width` and `height` asked
  for, 640x480 by default, so the image, its segmentation and its boxes agree; with a `camera_path`, the boxes are
  that camera's, and the viewport no longer switches to it (#51)", and that the extension must be installed again.
- `AGENTS.md`, Traps: a row, "A capture came at the viewport's size while its boxes used the size asked for | #51 |
  A feed of the camera at the size for each call; its segmentation graphs reset before its render product goes"
  (149 to 150 lines, the gate's limit).
- `plugin/skills/scene/SKILL.md`: none; its "some 400 tokens at the default 640x480" becomes true.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | The teardown uses omni.syntheticdata's private registry (A10); a release that renames it brings E16's errors back | Accepted: Replicator, NVIDIA's own, depends on the same names; the drop warns and goes on without them; `test_12d` and `test_17_06` catch it on each Kit release |
| R2 | A capture leaves Kit's unsaved-edits flag set (E13), and a save from elsewhere during a call writes the feed's render product into the user's file | Accepted: `main`'s `camera_path` sets the flag already, and the viewport's own render product is written the same way (#25's E12); the feed's prim is gone after the call |
| R3 | A second render while a call runs | Accepted: #25's E7 finds it within noise at 640x480 headless; it lasts the call only |
| R4 | The image is a view of its own, 2/255 from the viewport's (E15) | Accepted: the same camera, size and settings; TOOLS.md says it |
| R5 | The boxes come from omni.syntheticdata's pinhole fitted to the horizontal aperture; measured right at 16:9 and 4:3 (E2, E4, E11), not yet portrait or another aperture conform setting | Open: `test_12b` includes 360x640. If portrait disagrees, that case goes to an issue of its own and the test keeps landscape sizes, said in the review record |
| R6 | A large size costs memory and time: 3840x2160 took 0.8 s through the viewport (E8), and `inspect_prim` at the limit for 14 angles answers with hundreds of megabytes | Accepted, within the shared limit (Q2) |
| R7 | Settling: a renderer mode or setting other than those measured (Real-Time 1.0, E17; Path Tracing at fewer samples a frame) may need more frames | Path Tracing at fewer samples a frame waits for them through `settle_frames`, unit-tested and measured live only at Isaac Sim's 64 and 64; accepted for the other modes, whose first frame E14 shows within 0.24 of settled |
| R8 | This change waits on #25 (Q6) | Accepted: (a) is the fallback, its design kept above |
| R-a | Only if Q1 is (a): Kit 107's menu writes a preset size to the persistent resolution and leaves "Viewport"-size mode (A7); a window resized during a capture resizes the viewport (A6) | Accepted for (a) with Q4; the PNG check catches the second |

## Plan review

### Round 1

**How:** `review-plan`, a fresh reviewer (Claude), 2026-10-30, on `304519f`. **Verdict:** `needs-fixes`: three
majors, six minors. **Now:** all nine fixed in the commit after `304519f`, with runs 2 and 3 (E11-E18) run by the main
session on a fresh Kit; round 2 follows, since there were majors.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | The plan compared against #25's old Replicator design; #25's current plan (`39c1e8b`) has a hydra-texture camera feed "built for #51 to reuse", the direction the maintainer approved in Q6 of `2026-10-29-debug-draw-and-ignored-parameters.md`, and rejects resizing the viewport | fixed: Q1 compares (a), (b) and (c) with E11-E18; the recommendation is now (b), #25's feed, with the segmentation teardown E16 showed is needed; (a)'s design kept as the fallback |
| P2 | major | Nothing waited for the renderer after a resize; E3 measured size and brightness only; Path Tracing's first iteration may be noisy | fixed: E14 measures the first capture against a settled one in RT 2.0 and Path Tracing for both ways and for `main`'s camera move; `settle_frames` waits out Path Tracing's samples; R7 |
| P3 | major | The recording skip didn't hold, ticks running in flight (#25's E10), and had no test | fixed: dropped. (b) never touches the viewport, and after #25 recording doesn't read it; the change merges after #25 (Q6) |
| P4 | minor | Kit 107's resolution menu re-applies a preset and persists it | fixed: A7, in Q1's comparison, Q4 and R-a |
| P5 | minor | Kit 110's render-scale menu persists `resolutionScale` | fixed: A8; moot for (b); (a) sets the full resolution instead of the scale |
| P6 | minor | A size that won't hold cost 30 s a capture and didn't stop the call | fixed: moot for (b), whose frames are its size; (a) retries 3 frames, then fails and stops the call |
| P7 | minor | `/camera/inspect` without a size couldn't be fitted | fixed: a body without a size takes the viewport's resolution |
| P8 | minor | No test for an older extension's answer without `width` and `height` | fixed: `test_tools_camera.py` |
| P9 | minor | The `mcp.capture_viewport(width=1280)` example now gives 1280x480 | fixed: `(1280, 720)` in all four places |

**Refuted:** none.

**Owner calls:** the reviewer's O1 (the merge order with #25) is Q6, O2 (`readOnlyHint`) Q7, O3 (no Kit 107 live run)
Q8, O4 (one size limit with #25) Q2; Q1-Q5 stay. All unanswered.

| Improvement | Answer |
|---|---|
| None offered | |
