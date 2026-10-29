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

| | What | Issue | Shown by |
|---|---|---|---|
| 1 | A capture whose `wait_for_result` names nothing captured (`[]` or `None`) fails at once, not after ten seconds | #35 | `test_15e` |
| 2 | No wait in the capture path is unbounded: a viewport that renders nothing fails after 30 s instead of hanging the call and the viewport lock | #35 | `test_15f` |
| 3 | `inspect_prim` and `capture_viewport` answer within about 90 s, under the server's 120 s, and name each angle they did not capture | #35 | unit tests, `test_15f` |
| 4 | Segmentation that is late after the sensor is enabled is waited for by time (up to 5 s, read each update), not dropped after 10 app updates, and an answer without it says why | #27 | `test_15c` (fails on `main`), `test_15d` |
| 5 | Three cold starts of Isaac Sim 6.2 pass `test_13_camera_inspect_auto_fit`, `test_17_03_segmentation_after_a_new_stage` (now the first segmentation on a new stage) and `test_22_01_inspect_with_segmentation` on their first run, with Kit's log showing how long the first frames and the first segmentation took | #27 | the cold runs |

Why it matters: an assistant whose capture stalls sees the server's timeout, not the reason, and every later viewport
request queues behind the held lock; a user's first segmentation after opening a stage can come back without it and
without a word.

- **In scope:** the capture path in the bridge (`handlers/_utils.py`, `handlers/camera.py`, and recording through
  the shared helper), a new Kit-free module for its waits and bookkeeping, the two camera tools' text for a
  segmentation error, the docs, live tests.
