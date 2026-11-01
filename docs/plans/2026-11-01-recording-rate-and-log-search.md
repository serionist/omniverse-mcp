---
title: Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched
issue: "#111"
status: approved
approved_by: serionist
approved_at: 2026-11-01
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
| R2 | 6.1 | `start_recording` | The description and `docs/TOOLS.md` say that frames taken while the simulation is stopped or paused show Kit's grid, as the viewport does, and that Isaac Sim 6.2 hides it while the simulation plays. Scenario 6.2's Verify line expects that (Q3 A) | The probe; scenario 6.2 |
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
| | The bridge's own `get_update_event_stream` calls, which Kit 110 logs as deprecated with a callstack: #122 (Q6) |
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
| P3 | S1's and Z's frames show the grid (15,204 pixels above 5, the brightest 137; frames 0 and 63 seen). P's show nothing: 0 pixels. The global switch read false in P and true in S1 and Z. The counts above 5 and the brightest pixel come from the session's `cmp_frames.py`, whose output wasn't saved; the lit counts above 20 are in `111-probe.out.txt` | S1 holds: the grid follows the timeline. Paused frames show it as stopped ones do |
| P4 | In S2 the grid stayed. 12,682 pixels were still above 5, at 0.59 of S1's brightness on the same pixels (frame 13 seen: every line still there, dimmer). The capture taken during S2 was S1's frame to the pixel (15,204 above 5, the same sum). The 12,682, the 0.59 and the sums come from `cmp_frames.py`, as P3's do | The texture's own switch, set while the texture renders, dims the grid and doesn't hide it. It touches that texture alone. Whether it hides the grid when set before the texture's first frame is not measured (Q3) |
| P5 | Frames 0 and 1, and every pair in S1, are identical (difference 0.0). Frame 0 came 0.18 s after the start, frame 1 0.24 s later and frame 2 0.28 s after that, then 0.11 s, then one every 0.07 to 0.1 s | No first-frame fault, as in the runs. The longer first gaps are Kit updating more slowly just after the start: about 45 updates a second over the first 0.7 s, at 12 updates a frame, against 105 over S1 and 150 later |
| P6 | After the stop, Kit still holds the texture's settings: `updatesEnabled` false, `cameraPath`, `width`, `height`, `gizmos.enabled` true and the rest | Kit keeps every texture's settings after it goes, captures' included. That is Kit's own behaviour, and none of the keys is the bridge's |
| P7 | A deprecation entry, whole: 895 characters. Its first 200 end inside the callstack's second line, and the first "mcp" is at character 296. That is in the next frame of the callstack, the bridge's own file, whose path here holds "omniverse-mcp" (the session loads the extension from a folder of that name) | R3: the match lies past the cut, in the bridge's own frame of the callstack. Q6: the deprecation comes from the bridge's own call |

The probe restored the texture's own switch before playing and deleted `/World/ProbeCam`. Kit's settings afterwards
equal those before, except `/app/viewport/grid/plane`, `XY` before and `XZ` after: Kit turns its grid to the new
stage's Y up axis.

## Design

### R1: the recording's own clock (`core/recording.py`, `handlers/recording.py`; Q1)

- **`FrameClock(fps)`** keeps a clock of the recording's own, in seconds. Each update adds:
  - while the timeline plays and its time moves forward, the simulation time it advanced since the update before;
  - otherwise the wall time since then (`time.monotonic()`): while it is stopped or paused, or plays a timeline whose
    time doesn't move forward (P2).

  Frame k is due once that clock reaches k/`fps`, frame 0 on the first update after the start.
- **The start** waits, as now, for the feed's first frame, then for `capture.settle_frames(...)` more of its frames,
  as `capture_viewport` does, and only then subscribes to updates (P1).
  - That is no frame under RT 2.0, nor under Path Tracing with Isaac Sim's 64 samples a frame of 64.
  - Under Path Tracing at a lower `spp`, it is the frames still owed their samples, so frame 0 is converged as a
    capture is.
  - It goes in `_start`'s `try`, after `first_frame`, with `feed.wait_frames`' bounds: a feed that stalls fails the
    start and leaves nothing, as a first frame that never comes does.
