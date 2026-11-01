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
often meets the hang often: about one call in 300 to 400 in round 1's loop of real `inspect_prim` calls. #54's hang, in
the live suites, ended its log at a new view too.

The hang is NVIDIA's, and no setting tried at run time avoids it. What the bridge can do is make fewer new views: keep
one feed between calls and point it at each call's camera. A changed camera makes no new view; a changed size does. The
server can also tell an agent what happened, at once, instead of after 120 s on every later call.

## Goal

| Row | True when done | Shown by |
|---|---|---|
| G1 | `inspect_prim` and `capture_viewport` render through one kept feed. A call at the size of the last one, any camera, makes no new RTX view. A call at another size makes one, and the kept feed is then that size. The kept feed is released after 30 s with no capture (Q1, Q2), when the stage closes, and when the extension shuts down | `test_camera_handler.py`, `test_camera_feed.py`; live, a new `test_26_03` in `test_scenarios.py` counts the views Kit's log gained over five calls |
| G2 | A capture through a kept feed shows what one through a fresh feed shows, within the noise of two fresh feeds, and its segmentation and boxes still agree with it (#51) | live, a new test: a fresh and a kept capture of the same view compared |
| G3 | A call that times out, when Kit then answers no `/health` within 5 s either, fails with a message that Kit has stopped answering, that its main thread is likely stuck in NVIDIA's renderer (#114), and that only a restart frees it. Each later call checks `/health` first, for 5 s, and fails at once the same way while Kit stays silent (Q3) | `test_client.py`, `test_tools.py` with a bridge that stops answering |
| G4 | `docs/TOOLS.md`, the README's troubleshooting and `docs/ARCHITECTURE.md` say what the hang looks like, what the bridge does about it and what it costs: about 19 % more of the GPU's 3D engine while a feed is kept (an RTX 5090 at 800x600), for up to 30 s after a capture | review |

| In scope | Out of scope |
|---|---|
| The capture feed of `inspect_prim` and `capture_viewport`, and its release | Recordings: each makes one feed, so one new view, for its whole length |
| The server's message and fast failure for a Kit that stopped answering | Recovering a hung Kit: nothing in Kit's process can, since its main thread is the one stuck |
| A report to NVIDIA with the repro, drafted for the maintainer (Q4) | A fix inside Kit or the driver |
| #54, the same hang in the live suites | Hangs of other shapes: #54's earlier `DrvPresentBuffers` one, a phase-26 one, unless they recur |

## What the probes show

On my own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, main's extension, with the
maintainer's other Kit apps on the same GPU (a windowed Isaac Sim and a 4096-environment training run). Every run's
lines, dumps and Kit log are in the session's scratchpad `114/`. The probe is `114-probe.py`; `114-views.py` and
`114-ghost.py` measured K4 to K6.

| # | What | Evidence |
|---|---|---|
| K1 | Every hang so far came during a new RTX view's first frames: Kit's log ends at a view being set up (`createViewport`, `Added sensor`, `View 1 ... assigned to device 0`), then nothing | Round 1 (`--mode inspect`, call 416), 1b (`--mode toggle`, call 159), R2a and R2b's logs; #54's log ended at `omni.rtx` view assignment too |
| K2 | The hung main thread is busy, not blocked: 7.6 to 9.7 CPU seconds in 11 to 14, under Kit's update, in `rtx.hydra`, `carb.scenerenderer-rtx`, `gpu.foundation` and the driver, the top frames changing between samples. The GPU's 3D engine still shows work for Kit (about 10 %). The log stays silent | R2a, R2b, L1, L2, L3's `-activity.txt` and `-samples.txt` |
| K3 | The fast repro: one feed whose updates go on for 3 frames and off again, aimed at the next angle each time, makes a new view every 0.15 s. It hung at about view 101 (R2a), 421 (R2b), 121 (L1), 101 (L2) and 41 (L3), each within 2 minutes | `r2a-flicker.jsonl` and the others |
| K4 | With no new views, no hang: `--mode persist`, inspect_prim's steps through one feed made at the start, ran 600 captures with segmentation in 8 minutes, 35,312 frames, one view | `r3-persist.jsonl` |
| K5 | Which changes to a live texture make a new view: its `camera_path` set, none; its width and height set, one; its updates off then on, one; nothing changed, none. Instance segmentation turned on, read and turned off on a kept feed, none | `views.jsonl`, `ghost.jsonl` |
| K6 | A kept feed rendering while idle: 113 frames a second; Kit's share of the GPU's 3D engine 30 % with it, 12 % after its release, 11 % before (800x600, RTX 5090) | `views.jsonl` |
| K7 | A kept feed's capture, after it rendered another view, against a fresh feed's of the same view: mean 0.13 of 255, 99th percentile 3, against 0.06 and 2 between two fresh feeds. The same 120 frames later, so no ghost of the earlier view fades out: the kept feed has simply rendered more frames than a fresh one's 24 | `114-ghost-compare.py` |
| K8 | Run-time settings didn't avoid it: `/rtx/hydra/multiTickRate/enableRenderQuality` false (L1, view 121); that with `waitForInitialStreamingDone`, `multiTickRateParallelRendering`, `perSensorTickTlas` and `/rtx/ecoMode/enabled` false (L2, view 101). `/rtx/rendermode` didn't reach the feed, whose render product carries its own `omni:rtx:rendermode` (L3) | `r3-*.jsonl` |
| K9 | Free memory was 8.8 to 13 GB at every hang this round, so memory is not the trigger | the HANG lines |
| K10 | A verbose trace of Kit's multi-tick channels wrote nothing to Kit's log (R2b), so the log can't show what the loop does | `r2b-kit.log` |

Not shown: the hang on a GPU no other Kit app uses (the maintainer's apps ran through every run, and they are the
maintainer's to stop), on Linux, on Isaac Sim 5.x (Kit 107), or with a render mode other than Real-Time Path Tracing.

## Design

### The kept feed (extension, `handlers/camera_feed.py`, `handlers/camera.py`)

- **`kept_feed(camera_path, width, height)`**, async, replaces `_new_feed` in both handlers. It returns the kept feed when
  there is one of that size on the open stage, with its `camera_path` set to the call's, or else releases the kept one
  (`release`, as today) and makes a new one, waiting for its first frame as today. A camera change makes no view (K5).
- **`put_back(feed, healthy)`** replaces `release(feed)` at the end of each handler. A healthy feed starts the idle
  timer: 30 s (Q2) with no call, then `release`. A feed that gave no frame (`NoFrameError`) or met an error the handler
  didn't expect is released at once, so a stalled feed is never kept.
- **The timer and a call never race:** the timer's release takes the same lock as the capture handlers (`_viewport`,
  `@serial`), and a call that takes the feed stops the timer first.
- **The settle stays:** each angle still waits `CAMERA_SETTLE_FRAMES` plus Path Tracing's settle frames after aiming,
  so a frame from before the call or the aim is never taken (#57). K7 shows the result matches a fresh feed's.
- **Segmentation:** turned on for a call that asks for it and left on until the feed goes; turning it on and off makes
  no view (K5). Step 1 measures what a kept, segmented feed costs while idle; if it is more than K6's, it is turned off
  at the end of each call instead, which K5 shows is free of views too, and its graphs are still freed at release.
- **The stage:** a stage closing drops the kept feed at once and discards it (`discard`, which deletes its render
  product once a stage is open, #25's E13), through Kit's stage event `CLOSING` on Events 2.0
  (`carb.eventdispatcher`, `omni.usd.get_context().stage_event_name`), looked up through Context7 in step 1. So a kept
  feed never renders a camera the next stage hasn't got. `kept_feed` also checks the stage is the one the feed was made
  on.
- **Shutdown:** `forget` drops the kept feed and stops its timer, deleting nothing, as today.
- **The answer:** unchanged. `inspect_prim`'s and `capture_viewport`'s results don't say whether the feed was kept.

Alternatives:
- A feed per call (today): a new view each call, so the hang's rate.
- One feed kept for the extension's life (Q1's C): no idle cost saved, 19 % of a 5090's 3D engine for as long as Kit
  runs after one capture.
- Turning the kept feed's updates off between calls: a new view each time it comes back on (K5), so no gain.
- A Kit setting: none tried avoided it (K8).

### Naming the hang (server, `client.py`, `tools/_bridge.py`)

- A request that times out is followed by `/health` on a fresh connection with a 5 s timeout. When that answers too,
  the error is today's. When it doesn't, `bridge_answer` raises a `ToolError` that says: Kit at `<host>:<port>` stopped
  answering, a call and `/health` both; its main thread is likely stuck in NVIDIA's RTX renderer (#114), which happens
  during a new camera view's first frames; nothing frees it but a restart of the Kit app.
- The client remembers that Kit went silent. Its next request first asks `/health` for 5 s: silent still, the same
  error at once; answered, the mark clears and the request goes as usual. So an agent learns in 5 s, not 120.

## Compatibility

None of the one-way doors: no tool, schema, route, setting or output path changes. Users see captures as before, a
GPU busier for 30 s after a capture, and a clearer error when Kit hangs. An older extension with this server gets
the new error; a new extension with an older server keeps its feed and gets today's error. Both are fine (0.x).

## Steps

1. **Measure and look up:** Kit 110's stage events on Events 2.0 and their Kit 107 form (Context7); a kept, segmented
   feed's idle cost against K6's, to settle the segmentation rule above. Recorded in this plan.
2. **`camera_feed.py`:** `kept_feed`, `put_back`, the timer, the stage subscription, `forget`. Unit tests in
   `tests/test_camera_feed.py` with the fake texture: same size reused with the camera set; another size releases and
   makes; the timer releases after 30 s of no call and a call stops it; `NoFrameError` releases at once; a stage
   closing drops and discards; shutdown forgets.
3. **`camera.py`:** both handlers through `kept_feed` and `put_back`; `test_camera_handler.py` checks a call's feed is
   put back, not released, and the second call at the same size makes none.
4. **The server:** `client.py`'s silent mark and health check, `_bridge.py`'s message; `test_client.py` (a fake socket
   that accepts and never answers) and `test_tools.py`.
5. **Docs and CHANGELOG** (Docs, below).
6. **Live:** the new tests and both suites on a Z-up and a Y-up stage; the probe's `--mode inspect` loop for 600 calls
   with the branch's extension (round 1 hung at 416 on main's); AI phases 3, 22 and 26.

## Tests

- **Unit:** step 2 to 4's tests; the tool contract unchanged (`test_contract.py`).
- **Live, new,** in `test_scenarios.py`: `test_26_03`, five `inspect_prim` and `capture_viewport` calls at one size gain one `createViewport`
  in Kit's log, a sixth at another size one more; a kept feed's capture of a view against a fresh one's, within K7's
  bounds; the feed gone 30 s after the last call (no `ovmcp_capture` render product on the stage).
- **Live, existing:** both suites whole, on Z-up and Y-up.
- **Not shown:** that the hang never comes, since a new size, the first call after 30 s idle, and Kit's own views
  still make new views; Linux; Isaac Sim 5.x; a GPU of its own.

## Docs

- `docs/TOOLS.md`: `inspect_prim` and `capture_viewport` say a feed is kept for 30 s after a call, and what it costs.
- `README.md` troubleshooting: Kit stops answering, what the server says, restart it, #114.
- `docs/ARCHITECTURE.md`: the kept feed and its release; the client's silent mark.
- `AGENTS.md` Traps: a row for this hang and its guard, only if a line can be freed (it is at its 150-line cap);
  else `docs/ARCHITECTURE.md` alone.
- `CHANGELOG.md`: Fixed, the hang made rarer and named; Changed, the GPU cost while kept.

## Risks

| Risk | Answer |
|---|---|
| The hang still comes, on a new size, after 30 s idle, or in Kit's own views | Accepted: fewer views, not none; the server names it when it comes; the NVIDIA report (Q4) |
| A kept feed costs GPU while the user works in Kit (K6) | Accepted for 30 s after a capture; Q1 and Q2 are the maintainer's |
| A kept feed renders a camera the user deletes while it is kept | Kit renders a missing camera as it does for the viewport; the next call sets its own camera, and the feed goes in 30 s. Checked live in step 6 |
| The timer's release racing a call | The same lock (Design) |
| The 5 s health check mistakes a busy Kit (a long `execute_script`, a stage loading) for a hung one | `/health` never takes the capture lock and answers while another call runs; a stage load blocks the main thread, so a silent `/health` for 5 s after a 120 s timeout is rare enough, and the message says "likely" |

## Owner calls

| # | Question | Recommendation |
|---|---|---|
| Q1 | How does the bridge make fewer new views? A: one feed kept between calls, released after an idle time. B: no code change; the docs and the server's message only. C: one feed kept for the extension's life | A: K4 and K5 show it avoids most new views; C costs the GPU for as long as Kit runs |
| Q2 | How long is the feed kept after a call? 10 s, 30 s or 60 s | 30 s: an agent's calls in one task usually come within it; about 19 % of a 5090's 3D engine for that long |
| Q3 | Should the server name the hang and fail in 5 s once Kit is silent (G3)? A: yes. B: no, today's "timed out" after 120 s on every call | A |
| Q4 | A report to NVIDIA with the repro and dumps? A: I draft it in `.local/` for you to post on NVIDIA's developer forum. B: none | A: only NVIDIA can fix the loop |

## Plan review

Not reviewed yet.
