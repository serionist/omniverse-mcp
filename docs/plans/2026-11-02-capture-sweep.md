---
title: Add capture_sweep, which captures a list of shots with their own cameras, selections and times as a job, to the tool contract
issue: "#157"
status: draft
approved_by:
approved_at:
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
  lent (`camera_feed.lend`) at the start and handed back (`hand_back(feed, stage_id, healthy)`) in the `finally`, so the
  viewport lock is taken only to start, a capture made during a sweep gets a feed of its own as during a recording, a
  save between shots doesn't release it, and no new RTX view is set up per shot (#114); each shot goes through
  `_capture_frame`, 20 of the feed's frames after its camera is set (#57), with `is_black`; a shot's `camera_path` is
  checked with `camera_error`; at shutdown the sweep lets the feed go with `let_go_now`, as `recording.shut_down`
  does.
- **`core/xform.aim`** for a pose given by a target, the stage's up axis respected.

### The extension

- **`ovmcp/core/sweep.py`** (Kit-free): `Shot` and `read_shots(body)` checking every shot before anything changes (a
  pose given one way, intrinsics above zero, apertures whose ratio fits width over height within 1%, refused with the
  aperture that would fit (fit I6), a time a number, selections as names), up to 2,000 shots, a manifest's shots read
  back as shots; `pose(shot, up_axis)` giving the camera's eye and target from a yaw and pitch about the stage's up
  axis; `changes(previous, shot)`, the selections to write between two shots, so a run of shots in one state switches
  nothing and a shot's revert merges with the next one's apply; `manifest(...)`; `file_name(index, shot)`;
  `folder_name(name)` refusing a name that isn't one plain folder name (no `..`, no separator).
- **`handlers/sweep.py`:** `handle_sweep_start(body)` (`/jobs/sweep`) refuses a bad shot, a bad name, a folder that
  already holds a manifest (a sweep never writes over another's; the answer names the folder), or a busy board, then
  starts the job. Its coroutine:
  - reads the timeline's state and time, and makes a camera of its own in the session layer (`/OmniverseKit_Sweep`,
    as Kit keeps its cameras there), so no file changes;
  - for each shot: writes the selections that change through `switch`, keeping every snapshot it returns, with #155's
    refresh when it is needed; after a shot that switched, waits, bounded, until the stage has finished loading
    (`get_stage_loading_status()`), since a variant that brings payloads, materials or textures captured mid-load
    differs from its twin (fit I5); with a time, pauses the timeline at that time; without one, puts the timeline back
    to its state at the start; aims the camera and sets its lens; takes the frame through the lent feed; writes the
    PNG into the folder; prints `shot 37 of 400` as its progress;
  - in a `finally`: restores every snapshot it kept, last first, so every selection any shot wrote is back exactly,
    not only the first shot's; puts the timeline's state and time back; deletes its camera; hands the feed back; and
    writes the manifest of the shots done, file names relative to the folder, so a cancelled sweep still says what it
    took.

### The server

- `capture_sweep(shots: list[Shot] = [], shots_file: str = "", width=1280, height=720, name="")`, `EDITS`, since it
  changes the stage while it runs and puts it back: one of `shots` and `shots_file`; the server reads `shots_file`
  (a list of shots, or a sweep's `manifest.json`) and sends the shots, with the folder `<output>/sweeps/<name>`, `name`
  defaulting to a time stamp, as `start_recording` sends `<output>/recordings`.
- `get_job` for a sweep answers `400 shots in mcp_output/sweeps/site_a/ (manifest.json); 2 black: shots 12, 13`, so
  the agent's context gets one line, not 400.
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
| 1 | `ovmcp/core/sweep.py`, tests first | `tests/test_sweep.py`: shots read and refused, a manifest read back as shots, apertures against the image's shape, poses on both axes, `changes` merging reverts with applies, the manifest, file and folder names (`..` refused) |
| 2 | `handlers/sweep.py`, `/jobs/sweep` | handler tests with the Kit fakes: every layer's export and the timeline as before after a sweep whose shots switch different prims, after a cancel mid-sweep and after an error; a shot without a time after one with a time; the manifest of the shots done; a folder with a manifest refused; the feed lent and handed back |
| 3 | The client, the tool, `shots_file`, `get_job`'s answer for a sweep; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs, the `scene` skill | review |
| 5 | Live: a referenced file with a variant set; a 6-shot sweep over two states and two poses at 1280 x 720 with the case's lens; the root and session layers' exports as before, once the kept feed's render product is released (`release_kept`, since Kit writes a feed's render product into both layers), and the timeline as before; the manifest matching the files; the same sweep again from the first's manifest, each picture within the tolerance of its twin; whether the loading wait is needed after a switch, measured; one Replicator agent, a stopped timeline repeating and a seek not; a 50-shot sweep cancelled mid-way, the stage put back and the manifest saying what it took | `tests/test_integration.py` on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live: step 5, on a Z-up and a Y-up stage; the tolerance is a mean absolute difference under 2 of 255 per channel
  between twins, measured and recorded.
- What neither shows: a 400-shot sweep on the case's site (a by-hand run of 200 shots stands in, timed); Kit on
  another machine than the server (Kit writes under the same path there, as for recordings); how RTX renders
  apertures that don't fit the image's shape (refused, so never reached).

## Docs

`docs/TOOLS.md` (the tool, `shots_file`, the manifest, `get_job` for a sweep), `docs/ARCHITECTURE.md` (the route),
`docs/SETUP.md` (a remote Kit writes sweeps on its own machine, as recordings), `README.md`'s list and count and the
output folder's layout, the `scene` skill (a sweep for a scene's check, Replicator agents), `CHANGELOG.md` (Added).

## Risks

- **A sweep's length:** each shot waits its 20 frames, a switch with Fabric's refresh adds its own, and a switch that
  loads files waits for them; 400 shots take minutes. Accepted: a job, with progress; #155's measurement decides the
  refresh's cost.
- **Kit hangs mid-sweep** (#162's Fabric population hang, after many stage changes): the sweep can't prevent it; a
  restart loses the session layer, so the files are as they were anyway.
- **The lent feed's memory at a large size:** one feed at the sweep's size, as a recording's.

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
