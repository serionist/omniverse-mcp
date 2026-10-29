---
title: Bound the capture waits, and wait for segmentation by time after a stage opens
issue: "#27, #35"
status: draft
approved_by:
approved_at:
---

# Bound the capture waits, and wait for segmentation by time after a stage opens

## Goal

Every capture returns its image or says what went wrong, in a time that fits inside the server's 120-second client
timeout, and a segmentation asked for after a stage opens comes back or says why.

True when this is done:

| | What | Issue |
|---|---|---|
| 1 | A capture whose `wait_for_result` names nothing captured (`[]` or `None`) fails at once, not after ten seconds | #35 |
| 2 | No wait in the capture path is unbounded: a viewport that renders nothing fails after 30 s instead of hanging the call and the viewport lock | #35 |
| 3 | `inspect_prim` and `capture_viewport` answer within about 90 s, under the server's 120 s, and name each angle they did not capture | #35 |
| 4 | Segmentation after a new or opened stage waits for its first data by time (up to 5 s), not by 10 app updates, and an answer without it says why | #27 |
| 5 | Three cold starts of Isaac Sim 6.2 pass `test_13_camera_inspect_auto_fit` and `test_22_01_inspect_with_segmentation` on their first run, with the bridge's log showing how long the first frames took | #27 |

Why it matters: an assistant whose capture stalls sees the server's timeout, not the reason, and every later viewport
request queues behind the held lock; a user's first segmentation after opening a stage can come back without it and
without a word.

- **In scope:** the capture path in the bridge (`handlers/_utils.py`, `handlers/camera.py`, and recording through
  the shared helper), a new Kit-free module for its waits, the two camera tools' text for a segmentation error, the
  docs, live tests.
- **Out of scope:** moving segmentation to Replicator annotators; lifting Eco Mode for captures; the server's 120 s
  and the scenario client's 10 s timeouts; recording's ignored camera and size (#25); sweeping the temp files that
  abandoned captures leave (Risks).

## Design

### What the code and Kit show: #27's cause

#27's recorded failure was the colour capture, not the segmentation, and #33 removed its cause; the segmentation has a
race of the same shape that nothing has removed yet, and it fails silently.

| Fact | Where it shows |
|---|---|
| `'Viewport capture produced no output'` came only from the colour capture. A segmentation failure in `inspect` is dropped (`except Exception: pass`), so test_22_01's `'image_base64' not found` was its image; `test_13`, without segmentation, failed the same way (#27's first comment) | `_capture_frame` before `b1f918d`; `handle_camera_inspect`, `camera.py` lines 651-663 |
| Before #33 a capture waited 10 app updates for one shared temp file. A later capture found the earlier capture's late file (#32), so "no output" showed only when no earlier file was there: the first slow capture after Kit started | `git show b1f918d`, the removed `_do_capture` |
| #33 gave each capture a fresh file and 10 s to arrive. Every cold-start run since passed test_22_01 and test_13: #33's own, 0.2.0's release check, #48's | PR #33; `docs/reviews/2026-10-29-release-0.2.0-code.md`, `docs/reviews/2026-10-29-robot-usd-path-code.md` |
| Kit's `omni.syntheticdata` drops all its graphs on every stage CLOSING and OPENED, so the sensor `_init_sensors` enabled at startup is gone after `new_scene` or an open | `omni.syntheticdata` 0.6.17 (Isaac Sim 6.2) and 0.6.13 (5.1), `scripts/extension.py`, `_on_stage_opened`: `SyntheticData.Get().reset(False)` |
| unittest sorts by name, so the scenario suite runs `test_17_02_new_scene` before phase 22: test_22_01 is the first segmentation on a new stage | `tests/test_scenarios.py` |
| The handler then enables the sensor and reads it at once, which is empty by Kit's own account, pumps 10 app updates, reads once more, and drops the segmentation if it is still empty | `_capture_instance_segmentation`, `SEGMENTATION_RETRY_FRAMES = 10`; Kit's `create_or_retrieve_sensor`: "the sensor will be uninitialized until a frame is rendered after the sensor is created" |

