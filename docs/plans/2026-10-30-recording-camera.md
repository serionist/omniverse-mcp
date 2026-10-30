---
title: Record start_recording's frames from its camera at its size
issue: "#25"
status: draft
approved_by:
approved_at:
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
| 6 | A bad camera or size is refused at start, and a recording whose stage changes or whose camera goes stops taking frames and says so | `test_06_05`, `test_06_07`, `test_17_05` |
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
| E4 | The drawable-changed handler runs on Kit's main thread | 62 events, all on the main thread |
| E5 | The texture makes a render product prim and leaves it | `/Render/OmniverseKit/HydraTextures/<name>`, `resolution (320, 240)`, `camera` `/World/RecCam`; still there after the texture is dropped, and after a removal from the session layer alone |
| E6 | Any size from 1x1 to 4096x2160 | 1x1, 17x9, 1920x1080 (frame 0.05 s, file 0.17 s, 852 KB), 4096x2160 (0.11 s, 0.58 s, 3.5 MB): each a whole PNG of its size |
| E7 | The cost of one more render | App updates a second, headless: 122 without, 115 at 640x480, 101 at 1920x1080, 167 without again: within this run's noise at 640x480, about a sixth fewer at 1920x1080 against the first baseline. Updates off and on again: the next frame good at once |
| E8 | A deleted camera | Frames keep coming, all white, no error |
| E9 | A new stage | The texture renders on, on the new stage: Kit logs "cannot restore camera_path to '/World/RecCam' as it does not exist", and frames are near black (mean 8) |
| E10 | Today's recording, `fps=30`, 2 s playing | 72 frames, 19 numbers, 53 overwritten: four ticks a number |
| E11 | Kit logged "Plugin interface for a client: omni.hydratexture.plugin was already released." twice, once after a play and once at the new stage | E14 finds its source |
| E12 | Kit writes a render product's `def` into the root layer and an `over` into the session layer, whatever the edit target, for the viewport's own as for ours, and the root layer then reads as changed. Deleting the prim from each layer that holds a spec, as Replicator does (F5), clears it | Both render products: `root` `def`, `session` `over`, edit target the root layer; ours made under a session-layer edit target: the same; after the deletion: no spec, no prim |
| E13 | After a new stage the texture renders that stage, from `/OmniverseKit_Persp`, and its render product is there too, a `def` in the new root layer; it stays after the texture is dropped, and the same deletion clears it | `get_camera_path()` `/OmniverseKit_Persp` after `new_stage_async`; the prim on the new stage before and after the drop, gone after the deletion |
| E14 | E11's warning isn't ours | Logged after a play and a stop with no texture made; not logged after a texture is made, used and dropped |
| E15 | The tick below, one frame in flight, numbered at its tick, `fps=30` for 2 s playing | 161 updates, 40 frames, 40 numbers, in order, all whole 320x240 PNGs, none empty; 40 ticks skipped while a frame was in flight (each took 0.031-0.047 s, about four updates); the cube's centre from row 47 to 166 as it fell and landed |

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

`CameraFeed(name, camera_path, width, height)`, one per recording; built for #51 to reuse:

- **The texture:** `create_hydra_texture(name, width, height, "", camera_path, "rtx", is_async=False)`, as Replicator
  makes one (F5). `None` or an exception is an error. No edit target is set around it: Kit writes the render
  product into the root layer whatever the target (E12).
- **One drawable-changed subscription,** in F2's Kit 110 form when `omni.hydratexture` has
  `GLOBAL_EVENT_DRAWABLE_CHANGED`, else the Kit 107 one. The handler counts frames and hands any queued capture
  delegate the frame's outputs exactly as the viewport does (F3). Nothing else runs in it: no USD, no logging (#5's
  rule). E4 shows it on the main thread.
- **`schedule(delegate)` and `withdraw(delegate)`:** a frame given up at its time bound is withdrawn, so no late write
  lands in a temp file already deleted.
- **`first_frame(seconds)`:** waits for the first drawable-changed event, bounded.
- **`drop()`:** the subscription first, then `set_updates_enabled(False)` and the texture (F5). Safe to call twice.
- **`remove_render_product(stage)`:** deletes the render product's path from every layer of `stage` that holds a
  spec of it, as Replicator does (F5), only while the stage is `OPENED`. It clears the prim on the stage the feed was
  made on and on a new one (E12, E13). The path is kept when the feed is made, so it is known after `drop()`.

