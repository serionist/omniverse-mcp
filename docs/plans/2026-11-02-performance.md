---
title: Add get_performance, which measures the app's frame rate, its physics step and GPU memory, to the tool contract
issue: "#156"
status: draft
approved_by:
approved_at:
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
| physics step | `physics_frametime.py`: `omni.physics.core.get_physics_benchmarks_interface().subscribe_profile_stats_events` | the same, while the timeline plays |
| GPU memory | `memory.py`: `omni.hydra.engine.stats.get_device_info()` (`usage`) and `get_mem_stats()` | `get_device_info()`'s usage and budget for device 0 |

The limiter is `/app/runLoops/main/rateLimitEnabled` (with `rateLimitFrequency`), the setting Isaac Sim's own scripts
turn off to measure.

### The extension

- **`ovmcp/core/performance.py`** (Kit-free): `summarise(samples_ms)` gives mean, p50, p95, worst and frames per
  second; `ratio(sim_seconds, wall_seconds)`; `answer(...)` puts the numbers and conditions in one dict. Unit-tested
  with usd-core and plain lists.
- **`handlers/performance.py`,** `handle_performance(body)`, route `/sim/performance`:
  - checks `frames` (1 to 2000) and `warmup` (0 to 600) before anything changes;
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
  - reads the counts (`stage.Traverse()`: prims, `UsdGeom.Mesh`, instances and prototypes), the render products
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

  A number Kit can't give says so on its line (`gpu_render = not available in this app`).
- **Description:** what it measures, that the limiter is lifted and put back, that a playing simulation adds the
  physics lines, and that the numbers are this machine's: measure where the acceptance runs.

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
| 1 | `ovmcp/core/performance.py`, tests first | `tests/test_performance.py`: the statistics, the ratio, the answer's dict with each number missing in turn |
| 2 | `handlers/performance.py` and the route, with the Kit fakes the handler tests use | `tests/test_performance_handler.py`: bounds refused before a change; the limiter put back after success, an error and the time limit; subscriptions dropped |
| 3 | `client.performance`, the tool and its text; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs and the `simulate` skill's line | review |
| 5 | Live, in `tests/test_integration.py`: a light stage, then a heavy one (a point instancer of many cubes and a camera render product), the heavy one's mean frame time higher; the heavy stage measured twice, unchanged, the two means within a stated tolerance, and once more straight after a `capture_viewport`, within it too (fit I6); the limiter's setting the same after the call; a playing stage gives the physics lines | the live run on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live (by hand, Isaac Sim 6.2): step 5, on a Z-up and a Y-up stage with the suites.
- What neither shows: the lab server's numbers (another machine and GPU); USD Composer without Hydra's profiler, which
  the unit tests cover by a failed import; a Kit with a viewport window.

## Docs

`docs/TOOLS.md` (a heading for the tool, its row in the task table), `docs/ARCHITECTURE.md` (the route), `README.md`'s
tool list and count, the `simulate` skill (how to measure: playing, sensors on, warm-up), `CHANGELOG.md` (Added).

## Risks

- **The limiter isn't restored** if Kit dies mid-measurement: accepted; a restarted Kit reads its own settings again.
- **Another call runs while it measures:** a capture waits on the viewport lock the measurement holds (at most 90 s
  plus its own, which can pass the client's 120 s); any other call's work counts in the frames. The description and the
  skill say to measure alone; a recording is named in the answer.
- **The other Kit apps on a shared machine** share the GPU: `gpu_memory` may count the device's whole use, not this
  app's alone; the answer says which `get_device_info()` reports, once the build has read it.
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
