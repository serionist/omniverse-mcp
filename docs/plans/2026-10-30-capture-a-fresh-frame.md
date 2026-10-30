---
title: Make a capture wait out the renderer's trail, so what was drawn just before shows
issue: "#57"
status: approved
approved_by: serionist
approved_at: 2026-10-30
---

# Make a capture wait out the renderer's trail, so what was drawn just before shows

## Goal

A capture's image holds what was done before the capture was asked for: a drawing `draw_debug` just made, with
either extension, is in the `capture_viewport` that follows, however soon.

True when this is done:

| | What | Shown by |
|---|---|---|
| 1 | Why `test_16_09` misses `omni.debugdraw`'s lines is measured on Kit: which frame a capture takes, against the update that drew the lines | Design, runs 1 to 4 |
| 2 | A `capture_viewport` or `inspect_prim` capture waits `FRESH_FRAMES` frames of the viewport after it is asked for, then captures, every wait bounded as now; a recording frame doesn't wait | `tests/test_capture.py`; the live suites |
| 3 | `test_16_09` (the `omni.debugdraw` fallback) and `test_16_08` (`isaacsim.util.debug_draw`) capture each drawing at once after it is made, 5 times, and show the miss themselves with the wait set to 0; on `765d51c`'s bridge they fail in every run (measured: 15 and 14 misses of 15), with the fix they pass in 3 cold starts and 3 warm runs | Design; Step 6 |
| 4 | The same holds with async rendering on, as Isaac Sim's GUI runs it when stopped or paused | run 4 (Design); the async live run (Tests) |

Why it matters: an assistant that draws a path with `draw_debug` and captures to check it can get a picture without
the path, and any change made just before a capture can be missing from it the same way: the image is about 3
updates old.

- **In scope:** `capture_viewport_png` (`handlers/_utils.py`), through which `capture_viewport` and `inspect_prim`
  capture; the wait's rule and count in `ovmcp/core/capture.py`; `test_16_08`, `test_16_09` and their scenario
  text; the docs, ARCHITECTURE's wrong premise about async rendering in Isaac Sim included.
- **Out of scope:** recording, whose frames keep no wait (Compatibility); the settle waits of `set_camera`,
  `look_at_prim` and `viewport_light`; Kit's zero-delay setting (`hydraEngine.waitIdle`); the segmentation read,
  which reads its own sensor after the image; `omni.debugdraw` drawing in the handler (Alternatives).

## Design

### What Kit shows

Four runs, on 2026-10-30, each on a fresh Kit: Isaac Sim 6.2.0 headless (pip), `765d51c`'s bridge on port 8212, a new
stage with a ground cube and a distant light, the camera aimed away from both. Runs 1 to 3 rendered synchronously,
as the headless app does, at 3.5 to 5 ms an update; run 4 turned async rendering on (below), at 2.5 ms an update.
The probes, through `execute_script`, logged each update's `SWHFrameNumber` (from `PRE_UPDATE`), each `NEW_FRAME`,
each update in which `_OmniDebugDraw.frame` drew, and the frame each capture took (`RenderCapture.capture`). The
scripts are `e57_frames.py`, `e57_fresh.py` and `e57_async.py` in the session's scratchpad; they go in the PR's
description, not the repo.

**A capture's frame trails its request by about 3 updates.** A capture scheduled on each of the 10 to 14 updates after
a draw, 6 draws in all:

| Draw | Handler at update | First `draw_lines` | Captures without the lines: scheduled at | First with them: scheduled / delivered |
|---|---|---|---|---|
| run 1, 1 (the first after `omni.debugdraw` was turned on) | 124 | 125 | 124, 125, 126 | 127 / 128 |
| run 1, 2 | 270 | 271 | 270, 271 | 272 / 274 |
| run 1, 3 | 429 | 430 | 429 to 432 | 433 / 434 |
| run 2, 1 | 82 | 83 | 82, 83, 84 | 85 / 86 |
| run 2, 2 | 171 | 172 | 171, 172, 173 | 174 / 175 |
| run 2, 3 | 234 | 235 | 234, 235, 236 | 237 / 238 |