`capture_viewport_png`'s body becomes `capture_file_png(schedule, budget)` in `handlers/_utils.py`: a temp file of its
own, `capture.capture_png`, the unlink. `capture_viewport_png(viewport, budget)` and the new
`capture_feed_png(feed, budget)` each pass their `schedule`; the viewport's capture is unchanged.

### The Kit-free part (new `ovmcp/core/recording.py`)

- **`recording_args(body)`:** a `RecordingArgs` or a `ValueError` that says what is wrong. `output_dir` required;
  `fps`, `width`, `height` whole numbers, not booleans, `fps` at least 1; `width` and `height` from 1 to
  `MAX_SIDE = 4096` each, and at most `MAX_PIXELS = 3840 * 2160` in a frame (Decisions, Q2); `camera_path` a string;
  `track_prims` and `property_filter` lists of strings or none.
- **`steps_per_frame(time_codes_per_second, fps)`,** as today's inline `max(1, int(...))`.
- **`camera_error(stage, path)`:** why `path` can't be recorded from (no prim there, or not a `UsdGeom.Camera`), or
  `None`; usd-core runs it in the tests.
- **`FrameClock(steps_per_frame)`:** `tick()` is the number of the frame to take on this update, or `None`: every
  `steps_per_frame`-th update, while fewer than `MAX_IN_FLIGHT = 4` frames are in flight; `done()` frees a place.
  Numbers start at 0 and never repeat. A frame takes about four app updates (E15): with one in flight, `fps=30` gave
  15 frames a second; four in flight leave room for 30, and still hold a feed that renders nothing to four waits at a
  time. A tick skipped shows as a gap in the frames' `sim_time` (Q5).

### The recording handler (`handlers/recording.py`)

- **Start:**
  1. `recording_args`; an error answer on `ValueError`.
  2. The camera: `camera_path`, or the active viewport's camera when empty, checked with `camera_error`.
  3. The feed, then `first_frame(10 s)`: no frame is "the camera rendered no frame in 10 s". Any error from here on
     drops the feed and removes its render product before answering.
  4. The session folder, the state file's header and the update subscription, as today.
  5. Answer: `resolution` and `camera_path` are now what the frames are; new `source: "camera"` and
     `render_product`, the prim the feed renders into.
- **Each update:**
  - If the stage is not the one the recording started on (its `get_stage_id()`), or `camera_error` finds the camera
    gone, the recording takes no more frames, cancels the frames in flight (their files are the empty marker, at
    once, not after 30 s), drops its feed and keeps why for stop (E8, E9; Q4). After a stage change the feed renders
    the new stage from its default camera (E13), so its render product is deleted from the new stage on the first
    update on which that stage is `OPENED`.
  - Otherwise `FrameClock.tick()`. A frame gets its number and `sim_time` at its tick, and the tracked prims' state is
    read and appended to `state.txt` there too, on the main thread, so it is the state at that `sim_time` and in
    order; today it is read after the capture, frames later. A task of its own then captures the frame from the feed
    (30 s for the frame, 10 s for its file, an empty file when they run out, as today) and writes `frame_NNNNN.png`
    and its metadata.
- **Stop:** drops the update subscription, awaits the frames in flight, drops the feed and removes its render product,
  writes `metadata.json` (frames in number order, with `source` and, when frames stopped early, `ended`), and answers
  with `note` saying why frames stopped early, if they did.
- **A forced restart** (`force`, which the client never sends) tears the old recording down as stop does, without
  `metadata.json`, as today.
- **`on_shutdown`:** drops the subscription and the feed; removes nothing, since the stage may be tearing down.
- **`get_recording_frame`:** unchanged.

### The server (`tools/recording.py`)

