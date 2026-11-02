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

The case (#156, and its author's update of 2026-11-02): a 300 x 300 m construction site in Isaac Sim 6.2 is accepted
when it runs at 15 FPS or more on the lab server (an RTX 6000 Pro) with two walking robots, each rendering a lidar and
two cameras; short of that, the scene is cut down there. Agents cut detail (a far area's level, an instanced pile, a
collider) and must see each change's effect. The "30 FPS in the viewport" target is dropped, and whether the server
runs Isaac Sim headless is not known: the tool reports the app loop's rate either way.

When this is done, `get_performance(frames=120, warmup=30)` measures over `frames` app updates after `warmup`, with
Kit's frame-rate limiter lifted for the measurement and put back after (the maintainer's call), and answers:

- the app loop: frames per second and frame time (mean, p50, p95, worst), the number the acceptance reads;
- the GPU's render time per frame from Hydra's profiler, when it has one;
- while the simulation plays: the physics step time and the simulated-to-real ratio;
- GPU memory used and the device's total; the stage's prim, mesh and instance counts; the render products alive
  (sensors' and kept capture feeds');
- the conditions: frames, warm-up, the renderer, each render product's resolution, playing or not, headless or not,
  the limiter's setting before the call.

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
  - reads the limiter's setting, sets `rateLimitEnabled` false, and restores it in a `finally`, so an error or a
    cancelled request leaves Kit as it was;
  - awaits `warmup` updates, then subscribes to the pre-update event and the physics stats, awaits `frames` updates,
    and unsubscribes in the `finally`;
  - bounded by time: it stops at 90 s, under the server's 120 s, and answers what it measured with a note giving the
    frames it got;
  - reads the counts (`stage.Traverse()`: prims, `UsdGeom.Mesh`, instances and prototypes), the render products
    (the bridge's kept feeds and the stage's `RenderProduct` prims with their resolution), `/renderer/active`, the
    timeline's state, and whether Kit runs headless (`/app/window/hideUi` or no main window).
- It runs on Kit's main thread as every handler does, awaiting updates, never blocking them: the app keeps rendering
  while it measures (`AGENTS.md`, Traps).

### The server

- **`client.performance(frames, warmup)`;** **`tools/simulation.py`'s `get_performance`,** `READS`: it changes
  nothing a user would see once it returns; the limiter goes back.
- **The answer,** text, conclusion first:

  ```
  app = 22.4 FPS (frame time mean 44.6 ms, p50 43.9, p95 51.2, worst 63.0) over 120 frames after 30
  gpu_render = mean 31.2 ms, p95 36.0
  physics = step mean 6.1 ms, p95 7.4; simulated 4.00 s in 5.36 s (0.75 of real time)
  gpu_memory = 14.2 GB used of 47.8 GB
  stage = 18342 prims, 2210 meshes, 9120 instances of 41 prototypes
  render_products = 7: 2 lidars, 4 cameras at 1280x720, 1 kept capture feed at 1280x720
  conditions = RTX Real-Time, playing, headless; rate limit lifted for the measurement (was on at 60 Hz)
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
| 5 | Live: `test_25b`-style test in `tests/test_integration.py`: a light stage, then a heavy one (a point instancer of many cubes and a camera render product), the heavy one's mean frame time higher; the limiter's setting the same after the call; a playing stage gives the physics lines | the live run on Isaac Sim 6.2 at 8212 |
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
- **Another call runs while it measures** (a capture): its frames count in the measurement; the answer's conditions
  name the render products, and the skill says to measure alone.
- **Hydra's profiler is off by default** in some apps, so `gpu_render` reads 0: the handler reports `not available`
  when every sample is 0.

## Plan review

None yet.
