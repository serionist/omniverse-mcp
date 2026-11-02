---
title: Record through the kept capture feed, so a recording sets up no new RTX view
issue: "#141"
status: approved
approved_by: serionist
approved_at: 2026-11-02
---

# Record through the kept capture feed, so a recording sets up no new RTX view

Kit 110 (Isaac Sim 6.2) can hang for good during a new RTX view's first frames (#114, isaac-sim/IsaacSim#920). #131
kept one camera feed between `capture_viewport` and `inspect_prim` calls, so a capture rarely sets one up now, but
`start_recording` still makes a feed of its own for each recording and deletes it at the stop: one new view a
recording. Release 0.4.0's AI run hung so on phase 6's seventh `start_recording` call (#141).

The maintainer chose one kept feed for both (#141, 2026-11-02): a recording at the kept feed's size takes it, points
it at its own camera, and puts it back at the stop, where it waits 30 s for the next capture or recording, as a
capture's does. The MCP tools default captures and recordings alike to 640x480 (`tools/camera.py:142-143` and
`:335-336`, `tools/recording.py:21-22`), so a session that gives no sizes records and captures through one view.

## Goal

| Row | True when done | Shown by |
|---|---|---|
| G1 | `start_recording` renders through the kept feed when one is kept on the open stage at the recording's size: its camera set in place, no new view (#114's K15). Otherwise it makes a feed of its own, as today, and leaves the kept one on its clock. So no sequence of captures and recordings sets up more views than today's code: a recording that resized the kept feed would cost a view, and the next capture at the old size another (round 1's P1) | `test_camera_feed.py`, `test_recording_handler.py`; live `test_26_06` (new): views counted over a capture, a recording, a capture and a recording at one size, then a recording at another |
| G2 | `stop_recording` puts a healthy feed back as the kept one, on the 30 s idle clock, when none is kept meanwhile, the stage is the one it started on and the extension hasn't shut down; otherwise it releases it, in `release`'s order. Frames stopping early (a stage change, the camera gone), a start that fails, and the extension's shutdown tear the feed down at once, in the order that frees a capture's segmentation graphs | the same unit tests; live `test_06_06` (changed), `test_06_09` (changed), `test_17_05`, `test_17_07`, `test_17_08` (changed) |
| G3 | A recording's frame 0 through the kept feed shows the recording's camera, not the camera the last capture rendered: the start waits the frames a capture waits after it sets the camera | live `test_26_06`: frame 0 against a fresh feed's capture of that camera, by `test_26_04`'s checks of a camera switch (#114's K19) |
| G4 | Every feed is named `ovmcp_feed_<id>`, whichever call made it, since either may use it later | `test_camera_feed.py`; the live checks that look for a kept feed |
| G5 | `start_recording`'s answer and description, `stop_recording`'s description, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, the scene skill, the README and two scenario Verify lines say the render is shared and kept 30 s after a stop | review |

| In scope | Out of scope |
|---|---|
| The recording's feed: where it comes from, its settle, where it goes at the stop | A capture during a recording: it finds no kept feed and makes one, kept as usual; the recording's then goes at its stop. Rare, since agents call tools one at a time |
| Feed names | Kit's Save, `save_scene`, `flatten_usd` or `export_prim` during a recording: they write the recording's render product, as today, since the recording holds it; once it is kept after the stop, they leave it out as they do a capture's (#114) |
| The docs and the scenario lines that say a recording deletes its render product at the stop | #114's other new views: a new size, the first call after 30 s idle, Kit's own views |

## Design

### The feed a recording uses (extension, `handlers/camera_feed.py`)

Two functions beside `kept_feed` and `put_back`, for a user of the feed that holds it longer than one call:

- **`lend(camera_path, width, height)`,** async: takes `_viewport`, so it waits for a capture running now. A kept feed
  of another stage is discarded first, as `kept_feed` does. When the kept feed is `width` x `height`, it is taken off
  the slot (`_kept.let_go()`, which stops the idle timer and moves the generation on) and its camera set (`aim`, which
  then changes no size). Otherwise a new feed is made, and any kept feed stays kept, on its clock. A feed whose `aim`
  raises is torn down (`let_go_now`) and the error rises. After the extension's shutdown (`forget`) it raises. The
  lent feed is in no slot while the recording holds it, so the stage events, the idle timer and the saves'
  `without_kept_feed` never touch it, as today with a recording's feed.
- **`hand_back(feed, stage_id, healthy)`,** async: kept, on the idle timer, when `healthy`, no other feed is kept, the
  feed still renders (not dropped), the stage open now is `stage_id` and `OPENED`, and the extension hasn't shut down;
  `_observe_stage()` first, as `kept_feed` calls it. After shutdown, `let_go_now`, which awaits nothing. Otherwise
  `release(feed)`. It takes `_viewport` when the lock isn't held; when a capture holds it, it releases the feed
  instead of waiting, so `stop_recording` doesn't wait out a capture (one view more for the next call, in a case
  agents rarely make). A capture queued for the lock just as a holder lets it go is let in first, so the stop then
  waits for that one capture.
