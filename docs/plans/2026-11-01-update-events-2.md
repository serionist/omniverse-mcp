---
title: Move the bridge's update subscriptions to Kit's Events 2.0 update event
issue: "#122"
status: draft
approved_by:
approved_at:
---

# Move the bridge's update subscriptions to Kit's Events 2.0 update event

The bridge subscribes to Kit's app update in three places through `get_update_event_stream()`, which Kit wraps as
deprecated: each call writes a notice with a call stack into Kit's log, which `get_logs` and every bug report then
read. Kit 107 and Kit 110 both have the replacement, an observer of `omni.kit.app.GLOBAL_EVENT_UPDATE` through
`carb.eventdispatcher`, and Kit's own `next_update_async`, which every capture already awaits, uses it on both. This
plan moves the three to it at the place in the update they hold today, and adds a guard so none comes back.

The code waits until #114 (the capture path, `camera_feed.py`) and #111 (the recorder's clock, `recording.py`) merge,
then rebases onto them.

## Goal

| Row | Where | True when done | Shown by |
|---|---|---|---|
| U1 | A recording's tick, `handlers/recording.py` | Observes Kit's update event, called once an update on Kit's main thread at the same place in the update as now; dropped when the recording ends or the extension shuts down | `tests/test_recording_handler.py`; live `test_06_*`, `test_17_05` |
| U2 | A drawing's expiry watch, `handlers/debug_draw.py` | The same, while the book holds a drawing or owes a clear | `tests/test_debug_draw_handler.py`; live `test_16_*`, `test_17_03` |
| U3 | A dropped feed's render product watch, `handlers/camera_feed.py` | The same, while a render product waits for an open stage | `tests/test_camera_feed.py`; live `test_17_05` |
| U4 | Any update subscription #114 or #111 adds before the rebase | The same | Its handler's tests |
| U5 | The extension's files | Name none of the app event streams Kit wraps as deprecated (K1); CI fails on one (Q5) | `tests/test_updates.py` |
| U6 | Kit's log | A recording, a recording stopped by a new stage and a drawing log no "Use Events 2.0" notice naming the bridge's files (Q6) | live `test_17_08` (new); the count in a live-suite run's log, before and after |

Why:

- The notices are the bridge's own noise in the log users and agents read: 326 of them in the 31 Isaac Sim 6.2 logs
  of 2026-11-01 on this machine (L1), and five of 50 hits of scenario 24.3's `get_logs(search="MCP")` (L2).
- A Kit that drops the stream would break recordings, drawings and the render product cleanup at once.

| In scope | Out of scope |
|---|---|
| The three subscriptions, and any update subscription #114 or #111 adds | The feed's drawable-changed subscription: Events 2.0 already where Kit has it (Kit 108.2 and later), the texture's own stream on Kit 107, which has no other (C6) |
| One helper for them (Q1), its test and a CI guard (Q5) | The waits: `next_update_async` is Kit's own and already observes the update event (K5) |
| A live test of Kit's log (Q6) | The two notices Kit's own extensions log at each start (L1), and any other deprecation Kit logs |

## What the code, Kit and the logs say

### The code, at `84acfa5`

| # | Where | What it does |
|---|---|---|
| C1 | `handlers/camera_feed.py:149-179`, `_Leftovers` | `add()` deletes a dropped feed's render product from the open stage at once; only when the stage is closing or opening does it keep the feed and subscribe (`:160-164`). The callback, `delete()`, drops the subscription itself once nothing waits (`:174-175`); `forget()` drops it at shutdown. So it is made when a stage changes under a feed, as in `test_17_05`, not for every capture |
| C2 | `handlers/recording.py:159-163` | One subscription a recording, made after the feed's first frame; `_on_update(session)` ticks the frame clock, reads the simulation time, writes the tracked state and queues `_take_frame` with `asyncio.ensure_future`. `_end` (`:299`) and `shut_down` (`:368`) drop it |
| C3 | `handlers/debug_draw.py:183-185` | One subscription while the book holds a drawing; `_on_update` drops it itself when the backend goes or the book is idle (`:197`, `:206`); `stop_drawing` (`:212`) at shutdown. With `omni.debugdraw` it draws the book's lines on every update |
| C4 | The three | `create_subscription_to_pop(fn, name=...)` with no order: order 0, its default (`carb/events/_events.pyi:96` in 6.2). Each callback takes Kit's event and ignores it |
| C5 | `next_update_async` | Awaited by `camera_feed.py:114`, `:123`, `:282`, `_utils.py:88`, `scene_open.py:68`, `misc.py:56`: Kit's own observer (K5), untouched |
| C6 | `handlers/camera_feed.py:29-47`, `_subscribe` | The feed's drawable-changed: Events 2.0 where `omni.hydratexture` has `GLOBAL_EVENT_DRAWABLE_CHANGED`, the texture's event stream before. Untouched |
| C7 | The tests | `test_camera_feed.py:173-174`, `test_debug_draw_handler.py:72-73` and `test_recording_handler.py:118-119` fake the app's `get_update_event_stream().create_subscription_to_pop`. `test_camera_feed.py` loads `camera_feed.py` as a lone module (`:221`); the other two load their handler into a fake package, `handlers_under_test` |
| C8 | `ovmcp/bridge/__init__.py` | Imports `extension.py`, so all of Kit: a handler imports its siblings relatively, and the tests load handler files with Kit faked |

