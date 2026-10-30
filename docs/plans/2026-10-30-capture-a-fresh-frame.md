---
title: Make a capture wait out the renderer's trail, so what was drawn just before shows
issue: "#57"
status: draft
approved_by:
approved_at:
---

# Make a capture wait out the renderer's trail, so what was drawn just before shows

## Goal

A capture's image holds what was done before the capture was asked for: a drawing `draw_debug` just made, with
either extension, is in the `capture_viewport` that follows, however soon.

True when this is done:

| | What | Shown by |
|---|---|---|
| 1 | Why `test_16_09` misses `omni.debugdraw`'s lines is measured on Kit: which frame a capture takes, against the update that drew the lines | Design, the three runs |
| 2 | A capture waits `FRESH_FRAMES` frames of the viewport after it is asked for, then captures, every wait bounded as now | `tests/test_capture.py`; the live suites |
| 3 | `test_16_09` (the `omni.debugdraw` fallback) and `test_16_08` (`isaacsim.util.debug_draw`) capture each drawing at once after it is made, 5 times; on `765d51c`'s bridge they fail in every run (measured: 15 and 14 misses of 15), with the fix they pass in 3 cold starts and 3 warm runs | Design; Step 6 |

Why it matters: an assistant that draws a path with `draw_debug` and captures to check it can get a picture without
the path, and any change made just before a capture can be missing from it the same way: the image is about 3
updates old.

- **In scope:** `capture_viewport_png` (`handlers/_utils.py`), through which `capture_viewport`, `inspect_prim` and
  recording capture; the wait's rule and count in `ovmcp/core/capture.py`; `test_16_08`, `test_16_09` and their
  scenario text; the docs.
- **Out of scope:** the settle waits of `set_camera`, `look_at_prim` and `viewport_light`; Kit's zero-delay setting
  (`hydraEngine.waitIdle`); Eco Mode; the segmentation read, which reads its own sensor after the image;
  `omni.debugdraw` drawing in the handler (Alternatives).

## Design

### What Kit shows

Three runs, on 2026-10-30, Isaac Sim 6.2.0 headless (pip), `765d51c`'s bridge on port 8212, a new stage with a ground
cube and a distant light, the camera aimed away from both, 3.5 to 5 ms an update. The probes, through
`execute_script`, logged each update's `SWHFrameNumber` (from `PRE_UPDATE`), each `NEW_FRAME`, each update in which
`_OmniDebugDraw.frame` drew, and the frame each capture took (`RenderCapture.capture`). The scripts are
`e57_frames.py` and `e57_fresh.py` in the session's scratchpad; they go in the PR's description, not the repo.

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
| 1, every update slowed by 50 ms | 20 | 0: the renderer keeps up within a slow update |
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
`NEW_FRAME` numbered from the update after the request found none among the 450 to 620 frames of its 2 s, in each of
70 captures.

**The wait that works** (run 3, a fresh Kit, 187 frames a second): the capture first waits k frames of the viewport
(`next_viewport_frame_async(viewport, 1)`, k times), then captures as before. Drawn, then captured at once, 10 times
with each extension:

| k | `omni.debugdraw` misses | `isaacsim.util.debug_draw` misses | Each wait took |
|---|---|---|---|
| none | 10 of 10 | 10 of 10 | |
| 1 | 10 of 10 | 0 of 10 | 1 update, 1 frame, every time |
| 2 | 0 of 10 | 0 of 10 | 2 updates, 2 frames |
| 3 | 0 of 10 | 0 of 10 | 3 updates, 3 frames |
| 4 | 0 of 10 | 0 of 10 | 4 updates, 4 frames |

With k = 4 the HTTP path missed 0 of 60. `frame_info["metadata"]` is an `omni.kit.renderer_capture` `Metadata`
object, with nothing that names the frame's update.

### What the sources show