- **A due frame waits** while the feed awaits the last frame's render or four frames are in flight, as now. It is
  taken on the first update that can take it.
  - The next frame is due at the first period boundary after the clock at which this one was taken: one period later
    for a frame on time. Frames that a stall made late are dropped, never sent in a burst.
  - A tolerance of a millionth of a period lets twelve steps of 1/60 s add up to 0.2 s.
- **Numbers** are given when a frame is taken, from 0, never twice, as now (#69).
- **State changes need no case of their own:**
  - the first update of play adds its simulation step;
  - the first paused or stopped update adds the wall time since the last; a stop, which rewinds, is such an update;
  - a playing update whose simulation time doesn't move forward adds its wall time, as a stopped one does (P2). A
    loop at the end time and a time set back by hand each cost one update's wall time. A timeline that plays over a
    single frame gets a frame every 1/`fps` s by the clock, as a stopped one does: Isaac Sim warns on play "Timeline
    playback will loop over a single frame" for a file whose root layer authors no time-code range, and its time
    never moves while PhysX may still step.
- **`tick(playing, sim_time, now, render_pending)`** returns the frame's number or None. `simulated` and `idle` total
  the seconds of each kind (Q2): the simulation time added, and the wall time added.
  - The handler passes `timeline.is_playing()`, `timeline.get_current_time()` and the monotonic clock, which it reads
    through a name of its own, `_monotonic`, so its tests can move it without moving asyncio's.
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
- `idle_seconds`: the wall seconds it ran while the simulation didn't move forward: stopped, paused, or playing a
  timeline whose time doesn't move (P2).

The server's answer becomes
`Stopped. 33 frames, 4.99s: 3.00 s of simulation played, 2.00 s stopped or paused -> recordings/rec_1`. The frame count
comes out near `fps` times the sum of the two, and an agent can check that for itself. An extension without the
fields gets today's line.

### R2: the docs say when frames show Kit's grid (Q3 A)

No code. `start_recording`'s description and `docs/TOOLS.md` say that frames taken while the simulation is stopped or
paused show Kit's grid, as the viewport does, and that Isaac Sim 6.2 hides it while the simulation plays (S1, P3).
Isaac Sim's throttling has switched the grid with play since its 2.1.0 (2025-05-02), but no run checked 5.x, so the
docs name 6.2. Scenario 6.2's Verify line expects that.

The options Q3 weighed, with what the probe showed:

| Option | What it would take | Why not, now |
|---|---|---|
| B: the recording's texture turns its own gizmos off | The texture's own `gizmos/enabled` (S2), set when the feed is made. The name is the feed's own, so the key could be set before `create_hydra_texture` | Set while the texture renders, it only dims the grid, to 0.59 (P4). Set before the texture is made, it is unmeasured, and Kit writes the key itself when it makes the texture (S1's "true (Kit's)"), perhaps over one set before. That needs a second probe, and the key is one no doc names |
| C: the global `gizmos/enabled` off for the recording's span | One setting | It turns the grid off in the user's viewport and every capture, and Isaac Sim's throttling sets it back on at every pause and stop (S1) |
| D: captures too | | Out of scope: `capture_viewport` shows what the viewport would, and #105's warning on an unlit scene counts on its grid |

### R3: `get_logs` shows what a search matched (server, `tools/misc.py`; Q4, Q5)

The bridge's search stays as it is, over the whole message. P7's entry, searched for "MCP", would read as below, its
first path shortened and its second invented (an extension folder of `c:/users/ada/kit/exts/omniverse-mcp`):

```
  [INFO ] carb: `get_update_event_stream` is deprecated. Use Events 2.0. Callstack:   File "...\asyncio\events.py", line 88, in _run
    self._context.run(self._ ... (+695 characters)
    matched: File "c:/users/ada/kit/exts/omniverse-mcp/extension/ovmcp.bridge/ovmcp/bridge/handlers/camera_feed.py", line 161, in add
```

