---
title: Add capture_sweep, which captures a list of shots with their own cameras, selections and times as a job, to the tool contract
issue: "#157"
status: approved
approved_by: serionist (delegated to the author, 2026-11-02)
approved_at: 2026-11-02
---

# Add capture_sweep, which captures a list of shots with their own cameras, selections and times as a job, to the tool contract

## Goal

One call captures a list of shots and says where they are, with nothing left changed in the stage. Today
`capture_viewport` and `inspect_prim` take one camera and one state per call, so a scene's check of about 400
captures costs 400 agent turns and fills the agent's context with answers it doesn't need.

The case (#157 and its author, 2026-11-02): a 300 x 300 m construction site in Isaac Sim 6.2 with about 50 viewpoints
where an inspection robot stops and 128 switches (USD variant sets), each stepped through its states and captured from
its viewpoint, repeated after every change, and compared between two scenes built from one spec. A shot is the robot's
front camera: 1280 x 720, focal length 7.337 mm, apertures 20.955 x 11.787 mm, about 0.65 m above the floor, other
sizes now and then. Light and time of day are variant switches; nothing is ever hidden to make a state. People walk
(Replicator agents).

When this is done:

- `capture_sweep(shots=[...] or shots_file="...", width=1280, height=720, name="")` starts a sweep as a job on #158's
  board (kind `sweep`) and answers its id at once; `get_job` gives `shot 37 of 400` as it goes and, once it ends, one
  line naming the folder, the manifest and the counts;
- each shot is a pose (a position with a yaw and pitch, or a target, or a `camera_path`), optional intrinsics (focal
  length, apertures that fit the image's shape), optional selections `{prim: {set: option}}`, and an optional
  timeline time;
- Kit writes the PNGs and a `manifest.json` (per shot: its name, pose, lens, selections, time, file, the frame it was
  taken on and whether it came out black; with the sweep's size, renderer and Kit app) to `sweeps/<name>/` in the
  server's output folder, as it writes a recording's frames to `recordings/`; a remote Kit writes them under the same
  path on its own machine (fit I1);
- a sweep's own `manifest.json` can be the next sweep's `shots_file`, so a rerun or the second scene takes exactly the
  same shots without the shots passing through the agent's context (fit I3);
- every layer is as it was afterwards, the session layer included, and so is the timeline, even after a cancel;
- the same shots on an unchanged stage give the same pictures within a stated pixel tolerance, for content that is
  still or time-sampled (fit I4).

In scope: the tool, its route, a Kit-free core for shots and the manifest, the job's coroutine, docs, tests.
Out of scope: a contact sheet (the manifest gives what one needs; a later issue); boxes or segmentation per shot;
comparing two sweeps; shots of several sizes in one sweep (one size, one feed); making Replicator agents repeatable.

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | "The same pictures" twice means within a pixel tolerance, not bit for bit | yes (maintainer, 2026-11-02) |
| Q2 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02) |

### What it builds on

- **#158's job board** (`docs/plans/2026-11-02-script-jobs.md`): a `sweep` kind beside `script`, started with
  `watch_stage` so a new stage cancels it, its `finally` holding the slot until the stage is put back, its result a
  dict (the manifest's summary) that `get_job` formats by kind, `/jobs/get` and `/jobs/cancel` as they are. A sweep
  belongs there, where a recording doesn't: it ends by itself, reports progress, can be cancelled and returns a result.
- **#155's switch** (`docs/plans/2026-11-02-variant-layer.md`): `switch(stage, {prim: {set: name}}, "session")`
  returns a `Snapshot` of what it wrote over.
- **A recording's way of rendering many frames** (`handlers/recording.py`, `camera_feed.py`) (fit I2): the feed is
  lent (`camera_feed.lend`) at the start and handed back (`hand_back(feed, stage_id, healthy)`) in the `finally`, so a
  save between shots doesn't release it and no new RTX view is set up per shot (#114); the viewport lock is held for
  each shot alone (round 1, I9; round 2, P14), not for the whole sweep; each shot goes through
  `_capture_frame`, 20 of the feed's frames after its camera is set (#57), with `is_black`; a shot's `camera_path` is
  checked with `camera_error`; at shutdown the sweep lets the feed go with `let_go_now`, as `recording.shut_down`
  does.
- **`core/xform.aim`** for a pose given by a target, the stage's up axis respected.

### The extension

- **`ovmcp/core/sweep.py`** (Kit-free): `Shot` and `read_shots(body)` checking every shot before anything changes (a
  pose given one way, intrinsics above zero, apertures whose ratio fits width over height within 1%, refused with the
  aperture that would fit (fit I6), a time a number, selections as names), up to 2,000 shots, a manifest's shots read
  back as shots, where a `camera_path` shot is read back as the pose, lens and clipping range it rendered with, which
  the manifest records, so a twin on another scene takes the same view without the other scene having that camera
  (round 2, P15); `DEFAULT_LENS(width, height)`, the lens a shot without intrinsics gets on every shot, never the
  previous shot's: focal length 18.147 mm (Kit's own camera's) with apertures fitted to the image, horizontal 20.955
  mm, so a shot's picture never depends on its place in the list (round 1, P4); `pose(shot, up_axis)` giving the
  camera's eye and target from a yaw and pitch about the stage's up axis; `changes(start, written, shot)`, the
  selections to write before a shot, against `written`, the selections last written (never the last shot asked for,
  so after a refused shot nothing it asked for counts as shown; round 2, P13), where a set a shot doesn't name goes
  back to its starting session value (absent, blocked, or a name an earlier call wrote), not to a clear, so a
  selection made before the sweep holds for every shot that doesn't name its set (round 1, P1); a run of shots in one
  state switches nothing; `manifest(...)`;
  `file_name(index, shot)`; `folder_name(name)` refusing a name that isn't one plain folder name (no `..`, no
  separator).
- **`handlers/sweep.py`:** `handle_sweep_start(body)` (`/jobs/sweep`) takes the output root and the name apart, as a
  recording lets Kit name its folder, and checks the name before joining them (round 1, P9); it refuses a bad shot, a
  bad name, a folder that already holds a manifest (a sweep never writes over another's; the answer names the folder),
  a selection `variant_refusal` (#155) refuses wherever the set exists now (round 1, P8), or a busy board, then starts
  the job and answers with the folder's path, so the agent knows it even if the sweep ends without a result (round 1,
  P6). Its coroutine:
  - reads the timeline's state and time and each named (prim, set)'s starting session value, and makes a camera of its
    own in the session layer (`/OmniverseKit_Sweep`, as Kit keeps its cameras there) with a clipping range of 0.01 m
    to 1e7 m in stage units, Isaac Sim's own camera default (`apps/isaacsim.exp.base.kit:253`), where USD's `Define`
    gives 1 m to 1e6 and would cut the floor in front of a camera 0.65 m above it (round 1, P2); its transform and
    lens written in the session layer too, `aim(..., layer=session)`, since `aim`'s default layer would put the new
    camera's ops in the root layer (round 1, P3), so no file changes;
  - for each shot, holding the viewport lock (`_viewport`) for the shot alone, so a capture or `inspect_prim` called
    meanwhile runs between shots, never inside one (round 1, I9): writes the selections that change through `switch`,
    keeping every snapshot it returns, with #155's refresh when it is needed, and a revert to a blocked starting value
    through #155's `usd.select(spec, set, "")`, which writes a block where `switch` would clear (round 2, P11); after a
    shot that switched, waits, bounded at 20 s, until the stage has finished loading (`get_stage_loading_status()`),
    since a variant that brings payloads, materials or textures captured mid-load differs from its twin (fit I5); a
    shot past its bound is recorded as such and taken anyway, and the lock is never held past 30 s, so a capture
    queued behind a shot keeps most of its 80 s (round 2, P14); with a time, sets the timeline to it,
    pausing a playing timeline and leaving a stopped one stopped (round 1, I11); without one, puts the timeline back to
    its state at the start; for a `camera_path` shot, checks the camera with `camera_error` after the shot's switch
    (which may have removed it, and a missing camera renders white), renders through it as it is, writing nothing to
    it, and records in the manifest the pose and lens it rendered with, so a rerun on another scene takes the same
    view (round 1, P5); otherwise aims its own camera and sets its lens; takes the frame through the lent feed; writes
    the PNG into the folder; a shot that fails (a refused switch, a camera gone, a capture error) is recorded in the
    manifest with its reason and the sweep goes on (round 1, P8);
  - progress: the job's status message says `shot 37 of 400`, and a line is printed every 25 shots and at each failed
    one, so a `get_job` read carries a few lines, not hundreds (round 1, I8); the manifest is rewritten every 25 shots,
    so a hang (#162) still leaves an index of the files taken (round 1, I7);
  - in a `finally`, each step on its own so one that raises can't stop the rest, as recording's `_end` does (round 2,
    P12): restores every snapshot it kept, last first, so every selection any shot wrote is back exactly, except when
    the job was cancelled because the stage changed (#158's reason), whose layers are gone with their stage, and then
    also leaves the new stage's timeline and its cameras alone (round 1, P7); otherwise puts the timeline's state and
    time back and deletes its camera; hands the feed back; writes the manifest of the shots done, file names relative
    to the folder, with the camera's clipping range; and prints the summary line
    (`37 of 400 shots in .../sweeps/site_a/ (manifest.json); cancelled`), which #158's lines carry in every end state
    (round 1, P6).
- **The manifest** also records the sweep's lighting mode and render settings (the renderer, path tracing's samples
  per pixel when it is on), so a twin taken under other settings shows why it differs (round 1, I10).

### The server

- `capture_sweep(shots: list[Shot] = [], shots_file: str = "", width=1280, height=720, name="")`, `EDITS`, since it
  changes the stage while it runs and puts it back: one of `shots` and `shots_file`; the server reads `shots_file`
  (a list of shots, or a sweep's `manifest.json`) and sends the shots with `<output>/sweeps` and the name apart,
  `name` defaulting to a time stamp, as `start_recording` sends `<output>/recordings`. Its answer names the job and the
  folder.
- `get_job` for a sweep answers `400 shots in mcp_output/sweeps/site_a/ (manifest.json); 2 black: shots 12, 13; 1
  failed: shot 300`, so the agent's context gets one line, not 400; a cancelled or failed sweep's summary is its last
  line.
- The description: one call for many shots, the job and how to read it, `shots_file` and a manifest as one, that the
  stage is put back, the lens and time per shot, that a fixed time repeats time-sampled content but not Replicator
  agents, the size limit, and that a cancel keeps what was taken.

### Replicator agents (fit I4)

A shot's `time` fixes time-sampled content: USD time samples, baked and skeletal animation. Replicator's walking
agents don't follow the timeline's time: each moves on its update by `delta_time` from a seeded routine
(`isaacsim.replicator.agent.core`'s `agent.py:68`, `runtime_state.py:163-173`), so seeking a paused timeline leaves
them where they stand. The repeatable way is the timeline stopped, which step 5 checks with one agent, or their paths
baked to time samples; the description and the `scene` skill say so.

### Alternatives

- **The server loops over shots, one bridge call each:** one MCP call for minutes with no progress, and a lost
  connection loses the sweep; the issue asks for a job.
- **Kit's temp folder and a route the server pulls files through:** 400 PNGs a check, sent base64 on Kit's main thread
  and copied again; a recording's way, Kit writing into the output folder's path, needs neither (fit I1).
- **Replicator's `rep.orchestrator.step_async` with a writer:** it drives and pauses the timeline itself and writes
  its own layout; its lesson, waiting for a big scene change to load before capturing, is taken (fit I5).
- **Images in the job's result:** 400 PNGs at 1280 x 720 are hundreds of megabytes of JSON.
- **Hide and show prims for a state:** no; the case's rule is that nothing is hidden, and selections cover lights and
  time of day.

## Compatibility

**One-way doors: the tool contract, the wire protocol's paths, the output folder's layout.** A new tool, one new
route (`/jobs/sweep`), and a new folder `sweeps/` in the output folder: additive. The maintainer's agreement is posted
in #157 before the PR. It needs #155's and #158's extension: an older one answers the unknown route with the install
advice.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/sweep.py`, tests first | `tests/test_sweep.py`: shots read and refused, a manifest read back as shots, apertures against the image's shape, the default lens, poses on both axes, `changes` merging reverts with applies and a shot after a switching shot seeing the starting selection (absent, blocked, named), the manifest, file and folder names (`..` refused) |
| 2 | `handlers/sweep.py`, `/jobs/sweep` | handler tests with the Kit fakes: every layer's export and the timeline as before after a sweep whose shots switch different prims, after a cancel mid-sweep, after a stage-change cancel (the new stage left alone) and after an error; the camera's clipping range and its ops in the session layer only; a shot without a time after one with a time, and a stopped timeline left stopped; a `camera_path` shot's camera unwritten and checked after its switch; a failed shot recorded and the sweep going on; the manifest rewritten every 25 shots; the start answer and the last line naming the folder; a folder with a manifest refused; the name refused before it is joined; the feed lent and handed back; the viewport lock taken per shot |
| 3 | The client, the tool, `shots_file`, `get_job`'s answer for a sweep; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs, the `scene` skill | review |
| 5 | Live: a referenced file with a variant set; a 6-shot sweep over two states and two poses at 1280 x 720 with the case's lens; the root and session layers' exports as before, once the kept feed's render product is released (`release_kept`, since Kit writes a feed's render product into both layers), and the timeline as before; the manifest matching the files; the same sweep again from the first's manifest, each picture within the tolerance of its twin; whether the loading wait is needed after a switch, measured; one Replicator agent, a stopped timeline repeating and a seek not; a 50-shot sweep cancelled mid-way, the stage put back and the manifest saying what it took | `tests/test_integration.py` on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live: step 5, on a Z-up and a Y-up stage; the tolerance is a mean absolute difference under 2 of 255 per channel
  between twins, measured and recorded.
- What neither shows: a 400-shot sweep on the case's site (a by-hand run of 200 shots stands in, timed); Kit on
  another machine than the server (Kit writes under the same path there, as for recordings); how RTX renders a
  `camera_path` camera whose own apertures don't fit the image's shape (rendered as it is, its apertures in the
  manifest).

## Docs

`docs/TOOLS.md` (the tool, `shots_file`, the manifest, `get_job` for a sweep, and line 7's output folder layout,
which gains `sweeps/`), `docs/ARCHITECTURE.md` (the route, the core and handler lists, the lend section, which
gains a second borrower, and line 74's list of what Kit writes itself, which gains sweeps; round 2, P10), `AGENTS.md`'s `ovmcp/core` row (`sweep.py`), `docs/SETUP.md` (a remote Kit writes sweeps on
its own machine, as recordings), `README.md`'s list and count, the `scene` skill (a sweep for a scene's check,
Replicator agents), `CHANGELOG.md` (Added) (round 1, P10).

## Risks

- **A sweep's length:** each shot waits its 20 frames, a switch with Fabric's refresh adds its own, and a switch that
  loads files waits for them; 400 shots take minutes. Accepted: a job, with progress; #155's measurement decides the
  refresh's cost.
- **Kit hangs mid-sweep** (#162's Fabric population hang, after many stage changes): the sweep can't prevent it; a
  restart loses the session layer, so the files are as they were anyway.
- **The lent feed's memory at a large size:** one feed at the sweep's size, as a recording's.

## Build notes

Where the build departed from the plan, and what only a live run shows. The tool contract, the route and the scope
are as planned.

- **`shots` defaults to `None`,** not `[]`: a mutable default is ruff's B006, and the repo's other list parameters are
  `None`. A `Shot` model with `extra="forbid"` refuses a misspelled field before any request; Kit checks the rest.
- **`clipping_range` is a shot's field,** given or read back: the manifest records the range each shot rendered with
  (P15), so a shot from a list and one from a manifest take one form. A shot without one gets Isaac Sim's range in
  the stage's units, which its entry then records.
- **A `camera_path` shot's lens in the manifest** is its focal length, its horizontal aperture and the vertical one
  Kit renders with under the viewport's default aperture conform (match horizontally,
  `omni.kit.widget.viewport`'s `api.py`): horizontal times height over width, so it reads back as a lens that fits.
  Its pose is its world position with a yaw and pitch: a roll isn't kept.
- **A dead feed ends the sweep:** a shot whose capture failed while the feed rendered no frame fails the job, naming
  the shot, where each later shot would wait its 30 s holding the viewport lock. A capture that failed while frames
  still came is recorded, and the sweep goes on, as planned.
- **The end's order:** the feed pointed at the viewport's camera first, so a feed kept after the sweep doesn't
  render its deleted camera and lifts #177's exposure shield from the camera it rendered last; the selections, in one
  change block (code review, F2), the timeline and the camera; then the manifest and the summary line; then the feed
  handed back, last, so a second `cancel_job` during `hand_back`'s await can't cost the manifest (F5's test).
- **The session layer's empty overs:** a selection's snapshot and #177's shield each take back only what they found
  missing, and each can leave an empty over the other made: a scene camera rendered before a shot switches its parent
  left `/World/A` (rebase onto #177). The end removes each empty prim spec the session layer didn't hold at the start
  (`sweep.prune`). A session spec at `/OmniverseKit_Sweep` before the sweep is copied and put back after its camera
  is deleted.
- **Nested sets (code review, F1):** a set the shot doesn't name goes back to its starting value unchecked, since it
  held before the sweep; the shot's own selections are written outermost first, each level checked once the one above
  is written, and a refusal takes back every write of the shot. The plan's switch checked every change against the
  stage before any write, so a door's colour inside an area's open variant failed by the shot's place in the list.
- **A stage that went (F4):** a shot checks the stage is still the sweep's before it writes, and again after its
  switch's waits, and ends the sweep as the watch would, through `stop_for_stage`, a helper of `handlers/jobs.py`: the
  watch cancels only on the next update, and a stage opened at a shot's start got the shot's writes.
- **Refused at the start, beside the plan's:** a stage with a defined prim at `/OmniverseKit_Sweep`, an empty over
  there blocking nothing (L3, the live run's root-layer leftover before #177); a Kit app without
  `omni.kit.hydra_texture` or `omni.kit.widget.viewport.capture`, as `start_recording` refuses it; and a manifest
  given as `shots_file` that was taken at another size than the one asked, naming its own (G1). The manifest is
  written as the job starts (`working`). A feed whose first frame never came is released at the end, not kept (F3).
- **The default lens** is Kit's own camera's 18.147562 mm (`omni.kit.widget.viewport`'s typed default), not 18.147.
- **The timeline:** a seek commits at once (`Timeline.commit`, Kit 105 and up, as Isaac Sim's own utilities use it);
  a shot without a time commits only when it changed something, since a commit runs the timeline's callbacks. Whether
  `set_current_time` keeps a stopped timeline stopped isn't documented: the end stops it again if not, then puts its
  time back. Step 5 shows which.
- **The manifest's `frame`** is the timeline's time times the stage's time codes per second, the USD time code shown;
  `timeline_time` is beside it. A loading wait is `get_stage_loading_status()[2] > 0`, as Isaac Sim's own tests read
  it, and each switching shot records its `loading_seconds`, which step 5 prints.
- **The server:** the tool is a module of its own, `tools/sweep.py`, its `Shot` fields and `MAX_SHOTS` pinned to
  the core's by a test; `get_job` gives Kit's own summary line with its folder named through `Helpers.rel`. A
  `shots_file` is read as `utf-8-sig`. While it runs the job's message is `shot 37 of 400`, cleared once it
  completes.
- **A `camera_path` shot whose camera a switch removed** reads `typeless prim, not a Camera` rather than `No prim`
  while the feed's exposure shield holds an empty over there (#177), until the feed renders through another camera.
- **Step 5** is `TestCaptureSweep` (a Y-up and a Z-up stage of its own, six shots, the layers, the timeline, the
  manifest, twins from the manifest within 2 of 255, open and closed apart by more than 0.2% of the pixels changed by
  16 of 255, a 50-shot cancel) and `TestCaptureSweepAgents` (one worker in Isaac Sim's simple warehouse, from
  `isaacsim.replicator.agent.core`'s sample configs; skipped without the extension or its `api` module, as on Isaac
  Sim 5.1, and the extension turned off again when the test turned it on) in `tests/test_integration.py`. Its first
  run (Isaac Sim 6.2, Z-up) found RTX's exposure schemas in the root layer, fixed by #177. Kit 107 isn't covered.

## Plan review

### Fit

The plan at `7138583`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, with this repo's `fit-plan`.
The change's own question: recordings already render many frames to a folder the server names; does the plan reuse
that path, and is the job board the right home, given a recording isn't a job? Answers by the author, 2026-11-02, on
the maintainer's delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | Kit writes the PNGs and the manifest into `<output>/sweeps/<name>`, as `start_recording` sends `<output>/recordings`; drop `/jobs/file`, the pull, Kit's temp folder and the manifest's rewrite | taken |
| I2 | Hold the feed as a recording does: `lend` at the start, `hand_back` in the `finally`, `_capture_frame` per shot with `is_black`, `camera_error` for a `camera_path`, `let_go_now` at shutdown | taken |
| I3 | A `shots_file` the server reads, a sweep's own manifest accepted as one, so 400 shots needn't pass through the agent's context and a rerun takes exactly the same shots | taken |
| I4 | A shot's `time` fixes time-sampled content, not Replicator agents, which move by `delta_time` from seeded routines; say so and check it live with one agent | taken |
| I5 | After a switch, wait for the stage to finish loading, Replicator's lesson for big scene changes; name Replicator's orchestrator as an alternative | taken |
| I6 | Refuse apertures whose ratio doesn't fit the image's shape, naming the one that fits | taken |

Noticed on the way, for Round 1: restoring the first snapshot left later shots' selections behind (The extension;
now every snapshot, last first); Kit writes the feed's render product into the root and session layers, so step 5's
comparison needs the feed released first (Steps; now said); `name` was joined into a path unchecked and a reused name
undefined (The server; now a plain name, and a folder with a manifest refused); the temp folder and the pull's time
past 120 s (gone with I1); the timeline playing at the start, and a shot without a time after one with a time (The
extension; now put back to its starting state).

### Round 1

**How:** one fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, read only, every lens, at `cfe2248`, with
checks on usd-core 26.11 and the Isaac Sim 6.2 and 5.1 installs. **Verdict:** needs-fixes: two majors, so a second
round. **Now:** every finding fixed in the plan, I7 to I11 taken.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | `changes` undid a shot's selection by clearing it, so a selection the session layer held before the sweep (an earlier `set_variant_selection`, session by default) was lost for every later shot, which showed a state the stage never had (measured: start `night`, shot 1 `dusk`, shot 2 `day`) | fixed: each named (prim, set)'s starting session value read first; `changes` reverts to it; tested for absent, blocked and named |
| P2 | major | The sweep's camera kept USD's default clipping range, 1 m near, cutting the floor in front of a camera 0.65 m above it on a metres stage; twins cut alike, so step 5 would pass | fixed: 0.01 m to 1e7 m in stage units, Isaac Sim's camera default; in the manifest; tested |
| P3 | minor | `aim`'s default layer wrote the new session camera's ops into the root layer (measured) | fixed: `aim(..., layer=session)`; tested |
| P4 | minor | A shot without intrinsics got `Define`'s 4:3 lens or the previous shot's | fixed: a default lens fitted to the image on every such shot |
| P5 | minor | A `camera_path` shot: where its lens goes, what the manifest records, when it is checked | fixed: rendered as it is, unwritten, its pose and lens recorded, checked after its switch |
| P6 | minor | A cancelled or failed sweep has no result, so `get_job` couldn't name the folder | fixed: the start answer names it; the last line is the summary in every end state |
| P7 | minor | After a stage-change cancel the `finally` restored the old timeline onto the new stage | fixed: left alone on that reason |
| P8 | minor | A misspelled option at shot 300 failed minutes in, its outcome unsaid | fixed: `variant_refusal` at the start where the set exists; a failed shot recorded and the sweep going on |
| P9 | minor | `folder_name` ran on a joined path, where `../` passes `basename` | fixed: the root and the name sent apart, the name checked before joining |
| P10 | minor | `AGENTS.md`'s core row, `ARCHITECTURE.md`'s lists and lend section, `TOOLS.md`'s output layout missing from Docs | fixed: Docs names them |

**Refuted:**
- **A save during a sweep writes the lent feed's render product into the file:** accepted for recordings, as Kit does
  it for the viewport.
- **A capture or `inspect_prim` during a sweep changes its shots:** #158's Risks accepts it; I9 now keeps them between
  shots.
- **`get_stage_loading_status` missing on Kit 107:** present in 5.1's and 6.2's extensions.
- **A straight-down pitch breaks `aim`:** `look_at` handles it.
- **The bridge's security:** the route joins the token-checked table; naming a folder grants no more than `/execute`.
- **The Replicator citations, and the Fit's noticed items:** as the plan says, P7 and P9 aside.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I7 | Rewrite the manifest every 25 shots, so a hang leaves an index | taken |
| I8 | Progress in the status message and a line every 25 shots, not a line per shot | taken |
| I9 | Take the viewport lock for each shot, so a capture runs between shots, never inside one | taken |
| I10 | Record the lighting mode and render settings in the manifest | taken |
| I11 | On a stopped timeline, set a timed shot's time without pausing | taken |

**Not covered:** everything that needs a live Kit (the near-plane cut, a stopped-to-paused move's effect on PhysX or
agents); on Kit 107, only that the APIs exist.

### Round 2

**How:** one fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, read only, on `cfe2248..c92ac8a` and the
round 1 findings, running #155's `variants.py` from its branch in memory on usd-core 26.11. **Verdict:** approved: P1
to P10 fixed (P1, P7 and P10 with the remainders below), five new minors, all fixed. **Now:** the plan approved on the
maintainer's delegation.

| # | Sev | Finding | Status |
|---|---|---|---|
| P11 | minor | A blocked starting value can't be written back through `switch`, which treats `""` as a clear (measured: start blocked, shot 2 showed the file's `day`); rare, since a session block comes only from a script or Isaac Sim's assembler | fixed: a revert to a block goes through #155's block helper |
| P12 | minor | After a stage-change cancel, the `finally` restored snapshots whose layers had gone with their stage; `restore()` raises, and the rest of the `finally` (handing the feed back, the manifest, the summary) never ran | fixed: no restore on that reason, and each step of the `finally` on its own, as recording's `_end` does |
| P13 | minor | `changes` against the last shot asked for: after a refused shot, a next shot sharing a selection with it skipped writing it and captured the older state under the new label | fixed: against the selections last written |
| P14 | minor | One line still said the lock is taken only to start; and the loading wait had no number, so a capture queued behind a shot could pass the server's 120 s | fixed: the lock per shot throughout; the wait bounded at 20 s and the lock never held past 30 s |
| P15 | minor | A `camera_path` shot read back from a manifest was undefined: the path or the pose rendered | fixed: the pose, lens and clipping range it rendered with, which the manifest records |

Also from round 1's remainders: the clipping range now in the manifest (P2), and `ARCHITECTURE.md`'s list of what Kit
writes itself in Docs (P10).

**Refuted:**
- **The per-shot lock blocks `hand_back`:** `hand_back` checks the lock and releases the feed rather than keeping it,
  as long as the shot's lock closes before the `finally`.
- **Progress in the status message hides the cancel reason:** the board rewrites the message with the reason at cancel
  and at the end.
- **P2's units:** Isaac Sim's setting is in metres; the plan converts it.

**Improvements:** none beyond the fixes.
