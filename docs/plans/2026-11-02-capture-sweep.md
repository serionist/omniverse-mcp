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
(Replicator agents), so a repeatable shot of one needs a fixed timeline time.

When this is done:

- `capture_sweep(shots, width=1280, height=720, name="")` starts a sweep as a job on #158's board (kind `sweep`) and
  answers its id at once; `get_job` gives `shot 37 of 400` as it goes and, once it ends, the manifest;
- each shot is a pose (a position with a yaw and pitch, or a target, or a `camera_path`), optional intrinsics (focal
  length, apertures), optional selections `{prim: {set: option}}`, and an optional timeline time;
- the PNGs and a `manifest.json` (per shot: its name, pose, lens, selections, time, file and the frame it was taken
  on, with the sweep's size, renderer and Kit app) land in the server's output folder, under `sweeps/<name>/`;
- every layer is as it was afterwards, the session layer included, and so is the timeline, even after a cancel;
- the same shots on an unchanged stage give the same pictures within a stated pixel tolerance.

In scope: the tool, its routes, a Kit-free core for shots and the manifest, the job's coroutine, the server's pull of
the files, docs, tests.
Out of scope: a contact sheet (the manifest gives what one needs; a later issue); boxes or segmentation per shot;
comparing two sweeps; shots of several sizes in one sweep (one size, one kept feed).

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | "The same pictures" twice means within a pixel tolerance, not bit for bit | yes (maintainer, 2026-11-02) |
| Q2 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02) |

### What it builds on

- **#158's job board** (`docs/plans/2026-11-02-script-jobs.md`): a `sweep` kind beside `script`, started with
  `watch_stage` so a new stage cancels it, its `finally` holding the slot until the stage is put back, its result a
  dict (the manifest) that `get_job` formats by kind, `/jobs/get` and `/jobs/cancel` as they are.
- **#155's switch** (`docs/plans/2026-11-02-variant-layer.md`): `switch(stage, {prim: {set: name}}, "session")`
  returns a `Snapshot`; the sweep keeps the first one and restores it in its `finally`.
- **The kept capture feed** (`camera_feed.py`, #141): one feed at the sweep's size serves every shot, and each shot
  takes its frame 20 of the feed's frames after its camera is set, as a capture does (#57).
- **`core/xform.aim`** for a pose given by a target, the stage's up axis respected.

### The extension

- **`ovmcp/core/sweep.py`** (Kit-free): `Shot` and `read_shots(body)` checking every shot before anything changes (a
  pose given one way, intrinsics above zero, a time a number, selections as names), up to 2,000 shots;
  `pose(shot, up_axis)` giving the camera's eye and target from a yaw and pitch about the stage's up axis;
  `changes(previous, shot)`, the selections to write between two shots, so a run of shots in one state switches
  nothing and a shot's revert merges with the next one's apply; `manifest(...)`; `file_name(index, shot)`.
- **`handlers/sweep.py`:** `handle_sweep_start(body)` (`/jobs/sweep`) refuses a bad shot or a busy board, then starts
  the job. Its coroutine:
  - makes a camera of its own in the session layer (`/OmniverseKit_Sweep`, as Kit keeps its cameras there), so no
    file changes;
  - for each shot: writes the selections that change through `switch`, with #155's refresh when it is needed; sets the
    timeline's time and pauses it when the shot gives one; aims the camera and sets its lens; takes the frame through
    the kept feed; writes the PNG to the job's folder on Kit's machine; prints `shot 37 of 400` as its progress;
  - in a `finally`: restores the first snapshot (every selection back exactly), the timeline's state and time, deletes
    its camera, and writes the manifest of the shots done, so a cancelled sweep still says what it took.
- **Its files on Kit's machine:** a folder of the job's own under Kit's temp folder. A route `/jobs/file` gives one
  file of a finished or running job by its name, refusing any name that isn't one of that job's files, so the server
  can pull them when Kit runs on another machine.

### The server

- `capture_sweep(shots: list[Shot], width=1280, height=720, name="")`, `EDITS`, since it changes the
  stage while it runs and puts it back.
- `get_job` for a sweep: pulls each file not yet pulled through `/jobs/file` into
  `mcp_output/sweeps/<name or job id>/`, then, once it ends, writes `manifest.json` there with local paths and answers
  `400 shots in mcp_output/sweeps/site_a/ (manifest.json); 0 failed`, so the agent's context gets one line, not 400.
- The description: one call for many shots, the job and how to read it, that the stage is put back, the lens and time
  per shot, the size limit, and that a cancel keeps what was taken.

### Alternatives

- **The server loops over shots, one bridge call each:** one MCP call for minutes with no progress, and a lost
  connection loses the sweep; the issue asks for a job.
- **Write the PNGs straight into the server's folder:** works only when Kit and the server share a disk; the pull
  works either way, and a same-machine shortcut can come later.
- **Images in the job's result:** 400 PNGs at 1280 x 720 are hundreds of megabytes of JSON.
- **Hide and show prims for a state:** no; the case's rule is that nothing is hidden, and selections cover lights and
  time of day.

## Compatibility

**One-way doors: the tool contract, the wire protocol's paths, the output folder's layout.** A new tool, two new
routes (`/jobs/sweep`, `/jobs/file`), and a new folder `sweeps/` in the output folder: additive. The maintainer's
agreement is posted in #157 before the PR. It needs #155's and #158's extension: an older one answers the unknown
route with the install advice.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/sweep.py`, tests first | `tests/test_sweep.py`: shots read and refused, poses on both axes, `changes` merging reverts with applies, the manifest, file names |
| 2 | `handlers/sweep.py`, `/jobs/sweep`, `/jobs/file` | handler tests with the Kit fakes: every layer's export and the timeline as before after a sweep, after a cancel mid-sweep and after an error; the manifest of the shots done; a file name outside the job refused |
| 3 | The client, the tool, `get_job`'s pull and answer for a sweep; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs, the `scene` skill | review |
| 5 | Live: a referenced file with a variant set; a 6-shot sweep over two states and two poses at 1280 x 720 with the case's lens; the root and session layers' exports and the timeline as before; the manifest matching the files; the same sweep again, each picture within the tolerance of its twin; a 50-shot sweep cancelled mid-way, the stage put back and the manifest saying what it took | `tests/test_integration.py` on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live: step 5, on a Z-up and a Y-up stage; the tolerance is a mean absolute difference under 2 of 255 per channel
  between twins, measured and recorded.
- What neither shows: a 400-shot sweep on the case's site (a by-hand run of 200 shots stands in, timed); Kit on
  another machine than the server (the pull runs the same either way); Replicator agents, whose time step the
  timeline-time path covers in principle.

## Docs

`docs/TOOLS.md` (the tool, the manifest, `get_job` for a sweep), `docs/ARCHITECTURE.md` (the routes, the job's
folder), `README.md`'s list and count and the output folder's layout, the `scene` skill (a sweep for a scene's
check), `CHANGELOG.md` (Added).

## Risks

- **A sweep's length:** each shot waits its 20 frames, and a switch with Fabric's refresh adds its own; 400 shots take
  minutes. Accepted: a job, with progress; #155's measurement decides the refresh's cost.
- **Kit hangs mid-sweep** (#162's Fabric population hang, after many stage changes): the sweep can't prevent it; a
  restart loses the session layer, so the files are as they were anyway.
- **The kept feed's memory at a large size:** one feed at the sweep's size, as a capture's.

## Plan review

None yet.