| Fact | Where it shows |
|---|---|
| With `omni.debugdraw` the handler draws nothing itself: `added` only builds the point list, and the first `draw_lines` comes from the update subscription the handler creates, on the next update (the runs: one update after the handler). `isaacsim.util.debug_draw` draws in the handler, and its lines stay | `handlers/debug_draw.py`, `_OmniDebugDraw.added` and `show` (lines 72-87), `frame` (89-94), `handle_draw_debug` (181-185) |
| A capture takes the next frame the viewport delivers after it is scheduled, whichever update that frame was rendered from: pending delegates run on the next `DRAWABLE_CHANGED` | `omni.kit.widget.viewport-110.0.1`, `impl/texture.py` lines 431-439 |
| Kit renders behind the update: Isaac Sim keeps 3 stage frames of history for it, "needed for omni.syntheticdata", and ships an "Isaac Sim Zero Delay" app, "providing zero frame delay", that sets `hydraEngine.waitIdle = true`; NVIDIA's visual tests set `waitIdle` too | `isaacsim.exp.base.kit` line 201; `isaacsim.exp.base.zero_delay.kit`; `omni.anim.curve.core`'s `tests/visual_test_base.py` |
| Kit's own way to wait for a fresh frame, `omni.syntheticdata`'s `next_sensor_data_async(waitSimFrame=True)`, and `RenderCapture`'s `frame_to_capture`, both read `swh_frame_number`, which this Kit leaves at `-1` or absent (the runs) | `omni.syntheticdata-0.6.17`, `scripts/sensors.py` lines 56-112; `omni.kit.widget.viewport-110.0.1`, `capture.py` lines 123-140 |
| NVIDIA's own visual test of `omni.debugdraw` draws for 20 updates before it captures, "Windows requires ~5 Linux requires ~20", and the extension marks its tests unreliable | `omni.debugdraw-0.1.4`, `omni/debugdraw/tests/visualtests.py` (`base`), `config/extension.toml` |
| `inspect_prim` settles 20 frames before each angle, so its captures were already fresh; `capture_viewport` and recording capture with no wait before | `handlers/camera.py` lines 726-729, 790-800; `handlers/recording.py` `_record_tick` |
| #55 did not change the path from the draw to the capture: the image capture is the same call, now inside `asyncio.wait_for`; #55 changed the settle before the draw (`_aim_away`'s `set_camera`) and the segmentation after the image. The measured cause, the trail against a 2-update gap, passes through neither, and the HTTP miss rate swings between sessions (2 of 20, then 0 of 60), so the record before and after #55 (2 passes, then 2 misses in 7) is chance | `git show a70ab29 -- extension/ovmcp.bridge/ovmcp/bridge/handlers/`; the runs |
| Kit 107 has `next_viewport_frame_async`, which the wait uses, as the settles have since #55 | Isaac Sim 5.1, `omni.kit.viewport.utility-1.1.2`, `__init__.py` line 736 |

**The cause:** a capture takes the frame the viewport delivers next, which the renderer made about 3 updates before.
Drawn and captured at once, a drawing is never in it; over HTTP, `isaacsim.util.debug_draw`'s lines, drawn in the
handler, are in time, and `omni.debugdraw`'s, drawn one update later, are in time only when the trail is 3 updates,
not 4. Why the misses came on the first full run of a fresh Kit is not shown: run 1's two misses were its second and
third HTTP trials, and none came after.

### The fix: wait out the trail, then capture

`capture.capture_png` (`ovmcp/core/capture.py`) waits `FRESH_FRAMES` frames of the viewport before it schedules the
capture, through the `frames` it already has: each frame bounded by `FRAME_SECONDS` and the call's budget, a viewport
that renders nothing a `NoFrameError` before anything is scheduled.

- **The count:** `FRESH_FRAMES = 4`. Two frames were the fewest that never missed in run 3, where the trail was 3
  updates; run 1's third draw trailed 4, which needs one more; and one frame of margin. Read when it runs, as the
  other limits are, so a live test can change it through `execute_script`.
- **The bridge:** `capture_viewport_png` passes `next_viewport_frame_async(viewport, 1)` for the capture's own
  viewport; a Kit without the frame event pumps app updates instead, as `_viewport_frames` does.
- **All captures get it:** `capture_viewport`, `inspect_prim` (on top of its 20-frame settle) and recording.
- **Kit's log:** the slow-capture line (over 2 s) also says how long the wait took.

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

The count is of the renderer's frames, the unit the trail is measured in, each bounded by time; #27's trouble was app
updates counted for render progress, with no bound.

## Compatibility

None of the one-way doors in `AGENTS.md`: the routes, the tools' names, parameters and annotations
(`tests/fixtures/mcp-tools.json` untouched), the answers, the extension's settings and the output folder stay as they
are. `FRESH_FRAMES` is a constant in the core, not an extension setting.

- **What users see:** a capture's image holds what was done just before it, a drawing or any other change; a
  recording frame is rendered after its simulation time, where it was about 3 updates before. Each capture takes 4
  frames longer: 4 updates, about 21 ms, at run 3's 187 frames a second; about 67 ms at 60.
- **Kit apps:** Isaac Sim 6.2 live; Isaac Sim 5.x untested live, as for #55. A Kit app whose renderer keeps a longer
  trail than Isaac Sim's would still see stale frames (Risks, 1).
- **Moving over:** the fix is in the Kit extension: `uvx omniverse-mcp extension install`, then restart Kit, as the
  CHANGELOG line says.

## Steps