- **`let_go_now(feed)`:** `_tear_down_at_once`, public: segmentation off if on, the feed dropped, its graphs freed if
  it ever had any, its render product deleted now or from the next open stage. For what can't await: frames stopping
  early on an update, and shutdown.
- **`kept_feed`'s failed `aim`** tears the feed down with `let_go_now` too, where it used `discard`: the kept feed may
  hold a capture's segmentation graphs (round 1's improvement, taken).
- **`forget()`** also marks the module shut down (`_kept.closed`), so a stop whose frames were still being awaited
  when the extension shut down tears its feed down rather than keeping it on a timer that nothing would cancel, with
  its stage observers made again (round 1's P2).

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
  a new feed and a kept one: 20 frames, about 0.18 s at #114's K6 rate, more than a new feed needs and what a capture
  pays. A settle that runs out of time still starts, as today; a frame that never comes fails it. A start that fails
  after `lend` tears the feed down with `let_go_now`, as `discard` did.
- **Each frame:** unchanged, but a frame whose capture raised marks the session in doubt (`session.doubted`), as a
  capture's escaped error does its feed. A frame cancelled because frames stopped is not doubt (`CancelledError` isn't
  an `Exception`, which `_take_frame` catches).
- **Frames stop early** (stage closing or changed, camera gone): `let_go_now(feed)`, at once, as `discard` was.
- **Stop (`_end`):** after the frames in flight, `await hand_back(feed, session.stage_id, healthy=not
  session.doubted)`. Its failure is reported in the stop's note as a failed deletion is today. A forced start's `_end`
  hands back too, so the new recording takes the same feed when its size matches.