- **A message longer than 200 characters** ends its shown part with ` ... (+N characters)`, N the characters cut,
  grouped by commas: `(+695 characters)`, `(+2,345 characters)`. It does so whether or not the call searched.
- **With `search`,** an entry whose first match doesn't end within the shown part gets a `matched:` line (P3): a match
  that starts at character 199 shows only its first character, which doesn't count. That line is the line of the
  message holding the match, cut to 80 characters either side of it, with `...` marking each cut end. A match that
  ends inside the shown part adds nothing.
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
| Q1 | What does `fps` count? | **A.** As now, said in the description: app updates over the stage's time codes. That is simulation time while playing, and Kit's update rate divided by a number while not. **B.** Simulation time while the timeline plays, the wall clock while it is stopped or paused, through a clock of the recording's own. **C.** The wall clock always. **D.** A `clock` parameter | B. Frames follow the simulation where things move, and the clock where nothing does. The probe's Kit gave 8.5 to 12.6 frames a second at `fps=5` while not playing (P2). B also fixes `fps` values that don't divide the time codes. The description says frames come faster than `fps` by the clock while a simulation runs faster than real time, 2.5 times on the probe's Kit (P1) | B (serionist, 2026-11-01) |
| Q2 | Should `stop_recording` say how much simulation and how much stopped time the frames span (`simulation_seconds`, `idle_seconds`, in the answer and `metadata.json`)? | **A.** Yes. **B.** No: `docs/TOOLS.md` explains the count | A. Under B the frame count still reads as wrong against the duration, which is what the tester flagged; two numbers make it checkable | A (serionist, 2026-11-01) |
| Q3 | Frame 0's grid: what changes? | **A.** Nothing in code: the docs say frames show Kit's grid while the simulation is stopped or paused, and Isaac Sim hides it while it plays. **B.** The recording's texture turns its own gizmos off, after a second probe shows that setting the key before the texture is made hides the grid. **C.** The global switch for the recording's span. **D.** Captures too | A. The probe shows the texture's own switch, set while it renders, dims the grid rather than hiding it (P4). B rests on an undocumented key and another Kit run. C changes the user's viewport and is undone by Isaac Sim at every pause and stop. The frames that show motion, those while playing, already have no grid on Isaac Sim (P3) | A, the docs saying "on Isaac Sim 6.2" (serionist, 2026-11-01) |
| Q4 | `get_logs`: a match the answer hides | **A.** Match only the 200 characters shown: a search for an exception's name, on a traceback's last line, then finds nothing. **B.** Match the whole message, as now, show the match on a `matched:` line, and mark every cut. **C.** Show whole messages when searching: a callstack runs to hundreds or thousands of characters | B. P7's hit sits at character 296 of 895 | B (serionist, 2026-11-01) |
| Q5 | `get_logs`: show the channel whole, not cut at 40? | Yes; or keep the cut | Yes. A channel is one short name, and the cut hides what the `channel` filter matched, R3's fault again | Yes (serionist, 2026-11-01) |
| Q6 | The bridge's three `get_update_event_stream()` subscriptions log Kit 110's deprecation, with a callstack, each time one is made: in the runs, for each recording and each feed released (P7) | **A.** A new issue: Events 2.0's `GLOBAL_EVENT_UPDATE`, with Kit 107 checked. **B.** In this change | A. The change touches `camera_feed.py` and `debug_draw.py`, beyond this issue; the first is in #114's way, and Kit 107 needs checking | A: #122, "Move the bridge's update subscriptions off Kit's deprecated get_update_event_stream" (serionist, 2026-11-01) |

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
  - The first frame comes on the first update after the start, where it waited `steps` updates. The start waits for
    the feed's first frame, as now, and under Path Tracing for the samples a capture waits for.
  - `stop_recording`'s line names the simulation and stopped seconds (Q2).
  - `get_logs` lines: a cut marked with its length, a `matched:` line for a hidden match, channels whole.