1. **Measure (done, live).** The three runs above, recorded in Design; the scripts in the PR's description.
2. **The core.** `FRESH_FRAMES`, and `capture_png` taking a `next_frame` and waiting that many frames before it
   schedules. Proven by `tests/test_capture.py`: the capture is scheduled only after `FRESH_FRAMES` frames; a frame
   that never comes is `NoFrameError` with nothing scheduled; the budget caps the frames and says `OutOfTimeError`;
   the count is read when it runs; the existing tests keep their meaning with the frames given at once.
3. **The bridge.** `capture_viewport_png` passes the viewport's frame wait, with the app-update fallback; the slow
   line says the wait's time. Proven by the live suites (Step 6).
4. **The live tests.** A helper, `_drawn_then_captured(zigzag, times=5)`: in one `execute_script`, `draw_debug`'s
   handler (a 0.5 s drawing), then `mcp.capture_viewport` at once, then wait for the drawing to go; the red pixels of
   each capture. `test_16_08` (with `isaacsim.util.debug_draw`) and `test_16_09` (with `omni.debugdraw`) keep their
   checks over HTTP and add this one: each of the 5 captures holds over 100 red pixels. `test_project/scenarios.md`
   16.8 and 16.9 say so. Proven by: on `765d51c`'s bridge both fail in 5 runs of 5 (Design measured 15 and 14
   misses of 15), and pass with the fix.
5. **Docs** (Docs).
6. **The live runs** (Tests).

## Tests

| Suite | What |
|---|---|
| Unit (CI) | `tests/test_capture.py` (Step 2) |
| Live, `test_scenarios.py` | `test_16_08` and `test_16_09` (Step 4): 5 runs of `-k test_16_0` on `765d51c`'s bridge, each failing; with the fix, 3 cold starts with the full suites first thing, and 3 warm runs, all passing |
| Live, both suites | the full suites on the 3 cold starts: every capture test (`test_13`, `test_15c` to `test_15f`, `test_22_01`) and recording pass; the suites' time within a few seconds of `765d51c`'s; on the cold starts `test_16_09` runs after the G1 is loaded, the condition of the original misses |
| Not shown | Isaac Sim 5.x (5.1 crashes in its own start on the test machine); a Kit app that has only `omni.debugdraw`, such as USD Composer, where the fallback is the default and the renderer's trail may differ; async rendering (Kit 110 sends frame events on the renderer thread there, as for the settles since #55) |

## Docs

- `docs/TOOLS.md`: `capture_viewport`, a line that the image holds what was done before the call, at the cost of
  `FRESH_FRAMES` frames; `draw_debug`'s Captures bullet: with either extension, a capture after `draw_debug` holds the
  drawing, however soon.
- `docs/ARCHITECTURE.md`, Viewport Capture: the renderer's trail, the wait before each capture, a row in the limits
  table; Threading's note on `NEW_FRAME` covers this wait too.
- `CHANGELOG.md`, Unreleased, Fixed: a capture showed the scene about 3 updates before the call, so a drawing or a
  change made just before could be missing, `omni.debugdraw`'s lines most often; the fix is in the Kit extension: run
  `extension install` and restart Kit (#57).
- `AGENTS.md`, Traps: a row, "a capture took the next frame delivered, which the renderer made about 3 updates
  before (#57)"; the guard: `FRESH_FRAMES` frames before the capture. `AGENTS.md` is at 149 of its 150 lines; the gate
  says whether the row fits, or a line elsewhere gets shorter.
- `test_project/scenarios.md`: 16.8 and 16.9 (Step 4).

## Risks

| Risk | Status |
|---|---|
| 1. On a loaded Kit, or another Kit app, the trail is longer than `FRESH_FRAMES` | Accepted, with evidence: the cold-start full suites run `test_16_08` and `test_16_09` after the G1 is loaded; a frame of margin over the measured count; a Kit app with a longer trail still gets fresher frames than now |
| 2. Captures get slower | Accepted: 4 frames each, about 21 ms headless and 67 ms at 60 frames a second (run 3); `inspect_prim`'s 14 angles stay inside the same 80 s |
| 3. A paused viewport (Eco Mode on a static scene) gives no frame, so the wait fails | As today: the capture's own frame wait fails the same way after `FRAME_SECONDS`; `_reset_renderer` already turns Eco Mode off for its frames |
| 4. A frame event on the renderer thread (async rendering) | As for the settles since #55 (ARCHITECTURE.md, Threading); untested live |
| 5. Agents could not start Kit here: the brief's command was refused twice by the auto mode permission check | Resolved for the plan: the coordinating session ran the three runs; Step 6's runs need the same |

## Plan review

Written by `review-plan`.
