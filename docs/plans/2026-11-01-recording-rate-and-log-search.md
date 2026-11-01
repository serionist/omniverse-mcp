---
title: Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched
issue: "#111"
status: draft
approved_by:
approved_at:
---

# Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched

#111 holds three things the AI scenario runs of 2026-11-01 saw on Isaac Sim 6.2, headless on Windows:

- a recording takes frames at about twice the `fps` asked for;
- its frame 0 shows a grid and a dark square that no later frame has;
- a `get_logs` search returns entries whose shown text doesn't hold the word searched for.

The runs' own frames, answers and metadata, and Isaac Sim 6.2's install, explain all three. A live probe on the
session's Kit then confirmed the Kit facts and settled Q3. Two of the three change what users see: when frames come
(R1), and how `get_logs` shows a long entry (R3). The third, frame 0, is no first-frame fault. Isaac Sim hides Kit's
grid while the simulation plays and shows it while it doesn't, in the recording's render as in the viewport. Only the
docs change for it (R2).

## Goal

When this is done, with this release's server and Kit extension:

| Row | Scenario | Tool | True when done | Shown by |
|---|---|---|---|---|
| R1 | 6.1, 6.3 | `start_recording` | A frame comes every 1/`fps` seconds of the recording's own clock, which runs with the simulation while it plays and with the wall clock while it is stopped or paused (Q1). At `fps=5` that is 5 frames a second by the clock before play and while paused, where the probe's Kit gave 8.5 to 12.6. While playing it is one frame every 0.2 s of simulation for every `fps`, where `fps=7` gave one every 0.133 s. `stop_recording` says how much of each the recording spanned (Q2) | `test_recording.py`, `test_recording_handler.py`, `test_tools.py`; live `test_06_10` (new) |
| R2 | 6.1 | `start_recording` | The description and `docs/TOOLS.md` say that frames taken while the simulation is stopped or paused show Kit's grid, as the viewport does, and that Isaac Sim hides it while the simulation plays. Scenario 6.2's Verify line expects that (Q3 A) | The probe; scenario 6.2 |
| R3 | 24.3 | `get_logs` | A search still matches the whole message. An entry whose match lies past the 200 characters the answer shows gets a `matched:` line with the match in its context. Every message cut short says how many characters it lost, and a channel is shown whole (Q4, Q5) | `test_tools.py` |

Why:

- An agent that records at `fps=5` for 10 s on a fast Kit gets twice the frames and disk it planned for, and a frame
  count that doesn't fit its `fps` reads as a bug.
- A grid that appears and goes between frames misleads a review of the recording unless the docs say why.
- A search hit with nothing visible to show for it costs the agent's next call, or its trust.