### Kit: Isaac Sim 6.2 (Kit 110.4) and Isaac Sim 5.1 (Kit 107.3.3), on disk

| # | What | Where |
|---|---|---|
| K1 | Kit wraps the app's `get_update_event_stream`, and its pre-update, post-update, message bus, startup, shutdown and log stream getters, in `carb.deprecated("Use Events 2.0")`. Each call logs "`get_update_event_stream` is deprecated. Use Events 2.0. Callstack:" and four frames, at Info, or at Warn when `/app/enableDeveloperWarnings` is set. Kit 107 does the same, and its C++ header marks the getters `CARB_DEPRECATED("Use Events 2.0")` too | 6.2: `kit/kernel/py/omni/kit/app/_impl/__init__.py:319-325`, `kit/kernel/py/carb/__init__.py:72-115`; 5.1: `:307-313` and `:71-114`; both `kit/dev/include/omni/kit/IApp.h:210-231` |
| K2 | `omni.kit.app.GLOBAL_EVENT_UPDATE = 'update'`, with `GLOBAL_EVENT_PRE_UPDATE` and `GLOBAL_EVENT_POST_UPDATE`: "The main update event that is dispatched during the main RunLoop frame"; another run loop's is `runloop:<name>:update`. Its payload holds `dt` and `SWHFrameNumber` | 6.2: `_app.pyi:349-358`, `kit/dev/include/omni/kit/AppTypes.h:188-210`; 5.1: `_app.pyi:216-225`, `AppTypes.h:178-200` |
| K3 | `carb.eventdispatcher.get_eventdispatcher().observe_event(order=, event_name=, on_event=, filter=, observer_name=)`. Observers run "in the thread that calls `dispatch_event()`", lower orders first, those of one order and filter in the order they were made; one made during a dispatch is first called on the next. It returns an `ObserverGuard` that "when collected, removes the observer". `reset()` "is safe to perform while dispatching"; from inside the observer's own call it returns at once and the release follows that dispatch, and "when `reset()` returns, it is guaranteed that the observer callback function will no longer be called" | 6.2: `kit/kernel/py/carb/eventdispatcher/_eventdispatcher.pyi:175-208`, `:503-533`; 5.1: `:156`, `:471-478`, the same text; `get_eventdispatcher()` in both packages' `__init__.py` |
| K4 | The orders within the main update, identical in both Kits: -100 the render completion check, which pushes `NEW_FRAME`; -90 the timeline's state; -50 and -45 Python futures awaiting the update's start; -20 the timeline; -10 USD's update (stage events, then physics through `IUsdStageUpdate`); 0 the default; 15 the UI; 20 Fabric's flush; 30 Hydra's render; 50 `next_update_async`; 100 the Python loop. `omni.kit.app` names them `UPDATE_ORDER_*` (`UPDATE_ORDER_UNSPECIFIED = 0`) | `kit/dev/include/omni/kit/KitUpdateOrder.h:52-116` in both; 6.2 `_app.pyi:368-376`, 5.1 `:235-243` |
| K5 | Kit's own use, in both Kits: `next_update_async` observes the update event at order 50; `omni.kit.async_engine` runs the asyncio loop once an update in an observer at order 100, so every bridge handler runs there; Replicator's orchestrator observes it at order 0; Kit ships a snippet of this form | 6.2: `omni/kit/app/_impl/app_iface.py:57-71`, `extscore/omni.kit.async_engine/.../async_engine.py:353-363`, `omni.replicator.core-1.13.38/.../orchestrator.py:1047-1052`, `kit/snippets/snippet_app_update_event.py`; 5.1: `app_iface.py:50-64`, `async_engine.py:287-296`, `omni.replicator.core-1.12.27+107.3.3/.../orchestrator.py:877` |
| K6 | Context7 has no page on Kit's update event: `/websites/omniverse_nvidia_extensions` shows `observe_event` with these keywords for another event, `/websites/nvidia_omniverse` and `/nvidia-omniverse/kit-app-template` nothing | 2026-11-01 |