- **Descriptions:** `start_recording` records `camera_path` (the active viewport's camera when empty) at `width` x
  `height`, through a render of its own: the viewport, its camera and its size stay as they are. Up to 4096 a side
  and 3840x2160 a frame. A frame every few app updates, whether or not the simulation plays; frames stop if the stage
  changes or the camera is deleted. `width`: "Frame width in pixels, up to 4096"; `height` likewise; `camera_path`:
  "The camera to record, e.g. /World/RecCam; the active viewport's camera when empty".
- **Answer text:** `Recording rec_1 at 5fps, 320x240 from /World/RecCam -> recordings/rec_1`. `stop_recording`
  adds the `note` when there is one.
- **The #52 warning** stays for an answer without `source`: an extension of 0.2.2 or older, whose frames still come
  from the viewport. It names what is ignored, as now, and the fix: `uvx omniverse-mcp extension install`, then
  restart Kit. An answer with `source` gets none.

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Keep the tool's schema as it is (defaults 640, 480, `""`; minimum 1), so a default call now records 640x480 from the active camera, where it recorded the viewport's size? | Yes: 640x480 is what the contract has always said; "0 means the viewport's size" would be a schema change for a case `capture_viewport` covers | |
| Q2 | Cap a frame at 4096 a side and 3840x2160 pixels, refused by the extension, not in the schema? | Yes: E6 shows 4096x2160 works, at 3.5 MB a frame; a schema `maximum` is a contract change for no gain | |
| Q3 | Keep #52's warning for an extension of 0.2.2 or older, told apart by `source` missing from its answer? | Yes, with the install line: a new server on an old extension would otherwise say nothing again | |
| Q4 | When the stage changes or the camera goes mid-recording, stop taking frames and say so at stop, rather than record near-black or white frames (E8, E9)? | Yes | |
| Q5 | Up to four frames in flight, each numbered at its tick, where today's unbounded ticks overwrite each other (E10) and one in flight halves `fps=30` (E15)? | Four: close to the `fps` asked, and bounded | |

## Compatibility

No one-way door moves.

| Door | Effect |
|---|---|
| Tool names, parameters, types, defaults, bounds, hints | None. Only descriptions change, which `tools/golden.py` strips: `tests/fixtures/mcp-tools.json` stays as it is. The cap is the extension's refusal (Q2). |
| Wire protocol | Same paths and bodies. The start answer gains `source` and `render_product`, the stop answer `note`; `PROTOCOL` stays 1. |
| The extension's id and settings | Unchanged; `extension.toml` gains no dependency (`omni.kit.hydra_texture` and `omni.kit.widget.viewport` are imported at the call, as the viewport capture already does). |
| The output folder's layout | The same files; `metadata.json`'s `resolution` and `camera_path` are now the frames', and it gains `source` and, when frames stopped early, `ended`. |

What users notice:

| Before | After |
|---|---|
| Frames from the active viewport, at its size (1280x720 headless), with a `WARNING` when given a camera or a size | Frames from `camera_path` or the active camera, at `width` x `height`: 640x480 by default (Q1) |
| Several frames could share a number, each overwriting the last (E10) | Each frame its own number; a tick while four frames are still being written takes none, which `sim_time` shows |
| The tracked prims' state was read when a frame's capture ended, frames after its `sim_time` | It is read at the frame's tick, at its `sim_time` |
| A new stage or a deleted camera went on recording the viewport | Frames stop, and `stop_recording` says why (Q4) |
| | One more render while recording: within noise at 640x480 headless, about a sixth fewer app updates at 1920x1080 (E7) |

- **Mixed releases:** the fix is in the extension: `uvx omniverse-mcp extension install`, then restart Kit, as
  `get_sim_state`'s `note` says. A new server on an older extension keeps #52's warning (Q3); an older server on the
  new extension warns of values that are no longer ignored, which updating the server ends.
- **Kit apps:** Kit 107 and 110 through F2's two event forms. Run live on Isaac Sim 6.2 only: 5.1 crashes in its own
  start on this machine.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | The live runs E1-E15, before any code: done, and the Design follows them (the edit target and the removal from E12 and E13, the warning from E14, frames in flight from E15) | What the live runs showed |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | `core/recording.py` | `tests/test_recording.py` |
| 3 | `handlers/camera_feed.py`; `capture_file_png` in `_utils.py`, `capture_viewport_png` and `capture_feed_png` on it | `tests/test_camera_feed.py`; the capture tests unchanged and passing; live: the capture and inspect tests, `test_integration.py`'s `test_10` to `test_15e` and the scenario phases 3, 22 and 26 |
| 4 | The recording handler: start, the tick, stop, the forced restart, `on_shutdown` | `tests/test_recording_handler.py`; live: `test_06_01` to `test_06_08`, `test_17_05` |
| 5 | The tool's descriptions and text, #52's warning for an older extension | `tests/test_tools.py`; `tests/test_contract.py` unchanged |
| 6 | The docs | Below |
| 7 | Both live suites in full on Isaac Sim 6.2 headless; `review-code` | No failures beyond `main`'s on the same Kit |

## Tests

**Unit (CI):**

| File | What it checks |
|---|---|
| `tests/test_recording.py` (new) | `recording_args` takes and refuses what it should: 4096 a side taken and 4097 refused, 3840x2160 taken and 3840x2161 refused, 0 and `True` refused, a missing `output_dir`; `steps_per_frame`; `camera_error` on a usd-core stage: nothing there, an Xform, a Camera; `FrameClock`: a frame every `steps_per_frame` updates, none while four are in flight and one again once a place is free, numbers from 0 in order and never repeated |
| `tests/test_camera_feed.py` (new) | Against a fake Kit, as `tests/test_debug_draw_handler.py` loads its handler: the Kit 110 event form when the module has it, the 107 form otherwise; a queued delegate gets the next frame's outputs keyed by name, once; a withdrawn one gets none; `drop` twice is safe; `remove_render_product` touches each layer holding a spec, and nothing while the stage isn't `OPENED` |
| `tests/test_recording_handler.py` (new) | Against a fake Kit: start makes one feed with the camera and size asked; a missing camera, a non-camera and a bad size make none; a feed with no first frame is dropped and its render product removed; a tick with four frames in flight takes none; the tracked state is written at the tick, in number order, whatever order the captures end in; stop awaits every frame in flight and lists them in number order; a new stage and a deleted camera stop the frames, cancel those in flight (empty markers), drop the feed and give stop its `note`, and the render product is deleted from the new stage once it is `OPENED`; a forced restart drops the old feed; `on_shutdown` drops it without removing the prim |
| `tests/test_tools.py` | The answer with `source` reads `Recording rec_1 at 5fps, 320x240 from /World/RecCam` and has no `WARNING`, given a camera and a size or not; the answer without `source` (an older extension) keeps the warning, with the install line, for each parameter as today's three tests; `stop_recording` shows a `note` |
| `tests/test_contract.py` | Unchanged and passing: the golden file doesn't move |

**Live (`OMNIVERSE_MCP_SIM=1`, `test_scenarios.py`, Isaac Sim 6.2 headless):** which frames come from which camera,
at which size. Each test puts back what it moves (the viewport camera, its own prims) in `addCleanup`, places things
with `_up_axis()` and `_along_up()`, and reads a frame's size from its PNG header.

| Test | Camera | Size | It must show |
|---|---|---|---|
| `test_06_01` (changed) | `""`: the active viewport's | 320x240 | Started while stopped, then played: every frame a whole 320x240 PNG; `metadata.json` says 320x240, the viewport's camera and `source: camera` |
| `test_06_03_record_from_a_camera` (new) | `/World/RecCam`, aimed at the red cube; the viewport aimed away (`_aim_away`) | 160x120 | Frames 160x120, most of their pixels strongly red (red above green and blue by 80); after stop, the viewport's camera path, its transform and its resolution are as before, and a capture of it holds no red |
| `test_06_04_frames_follow_the_simulation` (new) | `/World/RecCam` | 320x240 | While the red cube falls, its centre in the last frame is lower than in the first: frames are fresh, none repeated |
| `test_06_05_record_from_a_prim_that_isnt_a_camera` (new) | `/World/RedCube`, then a path with no prim | 320x240 | An error each; nothing new under `/Render`; `get_sim_state` says no recording |
| `test_06_06_recording_makes_and_removes_its_render_product` (new) | `/World/RecCam` | 320x240 | The prim `render_product` names exists while recording and is gone after stop, from every layer; play-every-frame as before. On `main` the answer has no `render_product`, so it fails there |
| `test_06_07_refuses_a_frame_too_large` (new) | `/World/RecCam` | 4097x240, then 3840x2161 | An error each, naming the cap; no recording active |
| `test_06_08_each_frame_its_own_number` (new) | `/World/RecCam` | 320x240, `fps=30` | Every `frame` in `metadata.json` once, in order, each with its file; on `main` numbers repeat (E10) |
| `test_17_05_recording_stops_at_a_new_stage` (new) | `""` | 320x240 | Recording across `new_scene`: no frames after it, `stop_recording` succeeds with its `note`, nothing left under `/Render` |

**What neither can show:** Kit 107 live; a person watching the GUI's viewport stay put while recording (headless
checks its camera, transform, resolution and a capture instead); a feed that never renders (the fake Kit only).

