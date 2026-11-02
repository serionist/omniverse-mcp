---
title: Record through the kept capture feed, so a recording sets up no new RTX view
issue: "#141"
status: draft
approved_by:
approved_at:
---

# Record through the kept capture feed, so a recording sets up no new RTX view

Kit 110 (Isaac Sim 6.2) can hang for good during a new RTX view's first frames (#114, isaac-sim/IsaacSim#920). #131
kept one camera feed between `capture_viewport` and `inspect_prim` calls, so a capture rarely sets one up now, but
`start_recording` still makes a feed of its own for each recording and deletes it at the stop: one new view a
recording. Release 0.4.0's AI run hung so on phase 6's seventh `start_recording` call (#141).

The maintainer chose one kept feed for both (#141, 2026-11-02): a recording takes the kept feed, points it at its own
camera and size, and puts it back at the stop, where it waits 30 s for the next capture or recording, as a capture's
does.

## Goal

| Row | True when done | Shown by |
|---|---|---|
| G1 | `start_recording` renders through the kept feed when one is kept on the open stage: its camera set in place, a new view only when its size differs (#114's K5, K15). With none kept, it makes one, as today | `test_camera_feed.py`, `test_recording_handler.py`; live `test_26_06` (new): Kit's log gains one view over a capture, a recording, a capture and a recording at one size |
| G2 | `stop_recording` puts a healthy feed back as the kept one, on the 30 s idle clock, when none is kept meanwhile and the stage is the one it started on; otherwise it releases it, in `release`'s order. Frames stopping early (a stage change, the camera gone), a start that fails, and the extension's shutdown tear the feed down at once, as today, in the order that frees a capture's segmentation graphs | the same unit tests; live `test_06_06` (changed), `test_06_09`, `test_17_05`, `test_17_07`, `test_17_08` |
| G3 | A recording's frame 0 through the kept feed shows the recording's camera, not the camera the last capture rendered: the start waits the frames a capture waits after it sets the camera | live `test_26_06`: frame 0 against a fresh feed's capture of that camera, by `test_26_04`'s checks (#114's K19) |
| G4 | Every feed is named `ovmcp_feed_<id>`, whichever call made it, since either may use it later | `test_camera_feed.py`; the live checks that look for a kept feed |
| G5 | `start_recording`'s answer, `stop_recording`'s description, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, the scene skill, the README and two scenario Verify lines say the render is shared and kept 30 s after a stop | review |

| In scope | Out of scope |
|---|---|
| The recording's feed: where it comes from, its settle, where it goes at the stop | A capture during a recording: it finds no kept feed and makes one, kept as usual; the recording's then goes at its stop. Rare, since agents call tools one at a time |
| Feed names | Kit's Save, `save_scene`, `flatten_usd` or `export_prim` during a recording: they write the recording's render product, as today, since the recording holds it; once it is kept after the stop, they leave it out as they do a capture's (#114) |
| The docs and the scenario lines that say a recording deletes its render product at the stop | #114's other new views: a new size, the first call after 30 s idle, Kit's own views |

## Design

### The feed a recording uses (extension, `handlers/camera_feed.py`)

Two functions beside `kept_feed` and `put_back`, for a user of the feed that holds it longer than one call:

- **`lend(camera_path, width, height)`,** async: takes `_viewport`, so it waits for a capture running now; takes the
  kept feed off the slot (`_kept.let_go()`, which stops the idle timer and moves the generation on) and aims it, or
  makes a new feed. A kept feed of another stage is discarded first, as `kept_feed` does; a feed whose `aim` raises is
  torn down and the error rises. The lent feed is in no slot while the recording holds it, so the stage events, the
  idle timer and the saves' `without_kept_feed` never touch it, as today with a recording's feed.
- **`hand_back(feed, stage_id, healthy)`,** async: kept, on the idle timer, when `healthy`, no other feed is kept, the
  feed still renders (not dropped), and the stage open now is `stage_id` and `OPENED`; `_observe_stage()` first, as
  `kept_feed` calls it. Otherwise `release(feed)`. It takes `_viewport` when free; when a capture holds it, it
  releases the feed instead of waiting, so `stop_recording` never waits behind a capture (one view more for the next
  call, in a case agents rarely make).
- **`let_go_now(feed)`:** `_tear_down_at_once`, public: segmentation off if on, the feed dropped, its graphs freed if
  it ever had any, its render product deleted now or from the next open stage. For what can't await: frames stopping
  early on an update, and shutdown.

A lent feed may have served captures with segmentation: its sensor is off (each capture turns it off as it puts the
feed back), but its graphs stay until it goes. So no recording path uses `discard` any more, which drops a feed and
deletes its render product without freeing graphs: one left in omni.syntheticdata's registry when its render product
goes makes Kit log hundreds of errors a second (#51's E16). A feed a recording made, never segmented, goes the same
way it goes today: `_tear_down_at_once` of an unsegmented feed is `discard`.

`CameraFeed`'s default prefix becomes `ovmcp_feed`, and `kept_feed` passes none (G4). A capture's feed renders a
recording later and the reverse, so a name that says which call made it would mislead whoever reads the stage.
Alternative: keep the two prefixes and let each check accept both; rejected, for the same reason.

### The recording handler (extension, `handlers/recording.py`)

- **Start:** after its checks and a forced end, `feed = await lend(camera_path, width, height)`. It then waits the
  feed's first frame, as today (at once for a kept feed, which has frames), then `CAMERA_SETTLE_FRAMES` plus Path
  Tracing's settle frames, as every capture does after it sets the camera, so frame 0 shows the recording's camera
  and what was done just before (G3; #114's K14: a kept feed shows the previous view for 1 update or 2). One path for
  a new feed and a kept one: 20 frames, about 0.13 s at #114's K6 rate, more than a new feed needs and what a capture
  pays. A settle that runs out of time still starts, as today; a frame that never comes fails it. A start that fails
  after `lend` tears the feed down with `let_go_now`, as `discard` did.
- **Each frame:** unchanged, but a frame whose capture raised marks the session in doubt (`session.doubted`), as a
  capture's escaped error does its feed. A frame cancelled because frames stopped is not doubt.
- **Frames stop early** (stage closing or changed, camera gone): `let_go_now(feed)`, at once, as `discard` was.
- **Stop (`_end`):** after the frames in flight, `await hand_back(feed, session.stage_id, healthy=not
  session.doubted)`. Its failure is reported in the stop's note as a failed deletion is today. A forced start's `_end`
  hands back too, so the new recording takes the same feed.
- **Shutdown:** `let_go_now(feed)`, then `forget()`, which forgets render products still waiting for a stage. Today's
  shutdown drops the feed and deletes nothing; the kept feed's shutdown (`forget`) deletes its render product while a
  stage is open, measured quiet (#114's S4), and a lent feed may be one.
- **The answer:** unchanged keys; `render_product` names the lent feed's.

### The server (`src/omniverse_mcp/tools/recording.py`)

- `start_recording`'s line `Renders into <path>, deleted at stop` becomes `Renders into <path>, the render captures
  share, kept 30 s after the stop for the next capture or recording`.
- `stop_recording`'s description: "and delete the recording's render product" becomes "and hand its render back to
  the captures, kept 30 s". `start_recording`'s: "through a render of its own" becomes "through the render
  `capture_viewport` and `inspect_prim` use". Descriptions aren't in the tool contract (`test_contract.py`).

### Alternatives

- **A second feed kept for recordings** (#141's second option): a recording after captures still makes a view, and
  two feeds may render while idle, twice #114's cost.
- **A pool of two feeds** (the third): a capture during a recording finds the second; the most code, and up to twice
  the idle cost, for a case agents rarely make.
- **The capture during a recording renders through the recording's feed** when the camera and size match: it would
  share frames with the recording's delegates and turn segmentation on under it. Not worth the risk for a rare case.

## Compatibility

No tool, schema, route, setting or output path changes; no one-way door. Users notice:

- after a recording, its render stays up to 30 s (the GPU cost #114 states for a kept feed, by size: a 4096x4096
  recording's feed costs about 5.5 GB of video memory and half of Kit's updates while kept, where today it goes at the
  stop);
- the render product is named `ovmcp_feed_<id>`, not `ovmcp_recording_<id>` or `ovmcp_capture_<id>`.

An older extension with this server: the start line says the render is kept when that extension deletes it at the
stop; this extension with an older server: the line says deleted at stop. Both are wrong only in that line (0.x).

## Steps

1. **`camera_feed.py`:** `lend`, `hand_back`, `let_go_now`, the prefix. `tests/test_camera_feed.py` with its fake
   texture: `lend` with a feed kept takes it off the slot, aimed, the timer stopped, and a stale idle release does
   nothing; with none, a new feed named `ovmcp_feed_`, not kept; a kept feed of another stage is discarded first; an
   `aim` that raises tears the feed down; `hand_back` healthy into an empty slot keeps it and starts the timer; with
   another feed kept, the stage changed or closing, the feed dropped, or in doubt, releases it in `release`'s order;
   with `_viewport` held, releases without waiting; `let_go_now` of a segmented feed frees its graphs and deletes its
   render product.
2. **`recording.py`:** the handler through `lend`, `hand_back` and `let_go_now`. `tests/test_recording_handler.py`'s
   fake `camera_feed` module offers them: the start lends at the camera and size and waits first frame, then 20 plus
   the settle frames; stop hands back healthy; a frame that raised hands back in doubt; frames stopping early let go
   at once and hand nothing back; a failed start lets go; a forced start hands the old feed back before it lends;
   shutdown lets go, then forgets. The existing tests keep what they check, with `discard` read as `let_go_now`.
3. **The server:** the start line and the two descriptions; `tests/test_tools.py`'s start-line test.
4. **Docs and CHANGELOG** (Docs, below).
5. **Live:** the new and changed tests on a Z-up and a Y-up stage; both suites whole; AI phases 6, 7, 16, 17 and 26.
6. **finish-work:** `uv run tools/gate.py full`, `review-code` until clean, the PR, with the live runs it names.

## Tests

- **Unit:** steps 1 to 3; the tool contract unchanged.
- **Live, new:** `test_26_06` in `test_scenarios.py`, any kept feed released first and after: a capture at 320x240 of
  the viewport's camera; a recording at 320x240 of `/World/KeptCam`, a few frames, stopped; a capture; another
  recording; stopped. Kit's log gains one `createViewport` over the four, every render product named is the same
  `ovmcp_feed_`, and one feed is kept after the stop. The first recording's frame 0 against a fresh feed's capture of
  `/World/KeptCam` at 320x240 (after `release_kept`), by `test_26_04`'s ghost, mean and 99th percentile checks.
- **Live, changed:**
  - `test_06_06`: while recording, the render product is on the stage; after the stop it is the kept feed; after
    `release_kept` it is gone from every layer and from the render settings;
  - `test_26_03`'s view-assignment pattern, `_kept_feeds()`, `test_26_05`'s and `test_integration.py`'s
    `ovmcp_capture_` checks: `ovmcp_feed_`;
  - `test_17_08`: its capture's kept feed is lent to the recording, which the open stops; the render product still
    goes, as it checks now.
- **Live, existing:** both suites whole, on Z-up and Y-up; `test_06_09`, `test_17_05` and `test_17_07` unchanged.
- **AI scenarios:** 6.4 to 6.9's line "after `stop_recording()` it is gone" becomes "after `stop_recording()` it is the
  kept feed, gone 30 s later with no capture or recording"; 16.8's `ovmcp_capture_<id>` becomes `ovmcp_feed_<id>`,
  and "a recording's render product" leaves its failing cases, since a recording stopped before may have left the
  kept one.
- **Not shown:** that the hang never comes on a recording: a new size, the first call after 30 s idle, and a capture
  during a recording still set up views; Linux; Isaac Sim 5.x.

## Docs

- `docs/TOOLS.md`: `start_recording` (renders through the shared render, kept 30 s after the stop; the answer's
  `render_product`), `stop_recording` (hands the render back), the kept-render note under `capture_viewport` (shared
  with recordings; a recording's size is kept too), the read-only row's capture wording unchanged.
- `docs/ARCHITECTURE.md`: Recording System's start and stop, the kept feed section (lent to a recording), the
  handlers row.
- `plugin/skills/scene/SKILL.md`'s cost row: captures and recordings slow Kit down for 30 s after.
- `README.md`'s hang entry: the bridge keeps one render for captures and recordings.
- `AGENTS.md`'s #57/#51 Traps row: kept between calls and recordings (#114, #141), within its line.
- `CHANGELOG.md` under Unreleased: Fixed, recordings set up no new view at a kept feed's size (#141); Changed, the
  render kept 30 s after a recording and the render products' new name.
- `test_project/scenarios.md`: the two Verify lines (Tests).

## Risks

| Risk | Status |
|---|---|
| Frame 0 shows the previous camera | Resolved by the 20-frame settle; `test_26_06` checks it |
| A lent feed's segmentation graphs leak when a recording tears it down | Resolved: every recording path tears down through `release` or `_tear_down_at_once`, never `discard`; unit tests |
| A large recording's feed costs the GPU 30 s after the stop | Accepted, as #114's Q2 accepted it for captures; TOOLS.md states it |
| `stop_recording` waits behind a capture for the lock | Resolved: it releases the feed instead of waiting |
| A capture during a recording sets up a view, and the recording's feed then goes | Accepted: rare; one view, as before #131 |
| Shutdown now deletes a recording's render product while a stage is open | Accepted: the kept feed's shutdown does, measured quiet (#114's S4) |

## Plan review
