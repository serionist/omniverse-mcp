---
title: Keep the capture feed between calls, and name Kit's renderer hang when a call meets it
issue: "#114"
status: draft
approved_by:
approved_at:
---

# Keep the capture feed between calls, and name Kit's renderer hang when a call meets it

Kit 110 (Isaac Sim 6.2) can hang for good during a new RTX view's first frames. Kit's main thread loops inside NVIDIA's
renderer, its log goes silent, and nothing but killing the app frees it. `inspect_prim` and `capture_viewport` make a
new view on every call, since each renders through a camera feed of its own (#51, #57), so an agent that captures
often meets the hang often: about one call in 300 to 400 in round 1's loop of real `inspect_prim` calls, and once at
view 97 of a Kit that had run both live suites (K13). #54's first hang, in the live suites on 2026-10-29, ended its
log at a new view too.

The hang is NVIDIA's, and no setting tried at run time avoids it. What the bridge can do is make fewer new views: keep
one feed between calls and point it at each call's camera. A changed camera makes no new view, and 8,000 camera
switches on one feed never hung (K15); a changed size makes one, though the texture can be resized in place. The server can also tell an agent what happened, at once, instead of
after 120 s on every later call.

## Goal

| Row | True when done | Shown by |
|---|---|---|
| G1 | `inspect_prim` and `capture_viewport` render through one kept feed. A call at the size of the last one, any camera, makes no new RTX view; a call at another size resizes the kept feed in place, one new view and the same render product. The kept feed is released after 30 s with no capture (Q1, Q2), when the stage closes, when a call fails in a way that leaves the feed in doubt, and when the extension shuts down. Above a size cap (Q2) a call uses a feed of its own, as today | `test_camera_feed.py`, `test_camera_handler.py`; live `test_26_03` (new, `test_scenarios.py`): views gained in Kit's log over a run of calls |
| G2 | A capture through a kept feed shows what one through a fresh feed shows, within K7's bounds (mean 0.2 of 255, 99th percentile 4), its segmentation and boxes agreeing with it (#51). That holds when the camera changed, or the stage was edited, just before the call, inside the same request (`execute_script`) | live `test_26_04` (new): camera B straight after camera A at one size, and a USD move then `mcp.capture_viewport()` in one script, each against a fresh feed |
| G3 | The kept feed's render product is in the session layer only: `save_scene`, Kit's own Save, `flatten_usd` and `export_prim` never write it, and a disable within the 30 s leaves nothing in the user's file (K11, K12) | live `test_26_05` (new): `save_scene` and `flatten_usd` straight after a capture write no `ovmcp_capture_`; `test_12d`'s root-layer check |
| G4 | A call whose socket, once connected, gets no answer for the server's timeout, when Kit then answers no `/health` within 5 s either, fails with a message that Kit has stopped answering; that it may be busy with a long script or stuck, most likely in NVIDIA's renderer (#114); and that if it stays silent for minutes it needs a restart. Each later call checks `/health` first, for 5 s, and fails at once the same way while Kit stays silent (Q3) | `test_client.py` with a fake socket that accepts and never answers; `test_tools.py` |
| G5 | `docs/TOOLS.md`, the plugin's scene skill, the README's troubleshooting and `docs/ARCHITECTURE.md` say what the hang looks like, what the bridge does about it and what a kept feed costs, by size (step 1) | review |

| In scope | Out of scope |
|---|---|
| The capture feed of `inspect_prim` and `capture_viewport`, its settle and its release | Recordings: each makes one feed, so one new view, for its whole length |
| Moving the kept feed's render product into the session layer | Kit's own viewport render product, which Kit keeps in the root layer (K12) |
| The server's message and fast failure for a Kit that stopped answering | Recovering a hung Kit: nothing in Kit's process can, since its main thread is the one stuck |
| A report to NVIDIA with the repro, drafted for the maintainer (Q4) | A fix inside Kit or the driver |
| #54's first hang, which ended at a new view (Q6) | #54's other shapes (its second settings-lock hang, right after a recording's render product was deleted; a `usdrt` population spin; "Out of resource descriptors"), and #114's phase-26 `DrvPresentBuffers` hang, unless they recur |

## What the probes show

On my own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, main's extension, with the
maintainer's other Kit apps on the same GPU (a windowed Isaac Sim and a 4096-environment training run). Every run's
lines, dumps and Kit log are in the main checkout's git-ignored `.local/handoff-2026-11-01/114/r2-r3/`. The probe is
`114-probe.py` (`--switch` for K15); `114-views.py`, `114-ghost.py`, `114-layers.py` and `114-move.py` measured K5 to
K7, K11 and K12.

| # | What | Evidence |
|---|---|---|
| K1 | Every hang so far came during a new RTX view's first frames: Kit's log ends at a view being set up (`createViewport`, `Added sensor`, `View 1 ... assigned to device 0`), then nothing | Round 1 (`--mode inspect`, call 416), 1b (`--mode toggle`, call 159), R2a, R2b, L1 to L3 and K13's logs; #54's first hang ended at `omni.rtx` view assignment |
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
| K15 | Camera switches on one kept feed don't hang: `--mode flicker --switch`, one feed rendering throughout, its `camera_path` set between the active camera and `/OmniverseKit_Top` every 3 frames, 8,000 switches in 7 minutes, no hang, where flicker's new views hung within 41 to 421. Kit's log gained no `createViewport` and no `View 1 ... assigned to device 0` lines for them (166, as #119's suites alone left on that Kit). A feed's first camera change, and K12's move, each logged the assignment lines once | `r4-camswitch.jsonl`, `r4-camswitch-kit.log` |
| K16 | `Sdf.CopySpec` replaces the destination spec, it doesn't merge: onto a session `over` holding `deviceIds`, `viewportHandle`, a segmentation `orderedVars` target and `ogPostProcessPath`, it left the root's `def` alone; a partial root `over` copied onto a full session `def` left a typeless `over`. omni.syntheticdata writes its segmentation into the session layer as soon as it is turned on (`SyntheticData.py`, `activate_node_template` under `Usd.EditContext(stage, session_layer)`) | round 2's usd-core checks, `copyspec.py`, `copyspec2.py` |

Not shown: the hang on a GPU no other Kit app uses (the maintainer's apps ran through every run, and they are the
maintainer's to stop), on Linux, on Isaac Sim 5.x (Kit 107), or with a render mode other than Real-Time Path Tracing.

## Design

### The kept feed (extension, `handlers/camera_feed.py`, `handlers/camera.py`)

- **`kept_feed(camera_path, width, height)`**, async, replaces `_new_feed` in both handlers, called holding `_viewport`
  as today. With no kept feed, it makes one and waits for its first frame, as today. With one on the open stage, it
  sets the camera on both the texture and `CameraFeed.camera_path` (the boxes and segmentation read the latter), and a
  new size in place on the texture and on `CameraFeed.width` and `height` (K5: one new view, the same render product).
  Above the size cap (Q2) it makes a feed for the call alone, released at its end as today.
- **Every capture waits** `CAMERA_SETTLE_FRAMES` plus Path Tracing's settle frames of its feed's own after the call
  has set the camera, before its first frame is taken, kept feed or fresh, whether or not the camera changed: the
  handler can't see a USD move or a drawing made just before the call (K14). One code path, about 0.18 s at K6's rate,
  and #57's guard for every call: the frame taken comes 20 of the feed's frames after the call starts, more than a
  fresh feed's 15 updates. `inspect_prim`'s per-angle settle stays as it is.
- **The session layer:** the root layer's spec of the render product and its products target move into the session
  layer (K12), under `Sdf.ChangeBlock`, so no save or export writes it. The move merges, never replaces (K16): each
  field, property and child of the root's spec goes into the session spec only where the session has no opinion, a
  relationship both hold gets the union of their targets, and the products target is appended to the session's list,
  keeping Kit's order. It is idempotent: a root layer naming nothing is a no-op. It runs in `kept_feed` straight after
  the texture is made, before segmentation is turned on; in `put_back`, which catches what a resize or camera change
  wrote back if step 1 finds Kit does; and before the bridge's own `save_scene`, `flatten_usd` and `export_prim`, and
  on Kit's `SAVING` stage event, which a synchronous move suits. `delete_render_product` already deletes from every
  layer.
- **`put_back(feed, healthy)`** replaces `release(feed)` at the end of each handler. A healthy feed starts the idle
  timer: 30 s with no call (Q2), then `release`. A feed that gave no frame (`NoFrameError`), met an error the handler
  didn't expect, or whose segmentation sensor raised as it was turned on, or gave no legend, is released at once, so a
  stalled feed or a half-made sensor is never kept (`_SEGMENTATION_AS_BEFORE`'s "capture again" then gets a feed of
  its own). A Kit without omni.syntheticdata, where `enable_segmentation` returns a reason and touches nothing, keeps
  its feed. A feed the stage event already discarded is left alone.
- **The timer:** a module constant, the idle seconds, so the unit tests run fast. Its release takes `_viewport`, then
  checks that the feed is still the kept one and that no call took it since (a generation number), so a timer that
  fires as a call puts the feed back does nothing.
- **Segmentation:** `kept_feed` turns it on only for a call that asks and only when the kept feed hasn't it on yet,
  and it stays on until the feed goes; turning it on and off makes no view (K5). Step 1 measures what a kept,
  segmented feed costs while idle; if more than K6's, it is turned off at the end of each call instead, and its
  graphs are still freed at release (#51's E16). If step 1 finds a resized feed's segmentation isn't at the new size,
  a size change on a segmented kept feed releases it and makes a new one instead of resizing.
- **The stage:** a stage `CLOSING` drops the kept feed at once and discards it (`discard`, which deletes its render
  product once a stage is open, #25's E13), through Kit's stage events on Events 2.0
  (`omni.usd.get_context().stage_event_name(...)` with `carb.eventdispatcher`, which Kit 107's `omni.usd` 1.13.10
  has too). omni.syntheticdata resets its own graphs on `CLOSING`, so none leak. `kept_feed` also checks the stage is
  the one the feed was made on.
- **Shutdown:** `forget` drops the kept feed and stops its timer. An unsegmented feed's render product is deleted when
  the stage is `OPENED` (`remove_render_product` already checks that). A segmented one's stays in the session layer,
  which no save writes, until the stage closes: deleting it without `release`'s two updates would leave its graphs in
  omni.syntheticdata's registry and flood Kit's log (#51's E16), and shutdown can't wait updates.
- **The answer:** unchanged. `inspect_prim`'s and `capture_viewport`'s results don't say whether the feed was kept.

Alternatives:
- A feed per call (today): a new view each call, so the hang's rate.
- One feed kept for the extension's life (Q1's C): the GPU cost for as long as Kit runs after one capture.
- Turning the kept feed's updates off between calls: a new view each time it comes back on (K5), so no gain.
- Releasing the kept feed before each save instead of moving it: covers the bridge's own routes, but not Kit's Save
  (a synchronous event can't wait `release`'s two updates) or a save from `execute_script`.
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

## Compatibility

No tool, schema, route, setting or output path changes. Two things users notice: the GPU busier for 30 s after a
capture (by size, step 1), and a clearer error when Kit stops answering. `capture_viewport`'s `readOnlyHint` rests on
#51's Q7, "the stage holds nothing more after the call"; with a kept feed the session layer holds its render product
for up to 30 s after, as it holds Kit's viewport's own state, and the root layer holds nothing. Q5 asks the maintainer
to keep the hint on that basis. An older extension with this server gets the new error; a new extension with an older
server keeps its feed and gets today's error. Both are fine (0.x).

## Steps

1. **Measure and look up:** Kit's stage events on Events 2.0 in Kit 110 and 107 (Context7, the installed sources);
   whether a resize or a camera change writes into the root layer again; a kept feed's idle cost at 640x480,
   1920x1080 and 4096x4096 (frames a second, Kit's updates a second, the 3D engine's share, VRAM), with and without
   segmentation, which sets the size cap and the segmentation rule; a resized feed's segmentation at the new size; a
   segmented kept feed, resized and re-aimed, still giving a legend; whether the merged move logs a view's set-up
   again (K15 saw the assignment lines once at K12's copy). Recorded in this plan.
2. **`camera_feed.py`:** `kept_feed`, `put_back`, the move to the session layer, the timer with its generation, the
   stage subscription, `forget`. Unit tests in `tests/test_camera_feed.py` with the fake texture: same size reused
   with the camera set on both; another size resized in place; above the cap a feed of its own; the session-layer
   move, run twice onto a session spec holding Kit's fields and omni.syntheticdata's `orderedVars` target and
   `ogPostProcessPath` (usd-core), keeping all of them, and a no-op on a root layer naming nothing; the timer releases
   after the idle seconds and a call stops it; a stale timer does nothing; `NoFrameError` and a sensor that raised
   release at once, a Kit without omni.syntheticdata keeps its feed; a stage closing drops and discards; shutdown
   forgets, deleting an unsegmented feed's render product and leaving a segmented one's.
3. **`camera.py`:** both handlers through `kept_feed` and `put_back`, and the settle on every kept capture;
   `test_camera_handler.py` checks a call's feed is put back, the second call at the same size makes none, and the
   settle is waited when the feed already has frames.
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
    `createViewport` in Kit's log and no more `View 1 ... assigned to device 0` lines than step 1 finds the feed's
    making and moving costs; a sixth at another size one more view; the feed gone 30 s after the last call (no
    `ovmcp_capture` render product on the stage);
  - `test_26_04`: camera B straight after camera A at one size, and a USD move then `mcp.capture_viewport()` inside one
    `execute_script`, each against a fresh feed's capture within K7's bounds;
  - `test_26_05`: `save_scene` and `flatten_usd` straight after a capture write no `ovmcp_capture_`.
- **Live, changed,** each still checking what it checked, after the kept feed goes:
  - `test_12d` and `test_13b`: `_assert_nothing_left` runs after the kept feed's release, which the tests ask for
    through `execute_script`; its root-layer check also runs straight after the call, where the root layer already
    names no feed. `test_12d`'s failing half checks straight after the call with no release asked for, since a call
    that fails releases its feed itself;
  - `test_16_08` and `test_16_09`: `_a_capture_at_once_holds_the_drawing` releases any kept feed (through
    `execute_script`) before each `HYDRA_TEXTURES` read, so both reads compare stages with no kept feed and an extra
    render product left behind still fails it; that the kept feed itself goes is `test_26_03`'s;
  - `test_06_05`: its `HYDRA_TEXTURES` reads after the kept feed's release.
- **Live, existing:** both suites whole, on Z-up and Y-up.
- **Not shown:** that the hang never comes, since a new size, the first call after 30 s idle, a call above the cap,
  and Kit's own views still make new views; Linux; Isaac Sim 5.x; a GPU of its own.

## Docs

- `docs/TOOLS.md`: `inspect_prim` and `capture_viewport` say a feed is kept for 30 s after a call and what it costs;
  the read-only hint row (line 42) says the session layer holds it while kept; line 821's "first frame comes some 15
  updates later" becomes the 20 frames every capture waits.
- `plugin/skills/scene/SKILL.md:60` ("render the camera afresh for each call, so the move shows"): a move or drawing
  made before the call still shows, since every capture waits 20 frames.
- `README.md` troubleshooting: Kit stops answering, what the server says, when to restart it, #114.
- `docs/ARCHITECTURE.md`: the kept feed, its session layer and its release; the client's silent mark.
- `AGENTS.md` Traps: #51/#57's row's guard rewritten (the frame taken comes 20 of the feed's frames after the call
  sets the camera), and a row for this hang only if a line can be freed (it is at its 150-line cap); else
  `docs/ARCHITECTURE.md` alone.
- `CHANGELOG.md`: Fixed, the hang made rarer and named; Changed, the GPU cost while kept.

## Risks

| Risk | Answer |
|---|---|
| The hang still comes, on a new size, after 30 s idle, above the cap, or in Kit's own views | Accepted: fewer views, not none; the server names it when it comes; the NVIDIA report (Q4) |
| A kept feed costs GPU and app updates while the user works in Kit (K6) | Accepted for 30 s after a capture, below the size cap; Q1 and Q2 are the maintainer's |
| Kit writes the render product back into the root layer on a later change | Step 1 checks a resize and a camera change; the merged move runs in `put_back`, before the bridge's saves and exports and on `SAVING`; `test_26_05` and `test_12d` read the root layer |
| The move replaces what Kit or omni.syntheticdata wrote in the session layer (K16) | The move merges and runs before segmentation; step 2's unit test moves twice onto a full session spec |
| The move re-sets up the RTX view once (K15), on a feed already new | Accepted: once per kept feed made, against a view per call today; step 1 records whether the merged move does it |
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
| Q5 | `capture_viewport` keeps `readOnlyHint` (#51's Q7), with the session layer holding a kept feed's render product for up to 30 s and the root layer nothing, and the feed costing 32 % to 42 % of the app's updates in that time (K6)? A: keep it. B: drop it, a one-way door changed | A: the user's file never holds it (G3), as it never holds Kit's viewport state; the cost is the user's GPU's, not the stage's |
| Q6 | #54? A: `Refs #54`, kept open for its other shapes. B: `Closes #54` | A: its `usdrt` spin and descriptor errors aren't this |

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