- **Kit apps:** the clock reads the timeline alone, so every Kit app gets it.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the runs read and the probe run by the session at 8212 on main's extension, both above | `111-probe.out.txt` in the session's scratchpad |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | R1, in one commit so `tests/test_recording_handler.py` never breaks between them: `FrameClock(fps)` in `core/recording.py`, `steps_per_frame` removed; the handler ticks the clock with the timeline's state and time and `_monotonic()`, waits the settle frames before it subscribes, and puts Q2's fields in the stop answer and `metadata.json` | `tests/test_recording.py`, `tests/test_recording_handler.py` |
| 3 | R1, R2 and Q2 on the server: `start_recording`'s, `fps`'s and `stop_recording`'s descriptions, and the stop line | `tests/test_tools.py` |
| 4 | R3: `get_logs`' lines, the cut marker, `matched:`, the channel whole; its description | `tests/test_tools.py` |
| 5 | Docs, CHANGELOG, and scenarios 6.1, 6.2 and 24.3's Verify lines (Docs, below) | The gate's checks; `tests/test_contract.py` unchanged |
| 6 | The live tests below, run by the session on Isaac Sim 6.2 headless at 8212, then both suites whole; the AI scenarios' phases 6 and 24 | No failure beyond `main`'s on the same Kit |
| 7 | `finish-work`: the gate in full, `review-code`; the PR names #122 as Q6's follow-up | |

## Tests