- **Shutdown:** `let_go_now(feed)`, then `forget()`, which forgets render products still waiting for a stage. Today's
  shutdown drops the feed and deletes nothing, its test saying that deleting prims while Kit shuts down risks a crash;
  the kept feed's shutdown (`forget`) has deleted its render product while a stage is open since #114, measured quiet
  (#114's S4), and a lent feed may be the kept one.
- **The answer:** unchanged keys; `render_product` names the lent feed's.

### The server (`src/omniverse_mcp/tools/recording.py`)

- `start_recording`'s line `Renders into <path>, deleted at stop` becomes `Renders into <path>, kept 30 s after the
  stop for the next capture or recording`.
- `start_recording`'s description: "through a render of its own" becomes "through the render `capture_viewport` and
  `inspect_prim` use, at its size"; "The extra render runs while the recording does" becomes "while the recording
  does, and up to 30 s after". `stop_recording`'s: "and delete the recording's render product" becomes "and hand its
  render back to the captures, kept 30 s". Descriptions aren't in the tool contract (`tests/fixtures/mcp-tools.json`
  holds none).

### Alternatives

- **A recording that resizes the kept feed** (round 1's draft): with captures and recordings at different sizes
  alternating within 30 s, each cycle sets up two views where today's code sets up one (P1).
- **A second feed kept for recordings** (#141's second option): a recording after captures still makes a view, and
  two feeds may render while idle, twice #114's cost.
- **A pool of two feeds** (the third): a capture during a recording finds the second; the most code, and up to twice
  the idle cost, for a case agents rarely make.
- **The capture during a recording renders through the recording's feed** when the camera and size match: it would
  share frames with the recording's delegates and turn segmentation on under it. Not worth the risk for a rare case.

## Compatibility

No tool, schema, route, setting or output path changes; no one-way door. Users notice:

- after a recording, its render stays up to 30 s when no other is kept (the GPU cost #114 states for a kept feed, by
  size: a 4096x4096 recording's feed costs about 5.5 GB of video memory and half of Kit's updates while kept, where
  today it goes at the stop);
- the render product is named `ovmcp_feed_<id>`, not `ovmcp_recording_<id>` or `ovmcp_capture_<id>`.

An older extension with this server: the start line says the render is kept when that extension deletes it at the
stop; this extension with an older server: the line says deleted at stop. Both are wrong only in that line (0.x).

## Steps

1. **`camera_feed.py`:** `lend`, `hand_back`, `let_go_now`, `forget`'s mark, the prefix. `tests/test_camera_feed.py`
   with its fake texture: `lend` with a feed kept at the size takes it off the slot, its camera set, the timer
   stopped, and a stale idle release does nothing; at another size, a new feed named `ovmcp_feed_`, and the kept one
   still kept and timed; with none, a new feed, not kept; a kept feed of another stage is discarded first; an `aim`
   that raises tears the feed down; after `forget`, it raises. `hand_back` healthy into an empty slot keeps it and
   starts the timer; with another feed kept, the stage changed or closing, the feed dropped, or in doubt, releases it
   in `release`'s order; with `_viewport` held, releases without waiting; after `forget`, tears down at once and
   observes no stage event. `let_go_now` of a segmented feed frees its graphs and deletes its render product, and so
   does `kept_feed` when a segmented kept feed's `aim` raises.
2. **`recording.py`:** the handler through `lend`, `hand_back` and `let_go_now`. `tests/test_recording_handler.py`'s
   fake `camera_feed` module offers them: the start lends at the camera and size and waits the first frame, then 20
   plus the settle frames; stop hands back healthy; a frame that raised hands back in doubt; frames stopping early
   let go at once and hand nothing back; a failed start lets go; a forced start hands the old feed back before it
   lends. The other tests keep what they check, with `discard` read as `let_go_now`, but two that check the old
   design: `test_shutdown_ends_the_frames_and_the_feed_but_deletes_nothing` becomes shutdown letting the feed go,
   then forgetting (why above); the `(0, ["subscribed"])` case of
   `test_the_start_waits_the_frames_path_tracing_still_owes_before_it_takes_any` waits 20 frames, where it waited none.
3. **The server:** the start line and the descriptions; `tests/test_tools.py`'s start-line test.
4. **Docs and CHANGELOG** (Docs, below).
5. **Live:** the new and changed tests on a Z-up and a Y-up stage; both suites whole; AI phases 6, 7, 16, 17 and 26.
6. **finish-work:** `uv run tools/gate.py full`, `review-code` until clean, the PR, with the live runs it names.

## Tests

- **Unit:** steps 1 to 3; the tool contract unchanged.
- **Live, new:** `test_26_06` in `test_scenarios.py`, any kept feed released first and after:
  - at one size: a capture at 320x240 of the viewport's camera; a recording at 320x240 of `/World/KeptCam`, a few
    frames, stopped; a capture; another recording; stopped. Kit's log gains one `createViewport` over the four, each
    render product named is the same `ovmcp_feed_`, and one feed is kept after the stop;
  - at another size: a recording at 160x120, stopped, then a capture at 320x240: one `createViewport` more, the
    recording's own, and the kept 320x240 feed is the one kept after;
  - the first recording's frame 0 against a fresh feed's capture of `/World/KeptCam` at 320x240 (after
    `release_kept`), by `test_26_04`'s checks of a camera switch: mean and 99th percentile within a kept feed's
    bounds, and at most a third of the switch itself.
- **Live, changed:**
  - `test_06_06`: while recording, the render product is on the stage; after the stop it is the kept feed; after
    `release_kept` it is gone from every layer and from the render settings;
  - `test_06_09`: a segmented `capture_viewport` at the recording's size first, so the recording lends a feed with
    segmentation graphs; after the camera goes and frames stop, the render product is gone and Kit's log holds no
    `Py_Graph` line since the capture, as `test_17_06` checks (round 1's P5);
  - `test_17_08`: a capture after the recording starts too, so a kept feed and a lent one are both under the open,
    and its comment says so; both render products go;
  - `test_26_03`'s view-assignment pattern, `_kept_feeds()`, `test_26_05`'s and `test_integration.py`'s
    `ovmcp_capture_` checks: `ovmcp_feed_`.
- **Live, existing:** both suites whole, on Z-up and Y-up; `test_17_05` and `test_17_07` unchanged.
- **AI scenarios:** 6.4 to 6.9's line "after `stop_recording()` it is gone" becomes "after `stop_recording()` it is the
  kept feed, gone 30 s later with no capture or recording"; 16.8's `ovmcp_capture_<id>` becomes `ovmcp_feed_<id>`,
  and "a recording's render product" leaves its failing cases, since a recording stopped before may have left the
  kept one.
- **Not shown:** that the hang never comes on a recording: a recording at another size than the kept feed's, the
  first call after 30 s idle, and a capture during a recording still set up views; Linux; Isaac Sim 5.x.

## Docs

- `docs/TOOLS.md`: `start_recording` (renders through the shared render at its size, kept 30 s after the stop; the
  answer's `render_product`; line 967, the first frame waits 20 frames of the render plus Path Tracing's samples;
  line 978, the extra render runs while the recording does and up to 30 s after); `stop_recording` (hands the render
  back); the kept-render note under `capture_viewport` (shared with recordings at its size).
- `docs/ARCHITECTURE.md`: Recording System's start and stop, the kept feed section (lent to a recording), the
  handlers row.
- `plugin/skills/scene/SKILL.md`'s cost row: captures and recordings slow Kit down for 30 s after.
- `README.md`'s hang entry: the bridge keeps one render for captures and recordings.
- `AGENTS.md`'s #57/#51 Traps row: kept between calls and recordings (#114, #141), within its line.
- `CHANGELOG.md` under Unreleased: Fixed, a recording at the kept render's size sets up no new view (#141); Changed,
  the render kept 30 s after a recording and the render products' new name.
- `test_project/scenarios.md`: the two Verify lines (Tests).

## Risks

| Risk | Status |
|---|---|
| Frame 0 shows the previous camera | Resolved by the 20-frame settle; `test_26_06` checks it |
| A lent feed's segmentation graphs leak when a recording tears it down | Resolved: every recording path tears down through `release` or `_tear_down_at_once`, never `discard`; unit tests, and `test_06_09` reads Kit's log |
| More views than today when sizes alternate | Resolved: a recording lends only at the kept feed's size (P1); `test_26_06` counts both cases |
| A stop during shutdown keeps a feed nothing cancels | Resolved: `forget`'s mark (P2) |
| A large recording's feed costs the GPU 30 s after the stop | Accepted, as #114's Q2 accepted it for captures; TOOLS.md states it |
| `stop_recording` waits behind a capture for the lock | Resolved but for a capture queued at that moment, which it waits for |
| A capture during a recording sets up a view, and the recording's feed then goes | Accepted: rare; one view, as before #131 |
| Shutdown now deletes a recording's render product while a stage is open | Accepted: the kept feed's shutdown does, measured quiet (#114's S4) |

## Plan review

### Round 1

- **How:** a fresh general-purpose agent (Claude Opus 5.5), with every lens; a fresh refuter for its major. 2026-11-02,
  on `db5c00a`.
- **Verdict:** the reviewer's needs-fixes (P1 major, P2 to P5 minor). P1's refuter confirmed it in part and rated it
  minor: the scenario's sizes can't come through the MCP tools, which default both to 640x480, but explicit sizes that
  alternate within 30 s double the views. So no second round.
- **Now:** P1 to P5 fixed in this commit.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor (major as reported) | A recording resized the kept feed, so captures and recordings at different explicit sizes, alternating within 30 s, set up two views a cycle where today's code sets up one: the recording's resize, then the next capture's back | fixed: a recording lends only at the kept feed's size, else makes its own and leaves the kept one on its clock; `hand_back` keeps only into an empty slot. No sequence sets up more views than today's code (the refuter found none); `test_26_06` counts both cases |
| P2 | minor | `_end` awaits the frames in flight after it clears the session; a shutdown then finds none, `forget` clears the stage observers, and `hand_back` would keep the feed on a 30 s timer, observing the stage again, owned by an unloaded module | fixed: `forget` marks the module shut down; `hand_back` then tears down at once, `lend` raises |
| P3 | minor | Text the change makes false was not named: TOOLS.md:967 (what frame 0 waits for), TOOLS.md:978 (the render runs while the recording does), the server's start description (the extra render runs while the recording does) | fixed: Docs and the server's descriptions name them |
| P4 | minor | Step 2 said the existing tests keep what they check, but two check the old design: shutdown deletes nothing, and no settle outside Path Tracing | fixed: step 2 names both and why they change |
| P5 | minor | No live test showed the at-once teardown of a lent, segmented feed keeps Kit's log quiet: `test_06_09` lends an unsegmented feed and reads no log | fixed: `test_06_09` captures with segmentation first and reads `Py_Graph` lines, as `test_17_06` does |

**Refuted:**
- P1's scenario of a 1280x720 capture: the capture tools default to 640x480 and the client always sends a size
  (`client.py:446`, `:479`), so the bridge's viewport-size fallback is reached only by a raw HTTP caller.
- `lend` deadlocks on `_viewport`: `handle_recording_start` doesn't hold it, and no holder calls it.
- Stage events drop the lent feed while it records: `_on_closing` and `_on_saving` act through `_kept.let_go()` only.
- A stale idle release takes the lent feed: `let_go` moves the generation on, which `_release_idle` checks.
- The settle claim for frame 0: the 20 frames come after the aim, and frame 0's delegate gets the next frame.
- `_tear_down_at_once` of an unsegmented feed isn't `discard`: `_stop` skips both segmentation steps, then calls
  `_leftovers.add`, `discard`'s body.
- A cancelled frame marks doubt: `CancelledError` isn't an `Exception`.
- The descriptions change the tool contract: `tests/fixtures/mcp-tools.json` holds no description.
- The render product's name is a one-way door: not in AGENTS.md's list; the `render_product` key is unchanged.
- `hand_back` keeps a feed onto a new stage: it requires the start's stage, `OPENED`.

**Improvements:**

| Improvement | Answer |
|---|---|
| `test_17_08`: a capture after the recording starts, so a kept feed is still under the open | taken |
| `test_26_06`'s frame 0 check: a camera switch has no ghost; name the switch's checks | taken |
| The settle's cost: 20 frames at K6's 113 a second is about 0.18 s, not 0.13 | taken |
| "Takes `_viewport` when free": a capture queued for the lock goes first | taken: the wording and the Risks row say so |
| `kept_feed`'s own failed `aim` discards a feed that may hold segmentation graphs; `let_go_now` there too | taken (the maintainer, 2026-11-02): Design and step 1 |
