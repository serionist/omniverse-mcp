---
title: Make draw_debug work on Isaac Sim 6.2, and act on the parameters three tools ignore
issue: "#7, #25"
status: draft
approved_by:
approved_at:
---

# Make draw_debug work on Isaac Sim 6.2, and act on the parameters three tools ignore

Two issues, one branch: both are the bridge not doing what a tool's parameters say, and #25's `draw_debug` row is
only fixable on #7's new drawing extension. All the work is in the extension's handlers and its Kit-free core; the
server changes only descriptions and the text it returns.

## Goal

When this is done, on Isaac Sim 5.x and 6.x:

- **`draw_debug` draws** with `isaacsim.util.debug_draw`, enabled on first use, and each drawing stays `duration`
  seconds, then goes (#7, #25).
- **`start_recording` records from `camera_path`** (the active camera when empty) at `width` x `height` (#25).
- **`apply_force` pushes through PhysX** at `position`, or at the body's centre of mass when it is left out (#25).
- **Scenario tests `test_16_03` to `test_16_05` pass** on Isaac Sim 6.2, and the live suites gain a case for each
  parameter #25 names.

Why: an agent that asks for a 320x240 recording from a camera, a push at a body's centre, or a line for five seconds
gets something else, reported as success. The tool descriptions say "for now (#25)"; this removes the "for now".

| In scope | Out of scope |
|---|---|
| The `/debug/draw`, `/recording/*` and `/physics/apply_force` handlers; Kit-free logic for them in `ovmcp/core/` | `capture_viewport` and `inspect_prim` have the same flaw with `width` and `height` (Decisions, Q6) |
| The three tools' descriptions and answer text | Whether PhysX's `Force` mode lasts one step, against "continuous force" in `impulse`'s description (Risks, R9) |
| Live cases for `duration`, `camera_path`, `width`, `height`, `position` | #35's ten-second wait, which the viewport fallback keeps |
| Docs that name #7 or #25 | `draw_debug`'s `sphere` drawn as three crossing lines, as now |

## Design

### Root causes

| Problem | Where | Cause |
|---|---|---|
| `draw_debug` fails on 6.2 | `handlers/misc.py`, `handle_draw_debug` | It imports `omni.debugdraw`, which 6.2 doesn't ship. On apps that ship it (5.1, 6.1) the import also fails unless something enabled the extension first: nothing does. |
| `duration` ignored | `handlers/misc.py`, `duration = body.get("duration", 5.0)` | Read, never used. And `omni.debugdraw` draws for one frame (API facts, F4): a line drawn once was gone on the next frame even where the import worked. |
| `camera_path`, `width`, `height` ignored | `handlers/recording.py`, `_record_tick` | Every frame is `capture_viewport_png(get_active_viewport())`, the viewport's own camera at its own size. The three values are only stored in `_recording_state`, reported back and written to `metadata.json`. |
| `position` ignored | `handlers/simulation.py`, `handle_apply_force` | Worse than the issue's table: the PhysX call can't succeed. `get_physx_interface()` returns `PhysX`, which has no `apply_force_at_pos` on Kit 107.3 or 110.3 (F9); nor does `omni.physx.scripts.utils`. Every call so far took the `except` path, `method = "velocity"`, which adds `force * 0.01` (`* 1.0` for an impulse) to `physics:velocity`: no mass, no point, no PhysX. The `[0, 0, 0]` default for a missing `position` would put the force at the world origin even if the call worked. |

### API facts this rests on

Looked up for Kit 107 and 110: NVIDIA's docs, NVIDIA's Isaac Sim repo at `release/6.2`, and the extensions as
installed in Isaac Sim 5.0 (Kit 107.3.1), 5.1 (Kit 107.3.3) and 6.1 (Kit 110.3, pip).

| # | Fact | Source |
|---|---|---|
| F1 | `from isaacsim.util.debug_draw import _debug_draw`; `_debug_draw.acquire_debug_draw_interface()`; `draw_lines(start_points, end_points, colors, widths)`, colours RGBA in 0-1, widths in pixels: "All lists must have the same length. Lines persist until cleared." `clear_lines()`: "Clear all drawn lines and splines from the screen." `get_num_lines()` counts them. | Isaac Sim docs, `isaacsim.util.debug_draw` 3.2.8 API page; the same import in 6.1's 3.2.6 (`__init__.py` re-exports `bindings._debug_draw`) |
| F2 | "The 3D geometry drawn by this remains persistent across frames and is only cleared when desired", in contrast to the built-in drawer, which clears itself | Isaac Sim docs, `utilities/debugging/ext_isaacsim_util_debug_draw` |
| F3 | Its clear is global, and clearing while the stage tears down crashes: "debug_draw, whose clear is global"; "clearing the debug_draw overlay while the stage and renderer are tearing down segfaults" | NVIDIA's `isaacsim.robot_setup.virtual_gantry/_runtime.py`, `release/6.2` |
| F4 | `omni.debugdraw` 0.1.4 draws for a frame: its own visual tests call `draw_line` every frame ("Draw for 20 frames") before capturing. Its `extension.toml`: "Extension deprecated since Kit 106.0. omni.debugdraw is being replaced by omni.ui.scene." `IDebugDraw.draw_line(start_pos, start_color: int, start_width, end_pos, end_color: int, end_width)`. Shipped in 5.0, 5.1 and 6.1; not in 6.2 (#7). | `omni.debugdraw-0.1.4` in 5.1 and 6.1: `config/extension.toml`, `_debugDraw.pyi`, `tests/visualtests.py` |
| F5 | `isaacsim.util.debug_draw` depends on `omni.hydra.rtx`, `omni.kit.renderer.core`, `omni.graph`, `omni.usd` and the like: no UI, no `omni.debugdraw`. Its 6.1 test draws, then "Captures rendered debug geometry and compares it against a golden image" through a Replicator render product. (The 6.0 docs say geometry it draws "cannot be rendered"; R1.) | `extension.toml` and `tests/test_debug_draw.py` of 3.1.0 (5.1) and 3.2.6 (6.1); Isaac Sim 6.0 docs, `python_scripting/util_snippets` |
| F6 | Enabling at runtime: Isaac Sim's own `enable_extension` is `omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(name, enabled)`, which returns whether it worked; the bridge's `manage_extensions` already calls the same | `isaacsim.core.experimental.utils/python/impl/app.py`, `release/6.2`; `handlers/misc.py` |
| F7 | 6.1's `isaacsim.exp.base.kit`, which the Python app depends on, lists both `isaacsim.util.debug_draw` and `omni.replicator.core`; on 6.2's headless Python app the first is not enabled (#7) | `apps/isaacsim.exp.base.kit` and `isaacsim.exp.base.python.kit`, 6.1 |
| F8 | `IPhysxSimulation.apply_force_at_pos(stage_id: int, body_path: int, force: Float3, pos: Float3, mode: str = 'Force')`: "pos: World position where the force is applied. mode: Supporting various modes - Force (default), Impulse, Velocity, Acceleration." Same signature on Kit 107.3 and 110.3. | `omni.physx` 107.3.26 (5.1) and 110.3.2 (6.1), `bindings/_physx.pyi` |
| F9 | `PhysX`, what `get_physx_interface()` returns, has no `apply_force_at_pos`; `omni.physx.scripts.utils` has none either. `PhysX.get_rigidbody_transformation(path)` gives `position` and `rotation` "(quat - x,y,z,w)" in global space. | the same `_physx.pyi`; `scripts/ifaces.py`, `scripts/utils.py` |
| F10 | The call as NVIDIA makes it: `stage_id = UsdUtils.StageCache.Get().GetId(stage).ToLongInt()`, `PhysicsSchemaTools.sdfPathToInt(path)`, `get_physx_simulation_interface().apply_force_at_pos(stage_id, rbo_encoded, force, position, "Impulse")` | `omni.physx.tests` 110.3.2, `PhysicsRigidBodyAPI.py`, `test_physics_kinematic_apply_force` |
| F11 | `IPhysxPropertyQuery.query_prim(stage_id, prim_id, query_mode, timeout_ms, finished_fn, rigid_body_fn, ...)` reports a `PhysxPropertyQueryRigidBodyResponse` with `mass` and `center_of_mass: Float3` through a callback; NVIDIA's test awaits one `next_update_async()` before the callback has run, longer when a mesh still cooks | `_physx.pyi`; `omni.physxtests/tests/PhysxPropertyQueryInterface.py` |
| F12 | `rep.create.render_product(camera, resolution, force_new=False, name=None, ...)`: "If an existing render product exists that have the same resolution and camera attached, it is returned"; "Render Products no longer in use should be destroyed." `Annotator.get_data()`: "if calling get_data() immediately after initialization, the annotator output will not yet be available. Please allow for at least one update." | `omni.replicator.core` 1.13.36 (6.1), `scripts/create.py`, `scripts/annotators.py` |
| F13 | Isaac Sim's camera sensor makes `rep.create.render_product(self.prim_path, resolution=...)`, attaches the `rgb` annotator, and `get_rgba()` returns its `get_data()`, an (height, width, 4) array, with no orchestrator step | `isaacsim.sensors.camera` (deprecated in 6.x), `camera.py`; `isaacsim.test.utils/image_capture.py` |
| F14 | `await rep.orchestrator.step_async(delta_time=0.0, pause_timeline=False)` captures without advancing or pausing the timeline | Isaac Sim docs, Replicator snippets ("Capture data at specific simulation timepoints") |
| F15 | `UsdContext.get_stage_state()` returns `StageState`: `CLOSED`, `OPENING`, `OPENED`, `CLOSING` | `omni.usd` 1.18.0 (6.1), `_usd.pyi` |

### Shared: enabling an extension

`handlers/_utils.py` gains `enable_extension(name) -> bool`: true when it is enabled already, or when it is known
locally (`get_extensions()` lists it) and `set_extension_enabled_immediate(name, True)` takes (F6). An app that lacks
it is answered false without a registry fetch or an error in Kit's log. `draw_debug` and `start_recording` use it.

### `draw_debug`

**Kit-free, `ovmcp/core/debug_draw.py`:**

- `segments(shape, body)`: each shape as line segments, as the handler draws them today: `line` one, `lines` one
  per pair of neighbours, `sphere` three crossing lines, `points` a cross of half-length `size` per point, `point`
  one cross (kept for direct callers). A `ValueError` with today's messages for a missing part, and new ones for a
  vector that isn't three finite numbers and for an unknown shape, which today draws nothing and reports success.
- `rgba(color)`: three numbers clamped to 0-1, alpha 1, red when omitted. `argb(color)` packs the same clamped
  values for `omni.debugdraw`; today `int(r * 255)` with `r` above 1 spills into the next channel.
- `DebugBook`: the drawings still showing, each with the moment it expires. `add(segments, rgba, now, duration)`,
  `expire(now) -> bool` (whether any went), `lines()` (starts, ends, colours of all left), `empty`.
- `LINE_WIDTH_PX = 2.0`, the width every line is drawn with.

**Kit, a new `handlers/debug_draw.py`** (`handle_draw_debug` moves out of `misc.py`; the route and the name stay):

- **Backend, chosen once:** `isaacsim.util.debug_draw` when `enable_extension` gives it (Isaac Sim 5.x, 6.x), else
  `omni.debugdraw` (Kit 107 to 110 apps without Isaac Sim's), else an error naming both.
- **`isaacsim.util.debug_draw` keeps lines (F1, F2):** the handler draws at once; when one of ours expires, the
  bridge calls `clear_lines()` and draws again the ones left. Its clear is global (F3), so lines other code drew
  with it go too; points are never touched, since ours are all lines.
- **`omni.debugdraw` forgets each frame (F4):** every live segment is drawn again on every update.
- **One update subscription** (`get_update_event_stream().create_subscription_to_pop`, as recording uses) runs
  while the book holds anything, `now` from `time.monotonic()`: `duration` is real seconds from the call, whether
  the simulation plays or not. It is dropped when the book empties, after the last clear.
- **No clear while the stage changes (F3):** a clear waits for `get_stage_state()` to be `OPENED` (F15); none at
  shutdown, where `on_shutdown` only drops the subscription and the book.
- **Answer:** `drawn` as today, plus `backend` and `duration`. The tool says
  `Drew 1 debug element(s): line, for 5.0 s (isaacsim.util.debug_draw)`, and reads both with defaults, so a 0.2.0
  bridge's answer still reads.

### `start_recording`

**Kit-free, `ovmcp/core/recording.py`:**

- `recording_args(body)`: `output_dir` required; `fps`, `width`, `height` whole numbers of at least 1;
  `camera_path`, `track_prims`, `property_filter`. A `ValueError` says what is wrong, as `inspect_args` does.
- `steps_per_frame(sim_fps, fps)`, as today's inline `max(1, int(sim_fps / fps))`.
- `camera_error(stage, path)`: why `path` can't be recorded from (no prim there, or not a `UsdGeom.Camera`), or
  None. usd-core runs it in the tests.
- `frame_png(rgba)`: an annotator's (height, width, 4) array as PNG bytes through `png.encode_png`; `b""` for an
  empty buffer, the empty file today's code already writes for a frame that didn't arrive.

**Kit, `handlers/recording.py`:**

- **The camera:** `camera_path`, or the active viewport's camera when empty, checked with `camera_error` before
  anything is made.
- **A render product of its own (F12, F13):** `enable_extension("omni.replicator.core")`, then
  `rep.create.render_product(camera, (width, height), force_new=True)` and an `rgb` annotator attached to it.
  `force_new`, so stopping never destroys a render product someone else holds. `start` awaits updates, at most 60,
  until the annotator has a frame, so frame 0 isn't empty (F12).
- **Each frame** is read in `_on_update` itself, with no task: `get_data()`, `frame_png`, written as
  `frame_NNNNN.png`. The image and `sim_time` then come from the same update. Prim state is written as today.
- **Stop, a forced restart and `on_shutdown`** detach the annotator and destroy the render product, each in its own
  `try`: a new stage may already have taken it.
- **Without Replicator** (an app that lacks `omni.replicator.core`): today's path, the active viewport at its own
  size, and the answer says so (`note`), so the tool shows a `WARNING` line rather than ignoring the values silently
  (Decisions, Q3).
- **Answer and `metadata.json`:** `resolution` and `camera_path` are what the frames really are; new `source`
  (`camera` or `viewport`) and `note`. The tool says
  `Recording rec_1 at 5fps, 640x480 from /OmniverseKit_Persp -> ...`.

### `apply_force`

**Kit-free, `ovmcp/core/force.py`:**

- `force_args(body)`: `prim_path`; `force` and an optional `position`, three finite numbers each; `impulse`. The
  PhysX mode, `Impulse` or `Force` (F8).
- `world_point(position, rotation_xyzw, local)`: a body-frame point in world space, from the pose PhysX reports (F9).

**Kit, `handlers/simulation.py`:**

- **Refused while the timeline is stopped:** PhysX has no bodies then, and the force would vanish. The tool already
  says "Sim must be playing"; paused is accepted (Decisions, Q4).
- **The call PhysX has (F8, F10):** `get_physx_simulation_interface().apply_force_at_pos(stage_id, body_id, force,
  point, mode)`.
- **The point:** `position` when given. Otherwise the centre of mass: `query_prim` for the body's local
  `center_of_mass` (F11), awaited for at most 30 updates, then `world_point` with `get_rigidbody_transformation`
  (F9). If the query gives nothing in time, the body's world position, and the answer says which (Decisions, Q5).
- **No velocity fallback:** a PhysX failure is an error result (Decisions, Q1).
- **Answer:** `position` is the point used, `at` is `given`, `centre of mass` or `body origin`, `method` is
  `physx`. The tool says `Applied impulse [10, 0, 0] to /World/Cube at [0.0, 0.0, 2.0] (centre of mass)`.

### Alternatives

| Alternative | Why not |
|---|---|
| Drop the ignored parameters, as #25 allows | A Breaking contract change, and each has an API that does what it says |
| Draw with USD prims (`BasisCurves`) | Stage content: saved with the scene, seen by segmentation and bounding boxes, undone by `new_scene` |
| Draw with `omni.ui.scene`, `omni.debugdraw`'s named successor (F4) | Needs a viewport window's UI, which the headless app has none of |
| A timer per drawing that calls `clear_lines()` | The clear is global (F3): it takes drawings still due to show |
| Point the active viewport at the camera and size for each frame | Moves the user's viewport, races `capture_viewport` and `inspect_prim` for it (`_viewport` lock), and resets the renderer's accumulation every frame |
| `rep.orchestrator.step_async(delta_time=0.0, pause_timeline=False)` for each frame (F14) | Also triggers every writer anyone attached. Held back for R4: used only if `get_data()` doesn't refresh without it |
| The centre of mass from a PhysX tensor view (`apply_forces_and_torques_at_position` without a position) | Needs a simulation view made mid-play for one call |

### Decisions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | Keep `apply_force`'s velocity fallback? | Drop it: it ignores mass and point, and the PhysX call works on Kit 107.3 and 110.3 (F8). A failure becomes an error. |
| Q2 | Keep `omni.debugdraw` as the fallback for Kit apps without `isaacsim.util.debug_draw`, such as USD Composer? | Keep it: small, and its pure parts are unit-tested; no Kit app here can run it live (Tests). |
| Q3 | Without `omni.replicator.core`: record from the viewport with a warning, or refuse? | The viewport, with the warning: a refusal would break the default call on such an app. |
| Q4 | Refuse `apply_force` while the timeline is stopped? | Yes; paused is accepted. |
| Q5 | The centre of mass from PhysX's property query, or simply the body's origin? | The query, the origin as its fallback: they differ for any body whose centre of mass is off its origin. |
| Q6 | `capture_viewport` and `inspect_prim` also ignore `width` and `height`: the image comes at the viewport's size, while `screen_bbox` is scaled to the size asked for, so boxes and image disagree | A new issue, outside this plan; it can reuse the render product this adds |

## Compatibility

No one-way door moves.

| Door | Effect |
|---|---|
| Tool names, parameters, types, defaults, bounds, hints | None. Only descriptions change, which `tools/golden.py` strips: `tests/fixtures/mcp-tools.json` stays as it is. |
| Wire protocol | Paths, request bodies and the token are unchanged. Answers gain fields (`backend`, `duration`, `source`, `note`, `at`); `PROTOCOL` stays 1. |
| The extension's id and settings | Unchanged; `extension.toml` keeps its one optional dependency. |
| The output folder's layout | The same files in a recording's folder; `metadata.json` gains `source`. |

What users notice:

| Before | After |
|---|---|
| `draw_debug` fails on 6.2; elsewhere a drawing lasted a frame | It draws, for `duration` seconds; when a drawing expires, other lines drawn with `isaacsim.util.debug_draw` go too |
| Frames at the viewport's size, from its camera | 640x480 by default, from `camera_path` or the active camera |
| `apply_force` nudged `physics:velocity` by `force / 100`, or `force` for an impulse | PhysX applies the force or impulse, so mass counts, at `position` or the centre of mass; an error while stopped |

- **Mixed releases:** the fixes live in the extension, so they need `uvx omniverse-mcp extension install` and a Kit
  restart, as `get_sim_state`'s `note` says. A new server reads a 0.2.0 bridge's answers, since the new fields are
  read with defaults; a 0.2.0 server reads the new answers, which only add fields.
- **Kit apps:** Isaac Sim 5.x and 6.x draw with `isaacsim.util.debug_draw` and record through Replicator. Other
  Kit 107+ apps draw with `omni.debugdraw` when they ship it, and record from the viewport without Replicator.

## Steps

Each step builds and passes `uv run tools/gate.py quick` on its own.

| Step | What | Proven by |
|---|---|---|
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | `enable_extension` in `_utils.py`; `core/debug_draw.py` | `tests/test_debug_draw.py` |
| 3 | `handlers/debug_draw.py`, the route's import, `on_shutdown`; `draw_debug`'s description and text | `tests/test_tools.py`'s case; live: `test_16_03` to `test_16_07`, `test_31` |
| 4 | `core/recording.py`; the render product in `handlers/recording.py`, `on_shutdown`; `start_recording`'s descriptions and text | `tests/test_recording.py`, `tests/test_tools.py`; live: `test_06_01`, `test_06_03`, `test_06_04` |
| 5 | `core/force.py`; `handle_apply_force` through `IPhysxSimulation`; `apply_force`'s description and text | `tests/test_force.py`, `tests/test_tools.py`; live: `test_15_04`, `test_15_06` to `test_15_09` |
| 6 | The docs (Docs) | `test_contract.py` (TOOLS.md headings and hints), gate quick |
| 7 | `finish-work`: gate full, the live suites on Isaac Sim 6.2 (and 5.1, installed here), `review-code` | The review record in `docs/reviews/` |

## Tests

New behaviour gets a test that fails without it: Kit-free logic in `ovmcp/core/` under CI, the Kit calls in the live
suites.

**Unit (CI):**

| File | What it checks |
|---|---|
| `tests/test_debug_draw.py` (new) | The segments of each shape; each error; colours clamped, packed without spilling a channel; the book with a fake clock: two durations, one expiring, then none, `expire` true only when something went |
| `tests/test_recording.py` (new) | `recording_args` takes and refuses what it should; `steps_per_frame`; `camera_error` on a usd-core stage (nothing there, an Xform, a Camera); `frame_png` of a 120x160 RGBA array has a 160x120 IHDR; an empty array gives `b""` |
| `tests/test_force.py` (new) | `force_args`; the mode for each `impulse`; `world_point` with no rotation, a translation, and 90 degrees about Z and about Y (PhysX's x, y, z, w order) |
| `tests/test_tools.py` | The three cases' answers gain the new fields and their text. Beside the table, which holds one case per tool, tests of their own as `test_manage_extensions_enables_one` is: a 0.2.0-shaped answer for each tool still reads, and `start_recording`'s viewport `note` becomes a `WARNING` line |
| `tests/test_contract.py` | Unchanged and passing: the golden file doesn't move |

**Live (by hand, `OMNIVERSE_MCP_SIM=1`):** the main session runs them; this plan sets none of it up. Up-axis-aware,
as `test_15b` is, since #6's tests assume Y-up.

| Test | It must show |
|---|---|
| `test_scenarios.py`: `test_16_03` to `test_16_05` | Pass on 6.2; `backend` is `isaacsim.util.debug_draw` |
| `test_16_06_draw_debug_expires` (new) | `get_num_lines()` (through `execute`) rises by the line's segments, and falls back once `duration` (1 s) has passed |
| `test_16_07_draw_debug_twice` (new) | A 1 s drawing expiring leaves a 10 s one showing: the redraw after the global clear |
| `test_integration.py`: `test_31_draw_debug_reaches_a_capture` (new) | A thick red line across a grey view makes the capture redder where it runs (measured with numpy in Kit, as `_red_and_blue` does) |
| `test_06_01` (changed) | Frames are 320x240, from the PNG's IHDR; `metadata.json` says so |
| `test_06_03_record_from_a_camera` (new) | With the viewport turned away, frames from `/World/RecCam`, aimed at the red cube, are mostly red; the viewport's camera is unchanged after |
| `test_06_04_stop_destroys_the_render_product` (new) | No render product prim of ours is left under `/Render` after `stop_recording` |
| `test_15_04` (changed) | `method` is `physx` |
| `test_15_06_impulse_moves_by_mass` (new) | An impulse of 10 N s on the 5 kg cube in the air gives about 2 m/s along X, from PhysX's pose over sim time, within 25%; a 10 N force's speed is printed for R9, not asserted |
| `test_15_07_force_at_a_point_spins` (new) | Without `position` the cube doesn't turn (under 2 degrees); with a point above its centre it does (over 5) |
| `test_15_08_centre_of_mass_off_origin` (new) | With `MassAPI.centerOfMass` authored off centre, an impulse without `position` doesn't turn it, where one at its origin would; `at` is `centre of mass` |
| `test_15_09_apply_force_while_stopped` (new) | An error, not a success |
| Both suites in full | No failures beyond `main`'s on the same Kit (#5, #6) |

**What neither can show:** the `omni.debugdraw` backend and the recording's viewport fallback, since every Kit app
at hand has `isaacsim.util.debug_draw` and Replicator; a person watching the drawings come and go in a GUI
viewport (the live run is headless, and counts lines instead).

## Docs

- `docs/TOOLS.md`: `start_recording`'s `width`, `height` and `camera_path`, where frames come from and the fallback;
  `apply_force`'s `position`, the stopped refusal, what `method` and the point mean; `draw_debug`'s `duration` in
  real seconds, the backends, the global clear, the 2-pixel lines, and whether drawings reach a capture (R1).
- `docs/ARCHITECTURE.md`: the core list gains `debug_draw.py`, `recording.py`, `force.py`; the handlers list gains
  `debug_draw`; Recording System describes the render product; Extension Lifecycle's shutdown drops the drawing
  subscription and the render product.
- `CHANGELOG.md`, Unreleased, Fixed: `draw_debug` on 6.2 and its `duration` (#7, #25); `start_recording`'s camera
  and size (#25); `apply_force` through PhysX at the point or the centre of mass, refused while stopped (#25), with
  the line that the fixes come with `extension install`.
- `README.md`: the Known issues lines for #7 and #25 go, as #48 did for #40.
- `docs/SETUP.md`: the troubleshooting row for #7 goes.
- `plugin/skills/simulate/SKILL.md` (by `write-skill`'s rules): step 4's "at the world origin unless a `position`
  is given", step 5's "Frames keep the viewport's size and camera for now", and the #7 trap row.
- `.claude/skills/finish-work/SKILL.md`: the Traps row's "(#5, #6, #7)" loses #7.
- `AGENTS.md`: the extension's row names the new core modules (debug drawing, recording, forces).
- `test_project/scenarios.md`: phases 6, 15 and 16 gain the new checks; 16.6 already asks whether a capture shows
  the drawings.

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | Drawings may not reach `capture_viewport`: the 6.0 docs say the geometry "cannot be rendered", while 6.1's own test finds it in a Replicator render product (F5). Headless, a capture is the only way to see one. | Open: `test_31` decides. If it fails, TOOLS.md says drawings show in the viewport only, and the test goes, with the reason in the review record. |
| R2 | The global clear takes lines other code drew with `isaacsim.util.debug_draw` (F3) | Accepted: there is no per-line clear; TOOLS.md says so |
| R3 | A clear while the stage tears down crashes Kit (F3) | Guarded: clears wait for `OPENED`; none at shutdown |
| R4 | The `rgb` annotator may not refresh without an orchestrator step while the timeline plays, so frames repeat | Open: `test_06_03` compares frames of a falling cube. If they repeat, `step_async(delta_time=0.0, pause_timeline=False)` per frame (F14), and this plan is updated. |
| R5 | A render product renders every frame while recording: GPU time and VRAM, and frames may trail `sim_time` by a render or two | Accepted: destroyed at stop; trailing measured in `test_06_03` |
| R6 | Enabling Replicator or the drawing extension at runtime makes the first call slow, and Replicator turns on its capture-on-play | Accepted: seconds, under the client's 120 s timeout; with no writer attached, capture-on-play writes nothing |
| R7 | PNG encoding on Kit's main thread slows the simulation at a high `fps` | Accepted at the default 5 fps; the live run notes the frame rate at 30 |
| R8 | The property query is asynchronous and slower while a mesh cooks; its centre of mass is taken as body-local | Bounded at 30 updates, with the labelled origin fallback; `test_15_08` checks the frame |
| R9 | If PhysX's `Force` mode lasts one step, `impulse=False` gives `force * dt`, not the "continuous force" its description promises | Out of scope: `test_15_06`'s force case measures it; if confirmed, a new issue |
| R10 | The `omni.debugdraw` backend and the viewport fallback never run live | Accepted (Q2, Q3): unit-tested parts only |

## Plan review

None yet: `review-plan` writes round 1 here.