Each fix has a test that fails at `f5a27ed`; that test is named first.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_recording.py` | The clock, fed updates by hand. **Playing** at 1/60 s a step: `fps=5` takes a frame every 12 updates, and `fps=7` takes 70 frames in 600 updates (fails at `f5a27ed`: 75). **Stopped** at 120 updates a second by the clock: `fps=5` takes one every 24 updates (fails: 12). **Paused:** likewise. **Changes of state:** stopped, then play, then pause, the gaps stay 0.2 s of their own kind and no frame comes twice at a change. **A timeline that plays and doesn't move** (P2, fails under the plan as first written: one frame): playing with the simulation time held, at 120 updates a second by the clock, `fps=5` takes one every 24 updates, counted in `idle`; a step back while playing adds that update's wall time. **Waits:** a frame held by a pending render comes on the next update that can take it; after a stall of several periods only one comes, and the next is due on the boundary after the clock; four in flight hold frames back, as now. **Numbers:** from 0, in order, whatever order frames end in. **Totals:** `simulated` and `idle` total each kind. The `steps_per_frame` test goes |
| `tests/test_recording_handler.py` | The fake timeline gains `is_playing`, and the fake Kit a clock the test moves, which the handler reads through its module's `_monotonic`: asyncio's loop keeps the real `time.monotonic`. The existing "every few updates" and "no more than four in flight" tests move to it. A stopped recording at `fps=30` takes one frame per 1/30 s of fake time, whatever the updates between. The stop answer and `metadata.json` carry `simulation_seconds` and `idle_seconds`. **The settle** (P1): with frames owed under Path Tracing, the start waits that many of the feed's frames after its first and only then subscribes; with none owed it waits none; a settle that fails leaves nothing, as a first frame that never comes does |
| `tests/test_tools.py` | `stop_recording` prints the two seconds when the answer has them, and today's line when it doesn't. `get_logs` (each case fails at `f5a27ed`): **a long message:** 2,545 characters with its match at 2,000 prints its first 200, ` ... (+2,345 characters)`, and a `matched:` line holding the match in its original case; **a match starting at character 199** (P3) gets a `matched:` line; **a match ending within the first 200** adds no line; **no `search`** adds no line but keeps the marker; **200 characters or fewer:** no marker; **a 50-character channel** is shown whole |

**Live (`tests/test_scenarios.py`, run by the session on Isaac Sim 6.2 at 8212, Y-up and Z-up):**

| Test | What |
|---|---|
| `test_06_10_frames_follow_the_clock_stopped_and_the_simulation_playing` (new) | `fps=5` from `/World/RecCam`: 1.2 s stopped, 1.2 s playing, 1.0 s paused. In `metadata.json`: the frames before play are 0.2 s apart by `wall_time` (median, within 0.05); those while playing are 0.2 s apart in `sim_time` (median, within 1/60); the paused ones are 0.2 s apart by `wall_time`. `simulation_seconds` is the simulation played, within one frame, and `idle_seconds` is about 2.2. Fails at `f5a27ed` on a Kit faster than 60 updates a second, as the probe's (P2). **Frame 0** (P1): the scene is lit and still before play, and frame 0 against frame 1 is within one grey level, a mean absolute difference under 1 of 255. #51's E14 put a new feed's first frame 0.21 to 0.24 from a settled one; #111's grid made 6 to 8 |
| `test_06_01` to `test_06_09`, `test_07_*` | Pass as they are: no test counts frames against `fps` |
| `test_24_*` | Unchanged: the bridge's search is unchanged |

The AI scenarios' phases 6 and 24 (`uv run tools/scenarios.py run --phases 6,24`) show the Verify lines below hold.

## Docs

| File | What changes |
|---|---|
| `docs/TOOLS.md` | **`start_recording`, "When frames come":** the recording's clock, simulation time while playing and wall clock while not; at most one frame an update; frames faster than `fps` by the clock while a simulation runs faster than real time; Kit's grid in frames taken while stopped or paused, gone while playing on Isaac Sim 6.2. **`stop_recording`, Returns:** the two seconds, the second counting a playing timeline whose time doesn't move. **`get_logs`:** the cut marker, the `matched:` line, channels whole |
| `docs/ARCHITECTURE.md` | Recording System, step 2: the clock in place of `steps_per_frame` |
| `src/omniverse_mcp/tools/recording.py`, `tools/misc.py` | The descriptions of `start_recording` (the clock, and a clause on the grid) and `fps`; of `stop_recording`; of `get_logs` |
| `test_project/scenarios.md` | **6.1:** a Verify line on `metadata.json`'s gaps before and during play, and on the stop answer's seconds. **6.2:** frames taken before play may show Kit's grid; on Isaac Sim 6.2, those while playing don't. **24.3:** each entry shows the word searched for, in its text or on its `matched:` line |
| `CHANGELOG.md` | Under Unreleased: Changed, the clock and the stop line (the Kit extension's, and the server's); Fixed, `get_logs`' hidden match and cut channels (the server's) |
| `README.md`, `plugin/skills/simulate/SKILL.md`, `docs/AI_GUIDE.md` | None: none states when frames come or how `get_logs` prints |

## Risks

| Risk | Status |
|---|---|
| A Kit slower than `fps` while stopped takes at most one frame an update | Accepted, as now. The clock skips the boundaries it passed, so frames are fewer, never bunched. TOOLS.md says so |
| A forward jump in simulation time while playing (a time set by hand) adds the jump: one frame, then the next boundary after the clock | Accepted: no burst, and a jump is rare while playing |
| The first frame now comes on the first update after the start: the feed's second or third render, where today it is about the 13th at `fps=5`, the 3rd at `fps=30` and the 2nd at `fps` of 31 or more | Accepted (P1). #51's E14 measured a new feed's first capture against its own 100 updates later at 0.21 to 0.24 of 255 under RT 2.0, against 0.07 between settled ones: about three times the settled noise, a fraction of one grey level, which #51 judged no reader sees. `capture_viewport` already ships that render under RT 2.0, where `capture.settle_frames` is 0, and today's recordings at `fps` of 31 or more already take it as frame 0. It sits against #25's R12, which turned down rendering on demand for frames about four times the settled noise; that was for every frame, this is frame 0 alone. Path Tracing below its total samples, the one mode where it would show, gets the settle frames before the first update (Design R1). `test_06_10` compares frame 0 with frame 1 in a lit still scene |
| A timeline that plays over a single frame (a file with no time-code range) | Accepted (P2): its updates add wall time, so frames come by the clock as when stopped, and `idle_seconds` counts them. TOOLS.md says so |
| Frames still come faster than `fps` by the clock while a simulation runs faster than real time, 2.5 times on the probe's Kit; a tester may flag it again | Accepted by design (Q1 B). The description, TOOLS.md, the stop line (Q2) and scenario 6.1's Verify line say so |
| The grid in frames taken while stopped or paused is Kit's, and its state depends on the app: Isaac Sim 6.2's throttling turns it off while playing, other Kit apps don't, and 5.x is unchecked | Accepted (Q3 A). The docs say which frames show it on Isaac Sim 6.2, and that elsewhere they show what the viewport does |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, read only, 2026-11-01, on `e873d54`; its one major went to a fresh refuter,
who confirmed it in part, as a minor. **Verdict:** approved: no blocker or major open, three minors; no further round.
**Now:** P1 to P3 fixed, the three probe readings corrected and improvements 1 to 5 taken, in the commit after
`e873d54`. The maintainer answered Q1 to Q6 as recommended (2026-11-01).

Checked and holding: the Kit facts S1 to S4 match Isaac Sim 6.2's install, and the probe reads as the plan says but
for three small points (Refuted, last).

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor (reported major; the refuter confirmed it in part, as a minor) | Design R1's "frame 0 on the first update" and the Risks row "Resolved". Under the new clock frame 0 comes on the first update after `first_frame`, which waits only for the feed's first render (`camera_feed.py:114`, `n > 0`; `_start` subscribes after it, `handlers/recording.py:141`, `:159`), so frame 0 is the feed's second or third render. Today `FrameClock` takes it on update `steps`: about the 13th render at `fps=5`, the 3rd at `fps=30`, already the 2nd at `fps` of 31 or more. The row rested on P5, an unlit empty stage (`111-probe.py:18`) whose frame 0 came 0.18 s in under the old clock, and on #25's E23, which measured a feed rendered on demand, not an always-on feed's second render. #51's E14 measures it directly (`docs/plans/2026-10-30-capture-at-the-size-asked-for.md:102`, RT 2.0, mean absolute difference out of 255): a new feed's first capture against its own 100 updates later, 0.21 to 0.24, and 0.07 from 100 to 130. That is about three times the settled noise and a fraction of one grey level, which #51 judged no reader of a 640x480 image sees (line 152); `capture.settle_frames` is 0 outside Path Tracing, so every `capture_viewport` under RT 2.0 already ships that render. It isn't #111's symptom: the grid and shadow, 0.0235 to 0.0318 as a share of 255, came from Isaac Sim switching the grid with play. The real edge is Path Tracing with `spp` below `totalSpp`, where frame 0 would hold two frames' samples against about twelve today | fixed: the Risks row is "Accepted", citing E14 in place of E23 and P5, saying `capture_viewport` and today's recordings at `fps` of 31 or more already take this render, and naming the tension with #25's R12. The optional settle is taken: `_start` waits `feed.wait_frames(capture.settle_frames(...))` before it subscribes, which covers Path Tracing at a low `spp` and costs nothing under RT 2.0 or Isaac Sim's 64 of 64 (Design R1; a `test_recording_handler.py` case). `test_06_10` compares frame 0 with frame 1 in a lit still scene (Tests) |
| P2 | minor | Design R1's "a step back in simulation time adds nothing". Open a USD whose root layer authors no time-code range and record while playing: Isaac Sim 6.2's throttling 2.3.7 warns on play "Timeline playback will loop over a single frame", the timeline's time never moves forward, so each update adds nothing, and the recording takes frame 0 and nothing more while PhysX may keep stepping (not measured); today's clock takes one every 12 updates. New stages get [0, 1000000] (`isaacsim.exp.base.kit:257`); an opened file keeps its own range (throttling's `extension.py`, `_on_play`) | fixed: a playing update whose simulation time doesn't move forward adds its wall time, which `idle_seconds` counts; a normal loop or a time set back then costs one update's wall time (Design R1, Q2's fields, Risks; a `test_recording.py` case) |
| P3 | minor | Design R3's "an entry whose first match lies past the shown part". With `search="MCP"`, a match starting at character 199 shows only "M": it starts within the shown part, so it gets no `matched:` line | fixed: a match counts as shown only when it ends within the 200 characters (Design R3; a `test_tools.py` case) |

**Refuted:**

- Q2 breaks the output folder's one-way door: the layout is its folders and file names; two keys added to
  `metadata.json` change neither, and Compatibility names them.
- The tool contract: unchanged. `tools/golden.py` strips `PROSE = {"description", "title"}`; `fps` stays an integer
  of at least 1, default 5; every output is a string.
- Step 2 can't pass the gate while the handler still imports `steps_per_frame`: basedpyright excludes
  `ovmcp/bridge`, gate quick runs no pytest, and the branch is squash-merged. Improvement 5 joins the two steps
  anyway.
- An `fps` that doesn't divide 60, or above 60: "at most one frame an update", the period boundaries and the `fps=7`
  test (70 frames in 600 updates) cover it.
- Late frames in a burst: the next frame is due at the first period boundary ahead of the clock, and a test covers it.
- The changes of state at play, pause and stop: only one update's delta can be misread at each; `sim_control`'s step
  plays two updates (`simulation.py:53-57`), so `is_playing()` holds while it steps.
- The cost on Kit's main thread: three cheap reads an update, beside `_why_frames_stop`'s stage read.
- The logs answer's length: `h.text_response` writes a long answer to a file.
- An older extension's `/logs`: the same entry keys; the change is the server's alone.
- Case: "the match in its original case" fits `core/logs.py`'s case-blind `.lower()` rule.
- The writing rules: clean.
- How the plan reads the probe: right, but for three small points, each now corrected. P5's gaps: frame 1 to 2 was
  0.28 s and 2 to 3 0.11 s, not "then one every 0.07 to 0.1 s". P5's reason: Kit ran about 45 updates a second over
  the first 0.7 s, not S1's 105. P3's and P4's 15,204, 12,682, 0.59 and 137 came from `cmp_frames.py`, whose output
  wasn't saved: both rows now say so. The Kit facts S1 to S4 check out.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 to Q6 | Decisions for the maintainer | The reviewer agrees with each. Q1 B, once P1 and P2 are fixed. Q2 A: additive, and it makes the frame count checkable. Q3 A is honest: P3 shows the global switch false only while playing, P4 the texture's own switch only dimming the grid, to 0.59; throttling has switched the grid since its 2.1.0 (2025-05-02), but 5.x was never checked, so the docs say "on Isaac Sim 6.2" or 5.x is checked. Q4 B, with P3. Q5 yes. Q6 A, with a step for its issue | As recommended: Q1 B, Q2 A, Q3 A with "on Isaac Sim 6.2", Q4 B, Q5 yes, Q6 A as #122 (serionist, 2026-11-01) |

**Improvements:**

1. A step for Q6's issue (Events 2.0 for `camera_feed.py:161`, `recording.py:161`, `debug_draw.py:184`), named in the
   PR: taken. The issue is filed, #122, "Move the bridge's update subscriptions off Kit's deprecated
   get_update_event_stream"; Out of scope, Q6 and step 7 name it, and the PR does.
2. The R3 example quoted the maintainer's real path: taken, an invented one.
3. The handler tests inject the clock, not patch `time.monotonic`, which asyncio's loop also reads: taken. The handler
   reads it through its module's `_monotonic`, which the tests move (Design R1, Tests).
4. The cut marker's exact text pinned: taken, ` ... (+N characters)`, N grouped by commas, as in `(+695 characters)`
   and `(+2,345 characters)` (Design R3, Tests).
5. Steps 2 and 3 in one commit, so `tests/test_recording_handler.py` isn't broken between them: taken (Steps).
