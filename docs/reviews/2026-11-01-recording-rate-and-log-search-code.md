---
subject: "Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched (#111)"
base: main (84acfa5)
head: 8c5af7a
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only, every lens, with offline checks of the clock and get_logs; one minor, so no second round"
verdict: needs-fixes
---

# Review: Time recording frames by the simulation while it plays and by the clock while not, and show what a log search matched

Read from the branch's diff against `main`: `ovmcp/core/recording.py` (`FrameClock`), `handlers/recording.py` (the
settle, the clock's inputs, `_spans`), `src/omniverse_mcp/tools/recording.py` and `tools/misc.py` (`get_logs`' lines),
the unit and live tests, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `test_project/scenarios.md` and CHANGELOG, against
the approved plan `docs/plans/2026-11-01-recording-rate-and-log-search.md` (Q1 B, Q2 A, Q3 A, Q4 B, Q5 yes, Q6 A as
#122). The reviewer ran the clock and `get_logs`' formatting offline against the branch's code.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/recording.py`, `_start` (lines 148-150) | A slow settle under Path Tracing fails a start that worked on `main`. With `spp=1` and `totalSpp` of 256 or more, `settle_frames` gives its cap of 255 frames, which Kit must render faster than about 8.5 updates a second; with Kit's default 1/64 it is 63 frames, failing below about 2 a second, at 4096 a side say. `wait_frames(settle)` runs `capture.frames(..., budget=None)`, whose shared `Budget(FRAME_SECONDS)` runs out, and `start_recording` fails with "The 30 s this call may take ran out" and no advice. `first_frame` has already shown the feed renders, so the settle only polishes frame 0. An offline check raised `OutOfTimeError` | fixed in `163801e`: `capture.OutOfTimeError` from the settle is logged and the recording starts; `NoFrameError`, a feed that stalls, still fails it. `test_a_settle_that_runs_out_of_time_starts_anyway`; the stalled case is `test_a_settle_whose_frame_never_comes_is_an_error_that_leaves_nothing` |

Refuted:
- **Unicode case** between the bridge's `.lower()` and the server's `re.IGNORECASE`: they agree on İ, ǅ, ﬃ and ß.
- **The tool contract:** unchanged; `golden.contract()` equals `tests/fixtures/mcp-tools.json`.
- **The output folder's one-way door:** `handle_recording_frame` reads only `meta.get("frames", [])`, and nothing else
  parses `metadata.json`'s top level, so two keys more change nothing it reads.
- **The clock's rates,** each run offline:
  - `fps` 7, 25 and 45 give 70, 250 and 450 frames;
  - 120 gives one an update, and 10 updates a second at `fps=30` one an update;
  - a 0.5 s loop gives 50 frames, a single-frame loop 10 in 2 s;
  - a stall gives one late frame;
  - frame 0 comes on the first update, and `_monotonic` is the only time source.
- **`get_logs`' edges:**
  - a match at the end, at a line's start and mid-line;
  - a multiline message shows the matching line;
  - the original case is kept;
  - `(+N characters)` is `len(msg) - 200`, grouped by commas;
  - a match ending at 200 adds no line, one ending at 202 does;
  - a `None` channel prints empty;
  - a long answer goes through `text_response`.
- **An older extension** prints today's stop line, pinned by a test.
- **The settle's place:** inside `_start`'s `try`, before the closed and stage checks; a settle that fails discards
  the feed; it takes no lock another start shares.
- **`test_06_10`:**
  - it holds on Z-up and Y-up, and cleans up;
  - `[1:-1]` drops the pairs that straddle play and pause;
  - frame 0 against frame 1, both stopped, is about 0.24 of 255 against a threshold of 1.0;
  - it fails on `main`.
- **The unit tests** fail on `main`, but for the regression guards.
- **The harness, the writing rules and CHANGELOG:** clean.

Improvements:
- **`_settle_frames` into `handlers/_utils.py`,** which `camera.py` and `recording.py` already import, dropping the
  recording handler's import of a private name from the camera handler and the tests' fake `handlers_under_test.camera`
  module: taken, in `163801e`; `test_camera_handler.py`'s fake `_utils` gains it.
- **A live check of `simulation_seconds` after `sim_control('step')` calls, and the clock or the fake made to match
  Kit's order:** taken, in `3456e03`.
  - In the handler's fake, the recording's callback runs before the timeline moves. A step, two updates playing and
    then a pause, so showed its second advance only on the update after the pause, which the clock counted as idle,
    since it read `is_playing()`. The reviewer's model gave 10 steps of 2/60 s as 0.167 s.
  - Kit's real order wasn't known here, so the clock now reads the time alone: any forward move is simulation, any
    other update wall time. A step counts whole whichever side of Kit's timeline tick the recording's update runs on.
  - Tested by `test_each_step_counts_whole_as_simulation_whichever_order_kit_ticks_in` (both orders) and
    `test_each_step_a_recording_spans_counts_as_simulation` (the handler). Live, `test_06_11_steps_count_as_simulation`
    takes 10 steps and compares `simulation_seconds` with the timeline's time.
  - One effect beyond the plan: a time set forward by hand while paused or stopped now counts as simulation, as one set
    while playing already did. It gives one frame, then the next boundary after the clock, and no burst (the plan's
    Risks row on forward jumps).

## Live run

Run by the session on its own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows, at port 8212. `105-stage.py` set the
stage's up axis before each step. "The changed tests" are `test_scenarios.py -k "test_02_01 or test_04_05 or test_06
or test_07 or test_24"` and `test_integration.py -k test_24_get_logs`.

| Step | Extension | Stage | What ran | Result |
|---|---|---|---|---|
| 1 | `8c5af7a` | Z-up | the changed tests | 21 passed; 1 passed. `test_06_10`: 19 frames, median gaps 0.202 s by the clock stopped, 0.200 s of simulation playing, 0.204 s by the clock paused; 1.33 s simulated, 2.28 s idle; frame 0 against frame 1 0.615 of 255 |
| 2 | `8c5af7a` | Y-up | the changed tests | Kit hung in `test_06_04`, a recording test from before this change, and the suites' guard stopped the run (#54): #114's hang family. Superseded by step 3 |
| 3 | `85c1677` | Y-up | the changed tests | 22 passed; 1 passed. `test_06_10`: 20 frames, median gaps 0.203 s stopped, 0.200 s of simulation playing, 0.195 s paused; 1.6 s simulated, 2.23 s idle; frame 0 against frame 1 0.488. `test_06_11`: "10 steps: the timeline at 0.3333 s, the recording's simulation_seconds 0.33" |
| 4 | `85c1677` | Z-up | the changed tests | 22 passed; 1 passed. `test_06_10`: median gaps 0.201 s, 0.200 s and 0.197 s; 1.72 s simulated, 2.2 s idle; frame 0 against frame 1 0.482. `test_06_11` as in step 3 |
| 5 | `85c1677` | Z-up | both live suites whole | 196 passed |
| AI | `85c1677` | Y-up | `scenarios.py run --phases 6,24`, run `20261101-200054` | 12 PASS, 1 WARN. 6.1, 6.3 and 24.3 went from WARN to PASS: 6.1's stop line read "27 frames, 5.66s: 4.15 s of simulation played, 1.19 s stopped or paused", the frames before play 0.2 s apart by `wall_time` and those while playing 0.2 s apart in `sim_time`; 24.3's five callstacks ended `... (+695 characters)` with a `matched:` line each |

**The WARN, 6.2** (PASS before): its last frame, 26, came after 6.1's `sim_control("stop")` had put the cube back at
3 m, so it showed the cube high, where frame 25, the last while playing, showed it on the ground. The clock does as
designed: a stopped update takes a frame at `fps` by the clock. Fixed in the scenario text in the commit after
`85c1677`: 6.1, 7.1 and 7.3 pause, then call `stop_recording`, then stop, as 6.4 and `test_07_01` already did, and
`test_06_01` and `test_07_03` follow. TOOLS.md and `start_recording`'s description say to pause, or stop the
recording, before stopping the simulation to end on the run's last state. AI phase 6 is to be run again on it.

Frame 0 against frame 1 read 0.48 to 0.62 of 255 across the runs: more than #51's E14 (0.21 to 0.24) but under the
test's 1.0, against 6 to 8 for #111's grid. What the runs couldn't show: Isaac Sim 5.x, Linux, USD Composer, and Path
Tracing's settle, F1's case, live (Isaac Sim's default real-time mode owes no settle frames).