## Docs

- `docs/TOOLS.md`, `start_recording`: what it records and at what size, the cap, frames every few updates whether or
  not the simulation plays, the one extra render, frames stopping at a stage change or a deleted camera; `metadata.json`
  now lists what the frames are; the parameter table.
- `docs/ARCHITECTURE.md`: Recording System (the feed, the frame clock, stop's cleanup); the handlers list gains
  `camera_feed`; the core list gains `recording.py`; Extension Lifecycle's shutdown drops the feed.
- `README.md`, Known issues: the #25 line goes.
- `CHANGELOG.md`, Unreleased, Fixed: `start_recording` records from `camera_path` at `width` x `height`, 640x480 by
  default, without moving the viewport; frames no longer overwrite each other; with the `extension install` line.
- `plugin/skills/simulate/SKILL.md`, step 5, by `write-skill`'s rules: "Frames keep the viewport's size and camera for
  now" becomes how to pick the camera and size.
- `test_project/scenarios.md`, phase 6: the `WARNING` check becomes the camera and size checks; phase 17 gains 17.5.
- `AGENTS.md`: the extension's row names recording among the core modules, within the row (149 lines now).
- `docs/plans/2026-10-29-debug-draw-and-ignored-parameters.md`, its progress log: one row saying PR 3's camera and size
  went to this plan, as a plan that spans several PRs allows.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | The drawable-changed handler runs where Kit dispatches it: a Python callback on a worker thread can deadlock on the GIL (#5) | Resolved by E4: main thread only. The handler does no USD and no logging |
| R2 | One more RTX render for the whole recording: GPU time and VRAM | Accepted: E7 measures it, TOOLS.md says so, the cap bounds it; the feed exists only while recording |
| R3 | Kit writes the render product into the root layer, whatever the edit target, and the prim outlives the texture (E5, E12): a scene saved mid-recording carries it, as it carries the viewport's own, and the root layer reads as changed | Accepted for a save mid-recording, as Kit does it for the viewport; otherwise resolved: deleted from every layer at stop, on a failed start and at a stage change (E12, E13); `test_06_06` checks |
| R4 | A new stage or a deleted camera gives near-black or white frames (E8, E9), from the new stage's default camera (E13) | Resolved: frames stop, the render product is deleted from the new stage, and stop says why (Q4) |
| R5 | E11's "already released" warning in Kit's log | Resolved: not ours (E14) |
| R6 | Kit 107 runs untested live | Accepted: F2's two forms come from NVIDIA's own code, and the unit tests run both |
| R7 | `FileCapture`'s `capture()` is the viewport widget's delegate protocol, not a documented API | Accepted: the viewport's own capture depends on it; the live suites catch a change on each Kit release |
| R8 | A frame's `sim_time` is read at its tick; the render it captures is the next one | Accepted: E3's frames follow the simulation; the gap is an update or two, as today |
| R9 | With frames in flight, two ticks could get the same render if Kit rendered less often than it updates | Accepted: `is_async=False` renders the feed with each update, and E15's neighbouring frames differ (the cube at rows 47, 50, 56); their `sim_time`s differ anyway, and `test_06_08` prints how many neighbouring frames are the same byte for byte |
| R10 | `on_shutdown` leaves the render product on the stage | Accepted: deleting prims while Kit shuts down is the crash `draw_debug`'s plan avoided; the stage goes with Kit |

## Plan review

Not reviewed yet.
