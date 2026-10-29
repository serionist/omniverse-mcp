---
title: Make draw_debug work headless, and act on the parameters three tools ignore
issue: "#7, #25"
status: approved
approved_by: serionist
approved_at: 2026-10-29
---

# Make draw_debug work headless, and act on the parameters three tools ignore

Two issues, one plan, three PRs: each is the bridge not doing what a tool's parameters say, and #25's `draw_debug`
row is only fixable on #7's new drawing backend. All the work is in the extension's handlers and its Kit-free core;
the server changes only descriptions and the text it returns. Each PR updates this plan's progress log.

| PR | Branch | Tool | Names |
|---|---|---|---|
| 1 | `7-debug-draw-params`, this plan's branch | `draw_debug` | `Closes #7`, `Refs #25` |
| 2 | `25-apply-force`, from `main` after PR 1 | `apply_force` | `Refs #25` |
| 3 | `25-recording-camera`, from `main` after PR 2 | `start_recording` | `Closes #25` |

## Goal

When this is done, on Isaac Sim 5.x and 6.x, headless or not:

- **`draw_debug` draws** with `isaacsim.util.debug_draw`, enabled on first use if it isn't yet, and each drawing
  stays `duration` seconds, then goes (#7, #25).
- **`apply_force` pushes through PhysX** at `position`, or at the body's centre of mass when it is left out, and
  refuses a body PhysX won't move (#25).
- **`start_recording` records from `camera_path`** (the active camera when empty) at `width` x `height`, while the
  simulation plays (#25).
- **Scenario tests `test_16_03` to `test_16_05` pass** headless, and the live suites gain a case for each parameter
  #25 names.

Why: an agent that asks for a 320x240 recording from a camera, a push at a body's centre, or a line for five seconds
gets something else, reported as success. The tool descriptions say "for now (#25)"; this removes the "for now".

| In scope | Out of scope |
|---|---|
| The `/debug/draw`, `/physics/apply_force` and `/recording/*` handlers; Kit-free logic for them in `ovmcp/core/` | `capture_viewport` and `inspect_prim` have the same flaw with `width` and `height` (Decisions, Q6) |
| The three tools' descriptions and answer text, `impulse`'s set by what PhysX measurably does | #35's ten-second wait, which the recording's viewport fallback keeps |
| Live cases for `duration`, `position`, `impulse`, `camera_path`, `width`, `height` | `draw_debug`'s `sphere` drawn as three crossing lines, as now |
| Docs that name #7 or #25 | #5's deadlock; this plan's live runs wait for its fix (R11) |

## Design

### Root causes

| Problem | Where | Cause |
|---|---|---|
| `draw_debug` fails headless | `handlers/misc.py`, `handle_draw_debug` | It imports `omni.debugdraw`'s module, which imports only once that extension is enabled. Every Isaac Sim ships it, 6.2 included (F4), but only the GUI app enables it, by way of `omni.physx.bundle` and `omni.physx.ui` (F7); a headless app never does, on any version. #7's "omni.debugdraw is gone" was the error message read as a missing package. |
| `duration` ignored | `handlers/misc.py`, `duration = body.get("duration", 5.0)` | Read, never used. And `omni.debugdraw` draws for one frame (F4): a line drawn once was gone on the next frame even in the GUI app, where the import worked. |
| `position` ignored | `handlers/simulation.py`, `handle_apply_force` | Worse than the issue's table: the PhysX call can't succeed. `get_physx_interface()` returns `PhysX`, which has no `apply_force_at_pos` on Kit 107.3, 110.3 or 110.4 (F9); nor does `omni.physx.scripts.utils`. Every call so far took the `except` path, `method = "velocity"`, which adds `force * 0.01` (`* 1.0` for an impulse) to `physics:velocity`: no mass, no point, no PhysX. The `[0, 0, 0]` default for a missing `position` would put the force at the world origin even if the call worked. |
| `camera_path`, `width`, `height` ignored | `handlers/recording.py`, `_record_tick` | Every frame is `capture_viewport_png(get_active_viewport())`, the viewport's own camera at its own size. The three values are only stored in `_recording_state`, reported back and written to `metadata.json`. |

### API facts this rests on

Looked up for Kit 107 and 110: NVIDIA's docs, NVIDIA's Isaac Sim repo at `release/6.2`, and the extensions as
installed here in Isaac Sim 5.0 (Kit 107.3.1), 5.1 (Kit 107.3.3), 6.1 (Kit 110.3) and 6.2.0 (Kit 110.4, pip, in
`D:\isaac\venv`). F18 is plan review round 1's finding, which no Python source here shows; `test_17_03` checks it.
F19 was measured live by the main session.

| # | Fact | Source |
|---|---|---|
| F1 | `from isaacsim.util.debug_draw import _debug_draw`; `_debug_draw.acquire_debug_draw_interface()`; `draw_lines(start_points, end_points, colors, widths)`, colours RGBA in 0-1, widths in pixels: "All lists must have the same length. Lines persist until cleared." `clear_lines()`: "Clear all drawn lines and splines from the screen." `get_num_lines()` counts them. | Isaac Sim docs, `isaacsim.util.debug_draw` 3.2.8 API page; the same import in 6.1's 3.2.6 (`__init__.py` re-exports `bindings._debug_draw`) |
| F2 | "The 3D geometry drawn by this remains persistent across frames and is only cleared when desired", in contrast to the built-in drawer, which clears itself | Isaac Sim docs, `utilities/debugging/ext_isaacsim_util_debug_draw` |
| F3 | Its clear is global, and clearing while the stage tears down crashed: "debug_draw, whose clear is global"; "clearing the debug_draw overlay while the stage and renderer are tearing down segfaults". 3.2.8 (6.2) lists "Prevent debug drawing calls from crashing while a stage is closing or reopening"; 3.1.0 (5.x) and 3.2.6 (6.1) predate it. | NVIDIA's `isaacsim.robot_setup.virtual_gantry/_runtime.py`, `release/6.2`; 3.2.8's `docs/CHANGELOG.md` |
| F4 | `omni.debugdraw` 0.1.4 draws for a frame: its own visual tests call `draw_line` every frame ("Draw for 20 frames") before capturing a viewport window. Its `extension.toml`: "Extension deprecated since Kit 106.0. omni.debugdraw is being replaced by omni.ui.scene." `IDebugDraw.draw_line(start_pos, start_color: int, start_width, end_pos, end_color: int, end_width)` and `draw_lines(lines_list)` of `SimplexPoint` pairs; no line count. Shipped in 5.0, 5.1, 6.1 and 6.2 (`omni.debugdraw-0.1.4+187cf21b`). | `omni.debugdraw-0.1.4` in 5.1, 6.1 and 6.2: `config/extension.toml`, `_debugDraw.pyi`, `tests/visualtests.py` |
| F5 | `isaacsim.util.debug_draw` depends on `omni.hydra.rtx`, `omni.kit.renderer.core`, `omni.graph`, `omni.usd` and the like: no UI, no `omni.debugdraw`. Its 6.1 test draws, then "Captures rendered debug geometry and compares it against a golden image" through a Replicator render product. (The 6.0 docs say geometry it draws "cannot be rendered"; R1.) | `extension.toml` and `tests/test_debug_draw.py` of 3.1.0 (5.1) and 3.2.6 (6.1); Isaac Sim 6.0 docs, `python_scripting/util_snippets` |
| F6 | Enabling at runtime: Isaac Sim's own `enable_extension` is `omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(name, enabled)`, which returns whether it worked; the bridge's `manage_extensions` already calls the same | `isaacsim.core.experimental.utils/python/impl/app.py`, `release/6.2`; `handlers/misc.py` |
| F7 | `isaacsim.exp.base.kit`, which the Python app depends on, lists `isaacsim.util.debug_draw` and `omni.replicator.core` (6.1 lines 57 and 73; 6.2 lines 55 and 71), so both are likely on in a headless app already, though #7 reports the first off. The GUI's `isaacsim.exp.full.kit` lists `omni.physx.bundle` (6.1 line 134; 6.2 line 133), which needs `omni.physx.ui`, which needs `omni.debugdraw`. | `apps/*.kit` of 6.1 and 6.2; `omni.physx.bundle` and `omni.physx.ui` 110.3.2 `extension.toml` |
| F8 | `IPhysxSimulation.apply_force_at_pos(stage_id: int, body_path: int, force: Float3, pos: Float3, mode: str = 'Force')`: "pos: World position where the force is applied. mode: Supporting various modes - Force (default), Impulse, Velocity, Acceleration." Same signature on Kit 107.3 and 110.3. | `omni.physx` 107.3.26 (5.1) and 110.3.2 (6.1), `bindings/_physx.pyi` |
| F9 | `PhysX`, what `get_physx_interface()` returns, has no `apply_force_at_pos`; `omni.physx.scripts.utils` has none either. `PhysX.get_rigidbody_transformation(path)` gives `ret_val` ("whether transformation was found"), `position` and `rotation` "(quat - x,y,z,w)" in global space. | the same `_physx.pyi`; `scripts/ifaces.py`, `scripts/utils.py` |
| F10 | NVIDIA's call takes a body path as `PhysicsSchemaTools.sdfPathToInt(path)` and the stage's id: `get_physx_simulation_interface().apply_force_at_pos(stage_id, rbo_encoded, force, position, "Impulse")` | `omni.physx.tests` 110.3.2, `PhysicsRigidBodyAPI.py`, `test_physics_kinematic_apply_force` |
| F11 | `PhysXUnitTests.get_mass_information(body_path: str) -> dict`, through `get_physxunittests_interface()`, is synchronous: `'mass'`, `'inertia'`, `'com'` ("Center of mass of the body"). NVIDIA's own tool uses it outside tests and reads a mass of 0 as "Mass information not available, please make sure the simulation is running." NVIDIA's mass tests describe `com` as "the expected center of mass of the prim in it's local space" and scale an expected value by the prim's scale before comparing, so it is in the body's frame as PhysX holds it, the frame `get_rigidbody_transformation`'s pose maps to world. | `_physx.pyi`: 107.3.26 line 2469, 110.3.2 line 2421, 110.4.4 line 2424; `omni.physx.ui` `physxDebugView.py` line 640; `omni.physx.tests` `testBases/massTestBase.py` lines 219-223 and 242 |
| F12 | `rep.create.render_product(camera, resolution, force_new=False, name=None, ...)`: "If an existing render product exists that have the same resolution and camera attached, it is returned"; "Render Products no longer in use should be destroyed." `Annotator.get_data(device, do_array_copy=False, ...)`: "if calling get_data() immediately after initialization, the annotator output will not yet be available. Please allow for at least one update"; `do_array_copy` "is necessary if the data is expected to persist, such as when used in conjunction with asynchronous backends". | `omni.replicator.core` 1.13.36 (6.1), `scripts/create.py`, `scripts/annotators.py` |
| F13 | Isaac Sim's camera sensor makes `rep.create.render_product(self.prim_path, resolution=...)`, keeps its `.path`, attaches the `rgb` annotator, and `get_rgba()` returns its `get_data()`, an (height, width, 4) array. NVIDIA's own capture helper calls `await rep.orchestrator.step_async()` between attaching and `get_data()`. | `isaacsim.sensors.camera` (deprecated in 6.x), `camera.py`; `isaacsim.test.utils/image_capture.py` lines 113-115 |
| F14 | `step_async(rt_subframes=-1, pause_timeline=True, delta_time=None, wait_for_render=True)`: "If Replicator is not yet started, an initialization step is first taken". `step_async(delta_time=0.0, pause_timeline=False)` captures without advancing or pausing the timeline; NVIDIA's custom-FPS snippet calls it while the timeline plays, with capture-on-play off. | `orchestrator.py` 1.13.38 (6.2) line 1795; Isaac Sim docs, Replicator snippets ("Capture data at specific simulation timepoints", "Access Writer and Annotator Data at Custom FPS") |
| F15 | `UsdContext.get_stage_state()` returns `StageState`: `CLOSED`, `OPENING`, `OPENED`, `CLOSING`. `UsdContext.get_stage_id()`: "Gets the UsdStage Id that can be queried with Usd.StageCache", on Kit 107.3 and 110.3. | `omni.usd` `_usd.pyi`, 5.1 and 6.1 (1.18.0) |
| F16 | A kinematic body takes `apply_force_at_pos` and doesn't move; the call returns None | `omni.physx.tests` 110.3.2, `PhysicsRigidBodyAPI.py` lines 303-333 |
| F17 | NVIDIA's demo re-applies `apply_force_at_pos` on every update for as long as a key is held, as a push that lasts one step needs | `omni.physx.demos` 110.3.2, `OverlapAnyDemo.process_key` |
| F18 | `isaacsim.util.debug_draw` 3.2.8 drops its drawings when the stage detaches, so a redraw from the bridge's own list after `new_scene` would put the old stage's lines on the new one | plan review round 1, P3; `test_17_03` checks it |
| F19 | With the timeline stopped, Replicator gives no frame on its own: a render product on `/OmniverseKit_Persp` at 320x240 with an `rgb` annotator gave `get_data().shape == (0,)` on each of 60 updates; after one `await rep.orchestrator.step_async(delta_time=0.0, pause_timeline=False)` it gave `(240, 320, 4)`, and the timeline was still stopped. Its `DispatchSync` gate passes on PLAY with capture-on-play, or on a step. | Measured live on Isaac Sim 6.2.0 headless, 2026-10-29, by the main session; `orchestrator.py` 1.13.38 |
| F20 | With capture-on-play on (the default) and an annotator attached, PLAY runs the orchestrator's `_set_capture_settings`: grid, outlines, light and camera gizmos and collider display off, eco mode off, async rendering off unless asked, materials loaded synchronously, the selection cleared, and `timeline.set_play_every_frame(True)`. `_restore_settings` puts back what it cached (`SETTINGS_TO_SAVE`), never play-every-frame. A step runs the same settings. `omni.timeline` has `get_play_every_frame()` and `set_play_every_frame()`. | `orchestrator.py` 1.13.38 (6.2): `SETTINGS_TO_SAVE` line 73, PLAY line 356, `_set_capture_settings` lines 1148-1193, `_restore_settings` lines 1202-1230; `omni.timeline` 1.1.2 `_timeline.pyi` lines 374 and 568 |

### Shared: enabling an extension

- **Kit-free, `ovmcp/core/extensions.py`:** `extension_step(enabled, listed)` decides `ready` (enabled already),
  `enable` (known locally, so turn it on) or `absent`.
- **Kit, `handlers/_utils.py`:** `enable_extension(name) -> bool` reads both from the extension manager
  (`is_extension_enabled`, `get_extensions()`), and for `enable` calls `set_extension_enabled_immediate(name, True)`
  (F6). An app that lacks the extension gets false without a registry fetch or an error in Kit's log.
- `draw_debug` and `start_recording` use it. Enabling runs on Kit's main thread; R11 says why its live runs wait for
  #5's fix.

### `draw_debug` (PR 1)

**Kit-free, `ovmcp/core/debug_draw.py`:**

- `segments(shape, body)`: each shape as line segments, as the handler draws them today: `line` one, `lines` one
  per pair of neighbours, `sphere` three crossing lines, `points` a cross of half-length `size` per point, `point`
  one cross (kept for direct callers). A `ValueError` with today's messages for a missing part, and new ones for a
  vector that isn't three finite numbers and for an unknown shape, which today draws nothing and reports success.
- `rgba(color)`: three numbers clamped to 0-1, alpha 1, red when omitted. `argb(color)` packs the same clamped
  values for `omni.debugdraw`; today `int(r * 255)` with `r` above 1 spills into the next channel.
- `DebugBook`: the drawings still due, each with the stage it was drawn on and the moment it expires.
  `add(segments, rgba, stage, now, duration)`; `expire(now) -> bool` and `keep_stage(stage) -> bool`, each true when
  a drawing went; `lines()` (starts, ends, colours of all left); `empty`.
- `LINE_WIDTH_PX = 2.0`, the width every line is drawn with.

**Kit, a new `handlers/debug_draw.py`** (`handle_draw_debug` moves out of `misc.py`; the route and the name stay):

- **Backend:** `choose_backend(names=BACKENDS)` takes the first of `isaacsim.util.debug_draw` (Isaac Sim 5.x, 6.x)
  and `omni.debugdraw` (other Kit apps that ship it) that `enable_extension` gives, else an error naming both. Only a
  backend found is kept; a failure is tried again on the next call, so enabling an extension by hand later works.
  The live suite calls it through `execute` to run the `omni.debugdraw` backend on Isaac Sim, then again to restore
  the default; a change of backend clears ours (as below) and empties the book.
- **`isaacsim.util.debug_draw` keeps lines (F1, F2):** the handler draws at once; when one of ours goes, the bridge
  calls `clear_lines()` and draws again the ones left. Its clear is global (F3), so lines other code drew with it go
  too; points are never touched, since ours are all lines.
- **`omni.debugdraw` forgets each frame (F4):** the live segments are drawn again on every update, as one
  `draw_lines(lines_list)` call, its `SimplexPoint` list built when the book changes.
- **One update subscription** (`get_update_event_stream().create_subscription_to_pop`, as recording uses) runs
  while the book holds anything or a clear is owed, `now` from `time.monotonic()`: `duration` is real seconds from
  the call, whether the simulation plays or not. Each update it calls `keep_stage(get_stage_id())` (F15), then
  `expire(now)`; either dropping a drawing owes a clear and a redraw. It is dropped once the book is empty and no
  clear is owed.
- **A new stage forgets the old one's drawings (F18):** each drawing carries the id of the stage it was drawn on;
  one from another stage is dropped, never redrawn. The clear that follows also clears an extension that keeps
  drawings across a stage change, as 3.1.0 on Isaac Sim 5.x may.
- **No clear while the stage changes (F3):** an owed clear waits for the first update on which `get_stage_state()`
  is `OPENED` (F15), then runs with its redraw; none at shutdown, where `on_shutdown` only drops the subscription and
  the book.
- **Answer:** `drawn` as today, plus `backend` and `duration`. The tool says
  `Drew 1 debug element(s): line, for 5.0 s (isaacsim.util.debug_draw)`, and reads both with defaults, so a 0.2.0
  bridge's answer still reads.

### `apply_force` (PR 2)

**Kit-free, `ovmcp/core/force.py`:**

- `force_args(body)`: `prim_path`; `force` and an optional `position`, three finite numbers each; `impulse`. The
  PhysX mode, `Impulse` or `Force` (F8).
- `world_point(position, rotation_xyzw, local)`: a body-frame point in world space, from the pose PhysX reports (F9).

**Kit, `handlers/simulation.py`:**

- **Refused when PhysX won't move the body,** on every call, before anything is applied:
  - the timeline is stopped: PhysX has no bodies then. Paused is accepted (Decisions, Q4);
  - `physics:kinematicEnabled` is true: PhysX takes the force and nothing moves (F16);
  - `get_rigidbody_transformation(path)["ret_val"]` is false: PhysX holds no such body (F9). `test_15_11` checks an
    articulation link passes this; if it doesn't, this check goes and the two above stay.
- **The call PhysX has (F8, F10):** `get_physx_simulation_interface().apply_force_at_pos(stage_id, body_id, force,
  point, mode)`, with `stage_id` from `omni.usd.get_context().get_stage_id()` (F15).
- **The point:** `position` when given. Otherwise the centre of mass: `get_mass_information(path)["com"]` (F11),
  synchronous, with no callback for Kit to run on another thread, put in world space with `world_point` and the
  pose from `get_rigidbody_transformation`. Physics is parsed, since a stopped timeline is refused. A mass of 0, or
  no `com`, is an error, as NVIDIA's own tool reads it (F11). It sits on PhysX's unit-tests interface (R8).
- **No velocity fallback:** a PhysX failure is an error result (Decisions, Q1).
- **`impulse` says what PhysX does:** `test_15_06` measures a 10 N force on a 5 kg body. PhysX's `Force` mode is
  expected to push for one physics step (F17), giving `force * dt / mass`; the descriptions of `impulse` and
  `force`, in the tool and in TOOLS.md, then say "an impulse in N s, or a force in N for one physics step: call it
  each step to hold a push", and never "continuous". If the measurement shows a held force, they say that instead,
  and the test asserts whichever the description says.
- **Answer:** `position` is the point used, `at` is `given` or `centre of mass`, `method` is `physx`. The tool says
  `Applied impulse [10, 0, 0] to /World/Cube at [0.0, 0.0, 2.0] (centre of mass)`.

### `start_recording` (PR 3)

**Kit-free, `ovmcp/core/recording.py`:**

- `recording_args(body)`: `output_dir` required; `fps` a whole number of at least 1; `width` and `height` whole
  numbers from 1 to 4096 each, with at most `MAX_PIXELS = 1920 * 1080` in a frame, refused above. The contract keeps
  only `minimum: 1`; the bridge refuses. Then `camera_path`, `track_prims`, `property_filter`. A `ValueError` says
  what is wrong, as `inspect_args` does.
- `steps_per_frame(sim_fps, fps)`, as today's inline `max(1, int(sim_fps / fps))`.
- `whole_frame(shape, width, height)`: whether an annotator's buffer is a frame of the asked size, (height, width, 4).
- `camera_error(stage, path)`: why `path` can't be recorded from (no prim there, or not a `UsdGeom.Camera`), or
  None. usd-core runs it in the tests.
- Frames go through `png.encode_png` as they are; it drops alpha.

**Kit, `handlers/recording.py`:**

- **The camera:** `camera_path`, or the active viewport's camera when empty, checked with `camera_error` before
  anything is made.
- **A render product of its own (F12, F13):** `enable_extension("omni.replicator.core")`; the timeline's
  `get_play_every_frame()` read and kept (F20); then `rep.create.render_product(camera, (width, height),
  force_new=True)` and an `rgb` annotator attached to it. `force_new`, so stopping never destroys a render product
  someone else holds.
- **The check frame:** with the timeline stopped, Replicator renders no frame on its own (F19). So `start` takes one
  with `step_async(delta_time=0.0, pause_timeline=False)` (F14), bounded by `asyncio.wait_for` at
  `CAPTURE_TIMEOUT_SECONDS` (10 s), the bound captures already use, and checks it with `whole_frame`. It proves the
  camera renders; it is not a recorded frame. No whole frame is an error: "the camera gave no frame in 10 s".
- **A failed start leaves nothing:** any error after the render product exists (the attach raises, the step times
  out, or the frame isn't whole) detaches the annotator, destroys the render product, puts play-every-frame back,
  then answers the error.
- **Frames while the simulation plays,** as the tool's own description has always said ("Captures a screenshot
  every 1/fps seconds while the simulation is playing"): `_on_update` counts only updates on which the timeline
  plays, and every `steps_per_frame`-th of them takes a frame.
  - **Capture-on-play on** (Replicator's default, read from `/omni/replicator/captureOnPlay`): the annotator gets a
    frame on each playing update (F19), read in `_on_update` itself with `get_data(do_array_copy=True)` (F12). The
    image and `sim_time` then come from the same update.
  - **Capture-on-play off, or frames that repeat (R4):** each frame is one `step_async(delta_time=0.0,
    pause_timeline=False)` (F14), bounded at 10 s like the check, in a task of its own; a tick while one is still
    running is skipped.
  - **A read that isn't a whole frame** (the first playing updates, before the gate passes) is skipped and not
    numbered, so every `frame_NNNNN.png` is whole and frame 0 is the first real one; each frame's `sim_time` in
    `metadata.json` shows any gap. The viewport fallback keeps today's empty file for a frame that didn't arrive.
  - Prim state is written for each frame taken, as today.
- **Encoding off the main thread:** the copied buffer goes to `loop.run_in_executor` for `encode_png` and the write.
  It is not USD work (`AGENTS.md`, Traps), and `zlib` releases the GIL; the main thread only copies the buffer. At
  most two frames are in flight; a tick past that is skipped. `stop_recording` awaits them before it writes
  `metadata.json`. The pixel cap bounds VRAM and a frame's encode, about 0.1 s for 1920x1080 at `zlib`'s level 6.
- **Stop, a forced restart and `on_shutdown`** detach the annotator, destroy the render product and put
  play-every-frame back as it was, each in its own `try`: a new stage may already have taken the render product.
- **Without Replicator** (an app that lacks `omni.replicator.core`): today's path, the active viewport at its own
  size, and the answer says so (`note`), so the tool shows a `WARNING` line rather than ignoring the values silently
  (Decisions, Q3).
- **Answer and `metadata.json`:** `resolution` and `camera_path` are what the frames really are; new `source`
  (`camera` or `viewport`), `note`, and `render_product`, the prim path it made (F13). The tool reads a missing
  `source` as `viewport`, so a 0.2.0 bridge, whose frames do come from the viewport, gets the `WARNING` too. It says
  `Recording rec_1 at 5fps, 640x480 from /OmniverseKit_Persp -> ...`.

### Alternatives

| Alternative | Why not |
|---|---|
| Drop the ignored parameters, as #25 allows | A Breaking contract change, and each has an API that does what it says |
| Keep `omni.debugdraw` first and only enable it | It draws for one frame (F4), so `duration` means redrawing from Python every update, and it is deprecated since Kit 106; it stays as the fallback |
| Draw with USD prims (`BasisCurves`) | Stage content: saved with the scene, seen by segmentation and bounding boxes, undone by `new_scene` |
| Draw with `omni.ui.scene`, `omni.debugdraw`'s named successor (F4) | Needs a viewport window's UI, which the headless app has none of |
| A timer per drawing that calls `clear_lines()` | The clear is global (F3): it takes drawings still due to show |
| The centre of mass from `IPhysxPropertyQuery.query_prim` | It answers through Python callbacks, which Kit calls from another thread when a mesh still cooks, and waits forever by default: #5's deadlock shape, a GIL held on the main thread while a worker waits for it |
| The centre of mass from a PhysX tensor view (`apply_forces_and_torques_at_position` without a position) | Needs a simulation view made mid-play for one call |
| Point the active viewport at the camera and size for each frame | Moves the user's viewport, races `capture_viewport` and `inspect_prim` for it (`_viewport` lock), and resets the renderer's accumulation every frame |
| Record while stopped or paused too, a step per frame | Nothing moves then, so the frames repeat; the tool's description has always said "while the simulation is playing" |
| A step for every frame, playing or not (F14) | With capture-on-play on, Replicator already runs on PLAY, and a step also triggers every writer anyone attached; kept for capture-on-play off and for R4 |
| Turn capture-on-play off for the recording, so no capture settings change (F20) | A global Replicator setting other users' writers rely on; a step applies the same settings anyway |
| Encode on the main thread at `zlib` level 1 | Still tens of milliseconds a frame at 1080p on Kit's main thread, and larger files |
| One PR for all three tools | Recording carries the open risks (R4, R5); it would hold back `draw_debug`, which the scenario suite fails on today |

### Decisions for the maintainer

Owner calls, answered by the maintainer before approval.

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Keep `apply_force`'s velocity fallback? | Drop it: it ignores mass and point, and the PhysX call works on Kit 107.3 and 110.3 (F8). A failure becomes an error. | As recommended (the maintainer, 2026-10-29) |
| Q2 | Keep `omni.debugdraw` as the fallback for Kit apps without `isaacsim.util.debug_draw`, such as USD Composer? | Keep it: small, and unit-tested in its pure parts. It runs live on Isaac Sim through `choose_backend` if its lines reach a headless capture (`test_16_09`, R1). | As recommended (the maintainer, 2026-10-29) |
| Q3 | Without `omni.replicator.core`: record from the viewport with a warning, or refuse? | The viewport, with the warning: a refusal would break the default call on such an app. | As recommended (the maintainer, 2026-10-29) |
| Q4 | Refuse `apply_force` while the timeline is stopped? | Yes; paused is accepted. A kinematic body, or one PhysX doesn't hold, is refused too (Design). | As recommended (the maintainer, 2026-10-29) |
| Q5 | Take the centre of mass from PhysX's unit-tests interface (`get_mass_information`)? | Yes: synchronous and exact, and NVIDIA's own debug view uses it. The live suite catches it changing (R8). | As recommended (the maintainer, 2026-10-29) |
| Q6 | `capture_viewport` and `inspect_prim` also ignore `width` and `height`: the image comes at the viewport's size, while `screen_bbox` is scaled to the size asked for, so boxes and image disagree | A new issue, outside this plan; it can reuse PR 3's render product | As recommended (the maintainer, 2026-10-29) |
| Q7 | Three PRs from one plan, as above? | Yes: each tool lands when its live run passes; the plan keeps a progress log, as `docs/plans/README.md` asks of a plan that spans several PRs | As recommended (the maintainer, 2026-10-29) |

The maintainer approved the plan on 2026-10-29, with one change of scope. Round 3 left two majors open in the
recording's design (P16, a recording started while playing repeats its check frame; P17, a cancelled Replicator step
leaves the timeline frozen), so the recording's camera and size move to a later release, with their own review
round. For 0.2.1, PR 3 is only this: `start_recording` says it records the active viewport, at its own size, and
warns when it is given a `camera_path`, `width` or `height`; #25 stays open for the rest. Q3 waits with it. PR 1
(`draw_debug`) and PR 2 (`apply_force`) go as designed.

## Compatibility

No one-way door moves.

| Door | Effect |
|---|---|
| Tool names, parameters, types, defaults, bounds, hints | None. Only descriptions change, which `tools/golden.py` strips: `tests/fixtures/mcp-tools.json` stays as it is. The bridge's cap on `width` and `height` is a refusal, not a schema bound. |
| Wire protocol | Paths, request bodies and the token are unchanged. Answers gain fields (`backend`, `duration`, `at`, `source`, `note`, `render_product`); `PROTOCOL` stays 1. |
| The extension's id and settings | Unchanged; `extension.toml` keeps its one optional dependency. |
| The output folder's layout | The same files in a recording's folder; `metadata.json` gains `source`. |

What users notice:

| Before | After |
|---|---|
| `draw_debug` failed headless; in the GUI a drawing lasted a frame | It draws, for `duration` seconds; when a drawing expires, other lines drawn with `isaacsim.util.debug_draw` go too |
| `apply_force` nudged `physics:velocity` by `force / 100`, or `force` for an impulse, and reported success for any body | PhysX applies the force or impulse, so mass counts, at `position` or the centre of mass; an error while stopped, or for a kinematic body |
| Frames at the viewport's size, from its camera, on every tick whether the simulation played or not | 640x480 by default, from `camera_path` or the active camera, while it plays; a frame above 1920x1080 is refused. While a recording runs, Replicator's capture settings apply (F20): grid, outlines and gizmos hidden, eco mode off, the selection cleared, the timeline stepped once per frame; play-every-frame is put back at stop |

- **Mixed releases:** the fixes live in the extension, so they need `uvx omniverse-mcp extension install` and a Kit
  restart, as `get_sim_state`'s `note` says. A new server reads a 0.2.0 bridge's answers, since the new fields are
  read with defaults; a 0.2.0 server reads the new answers, which only add fields.
- **Kit apps:** Isaac Sim 5.x and 6.x draw with `isaacsim.util.debug_draw` and record through Replicator. Other
  Kit 107+ apps draw with `omni.debugdraw` when they ship it, and record from the viewport without Replicator.

## Steps

Each step builds and passes `uv run tools/gate.py quick` on its own; each PR ends with `finish-work`: gate full, the
live suites on Isaac Sim 6.2 (and 5.1, installed here), `review-code`, and this plan's progress log. The live runs
wait until #5's fix is on `main`, and each branch is rebased onto it first (R11).

| Step | PR | What | Proven by |
|---|---|---|---|
| 1 | 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | 1 | `core/extensions.py`, `enable_extension` in `_utils.py`; `core/debug_draw.py` | `tests/test_extensions.py`, `tests/test_debug_draw.py` |
| 3 | 1 | `handlers/debug_draw.py`, the route's import, `on_shutdown`; `draw_debug`'s description and text; its docs | `tests/test_tools.py`; live: `test_16_03` to `test_16_09`, `test_17_03` |
| 4 | 2 | `core/force.py`; `handle_apply_force` through `IPhysxSimulation`, its refusals; `apply_force`'s descriptions, `impulse`'s from the measurement; its docs | `tests/test_force.py`, `tests/test_tools.py`; live: `test_15_04`, `test_15_06` to `test_15_11` |
| 5 | 3 | `core/recording.py`; the render product in `handlers/recording.py`, `on_shutdown`; `start_recording`'s descriptions and text; its docs | `tests/test_recording.py`, `tests/test_tools.py`; live: `test_06_01`, `test_06_03` to `test_06_06` |

## Tests

New behaviour gets a test that fails without it: Kit-free logic in `ovmcp/core/` under CI, the Kit calls in the live
suites.

**Unit (CI):**

| File | PR | What it checks |
|---|---|---|
| `tests/test_extensions.py` (new) | 1 | `extension_step` for enabled, listed and absent |
| `tests/test_debug_draw.py` (new) | 1 | The segments of each shape; each error; colours clamped, packed without spilling a channel; the book with a fake clock: two durations, one expiring, then none, `expire` true only when something went; `keep_stage` drops another stage's drawings and keeps this one's |
| `tests/test_force.py` (new) | 2 | `force_args`; the mode for each `impulse`; `world_point` with no rotation, a translation, and 90 degrees about Z and about Y (PhysX's x, y, z, w order) |
| `tests/test_recording.py` (new) | 3 | `recording_args` takes and refuses what it should: 4096 a side taken and 4097 refused, 1920x1080 taken and 1920x1081 refused; `steps_per_frame`; `whole_frame` for a frame, an empty buffer and another size; `camera_error` on a usd-core stage (nothing there, an Xform, a Camera) |
| `tests/test_tools.py` | 1-3 | Each tool's case gains the new fields and their text. Beside the table, which holds one case per tool, tests of their own as `test_manage_extensions_enables_one` is: a 0.2.0-shaped answer for each tool still reads, and `start_recording`'s answer without `source` gives the `WARNING` line |
| `tests/test_contract.py` | 1-3 | Unchanged and passing: the golden file doesn't move |

**Live (by hand, `OMNIVERSE_MCP_SIM=1`):** the main session runs them; this plan sets none of it up. All in
`test_scenarios.py`, placing things with `_up_axis()` and `_along_up()` (#49), since Isaac Sim opens a Z-up stage and
17.2's `new_scene` leaves a Y-up one. Each test leaves the stage and the bridge as it found them: drawings expired
(it waits until `get_num_lines()` is back to its start count), its own bodies deleted and the backend restored, in
`addCleanup`.

| Test | PR | It must show |
|---|---|---|
| `test_16_03` to `test_16_05` | 1 | Pass headless; `backend` is `isaacsim.util.debug_draw` |
| `test_16_06_draw_debug_expires` (new) | 1 | `get_num_lines()` (through `execute`) rises by the line's segments, and falls back once `duration` (1 s) has passed |
| `test_16_07_draw_debug_twice` (new) | 1 | A 1 s drawing expiring leaves a 3 s one showing: the redraw after the global clear. It waits for both to go before it ends. |
| `test_16_08_draw_debug_reaches_a_capture` (new) | 1 | After `get_num_lines()` is back to its start count, with the camera aimed away from `/World/RedCube` (red since `test_02_01`): strongly red pixels (red above green and blue by 80), counted in Kit with numpy, about none in a capture of that view, hundreds once a 2-pixel red `lines` zigzag crosses it |
| `test_16_09_draw_debug_with_omni_debugdraw` (new) | 1 | With `choose_backend(("omni.debugdraw",))` through `execute`, restored by `choose_backend()` in `addCleanup`: `backend` is `omni.debugdraw`, and a capture holds the red pixels while `duration` lasts and not after. `IDebugDraw` has no line count, so the capture is the only check (R1). |
| `test_17_03_draw_debug_forgets_the_old_stage` (new) | 1 | A 30 s drawing, then `new_scene`, then a 1 s one: the line count is the second's alone, and back to the start once it expires |
| `test_15_04` (changed) | 2 | `method` is `physx` |
| `test_15_06_impulse_and_force_by_mass` (new) | 2 | On the 5 kg cube in the air, from PhysX's pose over sim time: an impulse of 10 N s gives about 2 m/s along X, within 25%; a 10 N force gives what `impulse`'s description says, `10 * dt / 5` for one step (dt from the physics scene, 1/60 s by default), within 50% |
| `test_15_07_force_at_a_point_spins` (new) | 2 | Without `position` the cube doesn't turn (under 2 degrees); with a point above its centre along the up axis it does (over 5) |
| `test_15_08_centre_of_mass_off_origin` (new) | 2 | On a body of its own, deleted after, with `MassAPI.centerOfMass` authored off centre: an impulse without `position` doesn't turn it, where one at its origin would; `at` is `centre of mass` |
| `test_15_09_apply_force_while_stopped` (new) | 2 | An error |
| `test_15_10_apply_force_to_a_kinematic_body` (new) | 2 | On a kinematic body of its own, deleted after: an error |
| `test_15_11_apply_force_to_a_robot_link` (new) | 2 | On a link of the G1 the scenario loads, while it plays: success, `at` is `centre of mass` (`ret_val` and `get_mass_information` work for an articulation link) |
| `test_06_01` (changed) | 3 | Started while stopped, then played: frame 0 is a whole 320x240 PNG, from its IHDR; `metadata.json` says 320x240 |
| `test_06_03_record_from_a_camera` (new) | 3 | With the viewport turned away, frames from `/World/RecCam`, aimed at the red cube, are mostly red, and differ as the cube falls (R4); the viewport's camera is unchanged after |
| `test_06_04_recording_makes_and_destroys_its_render_product` (new) | 3 | The prim `render_product` names exists while recording and is gone after `stop_recording`; on `main` there is no such prim, so the test fails there |
| `test_06_05_record_from_a_prim_that_isnt_a_camera` (new) | 3 | An error, and no render product left under `/Render` |
| `test_06_06_recording_puts_play_every_frame_back` (new) | 3 | `get_play_every_frame()` is the same after `stop_recording` as before `start_recording` |
| Both suites in full | 1-3 | No failures beyond `main`'s on the same Kit |

**What neither can show:** the recording's viewport fallback, since every Kit app at hand has Replicator; a start
that fails after its render product exists (the cleanup is read in review); a person watching the drawings come and
go in a GUI viewport (the live run is headless, and counts lines and pixels instead).

## Docs

Each PR moves the docs for its tool.

- `docs/TOOLS.md`: `draw_debug`'s `duration` in real seconds, the backends, the global clear, the 2-pixel lines,
  and whether drawings reach a capture (R1) (PR 1); `apply_force`'s `position`, `impulse` as measured, the refusals,
  what `method` and the point mean (PR 2); `start_recording`'s `width`, `height` (4096 a side, 1920x1080 a frame)
  and `camera_path`, frames only while the simulation plays, Replicator's capture settings while a recording runs
  (F20), and the fallback (PR 3).
- `docs/ARCHITECTURE.md`: the core list gains `extensions.py` and `debug_draw.py` (PR 1), `force.py` (PR 2),
  `recording.py` (PR 3); the handlers list gains `debug_draw` (PR 1); Recording System describes the render product,
  the check frame, frames while playing and the encoding off the main thread (PR 3); Extension Lifecycle's shutdown
  drops the drawing subscription (PR 1) and the render product (PR 3).
- `CHANGELOG.md`, Unreleased, Fixed, with the line that the fixes come with `extension install`:
  - PR 1: `draw_debug` works headless, on every Isaac Sim: it used `omni.debugdraw`, which only the GUI app turns
    on; and a drawing stays `duration` seconds, where it lasted a frame (#7, #25);
  - PR 2: `apply_force` goes through PhysX, so mass counts, at the point or the centre of mass; refused while
    stopped and for a kinematic body; `impulse` described as it acts (#25);
  - PR 3: `start_recording` records from its camera at its size, while the simulation plays (#25).
- `README.md`, Known issues: the #7 line goes (PR 1); the #25 line loses `apply_force` (PR 2), then goes (PR 3).
- `docs/SETUP.md`: the troubleshooting row for #7 goes (PR 1).
- `plugin/skills/simulate/SKILL.md`, by `write-skill`'s rules: the #7 trap row (PR 1); step 4's "at the world origin
  unless a `position` is given" (PR 2); step 5's "Frames keep the viewport's size and camera for now" (PR 3).
- `.claude/skills/finish-work/SKILL.md`: the Traps row's "(#5, #6, #7)" loses #7 (PR 1).
- `AGENTS.md`: the extension's row names the new core modules: extensions and debug drawing (PR 1), forces (PR 2),
  recording (PR 3). It stays within the gate's 150 lines (146 now).
- `test_project/scenarios.md`: phases 16 and 17 (PR 1), 15 (PR 2) and 6 (PR 3) gain the new checks.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | Drawings may not reach a headless `capture_viewport`: the 6.0 docs say `isaacsim.util.debug_draw`'s geometry "cannot be rendered", while 6.1's own test finds it in a Replicator render product (F5); `omni.debugdraw`'s visual tests capture a UI viewport window (F4). Headless, a capture is the only way to see one. | Open: `test_16_08` and `test_16_09` decide. If `test_16_08` fails, TOOLS.md says drawings show in the viewport only, and the test goes. If `test_16_09` fails, it goes, and Q2 and R10 go back to "unit-tested parts only" for `omni.debugdraw`. Each with the reason in the review record. |
| R2 | The global clear takes lines other code drew with `isaacsim.util.debug_draw` (F3) | Accepted: there is no per-line clear; TOOLS.md says so |
| R3 | A clear while the stage tears down crashes Kit before 3.2.8 (F3) | Guarded: an owed clear waits for the first `OPENED` update; none at shutdown |
| R4 | Replicator renders no frame on its own while stopped (F19, measured), and its streamed frames while playing may repeat or lag | Resolved for stopped: the check frame is a bounded step, and frames are taken only while playing. Open for playing: `test_06_01` checks frame 0 is whole and `test_06_03` that frames of a falling cube differ; if they repeat, the stepped path takes every frame, and PR 3 updates this plan. |
| R5 | A render product renders every frame while recording: GPU time and VRAM, and frames may trail `sim_time` by a render or two | Accepted: capped at 1920x1080, destroyed at stop; trailing measured in `test_06_03` |
| R6 | Enabling Replicator or a drawing extension at runtime makes the first call slow. With an annotator attached, PLAY and every step apply Replicator's capture settings (F20): grid, outlines, light and camera gizmos and collider display off, eco mode and async rendering off, the selection cleared, play-every-frame on, which steps the timeline once per update instead of by the clock. Replicator puts back all but play-every-frame. | Accepted, and said in TOOLS.md: seconds for the first call, under the client's 120 s timeout; the bridge reads play-every-frame before it attaches and puts it back at stop, at a failed start and at shutdown (`test_06_06`) |
| R7 | PNG encoding and writing slow the simulation at a high `fps` | Resolved: both run off the main thread, at most two frames in flight; the main thread copies the buffer. The live run notes the frame rate at 30 fps and 1920x1080 |
| R8 | `get_mass_information` sits on PhysX's unit-tests interface, which NVIDIA may change or drop without notice | Accepted (Q5): `test_15_08` catches a change at each Kit release; an interface that's gone is an error, never a wrong point |
| R9 | PhysX's `Force` mode may last one step (F17), so a force is `force * dt` of push | In scope: `test_15_06` measures it, and `impulse`'s description says what it shows |
| R10 | The recording's viewport fallback never runs live | Accepted (Q3): it is today's path, unchanged |
| R11 | #5: Kit's main thread can hold the GIL while waiting on a worker that waits for the GIL to call the bridge's `omni.log` consumer. Enabling an extension, `rep.create.render_product` and a step run on the main thread and can wait on workers that log. | Sequenced: the live runs wait for #5's fix (the consumer dropped) on `main`, and nothing here adds a Python callback Kit may call from a worker thread; the encoding thread is the bridge's own and waits on nothing of Kit's |

## Plan review

### Round 1

**How:** `review-plan`, a fresh reviewer on Claude Opus 5.5 (`claude-opus-5-5`), 2026-10-29, on `f8d5414`.
**Verdict:** `needs-fixes`: one major, eight minors. **Now:** all nine fixed in `3b1663b`.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | `apply_force`'s centre of mass from `query_prim`: Python callbacks Kit calls from another thread while a mesh cooks, waiting forever by default, #5's deadlock shape | fixed: `get_mass_information` (F11), synchronous; the wait, the origin fallback and `at = "body origin"` gone; Q5 and R8 rewritten; the property query in Alternatives |
| P2 | minor | `omni.debugdraw` ships in 6.2; `draw_debug` fails headless on any version, since only the GUI app enables it, through `omni.physx.bundle` and `omni.physx.ui` | fixed: Root causes, F4, F7, Q2, the title, the Goal and the CHANGELOG line; `test_16_09` runs the `omni.debugdraw` backend through `choose_backend` |
| P3 | minor | The book outlives a stage change, so a redraw after `new_scene` puts the old stage's lines on the new one | fixed: drawings carry their stage's id, `keep_stage` drops the others (F18); `test_17_03` and a unit test |
| P4 | minor | PhysX's `Force` mode most likely lasts one step (F17); `impulse` must not say "continuous force" | fixed: in scope; `test_15_06` measures it and the descriptions say what it shows |
| P5 | minor | A kinematic body takes the force and doesn't move, reported as success (F16) | fixed: refused, as is a body PhysX doesn't hold (`ret_val` false), on every call; `test_15_10` |
| P6 | minor | A start that fails after making the render product leaves it behind; no frame in 60 updates unstated | fixed: any start error destroys what start made; the wait bounded at 10 s, its end an error (round 2, P10, changes how that frame is taken) |
| P7 | minor | `width` and `height` now size a render product, with only `minimum: 1` in the contract | fixed: the bridge refuses above a cap (round 2, P12, sets it) |
| P8 | minor | `test_06_04` passes on `main`, which never makes a render product | fixed: it checks the prim the answer names exists while recording, then is gone |
| P9 | minor | "#6's tests assume Y-up" is stale since #49 | fixed: the new tests use `_up_axis()` and `_along_up()`; `test_31` moved to `test_16_08` in `test_scenarios.py` |

**Refuted:** none recorded by this round.

**Owner calls:** Q1-Q7, in Design, Decisions for the maintainer; unanswered.

| Improvement | Answer |
|---|---|
| Drop `frame_png`: `encode_png` already gives `b""` for a non-image | taken |
| Read a missing `source` as `viewport`, so a 0.2.0 bridge gets the `WARNING` | taken |
| `get_stage_id()` over the StageCache lookup | taken (F15) |
| `enable_extension`'s decision in core, with a unit test | taken: `core/extensions.py` |
| Sequence after #5's fix, or name #5 in Risks | taken, both (R11, Steps) |
| Three PRs | taken (Q7) |
| `test_31`'s "thick red line" when every line is 2 px | taken: a zigzag of 2-pixel lines, and a count of strongly red pixels |

### Round 2

**How:** `review-plan`, a fresh reviewer on Claude Opus 5.5 (`claude-opus-5-5`), 2026-10-29, on `3b1663b`; the
main session measured F19 on Isaac Sim 6.2.0. **Verdict:** `needs-fixes`: one major, five minors; round 1's P1-P9
confirmed fixed. **Now:** all six fixed in the commit after `3b1663b`; round 3 follows, since P10 is a major.

| # | Sev | Finding | Status |
|---|---|---|---|
| P10 | major | With the timeline stopped, Replicator gives no frame (F19), so `start_recording` then `sim_control("play")`, the documented workflow, failed with "the camera gave no frame in 10 s"; F13 said "with no orchestrator step" | fixed: the check frame is one bounded `step_async(delta_time=0.0, pause_timeline=False)`; frames are taken only while the simulation plays, streamed with capture-on-play, stepped without it; a read that isn't whole is skipped; F13 corrected, F19 recorded, R4 widened; `test_06_01` asserts a whole 320x240 frame 0 after a start while stopped |
| P11 | minor | Capture-on-play with our annotator applies Replicator's capture settings on PLAY, and its restore never undoes play-every-frame | fixed: F20; the bridge reads `get_play_every_frame()` before attaching and puts it back at stop, failed start and shutdown; R6 and TOOLS.md say what changes while recording; `test_06_06` |
| P12 | minor | 4096 a side is far past R7's 640x480 once frames are PNG-encoded on Kit's main thread | fixed: encoding and writing off the main thread (`run_in_executor`; not USD work, and `zlib` releases the GIL), at most two frames in flight, and a cap of 1920x1080 a frame within 4096 a side; level 1 on the main thread is in Alternatives |
| P13 | minor | Live tests leak into each other: `test_16_07`'s 10 s drawing under `test_16_08`'s baseline, a red view from `/World/RedCube`, `test_16_09`'s backend, `test_15_08`'s and `test_15_10`'s changes to `/World/RedCube` | fixed: each test leaves things as it found them, in `addCleanup`; `test_16_07` uses 1 s and 3 s and waits for both; `test_16_08` waits for the start count and aims away from the red cube; `test_15_08` and `test_15_10` use bodies of their own |
| P14 | minor | `omni.debugdraw` lines may not reach a headless capture, and `IDebugDraw` has no line count | fixed: R1 covers `test_16_09`; if it fails, it goes and Q2 and R10 go back to "unit-tested parts only" |
| P15 | minor | The record lacks the reviewers' model, a Refuted list and the skill's verdict words; Q1-Q7 lack an Answer column; 6.2 is on this machine after all | fixed: both rounds in the skill's form; the Answer column; the API facts re-checked on 6.2 in `D:\isaac\venv` (F3, F4, F7, F11, F13, F14, F20) |

**Refuted:** none.

**Owner calls:** Q1-Q7, unchanged but for Q2's wording (P14); unanswered.

| Improvement | Answer |
|---|---|
| A clear owed when a drawing drops while the stage isn't `OPENED`, done on the first `OPENED` update | taken |
| `choose_backend` keeps only a success | taken |
| `omni.debugdraw`'s `draw_lines(lines_list)` once per update | taken |
| "`physics:kinematicEnabled` is true", not "is set" | taken |
| Bound any `step_async` like the frame-0 wait | taken: every step is bounded at 10 s |
| A live `apply_force` case on a G1 link: does `ret_val` hold for an articulation link? | taken: `test_15_11`; if not, the `ret_val` check goes |

## Progress log

| Date | PR | What |
|---|---|---|
| 2026-10-29 | 1 | Plan drafted; review round 1: `needs-fixes`, all nine findings fixed |
| 2026-10-29 | 1 | Review round 2: `needs-fixes`, all six findings fixed; round 3 to follow |
| 2026-10-29 | 1 | Built steps 2 and 3: `core/extensions.py`, `core/debug_draw.py` (the book's `tick` holds the owed clear), `enable_extension`, `handlers/debug_draw.py`, the tool's text and docs, `test_16_03` to `test_16_09` and `test_17_03`. Two guards beyond Design: no drawing while the stage isn't `OPENED` (F3), and a backend whose extension was turned off since is dropped without a call into it. Gate full passes; the live runs wait for #5's fix (R11) |
| 2026-10-29 | 1 | Live on Isaac Sim 6.2 headless: all 124 live tests passed; R1 resolved for 6.x, drawings reach a capture with either backend. Isaac Sim 5.1 can't start on this machine, so 5.x is untested live. `review-code` round 1: two minors, fixed (`docs/reviews/2026-10-29-draw-debug-code.md`) |