- **Out of scope:** moving segmentation to Replicator annotators; lifting Eco Mode for captures; the server's 120 s
  and the scenario client's 10 s timeouts; recording's ignored camera and size (#25); sweeping the temp files that
  abandoned captures leave (Risks); how `get_logs` reads Kit's log (#5).

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
| unittest sorts by name, so the scenario suite runs `test_17_02_new_scene` before phase 22: on `main`, test_22_01 is the first segmentation on a new stage | `tests/test_scenarios.py` |
| The handler's `_capture_instance_segmentation` reads the sensor and, when empty, enables it and reads again at once, which is empty by Kit's own account. `inspect` calls it, pumps 10 app updates, calls it again, and drops the segmentation if it is still empty: four reads in all | `camera.py` lines 382-388, 653 and 658, `SEGMENTATION_RETRY_FRAMES = 10`; Kit's `create_or_retrieve_sensor`: "the sensor will be uninitialized until a frame is rendered after the sensor is created" |

**The likely root cause:** a fixed count of app updates against a renderer whose time to its first frame varies, and
is longest on the first run after Kit starts: 10 updates for the colour file (gone since #33), and 10 for the
segmentation after a stage opens (still there, and silent).

**How the live run confirms it,** since it shows only on a first run after Kit starts: the bridge logs, for each
segmentation it enables, how many updates and seconds its first data took, and for each capture over 2 s how long
its frame and its file took. Three cold starts, the live suites first thing after each (Tests). If a segmentation
after a new stage (`test_17_03`) ever needed more than 10 updates, the latent race is shown; if never, #27 was all
the colour file. Either way the cold runs with the new code are the evidence to close #27 (Q5). `test_15c` shows the
late-segmentation fix on any Kit, cold or warm, by making the data late on purpose.

### What Kit's capture API does, on Kit 107 and 110

Read in Kit's sources on this machine: Isaac Sim 6.2.0 (`D:\isaac\venv`, Kit 110: `omni.kit.widget.viewport`
110.0.1, `omni.kit.viewport.utility` 2.1.2, `omni.usd` 1.19.11, `omni.syntheticdata` 0.6.17) and Isaac Sim 5.1.0
(`D:\isaacsim5.1`, Kit 107: 107.1.3, 1.1.2, 1.13.10, 0.6.13). Both behave the same where this plan relies on them,
unless the row says otherwise.

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
| `ViewportAPI.wait_for_rendered_frames(n)`, used by `_settle_viewport` today | not used for the new waits. `__subscribe_to_change` calls the callback at once on subscribe ("If we're in a valid state, invoke the callback now"), so `n=1` returns before any frame renders. Its callback clears the subscription only inside `if (additional_frames <= 0) and (not future.done())`, so a cancelled wait's callback stays in the viewport's `__frame_changed` set for good, run on every frame | `api.py`, Kit 107 and 110 |
| `next_viewport_frame_async(viewport, n)`, the per-frame wait used instead | awaits `usd_context.next_frame_async(viewport, n)`, which is omni.usd's `_next_frame_async`: it observes `NEW_FRAME` for this viewport's handle, sets its future only `if not f.done()`, calls nothing on subscribe, and holds its subscription in a local, so a cancelled wait drops it when the coroutine ends | `omni/kit/viewport/utility/__init__.py`; `omni/usd/_impl/__init__.py`, the same text in 1.13.10 and 1.19.11 |
| `ViewportAPI.updates_enabled = False` | calls the hydra texture's `set_updates_enabled(False)`: a real way to get a viewport that renders nothing, for a live test | `api.py`, both Kits |
| `IRendererCapture.wait_async_capture()` | "Wait for asynchronous capture to complete", synchronous: it would block Kit's main thread | `omni/kit/renderer_capture/_renderer_capture.pyi` |
| `sensors.enable_sensors` | `activate_node_template(..., [viewport.render_product_path])`, which returns at once for a node already active (`if node_path in self._activatedNodePaths: return`): enabling again is harmless. The sensors API is marked deprecated, the async `create_or_retrieve_sensor_async` waiting at most 50 updates | `omni/syntheticdata/scripts/sensors.py`, `SyntheticData.py` |
| `get_instance_segmentation` | an empty `(0, 0)` array until the node has data | `get_sensor_array` |
| a stage's identity | `usd_context.get_stage_id()`, as Kit's own `capture_viewport_to_file` uses it; a new or opened stage has a new id | `omni/kit/viewport/utility/__init__.py` |
| Python | Kit 107 embeds 3.11 (`python311.dll`), Kit 110's extensions are `cp312`. Since 3.11 `asyncio.TimeoutError` is `TimeoutError`, an `OSError`, not a `RuntimeError` | the installs; Python 3.11's changelog |
| timers on Kit's loop | `asyncio.wait_for` and `call_later` run there: the bridge's `core/http.py` already uses `wait_for` on it. They fire only when the loop runs (Risks) | `ovmcp/core/http.py` |

### The change

One Kit-free module holds every wait the capture path makes, each bounded by time, and the bookkeeping of a call;
the handlers wire Kit into it.

**`extension/ovmcp.bridge/ovmcp/core/capture.py`, new, no Kit (import-linter's contract holds):**

| Name | What |
|---|---|
| `CaptureError(RuntimeError)` | a capture that gave no image, its message saying which step and for how long; recording's `except RuntimeError` still catches it |
| `NoFrame(CaptureError)` | the viewport delivered no frame within `FRAME_SECONDS`; the message names the likely reasons (updates off, a hidden viewport, Eco Mode on a static scene) |
| `OutOfTime(CaptureError)` | the call's time ran out |
| `Budget(seconds, clock=time.monotonic)` | the time a call may spend; caps each wait at what is left |
| `bounded(awaitable, seconds, budget)` | the awaitable within the shorter of `seconds` and what is left, through `asyncio.wait_for`; its `TimeoutError` becomes `NoFrame`, or `OutOfTime` when the budget was the shorter bound |
| `frames(next_frame, count, budget)` | `count` frames, each through `bounded(next_frame(), FRAME_SECONDS, ...)`; the bridge passes `lambda: next_viewport_frame_async(viewport, 1)` |
| `poll(read, ready, next_update, seconds, budget, clock)` | `read()` after each update until `ready(value)`; `None` once the time is up |
| `capture_png(schedule, read_file, next_update, budget)` | `schedule()` (`None`: `CaptureError`, the viewport has no render texture yet); `wait_for_result()` through `bounded`; a result of `[]` or `None`: `CaptureError` at once, naming the result (#35); otherwise `poll` the file for a whole PNG (`is_complete_png`) for `FILE_SECONDS` |
| `Call(seconds)` | one inspect or capture call: its `Budget`, and what stopped it. `failed(error)` keeps the kind and message of a `NoFrame` or `OutOfTime`, since the next angle would wait the same; never the exception, whose traceback would hold the cancelled frame wait's coroutine and its subscription; `skipped(angle)` gives that angle's `{"angle": ..., "error": "Not captured: <reason>"}` once stopped, else `None`; `settle_after_restore()` says whether the restore after `isolate` should settle (not after a `NoFrame`) |
| `SegmentationWaits` | per (stage id, render product path): `seconds(key)` is `SEGMENTATION_SECONDS`, or 0 once a wait there ended with no data; `failed(key)` records that; `got_data(key)` clears it. A new or opened stage has a new key, so it waits afresh |
| constants | `FRAME_SECONDS = 30`, `FILE_SECONDS = 10` (today's `CAPTURE_TIMEOUT_SECONDS`), `SEGMENTATION_SECONDS = 5`, `CALL_SECONDS = 80`, `CLEANUP_SECONDS = 10`. Read when a function runs, never bound as defaults, so a live test can shorten one through `execute_script` |

**The bridge, `extension/ovmcp.bridge/ovmcp/bridge/handlers/`:**

- **`_utils.capture_viewport_png(viewport, budget=None)`:** `capture_png` with Kit's `capture_viewport_to_file`, the
  fresh `ovmcp_capture_<uuid>.png`, and `_next_update`. The file is deleted in `finally`, as today. A failure is
  logged as a warning with its step and seconds; a capture over 2 s logs its frame and file times at info.
- **`_settle_viewport` and `_reset_renderer`:** wait frame by frame through `frames()` on
  `next_viewport_frame_async(viewport, 1)`, not `wait_for_rendered_frames` (the API table), with Eco Mode put back
  in a `finally`. Without a call budget, a settle or reset gets one of `FRAME_SECONDS` for all its frames. They raise
  `NoFrame` or `OutOfTime`: `set_camera`, `look_at_prim` and `viewport_light` catch it, log it and answer as today,
  where they hung; the capture handlers let it through. Without `omni.kit.viewport.utility`, they pump app updates,
  as today.
- **`camera._capture_frame(camera_path, width, height, budget=None)`:** as today, the budget passed down; no
  black-frame retry after an error.
- **Segmentation, `camera._segmentation(viewport, budget) -> (png, legend, error)`:** async, in place of
  `_capture_instance_segmentation`, its inline enable and both retry blocks.
  - Read the sensor. Data: `got_data(key)`, done.
  - Empty: enable it (harmless when already on) and `poll` it after each app update for `seconds(key)`. Log the
    updates and seconds the first data took, or that none came.
  - Still empty: `failed(key)`, and an error that says what to do: "Instance segmentation gave no data within 5 s
    of enabling it: capture again, and if it stays empty, get_logs(search="syntheticdata") shows why"; after an
    earlier failure on the same stage, without waiting: "Instance segmentation gave no data on this stage, as
    before, so this capture did not wait: capture again in a few seconds; get_logs(search="syntheticdata") shows
    why"; without the module: "omni.syntheticdata is not loaded: enable it with manage_extensions". None points at
    a new stage, which would throw the user's scene away: every call reads the sensor first, so data that starts
    flowing is picked up on the same stage.
  - The colouring and the legend are unchanged.
- **`handle_camera_inspect`:**
  - a `Call(CALL_SECONDS)` at its start; each angle's settle, capture and segmentation run under its budget;
  - an angle whose `skipped()` gives an entry gets it at once, with no capture;
  - each error goes through `failed()`; other errors stay that angle's, as today;
  - a `NoFrame` in the settle after hiding prims for `isolate` stops the call before any angle: every angle is
    "Not captured", the prims are restored in `finally` as today, and the restore does not settle;
  - `segmentation_error` beside the image when segmentation was asked for and none came;
  - the restore after `isolate` settles under its own `Budget(CLEANUP_SECONDS)` unless the call stopped on a
    `NoFrame`, an error there logged.
- **`handle_capture`:** a `Call(CALL_SECONDS)`; segmentation through `_segmentation`, so a viewport that gave none
  costs the wait once per stage, not on every call; `segmentation_error` beside `segmentation_base64: None`.
- **Recording:** no code change. Each frame's waits are now bounded (30 s, then 10 s), without a call budget; a frame
  that fails is the empty marker, as today.
- **`_init_sensors`** stays as it is: it enables the sensor once at startup, without polling or a timing line, and
  spares the first capture the wait until a stage opens.

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
| segmentation after enabling it | `SEGMENTATION_SECONDS`, 5 s; none again on that stage after a wait that got nothing | |
| `inspect_prim`, `capture_viewport` | `CALL_SECONDS`, 80 s, then `CLEANUP_SECONDS`, 10 s | about 90 s, leaving 30 s for encoding and the transfer |
| `inspect_prim(angles=["all"])`, every result `[]` | each angle fails at once | 14 settles of 20 frames: seconds, where it was 140 s |
| a viewport that renders nothing | the first `NoFrame` stops the call; no settle after the restore | about 30 s, where it hung |
| Kit 110's missing resource: the AOV named, no file | 10 s per angle | 80 s, the rest "Not captured" |
| `set_camera`, `look_at_prim`, `viewport_light` | 30 s for the settle or reset | about 30 s, where they hung |
| a recording frame | 30 s, then 10 s | 40 s, then the empty marker |

A unit test holds `CALL_SECONDS + CLEANUP_SECONDS + 20 <= BridgeClient`'s default timeout, so the two can't drift
apart unseen. The bounds are timers on Kit's loop, so a stalled main thread delays them (Risks).

### Alternatives considered

| Alternative | Why not |
|---|---|
| Retry an empty result once | `[]` means the frame had no colour AOV, which the next frame of the same render product won't change, and #35 asks to fail at once. The cold-run logs will show if a cold start ever gives one |
| One timeout around the whole handler | cancelling mid-angle loses the angles already captured, and runs the restore of hidden prims under cancellation; per-wait bounds keep each angle's result |
| `ViewportAPI.wait_for_rendered_frames` for the per-frame wait | it counts the call it makes on subscribe as a frame, and a cancelled wait leaves its callback in the viewport for good (the API table) |
| Wait for segmentation only when this call enabled the sensor | needs to know whether it was already on, which only `omni.syntheticdata`'s internals say; remembering a failed wait per stage gives the same cost (one wait per stage) from the bridge's own state |
| An extension setting for the times | settings are a one-way door; constants can change in a minor |
| Enable the sensor again on Kit's stage-opened event | `omni.syntheticdata` resets on the same event, and the order of two subscribers is not defined |
| Replicator's `instance_segmentation` annotator | the modern API, but a bigger change: other legend IDs, and `omni.replicator.core`, which not every Kit app has. Worth its own issue |
| `wait_async_capture()` | blocks Kit's main thread until the write ends, or forever |
| A larger `SEGMENTATION_RETRY_FRAMES` | a count of updates is what failed for the file |

### For the maintainer

| | Question | Recommended |
|---|---|---|
| Q1 | The numbers: 30 s a frame, 10 s the file, 5 s segmentation, 80 s a call, 10 s cleanup | as written; `FRAME_SECONDS` goes up if a cold run logs a first frame over 10 s, or any `NoFrame` |
| Q2 | An empty result: fail at once, or retry once | at once, as #35 says |
| Q3 | After "no frame", stop the call's other angles, or try each until the 80 s run out | stop: a viewport that rendered nothing for 30 s answers in 30 s, not 80 |
| Q4 | `set_camera`, `look_at_prim` and `viewport_light` share the bounded settle and reset, so they stop hanging too | yes; they answer as today, with a log line; `test_15f` checks `set_camera` |
| Q5 | Close #27 with this PR, or keep it open for more cold runs | `Closes #27` once three cold runs pass with the new logs; then README's #27 line goes too |
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
  - a segmentation error that says what to do, where segmentation went missing without a word;
  - `set_camera`, `look_at_prim` and `viewport_light` answer after 30 s on a viewport that renders nothing, where they
    hung.
- **Kit apps:** the same paths on Kit 107 and 110, compared in their sources above. Nothing to move over.

## Steps

Each step is a commit on `27-capture-first-call`, after this plan.

1. **The core module:** `ovmcp/core/capture.py` and `tests/test_capture.py` (Tests). `uv run tools/gate.py quick`.
2. **The bounded waits in the bridge:** `capture_viewport_png`, `_settle_viewport` and `_reset_renderer` on the
   core, the per-frame wait on `next_viewport_frame_async`; `set_camera`, `look_at_prim` and `viewport_light` catch a
   `CaptureError`. Checked by the unit tests, and live by the existing camera and lighting tests (`test_11` to
   `test_18`), warm.
3. **The capture handlers:** `handle_camera_inspect` and `handle_capture` with `Call`, async segmentation with
   `SegmentationWaits` and its error, and the log lines. Live: `test_15c` to `test_15f` (the stop rule and the
   bounded `set_camera` together in `test_15f`), `test_17_03`, and `test_13`, `test_15b`, `test_22_*`.
4. **The server's text** for `segmentation_error`, with its tests in `tests/test_tools_camera.py`.
5. **The docs** (Docs).
6. **The live runs**, by the main session (Tests): warm, the new tests against `main`'s extension, three cold starts,
   Isaac Sim 5.1 if Q6 is yes. Then finish-work: `uv run tools/gate.py full`, `review-code` until clean, the PR.

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
| `test_a_call_stops_on_no_frame_and_out_of_time` | `Call.failed` keeps those two, not other `CaptureError`s, and keeps their message, not the exception; `skipped` then gives each later angle its "Not captured" entry; no settle after the restore once stopped on `NoFrame` |
| `test_segmentation_waits_once_per_stage_until_data` | `seconds` is 5 for a new key, 0 after `failed`, 5 again after `got_data` or for another stage's key |
| `test_the_waits_read_their_seconds_when_called` | a patched `FRAME_SECONDS` takes effect, as the live test needs |
| `test_a_call_ends_before_the_server_gives_up` | `CALL_SECONDS + CLEANUP_SECONDS + 20` is within `BridgeClient`'s default timeout |

**Unit, the server (`tests/test_tools_camera.py`):** `inspect_prim` prints an angle's `segmentation_error`;
`capture_viewport` prints the bridge's reason, and today's line when there is none.

**Live, new.** Each changes Kit only through `/execute`, which is not behind the viewport lock, and undoes it in
`finally`; each patch also schedules its own undo on Kit's loop (`call_later`, 60 s), in case the test process dies
before its `finally`. An undo puts the original back only while the attribute is still that test's own wrapper
(`if module.attr is wrapper`), so a late undo never removes a later test's patch.

| Test | Does | On `main`'s extension |
|---|---|---|
| `test_integration.py::test_15c_segmentation_that_comes_late_is_waited_for` | wraps `omni.syntheticdata.sensors.get_instance_segmentation` to give an empty array for its first 15 reads, then the real data; `inspect_prim(["front"], include_segmentation=True)` returns `segmentation_base64` and no `segmentation_error`, and the wrapper counts at least 16 reads (the 15 empty ones, then the real one). No failed wait is on record for the stage: the suite's warmup capture reads real data, which clears one a previous run's `test_15d` left | fails: `main` reads four times (each of its two calls reads, then enables and reads) and drops the segmentation |
| `test_integration.py::test_15d_inspect_says_why_segmentation_is_missing` | the same wrapper, always empty; `inspect_prim(["front", "right"], include_segmentation=True)` returns both images, each with a `segmentation_error`: the first's says no data came within 5 s, the second's is the "as before, so this capture did not wait" text, which tells one wait from two; under 15 s, a guard against a hang | fails: no `segmentation_error` |
| `test_integration.py::test_15e_an_empty_capture_fails_at_once` | patches `omni.kit.viewport.utility.capture_viewport_to_file` with a capture whose `wait_for_result` gives `[]`: `inspect_prim` over 4 angles returns each with an error naming it, in under 15 s. Then a capture that names `LdrColor` but writes no file (Kit 110's missing resource), with `FILE_SECONDS = 2` if `ovmcp.core.capture` exists: 3 angles, each an error after the file wait, in under 15 s | fails: 4 x 10 s, past the test client's 30 s |
| `test_integration.py::test_15f_a_viewport_that_renders_nothing_fails_in_time` | sets `updates_enabled = False` on the active viewport, and `FRAME_SECONDS = 3` only if `ovmcp.core.capture` exists. Asserts through Kit's own API that no frame comes: `asyncio.wait_for(next_viewport_frame_async(vp, 1), 3)` times out. Then `set_camera` answers within `FRAME_SECONDS` plus 5 s (Q4); `inspect_prim` over 3 angles returns in under 15 s, the first angle's error saying no frame, the others "Not captured"; after the restore, `capture_viewport` succeeds | fails for the right reason: `set_camera`, then `inspect_prim`, hang past the client's timeout |
| `test_scenarios.py::test_17_03_segmentation_after_a_new_stage`, and 17.3 in `test_project/scenarios.md` | right after `test_17_02`'s `new_scene`, reads the sensor through `execute_script` and asserts it empty (Kit's reset, the mechanism above); then a cube, `inspect_prim(["front"], include_segmentation=True)` with segmentation and the cube in its legend, and the cube deleted at the end. Now the first segmentation on a new stage in the suite | the first part passes; the second may, as `main` passes on a warm Kit |

**Live, existing:** `test_13`, `test_15b` (each frame its own angle, with the new capture), `test_22_*` unchanged, as
#27 asks.

**What the live run must show:**

- **Warm,** Isaac Sim 6.2 on port 8212: the live suites with `-k "not test_10_ and not test_14_"` (#5) pass as on
  `main`, with #6's and #7's known failures, plus the five new tests. `test_15c` to `test_15f` fail once against
  `main`'s extension, so each reproduces its bug.
- **Cold, three times:** Kit started fresh, the live suites first thing. `test_13`, `test_17_03` and `test_22_01`
  pass each time.
  - The timing lines (slow captures' frame and file times; each segmentation's updates and seconds after enabling,
    notably `test_17_03`'s on the new stage) are carb log lines, so they are in Kit's log file, and in whatever
    `get_logs` reads at the time: today the 2000-entry ring, which a full run can overflow; after #5's fix, Kit's
    log file. Read Kit's log file, or, while `get_logs` reads the ring, call it right after the warmup capture and
    right after `test_17_03`.
  - No capture error lines. Record the numbers in the PR: they answer Q1 and confirm or rule out the segmentation
    race.
- **Timing:** a default 14-angle `inspect_prim`, warm, on `main` and on the branch: the same within noise, and well
  under `CALL_SECONDS`; if `main`'s is over half of it, Q1 comes back to the maintainer.
- **Isaac Sim 5.1** (Q6): one cold and one warm run of the same.

**What neither can show:** Kit 110's missing resource as Kit itself causes it (`test_15e` fakes its effect); a Kit
app with a window, where Eco Mode and a hidden viewport are likelier; a GPU slow enough to need more than 30 s for
one frame after the first.

## Docs

| File | Change |
|---|---|
| `docs/TOOLS.md` | `inspect_prim`: the 80 s limit, "Not captured" angles, the segmentation error. `capture_viewport`: the segmentation note says the answer gives the reason |
| `docs/ARCHITECTURE.md` | the `ovmcp/core/` row of the module table: `capture.py` (the capture path's waits, each bounded by time, and a call's bookkeeping). Viewport Capture: the bounds, failing at once on an empty result, the call limit against the client's 120 s. Extension Lifecycle: Kit resets the sensor on every stage open, and a capture enables it again. Threading Model, item 4: each wait bounded. The client's "A 120-second timeout" bullet: the bridge's capture calls answer within about 90 s |
| `README.md` | Known issues: #35's line goes; #27's goes only if Q5 closes #27 |
| `CHANGELOG.md` | Unreleased, Fixed: one line for #35 (fails at once, bounded, the call limit, partial answers), one for #27 (late segmentation is waited for by time, and an answer without it says why) |
| `AGENTS.md` | the extension row names `capture waits` among `ovmcp/core/`'s modules. Traps: the segmentation row's guard becomes "enabled again when empty (Kit resets it on every stage open), read each update for up to 5 s, an error when none comes"; a new row: "Render waits counted updates (too few on a cold start) or had no bound (a stalled viewport hung the call) \| #27, #35 \| Waits by time, each bounded, a call limit under the server's 120 s (`ovmcp.core.capture`)". 146 lines now, 147 after |
| `plugin/skills/scene/SKILL.md` | the "Segmentation missing or empty" trap: the answer now says why; through write-skill's rules |
| `test_project/scenarios.md` | 17.3, for `test_17_03` |

## Risks

| Risk | Status |
|---|---|
| 30 s is too short for a cold first frame: S2's run saw a cold first capture take over 30 s in all (modernization plan, progress log) | Accepted, checked: the cold runs log the time to each first frame; `FRAME_SECONDS` goes up if any is over 10 s (Q1). The bound is per frame, so a slow but working renderer passes |
| The bounds are asyncio timers on Kit's loop: they fire only when the loop runs, so a main thread blocked by a shader compile or a long load delays them, and a call can outlast its budget in wall time. A frame wait that times out logs "no frame in 30 s", not the frame's real time | Accepted: nothing in the bridge can preempt Kit's main thread. The log lines carry wall-clock seconds, so a stall shows; any `NoFrame` in a cold run counts as evidence the bound is short (Q1) |
| `updates_enabled = False` may not stop frames in some Kit app | Resolved by the live run: `test_15f` asserts it through Kit's own frame wait first, and says so if not |
| A capture abandoned after `NoFrame` stays queued in Kit, and writes its file when the viewport renders again: one temp file per abandoned capture | Accepted: the name is unique and never read; only a stalled viewport causes it |
| A cancelled frame wait | Resolved: the per-frame wait is `next_viewport_frame_async`, whose subscription is a local that goes when the cancelled coroutine ends, as long as no stored exception's traceback holds that frame: `Call` keeps a message, not the exception. `wait_for_rendered_frames`, which would leave its callback in the viewport for good, is no longer used for these waits |
| Eco Mode on a static scene can pause rendering | Accepted: it hung before; now it fails after 30 s, and `NoFrame`'s message names Eco Mode. Lifting it for captures is a later issue if anyone hits it |
| Time spent waiting for the viewport lock is outside the call's budget | Accepted: the server's client sends one request at a time; only a script's or a second client's capture can queue |
| The scenario client's 10 s timeout is shorter than a slow cold `inspect` | Accepted, unchanged as #27 asks; the cold runs show whether it bites |
| A segmentation that failed once on a stage is not waited for again there, so one slow start costs later captures their wait | Accepted: the sensor stays on, so a later read gets the data as soon as it flows, and a read with data clears the record |
| The live tests patch Kit modules and constants | Resolved: each undoes it in `finally` through `/execute`, and schedules its own undo after 60 s; constants are read when called, pinned by a unit test; on `main`, where `ovmcp.core.capture` doesn't exist, the tests patch no constant |
| The silent `except Exception: pass` in `inspect`'s segmentation hid #27's cause | Resolved: the error goes into the answer and the log |

## Plan review

### Round 1

- **How:** review-plan, one fresh reviewer agent started by the main session (its model was not passed to the
  author), 2026-10-29, on `6129de2`.
- **Verdict:** needs-changes: one major, seven minors.
- **Now:** all eight fixed in `8caecab`; every improvement taken.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | Goal row 4 and Tests: #27's fix, waiting by time for late segmentation, had no test that fails on `main`: `test_17_03`'s second part may pass there, the old `test_15c` covered only the error path, and the unit test covered `poll`, not its use | fixed: `test_15c_segmentation_that_comes_late_is_waited_for` wraps `get_instance_segmentation` to be empty for 15 reads, then real; `main`'s reads drop it, the new poll gets it. Goal row 4 names it. The count of `main`'s reads is corrected in round 2 (P9) |
| P2 | minor | Design `frames()`, the API table, Risks: `wait_for_rendered_frames(1)` returns before a frame, since `__subscribe_to_change` calls the callback on subscribe, and a cancelled wait's callback stays in the viewport's `__frame_changed` set; "until it is garbage collected" was wrong | fixed: checked in `api.py` (Kit 107 and 110) and omni.usd's `_next_frame_async` (1.13.10 and 1.19.11, the same text). `frames()` uses `next_viewport_frame_async(viewport, 1)`; the API table says why not `wait_for_rendered_frames`; the Risk is corrected |
| P3 | minor | `test_15e` (now `test_15f`): on `main`, setting `ovmcp.core.capture.FRAME_SECONDS` raises `ImportError`, so it failed for the wrong reason | fixed: the constant is patched only if the module exists, the frame wait is asserted through `next_viewport_frame_async`, and on `main` the calls really hang |
| P4 | minor | Steps 2 and 3: step 2 named the test of step 3's stop rule; Q4's `set_camera` behaviour had no test | fixed: the test moved to step 3; step 2 is checked by the unit tests and the existing camera and lighting tests; `test_15f` calls `set_camera` with updates off and bounds its answer |
| P5 | minor | `test_17_03` re-enables the sensor, so `test_22_01` was no longer the first segmentation on a new stage; its cube was left behind | fixed: Goal row 5 and the cold-run evidence name `test_17_03`; it uses `inspect_prim` with segmentation, as #27's title, and deletes its cube |
| P6 | minor | `handle_capture`: `capture_viewport` always captures segmentation, so a viewport that never gives it would cost every call 5 s | fixed: `SegmentationWaits` remembers a wait that got nothing, per stage and render product, until a read gets data or a stage opens; the alternative of waiting only when this call enabled the sensor is in the Alternatives |
| P7 | minor | Risks: the bounds are timers on Kit's loop, held in loop time, not wall time; a first frame over 30 s is logged as 30 s | fixed: a Risk row. In detail, asyncio's clock is monotonic, but its timers fire only when Kit's loop runs, which a blocked main thread delays |
| P8 | minor | Docs and the cold-run evidence: (a) ARCHITECTURE's `ovmcp/core/` module list; (b) README's #27 line only if Q5 closes #27; (c) `_init_sensors` logs no startup timing, yet Tests expected one; (d) the 2000-entry log ring may drop the warmup's lines | fixed: (a) and (b) in Docs and Q5; (c) Tests expects timing only from captures, and the Design says `_init_sensors` is unchanged; (d) the timing is read from Kit's log file, or from `get_logs` right after the warmup and after `test_17_03` while it reads the ring, and after #5's fix from whatever `get_logs` then reads |

Refuted: none.

Owner calls: none from the review. The plan's own questions, Q1 to Q6 (Design, For the maintainer), wait for the
maintainer's approval.

Improvements:

| Improvement | Answer |
|---|---|
| Simulate Kit 110's missing-resource branch live with a fake capture that writes no file | taken: the second half of `test_15e` |
| Make each live patch heal itself after one call or a few seconds | taken: each schedules its own undo with `call_later`, 60 s; `test_15c`'s wrapper also heals after 15 reads |
| Move the per-angle bookkeeping into `ovmcp/core/` | taken: `Call` and `SegmentationWaits`, with their unit tests |
| Skip the isolate restore's settle after a `NoFrame` stop, and say what a `NoFrame` in the settle after hiding does | taken: Design, `handle_camera_inspect` |
| Give `test_15e` 3 or 4 angles | taken: 4, still past the test client's 30 s on `main` |
| Record `main`'s warm 14-angle inspect time against `CALL_SECONDS` | taken: What the live run must show, Timing |
| Make the segmentation error say what to do | taken: each of its three messages |

A fact from outside the review: #5 was traced live to a deadlock between Kit's main thread and the bridge's `omni.log`
consumer; its fix drops that consumer and has `get_logs` read Kit's log file. This plan's timing lines are carb log
lines, so they reach whatever `get_logs` reads, and Kit's log file in any case.

### Round 2

- **How:** review-plan, one fresh reviewer agent started by the main session (its model was not passed to the
  author), 2026-10-29, on `8caecab`: round 1's edits and its findings.
- **Verdict:** approved: no blocker or major; round 1's eight findings confirmed fixed; three minors.
- **Now:** the three minors fixed and the three improvements taken, in the commit after `8caecab`. `status` stays
  `draft` until the maintainer approves the plan and answers Q1 to Q6.

| # | Sev | Finding | Status |
|---|---|---|---|
| P9 | minor | The Design's "three reads in all" and `test_15c`: `main` reads four times, since `_capture_instance_segmentation` reads, then enables and reads (`camera.py` 382-388), and `inspect` calls it twice (653, 658); "more than 3 reads" passes on `main` | fixed: the Design row says four reads and cites the lines; `test_15c` asserts at least 16 reads, the 15 empty ones and the real one |
| P10 | minor | `test_15d`: "the second without a second wait, in under 15 s" can't tell one wait from two (two 5 s waits and the settles come to 11-12 s warm) | fixed: the second angle's `segmentation_error` must be the "as before, so this capture did not wait" text; the 15 s stays as a guard against a hang |
| P11 | minor | The `_segmentation` message "it is tried again after a new or opened stage" was wrong, since every call reads the sensor first and a read with data clears the record, and it pointed an assistant at `new_scene`, which throws away the user's scene | fixed: "Instance segmentation gave no data on this stage, as before, so this capture did not wait: capture again in a few seconds; get_logs(search="syntheticdata") shows why"; the Design says why no message points at a new stage |

Refuted: none.

Owner calls: none from the review.

Improvements:

| Improvement | Answer |
|---|---|
| `Call` keeps the stopping error's message, not the exception: on 3.12 a stored `NoFrame` chains to `_next_frame_async`'s frame and its `sub` | taken: Design (`Call`), its unit test, and the Risk on a cancelled frame wait |
| Each heal undoes only if the attribute is still its own wrapper | taken: Tests, Live, new |
| Goal row 3's "name each angle they did not capture" is shown by `test_15f`, not `test_15e` | taken |

Also in this commit: step 6 names `review-code` inside finish-work, as review-plan's verdict rule asks of a plan's
last step.
