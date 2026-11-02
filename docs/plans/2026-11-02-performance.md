---
title: Add get_performance, which measures the app's frame rate, its physics step and GPU memory, to the tool contract
issue: "#156"
status: approved
approved_by: serionist (delegated to the author, 2026-11-02)
approved_at: 2026-11-02
---

# Add get_performance, which measures the app's frame rate, its physics step and GPU memory, to the tool contract

## Goal

One call gives the numbers a speed acceptance needs, the same way every time. Today no tool says how fast the stage
runs, and an agent times app updates with `execute_script` and guesses at the rest.

The case (#156, and its author's update of 2026-11-02, posted in the issue with the agreement): a 300 x 300 m
construction site in Isaac Sim 6.2 is accepted when it runs at 15 FPS or more on the lab server (an RTX 6000 Pro) with
two walking robots, each rendering a lidar and two cameras; short of that, the scene is cut down there. Agents cut
detail (a far area's level, an instanced pile, a collider) and must see each change's effect. The "30 FPS in the
viewport" target is dropped, and whether the server runs Isaac Sim headless is not known: the tool reports the app
loop's rate either way.

When this is done, `get_performance(frames=120, warmup=30)` measures over `frames` app updates after `warmup`, with
Kit's frame-rate limiter lifted for the measurement and put back after (the maintainer's call), and answers:

- the app loop: frames per second and frame time (mean, p50, p95, worst), the number the acceptance reads, and the
  first and second halves' means, with a "not settled, measure again" note when they drift apart (fit I4);
- the GPU's render time per frame from Hydra's profiler, when it has one;
- while the simulation plays: the physics scene's steps per second, the steps a frame carries, the physics time per
  step and per frame, and the simulated-to-real ratio (fit I3);
- GPU memory used and the device's total; the stage's prim, mesh and instance counts; the render products alive
  (the sensors');
- the conditions, so two answers can be compared (fit I2, I5): the GPU and the Kit app with its version; frames and
  warm-up; the renderer, each render product's resolution, playing or not, headless or not; the limiter's setting
  before the call; `/app/asyncRendering`, `/rtx/ecoMode/enabled` and a non-zero `/app/renderer/sleepMsOnFocus` or
  `sleepMsOutOfFocus`, which Isaac Sim's throttling changes around play and stop.

The same unchanged stage measured twice gives the same numbers within a stated tolerance: the kept capture feed is
released for the measurement (fit I1), the stage has finished loading before the warm-up starts (fit I4), and the
answer says what else could move them.

In scope: the tool, its client call, a route and handler, a Kit-free core for the statistics and the answer, the
contract, docs, the `simulate` skill's line on measuring, tests.
Out of scope: changing the scene to meet a target; per-prim or per-sensor cost; a viewport window's own present rate
(none exists headless; a later issue if the server has one); multi-GPU breakdowns.

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | The tool lifts Kit's frame-rate limiter while it measures, and puts it back | yes (maintainer, 2026-11-02) |
| Q2 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02) |

### Prior art

Isaac Sim's own benchmark extension, `isaacsim.benchmark.services` (installed with Isaac Sim 6.2), measures the same
things, and the bridge reads them the way it does, without depending on the extension:

| Number | Isaac Sim's recorder | The bridge |
|---|---|---|
| app frame time | `app_frametime.py`: `time.perf_counter_ns()` between `omni.kit.app.GLOBAL_EVENT_PRE_UPDATE` events | the same, on the update events the handler awaits |
| GPU frame time | `gpu_frametime.py`: `omni.hydra.engine.stats.HydraEngineStats().get_gpu_profiler_result()` each update | the same; left out, with a note, where the import fails (USD Composer without it) |
| physics step | `physics_frametime.py`: `omni.physics.core.get_physics_benchmarks_interface().subscribe_profile_stats_events` (Isaac Sim 6.x); Isaac Sim 5.1's recorder reads `omni.physx.get_physx_benchmarks_interface()` | `omni.physics.core`'s where it imports, else `omni.physx`'s, which 6.2 still has (round 1, P3); while the timeline plays |
| GPU memory | `memory.py`: `omni.hydra.engine.stats.get_device_info()` (`usage`) and `get_mem_stats()` | `get_device_info()`'s usage and budget for device 0 |

The limiter is `/app/runLoops/main/rateLimitEnabled` (with `rateLimitFrequency`), the setting Isaac Sim's own scripts
turn off to measure.

### The extension

- **`ovmcp/core/performance.py`** (Kit-free): `summarise(samples_ms)` gives mean, p50, p95, worst and frames per
  second; `ratio(sim_seconds, wall_seconds)`; `answer(...)` puts the numbers and conditions in one dict. Unit-tested
  with usd-core and plain lists.
- **`handlers/performance.py`,** `handle_performance(body)`, route `/sim/performance`:
  - checks `frames` (2 to 2000) and `warmup` (0 to 600) before anything changes, and times `frames` + 1 updates so
    `frames` intervals are left after the first is dropped; an answer with no samples (the 90 s spent loading or
    warming up) says so, with no statistics (round 1, P5);
  - inside `without_kept_feed()` (`camera_feed.py:623`), which releases the kept capture feed and holds the viewport
    lock, so a capture in the last 30 s doesn't add an RTX render to the number and none starts mid-measurement
    (fit I1); a running recording (`recording_active()`) is named in the answer, since its render product counts;
  - reads the limiter's setting, sets `rateLimitEnabled` false, and restores it in a `finally`, so an error or a
    cancelled request leaves Kit as it was;
  - waits, bounded, until the stage has finished loading (`omni.usd`'s `get_stage_loading_status()`, nothing left to
    load), then awaits `warmup` updates (fit I4);
  - times `frames` updates through `_updates.on_update` (`handlers/_updates.py`), the bridge's one update path, and
    drops the first interval as Isaac Sim's recorder does (fit I7); the physics stats through
    `get_physics_benchmarks_interface()`, unsubscribed in the `finally`;
  - bounded by `capture.Budget` and `bounded`: it stops at 90 s, under the server's 120 s, and answers what it
    measured with a note giving the frames it got. The viewport lock it holds makes a capture called meanwhile wait;
    the description says to measure alone;
  - takes simulated time from the physics steps it counted, each step's dt summed, not from the timeline's time,
    which wraps at its end (round 1, I8);
  - reads the counts (`stage.Traverse()`: prims, `UsdGeom.Mesh`, instanceable prims and their prototypes, and point
    instancers with their instances, which `IsInstance()` doesn't count; round 1, I10), the render products
    (the stage's `RenderProduct` prims with their resolution), `/renderer/active`, the timeline's state and its
    step (fixed time stepping and `timeCodesPerSecond`, or wall clock), the physics scene's steps per second, the
    throttling settings above, `get_device_info()`'s GPU description, `kit_app()` (`core/protocol.py`), and whether
    Kit runs headless.
- It runs on Kit's main thread as every handler does, awaiting updates, never blocking them: the app keeps rendering
  while it measures (`AGENTS.md`, Traps).

### The server

- **`client.performance(frames, warmup)`;** **`tools/simulation.py`'s `get_performance`,** `READS`: it changes
  nothing a user would see once it returns; the limiter goes back.
- **The answer,** text, conclusion first:

  ```
  app = 22.4 FPS (frame time mean 44.6 ms, p50 43.9, p95 51.2, worst 63.0) over 120 frames after 30
  settled = first half 44.9 ms, second half 44.3 ms
  gpu_render = mean 31.2 ms, p95 36.0
  physics = 120 steps/s, 5.4 steps a frame, 6.1 ms a step (32.9 ms a frame); simulated 4.00 s in 5.36 s (0.75 of real time)
  gpu_memory = 14.2 GB used of 47.8 GB
  stage = 18342 prims, 2210 meshes, 9120 instances of 41 prototypes
  render_products = 6: 2 lidars, 4 cameras at 1280x720
  conditions = NVIDIA RTX 6000 Pro, Isaac Sim 6.2.0 (Kit 110.4.0), RTX Real-Time, playing, headless; rate limit lifted
    for the measurement (was on at 60 Hz); async rendering off, eco mode off
  ```

  A number Kit can't give says so on its line (`gpu_render = not available in this app`). A stopped or paused timeline
  with eco mode on adds `note = eco mode is on and the timeline isn't playing: RTX may stop rendering a still stage,
  so this reads faster than the scene plays; measure while it plays` (round 1, P4).
- **Description:** what it measures; that the limiter is lifted and put back, so a playing stage with fixed time steps
  runs faster than real time while it measures (round 1, P8); that the kept capture feed is released, so the next
  capture sets up its view again (round 1, P7); that a playing simulation adds the physics lines; to measure while it
  plays, alone; and that the numbers are this machine's: measure where the acceptance runs.

### Alternatives

- **Depend on `isaacsim.benchmark.services`:** no; USD Composer and Kit without Isaac Sim lack it, and its recorders
  are a few calls each.
- **Measure in `execute_script`:** what agents do today; the issue asks for a call that gives the same numbers every
  time.
- **Keep the limiter on:** no (Q1); a light stage would read the cap, not its speed.
- **A long measurement as a job** (#158): no; 90 s bounds it, and 120 frames at 15 FPS take 8 s.

## Compatibility

**One-way door: the tool contract.** A new tool, `get_performance`, and a new route, `/sim/performance`: additive, no
existing call changes. The maintainer agreed in #156's thread (posted from the maintainer's chat decisions,
2026-11-02, before the PR). An older extension answers the unknown route with the install advice, as for any new
route.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/performance.py`, tests first | `tests/test_performance.py`: the statistics; the two halves and the "not settled" note when their means differ by more than 10%; zero samples answered with no statistics; simulated time from summed step dts; the ratio; the eco-mode note; the answer's dict with each number missing in turn (round 1, P6) |
| 2 | `handlers/performance.py` and the route, with the Kit fakes the handler tests use (`FakeUpdates`) | `tests/test_performance_handler.py`: bounds refused before a change; `frames` + 1 updates timed and the first interval dropped; the loading wait and its bound; the kept feed released under the viewport lock; a running recording named; `omni.physics.core` and, failing its import, `omni.physx`; the limiter put back after success, an error and the time limit; subscriptions dropped (round 1, P6) |
| 3 | `client.performance`, the tool and its text; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs and the `simulate` skill's line | review |
| 5 | Live, in `tests/test_integration.py`, every measurement while the timeline plays (round 1, P4): a light stage, then a heavy one (a point instancer of many cubes and a camera render product), the heavy one's mean frame time higher; the heavy stage measured twice, unchanged, the two means within 15% of each other, and once more straight after a `capture_viewport`, within 15% too (fit I6); the limiter's setting the same after the call; the physics lines present | the live run on Isaac Sim 6.2 at 8212, the shared machine's other Kit apps idle (round 1, I11) |
| 6 | First, the maintainer's agreement and the issue author's updated targets posted in #156 (round 1, P1, P2); then `uv run tools/gate.py full`, `review-code`, the PR linking them | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live (by hand, Isaac Sim 6.2): step 5, on a Z-up and a Y-up stage with the suites.
- What neither shows: the lab server's numbers (another machine and GPU); USD Composer without Hydra's profiler, which
  the unit tests cover by a failed import; a Kit with a viewport window; Isaac Sim 5.x, whose `omni.physx` path the
  unit tests cover by a failed import of `omni.physics.core` (round 1, P3).

## Docs

`docs/TOOLS.md` (a heading for the tool, its row in the task table), `docs/ARCHITECTURE.md` (the route), `README.md`'s
tool list and count, the `simulate` skill (how to measure: playing, sensors on, alone; its `description` naming frame
rate, FPS and speed targets so a speed request loads it, and `get_performance` in its `allowed-tools`; round 1, I9),
`plugin/README.md` and `docs/AI_GUIDE.md` if they list the skill's tools, `CHANGELOG.md` (Added).

## Risks

- **The limiter isn't restored** if Kit dies mid-measurement: accepted; a restarted Kit reads its own settings again.
- **Another call runs while it measures:** a capture waits on the viewport lock the measurement holds (at most 90 s
  plus its own, which can pass the client's 120 s); any other call's work counts in the frames. The description and the
  skill say to measure alone; a recording is named in the answer.
- **The other Kit apps on a shared machine** share the GPU: frame times move with their load (round 1, I11), and
  `gpu_memory` may count the device's whole use, not this app's alone; the answer says which `get_device_info()`
  reports, once the build has read it, and the skill says to measure with other GPU work idle.
- **Releasing the kept capture feed** makes the next capture set up its RTX view again, the step #114 found can hang
  Kit 110; in a capture, measure, edit, capture loop, each round sets one up that the kept feed would have saved
  (round 1, P7). Accepted: the issue's point is a repeatable number, and a kept 4096² render would swamp it; the
  description says so, and the skill says to measure before capturing.
- **The limiter lifted** makes a playing stage with fixed time steps (Isaac Sim's default) run faster than real time
  for the measurement, so a robot driven over ROS 2 or by a person falls behind its commands meanwhile (round 1, P8).
  Accepted (Q1): the measurement is short, and the description says so.
- **Hydra's profiler is off by default** in some apps, so `gpu_render` reads 0: the handler reports `not available`
  when every sample is 0.

## Plan review

### Fit

The plan at `76c4498`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, with this repo's `fit-plan`
from branch `160-fit-plan`. The change's own question: does the measurement give the same number twice on an unchanged
stage, and does its answer say enough to compare two runs? Answers by the author, 2026-11-02, on the maintainer's
delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | Measure inside `without_kept_feed()`, so a capture's kept feed, rendering every update for 30 s after it, doesn't add to the number and no capture starts mid-measurement; name a running recording | taken: The extension, Risks |
| I2 | Name `/app/asyncRendering`, `/rtx/ecoMode/enabled` and the sleep settings in the conditions: Isaac Sim's throttling turns async rendering and eco mode on and off around play and stop | taken: Goal, The server |
| I3 | Report the physics scene's steps per second, the steps a frame carries and the physics time per frame, not the time per step alone | taken: Goal, The server |
| I4 | Wait for the stage to finish loading before the warm-up, and give the two halves' means with a "not settled" note when they drift | taken: Goal, The extension |
| I5 | Name the GPU and the Kit app with its version, since agents build on one machine and the acceptance runs on another | taken: Goal, The extension |
| I6 | The live test measures the unchanged heavy stage twice, and once after a capture, within a stated tolerance | taken: step 5 |
| I7 | Time updates through `_updates.on_update`, bound the call with `capture.Budget` and `bounded`, and drop the first interval, as Isaac Sim's recorder does | taken: The extension |

Noticed on the way, for Round 1: #156 has no agreement comment yet (Compatibility); the author's update of the targets
isn't in the issue, whose body still names the laptop and the 30 FPS viewport target (Goal).

### Round 1

**How:** one fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, read only, every lens, at `280319d`, with
Isaac Sim 6.2's sources and Isaac Sim 5.1's on GitHub. **Verdict:** needs-fixes, minors only, so no second round.
**Now:** every finding fixed, I8 to I11 taken, and the plan approved on the maintainer's delegation.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | No step posted the maintainer's agreement in #156, so the PR would add a tool and a route with none in the issue (noticed by the fit) | fixed: step 6 posts it first; the PR links it |
| P2 | minor | The issue's body still names the 30 FPS viewport target and the laptop; review-code reads the change against it (noticed by the fit) | fixed: the author's updated targets are posted with the agreement |
| P3 | minor | Physics times came only from `omni.physics.core`, which Isaac Sim 5.1 lacks; its recorder reads `omni.physx`'s interface | fixed: `omni.physics.core` where it imports, else `omni.physx`; 5.x named in Tests |
| P4 | minor | Isaac Sim's throttling turns eco mode on at stop and pause, so a still, stopped stage renders few frames: step 5's "heavy higher" could fail, and an agent would read a speed the playing scene never reaches | fixed: step 5 measures while playing; the answer notes eco mode on a stopped timeline |
| P5 | minor | `frames=1` with the first interval dropped left no samples, and so did a measurement whose 90 s went to loading: a division by zero or an empty answer | fixed: `frames` 2 to 2000, `frames` + 1 updates timed, zero samples answered plainly |
| P6 | minor | Steps 1 and 2 named none of the fit's additions, and "a stated tolerance" gave no number | fixed: each in the steps' tests; 15% between runs, 10% between halves |
| P7 | minor | Releasing the kept feed makes the next capture set up its view again, the step #114 found can hang Kit 110 | fixed: accepted in Risks with its reason; the description and the skill say so |
| P8 | minor | With the limiter lifted, a playing stage with fixed time steps runs faster than real time, and a robot driven from outside falls behind | fixed: accepted in Risks (Q1); the description says so |

**Refuted:**
- **A capture waits on the lock past the client's 120 s:** already in Risks, and one client sends one request at a
  time.
- **The limiter is read only at start-up:** Kit's preferences and Isaac Sim's `RenderingManager.set_dt` write it at
  runtime.
- **Pausing the kept feed would cost less than releasing it:** the kept-feed plan's K5 found pausing also sets up a
  new view.
- **Hydra's stats missing in USD Composer:** covered by the note where the import fails.
- **"PhysX Update" per frame, not per step:** it fires on every physics fetch, once per step.
- **Bridge security:** the route sits with the others behind the token, `Origin` and `Host` checks.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I8 | Simulated time from the physics steps counted, not the timeline's time, which wraps at its end | taken |
| I9 | The `simulate` skill's description names frame rate, FPS and speed targets, and its `allowed-tools` the new tool, so a speed request loads it | taken: Docs |
| I10 | Count point instancers' instances as well as instanceable prims | taken |
| I11 | Other Kit apps on the same GPU move frame times: run step 5 with them idle | taken: step 5, Risks |

**Not covered:** Isaac Sim 5.x (inferred from 5.1's recorder, no install here); what needs a running Kit (eco mode's
effect on a camera feed, `get_device_info()`'s keys); harness-integrity, which nothing here touches.