**The likely root cause:** a fixed count of app updates against a renderer whose time to its first frame varies, and
is longest on the first run after Kit starts: 10 updates for the colour file (gone since #33), and 10 for the
segmentation after a stage opens (still there, and silent).

**How the live run confirms it,** since it shows only on a first run after Kit starts: the bridge logs, for each
segmentation it enables, how many updates and seconds its first data took, and for each capture over 2 s how long
its frame and its file took. Three cold starts, the live suites first thing after each (Tests). If a segmentation
after `test_17_02` ever needed more than 10 updates, the latent race is shown; if never, #27 was all the colour file.
Either way the cold runs with the new code are the evidence to close #27.

### What Kit's capture API does, on Kit 107 and 110

Read in Kit's sources on this machine: Isaac Sim 6.2.0 (`D:\isaac\venv`, Kit 110: `omni.kit.widget.viewport`
110.0.1, `omni.kit.viewport.utility` 2.1.2, `omni.syntheticdata` 0.6.17) and Isaac Sim 5.1.0 (`D:\isaacsim5.1`,
Kit 107: 107.1.3, 1.1.2, 0.6.13). Both behave the same where this plan relies on them, unless the row says otherwise.

| API | What it does | Source |
|---|---|---|
| `capture_viewport_to_file(viewport_api, file_path, ...)` | "Returns: A future-like object that can be awaited to ensure the capture completes." No timeout is documented | NVIDIA's API page for `omni.kit.viewport.utility.capture_viewport_to_file` |
| its return value | `viewport_api.schedule_capture(...)`, which is `None` when the viewport has no texture: `return self.__viewport_texture.schedule_capture(delegate) if self.__viewport_texture else None` | `omni/kit/widget/viewport/api.py` |
| `Capture.wait_for_result(self, completion_frames: int = 2)` | `await self.__future`, then 2 app updates, then `return self.__future.result()`. No timeout parameter | `omni/kit/widget/viewport/capture.py` |
| when the future is set | only when the viewport delivers a frame: the delegates run in the texture's `GLOBAL_EVENT_DRAWABLE_CHANGED` handler. A viewport that renders nothing never sets it | `omni/kit/widget/viewport/impl/texture.py` (Kit 110) |
| the result | `completed`, the AOVs it captured: `["LdrColor"]`; `[]` when the frame had no colour AOV; `None` only on the `frame_to_capture` branches, unused here. With `[]` or `None`, `capture_aov` never ran, so no file will come | `RenderCapture.capture` |
| Kit 110 only | `save_aov_to_file` returns early on a missing resource, logging "Capture of {aov['name']} was requested, but no valid resource!", yet the AOV is in the result: only the file wait catches it | `capture.py`, Kit 110 against Kit 107 |
| the file on Kit 110 | written after `wait_for_result` returns (#33). NVIDIA's own clash-detection export does the same as #33: `await capture.wait_for_result()`, then `await self._wait_for_file(screenshot_path)` | Context7, Omniverse extensions, `ext_clash-detection` |
| cancelling our wait | Kit sets the future through `if not self.__future.done(): self.__future.set_result(value)`, so a future our timeout cancelled gives Kit nothing to trip on when the frame comes later | `Capture._set_completed` |
| `ViewportAPI.wait_for_rendered_frames(additional_frames)` | awaits a future set from `subscribe_to_frame_change`; no timeout. `_reset_renderer`'s `next_viewport_frame_async` awaits `usd_context.next_frame_async(viewport, n)`, likewise bare | `api.py`; `omni/kit/viewport/utility/__init__.py` |
| `ViewportAPI.updates_enabled = False` | calls the hydra texture's `set_updates_enabled(False)`: a real way to get a viewport that renders nothing, for a live test | `api.py`, both Kits |
| `IRendererCapture.wait_async_capture()` | "Wait for asynchronous capture to complete", synchronous: it would block Kit's main thread | `omni/kit/renderer_capture/_renderer_capture.pyi` |
| `sensors.enable_sensors` | `activate_node_template(..., [viewport.render_product_path])`, which returns at once for a node already active (`if node_path in self._activatedNodePaths: return`): enabling again is harmless. The sensors API is marked deprecated, the async `create_or_retrieve_sensor_async` waiting at most 50 updates | `omni/syntheticdata/scripts/sensors.py`, `SyntheticData.py` |
| `get_instance_segmentation` | an empty `(0, 0)` array until the node has data | `get_sensor_array` |
| Python | Kit 107 embeds 3.11 (`python311.dll`), Kit 110's extensions are `cp312`. Since 3.11 `asyncio.TimeoutError` is `TimeoutError`, an `OSError`, not a `RuntimeError` | the installs; Python 3.11's changelog |
| timers on Kit's loop | `asyncio.wait_for` runs there: the bridge's `core/http.py` already uses it on the same loop | `ovmcp/core/http.py` |

### The change

One Kit-free module holds every wait the capture path makes, each bounded by time, and the handlers wire Kit into it.

**`extension/ovmcp.bridge/ovmcp/core/capture.py`, new, no Kit (import-linter's contract holds):**

| Name | What |
|---|---|
| `CaptureError(RuntimeError)` | a capture that gave no image, its message saying which step and for how long; recording's `except RuntimeError` still catches it |
| `NoFrame(CaptureError)` | the viewport delivered no frame within `FRAME_SECONDS`; the message names the likely reasons (updates off, a hidden viewport, Eco Mode on a static scene) |
| `OutOfTime(CaptureError)` | the call's time ran out |
| `Budget(seconds, clock=time.monotonic)` | the time a call may spend; caps each wait at what is left |
| `bounded(awaitable, seconds, budget)` | the awaitable within the shorter of `seconds` and what is left, through `asyncio.wait_for`; its `TimeoutError` becomes `NoFrame`, or `OutOfTime` when the budget was the shorter bound |
| `frames(next_frame, count, budget)` | `count` frames, each through `bounded(..., FRAME_SECONDS, ...)` |
| `poll(read, ready, next_update, seconds, budget, clock)` | `read()` after each update until `ready(value)`; `None` once the time is up |
| `capture_png(schedule, read_file, next_update, budget)` | `schedule()` (`None`: `CaptureError`, the viewport has no render texture yet); `wait_for_result()` through `bounded`; a result of `[]` or `None`: `CaptureError` at once, naming the result (#35); otherwise `poll` the file for a whole PNG (`is_complete_png`) for `FILE_SECONDS` |
| `stops_the_call(error)` | `NoFrame` or `OutOfTime`: the next angle would wait the same, so the call stops capturing |
| constants | `FRAME_SECONDS = 30`, `FILE_SECONDS = 10` (today's `CAPTURE_TIMEOUT_SECONDS`), `SEGMENTATION_SECONDS = 5`, `CALL_SECONDS = 80`, `CLEANUP_SECONDS = 10`. Read when a function runs, never bound as defaults, so a live test can shorten one through `execute_script` |

**The bridge, `extension/ovmcp.bridge/ovmcp/bridge/handlers/`:**

- **`_utils.capture_viewport_png(viewport, budget=None)`:** `capture_png` with Kit's `capture_viewport_to_file`, the
  fresh `ovmcp_capture_<uuid>.png`, and `_next_update`. The file is deleted in `finally`, as today. A failure is
  logged as a warning with its step and seconds; a capture over 2 s logs its frame and file times at info.
- **`_settle_viewport` and `_reset_renderer`:** wait frame by frame through `frames()`, with Eco Mode put back in a
  `finally`. Without a call budget, a settle or reset gets one of `FRAME_SECONDS` for all its frames. They raise
  `NoFrame` or `OutOfTime`: `set_camera`, `look_at_prim` and `viewport_light` catch it, log it and answer as today,
  where they hung; the capture handlers let it through.
- **`camera._capture_frame(camera_path, width, height, budget=None)`:** as today, the budget passed down; no
  black-frame retry after an error.
- **Segmentation, `camera._segmentation(viewport, seconds, budget)`:** async, returning `(png, legend, error)`, in
  place of `_capture_instance_segmentation`, its inline enable and both retry blocks. Read the sensor; if empty, enable
  it (harmless when already on) and `poll` it after each app update for `seconds`. Log the updates and seconds the
  first data took. When none came, an error: "omni.syntheticdata is not loaded" or "Instance segmentation gave no
  data within 5 s of enabling it". The colouring and legend are unchanged.
- **`handle_camera_inspect`:**
  - a `Budget(CALL_SECONDS)` at its start; each angle's settle, capture and segmentation run under it;
  - an error that `stops_the_call` ends the capturing: each later angle gets `{"angle": ..., "error": "Not
    captured: <reason>"}` at once;
  - a segmentation that failed once in a call is read without waiting at later angles;
  - `segmentation_error` beside the image when segmentation was asked for and none came;
  - the restore after `isolate` settles under its own `Budget(CLEANUP_SECONDS)`, an error there logged.
- **`handle_capture`:** a `Budget(CALL_SECONDS)`; segmentation with `SEGMENTATION_SECONDS`; `segmentation_error`
  beside `segmentation_base64: None`.
- **Recording:** no code change. Each frame's waits are now bounded (30 s, then 10 s), without a call budget; a frame
  that fails is the empty marker, as today.
- **`_init_sensors`** stays: until a stage opens, it spares the first capture the wait.

All of it runs on Kit's event loop: `asyncio.wait_for` makes a task on the same loop, no thread (`AGENTS.md`, Traps).

**The server, `src/omniverse_mcp/tools/camera.py`:** `inspect_prim` adds ` | seg: ERROR <segmentation_error>` to an
angle's line; `capture_viewport` prints `Segmentation: ERROR <reason>` when the bridge gives one, and today's line
when it does not (an older extension).

### Time bounds against the server's 120 s

The server's `BridgeClient` sets `timeout=120.0` as the socket's timeout, and the bridge sends nothing until a handler
returns, so 120 s bounds each call.

| Path | Bound | Worst case |
|---|---|---|
| one frame: a settle's, a reset's, `wait_for_result` | `FRAME_SECONDS`, 30 s, capped by the call's time | |
| the file after the frame | `FILE_SECONDS`, 10 s | |
| segmentation after enabling it | `SEGMENTATION_SECONDS`, 5 s, once per call | |
| `inspect_prim`, `capture_viewport` | `CALL_SECONDS`, 80 s, then `CLEANUP_SECONDS`, 10 s | about 90 s, leaving 30 s for encoding and the transfer |
| `inspect_prim(angles=["all"])`, every result `[]` | each angle fails at once | 14 settles of 20 frames: seconds, where it was 140 s |
| a viewport that renders nothing | the first `NoFrame` stops the call | about 30 s, where it hung |
| Kit 110's missing resource: the AOV named, no file | 10 s per angle | 80 s, the rest "Not captured" |
| `set_camera`, `look_at_prim`, `viewport_light` | 30 s for the settle or reset | about 30 s, where they hung |
| a recording frame | 30 s, then 10 s | 40 s, then the empty marker |

A unit test holds `CALL_SECONDS + CLEANUP_SECONDS + 20 <= BridgeClient`'s default timeout, so the two can't drift
apart unseen.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Retry an empty result once | `[]` means the frame had no colour AOV, which the next frame of the same render product won't change, and #35 asks to fail at once. The cold-run logs will show if a cold start ever gives one |
| One timeout around the whole handler | cancelling mid-angle loses the angles already captured, and runs the restore of hidden prims under cancellation; per-wait bounds keep each angle's result |
| An extension setting for the times | settings are a one-way door; constants can change in a minor |
| Enable the sensor again on Kit's stage-opened event | `omni.syntheticdata` resets on the same event, and the order of two subscribers is not defined |
| Replicator's `instance_segmentation` annotator | the modern API, but a bigger change: other legend IDs, and `omni.replicator.core`, which not every Kit app has. Worth its own issue |
| `wait_async_capture()` | blocks Kit's main thread until the write ends, or forever |
| A larger `SEGMENTATION_RETRY_FRAMES` | a count of updates is what failed for the file |

### For the maintainer

| | Question | Recommended |
|---|---|---|
| Q1 | The numbers: 30 s a frame, 10 s the file, 5 s segmentation, 80 s a call, 10 s cleanup | as written; `FRAME_SECONDS` goes up if a cold run logs a first frame over 10 s |
| Q2 | An empty result: fail at once, or retry once | at once, as #35 says |
| Q3 | After "no frame", stop the call's other angles, or try each until the 80 s run out | stop: a viewport that rendered nothing for 30 s answers in 30 s, not 80 |
| Q4 | `set_camera`, `look_at_prim` and `viewport_light` share the bounded settle and reset, so they stop hanging too | yes; they answer as today, with a log line |
| Q5 | Close #27 with this PR, or keep it open for more cold runs | `Closes #27` once three cold runs pass with the new logs |
| Q6 | A run on Isaac Sim 5.1 (Kit 107), which is installed at `D:\isaacsim5.1` | yes, one cold and one warm run, if you start it (its EULA) |

## Compatibility

- **One-way doors:** none. Tool names, schemas and annotations are unchanged (`tests/fixtures/mcp-tools.json`
  untouched, no `golden.py` run); routes, the auth header, the token file, protocol 1, the extension id and its
  settings are unchanged; no new setting.
- **The wire:** the bridge's answers gain an optional `segmentation_error`. An older server ignores it; a newer server
  with an older extension prints today's text.
- **What users notice:**
  - more specific errors, such as "Kit captured nothing (wait_for_result gave [])" or "The viewport rendered no frame
    in 30 s", where they saw "Viewport capture produced no output" or a timeout;
  - `inspect_prim` returns the angles it captured and "Not captured" for the rest, where it timed out;
  - a segmentation error where segmentation went missing without a word;
  - `set_camera`, `look_at_prim` and `viewport_light` answer after 30 s on a viewport that renders nothing, where they
    hung.
- **Kit apps:** the same paths on Kit 107 and 110, compared in their sources above. Nothing to move over.

## Steps

Each step is a commit on `27-capture-first-call`, after this plan.

1. **The core module:** `ovmcp/core/capture.py` and `tests/test_capture.py` (Tests). `uv run tools/gate.py quick`.
2. **The bounded waits in the bridge:** `capture_viewport_png`, `_settle_viewport`, `_reset_renderer` on the core;
   `set_camera`, `look_at_prim` and `viewport_light` catch a `CaptureError`. Live: `test_15e`, and the camera and
   lighting tests.
3. **The capture handlers:** `handle_camera_inspect` and `handle_capture` with the budget, the stop rule, async
   segmentation with its error, and the log lines. Live: `test_15c`, `test_15d`, `test_17_03`, and `test_13`,
   `test_15b`, `test_22_*`.
4. **The server's text** for `segmentation_error`, with its tests in `tests/test_tools_camera.py`.
5. **The docs** (Docs).
6. **The live runs**, by the main session (Tests): warm, the new tests against `main`'s extension, three cold starts,
   Isaac Sim 5.1 if Q6 is yes. Then `uv run tools/gate.py full` and finish-work.

## Tests

**Unit, without Kit (`tests/test_capture.py`, in CI):** fakes for Kit's capture object (a future set later, the way
`_set_completed` does), a fake clock, a fake file reader; `asyncio.run`, as `tests/test_serial.py` does.

| Test | Shows |
|---|---|
| `test_a_capture_returns_the_png_once_the_file_is_whole` | a partial file is not read; the whole one is, after the updates it took |
| `test_an_empty_result_fails_at_once` (`[]`, `None`) | `CaptureError` naming the result, with no file read and no update awaited; fails on today's loop, which waits `FILE_SECONDS` |
| `test_no_render_texture_is_an_error` | `schedule()` giving `None` is a `CaptureError`, not an `AttributeError` |
| `test_a_frame_that_never_comes_is_no_frame` | `NoFrame` after the bound (0.05 s in the test); Kit's future is cancelled, and setting it later raises nothing |
| `test_a_file_that_never_comes_fails_after_file_seconds` | `CaptureError` on the fake clock |
| `test_capture_errors_are_runtime_errors` | recording's `except RuntimeError` still holds; no `TimeoutError` escapes |
| `test_the_budget_caps_each_wait_and_says_out_of_time` | a wait cut short by the budget is `OutOfTime`, not `NoFrame`; a spent budget starts no capture |
| `test_frames_bounds_each_frame` | `frames()` raises `NoFrame` on the one slow frame |
| `test_poll_returns_the_first_ready_value_or_none` | `poll` stops at the first ready read, and gives `None` after its time |
| `test_stops_the_call` | `NoFrame` and `OutOfTime` stop it; other `CaptureError`s do not |
| `test_the_waits_read_their_seconds_when_called` | a patched `FRAME_SECONDS` takes effect, as the live test needs |
| `test_a_call_ends_before_the_server_gives_up` | `CALL_SECONDS + CLEANUP_SECONDS + 20` is within `BridgeClient`'s default timeout |

**Unit, the server (`tests/test_tools_camera.py`):** `inspect_prim` prints an angle's `segmentation_error`;
`capture_viewport` prints the bridge's reason, and today's line when there is none.

**Live, new (each restores what it changes in `finally`, through `/execute`, which is not behind the viewport lock,
so the restore gets through even past a stuck capture):**

| Test | Does | On `main`'s extension |
|---|---|---|
| `test_integration.py::test_15c_inspect_says_why_segmentation_is_missing` | patches `omni.syntheticdata.sensors.get_instance_segmentation` to give an empty array; `inspect_prim(["front", "right"], include_segmentation=True)` returns both images, each with `segmentation_error`, in under 15 s | fails: no `segmentation_error` |
| `test_integration.py::test_15d_an_empty_capture_fails_at_once` | patches `omni.kit.viewport.utility.capture_viewport_to_file` with a capture whose `wait_for_result` gives `[]`; all 14 angles come back with an error naming it, in under 20 s | fails: 140 s, past the test client's 30 s |
| `test_integration.py::test_15e_a_viewport_that_renders_nothing_fails_in_time` | sets `updates_enabled = False` on the active viewport and `ovmcp.core.capture.FRAME_SECONDS = 3`; first asserts a frame wait times out; `inspect_prim` over 3 angles returns in under 15 s, the first angle's error saying no frame, the others "Not captured"; after the restore, `capture_viewport` succeeds | fails: hangs past the client's timeout |
| `test_scenarios.py::test_17_03_segmentation_after_a_new_stage`, and 17.3 in `test_project/scenarios.md` | right after `test_17_02`'s `new_scene`, reads the sensor through `execute_script` and asserts it empty (Kit's reset, the mechanism above); then a cube, and `capture_viewport` returns segmentation with the cube in its legend | the first part passes, the second may |

**Live, existing:** `test_13`, `test_15b` (each frame its own angle, with the new capture), `test_22_*` unchanged, as
#27 asks.

**What the live run must show:**

- **Warm,** Isaac Sim 6.2 on port 8212: the live suites with `-k "not test_10_ and not test_14_"` (#5) pass as on
  `main`, with #6's and #7's known failures, plus the four new tests; `test_15c`, `test_15d` and `test_15e` fail once
  against `main`'s extension, so each reproduces its bug.
- **Cold, three times:** Kit started fresh, the live suites first thing. `test_13` and `test_22_01` pass each time.
  `get_logs(search="[MCP Bridge]")` after each run gives the time to the first frame and file of the slow captures,
  and the updates and seconds of each segmentation enabled (at startup, and after `test_17_02`); no capture error
  lines. Record the numbers in the PR: they answer Q1 and confirm or rule out the segmentation race.
- **Timing:** a default 14-angle `inspect_prim` takes as long as on `main` (no slower path when nothing fails).
- **Isaac Sim 5.1** (Q6): one cold and one warm run of the same.

**What neither can show:** Kit 110's missing-resource branch (no way found to cause it on demand); a Kit app with a
window, where Eco Mode and a hidden viewport are likelier; a GPU slow enough to need more than 30 s for one frame
after the first.

## Docs

| File | Change |
|---|---|
| `docs/TOOLS.md` | `inspect_prim`: the 80 s limit, "Not captured" angles, the segmentation error. `capture_viewport`: the segmentation note says the answer gives the reason |
| `docs/ARCHITECTURE.md` | Viewport Capture: the bounds, failing at once on an empty result, the call limit against the client's 120 s, `ovmcp.core.capture`. Extension Lifecycle: Kit resets the sensor on every stage open, and a capture enables it again. Threading Model, item 4: each wait bounded. The client's "A 120-second timeout" bullet: the bridge's capture calls answer within about 90 s |
| `README.md` | Known issues: the #27 and #35 lines go |
| `CHANGELOG.md` | Unreleased, Fixed: one line for #35 (fails at once, bounded, the call limit, partial answers), one for #27 (segmentation after a stage opens waits by time, and says why when none comes) |
| `AGENTS.md` | the extension row names `capture waits` among `ovmcp/core/`'s modules. Traps: the segmentation row's guard becomes "enabled again when empty (Kit resets it on every stage open), read each update for up to 5 s, an error when none comes"; a new row: "Render waits counted updates (too few on a cold start) or had no bound (a stalled viewport hung the call) \| #27, #35 \| Waits by time, each bounded, a call limit under the server's 120 s (`ovmcp.core.capture`)". 146 lines now, 147 after |
| `plugin/skills/scene/SKILL.md` | the "Segmentation missing or empty" trap: the answer now says why; through write-skill's rules |
| `test_project/scenarios.md` | 17.3, for `test_17_03` |

## Risks

| Risk | Status |
|---|---|
| 30 s is too short for a cold first frame: S2's run saw a cold first capture take over 30 s in all (modernization plan, progress log) | Accepted, checked: the cold runs log the time to each first frame; `FRAME_SECONDS` goes up if any is over 10 s (Q1). The bound is per frame, so a slow but working renderer passes |
| `updates_enabled = False` may not stop frames in some Kit app | Resolved by the live run: `test_15e` asserts it first, and says so if not |
| A capture abandoned after `NoFrame` stays queued in Kit, and writes its file when the viewport renders again: one temp file per abandoned capture | Accepted: the name is unique and never read; only a stalled viewport causes it |
| A cancelled frame wait leaves a frame subscription that does nothing until it is garbage collected | Accepted: cheap, and only on a stall |
| Eco Mode on a static scene can pause rendering | Accepted: it hung before; now it fails after 30 s, and `NoFrame`'s message names Eco Mode. Lifting it for captures is a later issue if anyone hits it |
| Time spent waiting for the viewport lock is outside the call's budget | Accepted: the server's client sends one request at a time; only a script's or a second client's capture can queue |
| The scenario client's 10 s timeout is shorter than a slow cold `inspect` | Accepted, unchanged as #27 asks; the cold runs show whether it bites |
| The live tests patch Kit modules and a constant | Resolved: each restores in `finally` through `/execute`; constants are read when called, pinned by a unit test |
| The silent `except Exception: pass` in `inspect`'s segmentation hid #27's cause | Resolved: the error goes into the answer and the log |

## Plan review

None yet: drafted on 2026-10-29, not yet reviewed with `review-plan`.
