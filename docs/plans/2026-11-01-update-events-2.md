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

The command, from this worktree, against main's extension (any `ovmcp.bridge` 0.3.0 or later; it uses `/execute`
alone), on the session's Isaac Sim 6.2 at 8212:

```
uv run python C:/Users/serio/AppData/Local/Temp/claude/D--workspaces-omniverse-mcp/ae0c0d9e-28b9-406b-a22f-39e21c083c92/scratchpad/122/122-probe.py
```

Results: not run yet. They go here, with the plan's choices they settle.

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
  handlers (100). P1 checks that the stream's 0 is the observers' 0; if it isn't, `ORDER` takes the place P1 measured
  for the stream's.
- **Main thread:** the update event is the main run loop's (K2), dispatched by the thread that runs it (K3), which
  also runs the asyncio loop (K5). P2 checks it.
- **No argument:** none of the three reads Kit's event.
- **Names:** `ovmcp.bridge <name>`, which Kit's profiler shows.
- **Errors:** as now, a callback's error is Kit's to log. If P4 shows Kit stops calling an observer that raised, where
  it went on calling a stream subscription, the helper catches and logs the error itself (`carb.log_warn`) so a
  recording doesn't stop taking frames without a word.
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
  drawable-changed frame. P1's drawable tag records where Kit announces that frame.
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
- **Explicit `reset()`** (Q4 B): K3 gives collection the same guarantee.

### Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | One helper, or the call in each place? | **A.** `handlers/_updates.py`'s `on_update(name, callback)` holds the event, the order and the name; the three call it. **B.** The `observe_event` call inline in each, as `camera_feed._subscribe` inlines the drawable-changed one | A: the order and why live in one place with one test, and the next Kit change is one edit. It costs `test_camera_feed.py` a package-style load (C7) | |
| Q2 | Where in the update? | **A.** Order 0 of the update event, where the stream's subscriptions ran (C4), if P1 agrees. **B.** The post-update event, after Hydra's render is scheduled. **C.** The pre-update event, before USD's update and physics | A: nothing measured under #25, #57 and #69 moves. B would read a frame's simulation time after its render was scheduled and move `omni.debugdraw`'s lines out of the update they were drawn for; C would read the simulation time before this update's step | |
| Q3 | A fallback for a Kit without the update event? | **A.** None: Kit 107.3.3 has it (K1 to K5). **B.** The stream where `omni.kit.app` lacks `GLOBAL_EVENT_UPDATE`, as `_subscribe` does for drawable-changed | A: B adds a branch no supported Kit takes and only a fake can run. Isaac Sim 5.0 is not on disk (Risks) | |
| Q4 | How is each released? | **A.** The guard dropped, as now and as Kit's own code does (`async_engine.py` `on_shutdown`); K3 gives collection `reset()`'s guarantee, from inside its own call too. **B.** `reset()` called, then the guard dropped | A, unless P3 shows a guard dropped in its own call still called | |
| Q5 | A CI guard against the deprecated app streams? | **A.** `tests/test_updates.py` fails when any file under `extension/ovmcp.bridge` names one of the app's stream getters K1 lists, but the log stream's, which `tests/test_logs.py` refuses already. **B.** None | A: CI runs on every PR, the live suites only by hand | |
| Q6 | How is Kit's log checked live? | **A.** A scenario test, `test_17_08`, in phase 17, which already changes the stage: a recording stopped by a new stage, then a 0.5 s drawing; `get_logs` since its start holds the bridge's own Info line and no "Use Events 2.0" notice naming `ovmcp/bridge`. **B.** By hand: those notices in a live-suite run's Kit log, on main's extension and the branch's, in the PR. **C.** Both | C: A keeps it checked and fails on main's extension; B gives the whole run's numbers, before and after | |

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
| 0 | The probe, run by the session on Isaac Sim 6.2 at 8212 with main's extension; its results into this plan, and `ORDER`, Q4 and the helper's error handling settled by them | The probe's output |
| 1 | This plan, the branch's first commit; `review-plan`; the maintainer's answers | |
| 2 | Wait for #114 and #111 to merge; rebase onto `origin/main`; read `camera_feed.py`, `recording.py` and `debug_draw.py` again and list every update subscription; amend C1 to C3 and the roles if they moved | `rg "update_event_stream\|create_subscription_to_pop" extension` |
| 3 | `handlers/_updates.py`; `FakeUpdates` in `tests/conftest.py` | `tests/test_updates.py` |
| 4 | U2: `debug_draw.py` through `on_update` | `tests/test_debug_draw_handler.py` |
| 5 | U1: `recording.py` through `on_update` | `tests/test_recording_handler.py` |
| 6 | U3, U4: `camera_feed.py`'s watch, and any other #114 or #111 left, through `on_update`; the test loads it as a package module | `tests/test_camera_feed.py` |
| 7 | U5: the guard (Q5) | `tests/test_updates.py` |
| 8 | U6: `test_17_08` (Q6) | Run by the session |
| 9 | The docs (Docs) | The gate |
| 10 | The live suites by the session on Isaac Sim 6.2 at 8212, whole, on the default up axis (nothing here reads it), main's extension then the branch's: `test_17_08` fails then passes; the notices naming the bridge in each run's Kit log counted (Q6 B). On Isaac Sim 5.1 too, if the session has one | No failure beyond main's on the same Kit |
| 11 | `finish-work`: the gate in full, `review-code` | |

## Tests

**Unit (CI):**

| File | What | At `84acfa5` |
|---|---|---|
| `tests/test_updates.py` (new) | `on_update` observes `GLOBAL_EVENT_UPDATE` at order 0 as `ovmcp.bridge <name>`; calls back once an update, with no argument; a guard reset, dropped, or dropped in its own call, ends the calls. The guard (Q5): each deprecated getter is found in a sample; `on_update`'s own call passes; no file under the extension names one | The guard fails: three files name the update stream |
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
| The stream's order 0 and the observers' order 0 are different places in the update | Open until P1; then `ORDER` takes the stream's place |
| Kit stops calling an observer whose callback raised, where it went on calling a stream's | Open until P4; then the helper catches and logs |
| Isaac Sim 5.0 isn't on disk: a Kit 107 before 107.3.3 might lack the update event | Accepted: the extension supports Kit 107 and later, and 5.1's Kit 107.3.3 has it, with Kit's own `next_update_async` and Replicator observing it (K5) |
| #114 or #111 adds or moves an update subscription | Accepted: step 2 reads the code again after both merge, and the guard (Q5) fails on any stream left |
| The observers' thread in Isaac Sim's GUI or another Kit app | Accepted: the update event is the main run loop's (K2), dispatched by its thread (K3); the live suites run headless |
| A guard kept alive by a stray reference goes on calling | Accepted: each is held in one attribute, as each subscription is now, and the unit tests drop each and count the calls after |

## Plan review

Not reviewed yet.