| In scope | Out of scope |
|---|---|
| The recording's frame clock and `stop_recording`'s answer, in the Kit extension and the server | A `clock` parameter for `start_recording`: a schema change, a one-way door (Q1's D) |
| What the docs say about the grid in a recording's frames (Q3 A) | Frames without Kit's grid. Set while the texture renders, the texture's own switch only dims the grid. The global switch is the user's viewport's and every capture's too (Q3) |
| `get_logs`' text answer, on the server | `capture_viewport` and `inspect_prim`, which keep the grid as the viewport shows it; #105 reads the grid as the sign of an unlit scene |
| Scenarios 6.1, 6.2 and 24.3's Verify lines | The bridge's `/logs` search, which keeps matching the whole message; `execute_script`'s `mcp.get_logs`, which returns whole entries |
| | The bridge's own `get_update_event_stream` calls, which Kit 110 logs as deprecated with a callstack: a new issue (Q6) |
| | Isaac Sim's own simulation speed. It ran 1.25 to 2.5 times real time headless, which a recording timed by the simulation shows by design |

## What the code, the sources, the runs and the probe say

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
| S2 | Kit's hydra texture reads `/exts/omni.kit.hydra_texture/gizmos/enabled` and `/app/playingScenario/enabled`. It keeps, per texture under its settings path (`get_settings_path()`, `/exts/omni.kit.hydra_texture/<name>/`), `updatesEnabled`, `async`, `asyncLowLatency`, `hydraTickRate`, `width`, `height`, `hydraEngine`, `cameraPath` and `gizmos/enabled`. No doc names the last; the plugin's strings do | `extscache/omni.kit.hydra_texture-1.6.2`: `bin/.../omni.hydratexture.plugin.dll`'s strings; `omni/hydratexture/_hydra_texture.pyi:126`, `get_settings_path` |
| S3 | Kit's grid is drawn by `omni.kit.viewport.legacy_gizmos` (`/app/viewport/grid/enabled`, on by default) into Kit's hydra textures, the recording's among them. Replicator turns it off for its own captures | `omni.kit.viewport.legacy_gizmos-1.0.24`: `config/extension.toml`; `omni.replicator.core-1.13.38`: `scripts/orchestrator.py:1160` |
| S4 | Isaac Sim's full app sets `player.useFixedTimeStepping = true`: "timeline forces dt = 1/timeCodesPerSecond regardless of measured wall-clock dt". Its base app, and the Python app built on it, set it false but turn on `runLoops.main.manualModeEnabled`: "dt is fixed at requested rate", and the timeline "advances by the loop runner's wall-clock dt (or manual_step_size when manual_mode is on)". Either way one update is one time code on Isaac Sim, as the probe measured. A Kit app with neither would step the timeline by the measured time between updates | `apps/isaacsim.exp.full.kit:166-168`; `apps/isaacsim.exp.base.kit:205-207`; `apps/isaacsim.exp.base.python.kit` |
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
while playing (S4). The simulation ran 1.25 to 1.8 times real time. While playing, `fps` holds in simulation time;
while not, it is Kit's update rate divided by 12 (at `fps=5`), whatever that rate is.

Frame 0: each frame's mean difference from the one before, as a share of 255, computed with the Isaac Sim venv's numpy
and Pillow (`scratchpad/111/frames_stats.py`):

| Recording | Frame 1 | Frames 2 to the last before play | The first frame while playing |
|---|---|---|---|
| `rec_1793530404` | 0.0010 | 0.0006 to 0.0011 (frames 2-9) | 0.0235 (frame 10, sim 0.083 s) |
| `rec_1793529578` | 0.0008 | 0.0006 to 0.0015 (frames 2-12) | 0.0318 (frame 13, sim 0.133 s) |

Frame 0 is no different from the frames after it:

- Frames 0, 1 and 9 of `rec_1793530404` show Kit's grid beyond the ground, and a dark square on the ground. The square
  is the red cube's shadow while the cube hangs at 3 m.
- Frame 10, the first while playing, and frames 13 and 32 have no grid. The shadow joins the cube once it lands.
- The tester compared frame 0 with frames 12, 13 and 32, all taken while playing.
- S1 says why the grid goes: Isaac Sim turns the textures' gizmos off on play and back on at pause and stop.

The log search: scenario 24.3's answer, `phase-24/responses/logs_0003.txt`, holds 50 entries for `search="MCP"`.

- Five are carb's `` `get_update_event_stream` is deprecated. Use Events 2.0. Callstack: `` entries, cut at 200
  characters inside their second line.
- Each comes just before one of the bridge's own lines (`Deleted the camera feed's render product`, or a texture made
  for a recording). They are the callstacks of the bridge's own `get_update_event_stream()` calls
  (`camera_feed.py:161`, `recording.py:161`, `debug_draw.py:184`).
- Their file paths hold `ovmcp`, so "MCP" matched past the cut.

### The probe: `111-probe.py`

The script is in the session's scratchpad, `111/`. The session ran it on a fresh headless Isaac Sim 6.2 ("Isaac-Sim
Python" 6.2.0, Kit 110.4.0) at port 8212, with main's extension (`f5a27ed`). It exited 0 and wrote its output to
`111-probe.out.txt` beside the script.

- **The scene:** a new, empty Y-up stage with no light, so a frame's lit pixels are Kit's grid and nothing else. The
  probe recorded at `fps=5`, 320x240, from `/World/ProbeCam`, which looks down at the origin.
- **The phases:**
  - S1: stopped, 1.5 s;
  - S2: stopped, 1.5 s, with the recording texture's own `gizmos/enabled` set False after it had rendered for 1.5 s,
    and a 320x240 `capture_viewport` from the same camera meanwhile;
  - P: playing, 2 s;
  - Z: paused, 1.5 s.

The Kit's settings:

- `/app/player/useFixedTimeStepping` false, `/app/runLoops/main/rateLimitEnabled` false,
  `/app/runLoops/main/manualModeEnabled` true;
- 60 time codes a second, end time 16,666.7 s, looping;
- `isaacsim.core.throttling` enabled, `/exts/omni.kit.hydra_texture/gizmos/enabled` true,
  `/app/viewport/grid/enabled` true.

| Phase | Timeline | Seconds | Updates a second | Frames | Frames a wall second | Median gap by the clock | Median gap in simulation | Lit pixels a frame | Global `gizmos/enabled` | The texture's own |
|---|---|---|---|---|---|---|---|---|---|---|
| S1 | stopped | 1.53 | 105 | 13 | 8.5 | 0.081 s | 0 | 9,270 | true | true (Kit's) |
| S2 | stopped | 1.83 | 153 | 23 | 12.6 | 0.068 s | 0 | 1,674 | true | false |
| P | playing | 2.11 | 151 | 27 | 12.8 | 0.076 s | 0.200 s | 0 | false | true |
| Z | paused | 1.52 | 139 | 17 | 11.2 | 0.079 s | 0 | 9,270 | true | true |

"Lit" means any channel above 20 of 255.

| # | What it showed | So |
|---|---|---|
| P1 | While playing, the simulation advanced 5.27 s in 2.11 s of wall time: 1/60 s an update, 2.5 times real time, with fixed time stepping off. Frames were exactly 0.2 s of simulation apart (frames 36-62: 0.1, 0.3, ... 5.3) and 12.8 a second by the clock | S4: manual mode fixes the step, so update counting is simulation time while playing on both of Isaac Sim's apps. Q1 B keeps that and fixes the rest |
| P2 | Stopped and paused, `fps=5` gave 8.5 to 12.6 frames a second by the clock, at 105 to 153 updates a second | R1's fault, on the session's Kit too: the rate follows Kit's update rate |
| P3 | S1's and Z's frames show the grid (15,204 pixels above 5, the brightest 137; frames 0 and 63 seen). P's show nothing: 0 pixels. The global switch read false in P and true in S1 and Z | S1 holds: the grid follows the timeline. Paused frames show it as stopped ones do |
| P4 | In S2 the grid stayed. 12,682 pixels were still above 5, at 0.59 of S1's brightness on the same pixels (frame 13 seen: every line still there, dimmer). The capture taken during S2 was S1's frame to the pixel (15,204 above 5, the same sum) | The texture's own switch, set while the texture renders, dims the grid and doesn't hide it. It touches that texture alone. Whether it hides the grid when set before the texture's first frame is not measured (Q3) |
| P5 | Frames 0 and 1, and every pair in S1, are identical (difference 0.0). Frame 0 came 0.18 s after the start and frame 1 0.24 s later, then one every 0.07 to 0.1 s | No first-frame fault, as in the runs. The longer first gap is Kit updating more slowly just after the start (S1's 105 a second against 150 later) |
| P6 | After the stop, Kit still holds the texture's settings: `updatesEnabled` false, `cameraPath`, `width`, `height`, `gizmos.enabled` true and the rest | Kit keeps every texture's settings after it goes, captures' included. That is Kit's own behaviour, and none of the keys is the bridge's |
| P7 | A deprecation entry, whole: 895 characters. Its first 200 end inside the callstack's second line, and the first "mcp" is at character 296. That is in the next frame of the callstack, the bridge's own file, whose path here holds "omniverse-mcp" (the session loads the extension from a folder of that name) | R3: the match lies past the cut, in the bridge's own frame of the callstack. Q6: the deprecation comes from the bridge's own call |

The probe restored the texture's own switch before playing and deleted `/World/ProbeCam`. Kit's settings afterwards
equal those before, except `/app/viewport/grid/plane`, `XY` before and `XZ` after: Kit turns its grid to the new
stage's Y up axis.

## Design

### R1: the recording's own clock (`core/recording.py`, `handlers/recording.py`; Q1)

- **`FrameClock(fps)`** keeps a clock of the recording's own, in seconds. Each update adds:
  - while the timeline plays, the simulation time it advanced since the update before;
  - while it is stopped or paused, the wall time since then (`time.monotonic()`).

  Frame k is due once that clock reaches k/`fps`, frame 0 on the first update.
- **A due frame waits** while the feed awaits the last frame's render or four frames are in flight, as now. It is
  taken on the first update that can take it.
  - The next frame is due one period later. If the clock has fallen further behind, the next is due at the first
    period boundary ahead of the clock: frames that a stall made late are dropped, never sent in a burst.
  - A tolerance of a millionth of a period lets twelve steps of 1/60 s add up to 0.2 s.
- **Numbers** are given when a frame is taken, from 0, never twice, as now (#69).
- **State changes need no case of their own:**
  - the first update of play adds its simulation step;
  - the first paused or stopped update adds the wall time since the last;
  - a step back in simulation time adds nothing for that update. That covers a stop, which rewinds, a loop at the end
    time, and a time set by hand.
- **`tick(playing, sim_time, now, render_pending)`** returns the frame's number or None. `simulated` and `idle` total
  the seconds of each kind (Q2).
  - The handler passes `timeline.is_playing()`, `timeline.get_current_time()` and `time.monotonic()`.
  - `wall_time` in `metadata.json` stays `time.time()` since the start.
- **`steps_per_frame` goes,** and with it its faults while playing:
  - an `fps` that doesn't divide the time codes: `fps=7` gave 7.5 frames per second of simulation, `25` gave 30, and
    anything above 30 gave 60;
  - a Kit app whose timeline steps by the measured time between updates (S4). Isaac Sim's apps step one time code an
    update (P1), so this second fault is for other Kit apps.

| Option | Why not |
|---|---|
| A: the description only | The stopped rate stays Kit's update rate divided by a number no user sets: 8.5 to 21 frames a second where 5 or 10 were asked (P2, the runs), and 5 on a 60-update Kit. The `fps=7` fault stays |
| C: the wall clock always | A simulation running faster or slower than real time spreads the frames unevenly in simulation time, differently on each machine. At `fps=5` here that is 0.5 s of simulation between frames (P1). A review reads frames against `sim_time` |
| D: a `clock` parameter | A schema change, a one-way door, for a choice B makes well without one |

### R1: `stop_recording` says what the frames span (Q2)

`/recording/stop` and `metadata.json` gain two fields, from the clock's totals:

- `simulation_seconds`: the simulation the recording played through;
- `idle_seconds`: the wall seconds it ran stopped or paused.

The server's answer becomes
`Stopped. 33 frames, 4.99s: 3.00 s of simulation played, 2.00 s stopped or paused -> recordings/rec_1`. The frame count
comes out near `fps` times the sum of the two, and an agent can check that for itself. An extension without the
fields gets today's line.

### R2: the docs say when frames show Kit's grid (Q3 A)

No code. `start_recording`'s description and `docs/TOOLS.md` say that frames taken while the simulation is stopped or
paused show Kit's grid, as the viewport does, and that Isaac Sim hides it while the simulation plays (S1, P3). Scenario
6.2's Verify line expects that.

The options Q3 weighed, with what the probe showed:

| Option | What it would take | Why not, now |
|---|---|---|
| B: the recording's texture turns its own gizmos off | The texture's own `gizmos/enabled` (S2), set when the feed is made. The name is the feed's own, so the key could be set before `create_hydra_texture` | Set while the texture renders, it only dims the grid, to 0.59 (P4). Set before the texture is made, it is unmeasured, and Kit writes the key itself when it makes the texture (S1's "true (Kit's)"), perhaps over one set before. That needs a second probe, and the key is one no doc names |
| C: the global `gizmos/enabled` off for the recording's span | One setting | It turns the grid off in the user's viewport and every capture, and Isaac Sim's throttling sets it back on at every pause and stop (S1) |
| D: captures too | | Out of scope: `capture_viewport` shows what the viewport would, and #105's warning on an unlit scene counts on its grid |

### R3: `get_logs` shows what a search matched (server, `tools/misc.py`; Q4, Q5)

The bridge's search stays as it is, over the whole message. P7's entry, searched for "MCP", would read as below,
with its paths shortened here:

```
  [INFO ] carb: `get_update_event_stream` is deprecated. Use Events 2.0. Callstack:   File "...\asyncio\events.py", line 88, in _run
    self._context.run(self._ ... (+695 characters)
    matched: ...File "c:/users/serio/appdata/local/temp/claude/d--workspaces-omniverse-mcp/.../ovmcp/bridge/...", line ...
```

- **A message longer than 200 characters** ends its shown part with `... (+N characters)`, whether or not the call
  searched.
- **With `search`,** an entry whose first match lies past the shown part gets a `matched:` line. That line is the line
  of the message holding the match, cut to 80 characters either side of it, with `...` marking each cut end. A match
  inside the shown part adds nothing.
- **The channel is shown whole** (Q5). A `channel` filter matches the whole name too, and the 40-character cut hid the
  part that tells modules apart (`isaacsim.core.experimental.utils.impl...`).
- `count`, the header, and writing a long answer to a file (`h.text_response`) stay as they are.

### Older extensions

- The server's `get_logs` change needs no extension.
- With a 0.3.0 extension, `stop_recording` answers today's line (no `simulation_seconds`) and frames come as today.
- With this release's extension, the new clock.
- A 0.3.0 server ignores the new answer fields.

### Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | What does `fps` count? | **A.** As now, said in the description: app updates over the stage's time codes. That is simulation time while playing, and Kit's update rate divided by a number while not. **B.** Simulation time while the timeline plays, the wall clock while it is stopped or paused, through a clock of the recording's own. **C.** The wall clock always. **D.** A `clock` parameter | B. Frames follow the simulation where things move, and the clock where nothing does. The probe's Kit gave 8.5 to 12.6 frames a second at `fps=5` while not playing (P2). B also fixes `fps` values that don't divide the time codes. The description says frames come faster than `fps` by the clock while a simulation runs faster than real time, 2.5 times on the probe's Kit (P1) | |
| Q2 | Should `stop_recording` say how much simulation and how much stopped time the frames span (`simulation_seconds`, `idle_seconds`, in the answer and `metadata.json`)? | **A.** Yes. **B.** No: `docs/TOOLS.md` explains the count | A. Under B the frame count still reads as wrong against the duration, which is what the tester flagged; two numbers make it checkable | |
| Q3 | Frame 0's grid: what changes? | **A.** Nothing in code: the docs say frames show Kit's grid while the simulation is stopped or paused, and Isaac Sim hides it while it plays. **B.** The recording's texture turns its own gizmos off, after a second probe shows that setting the key before the texture is made hides the grid. **C.** The global switch for the recording's span. **D.** Captures too | A. The probe shows the texture's own switch, set while it renders, dims the grid rather than hiding it (P4). B rests on an undocumented key and another Kit run. C changes the user's viewport and is undone by Isaac Sim at every pause and stop. The frames that show motion, those while playing, already have no grid on Isaac Sim (P3) | |
| Q4 | `get_logs`: a match the answer hides | **A.** Match only the 200 characters shown: a search for an exception's name, on a traceback's last line, then finds nothing. **B.** Match the whole message, as now, show the match on a `matched:` line, and mark every cut. **C.** Show whole messages when searching: a callstack runs to hundreds or thousands of characters | B. P7's hit sits at character 296 of 895 | |
| Q5 | `get_logs`: show the channel whole, not cut at 40? | Yes; or keep the cut | Yes. A channel is one short name, and the cut hides what the `channel` filter matched, R3's fault again | |
| Q6 | The bridge's three `get_update_event_stream()` subscriptions log Kit 110's deprecation, with a callstack, each time one is made: in the runs, for each recording and each feed released (P7) | **A.** A new issue: Events 2.0's `GLOBAL_EVENT_UPDATE`, with Kit 107 checked. **B.** In this change | A. The change touches `camera_feed.py` and `debug_draw.py`, beyond this issue; the first is in #114's way, and Kit 107 needs checking | |

## Compatibility

- **One-way doors:** none.
  - No tool's name, schema or annotations change: `tests/fixtures/mcp-tools.json` holds `fps` as an integer of at least
    1, default 5, and holds no descriptions.
  - The routes keep their paths and only gain answer fields, `simulation_seconds` and `idle_seconds`; `PROTOCOL`
    stays 1.
  - The output folder's layout, its files and their names, stays; `metadata.json` gains two keys.
- **What users notice,** under CHANGELOG's Changed and Fixed, each extension line saying it is the Kit extension's:
  - Fewer frames before play and while paused, on a Kit that runs more updates a second than the stage has time
    codes: `fps` frames a second by the clock, where the count was the update rate divided by a number.
  - While playing, frames are 1/`fps` s of simulation apart for every `fps`. They still come faster than `fps` by the
    clock wherever the simulation runs faster than real time, as now.
  - The first frame comes on the first update after the start, where it waited `steps` updates.
  - `stop_recording`'s line names the simulation and stopped seconds (Q2).
  - `get_logs` lines: a cut marked with its length, a `matched:` line for a hidden match, channels whole.
- **Kit apps:** the clock reads the timeline alone, so every Kit app gets it.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the runs read and the probe run by the session at 8212 on main's extension, both above | `111-probe.out.txt` in the session's scratchpad |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | R1: `FrameClock(fps)` in `core/recording.py`; `steps_per_frame` removed | `tests/test_recording.py` |
| 3 | R1: the handler ticks the clock with the timeline's state and time and `time.monotonic()`; Q2's fields in the stop answer and `metadata.json` | `tests/test_recording_handler.py` |
| 4 | R1, R2 and Q2 on the server: `start_recording`'s, `fps`'s and `stop_recording`'s descriptions, and the stop line | `tests/test_tools.py` |
| 5 | R3: `get_logs`' lines, the cut marker, `matched:`, the channel whole; its description | `tests/test_tools.py` |
| 6 | Docs, CHANGELOG, and scenarios 6.1, 6.2 and 24.3's Verify lines (Docs, below) | The gate's checks; `tests/test_contract.py` unchanged |
| 7 | The live tests below, run by the session on Isaac Sim 6.2 headless at 8212, then both suites whole; the AI scenarios' phases 6 and 24 | No failure beyond `main`'s on the same Kit |
| 8 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fix has a test that fails at `f5a27ed`; that test is named first.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_recording.py` | The clock, fed updates by hand. **Playing** at 1/60 s a step: `fps=5` takes a frame every 12 updates, and `fps=7` takes 70 frames in 600 updates (fails at `f5a27ed`: 75). **Stopped** at 120 updates a second by the clock: `fps=5` takes one every 24 updates (fails: 12). **Paused:** likewise. **Changes of state:** stopped, then play, then pause, the gaps stay 0.2 s of their own kind and no frame comes twice at a change. A step back in simulation time adds nothing. **Waits:** a frame held by a pending render comes on the next update that can take it; after a stall of several periods only one comes, and the next is due on the boundary after the clock; four in flight hold frames back, as now. **Numbers:** from 0, in order, whatever order frames end in. **Totals:** `simulated` and `idle` total each kind. The `steps_per_frame` test goes |
| `tests/test_recording_handler.py` | The fake timeline gains `is_playing`, and the fake Kit a clock the test moves. The existing "every few updates" and "no more than four in flight" tests move to it. A stopped recording at `fps=30` takes one frame per 1/30 s of fake time, whatever the updates between. The stop answer and `metadata.json` carry `simulation_seconds` and `idle_seconds` |
| `tests/test_tools.py` | `stop_recording` prints the two seconds when the answer has them, and today's line when it doesn't. `get_logs` (each case fails at `f5a27ed`): **a long message:** 2,545 characters with its match at 2,000 prints its first 200, `... (+2,345 characters)`, and a `matched:` line holding the match in its original case; **a match within the first 200** adds no line; **no `search`** adds no line but keeps the marker; **200 characters or fewer:** no marker; **a 50-character channel** is shown whole |

**Live (`tests/test_scenarios.py`, run by the session on Isaac Sim 6.2 at 8212, Y-up and Z-up):**

| Test | What |
|---|---|
| `test_06_10_frames_follow_the_clock_stopped_and_the_simulation_playing` (new) | `fps=5` from `/World/RecCam`: 1.2 s stopped, 1.2 s playing, 1.0 s paused. In `metadata.json`: the frames before play are 0.2 s apart by `wall_time` (median, within 0.05); those while playing are 0.2 s apart in `sim_time` (median, within 1/60); the paused ones are 0.2 s apart by `wall_time`. `simulation_seconds` is the simulation played, within one frame, and `idle_seconds` is about 2.2. Fails at `f5a27ed` on a Kit faster than 60 updates a second, as the probe's (P2) |
| `test_06_01` to `test_06_09`, `test_07_*` | Pass as they are: no test counts frames against `fps` |
| `test_24_*` | Unchanged: the bridge's search is unchanged |

The AI scenarios' phases 6 and 24 (`uv run tools/scenarios.py run --phases 6,24`) show the Verify lines below hold.

## Docs

| File | What changes |
|---|---|
| `docs/TOOLS.md` | **`start_recording`, "When frames come":** the recording's clock, simulation time while playing and wall clock while not; at most one frame an update; frames faster than `fps` by the clock while a simulation runs faster than real time; Kit's grid in frames taken while stopped or paused, gone while playing on Isaac Sim. **`stop_recording`, Returns:** the two seconds. **`get_logs`:** the cut marker, the `matched:` line, channels whole |
| `docs/ARCHITECTURE.md` | Recording System, step 2: the clock in place of `steps_per_frame` |
| `src/omniverse_mcp/tools/recording.py`, `tools/misc.py` | The descriptions of `start_recording` (the clock, and a clause on the grid) and `fps`; of `stop_recording`; of `get_logs` |
| `test_project/scenarios.md` | **6.1:** a Verify line on `metadata.json`'s gaps before and during play, and on the stop answer's seconds. **6.2:** frames taken before play may show Kit's grid; on Isaac Sim, those while playing don't. **24.3:** each entry shows the word searched for, in its text or on its `matched:` line |
| `CHANGELOG.md` | Under Unreleased: Changed, the clock and the stop line (the Kit extension's, and the server's); Fixed, `get_logs`' hidden match and cut channels (the server's) |
| `README.md`, `plugin/skills/simulate/SKILL.md`, `docs/AI_GUIDE.md` | None: none states when frames come or how `get_logs` prints |

## Risks

| Risk | Status |
|---|---|
| A Kit slower than `fps` while stopped takes at most one frame an update | Accepted, as now. The clock skips the boundaries it passed, so frames are fewer, never bunched. TOOLS.md says so |
| A forward jump in simulation time while playing (a time set by hand) adds the jump: one frame, then the next boundary after the clock | Accepted: no burst, and a jump is rare while playing |
| The first frame now comes on the first update, perhaps before the feed's frame settles | Resolved. The start already waits for the feed's first frame (`first_frame`), and frames come from a feed rendering every update (#25's E23). Frames 0 and 1 matched to the pixel (P5) |
| Frames still come faster than `fps` by the clock while a simulation runs faster than real time, 2.5 times on the probe's Kit; a tester may flag it again | Accepted by design (Q1 B). The description, TOOLS.md, the stop line (Q2) and scenario 6.1's Verify line say so |
| The grid in frames taken while stopped or paused is Kit's, and its state depends on the app: Isaac Sim's throttling turns it off while playing, other Kit apps don't | Accepted (Q3 A). The docs say which frames show it on Isaac Sim, and that elsewhere they show what the viewport does |

## Plan review

Not reviewed yet.
