---
title: Keep Kit answering when physics plays with a robot on the stage
issue: "#5"
status: draft
approved_by:
approved_at:
---

# Keep Kit answering when physics plays with a robot on the stage

On Isaac Sim 6.2, Kit stops answering when physics first plays with the G1 or the Franka on the stage (#5). The code
and NVIDIA's published source point at a deadlock that our bridge's Python log subscription makes possible. That is
still an inference, so this plan starts with experiments the main session runs on its own headless Kit. The fix waits
for their result and the maintainer's choice.

## Goal

**When this is done:**

- On Isaac Sim 6.2, headless and GUI, with the bridge: `sim_control("play")` with the G1 or the Franka on the stage
  returns, and Kit keeps answering.
- `get_joint_states` returns the robot's joint positions and velocities while physics plays or is paused.
- The live runs drop `-k "not test_10_ and not test_14_"`, and `test_14_04` checks that joint states come back.

**Or, if the hang is NVIDIA's:** README's Known issues names the upstream issue and any workaround, the skip stays
with its reason, and #5 stays open.

**In scope:**

- the investigation;
- the bridge's log subscription, if it is the cause;
- `get_joint_states`'s articulation path, which can't work on Isaac Sim 5.1 or 6.2 today;
- the tests and docs these touch.

**Out of scope:**

- NVIDIA's bugs, such as isaac-sim/isaacsim#729's render livelock;
- Newton physics;
- `set_joint_targets`;
- the Y-up gravity tests (#6) and `draw_debug` (#7).

## What the code and the sources say

Each row is read from the code or from a source, not from memory. Isaac Sim's source is at
[isaac-sim/isaacsim](https://github.com/isaac-sim/isaacsim) (tags `v5.1.0` and `v6.2.0`). omni.physx's source is at
[NVIDIA-Omniverse/PhysX](https://github.com/NVIDIA-Omniverse/PhysX) under `omni/`, read at `release/110.3`, the
nearest published branch: Isaac Sim 6.2 runs Kit 110.4.0 (`deps/kit-sdk.packman.xml` at `v6.2.0`) and
`omni.physx.cooking` 110.4.4 (the 6.2.0 release notes).

| # | Fact | Source |
|---|---|---|
| 1 | `test_14_04` calls `sim_control("play")` first. Nothing earlier plays physics after the G1 arrives in phase 10: phases 11 to 13 don't play, and recording doesn't start the timeline. So the G1's first physics load happens inside that `play` | `tests/test_scenarios.py` lines 808-812; `handlers/recording.py` has no `play()` |
| 2 | `get_joint_states` can't build an articulation on 5.1 or 6.2. `isaacsim.core.api.articulations` exports only `ArticulationGripper` and `ArticulationSubset` at both tags. `omni.isaac.core` is a deprecated extension at `v5.1.0` and gone at `v6.2.0`. The handler's `except Exception` turns the `ImportError` into an error result, so on 6.2 it errors before touching physics: it isn't the call that blocks | `handlers/robot.py` lines 196-205; `source/deprecated/isaacsim.core.api/python/impl/articulations/__init__.py` (`v6.2.0`), `source/extensions/...` (`v5.1.0`) |
| 3 | When the timeline plays, Isaac Sim loads physics from a Python callback: `SimulationManager._on_play` calls `initialize_physics()`, which calls `force_load_physics_from_usd()`. 5.1 does the same through `_warm_start` | `isaacsim.core.simulation_manager/python/impl/simulation_manager.py`: `v6.2.0` lines 431-440, 640-668, 711-733; `v5.1.0` lines 164-166, 234-237 |
| 4 | That binding doesn't release the GIL: `.def("force_load_physics_from_usd", wrapInterfaceFunction(&IPhysicsStageUpdate::forceLoadPhysicsFromUSD), ...)`. Carbonite's own bindings add `py::call_guard<py::gil_scoped_release>()` where they do release it. So the main thread holds the GIL for the whole parse | `omni/umbrella/bindings/BindingsPhysicsStageUpdate.cpp` line 90; Carbonite's `SettingsBindingsPython.h` and `TokensBindingsPython.h` for the idiom |
| 5 | Collision meshes are cooked as `carb.tasking` tasks on worker threads (`tasking->addTask(...)`, "Set up the background task to actually generate the convex mesh"). A synchronous request waits on the task's future with no timeout (`futureWait(-1)`, then `m_future.wait()`) | `omni/ovruntime/source/omni.physx.cooking/plugins/service/CookingTask.cpp` lines 154-175, 573-588; `CookingComputeService.cpp` lines 294, 810-825 |
| 6 | Kit's last log line is written from inside that task: `CARB_LOG_INFO("ConvexMeshCookingTask: polygon limit reached, resulting convex hull may be suboptimal. Prim %s", ...)` | `plugins/tasks/ConvexMeshCookingTask.cpp` line 142 |
| 7 | Logging is synchronous by default. `/log/async`: "If true, logging a message does not block the thread calling the logging function ... Defaults to false". `ILog::log` "Sends the supplied message to all registered omni::log::ILogMessageConsumer objects", and "Each message may be sent to registered consumers in parallel" | [Carbonite logging](https://docs.omniverse.nvidia.com/kit/docs/carbonite/latest/docs/logging/Logging.html), [ILog](https://docs.omniverse.nvidia.com/kit/docs/carbonite/latest/api/classomni_1_1log_1_1ILog.html) |
| 8 | The bridge subscribes a Python function to `omni.log` when it starts. Python code runs only with the GIL. ARCHITECTURE.md already says "`omni.log` may fire from any thread" | `handlers/logging.py` (`log.add_message_consumer(self._on_log)`); `extension.py` lines 146-149 |
| 9 | NVIDIA documents the same kind of deadlock in Isaac Sim 6.2's own code: "the Python binding for shutdown_and_release_framework holds the GIL while releaseFrameworkAndShutdown() joins carb.tasking worker threads that may themselves be blocked waiting for the GIL" (NVBug 5948099) | `isaacsim.simulation_app/isaacsim/simulation_app/simulation_app.py` (`v6.2.0`) lines 991-995 |
| 10 | A different upstream bug looks alike from outside, on the same GPU as this machine. A single `simulation_app.update()` "intermittently livelocks for 20-270+ seconds", "CPU pinned ~99% (one thread), GPU utilization 0%", then "self-recovers". It is open on 6.0.1 under NVIDIA ticket 6649001. A commenter saw it during heavy start-up work on an Ampere GPU too | [isaac-sim/isaacsim#729](https://github.com/isaac-sim/isaacsim/issues/729) |
| 11 | Isaac Sim 6.2's release notes list no known issue about hangs, cooking, the G1 or the Franka | [6.2.0 release notes](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/overview/release_notes.html) |

### The likely cause

**H1, ours:** Kit's main thread and a cooking worker deadlock over the GIL, through our log subscription.

1. `play` runs `SimulationManager._on_play` in Python on the main thread, so the main thread holds the GIL. It calls
   `force_load_physics_from_usd()`, which keeps the GIL (fact 4). That call cooks the G1's collision meshes on
   worker threads and waits for each one (fact 5).
2. A cooking task logs "polygon limit reached" (fact 6). `omni.log` runs every consumer on the thread that logged
   (fact 7). Our Python `_on_log` then waits for the GIL (fact 8).
3. The main thread waits for the task, and the task waits for the main thread's GIL. Neither moves. The bridge's event
   loop runs on that main thread, so nothing answers, and the cooking line is the last in the log.

**What H1 explains:**

- **The last log line** is the cooking task's own.
- **Phase 5 plays fine:** a cube needs no cooking, so no worker logs during that load.
- **Every run hangs again:** cooked data is finalised on the main thread after the task ends, so a Kit that was
  killed never cached it.
- **`main` before #3 hangs too:** the log subscription is older than #3.
- **Isaac Sim users rarely see it:** few of them subscribe Python to `omni.log`.

**What H1 doesn't explain yet:**

- what the Franka's cooking logs (S8b in the modernization plan);
- whether the suite ever passed phase 14 on 5.1. No 5.1 results are recorded, and 5.1's play path has the same shape.

**H2, NVIDIA's:** #729's livelock, coinciding with the heavy physics load. The two look different from inside:

| Sign | H1 (deadlock) | H2 (#729 livelock) |
|---|---|---|
| Kit's CPU | flat: both threads wait | one core near 100% |
| Recovery | never | within about 5 minutes |
| Main thread's stack | `_on_play`, `initialize_physics`, `force_load_physics_from_usd`, a `carb.tasking` wait | `librtx.hydra`, `libgpu.foundation`, `libcarb.tasking` |
| Another thread | in `_on_log`, waiting for the GIL | nothing of ours |
| Without our log subscription | plays | still stalls |

**H3:** no hang, only a long cook. This is unlikely: every later test failed for minutes. E2 and E7 measure it anyway.

## Investigation

The main session runs these on its own headless Kit, cheapest first; E1 to E3 decide the cause.

**Rules for every run:**

- port 8212, never the maintainer's Isaac Sim on 8211;
- `OMNI_KIT_ACCEPT_EULA` only as the maintainer set it;
- kill only the Kit process the session started.

| # | Experiment | What it shows |
|---|---|---|
| E1 | **Reproduce, with stacks.** Start the headless Kit as for the live runs, with `faulthandler.dump_traceback_later(60, repeat=True, file=<a file>)` in its launch script. That dumps every thread's Python stack without needing the GIL. Through a `BridgeClient(timeout=600)`: `new_scene`, a PhysicsScene through `execute_script`, `create_robot("g1", "/World/G1")`, then `sim_control("play")`. If it hasn't answered after 60 s: note Kit's last log lines; read `(Get-Process -Id <pid>).CPU` twice, 10 s apart; run `uvx py-spy dump --native --pid <pid>` twice (it may need an elevated shell on Windows); then poll `GET /bridge` every 30 s for 10 minutes | Which call blocks, and H1 or H2 by the table above. If `play` answers, its time is a cold cook |
| E2 | **Our subscription off.** A fresh Kit and E1's steps, after `execute_script("from ovmcp.bridge.handlers.logging import log_buffer\nlog_buffer.stop()")` | If `play` returns now, our consumer is needed for the hang: H1. Its time is the G1's cold cook |
| E3 | **Without the bridge.** A `SimulationApp` script without `--enable ovmcp.bridge`: a new stage, a PhysicsScene, the G1 referenced from `get_assets_root_path() + "/Isaac/Robots/Unitree/G1/g1.usd"`, `omni.timeline.get_timeline_interface().play()`, then 30 timed `app.update()` calls, printing any over 1 s. (a) As is. (b) After `omni.log.get_log().add_message_consumer(lambda *args: None)` | (a) hangs: an Isaac Sim problem (H2 or another). (a) runs and (b) hangs: any Python log consumer deadlocks Kit, and (b) is the repro to give NVIDIA |
| E4 | **Kit flags, subscription on.** A fresh Kit with the bridge and E1's steps, under (a) `--/log/async=true`, then (b) `--/log/level=warn` | A workaround users can apply to 0.2.0 now. (a) also tests fix A2 |
| E5 | **The Franka.** E1, or E2 if E1 already hung, with `create_robot("franka", "/World/Franka")` | Whether S8b's Franka hang is the same one, and which worker line triggers it |
| E6 | **Joint states.** After a `play` that returns (E2 or E4): `get_joint_states("/World/G1")` on today's code; an error naming `omni.isaac.core` is expected. Then through `execute_script`: `from isaacsim.core.experimental.prims import Articulation`, `a = Articulation("/World/G1")`, then `a.dof_names`, `a.get_dof_positions().numpy()` and `a.get_dof_velocities().numpy()`, while playing, paused and stopped. On Isaac Sim 5.1 too, if it is installed | Fact 2 confirmed live, and fix D's read path working on 6.2 (and 5.1), with its behaviour while stopped |
| E7 | **Cook time, cold and warm.** Subscription off: time the first `play`, then `stop` and `play` again in the same Kit, then `play` in a restarted Kit | How long a robot's first play blocks Kit's main thread, for the docs and the suite's timeout |
| E8 | **Kit's log file.** In one Kit: `carb.settings.get_settings().get(...)` for `/log/file`, `/log/level`, `/log/fileLogLevel`, `/log/fileFlushLevel` and `/log/async`. Then 30 lines of the file, including the traceback of `execute_script("raise ValueError('x')")`, and `carb.log_warn("ovmcp-probe")` followed at once by a read of the file's end | Whether fix A1 can read the file: its path, line format, levels, multi-line entries and flushing |
| E9 | **The GUI app, by the maintainer.** Isaac Sim 6.2's GUI with the bridge, the G1, Play | The issue's question, whether the hang is headless-only. H1 says the GUI hangs too, since its play path is the same |

The results go into Findings, below, before the maintainer picks a fix.

## Findings

None yet: the investigation hasn't run.

## Design

The fix depends on which outcome the investigation finds. D applies whatever it finds.

| Outcome | Our fix | Left to NVIDIA |
|---|---|---|
| **A: H1 confirmed** (E1's stacks, E2 plays, E3b hangs) | A1, recommended, or A2; A3 until a release carries it | Releasing the GIL in `force_load_physics_from_usd`'s binding, or loading physics outside a Python callback. The maintainer reports it with E3b's script |
| **B: hangs without the bridge** (E3a) | Known issues links the upstream issue (#729, or a new one with E3a's script) and any workaround found. The live runs keep the skip on 6.2, and #5 stays open. Workarounds to try: CPU dynamics (`physxScene:enableGPUDynamics` false), `--/physics/cooking/ujitsoCollisionCooking=false`, and the steps #729 lists | The fix. No bridge change can bound this: the blocked thread is the one the bridge's event loop runs on |
| **C: no hang, a slow cook** (E2 and E7's times exceed the clients' timeouts) | Docs say how long a robot's first play takes; the suite gives that `play` E7's time; the server's timeout error says Kit may still be cooking | None |

### A1: no Python callback on Kit's worker threads

`get_logs` reads Kit's log file instead of subscribing to `omni.log`.

- **The extension** no longer calls `add_message_consumer`. On each `/logs` request, on the main thread, the handler
  reads what Kit appended to `/log/file` since the last read. It parses that into the same `LogRing`, so the query,
  `since_index` and `total_captured` keep their meaning, and `test_integration.py`'s use of `since_index` still holds.
- **Kit-free work in `ovmcp/core/logs.py`:** the line parser (level, channel, message; continuation lines join their
  entry) and the tail reader. The tail reader takes the appended bytes only; a file shorter than the last offset
  starts over; the first read takes at most the file's last 4 MB.
- **`handlers/logging.py`** keeps only the setting lookup and the file read. With `/log/file` empty, `/logs` returns an
  error naming `--/log/file=<path>`.
- **Why:** it removes the whole class, not only the case we saw. A1 covers any Kit worker that logs while the main
  thread holds the GIL: physics cooking here, and asset loads or shader compiles elsewhere.
- **Why the file holds what we need:** Carbonite's defaults log every level to it and flush every message
  (`/log/fileLogLevel` and `/log/fileFlushLevel`, both verbose). E8 checks Isaac Sim's values.
- **Cost:** entries lose `module`, `source` and `func` unless Kit's line format carries them. The tool's text never
  showed them.

### A2: keep the subscription, make logging asynchronous

The fallback, if E4a works and A1 can't read the file. The extension sets `/log/async` true at startup. A worker's log
call then returns at once, and Kit's own log thread waits for the GIL instead.

**Costs:**

- It changes a setting for the whole app; messages may appear "slightly out-of-order in the log" (Carbonite logging
  docs).
- Kit's log thread still contends for the GIL whenever Python runs.
- A log flush called with the GIL held would deadlock again.

**Rejected: pausing the subscription around `play`.** Play also comes from the GUI's button, from scripts and from
`step`, and the cooking messages lost meanwhile are the ones users need.

### A3: a workaround for 0.2.0

If E4 finds a flag that works, Known issues names it until a release carries A1 or A2.

### D: `get_joint_states` through the articulation API Isaac Sim keeps

This applies in every outcome: today's path errors on 5.1 and 6.2 (fact 2).

- **Read through `isaacsim.core.experimental.prims.Articulation`.** It ships in `v5.0.0`, `v5.1.0` and `v6.2.0`. It
  finds the `ArticulationRootAPI` prim under the given path (`fetch_articulation_root_api_prim_paths`) and reads
  `dof_names`, `get_dof_positions()` and `get_dof_velocities()`.
- **A new object per call.** The cache goes: an object outlives a `stop`.
- **No physics load from the handler.** With the timeline stopped, the handler returns an error: "play or step the
  simulation first". Loading physics from a handler would block the main thread the same way. The constructor only
  builds its physics view when `SimulationManager`'s view already exists (`articulation.py`, `v6.2.0`, lines
  186-188).
- **Without Isaac Sim's core** (USD Composer), the error names the missing extension.
- **Units:** radians for revolute joints and metres for prismatic ones, the tensor API's units. `set_joint_targets`
  takes degrees, USD's drive targets; TOOLS.md says both.
- **Alternatives:** `isaacsim.core.prims.SingleArticulation` is deprecated since 6.0.0 (its `extension.toml`).
  `omni.physics.tensors` directly would drop the dependency on Isaac Sim's core, but `create_simulation_view` takes
  different arguments in 5.1 and 6.2. The experimental API is the one Isaac Sim keeps.

### Files (outcome A with A1, and D)

| File | Change |
|---|---|
| `extension/ovmcp.bridge/ovmcp/core/logs.py` | the Kit log line parser and the tail reader |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/logging.py` | no consumer; finds `/log/file` and feeds the ring before each query |
| `extension/ovmcp.bridge/ovmcp/bridge/extension.py` | no log subscription at startup or shutdown; no articulation cache to clear |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/robot.py` | `handle_get_joint_states` as in D; `_articulation_cache` and `_clear_articulation_cache` go |
| `src/omniverse_mcp/tools/robot.py`, `src/omniverse_mcp/tools/misc.py` | the docstrings of `get_joint_states` and `get_logs` |
| `tests/test_logs.py`, `tests/test_scenarios.py`, `tests/test_integration.py` | as in Tests |

## Compatibility

No one-way door moves.

- **The tool contract:** tool names, parameters, bounds and annotations stay. Only descriptions change, so
  `tests/fixtures/mcp-tools.json` doesn't.
- **The wire protocol:** `/logs` and `/robot/joint_states` keep their paths and request bodies. `/logs` entries keep
  their keys, with `module`, `source` and `func` empty when Kit's file doesn't carry them. `execute_script`'s
  `mcp.get_logs` sees the same.
- **What users notice:**
  - `get_joint_states` works on Isaac Sim 5.x and 6.x, where it always errored;
  - it errors while the timeline is stopped, saying to play first;
  - `get_logs` sees Kit's messages from Kit's start, not the extension's.
- **Settings:** the extension adds none. A2 would set Kit's `/log/async`, a Kit setting, not ours.
- **Kit apps:** Kit 107+ as before. `get_joint_states` needs Isaac Sim, as before. `get_logs` needs Kit's log file,
  which Kit apps write unless told not to (E8).
- **Migration:** none.

## Steps

1. **The investigation,** E1 to E9; the results go into Findings. The maintainer picks the outcome's fixes. No code
   before that.
2. **A1, core:** the parser and the tail reader in `ovmcp/core/logs.py`, with E8's lines as test data. Proved by the
   new cases in `tests/test_logs.py`.
3. **A1, bridge:** the subscription goes, and the ring is fed from the file. Proved live by `test_24_*`,
   `test_integration.py`'s `set_material` log check, and E1's steps no longer hanging.
4. **D:** `get_joint_states` as in D. `test_14_04` asserts success instead of recording a skip. Proved live on 6.2,
   and on 5.1 if it is installed.
5. **The suite:** `test_14_04`'s `play` gets E7's time. The live runs go without the `-k` skip on 6.2 headless, and
   the maintainer runs the GUI (E9).
6. **Docs:** as in Docs, below, with the AGENTS.md trap row.

**For outcome B,** steps 4 and 6 still apply; steps 2 and 3 become the upstream report and the Known issues line.
**For outcome C,** steps 4 to 6 apply, with the timeout message instead of steps 2 and 3.

## Tests

| Suite | What |
|---|---|
| Unit, CI (`tests/test_logs.py`) | each Kit level parses; the channel parses; continuation lines join their entry; an unknown level is kept by name; a partial last line waits for its end; the tail reads appended bytes only; a shorter file starts over; the first read is capped. The existing ring and query tests stay. The coverage floor holds |
| Live, new | a fresh stage, the Franka (smaller than the G1), `play`: it returns within E7's time, and `get_joint_states` returns its DOF positions. On 6.2 today it hangs: the test that fails without the fix |
| Live, changed | `test_14_04` asserts that `get_joint_states` succeeds; its `play` gets E7's time; `test_10_*` and `test_14_*` run again |
| Live, suites | `test_integration.py` and `test_scenarios.py` on Isaac Sim 6.2 headless, on 5.1 if installed, and the GUI by the maintainer |

**What neither shows:**

- **The deadlock needs Kit:** no unit test can reproduce it.
- **It depends on timing:** a worker, not the waiting thread, must run the task. So E1's steps run three times on
  fresh Kits after the fix.
- **USD Composer:** it has no Isaac Sim core, so `get_joint_states` errors there by design.
- **Linux:** the live runs are on Windows.

## Docs

- **`docs/TOOLS.md`:**
  - `get_logs`: how it works, reading Kit's log file;
  - `get_joint_states`: works on 5.x and 6.x, needs physics playing or paused, the units;
  - `sim_control`: a robot's first play cooks its collision meshes, and Kit answers nothing until it ends, with E7's
    numbers.
- **`docs/ARCHITECTURE.md`:** the Threading Model's item 5, the Log Buffer section, and the Robot System's
  `get_joint_states` line.
- **`README.md`:** line 145 ("Driving a robot while physics plays hangs Isaac Sim 6.2 for now"), the Known issues
  entry for #5, and line 252's "need physics to have played once". For outcome B, the Known issues entry names the
  upstream issue instead.
- **`docs/SETUP.md`:** the Troubleshooting row for #5.
- **`plugin/skills/simulate/SKILL.md`:** the `get_joint_states` steps and its Traps row ("play the simulation once
  first" becomes "play or pause, not stop").
- **`CHANGELOG.md`,** Unreleased:
  - Fixed: Kit no longer stops answering when physics plays with a robot on the stage (#5); `get_joint_states` reads
    joint states on Isaac Sim 5.x and 6.x.
  - Changed: `get_logs` reads Kit's log file.
- **`AGENTS.md`,** Traps, a row: a Python `omni.log` consumer deadlocked Kit when a cooking worker logged while the
  main thread held the GIL | #5 | no Python callback on Kit's worker threads.

## Risks

| Risk | Status |
|---|---|
| H1 is wrong | Resolved by the order: E1 to E3 run before any code, and the Design is chosen after them |
| A1 misses messages: a Kit without a log file, or a file level above the consumer's | Accepted. E8 checks Isaac Sim's values; the error names the flag |
| A1 reads a large log file | Resolved: the first read is capped, and later reads take only the new bytes |
| A passing run hides the deadlock, since it depends on timing | Accepted: E1's steps run three times on fresh Kits after the fix |
| Another Python callback of ours runs on Kit's worker threads | Resolved by reading the bridge: the `omni.log` consumer is the only one. Recording's subscription runs on update events, on the main thread. Checked again at build time |
| #729's livelock stalls a play for minutes on this RTX 5090 even after our fix | Accepted: live runs that stall with H2's signs are recorded as #729, not ours |
| The experimental Articulation API changes names between releases | Accepted: the handler's error names the missing call, and the live suites catch it |
| An experiment leaves a hung Kit | Resolved by the rules: the session kills only the process it started |

## Questions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | If H1 holds: A1 (read Kit's log file) or A2 (asynchronous logging)? | A1: it removes the cause instead of moving the wait to another thread |
| Q2 | D (`get_joint_states`) in this issue, or its own? | Here: `test_14_04` can't pass without it, and both land in the robot phases |
| Q3 | Report the deadlock (E3b) or the hang (E3a) on isaac-sim/isaacsim, from your account? | Yes, after E3, with its script |
| Q4 | Will you run E9 on Isaac Sim 6.2's GUI? | Yes: agents don't drive your Isaac Sim |
| Q5 | If E4 finds a working flag: a docs-only PR with it now, or wait for the fix? | Now, if the fix is more than a few days away |
| Q6 | Is Isaac Sim 5.1 installed here for E6 and the live runs? | If not, the 5.x claim for `get_joint_states` rests on the source |

## Plan review

Not reviewed yet: `review-plan` runs once the main session has read this draft.