### Kit's logs

| # | What | Where |
|---|---|---|
| L1 | 388 "`get_update_event_stream` is deprecated" notices, all at Info: 184 whose stack names `debug_draw.py`, 122 `recording.py`, 20 `camera_feed.py`, and 62, two a start, from Kit's own `omni.usd.schema.physx` and `omni.graph.visualization.nodes`. No other deprecation notice names the bridge | The 31 logs of 2026-11-01 in `D:\isaac\venv\Lib\site-packages\isaacsim\kit\logs\Kit\Isaac-Sim Python\6.2\` |
| L2 | Five of 50 hits of `get_logs(search="MCP")` in scenario 24.3 were these notices, matched by `ovmcp` in their stacks | #122; #111's plan |

### What the probe answers

K3 and K4 say where an observer runs; they don't say that the stream's subscriptions share the observers' orders.
`122-probe.py`, in the session's scratchpad `122/`, measures it on Kit 110 through `/execute` alone, over 8 updates,
then drops what it made. It renders, opens and changes nothing; it logs one deprecation notice of its own and two
deliberate errors, each naming "ovmcp 122 probe".

| # | Measures | Decides |
|---|---|---|
| P1 | The order within one update of: update observers at -101, -11, -9, 0, 1, 14, 16, 29, 31, 49, 51, 99 and 101; the stream's subscriptions at -9, 0 and 31, as the bridge makes them; pre- and post-update observers; any texture's drawable-changed event; the probe's coroutine resuming after `next_update_async` | Where `ORDER` goes: 0 if the stream's 0 sits between the observers at -9 and 1. Where Kit announces a frame relative to the recorder's tick |
| P2 | Each call's thread, against the asyncio loop's and Python's main thread | That the observers run on the main thread (#5) |
| P3 | Calls to an observer that drops its own guard in its second call, and to one that resets it | Q4 |
| P4 | Calls to an observer and to a stream subscription that each raise in their first call | Whether the helper catches errors (Design) |
| P5 | Calls after everything is dropped | That a dropped guard is no longer called |

The session ran it from this worktree, `uv run python <scratchpad>/122/122-probe.py`, on its Isaac Sim 6.2 headless
at 8212 (Kit `110.4.0+feature.386251.187cf21b.gl`, `/app/asyncRendering` false, the async engine's order 100, a Y-up
stage open), with #113's branch's extension, of which it used `/execute` alone. Exit 0; its output is
`122-probe.out.txt` beside the script, its stderr empty. It saw 8 updates, 7 of them whole.

