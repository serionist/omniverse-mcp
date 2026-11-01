---
title: Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched
issue: "#111"
status: draft
approved_by:
approved_at:
---

# Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched

#111 holds three things the AI scenario runs of 2026-11-01 saw on Isaac Sim 6.2, headless on Windows: a recording
takes frames at about twice the `fps` asked for, its frame 0 shows a grid and a dark square no later frame has, and a
`get_logs` search returns entries whose shown text doesn't hold the word searched for. The runs' own frames, answers
and metadata, and Isaac Sim 6.2's install, explain all three before any probe; one live probe (below) confirms the
Kit facts on the session's Kit and decides Q3. Two of the three change what users see: when frames come (R1), and
how `get_logs` shows a long entry (R3). The third, frame 0, is no first-frame fault: Isaac Sim hides Kit's grid while
the simulation plays and shows it while it doesn't, in the recording's render as in the viewport (R2).

## Goal

When this is done, with this release's server and Kit extension:

| Row | Scenario | Tool | True when done | Shown by |
|---|---|---|---|---|
| R1 | 6.1, 6.3 | `start_recording` | A frame comes every 1/`fps` seconds of the recording's own clock, which runs with the simulation while it plays and with the wall clock while it is stopped or paused (Q1). At `fps=5` that is 5 frames a second by the clock before play, where a Kit running 120 updates a second gave 10, and one every 0.2 s of simulation while it plays, for every `fps`, where `fps=7` gave one every 0.133 s. `stop_recording` says how much of each the recording spanned (Q2) | `test_recording.py`, `test_recording_handler.py`, `test_tools.py`; live `test_06_10` (new) |
| R2 | 6.1 | `start_recording` | Frames show the stage without Kit's grid and gizmos, stopped, playing or paused, where Isaac Sim showed the grid in frames taken while the simulation didn't play (Q3 B, if the probe shows the texture's own switch works); or the docs say why frames differ (Q3 A) | `test_camera_feed.py`; live `test_06_10`; the probe |
| R3 | 24.3 | `get_logs` | A search still matches the whole message, and an entry whose match lies past the 200 characters the answer shows gets a `matched:` line with the match in its context; every message cut short says how many characters it lost; a channel is shown whole (Q4, Q5) | `test_tools.py` |

Why: an agent that records at `fps=5` for 10 s on a fast Kit gets twice the frames and disk it planned for, and a
frame count that doesn't fit its `fps` reads as a bug. A grid that appears and goes between frames misleads a review
of the recording. A search hit with nothing visible to show for it costs the agent's next call, or its trust.

| In scope | Out of scope |
|---|---|
| The recording's frame clock and `stop_recording`'s answer, in the Kit extension and the server | A `clock` parameter for `start_recording`: a schema change, a one-way door (Q1's D) |
| The recording's own render without gizmos (Q3 B) | `capture_viewport` and `inspect_prim`, which keep the grid, as the viewport shows it; #105 reads it as the sign of an unlit scene |
| `get_logs`' text answer, on the server | The bridge's `/logs` search, which keeps matching the whole message; `execute_script`'s `mcp.get_logs`, which returns whole entries |
| Scenarios 6.1, 6.2 and 24.3's Verify lines | The bridge's own `get_update_event_stream` calls, which Kit 110 logs as deprecated with a callstack: a new issue (Q6) |
| | Isaac Sim's own simulation speed: it ran 1.25 to 1.8 times real time headless in the runs, which a recording timed by the simulation shows by design |

## What the code, the sources and the runs say

### The code, at `f5a27ed`

| Row | Where | What it does |
|---|---|---|
| R1 | `core/recording.py:71-73`, `steps_per_frame` | `max(1, int(time_codes_per_second / fps))`: app updates between frames. At 60 time codes a second, `fps=5` is 12 updates, `fps=7` 8 (7.5 a second), `fps=25` 2 (30), any `fps` above 30 is 1 (every update) |
| R1 | `core/recording.py:88-119`, `FrameClock` | Takes a frame on every `steps`-th update unless the feed awaits the last render or four frames are in flight; counts updates whether or not the timeline plays |
| R1 | `handlers/recording.py:44-45`, `_Session` | `FrameClock(steps_per_frame(timeline.get_time_codes_per_seconds() or 60.0, args.fps))` |
| R1 | `handlers/recording.py:243-261`, `_on_update` | Ticks the clock every update; a frame gets `sim_time` (the timeline's) and `wall_time` (`time.time()` since the start) |
| R1 | `handlers/recording.py:340-359`, `handle_recording_stop` | Answers `frame_count`, `duration_seconds` (wall), the folder, `metadata_file`, `state_file`, `note` |
| R1 | server `tools/recording.py:55`, `:76` | `fps`: "Frames a second: 5 captures one every 0.2 s"; the description: "every few app updates, about 1/fps seconds, whether or not the simulation plays" |
| R2 | `handlers/camera_feed.py:71` | `create_hydra_texture(name, width, height, "", camera_path, "rtx", is_async=False)`; nothing touches the texture's settings |
| R3 | `core/logs.py:173-175`, `LogRing.get_entries` | `search` is a case-blind substring of the whole `msg`, a traceback's every line included |
| R3 | server `tools/misc.py`, `get_logs` | Prints each entry as `[LEVEL] <channel[:40]>: <msg[:200]>`, with no sign of a cut |

### The sources, in Isaac Sim 6.2's install

| # | What | Where |
|---|---|---|
| S1 | `isaacsim.core.throttling` sets `/exts/omni.kit.hydra_texture/gizmos/enabled` to False (and `/rtx/ecoMode/enabled` to False) on the timeline's PLAY, and both back to True on STOP and on PAUSE. Every Isaac Sim app built on `isaacsim.exp.base.kit` loads it | `exts/isaacsim.core.throttling` 2.3.7: `isaacsim/core/throttling/extension.py`, `_on_play`, `_on_stop`, `_on_pause`; `apps/isaacsim.exp.base.kit:23` |
| S2 | Kit's hydra texture reads `/exts/omni.kit.hydra_texture/gizmos/enabled` and `/app/playingScenario/enabled`, and keeps, per texture under its settings path (`get_settings_path()`, `/exts/omni.kit.hydra_texture/<name>/`), `updatesEnabled`, `async`, `asyncLowLatency`, `hydraTickRate`, `width`, `height`, `hydraEngine`, `cameraPath` and `gizmos/enabled`. No doc names the last; the plugin's strings do | `extscache/omni.kit.hydra_texture-1.6.2`: `bin/.../omni.hydratexture.plugin.dll`'s strings; `omni/hydratexture/_hydra_texture.pyi:126`, `get_settings_path` |
| S3 | Kit's grid is drawn by `omni.kit.viewport.legacy_gizmos` (`/app/viewport/grid/enabled`, on by default) into Kit's hydra textures, the recording's among them. Replicator turns it off for its own captures | `omni.kit.viewport.legacy_gizmos-1.0.24`: `config/extension.toml`; `omni.replicator.core-1.13.38`: `scripts/orchestrator.py:1160` |
| S4 | Isaac Sim's full app sets `player.useFixedTimeStepping = true`: "timeline forces dt = 1/timeCodesPerSecond regardless of measured wall-clock dt", with the run loop's rate limit on. Its base app sets it false: the timeline "advances by the loop runner's wall-clock dt (or manual_step_size when manual_mode is on)", with no rate limit. So updates and simulation time are tied by the time codes on one app and not on the other | `apps/isaacsim.exp.full.kit:166-168`; `apps/isaacsim.exp.base.kit:205-207` |
| S5 | `omni.timeline`'s `is_playing()`, `is_stopped()` and `get_current_time()` (seconds), which the handlers already read | `omni.timeline-1.1.2`: `omni/timeline/_timeline.pyi` |

### The runs: 20261101-113702 and 20261101-115226

Each recording's `metadata.json` under `test_project/results/runs/<run>/mcp_output/phase-06/recordings/`:

| Recording | `fps` | Timeline | Frames | Apart by the clock | Apart in simulation |
|---|---|---|---|---|---|
| `rec_1793529578` (6.1, run 1) | 5 | stopped, frames 0-12 | 13 | 0.075 s: 13 a second | 0 |
| | | playing, 13-47 | 35 | 0.14 to 0.15 s | 0.200 s |
| `rec_1793530404` (6.1, run 2) | 5 | stopped, 0-9 | 10 | 0.095 s: 10.5 a second | 0 |
| | | playing, 10-32 | 23 | 0.15 to 0.19 s | 0.200 s |
| `rec_1793530442` (6.3) | 10 | stopped | 48 in 2.37 s | 0.047 s: 21 a second | 0 |
| `rec_1793530460` (6.4) | 10 | stopped, then playing | 65 | playing: 0.055 s | playing: 0.100 s |
| `rec_1793530473` (6.8) | 30 | paused | 90 in 1.99 s | 0.021 s: 45 a second | 0 |

So Kit ran about 95 to 160 updates a second while not playing, and each update advanced the simulation 1/60 s
while playing (S4's fixed step): the simulation ran 1.25 to 1.8 times real time. While playing, `fps` holds in
simulation time; while not, it is Kit's update rate over 12 (at `fps=5`), whatever that is.

Frame 0: each frame's mean difference from the one before, as a share of 255, with the Isaac Sim venv's numpy and
Pillow (`scratchpad/111/frames_stats.py`):

| Recording | Frame 1 | Frames 2 to the last before play | The first frame while playing |
|---|---|---|---|
| `rec_1793530404` | 0.0010 | 0.0006 to 0.0011 (frames 2-9) | 0.0235 (frame 10, sim 0.083 s) |
| `rec_1793529578` | 0.0008 | 0.0006 to 0.0015 (frames 2-12) | 0.0318 (frame 13, sim 0.133 s) |

Frame 0 is no different from the frames after it. Seen: frames 0, 1 and 9 of `rec_1793530404` show Kit's grid beyond
the ground and a dark square on the ground, the red cube's shadow while it hangs at 3 m. Frame 10, the first while
playing, and frames 13 and 32 have no grid; the shadow joins the cube once it lands. The tester compared frame 0 with
frames 12, 13 and 32, all taken while playing. S1 says why the grid goes: Isaac Sim turns the textures' gizmos off on
play and back on at pause and stop.

The log search: scenario 24.3's answer, `phase-24/responses/logs_0003.txt`, holds 50 entries for `search="MCP"`.
Five are carb's `` `get_update_event_stream` is deprecated. Use Events 2.0. Callstack: `` entries, cut at 200
characters inside their second line. Each comes just before a line of the bridge's own (`Deleted the camera feed's
render product`, a texture made for a recording): they are the callstacks of the bridge's own
`get_update_event_stream()` calls (`camera_feed.py:161`, `recording.py:161`, `debug_draw.py:184`), whose file paths
hold `ovmcp`, where "MCP" matched past the cut. The probe prints one whole.

### The probe

`111-probe.py`, in the session's scratchpad `111/`, reads and measures what the runs could not: the session Kit's
timing settings, the gizmo settings in each timeline state, and whether a texture's own `gizmos/enabled` hides the
grid in that texture alone. On a new, empty Y-up stage with no light, so a frame's lit pixels are Kit's grid alone,
it records at `fps=5` from `/World/ProbeCam`, which looks down at the origin, through four phases: S1 stopped 1.5 s;
S2 stopped 1.5 s with the recording texture's own `gizmos/enabled` set False, and a 320x240 `capture_viewport` from
the same camera meanwhile; P playing 2 s; Z paused 1.5 s. It prints, per phase, the updates a second, the frames, their
median gaps by the clock and in simulation, their lit pixels, and the gizmo settings; frames 0 and 1's paths; whether
Kit keeps a texture's settings after the texture goes; and the whole message of a logged deprecation callstack.

What its answers decide:

| It shows | Then |
|---|---|
| S1's frames lit (the grid), P's dark, Z's lit; `gizmos_global` False in P and True in S1 and Z | S1 holds on the session's Kit: the grid follows the timeline |
| S2's frames dark, the capture during S2 lit | The texture's own switch works and is the texture's alone: Q3 B as designed |
| S2's frames lit | The switch is read only when a texture is made, or not at all: a second probe from this branch, setting it right after the texture is made, before Q3 B; or Q3 A |
| Frames 0 and 1 alike (difference near S1's other pairs) | No first-frame fault, as in the runs |
| S1's and Z's frames about 0.2 s apart only if Kit runs 60 updates a second; P's 0.2 s apart in simulation | R1's facts, with the session Kit's `useFixedTimeStepping`, rate limit and time codes |
| The texture's settings still there after stop | The feed deletes its key when it drops the texture (Design, R2) |

## Design

### R1: the recording's own clock (`core/recording.py`, `handlers/recording.py`; Q1)

- **`FrameClock(fps)`** keeps a clock of the recording's own, in seconds. Each update adds the simulation time the
  timeline advanced since the update before while it plays, and the wall time since then (`time.monotonic()`) while
  it is stopped or paused. Frame k is due once that clock reaches k/`fps`, frame 0 on the first update.
- **A due frame waits** while the feed awaits the last frame's render or four frames are in flight, as now, and is
  taken on the first update that can. The next is due one period after, or at the first period boundary ahead of the
  clock when it fell further behind: frames a stall made late are dropped, never sent in a burst. A tolerance of a
  millionth of a period lets twelve steps of 1/60 s make 0.2 s.
- **Numbers** are given when a frame is taken, from 0, never twice, as now (#69).
- **State changes need no case of their own:** the first update of play adds its simulation step; the first paused
  or stopped update adds the wall time since the last. A step back in simulation time (a stop, which rewinds; a loop
  at the end time; a time set by hand) adds nothing for that update.
- **`tick(playing, sim_time, now, render_pending)`** returns the frame's number or None; `simulated` and `idle` total
  the seconds of each kind (Q2). The handler passes `timeline.is_playing()`, `timeline.get_current_time()` and
  `time.monotonic()`; `wall_time` in `metadata.json` stays `time.time()` since the start.
- **`steps_per_frame` goes,** and with it two faults it had while playing: an `fps` that doesn't divide the time codes
  (`fps=7` gave 7.5 frames per second of simulation, `25` gave 30, anything above 30 gave 60), and a Kit app whose
  timeline doesn't move 1/time codes a second per update (S4's base app).

| Option | Why not |
|---|---|
| A: the description only | The stopped rate stays Kit's update rate over a number, which no user sets: 10 to 21 frames a second where 5 or 10 were asked, 5 on a 60-update Kit. The `fps=7` and S4 faults stay |
| C: the wall clock always | Frames of a simulation running faster or slower than real time come unevenly in simulation time, differently on each machine: here 0.4 s of simulation apart at `fps=5`. A review reads frames against `sim_time` |
| D: a `clock` parameter | A schema change, a one-way door, for a choice B makes well without one |

### R1: `stop_recording` says what the frames span (Q2)

`/recording/stop` and `metadata.json` gain `simulation_seconds` (the simulation the recording played through) and
`idle_seconds` (the wall seconds it ran stopped or paused), from the clock's totals. The server's answer:
`Stopped. 33 frames, 4.99s: 3.00 s of simulation played, 2.00 s stopped or paused -> recordings/rec_1`, so frames
come out near `fps` times the two seconds added, and an agent can check that itself. An extension without the fields
gets today's line.

### R2: the recording renders without Kit's gizmos (`handlers/camera_feed.py`; Q3)

- **B, if the probe shows the switch works:** `CameraFeed` takes `gizmos: bool = True`; `handle_recording_start`
  passes False. With False, right after the texture is made, the feed sets `<texture.get_settings_path()>gizmos/enabled`
  to False (S2), so its frames show the stage alone, as Isaac Sim's frames while playing already do and as Replicator's
  captures do (S3). The user's viewport and every capture keep their gizmos. If Kit keeps a texture's settings after
  the texture goes (the probe), `drop()` deletes the key (`carb.settings` `destroy_item`).
- **A otherwise:** no code. `docs/TOOLS.md` and the description say frames taken while the simulation is stopped or
  paused show Kit's grid, as the viewport does, and that Isaac Sim hides it while it plays.
- **C,** captures too: out of scope. `capture_viewport` shows what the viewport would, and #105's warning on an unlit
  scene counts on its grid.

### R3: `get_logs` shows what a search matched (server, `tools/misc.py`; Q4, Q5)

The bridge's search stays as it is, the whole message. Each entry's lines in the answer:

```
  [INFO ] carb: `get_update_event_stream` is deprecated. Use Events 2.0. Callstack:   File "...\asyncio\events.py", line 88, in _run
    self._context.run(self._ ... (+2,345 characters)
    matched: ...File "...\exts\ovmcp.bridge\ovmcp\bridge\handlers\camera_feed.py", line 161, in add...
```

- **A message longer than 200 characters** ends its shown part with `... (+N characters)`, search or not.
- **With `search`,** an entry whose first match lies past the shown part gets a `matched:` line: the line of the
  message that holds the match, cut to 80 characters either side of it, `...` marking each cut end. A match inside
  the shown part adds nothing.
- **The channel is shown whole** (Q5): a `channel` filter matches the whole name too, and the 40-character cut hid
  the part that tells modules apart (`isaacsim.core.experimental.utils.impl...`).
- `count`, the header and the answer written to a file when long (`h.text_response`) stay.

### Older extensions

The server's `get_logs` change needs no extension. With a 0.3.0 extension, `stop_recording` answers today's line
(no `simulation_seconds`), and frames come as today; with this release's, the new clock and, with Q3 B, frames
without gizmos. A 0.3.0 server ignores the new answer fields.

### Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | What does `fps` count? | **A.** As now, said in the description: app updates over the stage's time codes, which is simulation time while playing and Kit's update rate over a number while not. **B.** Simulation time while the timeline plays, the wall clock while it is stopped or paused, through a clock of the recording's own. **C.** The wall clock always. **D.** A `clock` parameter | B: frames match the simulation where motion is, and the clock where nothing moves; it also fixes `fps` values that don't divide the time codes and Kit apps whose timeline isn't stepped by them. The description says frames come faster than `fps` by the clock while a fast Kit plays | |
| Q2 | Should `stop_recording` say how much simulation and how much stopped time the frames span (`simulation_seconds`, `idle_seconds`, in the answer and `metadata.json`)? | **A.** Yes. **B.** No: `docs/TOOLS.md` explains the count | A: under B the frame count still reads as wrong against the duration, which is what the tester flagged; two numbers make it checkable | |
| Q3 | Frame 0's grid: what changes? | **A.** Nothing in code: the docs say frames show Kit's grid while the simulation is stopped or paused, and Isaac Sim hides it while it plays. **B.** The recording's render turns its own gizmos off, so no frame shows them. **C.** B for captures too | B if the probe shows the texture's own switch hides the grid in it alone; A otherwise. C is out of scope (R2) | |
| Q4 | `get_logs`: a match the answer hides | **A.** Match only the 200 characters shown: a search for an exception's name, on a traceback's last line, then finds nothing. **B.** Match the whole message, as now, and show the match on a `matched:` line; mark every cut. **C.** Show whole messages when searching: a callstack runs to thousands of characters | B | |
| Q5 | `get_logs`: show the channel whole, not cut at 40? | Yes; or keep the cut | Yes: a channel is one short name, and the cut hides what the `channel` filter matched, R3's fault again | |
| Q6 | The bridge's three `get_update_event_stream()` subscriptions log Kit 110's deprecation, with a callstack, each time one is made: in the runs, each recording and each feed released | **A.** A new issue: Events 2.0's `GLOBAL_EVENT_UPDATE`, with Kit 107 checked. **B.** In this change | A: it touches `camera_feed.py` and `debug_draw.py` beyond this issue, the first in #114's way, and needs Kit 107 checked | |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change: `tests/fixtures/mcp-tools.json` holds
  `fps` as an integer of at least 1, default 5, and no descriptions. The routes keep their paths and only gain answer
  fields, `simulation_seconds` and `idle_seconds`; `PROTOCOL` stays 1. The output folder's layout, its files and
  their names, stays; `metadata.json` gains two keys.
- **What users notice,** under CHANGELOG's Changed and Fixed, the extension's lines saying they are the Kit
  extension's:
  - Fewer frames before play and while paused on a Kit faster than the stage's time codes: `fps` a second by the
    clock, where it was the update rate over a number. While playing, frames are 1/`fps` s of simulation apart for
    every `fps`, and come faster than `fps` by the clock wherever the simulation runs faster than real time, as now.
  - The first frame on the first update after the start, where it waited `steps` updates.
  - With Q3 B, no grid in any frame, on Isaac Sim before play and after pause, and on every Kit app without Isaac
    Sim's throttling, where every frame had it.
  - `stop_recording`'s line names the simulation and stopped seconds (Q2).
  - `get_logs` lines: a cut marked with its length, a `matched:` line for a hidden match, channels whole.
- **Kit apps:** the clock reads the timeline alone; the texture switch (Q3 B) is plain `carb.settings` on the
  texture's own path, and a Kit that doesn't read it shows the grid as now.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | The runs read (above); the probe run by the session at 8212 on main's extension, its answers into this plan | `111-probe.out.txt` in the session's scratchpad |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | R1: `FrameClock(fps)` in `core/recording.py`; `steps_per_frame` out | `tests/test_recording.py` |
| 3 | R1: the handler ticks the clock with the timeline's state and time and `time.monotonic()`; Q2's fields in the stop answer and `metadata.json` | `tests/test_recording_handler.py` |
| 4 | R1 and Q2 on the server: `start_recording`'s and `stop_recording`'s descriptions, `fps`'s, the stop line | `tests/test_tools.py` |
| 5 | R2 (Q3 B): `CameraFeed(gizmos=False)` for recordings, and the key deleted at `drop()` if the probe says Kit keeps it | `tests/test_camera_feed.py`, `tests/test_recording_handler.py` |
| 6 | R3: `get_logs`' lines, the cut marker, `matched:`, the channel whole; its description | `tests/test_tools.py` |
| 7 | Docs, CHANGELOG, and scenarios 6.1, 6.2 and 24.3's Verify lines (Docs, below) | The gate's checks; `tests/test_contract.py` unchanged |
| 8 | The live tests below, run by the session on Isaac Sim 6.2 headless at 8212, then both suites whole; the AI scenarios' phases 6 and 24 | No failure beyond `main`'s on the same Kit |
| 9 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fix has a test that fails at `f5a27ed`, named first.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_recording.py` | The clock, fed updates by hand: playing at 1/60 s a step, `fps=5` takes a frame every 12 updates, and `fps=7` 70 frames in 600 updates (fails at `f5a27ed`: 75); stopped at 120 updates a second by the clock, `fps=5` one every 24 updates (fails: 12); paused likewise; stopped, then play, then pause: the gaps stay 0.2 s of their own kind and no frame comes twice at the change; a step back in simulation time adds nothing; a frame held by a pending render comes on the next update that can, and after a stall of several periods only one comes, the next on the boundary after the clock; four in flight hold frames back, as now; numbers from 0 in order whatever order frames end in; `simulated` and `idle` total each kind. The `steps_per_frame` test goes |
| `tests/test_recording_handler.py` | The fake timeline gains `is_playing`, the fake Kit a clock the test moves; the existing "every few updates" and "no more than four in flight" tests move to it; a stopped recording at `fps=30` takes one frame per 1/30 s of fake time whatever the updates between; the stop answer and `metadata.json` carry `simulation_seconds` and `idle_seconds`; with Q3 B, the feed is made with `gizmos=False` |
| `tests/test_camera_feed.py` | Q3 B: a feed made with `gizmos=False` sets its texture's `<settings path>gizmos/enabled` to False and, if the probe says Kit keeps it, deletes it at `drop()`; a feed made without it, a capture's, writes no setting |
| `tests/test_tools.py` | `stop_recording` prints the two seconds when the answer has them and today's line when it doesn't; `get_logs`: a 2,545-character message whose match is at 2,000 prints its first 200, `... (+2,345 characters)` and a `matched:` line holding the match in its original case; a match in the first 200 adds no line; no `search` adds no line but keeps the marker; a message of 200 characters or fewer has no marker; a 50-character channel is shown whole (each fails at `f5a27ed`) |

**Live (`tests/test_scenarios.py`, by the session on Isaac Sim 6.2 at 8212, Y-up and Z-up):**

| Test | What |
|---|---|
| `test_06_10_frames_follow_the_clock_stopped_and_the_simulation_playing` (new) | `fps=5` from `/World/RecCam`: 1.2 s stopped, 1.2 s playing, 1.0 s paused. In `metadata.json`, the frames before play are 0.2 s apart by `wall_time` (median, within 0.05), those while playing 0.2 s apart in `sim_time` (median, within 1/60), the paused ones 0.2 s by `wall_time`; `simulation_seconds` is the simulation played, within one frame, and `idle_seconds` about 2.2. With Q3 B, the recording texture's `gizmos/enabled` reads False while it runs and the global `/exts/omni.kit.hydra_texture/gizmos/enabled` is untouched. Fails at `f5a27ed` on a Kit faster than 60 updates a second |
| `test_06_01` to `test_06_09`, `test_07_*` | Pass as they are: no test counts frames against `fps` |
| `test_24_*` | Unchanged: the bridge's search is unchanged |

The AI scenarios' phases 6 and 24 (`uv run tools/scenarios.py run --phases 6,24`) show the Verify lines below hold.
Neither suite can show the grid in a frame on a stage of the scenarios' own, whose ground hides most of it: the probe
does, once.

## Docs

| File | What changes |
|---|---|
| `docs/TOOLS.md` | `start_recording`'s "When frames come": the recording's clock, simulation while playing and wall clock while not, at most one frame an update, frames faster than `fps` by the clock while a fast Kit plays; with Q3 B, frames without Kit's grid and gizmos (A: frames while stopped or paused show the grid). `stop_recording`'s Returns: the two seconds. `get_logs`: the cut marker, the `matched:` line, channels whole |
| `docs/ARCHITECTURE.md` | Recording System, step 2: the clock in place of `steps_per_frame`; step 1, with Q3 B: the feed's own gizmos off |
| `src/omniverse_mcp/tools/recording.py`, `tools/misc.py` | `start_recording`'s description and `fps`'s; `stop_recording`'s; `get_logs`' |
| `test_project/scenarios.md` | 6.1: a Verify line on `metadata.json`'s gaps before and during play and on the stop answer's seconds; 6.2: with Q3 B, frame 0 shows no grid; 24.3: each entry shows the word searched for in its text or on its `matched:` line |
| `CHANGELOG.md` | Under Unreleased: Changed, the clock and the stop line (the Kit extension's, and the server's); Fixed, with Q3 B, the grid in frames before play; Fixed, `get_logs`' hidden match and cut channels (the server's) |
| `README.md`, `plugin/skills/simulate/SKILL.md`, `docs/AI_GUIDE.md` | None: none states when frames come or how `get_logs` prints |

## Risks

| Risk | Status |
|---|---|
| Q3 B rests on a setting no doc names (S2); a Kit that ignores it shows the grid as now | Accepted: harmless, and the probe shows it on Isaac Sim 6.2. The live test checks the setting is written, not its effect |
| A texture's settings outlive it in `carb.settings`, so each recording would leave a key | Resolved by the probe: if so, `drop()` deletes the key |
| A Kit slower than `fps` while stopped: at most one frame an update | Accepted, as now; the clock skips the boundaries it passed, so frames are fewer, never bunched. TOOLS.md says so |
| A forward jump in simulation time while playing (a time set by hand) adds the jump: one frame, then the next boundary after the clock | Accepted: no burst, and a jump is rare while playing |
| The first frame now comes on the first update, before the feed's frame settles | Resolved: the start already waits for the feed's first frame (`first_frame`), and frames come from a feed rendering every update (#25's E23) |
| Frames still come faster than `fps` by the clock while a simulation runs faster than real time; a tester may flag it again | Accepted by design (Q1 B): the description, TOOLS.md, the stop line (Q2) and scenario 6.1's Verify line say so |
| `camera_feed.py` is #114's file too | Accepted: this change adds a constructor parameter and a line in `drop()`; #114 changes the waits |

## Plan review

Not reviewed yet.
