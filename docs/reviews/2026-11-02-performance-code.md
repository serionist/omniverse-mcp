---
subject: "Add get_performance, which measures the app's frame rate, its physics step and GPU memory, to the tool contract (#156)"
base: main (feb45c5)
head: d7eda78
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the extension's core and handler; the server, contract, docs and live test. Minors only, so no second round"
verdict: clean
---

# Review: Add get_performance

Read from the branch's diff against `main` (23 files, about 2,650 lines with the plan) by two fresh reviewers, read
only, against the approved plan `docs/plans/2026-11-02-performance.md` and the maintainer's agreement on #156. One
read `ovmcp/core/performance.py`, `handlers/performance.py` and their tests, checking every Kit and Isaac Sim API
against Isaac Sim 6.2's sources; the other the tool, client, contract, docs, skill and live test. Six minors, all fixed
in `333dc67` and `feff522`; every improvement taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/performance.py`, `handle_performance` | A measurement that waited out its 90 s on the viewport lock (a capture or another measurement holding it) said it "ran out while the stage was still loading" | fixed: a phase of its own until the first update, "waiting for a capture or another measurement"; tested |
| F2 | minor | `core/performance.py`, `_not_settled` | The note divided by the first half where `settled` compared against the smaller, so 50.0 then 45.4 ms said "9% below" though unsettled | fixed: against the smaller half; tested |
| F3 | minor | `core/performance.py`, `gpu_render` | With no frame timed, the answer blamed Hydra's profiler | fixed: "no frame was timed"; tested |
| F4 | minor | `tests/test_performance_handler.py` | The handler's six fallbacks (a profiler, physics or memory read that raises) had no test | fixed: each pinned with a fake that raises |
| G1 | minor | `docs/TOOLS.md`, the Returns sample | The sample didn't add up (its physics line was another run's), showed a fixed-step stage near real time where it runs at a third of it, and misquoted the profiler-off line | fixed: one coherent 120-frame run; the line as the tool sends it |
| G2 | minor | `tests/test_tools.py` | The answer's lines for a limiter already off, missing memory figures and fixed steps without time codes had no test | fixed: one case for all three |

**Refuted:**
- **The limiter or subscriptions left after the time limit or a cancel:** the `finally` stops the measurement and puts
  the setting back; the time-limit, error and cancel tests assert both.
- **Physics steps misaligned with the kept intervals:** physics runs before the update observer, and the count
  follows the kept samples; a test pins the dropped first step.
- **A timing error escaping:** both errors `bounded` can raise subclass the error the handler catches.
- **A subscription changed inside PhysX's callback, nested measurements, bridge security:** none; measurements run one
  at a time under the viewport lock, and the route sits behind the token, `Origin` and `Host` checks.
- **"Fixed time steps of 1/<time codes per second> s" wrong:** `RenderingManager.set_dt` sets both together.
- **An older extension, a retried 90 s call, the live test without Kit or left heavy, `READS`, the one-way door, the
  plugin skill's rules:** each checked against the code and the issue's agreement.
- **The build's departures** (simulated time from steps counted, GPU memory against a budget, a limiter Kit doesn't
  set left alone, a stopped timeline's line, the lock's wait inside the 90 s, headless from `/app/window/enabled`):
  each sound.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Use Hydra's `dedicated_video_memory` for the device's total, the budget as a fallback | taken: `333dc67` |
| I2 | Note the physics scene during the survey, so the step needs no second walk | taken: `333dc67` |
| I3 | Lift the limiter only when it is on, so one already off isn't reported as lifted | taken: `333dc67` |
| I4 | Make the live limiter check prove the lift: the limiter on at 30 Hz, the light stage reading over 36 FPS, the setting back after every call | taken: `feff522` |
| I5 | Pin the description's warnings in `test_contract.py` | taken: `feff522` |
| I6 | `get_sim_state`'s description names `get_performance` for a render rate | taken: `feff522` |
| I7 | "No physics numbers" where the description said "no physics lines" | taken: `feff522` |

**Not covered:** which thread PhysX calls the stats callback on (Isaac Sim's own recorder does the same); whether
"PhysX Update" fires once per substep; Isaac Sim 5.x; whose memory Hydra's usage counts (below).

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, each run on a fresh Kit; the
machine's GPU (an RTX 5090) shared with other sessions' work throughout:

- At `d7eda78`, both live suites on a Z-up stage: 209 passed, `TestGetPerformance` among them.
- At `d7eda78`, on a Y-up stage, three runs: the first stopped answering at `test_16_02_raycast_miss`, after
  `TestGetPerformance` had passed (Kit hung where #54 first did; no dump was taken); the second had one failure, a
  capture ending 1.51 s after its draw against `test_16_08`'s 1 s, with other work on the GPU; the third passed, 209.
- After the review's fixes (`feff522`), `TestGetPerformance` alone: passed. With the limiter set on at 30 Hz, the light
  stage read 7.96 ms a frame (about 126 FPS), so the lift took effect, and the setting came back after every call; the
  heavy stage (250,000 point-instanced cubes and a 1920x1080 render) read 9.47 ms, the same stage again 9.10 ms (4%
  apart) and once more straight after a capture 10.80 ms (14%, inside the 15% tolerance).
- Not shown live: whose memory Hydra's figures count on a GPU other apps share, which the answer's line names as
  Hydra's; Isaac Sim 5.x's `omni.physx` path.
