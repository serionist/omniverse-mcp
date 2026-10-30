---
title: Record start_recording's frames from its camera at its size
issue: "#25"
status: approved
approved_by: serionist
approved_at: 2026-10-30
---

# Record start_recording's frames from its camera at its size

`start_recording` records the active viewport, from its camera at its own size, and since 0.2.1 warns when it is
given a `camera_path`, `width` or `height` (#52). This plan makes it record from `camera_path` at `width` x
`height` through a render of the recording's own, a hydra texture, without Replicator and without touching the
user's viewport. It is the last part of #25: `draw_debug` (#53) and `apply_force` (#59) are done.

## Goal

When this is done, on Isaac Sim 6.x headless or in the GUI, and on any Kit 107+ app with a viewport:

| | What | Shown by |
|---|---|---|
| 1 | Frames come from `camera_path`, or from the active viewport's camera when it is empty | `test_06_03` |
| 2 | Every frame is `width` x `height` pixels, whatever the viewport's size | `test_06_01`, `test_06_03` |
| 3 | The user's viewport keeps its camera, its view and its size while recording, and Replicator's settings and the timeline are left alone | `test_06_03`, `test_06_06` |
| 4 | Frames come in every timeline state and follow the simulation | `test_06_04` |
| 5 | Each frame has its own number: none is overwritten | `test_06_08`, unit tests |
| 6 | A bad camera or size is refused at start, and a recording whose stage changes or whose camera goes stops taking frames and says so | `test_06_05`, `test_06_07`, `test_06_09`, `test_17_05` |
| 7 | `start_recording`'s answer reports the camera and size the frames have; the #52 warning stays for an older extension only | `tests/test_tools.py` |

Why: an assistant that asks for a 320x240 recording from a camera gets the viewport's frames, at its size, with a
warning it has to work around by moving the user's viewport. With this, it records what it asked for.

| In scope | Out of scope |
|---|---|
| `handlers/recording.py`; a camera feed (`handlers/camera_feed.py`) and the capture helper it shares with `capture_viewport_png`; Kit-free `ovmcp/core/recording.py` | `capture_viewport` and `inspect_prim`'s `width` and `height` (#51): they can reuse the camera feed, in their own PR |
| At most four frames in flight, each numbered at its tick, the tracked state read there (today's frames share numbers, E10) | When frames are taken: every few app updates whether or not the simulation plays, as since 0.2.1 |
| `start_recording`'s descriptions and answer text, the #52 warning's case | A tool schema change: names, types, defaults and bounds stay (Compatibility) |
| Live cases for the camera, the size, the viewport left alone, the refusals, a stage change | Video files; frames timed by the clock instead of app updates |

## Design

### How the recording works today

| End | Where | What it does |
|---|---|---|
| Tool | `src/omniverse_mcp/tools/recording.py`, `start_recording` | Sends `output_dir` (`mcp_output/recordings`), `fps`, `width`, `height`, `camera_path`, `track_prims`, `property_filter`; adds #52's `WARNING` when given a camera, or a size other than 640x480 (`_ignored_warning`), since it can't tell 640x480 asked for from the default |
| Client | `client.py`, `recording_start` | `POST /recording/start`; `camera_path` only when set |
| Route | `extension.py` | `/recording/start`, `/recording/stop`, `/recording/frame` |
| Handler | `handlers/recording.py`, `handle_recording_start` | Resolves an empty `camera_path` to the active viewport's camera; makes `rec_<unix time>`; `steps_per_frame = max(1, int(time codes a second / fps))`; subscribes `_on_update` to the app's update stream |
| Tick | `_on_update`, `_record_tick` | Every `steps_per_frame`-th update reads the timeline's time and starts a task that captures `get_active_viewport()` with `capture_viewport_png` (30 s for the frame, 10 s for its file, an empty file when they run out), writes `frame_NNNNN.png`, appends the frame to the metadata and the tracked prims' state |
| Stop | `handle_recording_stop` | Drops the subscription, writes `metadata.json` |
| Shutdown | `extension.py`, `on_shutdown` | Drops the subscription |

`camera_path`, `width` and `height` go only into `_recording_state`, the answer and `metadata.json`.

Two flaws beyond #25, both read in the code and the first measured:

- **Frames share numbers.** `_record_tick` reads `frame_count` before its capture's `await` and counts it after, and
  ticks are not held back while a capture runs. At `fps=30` (a tick every 2 updates) four ticks took each number:
  72 frames captured, 19 numbers, 53 frames overwritten (E10).
- **No bound on captures in flight.** A viewport that renders nothing starts another 40 s wait on every tick.

### What Kit and Isaac Sim offer

Read in the extensions installed with Isaac Sim 6.2.0 (Kit 110.4, `D:\isaac\venv`) and 5.1 (Kit 107.3,
`D:\isaacsim5.1`), and Isaac Sim's docs through Context7.

| # | Fact | Source |
|---|---|---|
| F1 | `omni.kit.hydra_texture.create_hydra_texture(name, width, height, usd_context_name="", usd_camera_path="/OmniverseKit_Persp", hydra_engine_name="rtx", is_async=True, ...)` renders a camera at a size into a texture of its own. It is in the module's `__all__`, under "Mark the interfaces that are public and documented", on 1.4.6 (Kit 107.3) and 1.6.2 (Kit 110.4). | `omni/kit/hydra_texture/__init__.py`: 1.6.2 lines 10-58, 1.4.6 lines 10-52 |
| F2 | A rendered frame is announced by a drawable-changed event. Kit 110: `GLOBAL_EVENT_DRAWABLE_CHANGED` through `carb.eventdispatcher.get_eventdispatcher().observe_event(..., filter=texture.get_event_key())`, `event["result_handle"]`. Kit 107: `texture.get_event_stream().create_subscription_to_push_by_type(EVENT_TYPE_DRAWABLE_CHANGED, fn)`, `event.payload["result_handle"]`. NVIDIA's material preview tells them apart with `not hasattr(omni.hydratexture, "GLOBAL_EVENT_DRAWABLE_CHANGED")` ("updated to Events 2.0 in 108.2"). | `omni.kit.widget.material_preview` 1.1.4, `material_preview_producer.py` lines 37-39 and 210-236; `omni.kit.hydra_texture` 1.6.2 `tests/test_hydra_texture.py`, `test_2_drawable_changed` |
| F3 | The viewport captures the same way: `capture_viewport_to_file` gives `ViewportAPI.schedule_capture` a capture delegate, and on the next drawable-changed event the viewport's texture calls `delegate.capture({aov["name"]: aov for aov in texture.get_aov_info(result_handle, include_texture=True)}, frame_info, texture, result_handle)`. | `omni.kit.widget.viewport` `impl/texture.py`: 110.0.1 lines 372-445, 107.1.3 lines 337-370 |
| F4 | `omni.kit.widget.viewport.capture.FileCapture(path)` saves the `LdrColor` output (`HdrColor` when there is none) through the renderer capture interface's `capture_next_frame_rp_resource`, then completes; `wait_for_result(completion_frames=2)` waits for that and two more updates. Kit 110 writes the file after that (#32), which `ovmcp.core.capture.capture_png` already waits for. | `capture.py`, 110.0.1 lines 123-195 and 234; 107.1.3 line 216 |
| F5 | Replicator's render product is such a texture: `create_hydra_texture(name, w, h, "", camera, "rtx", async_rendering=False)`. Its `destroy` turns the texture's updates off, drops it, and deletes the render product prim "from all layers" of the stage. Isaac Sim's own examples stop a render product rendering between captures with `rp.hydra_texture.set_updates_enabled(False)`. | `omni.replicator.core` 1.13.38, `scripts/utils/viewport_manager.py` lines 53-170; Context7, Isaac Sim docs: "Access Writer and Annotator Data at Custom FPS", `set_render_products_updates` |
| F6 | Replicator's annotators are gated by its orchestrator: stopped, an `rgb` annotator gives no frame until a step; PLAY with an annotator attached, or an annotator attached while playing (`_on_attached`), applies Replicator's capture settings and play-every-frame, which its restore never undoes; `step_async` turns the timeline's auto-update off and back on only after its render wait, so a step cancelled at a time bound leaves the timeline frozen. | Plan `2026-10-29-debug-draw-and-ignored-parameters.md`, F19 and F20 (measured), round 3's P16 and P17; `orchestrator.py` 1.13.38 lines 321-329, 1851-1860, 1968-2000 |
| F7 | `capture_viewport_to_file(viewport, path, render_product_path=other)` points the viewport at `other` for the capture and back after (`RestoreMultiAOVFileCapture`); `create_viewport_window(name, width, height, camera_path=...)` makes a `ViewportWindow`, a window of the UI. | `omni.kit.viewport.utility` 2.1.2, lines 356-458 and 481-541 |

### What the live runs showed

Run by the main session on Isaac Sim 6.2.0 headless on 2026-10-30, with two scripts kept in the session's scratchpad
(`e25_feed.py`, then `e25_layers.py` on a fresh Kit), against `main`'s bridge: a stage with a red cube in front of
`/World/RecCam` and the viewport aimed at a green one. The texture was made as F1 with `is_async=False`, and frames
taken as the viewport takes them (F3, F4), through `execute_script`.

| # | What it shows | Numbers |
|---|---|---|
| E1 | The texture renders its camera at its size, from its first frame | Made in 0.015 s; first frame 0.17 s later, 320x240, 3.6 % red pixels, not black (mean 222); the same after 10 updates |
| E2 | The viewport is left alone | Before and after: `/OmniverseKit_Persp`, 1280x720, its own render product; its capture meanwhile 1280x720, 4.5 % green, no red; play-every-frame still off |
| E3 | Frames in every timeline state, fresh each time | The red cube's centre at image row 47 stopped, 49 then 106 playing (sim 0.13 s, 0.52 s), 122 twice paused, 47 stopped again; each frame 0.015-0.03 s, its file under 0.02 s |
| E4 | The drawable-changed handler ran on Kit's main thread, while stopped | The first 14 events, all stopped, all on the main thread (the script copied the record then); E16 counts every state |
| E5 | The texture makes a render product prim and leaves it | `/Render/OmniverseKit/HydraTextures/<name>`, `resolution (320, 240)`, `camera` `/World/RecCam`; still there after the texture is dropped, and after a removal from the session layer alone |
| E6 | Any size from 1x1 to 4096x2160 | 1x1, 17x9, 1920x1080 (frame 0.05 s, file 0.17 s, 852 KB), 4096x2160 (0.11 s, 0.58 s, 3.5 MB): each a whole PNG of its size |
| E7 | The cost of one more render: not measurable in one pass | App updates a second, headless, one pass each: 122 without, 115 at 640x480, 101 at 1920x1080, 167 without again; the two baselines differ by 37 %, so no cost is read from them; E20 takes five interleaved rounds. Updates off and on again: the next frame showed the scene |
| E8 | A deleted camera | Frames keep coming, all white, no error |
| E9 | A new stage | The texture renders on, on the new stage: Kit logs "cannot restore camera_path to '/World/RecCam' as it does not exist", and frames are near black (mean 8) |
| E10 | Today's recording, `fps=30`, 2 s playing | 72 frames, 19 numbers, 53 overwritten: four ticks a number |
| E11 | Kit logged "Plugin interface for a client: omni.hydratexture.plugin was already released." twice, once after a play and once at the new stage | E14 finds its source |
| E12 | Kit writes a render product's `def` into the root layer and an `over` into the session layer, whatever the edit target, for the viewport's own as for ours. Deleting the prim from each layer that holds a spec, as Replicator does (F5), clears it | Both render products: `root` `def`, `session` `over`, edit target the root layer; ours made under a session-layer edit target: the same; after the deletion: no spec, no prim. The root layer read as changed, but the scene script had changed it first (E21 starts from a file) |
| E13 | After a new stage the texture renders that stage, from `/OmniverseKit_Persp`, and its render product is there too, a `def` in the new root layer; it stays after the texture is dropped, and the same deletion clears it | `get_camera_path()` `/OmniverseKit_Persp` after `new_stage_async`; the prim on the new stage before and after the drop, gone after the deletion |
| E14 | E11's warning isn't ours | Logged after a play and a stop with no texture made; not logged after a texture is made, used and dropped |
| E15 | The tick below, one frame in flight, numbered at its tick, `fps=30` for 2 s playing | 161 updates, 40 frames, 40 numbers, in order, all whole 320x240 PNGs, none empty; 40 ticks skipped while a frame was in flight (each took 0.031-0.047 s, about four updates); the cube's centre from row 47 to 166 as it fell and landed |

Plan review round 1 asked for more (P4, P5 and rendering on demand); the main session ran `e25_round1.py` (E16-E21),
`e25_residue.py` (E22) and `e25_quality.py` (E23) on fresh Kits the same day. The image's height was matched to
PhysX's pose through a table of the cube's image row at six heights, taken stopped.

| # | What it shows | Numbers |
|---|---|---|
| E16 | The drawable-changed handler runs on the main thread in every timeline state | 77 events over 93 updates, stopped, playing, paused and stopped again: 77 on the main thread, 0 elsewhere |
| E17 | A feed that renders every update delivers a frame on the update it is asked for, showing the simulation one update before its tick | 54 frames at a request every 2 updates, up to 4 in flight; each delivered on its request's update; all 16 frames taken while the cube fell showed PhysX's pose of the update before |
| E18 | A feed rendering on demand (updates on from a request to its delivery) delivers 0 to 2 updates late, and a request made before the last render arrived shares it | 25 frames; delivery 0, 1 or 2 updates after the request; the falling frames within one update of their tick, 8 before and 8 after; pairs of requests 2 updates apart got the same render (rows 55.44, 62.46, 72.35, 83.33 twice each) |
| E19 | Rendering on demand, stopped, the first frame after updates come back on is fresh | The cube moved, then a frame asked for after 0, 1 and 5 updates: rows 121.42, 96.48, 121.38, against the table's 121.44 for its new height 1.5 and 96.46 for 2.0 |
| E20 | The cost, headless: app updates a second, medians of five interleaved rounds of 120 updates | None 213; a feed rendering every update: 145 at 640x480 (32 % fewer), 124 at 1920x1080 (42 %), 52 at 4096x4096 (75 %); a feed on demand, idle: 202 (within the rounds' spread: none ranged 179-214). One 4096x4096 frame: a whole 6.5 MB PNG in 1.14 s |
| E21 | From a scene opened from a file: the root layer reads as changed straight after the open, before any feed (Kit writes the viewport's render product into it); a feed adds its `def`; deleting the render product from every layer leaves no spec at its path, but the root layer's text still names the feed | `root_dirty_after_open: true`; the feed's specs `root` `def`, `session` `over`, then none; `feed_in_root_export_after_removal: true` (E22) |
| E22 | What else names the feed (`e25_residue.py`, a fresh Kit): Kit also adds the render product to `/Render/OmniverseGlobalRenderSettings`'s `products` in the root layer. Deleting the prim from every layer leaves that target, so a scene saved after a recording would list a render product that isn't there | While the texture lives: the session `over` (`viewportHandle`, `viewPickingId`, `deviceIds`), the root `def` (`resolution`, `camera`, `orderedVars` to `/Render/Vars/LdrColor`, 31 `omni:rtx:*` settings) and the `products` target; after the deletion, the `products` target alone |
| E23 | R12's check (`e25_quality.py`, a fresh Kit, real-time path tracing, async rendering off, a still scene, 640x480): a frame rendered on demand is about four times as far from a settled always-on frame as two settled frames are from each other, and doesn't settle at `fps=5` | Mean absolute difference per channel, as a share of 255: two always-on frames after 100 and 130 updates, 0.0020 (0.0024 against a third); on demand, its first frame 0.0094, one after 60 updates off 0.0088, ten at a frame every 12 updates 0.0088 to 0.0098 |

### Candidates

| Candidate | Verdict | Why |
|---|---|---|
| A hydra texture of the recording's own, read as the viewport reads its own (F1-F4) | **Chosen** | E1-E4: the right camera, the right size, every timeline state, the viewport untouched, on the main thread. Every Kit app with a viewport has both extensions. No Replicator, so none of F6 |
| Replicator's render product with an `rgb` annotator (the deferred design) | No | F6: no frame while stopped without a step, Replicator's capture settings and play-every-frame on the user's session, a step cancelled at its bound freezes the timeline (P17), a recording started while playing repeats a frame (P16); and `omni.replicator.core` must be on |
| Replicator's render product, read through the drawable event | No | The chosen design with Replicator turned on only for the prim's name and its removal; turning it on takes seconds and adds its orchestrator's timeline hooks |
| Point the active viewport at the camera and size, put it back after (per frame or per recording) | No | The user sees it in the GUI; it races `capture_viewport`, `inspect_prim` and `set_camera` for the viewport; a resolution change resets the renderer's accumulation |
| `capture_viewport_to_file(..., render_product_path=)` (F7) | No | The viewport shows the recording's camera at every frame |
| A second viewport window (F7) | No | A window opens in the GUI; a hidden one may stop rendering (`capture.NoFrameError`'s "its window hidden") |
| `omni.syntheticdata`'s viewport sensors | No | Bound to a viewport, so to its camera and size |

### The camera feed (Kit, new `handlers/camera_feed.py`)

`CameraFeed(camera_path, width, height)`, one per recording; built so #51 could reuse it (Overlap):

- **The texture:** `create_hydra_texture(name, width, height, "", camera_path, "rtx", is_async=False)`, as Replicator
  makes one (F5), named `ovmcp_recording_<uuid hex>`: a session's id is its start second, so a forced restart within
  that second would reuse a name. `None` or an exception is an error. No edit target is set around it: Kit writes
  the render product into the root layer whatever the target (E12).
- **Rendering while the recording runs:** the texture renders every update from start to stop, so each frame is as
  settled as the viewport's own. Rendering on demand (updates off, F5, except from a frame's request to its
  delivery) costs nothing measurable between frames (E20) and its frames show the scene as it is (E19), but under
  Isaac Sim's default real-time path tracing each is a first render, about four times as far from a settled frame as
  two settled frames are from each other, and it doesn't settle at `fps=5` (E23). Rendering every update costs a
  third of the app's updates at 640x480 headless (E20). Which to ship is an owner call (Q9).
- **One drawable-changed subscription,** in F2's Kit 110 form when `omni.hydratexture` has
  `GLOBAL_EVENT_DRAWABLE_CHANGED`, else the Kit 107 one. The handler counts frames and hands any queued capture
  delegate the frame's outputs exactly as the viewport does (F3). Nothing else runs in it: no USD, no logging (#5's
  rule), whatever thread Kit calls it on (R1).
- **`schedule(delegate)` and `withdraw(delegate)`:** a frame given up at its time bound is withdrawn, so no late write
  lands in a temp file already deleted.
- **`first_frame(seconds)`:** waits for the first drawable-changed event, bounded. A feed capture waits on the feed's
  own frames only, never the viewport's (Overlap).
- **`drop()`:** the subscription first, then `set_updates_enabled(False)` and the texture (F5). Safe to call twice.
- **`remove_render_product(stage)`:** deletes the render product's path from every layer of `stage` that holds a
  spec of it, as Replicator does (F5), and its target from `/Render/OmniverseGlobalRenderSettings`'s `products` in
  every layer that lists it (E22), only while the stage is `OPENED`. It clears the prim on the stage the feed was
  made on and on a new one (E12, E13). The path is kept when the feed is made, so it is known after `drop()`.

`capture_viewport_png`'s body becomes `capture_file_png(schedule, budget)` in `handlers/_utils.py`: a temp file of its
own, `capture.capture_png`, the unlink. `capture_viewport_png(viewport, budget)` and the new
`capture_feed_png(feed, budget)` each pass their `schedule`; the viewport's capture is unchanged.

### The Kit-free part (new `ovmcp/core/recording.py`)

- **`recording_args(body)`:** a `RecordingArgs` or a `ValueError` that says what is wrong. `output_dir` required;
  `fps` a whole number, not a boolean, at least 1; `width` and `height` through the one size check the three tools
  share (Q8, Overlap): whole numbers from 1 to `MAX_SIDE = 4096` each (Q2); `camera_path` a string; `track_prims`
  and `property_filter` lists of strings or none.
- **`steps_per_frame(time_codes_per_second, fps)`,** as today's inline `max(1, int(...))`.
- **`camera_error(stage, path)`:** why `path` can't be recorded from (no prim there, or not a `UsdGeom.Camera`), or
  `None`; usd-core runs it in the tests.
- **`FrameClock(steps_per_frame)`:** `tick()` is the number of the frame to take on this update, or `None`: every
  `steps_per_frame`-th update, while no frame awaits its render and fewer than `MAX_IN_FLIGHT = 4` frames are in
  flight; `rendered()` and `done()` free them. Rendering every update, a frame arrives on its request's update (E17),
  so the first rule costs nothing; it keeps two frames from sharing a render, as they did on demand (E18). Numbers
  start at 0 and never repeat. A frame takes about four app updates (E15), most of them after its render (E17): with
  one in flight, `fps=30` gave 15 frames a second; four leave room for more while their files are written, and the
  one awaiting its render holds a feed that renders nothing to one wait at a time. A tick skipped shows as a gap in
  the frames' `sim_time` (Q5).

### The recording handler (`handlers/recording.py`)

- **Start:**
  1. `recording_args`; an error answer on `ValueError`.
  2. The recording is marked as starting, so a second start meanwhile gets "Recording already active", as one during
     a recording does. Every error below clears the mark.
  3. The camera: `camera_path`, or the active viewport's camera when empty, checked with `camera_error`; the stage's
     id taken.
  4. The feed, then `first_frame(capture.FRAME_SECONDS)`, the 30 s a viewport frame gets, sized for #27's cold
     starts: no frame is "the camera rendered no frame in 30 s". Then the stage's id again: another stage (a
     `new_scene` during the wait) is an error. Any error from here on drops the feed and deletes its render product
     from the stage now open, once it is `OPENED`, before answering.
  5. The session folder, the state file's header and the update subscription, as today.
  6. Answer: `resolution` and `camera_path` are now what the frames are; new `render_product`, the prim the feed
     renders into, which also tells the server this extension records from a camera (Q3).
- **Each update:**
  - If the stage isn't `OPENED` (`get_stage_state()`, so frames stop as soon as a stage starts to close), or is not
    the one the recording started on (its `get_stage_id()`), or `camera_error` finds the camera gone, the recording
    takes no more frames, cancels the frames in flight (their files are the empty marker, at once, not after 30 s),
    drops its feed and keeps why for stop and `get_sim_state` (E8, E9; Q4). After a stage change the feed renders the
    new stage from its default camera (E13), so its render product is deleted from the new stage on the first update
    on which that stage is `OPENED`.
  - Otherwise `FrameClock.tick()`. A frame gets its number and `sim_time` at its tick, and the tracked prims' state is
    read and appended to `state.txt` there too, on the main thread, so it is the state at that `sim_time` and in
    order; today it is read after the capture, frames later. A task of its own then captures the frame from the feed
    (30 s for the frame, 10 s for its file, an empty file when they run out, as today) and writes `frame_NNNNN.png`
    and its metadata.
- **Stop:** drops the update subscription, awaits the frames in flight, drops the feed and removes its render product,
  writes `metadata.json` (frames in number order and, when frames stopped early, `ended`), and answers with `note`
  saying why frames stopped early, if they did. Each teardown step runs in its own `try`, its failure logged and
  named in `note`, so `metadata.json` is written and the recording ends whatever the removal does.
- **A forced restart** (`force`, which the client never sends) tears the old recording down as stop does, without
  `metadata.json`, as today.
- **`on_shutdown`** (Kit's exit, the extension turned off, a hot reload): cancels the frame tasks, drops the
  subscription and the feed; deletes nothing, since the stage may be tearing down (R10).
- **`get_sim_state`:** while a recording runs whose frames stopped, its answer gains `recording_note`, the same why,
  and the tool shows it.
- **`get_recording_frame`:** unchanged.

### The server (`tools/recording.py`)

- **Descriptions:** `start_recording` records `camera_path` (the active viewport's camera when empty) at `width` x
  `height`, through a render of its own: the viewport, its camera and its size stay as they are. Up to 4096 a side.
  A frame every few app updates, whether or not the simulation plays; frames stop if the stage changes or the camera
  is deleted. `width`: "Frame width in pixels, up to 4096"; `height` likewise; `camera_path`:
  "The camera to record, e.g. /World/RecCam; the active viewport's camera when empty".
- **Answer text:** `Recording rec_1 at 5fps, 320x240 from /World/RecCam -> recordings/rec_1`. `stop_recording`
  adds the `note` when there is one.
- **The #52 warning** stays for an answer without `render_product`: an extension of 0.2.2 or older, whose frames still
  come from the viewport. It names what is ignored, as now, and the fix: `uvx omniverse-mcp extension install`, then
  restart Kit. An answer with `render_product` gets none.
- **`get_sim_state`** shows `recording_note` when there is one.

### Overlap with #51 and #57

Two plans planned alongside this one touch the same code. Each lands on its own; the merge order is an owner call
(Q6).

| Plan | What it does here | How this plan meets it |
|---|---|---|
| #51, `2026-10-30-capture-at-the-size-asked-for.md` (branch `51-capture-size`) | Holds the viewport at the size asked for during a capture (`ViewportAtSize`), and makes recording's tick skip while it does (`capture.resized()`); adds `capture.MAX_SIDE = 4096` and `capture.capture_size(body)` | Recording no longer reads the viewport, so the skip goes: this PR removes it if #51 lands first, or #51 leaves it out if this lands first. One size check in `ovmcp/core` for the three tools (Q8): whichever lands first adds it, the other uses it. #51 could also capture through this plan's feed instead of resizing the viewport (Q6). If it does, with segmentation, the feed's teardown must reset the render product's `omni.syntheticdata` graphs before deleting it, in Replicator's order (F5): #51's run gave 0 tracebacks that way, and without it 380 at the teardown, 400 at the next save and 2 at a new stage. That is #51's to add: a recording registers no graphs |
| #57, `2026-10-30-capture-a-fresh-frame.md` (branch `57-debugdraw-capture`) | `capture.capture_png` waits `FRESH_FRAMES = 4` of the viewport's frames before a capture, since the viewport's frame trails its request by about 3 updates; its round 1 leaves recording out of the wait | A feed capture passes no viewport frames to wait on: its delegate is served by the feed's own next frame, which shows the simulation within one update of its tick (E17, E18; R8), not #57's three |

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Keep the tool's schema as it is (defaults 640, 480, `""`; minimum 1), so a default call now records 640x480 from the active camera, where it recorded the viewport's size? | Yes: 640x480 is what the contract has always said; "0 means the viewport's size" would be a schema change for a case `capture_viewport` covers || As recommended (2026-10-30) |
| Q2 | Cap a side at 4096, as #51 does, refused by the extension, not in the schema? | Yes: 4096x4096 works, a 6.5 MB frame in 1.14 s, though rendering it every update leaves a quarter of the app's updates headless (E20), which TOOLS.md says; a schema `maximum` is a contract change for no gain. #51's round-1 plan (`00469be`) names 3840x2160 a frame besides; this plan measured 4096x4096 and keeps 4096 a side alone, for the shared check (Q8) || As recommended (2026-10-30) |
| Q3 | Keep #52's warning for an extension of 0.2.2 or older, told apart by `render_product` missing from its answer? | Yes, with the install line: a new server on an old extension would otherwise say nothing again || As recommended (2026-10-30) |
| Q4 | When the stage changes or the camera goes mid-recording, stop taking frames and say so at stop, rather than record near-black or white frames (E8, E9)? | Yes || As recommended (2026-10-30) |
| Q5 | Up to four frames in flight, each numbered at its tick, where today's unbounded ticks overwrite each other (E10) and one in flight halves `fps=30` (E15)? | Four: close to the `fps` asked, and bounded || As recommended (2026-10-30) |
| Q6 | #51's direction (resize the viewport for a capture, or capture through this plan's feed), and the merge order of #51, #57 and #25 | #51's own call; whichever order, the second to land takes the first's size check, and #51's recording skip goes (Overlap) || As recommended (2026-10-30) |
| Q7 | Frames overwriting each other (E10) gets an issue of its own, closed by this PR, with its own CHANGELOG line? | Yes: a bug users hit at any `fps` whose ticks outrun a capture, apart from #25's camera and size || As recommended (2026-10-30) |
| Q8 | One size check in `ovmcp/core` for `capture_viewport`, `inspect_prim` and `start_recording`? | Yes: one cap, one message, one test || As recommended (2026-10-30) |
| Q9 | The feed renders every update while the recording runs (settled frames; a third of the app's updates at 640x480 headless, three quarters at 4096x4096, E20), or only for each frame (nothing measurable between frames; frames about four times the settled noise under real-time path tracing, E23)? | Every update: recorded frames match what the viewport shows, and the cost lasts only while recording. Headless, where each update advances the simulation a fixed step (E15: 161 updates, 2.63 s simulated), it slows the run's wall time, not its results. A warm-up of a few updates before each frame is a middle way no run here has measured || As recommended (2026-10-30) |

## Compatibility

No one-way door moves.

| Door | Effect |
|---|---|
| Tool names, parameters, types, defaults, bounds, hints | None. Only descriptions change, which `tools/golden.py` strips: `tests/fixtures/mcp-tools.json` stays as it is. The cap is the extension's refusal (Q2). |
| Wire protocol | Same paths and bodies. The start answer gains `render_product`, the stop answer `note`, `/sim/state`'s `recording_note`; `PROTOCOL` stays 1. |
| The extension's id and settings | Unchanged. `extension.toml` gains `omni.kit.hydra_texture` and `omni.kit.widget.viewport` as optional dependencies, so Kit loads them first where they exist and the extension still loads where they don't; they are imported at the call, as the viewport capture already does. |
| The output folder's layout | The same files; `metadata.json`'s `resolution` and `camera_path` are now the frames', and it gains `ended` when frames stopped early. |

What users notice:

| Before | After |
|---|---|
| Frames from the active viewport, at its size (1280x720 headless), with a `WARNING` when given a camera or a size | Frames from `camera_path` or the active camera, at `width` x `height`: 640x480 by default (Q1) |
| Several frames could share a number, each overwriting the last (E10) | Each frame its own number; a tick while four frames are still being written takes none, which `sim_time` shows |
| The tracked prims' state was read when a frame's capture ended, frames after its `sim_time` | It is read at the frame's tick, at its `sim_time` |
| A new stage or a deleted camera went on recording the viewport | Frames stop, and `stop_recording` and `get_sim_state` say why (Q4) |
| | One more render every update while recording, at the frame's size: a third of the app's updates at 640x480 headless, three quarters at 4096x4096 (E20; Q9) |
| | A frame shows the simulation one update before its `sim_time` (E17) |

- **Mixed releases:** the fix is in the extension: `uvx omniverse-mcp extension install`, then restart Kit, as
  `get_sim_state`'s `note` says. A new server on an older extension keeps #52's warning (Q3); an older server on the
  new extension warns of values that are no longer ignored, which updating the server ends.
- **Kit apps:** Kit 107 and 110 through F2's two event forms. Run live on Isaac Sim 6.2 only: 5.1 crashes in its own
  start on this machine.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | The live runs before any code: E1-E23 done, and the Design follows them (the edit target and the removal from E12, E13 and E22, the warning from E14, frames in flight from E15, rendering every update from E18 to E20 and E23, pending Q9). Q7's issue opened by the maintainer's session | What the live runs showed |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | `core/recording.py` | `tests/test_recording.py` |
| 3 | `handlers/camera_feed.py`; `capture_file_png` in `_utils.py`, `capture_viewport_png` and `capture_feed_png` on it | `tests/test_camera_feed.py`; the capture tests unchanged and passing; live: the capture and inspect tests, `test_integration.py`'s `test_10` to `test_15e` and the scenario phases 3, 22 and 26 |
| 4 | The recording handler: start, the tick, stop, the forced restart, `on_shutdown`, `get_sim_state`'s `recording_note`; the two optional dependencies in `extension.toml` | `tests/test_recording_handler.py`; live: `test_06_01` to `test_06_09`, `test_17_05` |
| 5 | The tool's descriptions and text, #52's warning for an older extension | `tests/test_tools.py`; `tests/test_contract.py` unchanged |
| 6 | The docs | Below |
| 7 | Both live suites in full on Isaac Sim 6.2 headless; `review-code` | No failures beyond `main`'s on the same Kit |

## Tests

**Unit (CI):**

| File | What it checks |
|---|---|
| `tests/test_recording.py` (new) | `recording_args` takes and refuses what it should: 4096 a side taken, 4097 refused, 0 and `True` refused, a missing `output_dir` (the size check itself is tested where it lives, Q8); `steps_per_frame`; `camera_error` on a usd-core stage: nothing there, an Xform, a Camera; `FrameClock`: a frame every `steps_per_frame` updates, none while one awaits its render or four are in flight, one again once freed, numbers from 0 in order and never repeated |
| `tests/test_camera_feed.py` (new) | Against a fake Kit, as `tests/test_debug_draw_handler.py` loads its handler: the Kit 110 event form when the module has it, the 107 form otherwise; updates on from creation to `drop` (or, if Q9 picks on demand, off until a delegate is queued, on until its frame is delivered, then off); a queued delegate gets the next frame's outputs keyed by name, once; a withdrawn one gets none; `drop` twice is safe; `remove_render_product` deletes the prim in each layer holding a spec and the `products` target in each layer listing it, and nothing while the stage isn't `OPENED` |
| `tests/test_recording_handler.py` (new) | Against a fake Kit: start makes one feed with the camera and size asked; a missing camera, a non-camera and a bad size make none; a second start while the first awaits its first frame is refused; a feed with no first frame, or a stage change during that wait, is an error that drops the feed and removes its render product; a tick while a frame awaits its render, or with four in flight, takes none; the tracked state is written at the tick, in number order, whatever order the captures end in; stop awaits every frame in flight and lists them in number order; a removal that raises still lets stop write `metadata.json`, end the recording and name the failure in `note`; a stage that isn't `OPENED`, a new stage and a deleted camera stop the frames, cancel those in flight (empty markers), drop the feed and give stop and `get_sim_state` their note, and the render product is deleted from the new stage once it is `OPENED`; a forced restart drops the old feed; `on_shutdown` cancels the frame tasks and drops the feed without removing the prim |
| `tests/test_tools.py` | The answer with `render_product` reads `Recording rec_1 at 5fps, 320x240 from /World/RecCam` and has no `WARNING`, given a camera and a size or not; the answer without it (an older extension) keeps the warning, with the install line, for each parameter as today's three tests; `stop_recording` shows a `note`, `get_sim_state` a `recording_note` |
| `tests/test_contract.py` | Unchanged and passing: the golden file doesn't move |

**Live (`OMNIVERSE_MCP_SIM=1`, `test_scenarios.py`, Isaac Sim 6.2 headless):** which frames come from which camera,
at which size. Each test puts back what it moves (the viewport camera, its own prims) in `addCleanup`, places things
with `_up_axis()` and `_along_up()`, and reads a frame's size from its PNG header.

| Test | Camera | Size | It must show |
|---|---|---|---|
| `test_06_01` (changed) | `""`: the active viewport's | 320x240 | Started while stopped, then played: every frame a whole 320x240 PNG; `metadata.json` says 320x240 and the viewport's camera |
| `test_06_03_record_from_a_camera` (new) | `/World/RecCam`, aimed at the red cube; the viewport aimed away (`_aim_away`) | 160x120 | Frames 160x120, most of their pixels strongly red (red above green and blue by 80); after stop, the viewport's camera path, its transform and its resolution are as before, and a capture of it holds no red |
| `test_06_04_frames_follow_the_simulation` (new) | `/World/RecCam` | 320x240 | While the red cube falls, its centre in the last frame is lower than in the first: frames are fresh, none repeated. The simulation is paused, not stopped, before `stop_recording`, since a stop puts the cube back at the top |
| `test_06_05_record_from_a_prim_that_isnt_a_camera` (new) | `/World/RedCube`, then a path with no prim | 320x240 | An error each; nothing new under `/Render`; `get_sim_state` says no recording |
| `test_06_06_recording_makes_and_removes_its_render_product` (new) | `/World/RecCam` | 320x240 | The prim `render_product` names exists while recording; after stop no layer holds it and the root layer's text doesn't name it (E22); play-every-frame as before. On `main` the answer has no `render_product`, so it fails there |
| `test_06_07_refuses_a_frame_too_large` (new) | `/World/RecCam` | 4097x240, then 240x4097 | An error each, naming the cap; no recording active |
| `test_06_08_each_frame_its_own_number` (new) | `/World/RecCam` | 320x240, `fps=30` | Every `frame` in `metadata.json` once, in order, each with its file; it prints how many neighbouring frames are the same byte for byte (R9); on `main` numbers repeat (E10) |
| `test_06_09_recording_stops_when_its_camera_goes` (new) | A camera of its own, deleted mid-recording | 320x240 | No frames after the deletion; `get_sim_state` gives `recording_note`; `stop_recording` succeeds with its `note`; the render product is gone from every layer |
| `test_17_05_recording_stops_at_a_new_stage` (new) | `""` | 320x240 | Recording across `new_scene`: no frames after it, `stop_recording` succeeds with its `note`, nothing left under `/Render` |

**What neither can show:** Kit 107 live; a person watching the GUI's viewport stay put while recording (headless
checks its camera, transform, resolution and a capture instead); a feed that never renders (the fake Kit only); a
cold first recording, the first after Kit starts, whose first frame may need more of `FRAME_SECONDS` than the warm
runs' 0.17 s (the live suites run warm, after earlier phases).

## Docs

- `docs/TOOLS.md`, `start_recording`: what it records and at what size, the cap, frames every few updates whether or
  not the simulation plays, a frame showing the simulation one update before its `sim_time` (E17), the extra render
  while recording and its cost (E20), frames stopping at a stage change or a deleted camera; `metadata.json` now
  lists what the frames are; the parameter table. `stop_recording`'s `note`; `get_sim_state`'s `recording_note`.
- `docs/ARCHITECTURE.md`: Recording System (the feed, the frame clock, stop's cleanup); the handlers list gains
  `camera_feed`; the core list gains `recording.py`; Extension Lifecycle's shutdown drops the feed.
- `README.md`, Known issues: the #25 line goes.
- `CHANGELOG.md`, Unreleased, Fixed, each with the `extension install` line:
  - `start_recording` records from `camera_path` at `width` x `height`, without moving the viewport (#25);
  - a default call now records 640x480 from the active camera, where it recorded at the viewport's size: pass the
    size wanted (#25);
  - frames no longer overwrite each other when they come faster than a capture (Q7's issue).
- `plugin/skills/simulate/SKILL.md`, step 5, by `write-skill`'s rules: "Frames keep the viewport's size and camera for
  now" becomes how to pick the camera and size.
- `test_project/scenarios.md`, phase 6: the `WARNING` check becomes the camera and size checks; phase 17 gains 17.5.
- `AGENTS.md`: the extension's row names recording among the core modules, within the row (149 lines now).
- `docs/plans/2026-10-29-debug-draw-and-ignored-parameters.md`, its progress log: one row saying PR 3's camera and size
  went to this plan, as a plan that spans several PRs allows.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | The drawable-changed handler runs where Kit dispatches it: a Python callback on a worker thread can deadlock on the GIL (#5) | Resolved on Kit 110: main thread only, in every timeline state (E16). Accepted on Kit 107, whose push subscription's thread no run here measured: the handler only queues, with no USD and no logging, whatever thread calls it |
| R2 | One more RTX render every update while recording, at the frame's size: GPU time and VRAM | Accepted, pending Q9: a third of the app's updates at 640x480 and three quarters at 4096x4096, headless (E20); TOOLS.md says so; the feed exists only while recording. On demand would cost nothing measurable between frames, at E23's grain |
| R3 | Kit writes the render product into the root layer, whatever the edit target, adds it to `/Render/OmniverseGlobalRenderSettings`'s `products` there, and the prim outlives the texture (E5, E12, E22): a scene saved mid-recording carries it, as it carries the viewport's own | Accepted for a save mid-recording, as Kit does it for the viewport; otherwise resolved: the prim and the `products` target deleted from every layer at stop, on a failed start and at a stage change (E12, E13, E22); `test_06_06` checks the root layer's text. The root layer reads as changed after any open (E21), so a recording doesn't change what the user is told about unsaved changes |
| R4 | A new stage or a deleted camera gives near-black or white frames (E8, E9), from the new stage's default camera (E13) | Resolved: frames stop, the render product is deleted from the new stage, and stop says why (Q4) |
| R5 | E11's "already released" warning in Kit's log | Resolved: not ours (E14) |
| R6 | Kit 107 runs untested live | Accepted: F2's two forms come from NVIDIA's own code, and the unit tests run both |
| R7 | `FileCapture`'s `capture()` is the viewport widget's delegate protocol, not a documented API | Accepted: the viewport's own capture depends on it; the live suites catch a change on each Kit release |
| R8 | A frame's `sim_time` is read at its tick, but its image is a render of another update | Measured and accepted: always on, the image shows the update before the tick (16 of 16, E17); on demand, within one update either way (E18). TOOLS.md says a frame shows the simulation within one update of its `sim_time`; #57's viewport trail of three doesn't apply to the feed |
| R9 | Two frames could get the same render: a request made before the last render arrived shares it (E18) | Resolved: the frame clock asks for no frame while one awaits its render; `test_06_08` prints how many neighbouring frames are the same byte for byte |
| R10 | `on_shutdown` leaves the render product on the stage: at Kit's exit the stage goes with Kit, but when the extension is turned off or hot-reloaded during a recording, the stage stays, with the prim and its `products` target in the root layer | Accepted: deleting prims while Kit shuts down is the crash `draw_debug`'s plan avoided, and `on_shutdown` can't tell an exit from a turn-off; a recording live across a turn-off is rare, and a new stage or the user deleting the prim clears it. `on_shutdown` cancels the frame tasks, so none writes after |
| R11 | The texture leaves a target in the root layer's `/Render/OmniverseGlobalRenderSettings.products` after its prim is deleted (E21, E22) | Resolved: `remove_render_product` deletes the target too; `test_06_06` checks the root layer's text no longer names the feed |
| R12 | An on-demand frame may be less clean than an always-on one under real-time path tracing, Isaac Sim 6.2's default: #51's run found a feed's first frame further from its 100th (0.24 by that run's measure) than its 100th from its 130th (0.07), and none of E18 to E20 compares image quality | Resolved by E23: on-demand frames were 0.0088 to 0.0098 from a settled frame, against 0.0020 to 0.0024 between settled frames, so on demand failed its rule. The feed renders every update while recording, at E20's cost, and Q9 asks the maintainer to confirm or pick on demand |

## Plan review

### Round 1

**How:** `review-plan`, a fresh reviewer (Claude) started by the main session, 2026-10-30, on `39c1e8b`. It checked
the live runs' numbers against their outputs: E1-E3, E5, E6, E8-E11, E13 and E15 matched, and E14 held (other Kit
logs with no feed of ours show the warning too). **Verdict:** `needs-answers`: six minors, no blocker or major; the
owner calls wait for the maintainer. **Now:** all six fixed in the commit after `39c1e8b`, with round 1's runs
(E16-E23) in. E23 settled R12 against rendering on demand, so the feed renders every update while recording,
pending the new owner call Q9.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | The overlap with #51 and #57 wasn't named: #51 adds `capture.resized()` to `_record_tick` and a `MAX_SIDE` of its own, #57 makes `capture_png` wait four viewport frames; whichever lands second meets three changes to the same code and two size caps | fixed: Design, Overlap with #51 and #57: a feed capture waits on the feed's own frames only; #51's recording skip goes; one size check in `ovmcp/core` (Q8); #51's direction and the merge order are owner calls (Q6) |
| P2 | minor | `first_frame(10 s)` was shorter than `capture.FRAME_SECONDS` (30 s, sized for #27's cold starts), so a cold first recording could fail at start | fixed: `first_frame(capture.FRAME_SECONDS)`; "a cold first recording" in What neither can show |
| P3 | minor | Cleanup paths: a second start during the first-frame wait, or a `new_scene` during it, left two feeds or a feed on the wrong stage; a removal that raised in stop left `metadata.json` unwritten and the recording half ended; R10 named only Kit's exit | fixed: start marks the recording as starting and checks the stage's id after the wait; each stop step in its own `try`, `metadata.json` written whatever the removal does, with a unit test of a removal that raises; R10 names the extension turned off and a hot reload, and `on_shutdown` cancels the frame tasks |
| P4 | minor | Evidence stated beyond the runs: E4 copied the thread record after 14 events, all stopped; E7 read a cost from one pass whose baselines differed by 37 %; Q2 cited 4096x2160 working while `MAX_PIXELS` refused it; E12's root layer was already changed by the scene script | fixed: E4, E7 and E12 restated to what their runs showed; round 1's run counted every state (E16), took the cost over five interleaved rounds (E20) and started from a root layer opened from a file (E21), which found the `products` target left behind (E22, R11); the cap is 4096 a side, one check with #51's (Q2, Q8), and 4096x4096 was measured (E20) |
| P5 | minor | Which way a frame's image lags its tick was unmeasured for this feed, where #57 measured the viewport's frame three updates behind | fixed: E17 and E18 match the falling cube's image height to PhysX's pose: always on, the update before the tick; on demand, within one update either way; R8 and TOOLS.md say so |
| P6 | minor | No live test of a camera deleted mid-recording | fixed: `test_06_09` |

**Refuted:** none recorded by this round.

**Owner calls:** Q1-Q9, in Design, Decisions for the maintainer; Q6-Q8 are this round's, Q9 its follow-up run's.
All answered as recommended by the maintainer, 2026-10-30. Q7's issue is #69, which this PR closes with #25.

| Improvement | Answer |
|---|---|
| Render only while a frame is pending (`set_updates_enabled` between captures) | left, for Q9: the first frame after updates come back on shows the scene as it is (E19), but under real-time path tracing it is a first render, about four times the settled noise, and stays so at `fps=5` (E23); the rule that no frame is asked for while one awaits its render (E18) stays |
| Stop taking frames as soon as `get_stage_state()` isn't `OPENED` | taken |
| A texture name of its own (a uuid), not the session's second | taken |
| `omni.kit.hydra_texture` and `omni.kit.widget.viewport` as optional dependencies in `extension.toml` | taken |
| R1's wording for Kit 107, whose thread no run measured | taken |
| `get_sim_state` says when a recording's frames stopped | taken: `recording_note` |
| `test_06_04` pauses rather than stops before `stop_recording` | taken |
| A CHANGELOG line on the new 640x480 default | taken |
| Drop `source`: `render_product` tells a new extension from an old one | taken; Q3 keys on `render_product` |