- A capture is delivered on the update after it is scheduled (sometimes the one after that), and its image holds
  `omni.debugdraw`'s lines only once it is delivered 3 updates after their first `draw_lines` (4 in run 1's third
  draw). The first draw after the extension is turned on behaves like the rest: no warm-up.
- `frame_info["frame_number"]` steps by 2 an update, and in the HTTP runs the frames that missed were one update
  older, against the update that delivered them, than those that hit (`2 x SWH - 50` against `2 x SWH - 48`).

**The test's path, `draw_debug` and then the capture, each over HTTP:** the first `draw_lines` at update U, the
capture scheduled at U + 2 and delivered at U + 3 (19 of run 1's 20 trials; the other an update later, and a hit);
whether it holds the lines depends only on whether the trail is 3 or 4 that time.

| Run | Trials | Misses |
|---|---|---|
| 1 | 20 | 2 (trials 2 and 3) |
| 1, every update slowed by 50 ms | 20 | 0: every frame trailed 3 updates (`2 x SWH - 48`), none 4 |
| 2 | 60 | 0 |

**Drawn, then captured at once,** in one `execute_script` (`draw_debug`'s handler, then `mcp.capture_viewport`):

| Extension | Run 2 | Run 3 |
|---|---|---|
| `omni.debugdraw` | 5 misses of 5 | 10 of 10 |
| `isaacsim.util.debug_draw` | 4 of 5 | 10 of 10 |

So the stale frame is not the fallback's alone: `isaacsim.util.debug_draw` draws in the handler, an update before
`omni.debugdraw`'s first draw, so the HTTP path's gap is enough for it, and `test_16_08` never missed.

**Frames carry no number to tell their age:** `NEW_FRAME`'s `swh_frame_number` is `-1` on every frame, and
`frame_info` has no `swh_frame_number` (its keys: `device_mask`, `fps`, `frame_number`, `metadata`, `progression`,
`projection`, `resolution`, `status`, `subframe_count`, `view`, `viewport_handle`). A capture that first waited for a
`NEW_FRAME` numbered from the update after the request found none among the 107 to 619 frames of its 2 s, in each of
70 captures.

**The wait that works** (run 3, a fresh Kit, 187 frames a second): the capture first waits k frames of the viewport
(`next_viewport_frame_async(viewport, 1)`, k times), then captures as before. These k frames come after the one app
update `handle_capture` already waits before it captures (`handlers/camera.py` line 790), so the counts below hold
for `capture_viewport`'s path as it is. Drawn, then captured at once, 10 times with each extension:

| k | `omni.debugdraw` misses | `isaacsim.util.debug_draw` misses | Each wait took |
|---|---|---|---|
| none | 10 of 10 | 10 of 10 | |
| 1 | 10 of 10 | 0 of 10 | 1 update, 1 frame, every time |
| 2 | 0 of 10 | 0 of 10 | 2 updates, 2 frames |
| 3 | 0 of 10 | 0 of 10 | 3 updates, 3 frames |
| 4 | 0 of 10 | 0 of 10 | 4 updates, 4 frames |

With k = 4 the HTTP path missed 0 of 60. `frame_info["metadata"]` is an `omni.kit.renderer_capture` `Metadata`
object, with nothing that names the frame's update.

**With async rendering (run 4):** runs 1 to 3 were synchronous, headless. Isaac Sim's GUI renders asynchronously
whenever the simulation is stopped or paused (What the sources show), so run 4, on a fresh headless Kit, turned
`/app/asyncRendering` and `/app/asyncRenderingLowLatency` on through `execute_script`, as `isaacsim.core.throttling`
does, then repeated run 3's tests (`e57_async.py`, in the order of `e57_sequence4.sh`).

- **Frames and updates part:** in 2 s, 813 updates and 218 frames (synchronous, 422 and 422), so the wait counts
  frames, not updates. The lines first showed in the 2nd or 3rd frame delivered after their first `draw_lines`, 3
  draws.
- **The same count holds:**

  | k | `omni.debugdraw` misses | `isaacsim.util.debug_draw` misses | Draw and capture took |
  |---|---|---|---|
  | none | 9 of 10 | 9 of 10 | 0.078 to 0.110 s |
  | 1 | 6 of 10 | 2 of 10 | 0.078 to 0.110 s |
  | 2 | 0 of 10 | 0 of 10 | 0.094 to 0.125 s |
  | 3 | 0 of 10 | 0 of 10 | 0.093 to 0.125 s |
  | 4 | 0 of 10 | 0 of 10 | 0.109 to 0.141 s |

  With k = 4 the HTTP path missed 0 of 60.
- **The frame events come on the main thread (Q6):** the immediate `NEW_FRAME` (which `next_viewport_frame_async`
  observes), the deferred one, and hydratexture's `DRAWABLE_CHANGED`, every one of them, synchronous and
  asynchronous: 422, 422 and 363 events in 2 s, then 218, 218 and 218, none on another thread.
- **Eco Mode (Q7):** it was on from the start of the fresh Kit, with `/rtx/ecoMode/maxFramesWithoutChange` at 500,
  and `isaacsim.core.throttling` enabled with its async toggle off. The eco step ran about 545 frames with nothing
  changing (3 s, then 2 s counted, at about 109 frames a second) and still saw 217 frames in the last 2 s: past 500
  frames, Eco Mode did not pause the viewport headless. There, with async rendering on, captures with no wait missed 5
  of 5, and with k = 4 missed 0 of 5 with each extension, each in 0.109 to 0.140 s.

### What the sources show

| Fact | Where it shows |
|---|---|
| With `omni.debugdraw` the handler draws nothing itself: `added` only builds the point list, and the first `draw_lines` comes from the update subscription the handler creates, on the next update (the runs: one update after the handler). `isaacsim.util.debug_draw` draws in the handler, and its lines stay | `handlers/debug_draw.py`, `_OmniDebugDraw.added` and `show` (lines 72-87), `frame` (89-94), `handle_draw_debug` (181-185) |
| A capture takes the next frame the viewport delivers after it is scheduled, whichever update that frame was rendered from: pending delegates run on the next `DRAWABLE_CHANGED` | `omni.kit.widget.viewport-110.0.1`, `impl/texture.py` lines 431-439 |
| Kit renders behind the update: Isaac Sim keeps 3 stage frames of history for it, "needed for omni.syntheticdata", and ships an "Isaac Sim Zero Delay" app, "providing zero frame delay", that sets `hydraEngine.waitIdle = true`; NVIDIA's visual tests set `waitIdle` too | `isaacsim.exp.base.kit` line 201; `isaacsim.exp.base.zero_delay.kit`; `omni.anim.curve.core`'s `tests/visual_test_base.py` |
| Kit's own way to wait for a fresh frame, `omni.syntheticdata`'s `next_sensor_data_async(waitSimFrame=True)`, and `RenderCapture`'s `frame_to_capture`, both read `swh_frame_number`, which this Kit leaves at `-1` or absent (the runs) | `omni.syntheticdata-0.6.17`, `scripts/sensors.py` lines 56-112; `omni.kit.widget.viewport-110.0.1`, `capture.py` lines 123-140 |
| NVIDIA's own visual test of `omni.debugdraw` draws for 20 updates before it captures, "Windows requires ~5 Linux requires ~20", and the extension marks its tests unreliable | `omni.debugdraw-0.1.4`, `omni/debugdraw/tests/visualtests.py` (`base`), `config/extension.toml` |
| `inspect_prim` settles 20 frames before each angle, so its captures were already fresh; `capture_viewport` and recording capture with no wait before | `handlers/camera.py` lines 726-729, 790-800; `handlers/recording.py` `_record_tick` |
| Recording starts a tick task every `steps_per_frame` updates with no limit on ticks in flight; each reads `frame_count` before its capture's `await` and sets it after, so ticks that overlap write the same frame file. A capture takes about 4 updates now; with 4 more frames, about 8, so at 8 to 15 frames a second ticks would overlap and about half the PNGs be overwritten. `test_07_02` checks only that the cube falls | `handlers/recording.py` lines 145, 158, 192, 196-206 (round 1, P1) |
| Isaac Sim's GUI renders asynchronously: `isaacsim.exp.full.kit` sets `isaacsim.core.throttling`'s `enable_async = true`, which turns `/app/asyncRendering` and `/app/asyncRenderingLowLatency` on at startup and a few updates after each stop or pause, and off on play; throttling also turns Eco Mode on at stop and pause, off on play. So ARCHITECTURE's "Isaac Sim turns async rendering off" holds for the headless Python app only | `isaacsim.exp.full.kit` line 155; `isaacsim.core.throttling`, `extension.py` (`_set_async_rendering`, `_on_frame_update`; `/rtx/ecoMode/enabled` lines 260, 277, 295) |
| #55 did not change the path from the draw to the capture: the image capture is the same call, now inside `asyncio.wait_for`; #55 changed the settle before the draw (`_aim_away`'s `set_camera`) and the segmentation after the image. The measured cause, the trail against a 2-update gap, passes through neither, and the HTTP miss rate swings between sessions (2 of 20, then 0 of 60), so the record before and after #55 (2 passes, then 2 misses in 7) is chance | `git show a70ab29 -- extension/ovmcp.bridge/ovmcp/bridge/handlers/`; the runs |
| Kit 107 has `next_viewport_frame_async`, which the wait uses, as the settles have since #55 | Isaac Sim 5.1, `omni.kit.viewport.utility-1.1.2`, `__init__.py` line 736 |

**The cause:** a capture takes the frame the viewport delivers next, which the renderer made about 3 updates before.
Drawn and captured at once, a drawing is never in it; over HTTP, `isaacsim.util.debug_draw`'s lines, drawn in the
handler, are in time, and `omni.debugdraw`'s, drawn one update later, are in time only when the trail is 3 updates,
not 4. Why the misses came on the first full run of a fresh Kit is not shown: run 1's two misses were its second and
third HTTP trials, and none came after.

### The fix: wait out the trail, then capture

`capture.capture_png` (`ovmcp/core/capture.py`) takes an optional `next_frame`. Given one, it waits `FRESH_FRAMES`
frames of the viewport before it schedules the capture, through the `frames` it already has: each frame bounded by
`FRAME_SECONDS` and the call's budget, a viewport that renders nothing a `NoFrameError` before anything is scheduled.
Without one, it captures at once, as now.

- **The count:** `FRESH_FRAMES = 4`. Two frames were the fewest that never missed in run 3, where the trail was 3
  updates; run 1's third draw trailed 4, which needs one more; and one frame of margin. Read when it runs, as the
  other limits are, so a live test can change it through `execute_script`. Run 4 found the same fewest, 2, with
  async rendering.
- **The bridge:** one helper, `_next_frame(viewport)`, waits one frame of a viewport through
  `next_viewport_frame_async(viewport, 1)`; `_viewport_frames` (the settles) and `capture_viewport_png` both use it,
  and a Kit without the frame event pumps app updates instead, as `_viewport_frames` does now. It keeps the immediate
  `NEW_FRAME`, which run 4 saw on the main thread with async rendering too (Q6).
- **Who waits:** `capture_viewport` and `inspect_prim` (on top of its 20-frame settle): `capture_viewport_png` passes
  `_next_frame` by default. Recording passes none: its ticks would overlap with the longer capture and overwrite
  frames (What the sources show), and the wait buys it nothing a user asked for. #25 removes this opt-out once
  recording takes its frames from its own feed.
- **Kit's log:** the slow-capture line (over 2 s) also says how long the wait took, and the app's
  `/app/settings/fabricDefaultStageFrameHistoryCount`, the stage history the renderer may trail by, for a later
  look at other apps.

**Alternatives:**

| Option | Why not |
|---|---|
| Wait for a frame numbered from the update after the request, as Kit's `next_sensor_data_async(waitSimFrame=True)` does | This Kit gives no number: `-1` on every `NEW_FRAME` (the runs) |
| Kit's `capture_viewport_to_file(..., frame_to_capture=n)` | The same number, absent from `frame_info`: Kit's code logs "No SWH frame number available" and captures nothing |
| `frame_info["frame_number"]`, 2 an update here | Nothing gives the number of the frame being rendered now to compare it with, its step is the renderer's own, and `metadata` names no update (run 3) |
| Turn on `hydraEngine.waitIdle` around a capture | A renderer-wide setting the user's app chose; Isaac Sim offers it as a separate app; its effect when switched at run time is unmeasured |
| `omni.debugdraw` draws in the handler too, as `isaacsim.util.debug_draw` does | One update sooner: enough for the HTTP path most of the time, never for a capture made at once |
| `draw_debug` waits before it answers | Every draw pays it, and every other change before a capture keeps the stale frame |
| The issue's fallback: the test captures several times; TOOLS.md says lines can miss | Leaves every capture about 3 updates old |
| The count from the app: `fabricDefaultStageFrameHistoryCount` + 1, at least 4 | One number is simpler until another app shows a longer history; the slow-capture line logs the history for that day (round 1) |
| Recording waits too, with one tick in flight at a time | A change to recording's timing that nobody asked for here; recording is #25's ground |

The count is of the renderer's frames, the unit the trail is measured in, each bounded by time; #27's trouble was app
updates counted for render progress, with no bound.

### For the maintainer

| | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Should `inspect_prim` pay the 4 frames too, on top of its 20-frame settle per angle? | Yes: one rule for every capture but recording, about 20 ms an angle | As recommended (2026-10-30) |
| Q2 | `FRESH_FRAMES = 4`? | Yes: the fewest that never missed was 2, synchronous and asynchronous (runs 3 and 4); one more for the longer trail run 1 saw, one of margin; a core constant, not an extension setting | As recommended (2026-10-30) |
| Q3 | Who runs Kit for the code PR's live runs, since the agents' start of Kit is refused? | As for runs 1 to 4: the coordinating session | As recommended (2026-10-30) |
| Q4 | Recording gets no wait (round 1, P1)? | Yes | As recommended (2026-10-30) |
| Q5 | Must a GUI run, or a headless run with async rendering, come before CHANGELOG says Fixed? | The code's headless async run (Tests) is required, as run 4 was for the plan; a GUI run is welcome | As recommended (2026-10-30) |
| Q6 | The wait listens for the immediate `NEW_FRAME`, which ARCHITECTURE says Kit 110 may send on the renderer thread with async rendering (#5 was a deadlock of that kind): keep it, or listen to another event? | Keep it: run 4 saw every `NEW_FRAME`, immediate and deferred, and every `DRAWABLE_CHANGED` on the main thread, with async rendering on and off; ARCHITECTURE says so, for Isaac Sim 6.2 | As recommended (2026-10-30) |
| Q7 | Eco Mode, which throttling turns on at stop and pause: does a static scene still give the frames the wait needs? | Nothing to add: Eco Mode was on through run 4, frames kept coming after about 545 static frames, past its 500, and the waited captures held the drawing; the GUI is untried | As recommended (2026-10-30) |

## Compatibility

None of the one-way doors in `AGENTS.md`: the routes, the tools' names, parameters and annotations
(`tests/fixtures/mcp-tools.json` untouched), the answers, the extension's settings and the output folder stay as they
are. `FRESH_FRAMES` is a constant in the core, not an extension setting.

- **What users see:** a `capture_viewport` or `inspect_prim` image holds what was done just before it, a drawing or
  any other change. Each takes 4 frames longer: about 21 ms at run 3's 187 frames a second, about 30 ms with run 4's
  async rendering, about 67 ms at 60 frames a second.
- **Recording is unchanged:** its frames still show the scene about 3 updates before their simulation time, as now.
- **Kit apps:** Isaac Sim 6.2 live, headless, synchronous (runs 1 to 3) and asynchronous (run 4); the GUI untested;
  Isaac Sim 5.x untested live, as for #55. A Kit app whose renderer keeps a longer trail than Isaac Sim's would still
  see stale frames (Risks, 1).
- **Moving over:** the fix is in the Kit extension: `uvx omniverse-mcp extension install`, then restart Kit, as the
  CHANGELOG line says.

## Steps

1. **Measure (done, live).** Runs 1 to 4, recorded in Design; the scripts go in the PR's description.
2. **The core.** `FRESH_FRAMES`, and `capture_png` taking an optional `next_frame`: given one, it waits that many
   frames before it schedules; without, it captures at once. Proven by `tests/test_capture.py`: with `next_frame`
   the capture is scheduled only after `FRESH_FRAMES` frames, and without it at once; a frame that never comes is
   `NoFrameError` with nothing scheduled; the budget caps the frames and says `OutOfTimeError`; the count is read
   when it runs; the existing tests keep their meaning.
3. **The bridge.** `_next_frame(viewport)` for `_viewport_frames` and `capture_viewport_png`, with the app-update
   fallback, on the immediate `NEW_FRAME` (Q6); `capture_viewport_png` passes it unless its caller says not to, and
   recording says not to; the slow line says the wait's time and the stage frame history. Proven by the live
   suites (Step 6). That recording doesn't wait is shown by no test yet (Tests, Not shown); a unit test of the
   bridge's call is out of reach, since the handlers import Kit.
4. **The live tests.** A helper, `_drawn_then_captured(zigzag, times=5, fresh_frames=None)`: in one
   `execute_script`, `draw_debug`'s handler (a 1 s drawing), then `mcp.capture_viewport` at once, then wait for the
   drawing to go; each capture's red pixels, and the time from the draw to the end of its capture. Given
   `fresh_frames`, the same script sets `capture.FRESH_FRAMES` to it and puts the old value back in a `finally`, so
   the change ends with the script, not with the test (cleanups run only after it); as a backstop it takes
   `test_integration.py`'s `_SHORTEN` way, a token and a 60 s timed undo, the snippet shared through `conftest.py`.
   `test_16_08` (with `isaacsim.util.debug_draw`) and `test_16_09` (with `omni.debugdraw`) keep their checks over
   HTTP and add this one twice:
   - first with `fresh_frames=0`: its misses are printed, to show the trail on this bridge (Design measured 15 and 14
     misses of 15 without the wait). Departed from in the build: this asserted at least one miss, but with async
     rendering the renderer sometimes kept up (the no-wait half held the drawing in 3, 5, 3 and 5 captures of 5), so
     it is recorded, not asserted; `765d51c`'s bridge still fails the test, on the half below;
   - then as shipped: each of the 5 holds over 100 red pixels;
   - each time, a capture that ended after its drawing's 1 s fails as "Kit was slow", as `test_16_09` does now.

   `test_project/scenarios.md` 16.8 and 16.9 say so. Proven by: on `765d51c`'s bridge both fail in 5 runs of 5, and
   pass with the fix.
5. **Docs** (Docs).
6. **The live runs** (Tests).

## Tests

| Suite | What |
|---|---|
| Unit (CI) | `tests/test_capture.py` (Step 2) |
| Live, `test_scenarios.py` | `test_16_08` and `test_16_09` (Step 4): 5 runs of `-k test_16_0` on `765d51c`'s bridge, each failing; with the fix, 3 cold starts with the full suites first thing, and 3 warm runs, all passing |
| Live, both suites | the full suites on the 3 cold starts: every capture test (`test_13`, `test_15c` to `test_15f`, `test_22_01`) and recording (`test_07_*`) pass. Time: the new halves of `test_16_08` and `test_16_09` add about 20 to 25 s (a 1 s drawing waited out 5 times, twice a test, in two tests); without those two tests, the suites' time within a few seconds of `765d51c`'s. On the cold starts `test_16_09` runs after the G1 is loaded, the condition of the original misses |
| Live, async rendering | `-k test_16_0` with `/app/asyncRendering` and its low-latency twin turned on through `execute_script` before the suite, as run 4 does: required before CHANGELOG says Fixed (Q5) |
| Not shown | Isaac Sim's GUI itself, unless the maintainer runs it (Q5); Isaac Sim 5.x (5.1 crashes in its own start on the test machine); a Kit app that has only `omni.debugdraw`, such as USD Composer, where the fallback is the default and the renderer's trail may differ; whether recording waits: `test_07_*` assert success, a state file and a falling cube, nothing of a frame's timing, until #25's numbered ticks |

## Docs

- `docs/TOOLS.md`: `capture_viewport` and `inspect_prim`, a line that the image holds what was done before the call,
  at the cost of `FRESH_FRAMES` frames; `draw_debug`'s Captures bullet: with either extension, a capture after
  `draw_debug` holds the drawing, however soon; `start_recording`: its frames show the scene a few updates before
  their simulation time.
- `docs/ARCHITECTURE.md`, Viewport Capture: the renderer's trail, the wait before each capture and why recording has
  none, a row in the limits table. Threading (line 264): the premise corrected, that Isaac Sim's GUI renders
  asynchronously through `isaacsim.core.throttling` (on at startup and after a stop or pause, off while it plays);
  its clause "and `omni.syntheticdata` does too when it loads" goes, since `SyntheticData.disable_async_rendering`
  (0.6.17, `SyntheticData.py` line 831) has no caller and run 4 kept async rendering on with the bridge and
  `omni.syntheticdata` loaded; and on Isaac Sim 6.2 run 4 saw the frame events on the main thread with async
  rendering on too.
- `CHANGELOG.md`, Unreleased, Fixed: `capture_viewport` and `inspect_prim` showed the scene about 3 updates before the
  call, so a drawing or a change made just before could be missing, `omni.debugdraw`'s lines most often; the fix is in
  the Kit extension: run `extension install` and restart Kit (#57).
- `AGENTS.md`, Traps: a row, "a capture took the next frame delivered, which the renderer made about 3 updates
  before (#57)"; the guard: `FRESH_FRAMES` frames before the capture, none for recording. `AGENTS.md` is at 149 of
  its 150 lines; the gate says whether the row fits, or a line elsewhere gets shorter.
- `test_project/scenarios.md`: 16.8 and 16.9 (Step 4).

## Risks

| Risk | Status |
|---|---|
| 1. On a loaded Kit, with async rendering, or in another Kit app, the trail is longer than `FRESH_FRAMES` | Async rendering: resolved, run 4 needed 2 frames, as run 3 did. The rest accepted, with evidence: the cold-start full suites run `test_16_08` and `test_16_09` after the G1 is loaded; `FRESH_FRAMES` is one frame over the longest trail measured (3 frames, run 1's third draw); a Kit app with a longer trail still gets fresher frames than now |
| 2. Captures get slower | Accepted: 4 frames each, about 21 ms headless and 67 ms at 60 frames a second (run 3); `inspect_prim`'s 14 angles stay inside the same 80 s |
| 3. A paused viewport gives no frame, so the wait fails: Eco Mode on a static scene, which throttling turns on in the GUI at stop and pause | Accepted: Eco Mode was on through run 4 and did not pause the viewport after about 545 static frames, past its 500 (Q7); in the GUI, untried, a paused viewport would fail the capture's own frame wait the same way today, after `FRAME_SECONDS` |
| 4. A frame event on the renderer thread (async rendering): #5 was a deadlock of that kind | Resolved for Isaac Sim 6.2: run 4 saw every frame event on the main thread, async rendering on and off (Q6); another Kit app is as untested as for the settles since #55 |
| 5. Recording's ticks overlap and overwrite frames when a capture takes longer | Resolved: recording gets no wait (round 1, P1; Q4) |
| 6. Agents could not start Kit here: the brief's command was refused twice by the auto mode permission check | Resolved for the plan: the coordinating session ran runs 1 to 4; Step 6's runs need the same (Q3) |

## Plan review

### Round 1

- **How:** review-plan, one fresh reviewer agent on Claude, started by the coordinating session, 2026-10-30, on
  `0a011ab`.
- **Verdict:** needs-fixes: one major, two minors. The root cause found shown; a frame count found the right unit;
  every number in the run tables checked against the three outputs.
- **Now:** all three fixed in `37c0a6c`; run 4, P3's measurement, is recorded in Design since. A second round
  follows, for the major.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | Recording's frames would overwrite each other at middle frame rates: `_record_tick` reads `frame_count` before its capture's `await` and sets it after (`recording.py` lines 145, 158, 192), with no limit on ticks in flight. A capture takes about 4 updates now, so at 10 frames a second (a tick every 6 updates) ticks don't overlap; with 4 fresh frames it takes about 8, so at 8 to 15 frames a second about half the PNGs would be overwritten. `test_07_02` checks only that the cube falls. The wait buys recording nothing | fixed: `capture_png`'s `next_frame` is optional and recording passes none (Design, The fix; Compatibility; Q4); a Risk row and an Alternatives row |
| P2 | minor | "450 to 620 frames ... in each of 70 captures" doesn't match the patch log (107 to 619 seen); and `capture_viewport` waits one app update before it captures (`camera.py` line 790), which the k table depends on | fixed: 107 to 619; the k table says its frames follow that update |
| P3 | minor | Isaac Sim's GUI runs async rendering: `isaacsim.exp.full.kit` sets `isaacsim.core.throttling`'s `enable_async = true`, which turns `/app/asyncRendering` on at startup and a few updates after each stop or pause. All three runs were synchronous and headless, and ARCHITECTURE's "Isaac Sim turns async rendering off" is false for the GUI after a stop. If the trail is longer there, this becomes a major | fixed: a sources row, the Docs line correcting ARCHITECTURE's premise, Goal row 4, a Tests row; run 4 (`e57_async.py`, `e57_sequence4.sh`) measured the trail for k = 0 to 4 with async rendering on: the fewest frames that never missed was 2, as synchronous, so it stays a minor and `FRESH_FRAMES` stays 4 (Design) |

Refuted: none.

Owner calls: Q1 to Q7 (Design, For the maintainer), the review's Q4 to Q7 among them, Q6 and Q7 with run 4's
evidence; their answers wait for the maintainer. The reviewer recommends merging #57 first, without recording, then
#51, then #25.

Improvements:

| Improvement | Answer |
|---|---|
| A self-proving live test: set `capture.FRESH_FRAMES = 0` through `execute_script` to show the miss on the new bridge | taken: Step 4 |
| A "Kit was slow" guard, as `test_16_09` has | taken: Step 4, each capture against its drawing's 1 s |
| One bridge-side `_next_frame(viewport)` shared with `_viewport_frames` | taken: Design, The fix; Step 3 (#51 may reuse it) |
| Log `fabricDefaultStageFrameHistoryCount` in the slow-capture line | taken: Design, The fix |
| Wait for the history count + 1 frames, at least 4 | left: one number is simpler until another app shows a longer history; Alternatives |

### Round 2

- **How:** review-plan, one fresh reviewer agent on Claude, started by the coordinating session, 2026-10-30, on
  `f656a98`.
- **Verdict:** approved: P1, P2 and P3 fixed, and every number of run 4 matching its output; three minors, and one
  finding refuted. The plan waits on the maintainer's answers to Q1 to Q7 (needs-answers).
- **Now:** the three minors and all four improvements in the commit that records this round.

| # | Sev | Finding | Status |
|---|---|---|---|
| P4 | | On run 1's run with every update slowed by 50 ms | refuted by the reviewer: at 50 ms every frame is `2 x SWH - 48`, the 3-update trail, and with no wait a capture made at once is delivered at U + 2, which misses. It also showed the plan's reading of that run wrong ("the renderer keeps up within a slow update"): fixed, the run's row now says every frame trailed 3 updates, none 4 |
| P5 | minor | Step 4: cleanups run only after the test, so the "as shipped" half would run with `FRESH_FRAMES` still 0 | fixed: the helper's own `execute_script` sets it and puts it back in a `finally`; `_SHORTEN`'s token and 60 s timed undo as a backstop, shared through `conftest.py` |
| P6 | minor | Tests: the new halves add about 20 s (a 1 s drawing waited out 5 times, twice a test, in two tests), which breaks "the suites' time within a few seconds of `765d51c`'s" | fixed: the row names the 20 to 25 s and compares the rest without `test_16_08` and `test_16_09` |
| P7 | minor | Step 3 and Tests: `test_07_*` can't show whether recording waits; they assert success, a state file and a falling cube | fixed: Step 3 no longer claims it, and Tests' Not shown says so until #25's numbered ticks |

Improvements:

| Improvement | Answer |
|---|---|
| Risk 1: one frame over the longest trail measured, not "two frames of margin" | taken |
| Eco Mode: the eco step ran about 545 static frames and still saw 217 in its last 2 s, so the run went past 500 and Eco Mode didn't pause headless | taken: Design, Q7, Risk 3 |
| ARCHITECTURE line 264's "omni.syntheticdata does too when it loads" is wrong too: `SyntheticData.disable_async_rendering` (0.6.17, line 831) has no caller, and run 4 kept async rendering on with the bridge loaded | taken: Docs |
| Say #25 removes `capture_viewport_png`'s opt-out once recording moves to its feed | taken: Design, Who waits |

For #51, passed on by the coordinating session: each retake after a resize pays `FRESH_FRAMES`, and this plan's new
test halves run through #51's capture.