| # | Result | Settles |
|---|---|---|
| P1 | All 7 whole updates ran in one order: `preUpdate+0`, `drawable`, `update-101`, `update-11`, `update-9`, `stream-9`, `update+0`, `stream+0`, `update+1`, `update+14`, `update+16`, `update+29`, `update+31`, `stream+31`, `update+49`, `update+51`, `update+99`, `resume`, `update+101`, `postUpdate+0`. Each stream subscription ran beside the observer of its own order, after it, since the observer was made first (K3's rule for one order): the stream's orders are the update event's. The asyncio loop resumed the probe between 99 and 101, at the async engine's 100. A texture's drawable-changed event came once an update, after the pre-update event and before the update event's first observer | `ORDER` is 0, the stream's place (Q2 A). Kit announces a frame rendered at 30 at the start of the next update, before the recorder's tick at 0 |
| P2 | Every call, of every tag, on the thread that runs the asyncio loop, which is Python's main thread | The observers run on the main thread, as the stream's did |
| P3 | An observer that dropped its own guard in its second call was called twice in 8 updates; one that reset its guard, twice | Dropping the guard in its own call ends the calls (Q4 A) |
| P4 | An observer that raised in its first call was called in all 8 updates; the stream subscription that raised, in all 8 too | Kit goes on calling either after an error: the helper adds no error handling |
| P5 | No call after every guard and subscription was dropped | A dropped guard is no longer called |

## Design

### One helper: `handlers/_updates.py` (Q1)

```python
def on_update(name: str, callback: Callable[[], None]) -> Any:
    """Calls `callback` once each update of Kit's main run loop, on Kit's main thread, until the guard it returns is
    dropped or reset."""
    return carb.eventdispatcher.get_eventdispatcher().observe_event(
        order=omni.kit.app.UPDATE_ORDER_UNSPECIFIED,
        event_name=omni.kit.app.GLOBAL_EVENT_UPDATE,
        on_event=lambda _event: callback(),
        observer_name=f"ovmcp.bridge {name}",
    )
```

- **Order 0** (Q2): where the stream's subscriptions ran (C4), after USD's update and the physics step (-10), before
  the UI (15), Fabric's flush (20), Hydra's render (30), `next_update_async` (50) and the asyncio loop that runs the
  handlers (100). P1 measured the stream's 0 as the observers' 0.
- **Main thread:** the update event is the main run loop's (K2), dispatched by the thread that runs it (K3), which
  also runs the asyncio loop (K5). P2 measured every call there.
- **No argument:** none of the three reads Kit's event.
- **Names:** `ovmcp.bridge <name>`, which Kit's profiler shows.
- **Errors:** as now, a callback's error is Kit's to log, and Kit goes on calling the observer, as it did the stream
  subscription (P4). The helper wraps nothing.
- **The docstring** names no deprecated getter: the guard (Q5) reads every file under the extension.

### The three, by role

| Role | Made | Dropped (Q4) |
|---|---|---|
| A recording's tick (C2) | `session.subscription = on_update(f"recording {session_id}", lambda: _on_update(session))`, after the first frame, as now | `_end`, `shut_down`, as now |
| A drawing's watch (C3) | `_drawings.sub = on_update("debug draw", _on_update)`; `_on_update()` takes no argument | By `_on_update` itself, and `stop_drawing`, as now |
| A render product's watch (C1) | `self.subscription = on_update("camera feed leftovers", self.delete)` | By `delete()` itself, and `forget()`, as now |
| Any #114 or #111 adds | Through `on_update` | Where it is dropped now |

The rebase reads each file again; the rows follow the code by role, not by line.

### Where in the update, and #57's first frame

- **The capture path doesn't move.** Its waits are `next_update_async` (C5, K5) and its frames the feed's
  drawable-changed event (C6), neither touched. The render product's watch runs only after a feed is dropped, never
  during a capture. #57's rule, a capture's first frame comes after the call starts, rests on those alone.
- **The recorder stays at order 0:** it reads the simulation time after the step and before the render, and queues
  `_take_frame`, which runs in the asyncio loop at 100, after Hydra's render at 30, and is handed the feed's next
  drawable-changed frame. Kit announces a frame at the start of the next update, before the tick (P1), so the tick's
  `feed.waiting` already knows whether the last frame came, as it did with the stream.
- **`omni.debugdraw`'s lines** are drawn at 0 and reach the render at 30 of the same update, as `test_16_09` checks.
- **An observer made during a dispatch** is first called on the next update (K3). The handlers make theirs at 100,
  after order 0 has passed, so a recording's first tick comes on the next update, as now. The recorder's tick makes
  the render product watch at 0 when a stage change stops its frames; that watch waits for an open stage anyway.

### Kit 107 (Q3)

Kit 107.3.3 has the same names, orders and guard (K1 to K5): no fallback. The feed's drawable-changed subscription
keeps its Kit 107 form (C6), outside this change.

### Tests' fakes

`tests/conftest.py` gains `FakeUpdates`: a fake `carb.eventdispatcher` that records each observer (order, event,
name) and returns a guard whose `reset()`, or its collection, removes it, and an `update()` that calls the `update`
observers in order, skipping any removed during the call. The handler tests load the real `_updates.py` into their
fake package with it, and deliver updates through it. `test_camera_feed.py` loads `camera_feed.py` into a fake package
too (C7, C8), and its fake keeps the drawable-changed observers it has.

### Alternatives

- **The call inline in each place** (Q1 B): three copies of the order, the event and the reason for both.
- **Another place in the update** (Q2 B, C): moves what #25, #57 and #69 measured.
- **A fallback to the stream** (Q3 B): a branch no supported Kit takes.
- **Explicit `reset()`** (Q4 B): K3 gives collection the same guarantee, and P3 measured both alike.
- **An error handler in the helper:** Kit calls an observer again after an error, as it did a stream's (P4).

### Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | One helper, or the call in each place? | **A.** `handlers/_updates.py`'s `on_update(name, callback)` holds the event, the order and the name; the three call it. **B.** The `observe_event` call inline in each, as `camera_feed._subscribe` inlines the drawable-changed one | A: the order and why live in one place with one test, and the next Kit change is one edit. It costs `test_camera_feed.py` a package-style load (C7) | A (serionist, 2026-11-01) |
| Q2 | Where in the update? | **A.** Order 0 of the update event, where the stream's subscriptions ran (C4); P1 measured the stream's 0 as that place. **B.** The post-update event, after Hydra's render is scheduled. **C.** The pre-update event, before USD's update and physics | A, settled by P1: the three run where they ran, so nothing measured under #25, #57 and #69 moves. B would read a frame's simulation time after its render was scheduled and move `omni.debugdraw`'s lines out of the update they were drawn for; C would read the simulation time before this update's step | A, settled by P1 (serionist, 2026-11-01) |
| Q3 | A fallback for a Kit without the update event? | **A.** None: Kit 107.3.3 has it (K1 to K5). **B.** The stream where `omni.kit.app` lacks `GLOBAL_EVENT_UPDATE`, as `_subscribe` does for drawable-changed | A: B adds a branch no supported Kit takes and only a fake can run. Isaac Sim 5.0 is not on disk (Risks) | A (serionist, 2026-11-01) |
| Q4 | How is each released? | **A.** The guard dropped, as now and as Kit's own code does (`async_engine.py` `on_shutdown`); K3 gives collection `reset()`'s guarantee, from inside its own call too. **B.** `reset()` called, then the guard dropped | A, settled by P3: a guard dropped in its own call ended the calls as `reset()` did, and P5 saw none after a drop | A, settled by P3 (serionist, 2026-11-01) |
| Q5 | A CI guard against the deprecated app streams? | **A.** `tests/test_updates.py` fails when any file under `extension/ovmcp.bridge` names one of the app's stream getters K1 lists, but the log stream's, which `tests/test_logs.py` refuses already. It skips `__pycache__`, as `tests/test_logs.py` does, so a stale `.pyc` left by a pull, or Kit 107's `cpython-311` one, can't fail it on fixed code. **B.** None | A: CI runs on every PR, the live suites only by hand | A (serionist, 2026-11-01) |
| Q6 | How is Kit's log checked live? | **A.** A scenario test, `test_17_08`, in phase 17, which already changes the stage: a recording stopped by a new stage, then a 0.5 s drawing; `get_logs` since its start holds the bridge's own Info line and no "Use Events 2.0" notice naming `ovmcp/bridge`. **B.** By hand: those notices in a live-suite run's Kit log, on main's extension and the branch's, in the PR. Kit is started again for each run, so each run's notices are a Kit log file of their own, from its first line. **C.** Both | C: A keeps it checked and fails on main's extension; B gives the whole run's numbers, before and after | C (serionist, 2026-11-01) |

## Compatibility

- **One-way doors:** none. No tool, route, setting, file or protocol changes.
- **What users notice:** Kit's log, and so `get_logs`, holds none of the bridge's "Use Events 2.0" notices. A
  CHANGELOG line under Fixed says so, and that the fix is in the Kit extension: `uvx omniverse-mcp extension install`,
  then restart Kit.
- **Kit apps:** Kit 107 and later, as now (K1 to K5). A 0.3.0 server with this extension, or this server with a 0.3.0
  extension, works as before.

## Steps

Each step builds and passes `uv run tools/gate.py quick`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the probe, run by the session on Isaac Sim 6.2 at 8212; its results are above, and settle `ORDER` (Q2), Q4 and the helper's error handling | `122-probe.out.txt` |
| 1 | This plan, the branch's first commit; `review-plan`; the maintainer's answers | |
| 2 | Wait for #114 and #111 to merge; rebase onto `origin/main`; read `camera_feed.py`, `recording.py` and `debug_draw.py` again and list every update subscription; amend C1 to C3 and the roles if they moved | The guard's scan (Q5, step 7), run on the rebased tree before any edit: the files it names are the work |
| 3 | `handlers/_updates.py`; `FakeUpdates` in `tests/conftest.py` | `tests/test_updates.py` |
| 4 | U2: `debug_draw.py` through `on_update` | `tests/test_debug_draw_handler.py` |
| 5 | U1: `recording.py` through `on_update` | `tests/test_recording_handler.py` |
| 6 | U3, U4: `camera_feed.py`'s watch, and any other #114 or #111 left, through `on_update`; the test loads it as a package module | `tests/test_camera_feed.py` |
| 7 | U5: the guard (Q5) | `tests/test_updates.py` |
| 8 | U6: `test_17_08` (Q6) | Run by the session |
| 9 | The docs (Docs) | The gate |
| 10 | The live suites by the session on Isaac Sim 6.2 at 8212, whole, on the default up axis (nothing here reads it), main's extension then the branch's, each on a Kit started for it: `test_17_08` fails then passes; the notices naming `ovmcp/bridge` counted in each run's own Kit log file (Q6 B). Isaac Sim 5.1 is a later check (Plan review, improvement 1) | No failure beyond main's on the same Kit |
| 11 | `finish-work`: the gate in full, `review-code` | |

## Tests

**Unit (CI):**

| File | What | At `84acfa5` |
|---|---|---|
| `tests/test_updates.py` (new) | `on_update` observes `GLOBAL_EVENT_UPDATE` at order 0 as `ovmcp.bridge <name>`; calls back once an update, with no argument; a guard reset, dropped, or dropped in its own call, ends the calls. The guard (Q5): each deprecated getter is found in a sample; `on_update`'s own call passes; no file under the extension names one, `__pycache__` skipped as `tests/test_logs.py` skips it | The guard fails: three files name the update stream |
| `tests/test_debug_draw_handler.py` | Its fake app loses the stream; updates come through `FakeUpdates`. One observer while drawings show, none once the book is idle or the backend is off, as now | Fails: the handler calls the stream |
| `tests/test_recording_handler.py` | The same; one observer a recording, gone at stop, at a forced restart and at shutdown | Fails likewise |
| `tests/test_camera_feed.py` | The same, for both Kit forms of the drawable event; `camera_feed.py` loaded into a fake package | Fails likewise |

**Live (by the session, Isaac Sim 6.2 headless at 8212):**

| Test | What |
|---|---|
| `test_17_08_the_bridge_logs_no_deprecated_update_stream` (new, Q6 A) | Marks the log; starts a recording, opens a new stage, stops it (U1, and U3 when the recorder sees the stage before it has opened again, as 20 notices in L1 show it does); draws a 0.5 s line and waits for it to go (U2). Since the mark: the bridge's own "Deleted the camera feed's render product" Info line is there, so Info reaches the file, and no "Use Events 2.0" entry's text matches `ovmcp[/\\]bridge`. Fails on main's extension |
| `test_06_*`, `test_07_*`, `test_16_*`, `test_17_03`, `test_17_05`, `test_17_07` | Pass as they are: frames, drawings and their expiry, and the render product cleanup at a new stage |
| `test_integration.py` whole | Passes as on main: the captures' waits are untouched |

**Neither shows:** Kit 107 running this code, unless the session has an Isaac Sim 5.1; Isaac Sim's GUI, which
renders asynchronously while stopped (`docs/ARCHITECTURE.md`, Threading Model, point 4), and other Kit apps such as
USD Composer. The observers' thread there rests on K2 and K3.

## Docs

| File | What changes |
|---|---|
| `docs/ARCHITECTURE.md` | Threading Model: a point on the bridge's update observers, `handlers/_updates.py`, Events 2.0 at order 0 on the main thread, and where that is in the update (K4). Recording System, steps 1 and 5, and Debug Drawing, steps 2 and 3: "observes the app's update event" for "subscribes to the update stream" |
| `CHANGELOG.md` | Under Unreleased, Fixed: Kit's log holds none of the bridge's "`get_update_event_stream` is deprecated" notices, one with a call stack for each recording, drawing and render product left by a stage change, which `get_logs` returned; the fix is in the Kit extension (#122) |
| `AGENTS.md` | None: it is at its 150-line cap, and the guard's message names #122 |
| `docs/TOOLS.md`, the READMEs, `docs/SETUP.md`, the plugin's skills | None: no tool, setting or setup changes |

## Risks

| Risk | Status |
|---|---|
| The stream's order 0 and the observers' order 0 are different places in the update | Resolved by P1 on Kit 110: one place. Kit 107 wasn't probed; its orders and `next_update_async` are the same (K4, K5) |
| Kit stops calling an observer whose callback raised, where it went on calling a stream's | Resolved by P4 on Kit 110: Kit calls both again |
| Isaac Sim 5.0 isn't on disk: a Kit 107 before 107.3.3 might lack the update event | Accepted: the extension supports Kit 107 and later, and 5.1's Kit 107.3.3 has it, with Kit's own `next_update_async` and Replicator observing it (K5). `122-probe.py` on Isaac Sim 5.1 is a later check: no 5.1 Kit runs in this batch |
| #114 or #111 adds or moves an update subscription | Accepted: step 2 reads the code again after both merge, and the guard (Q5) fails on any stream left |
| The observers' thread in Isaac Sim's GUI or another Kit app | Accepted: P2 measured the main thread on Isaac Sim 6.2 headless, with async rendering off; elsewhere it rests on the update event being the main run loop's (K2), dispatched by its thread (K3) |
| A guard kept alive by a stray reference goes on calling | Accepted: each is held in one attribute, as each subscription is now, and the unit tests drop each and count the calls after |

## Plan review

### Round 1

**How:** one fresh reviewer, started by the main session, read only, 2026-11-01, on `81850b3`. **Verdict:** approved:
no blocker or major, one minor; no further round. **Now:** P1 fixed, improvements 2 and 3 taken, in the commit after
`81850b3`. The maintainer answered Q1 A, Q3 A, Q5 A and Q6 C; Q2 and Q4 are A, settled by the probe (2026-11-01).

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | Q5 and Tests (`tests/test_updates.py`): the guard reads every file under the extension, `__pycache__` included. After a pull, a stale `recording.cpython-312.pyc` that still holds the old name fails the guard on code already fixed, and a Kit 107 `cpython-311.pyc` would do the same; the main checkout has 43 `.pyc` files under `extension/`. `tests/test_logs.py` skips them (`"__pycache__" not in p.parts`) | fixed: Q5 and the Tests row say the guard skips `__pycache__`, as `tests/test_logs.py` does |

**Refuted:**

- Order 0 is the stream's place: P1 gave `update-9`, `stream-9`, `update+0`, `stream+0`, ..., `update+31`,
  `stream+31`, `update+49` in all 7 whole updates, and the stream's subscriptions default to 0
  (`carb/events/_events.pyi:96`).
- The thread: P2, with `loop_thread_is_main` true.
- An observer that raises: the stream subscription does the same (P4), so no new risk.
- The guards' lifetimes: the same attributes and the same release sites as the subscriptions they replace.
- #111: its `_on_update` adds no subscription.
- Kit 107: Isaac Sim 5.1 has `GLOBAL_EVENT_UPDATE`, `UPDATE_ORDER_UNSPECIFIED`, `observe_event`,
  `ObserverGuard.reset`, and `next_update_async` at 50; Isaac Sim 5.0 is an accepted risk.
- The guard's false hits: none.
- `test_17_08` sees the call stack: a multi-line entry's continuation lines join its `msg` (`core/logs.py:198`).
- Phases 22 to 26: unaffected.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 to Q6 | Decisions for the maintainer | The reviewer agrees with each | Q1 A, Q3 A, Q5 A, Q6 C; Q2 A and Q4 A, settled by P1 and P3 (serionist, 2026-11-01) |

**Improvements:**

1. Run `122-probe.py` on Isaac Sim 5.1: left: no 5.1 Kit is started in this batch; a later check (Risks).
2. Step 2's `rg` command, whose `\|` the table escapes: taken. Step 2's proof is the guard's scan, run on the
   rebased tree.
3. Q6 B: say how each run's part of Kit's log is cut: taken. Each run is on a Kit started for it, so its notices are
   that start's own log file (Q6, step 10).
