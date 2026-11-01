---
title: Keep the capture feed between calls, and name Kit's renderer hang when a call meets it
issue: "#114"
status: approved
approved_by: serionist
approved_at: 2026-11-01
---

# Keep the capture feed between calls, and name Kit's renderer hang when a call meets it

Kit 110 (Isaac Sim 6.2) can hang for good during a new RTX view's first frames. Kit's main thread loops inside NVIDIA's
renderer, its log goes silent, and nothing but killing the app frees it. `inspect_prim` and `capture_viewport` make a
new view on every call, since each renders through a camera feed of its own (#51, #57), so an agent that captures
often meets the hang often: about one call in 300 to 400 in round 1's loop of real `inspect_prim` calls, and once at
view 97 of a Kit that had run both live suites (K13). #54's first hang, in the live suites on 2026-10-29, ended its
log at a view's assignment too, as a test started play: a view Kit made, which a kept feed can't spare.

The hang is NVIDIA's, and no setting tried at run time avoids it. What the bridge can do is make fewer new views: keep
one feed between calls and point it at each call's camera. A changed camera makes no new view, and 8,000 camera
switches on one feed never hung (K15); a changed size makes one, though the texture can be resized in place. The server can also tell an agent what happened, at once, instead of
after 120 s on every later call.

## Goal

| Row | True when done | Shown by |
|---|---|---|
| G1 | `inspect_prim` and `capture_viewport` render through one kept feed. A call at the size of the last one, any camera, makes no new RTX view; a call at another size resizes the kept feed in place, one new view and the same render product. The kept feed is released after 30 s with no capture (Q1, Q2), when the stage closes, when a call fails in a way that leaves the feed in doubt, and when the extension shuts down, whatever its size (Q2) | `test_camera_feed.py`, `test_camera_handler.py`; live `test_26_03` (new, `test_scenarios.py`): views gained in Kit's log over a run of calls |
| G2 | A capture through a kept feed shows what one through a fresh feed shows, within K7's bounds (mean 0.2 of 255, 99th percentile 4), its segmentation and boxes agreeing with it (#51). That holds when the camera changed, or the stage was edited, just before the call, inside the same request (`execute_script`) | live `test_26_04` (new): camera B straight after camera A at one size, and a USD move then `mcp.capture_viewport()` in one script, each against a fresh feed |
| G3 | The bridge's own `save_scene`, `flatten_usd` and `export_prim` release the kept feed first, so they never write its render product; Kit's own Save tears it down on `SAVING`, before it writes (Q7's B, step 1); the extension's shutdown deletes it when the stage is open | live `test_26_05` (new): `save_scene`, `flatten_usd`, `export_prim` and Kit's own Save straight after a capture write no `ovmcp_capture_` |
| G4 | A call whose socket, once connected, gets no answer for the server's timeout, when Kit then answers no `/health` within 5 s either, fails with a message that Kit has stopped answering; that it may be busy with a long script or stuck, most likely in NVIDIA's renderer (#114); and that if it stays silent for minutes it needs a restart. Each later call checks `/health` first, for 5 s, and fails at once the same way while Kit stays silent (Q3) | `test_client.py` with a fake socket that accepts and never answers; `test_tools.py` |
| G5 | `docs/TOOLS.md`, the plugin's scene skill, the README's troubleshooting and `docs/ARCHITECTURE.md` say what the hang looks like, what the bridge does about it and what a kept feed costs, by size (step 1) | review |

| In scope | Out of scope |
|---|---|
| The capture feed of `inspect_prim` and `capture_viewport`, its settle and its release | Recordings: each makes one feed, so one new view, for its whole length |
| Releasing the kept feed before the bridge's own saves and exports, and tearing it down at Kit's own Save | Kit's viewport render product, which Kit keeps in the root layer (K12); a script that writes the root layer through USD itself |
| The server's message and fast failure for a Kit that stopped answering | Recovering a hung Kit: nothing in Kit's process can, since its main thread is the one stuck |
| A report to NVIDIA with the repro, drafted for the maintainer (Q4) | A fix inside Kit or the driver |
| #54, closed with this change as the same hang family (Q6) | #54's other shapes (its second settings-lock hang, right after a recording's render product was deleted; a `usdrt` population spin; "Out of resource descriptors"), and #114's phase-26 `DrvPresentBuffers` hang, unless they recur |

## What the probes show

On my own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, main's extension, with the
maintainer's other Kit apps on the same GPU (a windowed Isaac Sim and a 4096-environment training run). Every run's
lines, dumps and Kit log are in the main checkout's git-ignored `.local/handoff-2026-11-01/114/r2-r3/`. The probe is
`114-probe.py` (`--switch` for K15); `114-views.py`, `114-ghost.py`, `114-layers.py` and `114-move.py` measured K5 to
K7, K11 and K12.

| # | What | Evidence |
|---|---|---|
| K1 | Every hang so far came during a new RTX view's first frames: Kit's log ends at a view being set up (`createViewport`, `Added sensor`, `View 1 ... assigned to device 0`), then nothing | Round 1 (`--mode inspect`, call 416), 1b (`--mode toggle`, call 159), R2a, R2b, L1 to L3 and K13's logs; #54's first hang ended at an `omni.rtx` view assignment as `test_16_02` started play |
| K2 | The hung main thread is busy, not blocked: 7.1 to 9.7 CPU seconds in 11 to 14, under Kit's update, in `rtx.hydra`, `carb.scenerenderer-rtx`, `gpu.foundation` and the driver, the top frames changing between samples. The GPU's 3D engine still shows work for Kit (about 10 %). The log stays silent | the runs' `-activity.txt` and `-samples.txt` |
| K3 | The fast repro: one feed whose updates go on for 3 frames and off again, aimed at the next angle each time, makes a new view every 0.15 s. It hung at about view 101 (R2a), 421 (R2b), 121 (L1), 101 (L2) and 41 (L3), each within 2 minutes | `r2a-flicker.jsonl` and the others |
| K4 | With no new views, no hang: `--mode persist`, inspect_prim's steps through one feed made at the start, ran 600 captures with segmentation in 8 minutes, 35,312 frames, one view | `r3-persist.jsonl` |
| K5 | Which changes to a live texture make a new view: its `camera_path` set, none; its width and height set, one, with the same render product; its updates off then on, one; nothing changed, none. Instance segmentation turned on, read and turned off on a kept feed, none | `views.jsonl`, `ghost.jsonl` |
| K6 | A kept feed rendering while idle at 800x600: 113 frames a second; Kit's share of the GPU's 3D engine 30 % with it, 12 % after its release, 11 % before. #51's A11: a feed rendering every update costs 32 % of the app's updates at 640x480, 42 % at 1920x1080, 75 % at 4096x4096 | `views.jsonl`; #51's plan |
| K7 | A kept feed's capture, aimed and settled 20 frames after it rendered another view, against a fresh feed's of the same view: mean 0.13 of 255, 99th percentile 3, max 94, against 0.06, 2 and 21 between two fresh feeds. The same 120 frames later, so the difference isn't a fading ghost: the kept feed has rendered more frames than a fresh one's 24 | `114-ghost-compare.py` |
| K8 | Run-time settings didn't avoid it: `/rtx/hydra/multiTickRate/enableRenderQuality` false (L1, view 121); that with `waitForInitialStreamingDone`, `multiTickRateParallelRendering`, `perSensorTickTlas` and `/rtx/ecoMode/enabled` false (L2, view 101). `/rtx/rendermode` didn't reach the feed, whose render product carries its own `omni:rtx:rendermode` (L3) | `r3-*.jsonl` |
| K9 | Free memory was 8.8 to 13 GB at every hang this round, so memory is not the trigger | the HANG lines |
| K10 | A verbose trace of Kit's multi-tick channels wrote nothing to Kit's log (R2b), so the log can't show what the loop does | `r2b-kit.log` |
| K11 | Kit writes a feed's render product into the root layer (a `def`, and a target in `/Render/OmniverseGlobalRenderSettings.products`) and an `over` into the session layer, also with the session layer as the edit target while the texture is made | `layers.json`; #25's E12, #51's E13 |
| K12 | Moved after the texture is made, the root layer's `def` copied into the session layer and removed from the root layer with its products target, the feed keeps rendering (24 frames in 30 updates), captures (not black), the root layer names it nowhere, and `release` still deletes it from both. Kit's own viewport render product is in the root layer's products too | `move.txt` |
| K13 | A Kit that had run #119's live suites (about 94 views) hung on the third view of a probe, at view 97, the log ending at the view's set-up | `p2-rootspecs-*` |
| K14 | A feed kept alive after a camera move shows the previous view for 1 update or 2: #51's E14, 10.7 at 0 and 1 updates, 0.45 at 3; under Path Tracing 7.0 at 0 and 1, 0.0 from 3 | #51's plan, E14 |
| K15 | Camera switches on one kept feed don't hang: `--mode flicker --switch`, one feed rendering throughout, its `camera_path` set between the active camera and `/OmniverseKit_Top` every 3 frames, 8,000 switches in 7 minutes, no hang, where flicker's new views hung within 41 to 421. Kit's log gained no `createViewport` and no `View 1 ... assigned to device 0` lines for them after the first: 161 assignment lines before the probe, 166 after: the viewport's View 0, the probe's feed made, its updates turned back on (the probe turns them off after the first frame, which a kept feed never does), its first switch, and View 0 again after `new_scene`. K12's move logged the assignment lines once too | `r4-camswitch.jsonl`, `r4-camswitch-kit.log` |
| K16 | `Sdf.CopySpec` replaces the destination spec, it doesn't merge: onto a session `over` holding `deviceIds`, `viewportHandle`, a segmentation `orderedVars` target and `ogPostProcessPath`, it left the root's `def` alone; a partial root `over` copied onto a full session `def` left a typeless `over`. omni.syntheticdata writes its segmentation into the session layer as soon as it is turned on (`SyntheticData.py`, `activate_node_template` under `Usd.EditContext(stage, session_layer)`) | round 2's usd-core checks, `copyspec.py`, `copyspec2.py` |
| K17 | After K12's move, Kit writes each later change into the root layer as an `over`: a camera change wrote `camera` = Top and `resolution`; a resize wrote `resolution` = 640x480 and `camera` read back from the composed value (Persp). The texture renders the composed render product, so the moved session spec hid both: the capture stayed Persp at 320x240 | `move2.json` |
| K18 | A moved feed renders exactly as an unmoved one (difference 0.0), and a camera switch on an unmoved feed exactly as a fresh feed of that camera (0.01). Replacing the session spec's properties with Kit's root `over` after a change gave the right camera and size but a different image (mean 226 of 255 against a fresh feed's 3) | `move3b.json`, `114-move4.py`, `114-move5.py`, `move3png/` |

Not shown: the hang on a GPU no other Kit app uses (the maintainer's apps ran through every run, and they are the
maintainer's to stop), on Linux, on Isaac Sim 5.x (Kit 107), or with a render mode other than Real-Time Path Tracing.

## Design

### The kept feed (extension, `handlers/camera_feed.py`, `handlers/camera.py`)

- **`kept_feed(camera_path, width, height)`**, async, replaces `_new_feed` in both handlers, called holding `_viewport`
  as today. With no kept feed, it makes one and waits for its first frame, as today. With one on the open stage, it
  sets the camera on both the texture and `CameraFeed.camera_path` (the boxes and segmentation read the latter), and a
  new size in place on the texture and on `CameraFeed.width` and `height` (K5: one new view, the same render product).
  Any size is kept, with no cap (Q2).
- **Every capture waits** `CAMERA_SETTLE_FRAMES` plus Path Tracing's settle frames of its feed's own after the call
  has set the camera, before its first frame is taken, kept feed or fresh, whether or not the camera changed: the
  handler can't see a USD move or a drawing made just before the call (K14). One code path, about 0.18 s at K6's rate,
  and #57's guard for every call: the frame taken comes 20 of the feed's frames after the call starts, more than a
  fresh feed's 15 updates. `inspect_prim`'s per-angle settle stays as it is.
- **Saves:** the render product stays where Kit puts it, in the root layer with an `over` in the session layer
  (K11). `save_scene`, `flatten_usd` (with or without `input_path`, since `open_to_flatten` takes Kit's held
  layers) and `export_prim` take `_viewport`, release the kept feed in `release`'s order, and hold the lock through
  their write, so no call makes a feed in between and none of them writes it. Kit's own Save sends `SAVING`
  synchronously before it writes, and the kept feed is torn down then, in `release`'s order with no update between
  its steps (Q7's B: step 1 found that teardown quiet). The live tests call `release_kept()` through
  `execute_script`.
- **`put_back(feed, healthy)`** replaces `release(feed)` at the end of each handler. A healthy feed starts the idle
  timer: 30 s with no call (Q2), then `release`. A feed is released at once when any exception escaped the capture
  (`NoFrameError`, `OutOfTimeError`, the handler's "Kit captured nothing" `CaptureError`, or one it didn't expect, an
  angle's error that `inspect_prim` records included), or when its segmentation sensor raised as it was turned on or
  gave no data (a legend of no prims, from an empty view, is data), so a stalled feed or a half-made sensor is never
  kept (`_SEGMENTATION_AS_BEFORE`'s "capture again" then gets a feed of
  its own). A Kit without omni.syntheticdata, where `enable_segmentation` returns a reason and touches nothing, keeps
  its feed. A feed the stage event already discarded is left alone.
- **The lock:** `_viewport` moves from `camera.py` into `camera_feed.py`, which `camera.py` already imports, so
  `release_kept`, the timer and the save handlers take the one lock. It isn't re-entrant (`serial.py`), so the
  at-once releases inside `kept_feed` and `put_back`, which run holding it, call `release` directly.
- **The timer:** a module constant, the idle seconds, so the unit tests run fast. Its release takes `_viewport`, then
  checks that the feed is still the kept one and that no call took it since (a generation number), so a timer that
  fires as a call puts the feed back does nothing.
- **Segmentation:** turned on for a call that asks, and off again as the call puts the feed back; turning it on and
  off makes no view (K5). Step 1 found a kept, segmented feed costs far more while idle than K6's, so it isn't left
  on; its graphs are still freed at release (#51's E16). A resized feed's segmentation is at the new size (step 1), so
  a segmented kept feed is resized in place too.
- **The stage:** a stage `CLOSING` drops the kept feed at once and discards it (`discard`, which deletes its render
  product once a stage is open, #25's E13), through Kit's stage events on Events 2.0
  (`omni.usd.get_context().stage_event_name(...)` with `carb.eventdispatcher`, which Kit 107's `omni.usd` 1.13.10
  has too). omni.syntheticdata resets its own graphs on `CLOSING`, so none leak. `kept_feed` also checks the stage is
  the one the feed was made on.
- **Shutdown:** `forget` stops the timer and tears the kept feed down in `release`'s order without its two updates,
  which shutdown can't wait: segmentation off, the feed dropped, the graphs freed, the render product deleted when the
  stage is `OPENED` (`remove_render_product` already checks that). Step 1 found this leaves Kit's log quiet in #51's
  E16 windows (2 s, a save, a new stage, the viewport's segmentation afterwards).
- **The answer:** unchanged. `inspect_prim`'s and `capture_viewport`'s results don't say whether the feed was kept.

Alternatives:
- A feed per call (today): a new view each call, so the hang's rate.
- One feed kept for the extension's life (Q1's C): the GPU cost for as long as Kit runs after one capture.
- Turning the kept feed's updates off between calls: a new view each time it comes back on (K5), so no gain.
- Moving the render product into the session layer (rounds 1 to 3): it works alone (K12, K18), but Kit writes each
  later change into the root layer and renders the composed render product, so the moved spec hid them (K17, P14),
  and replacing it with Kit's root `over` changed what the feed rendered (K18). Too fragile to keep.
- Releasing on Kit's `SAVING` event with `release`'s two updates: a synchronous event can't wait them, so the
  no-update teardown runs there instead (Q7's B, step 1).
- A Kit setting: none tried avoided it (K8).

### Naming the hang (server, `client.py`, `tools/_bridge.py`)

- A request whose connected socket times out on its read is followed by `/health` on a fresh connection with a 5 s
  timeout. When that answers, the error is today's. When it doesn't, `bridge_answer` raises a `ToolError` that says:
  Kit at `<host>:<port>` stopped answering, a call and `/health` both; it may be busy with a long synchronous script,
  or stuck, most likely in NVIDIA's RTX renderer during a new camera view's first frames (#114); if it stays silent for
  minutes, restart the Kit app. A connect timeout (a host that is down) keeps today's error.
- The client remembers that Kit went silent, under its `_lock`. Its next request first asks `/health` for 5 s: silent
  still, the same error at once; answered, the mark clears and the request goes as usual. So an agent learns in 5 s,
  not 120.

### Step 1: measured

Measured by the maintainer's session on headless Isaac Sim 6.2.0 (Kit 110.4.0), RTX 5090, port 8212, main's extension;
the lines are in the main checkout's git-ignored `.local/handoff-2026-11-01/114/r2-r3/` (`step1-a.jsonl`,
`step1-bcd.jsonl`, `segcycle.json`, from `114-step1.py` and `114-segcycle.py`). Kit's stage events were looked up in
the installed sources; Context7 holds no Kit docs for them.

| # | What | Result | So |
|---|---|---|---|
| S1 | A kept feed's idle cost, by size (video memory as the difference from no feed, since the absolute counter misreads) | no feed: 183 updates a second, 9 % of the 3D engine. Segmentation off: 640x480 157, 25 %, about 0.3 GB; 1920x1080 153, 28 %, about 1.0 GB; 4096x4096 69, 65 %, about 5.5 GB. On: 110, 30 %, 0.5 GB; 100, 35 %, 1.3 GB; 63, 66 %, 6.7 GB | segmentation is turned off at the end of each call that turned it on; the docs state the off rows, 4096x4096's plainly (Q2: no cap) |
| S2 | Segmentation on, read and off on one feed, five times | a full legend (10 prims) each time, one graph in the registry throughout, one `createViewport` in all, no errors, no E16 lines; idle after, 137 updates a second | turning it off between calls costs nothing in views or legends |
| S3 | A segmented 320x240 feed resized in place to 640x480, then switched to `/OmniverseKit_Top` | a 640x480 capture and segmentation, legend intact; against a fresh Top feed, mean 0.08 of 255, 99th percentile 1, legend intact | a segmented feed is resized in place; the release-and-remake fallback isn't built |
| S4 | The no-update teardown of a segmented feed: segmentation off, `drop`, graphs freed, render product deleted | the registry's graphs went 1 to 0, the prim gone; no E16 error (`getWrappedGraphFromNode`) and no error at all in each of #51's windows: the teardown, 2 s after, a root-layer save, a new stage, a segmented viewport capture after (which succeeded) | Q7's B: Kit's `SAVING` tears the kept feed down that way; `forget` too, deleting the render product while a stage is open |
| S5 | A file Kit saved with a feed kept, reopened | the render product prim is in it; Kit logs no error (one "plugin interface already released" warning, as every release logs), and a capture after is fine | with Q7's B, Kit's Save no longer writes it |
| S6 | Kit's stage events on Events 2.0 | Kit 110's `omni.usd` 1.19.11 and Kit 107's 1.13.10 both have `UsdContext.stage_event_name(StageEventType)`, observed with `carb.eventdispatcher.get_eventdispatcher().observe_event(observer_name, event_name, on_event)`, as `omni.usd`'s own extension does; its test asserts `SAVING`, then `SETTINGS_SAVING`, then `SAVED`, synchronously, and a `SAVING` observer may cancel the save. `omni.syntheticdata` 0.6.17 resets its registry (`_nodeGraphs = {}`) on `CLOSING` | `kept_feed` observes `CLOSING` and `SAVING` once |

### What the build changed

Built as above, at the steps' commits, with step 1's outcomes (S1 to S6), and these, none of them a change of design:

- **`kept_feed` is synchronous:** nothing in it waits. A feed kept on another stage, whose `CLOSING` never came, is
  dropped and discarded, as at `CLOSING`, rather than released.
- **The saves' lock:** `camera_feed.without_kept_feed()`, an async context manager, takes `_viewport`, releases the
  kept feed and holds the lock while the route writes; `release_kept()` takes the lock itself, for the live tests.
  The routes take it before their refusal checks, so a refused save releases the feed too, and the next capture makes
  one view.
- **A feed let go during a call** (a stage closing, Kit's Save, shutdown): its frame waits and `schedule` fail at once
  with `NoFrameError`, rather than after `FRAME_SECONDS`; `put_back` leaves it alone.
- **`CameraFeed.sensor_on`** beside `segmented`: with segmentation off between calls, `segmented` says the graphs need
  freeing at release, `sensor_on` that the sensor is on now; `release` and the teardown turn off only an on sensor.
  A failure to turn it off at `put_back` releases the feed.
- **The server:** the error is `KitSilentError` (ruff's N818), a `TimeoutError`, so the live suites' hung-Kit guard
  still sees a timeout. The `/health` check is a bare `GET /health` on a connection of its own, without the
  handshake: any byte back is an answer, a refusal too, and connect and answer share the 5 s. The message names
  "omniverse-mcp issue #114", since an agent reads it without the repo.
- **Live tests:** `test_12e` releases the kept feed first too, as its stage reads before and after a refused call
  would differ if the idle release came between them. `test_26_05` adds Kit's own Save, of a copy of the stage
  opened from its file, the stage as it was opened again after. `test_26_03` reads the idle seconds from Kit, and
  checks the feed is still kept 5 s before they end. Its counts read `createViewport - handle`, as the probes did, and
  view assignments naming an `ovmcp_capture_` render product, so they need Kit's log to hold Info lines.
  `test_project/scenarios.md` has no 26.3 to 26.5: the tests' "Phase 26.x" follows the file's numbering.
- **AGENTS.md:** no new Traps row; it is at its 150 lines and no line could be freed, so `docs/ARCHITECTURE.md`
  holds the hang.
- **Not settled without Kit:** that `SAVING` comes on Kit's main thread for `save_stage_async` and File > Save (the
  teardown edits USD); that Kit 107 logs the counted lines alike; the live tests themselves, written, not run.

## Compatibility

No tool, schema, route, setting or output path changes. Two things users notice: the GPU busier for 30 s after a
capture (by size, step 1), and a clearer error when Kit stops answering. `capture_viewport`'s `readOnlyHint` rests on
#51's Q7, "the stage holds nothing more after the call"; with a kept feed the stage holds its render product for up
to 30 s after, in the root layer as Kit writes it, as it holds Kit's viewport's own. Q5 asks the maintainer whether
the hint stays on that basis. An older extension with this server gets the new error; a new extension with an older
server keeps its feed and gets today's error. Both are fine (0.x).

## Steps

1. **Measure and look up:** Kit's stage events on Events 2.0 in Kit 110 and 107 (Context7, the installed sources);
   a kept feed's idle cost at 640x480,
   1920x1080 and 4096x4096 (frames a second, Kit's updates a second, the 3D engine's share, VRAM), with and without
   segmentation, which the docs state and which sets the segmentation rule; a resized feed's segmentation at the new size; a
   segmented kept feed, resized and re-aimed, still giving a legend and capturing both cameras right; shutdown's
   order (segmentation off, drop, graphs freed, the render product deleted, no updates) leaving Kit's log quiet in
   E16's windows; and a file saved by Kit with a kept feed's render product in it, reopened: what Kit logs and
   renders. Recorded in this plan.
2. **`camera_feed.py`:** `kept_feed`, `put_back`, `release_kept`, the timer with its generation, the stage
   subscription, `forget`. Unit tests in `tests/test_camera_feed.py` with the fake texture: same size reused with the
   camera set on both; another size resized in place; the timer releases after the
   idle seconds and a call stops it; a stale timer does nothing; an escaped exception and a sensor that raised release
   at once, a Kit without omni.syntheticdata and an empty legend keep the feed; `release_kept` with none kept is a
   no-op; a stage closing drops and discards; shutdown turns segmentation off, frees the graphs, drops and deletes.
   `save_scene`, `flatten_usd` and `export_prim` release the kept feed first and hold the lock through their write
   (`test_scene_save_handler.py`, `test_flatten_handler.py`).
3. **`camera.py`:** both handlers through `kept_feed` and `put_back`, and the settle on every capture;
   `test_camera_handler.py` checks a call's feed is put back, the second call at the same size makes none, the
   settle is waited when the feed already has frames, and an `inspect_prim` angle's error releases the feed.
4. **The server:** `client.py`'s silent mark and health check, `_bridge.py`'s message; `test_client.py` and
   `test_tools.py`.
5. **Docs and CHANGELOG** (Docs, below).
6. **Live:** the new tests and the changed ones, on a Z-up and a Y-up stage; both suites whole; the probe's
   `--mode inspect` loop for 600 calls with the branch's extension (round 1 hung at 416 on main's); a loop of 600
   `capture_viewport` calls alternating two cameras at one size; AI phases 3, 22 and 26.

## Tests

- **Unit:** step 2 to 4's tests; the tool contract unchanged (`test_contract.py`).
- **Live, new,** in `test_scenarios.py`, each releasing any kept feed first:
  - `test_26_03`: five `inspect_prim` and `capture_viewport` calls at one size, two cameras between them, gain one
    `createViewport` in Kit's log and two `View 1 ... assigned to device 0` lines (the feed made, its first camera
    change; K15); a sixth at another size one more view; the feed gone 30 s after the last call (no
    `ovmcp_capture` render product on the stage);
  - `test_26_04`: camera B straight after camera A at one size, and a USD move then `mcp.capture_viewport()` inside one
    `execute_script`, each against a fresh feed's capture within K7's bounds;
  - `test_26_05`: `save_scene`, `flatten_usd` and `export_prim` of `/Render`, the subtree the render product is in,
    straight after a capture write no `ovmcp_capture_`.
- **Live, changed,** each still checking what it checked, after the kept feed goes:
  - `test_12d` and `test_13b`: the kept feed is released, through `execute_script`, before `before` is read and
    again before `_assert_nothing_left`, so both compare stages with no kept feed. `test_12d`'s failing half checks straight after the call with no release asked for,
    since the handler's "Kit captured nothing" escapes the capture and releases its feed itself;
  - `test_16_08` and `test_16_09`: `_a_capture_at_once_holds_the_drawing` releases any kept feed (through
    `execute_script`) before each `HYDRA_TEXTURES` read, so both reads compare stages with no kept feed and an extra
    render product left behind still fails it; that the kept feed itself goes is `test_26_03`'s;
  - `test_06_05`: its `HYDRA_TEXTURES` reads after the kept feed's release;
  - `test_15f`, whose wrapped `create_hydra_texture` must be called: any kept feed released first, as test_15e's
    capture at the same size seconds before would otherwise be reused.
- **Live, existing:** both suites whole, on Z-up and Y-up.
- **Not shown:** that the hang never comes, since a new size, the first call after 30 s idle, and Kit's own views still make new views; Linux; Isaac Sim 5.x; a GPU of its own.

## Docs

- `docs/TOOLS.md`: `inspect_prim` and `capture_viewport` say a feed is kept for 30 s after a call and what it costs;
  the read-only hint row (line 42) says the stage holds it while kept; line 821's "first frame comes some 15
  updates later" becomes the 20 frames every capture waits.
- `plugin/skills/scene/SKILL.md:60` ("render the camera afresh for each call, so the move shows"): a move or drawing
  made before the call still shows, since every capture waits 20 frames.
- `README.md` troubleshooting: Kit stops answering, what the server says, when to restart it, #114.
- `docs/ARCHITECTURE.md`: the kept feed, its release and the saves that release it first; the client's silent mark.
- `AGENTS.md` Traps: #51/#57's row's guard rewritten (the frame taken comes 20 of the feed's frames after the call
  sets the camera), and a row for this hang only if a line can be freed (it is at its 150-line cap); else
  `docs/ARCHITECTURE.md` alone.
- `CHANGELOG.md`: Fixed, the hang made rarer and named; Changed, the GPU cost while kept, and that the bridge's
  saves and Kit's own Save (Q7's B) let the feed go before they write.
- `docs/TOOLS.md`: the same, under `inspect_prim` and `capture_viewport`, and under the save routes.

## Risks

| Risk | Answer |
|---|---|
| The hang still comes, on a new size, after 30 s idle, or in Kit's own views | Accepted: fewer views, not none; the server names it when it comes; the NVIDIA report (Q4) |
| A kept feed costs GPU and app updates while the user works in Kit (K6) | Accepted for 30 s after a capture, at any size (Q2: up to 75 % of Kit's updates at 4096x4096, #51's A11); the docs state the cost by size |
| A script that writes the root layer through USD itself, from `execute_script`, within 30 s of a capture writes the kept feed's render product into the user's file | Documented; Kit's own Save tears the feed down on `SAVING` (Q7's B) and the bridge's own saves release it first (G3) |
| A disable of the extension while a feed is kept leaves the render product in the root layer | `forget` deletes it when the stage is open, with the no-update teardown step 1 found quiet |
| A kept feed renders a camera the user deletes while it is kept | Kit renders a missing camera as it does for the viewport; the next call sets its own camera, and the feed goes in 30 s. Checked live in step 6 |
| The timer's release racing a call | The same lock and the generation number (Design) |
| The 5 s health check takes a Kit busy with a long synchronous `execute_script` for a hung one | The message says it may be busy, and only to restart if it stays silent for minutes; the next call clears the mark once `/health` answers |

## Owner calls

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does the bridge make fewer new views? A: one feed kept between calls, released after an idle time. B: no code change; the docs and the server's message only. C: one feed kept for the extension's life | A: K4 and K5 show it avoids most new views; C costs the GPU for as long as Kit runs |
| Q2 | How long is the feed kept after a call, and up to what size? 10 s, 30 s or 60 s; a cap at 1920x1080, or none | 30 s and 1920x1080, to be confirmed by step 1's costs: an agent's calls in one task usually come within 30 s, and #51's A11 puts a 4096x4096 feed at 75 % of the app's updates |
| Q3 | Should the server name the hang and fail in 5 s once Kit is silent (G4)? A: yes, worded as busy or stuck. B: no, today's "timed out" after 120 s on every call | A: the cost of a wrong guess is a message that says "may be busy" for a script past 125 s |
| Q4 | A report to NVIDIA with the repro and dumps? A: I draft it in `.local/` for you to post on NVIDIA's developer forum. B: none | A: only NVIDIA can fix the loop |
| Q5 | `capture_viewport` keeps `readOnlyHint` (#51's Q7), with the stage holding a kept feed's render product for up to 30 s after a call, and the feed costing 32 % to 42 % of the app's updates in that time (K6)? A: keep it. B: drop it, a one-way door changed | A: the scene the user made is unchanged, as with Kit's viewport's own render product; the bridge's saves never write it, Kit's own Save while a feed is kept does (Q7); the cost is the user's GPU's, not the stage's |
| Q6 | #54? A: `Refs #54`, kept open for its other shapes. B: `Closes #54` | A: its `usdrt` spin and descriptor errors aren't this, and its first hang came at a view Kit made |
| Q7 | Kit's own Save (File > Save, `save_stage`) while a feed is kept writes its render product into the file: up to 30 s after each capture, so for an agent capturing more often, its whole session. A: accept it and say so in TOOLS.md and CHANGELOG, as Kit writes its viewport's own. B: on Kit's `SAVING` event, tear the kept feed down as shutdown does (segmentation off, drop, graphs freed, delete, no updates), which step 1 measures | A, unless step 1 finds the no-update teardown quiet in E16's windows, then B: A leaves a render product prim beside Kit's own (step 1 checks what reopening such a file does); B is clean only if that teardown is |

Answers (serionist, 2026-11-01):

| # | Answer |
|---|---|
| Q1 | A: one feed kept between calls, released after an idle time |
| Q2 | 30 s, and no size cap: any size is kept |
| Q3 | A: the server names the hang and fails in 5 s while Kit stays silent |
| Q4 | A, and post it too: I draft the report, the maintainer reads the final text, and I post it on NVIDIA's developer forum under the maintainer's account once they say so |
| Q5 | A: `capture_viewport` keeps `readOnlyHint` |
| Q6 | B: `Closes #54`; its other shapes get an issue of their own if they recur |
| Q7 | As recommended: decided by step 1, A unless the no-update teardown is quiet in E16's windows, then B |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `06686cc`; a fresh refuter for each major. **Verdict:**
needs-fixes, two majors and five minors. **Now:** all seven fixed in this revision; round 2 reads the edits.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | A kept feed loses #57's guard for `capture_viewport`: `first_frame` returns at once on a feed with frames and `_settle_frames()` is 0 outside Path Tracing, so a capture straight after a camera switch or a USD move in the same request takes the previous view while its boxes follow the new camera (K14). Also `capture_viewport(camera_path=B)` within 30 s of a call on A. The refuter confirmed it, adding SKILL.md:60 and TOOLS.md:821 | fixed: every kept capture waits 20 frames of its own after the call sets the camera; the camera set on `CameraFeed` too; G2 and `test_26_04`; both docs listed |
| P2 | major | The kept feed's render product sits in the user's root layer for 30 s: `save_scene` (`stage.GetRootLayer().Export`), Kit's Save, `flatten_usd` and `export_prim` write it; a disable in the window leaves it; `test_12d` and `test_13b` fail; #51 rejected a kept feed for this, and it is the basis of `readOnlyHint`. The refuter confirmed it, correcting that `test_16_08`/`16_09` would pass while no longer testing a feed that goes, and `test_06_05` fails only by a timing race | fixed: the render product moved into the session layer (K11, K12), G3, `test_26_05`; shutdown deletes it when the stage is open; the changed tests named; Q5 re-asks #51's Q7 |
| P3 | minor | The silent mark fires when Kit is busy (a synchronous `execute_script` past 125 s) or a remote host is down (a connect timeout), telling the agent to restart | fixed: only a read timeout on a connected socket; worded as busy or stuck, restart if silent for minutes; the mark under `_lock` |
| P4 | minor | G2's "within the noise of two fresh feeds" fails on K7's own data (0.13 against 0.06) | fixed: G2 states K7's bounds |
| P5 | minor | The cost given is the 3D engine's share at 800x600 only; #51's A11 puts a feed at 32 % to 75 % of the app's updates by size | fixed: step 1 measures by size; a size cap in Q2 |
| P6 | minor | A feed whose segmentation failed is "healthy" and kept, so retries reuse a half-made sensor | fixed: released at once |
| P7 | minor | "#54's earlier `DrvPresentBuffers` one" was #114's; #54 has other shapes, one after a recording's render product went | fixed: In scope and Out of scope reworded; Q6 |

Refuted: Kit 107 lacks the `camera_path` setter (it has one, `hydra_texture-1.4.6`); Kit 107 lacks Events 2.0 stage
events (`omni.usd-1.13.10` has `stage_event_name` with `CLOSING` and `SAVING`); `discard` on `CLOSING` leaks
segmentation graphs (omni.syntheticdata resets itself); shutdown never reaches `forget` (it does, through
`recording.shut_down()`); the timer releases a feed mid-call (the same lock); segmentation on a kept feed makes views
(K5); the health check resends a timed-out request (`_exchange` never retries a `TimeoutError`); K3, K4 and K9
unsupported (they hold).

Improvements:
- Resize the kept texture in place, not release and remake: taken (K5).
- A generation number for the timer, the idle seconds a module constant: taken.
- `test_26_03` releases any kept feed first: taken, for every new test.
- Skip `enable_segmentation` when the kept feed has it on: taken.
- `put_back` leaves a feed the stage event discarded: taken.

### Round 2

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `9bf5c2a`, reading the edits and P1 to P7; a fresh refuter
for each major. **Verdict:** needs-fixes, one major (P8) and five minors, P9 cut to minor by its refuter. **Now:** all
fixed in this revision, with K15 and K16 added; P12 settled by a probe; round 3 reads the edits.

P1 to P6 fixed. P7 partly: the hang that ended at a view assignment was #54's first (2026-10-29), and its second came
right after a recording's render product was deleted; fixed in the lead, K1 and the scope table.

| # | Sev | Finding | Status |
|---|---|---|---|
| P8 | major | The move used `Sdf.CopySpec`, which replaces the session layer's spec: Kit's `deviceIds`, `viewportHandle` and omni.syntheticdata's `orderedVars` target and `ogPostProcessPath`, which it writes into the session layer as soon as segmentation is on, are lost when the move runs after segmentation (today's order turns it on before the first frame) or again after a change; a partial root `over` turns the session's `def` typeless. Segmentation then fails, the P6 rule releases the feed, and every call makes a new view again. Confirmed by the refuter on usd-core | fixed: the move merges and is idempotent, runs before segmentation, again in `put_back`, before the bridge's saves and exports and on `SAVING`; K16; step 2's test of two moves onto a full session spec; step 1 checks a segmented feed resized and re-aimed |
| P9 | minor | `test_16_08` and `test_16_09`'s "second capture at another size" compares the same render product by construction, since a resize keeps it (K5). The refuter cut it to minor: the comparison still catches an extra render product, and `test_26_03` covers the release | fixed: the helper releases any kept feed before each `HYDRA_TEXTURES` read |
| P10 | minor | `forget` deleting a segmented kept feed's render product at shutdown, with no updates to free its graphs first, floods Kit's log until the next stage (#51's E16) | fixed: a segmented feed's render product stays in the session layer until the stage closes |
| P11 | minor | "Segmentation failed to turn on" also caught a Kit without omni.syntheticdata, where `enable_segmentation` returns a reason; `capture_viewport` always asks, so every call would make a new view there | fixed: released only when the sensor raised or gave no legend |
| P12 | minor | A camera change and the move each re-set up the RTX view (`View 1 ... assigned to device 0`) without a `createViewport`, the lines every hang's log ends at, and the 600-call loop never changes the camera | settled by K15: 8,000 switches on a kept feed, no hang and no such lines; `test_26_03` counts the lines; step 6 adds a 600-call loop alternating cameras; step 1 checks the merged move; a Risks row |
| P13 | minor | The docs would say every capture waits 20 frames while the Design waited only through a kept feed | fixed: every capture waits, one code path |

Refuted: `flatten_usd` and `export_prim` (`without_session` opens the root layer alone); `save_scene` and Kit's Save
(the root layer only); `release` after the move (`delete_render_product` walks every layer, `move.txt`); a new stage
carrying the render product over; the timer racing a call; the health check resending; `test_12d`, `test_13b` and
`test_06_05` loosened (they fail if a feed is kept, never pass vacuously); #57's guard; Q5's framing.

Improvements:
- The move idempotent, also at `put_back`, before the bridge's saves and exports, and on `SAVING`: taken.
- The products target appended, keeping Kit's order: taken.
- A fallback if a resized feed's segmentation isn't at the new size: taken (release and remake).
- `test_12d`'s failing half checked straight after the call: taken.
- Q5 names the 30 s app-update cost: taken.

### Round 3

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `8096ce7`, reading the edits and P7 to P13. **Verdict:**
needs-fixes, one major (P14) and four minors. **Now:** P14 measured live (K17, K18) and the session-layer move dropped
for releasing the kept feed before the bridge's saves (G3, Q7); the minors fixed; round 4 reads the edits.

P7 fixed but for one point, now fixed: #54's first hang ended at a view assignment as `test_16_02` started play, a
view Kit made. P8 to P11 and P13 fixed (P13's step 3 wording now too). P12 settled, with K15's count corrected (161
assignment lines before the probe, 166 after) and `test_26_03` counting the first camera change.

| # | Sev | Finding | Status |
|---|---|---|---|
| P14 | major | After the first move the session spec holds copies of `camera` and `resolution`, so a camera change or resize Kit writes into the root layer is hidden: the feed renders the old camera at the old size while `CameraFeed.camera_path` and the boxes say the new one, #51's mismatch; `put_back`'s move then unions the camera targets | confirmed live (K17): Kit writes each change into the root layer and renders the composed values. A fix that let Kit's root `over` replace the session's properties gave the right camera and size but changed the image (K18). Fixed by dropping the move: the render product stays where Kit puts it, and the bridge's own saves and exports release the kept feed first (G3); Kit's own Save is Q7 |
| P15 | minor | A session `over` counts as having a specifier, so the merge rule read literally never copies the root's `def` | moot: no move |
| P16 | minor | `test_15f` wraps `create_hydra_texture` and expects "no frame"; a kept feed from `test_15e` at the same size would be reused | fixed: released first |
| P17 | minor | Which errors release the feed was unclear: `test_12d`'s failing half raises the handler's own `CaptureError` after frames came, `inspect_prim` records each angle's error; "gave no legend" also matches an empty view's good segmentation | fixed: any exception that escaped the capture, an angle's recorded error included; "no data", an empty legend being data |
| P18 | minor | G3 claimed Kit's Save and `export_prim`, but `test_26_05` covered `save_scene` and `flatten_usd` only | fixed: `test_26_05` covers `export_prim`; Kit's Save is Q7 |

Refuted: `SAVING` not synchronous (omni.usd's own test asserts its order); the merge not buildable (built on usd-core;
moot now); K15 not supporting "a changed camera makes no new view" (no `createViewport` and no assignment line across
8,001 switches after the first); the 20-frame wait slowing things badly (about 0.18 s; `set_camera` and `look_at` wait
on the viewport); the changed tests not checking what they did; shutdown leaving a segmented feed's render product
(moot with the new shutdown order).

Improvements:
- `camera_feed.release_kept()` for the live tests and the saves: taken.
- At shutdown, segmentation off and graphs freed before the render product goes: taken.
- Step 1 runs a moved, segmented feed through camera switches: replaced by K17 and K18's probes; step 1 keeps the
  segmented, resized, re-aimed check.

### Round 4

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `5fe8907`, reading the edits and P14 to P18. **Verdict:**
approved, four minors, all fixed in this revision; no further round.

P14 fixed (the move dropped), P15 moot, P16 and P17 fixed, P18 completed by P21's fix.

| # | Sev | Finding | Status |
|---|---|---|---|
| P19 | minor | Shutdown's fallback said a segmented feed's render product "is left for the next stage's leftovers", but `forget` clears the leftovers and nothing of the extension runs after: it stays in the root layer and a later save writes it | fixed: the consequence stated, in Design and Risks |
| P20 | minor | `test_12d` and `test_13b` read `before` while the warm call's feed is kept, so `assertEqual(after, before)` fails once it is released | fixed: released before `before` too |
| P21 | minor | `test_26_05`'s `export_prim` leg passes either way: the handler copies `prim_path`'s subtree only | fixed: it exports `/Render` |
| P22 | minor | Q7's B called "a known failure" though shutdown uses the same no-update teardown, which step 1 measures; "inert" unmeasured; "within 30 s" undersells an agent capturing more often; Q5 left out Kit's own Save; Q7's A had no Docs or CHANGELOG line | fixed: Q5 and Q7 reworded, the recommendation following step 1; step 1 reopens such a file; Docs and CHANGELOG lines |

Refuted: deadlock or re-entrancy (the save handlers aren't `@serial(_viewport)`); a save while a capture holds the
lock (it waits, then releases); a recording's feed (separate); `release`'s two updates in the save handlers (all
async); other routes writing the root layer to a file (none; `flatten_usd` with `input_path` included now); K17 and
K18 not supporting the drop (decoded offline: 0.0, 0.01, 226.0 against 2.0); `test_26_03`'s counts against K15's log
(the probe's second view came from turning its updates back on, which a kept feed never does); `test_16_08`,
`test_16_09`, `test_06_05`, `test_15f` loosened.

Improvements, all taken: step 1's leftover check removed; K15's five lines named; `_viewport` moved into
`camera_feed.py`, the at-once releases calling `release` directly; shutdown in `release`'s order minus the updates,
with E16's windows checked; `test_flatten_handler.py` named; an `inspect_prim` angle error test; the saves hold the
lock through their write.

**Verdict of the review:** approved: no blocker or major open; the owner calls Q1 to Q7 wait for the maintainer.
