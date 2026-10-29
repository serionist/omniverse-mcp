---
title: Keep Kit answering when physics plays with a robot on the stage
issue: "#5, #50"
status: approved
approved_by: serionist
approved_at: 2026-10-29
---

# Keep Kit answering when physics plays with a robot on the stage

On Isaac Sim 6.2, Kit stops answering when physics first plays with the G1 on the stage (#5). E1 and E2 (Findings)
showed why. Kit's main thread holds Python's GIL while it waits for a collision-cooking worker. That worker waits for
the GIL inside our bridge's Python `omni.log` subscription. With the subscription stopped, the same `play` answered in
0.6 s. This plan removes the subscription: `get_logs` reads Kit's log file instead. Separately, it makes
`get_joint_states` read through the articulation API Isaac Sim 5.1 and 6.x ship: tested live on 6.2, and untested
live on 5.x, which can't run on this machine (Findings).

## Goal

**When this is done:**

- On Isaac Sim 6.2, headless and GUI, with the bridge: `sim_control("play")` with the G1 on the stage returns, and Kit
  keeps answering. So does a play that cooks collision meshes from scratch.
- The bridge registers no Python callback with Kit's logging, and a CI test fails if one comes back.
- `get_logs` returns what Kit's log file holds since the extension started, with the bridge token redacted.
- `get_joint_states` returns joint positions and velocities while physics plays or is paused (D, its own issue on this
  branch).
- The live runs drop `-k "not test_10_ and not test_14_"`.

**In scope:**

- the bridge's log subscription and `get_logs`;
- `get_joint_states`'s articulation path, which can't work on Isaac Sim 5.1 or 6.2 today (D);
- the remaining experiments, the tests and the docs these touch.

**Out of scope:**

- NVIDIA's side: the GIL held across `force_load_physics_from_usd`, and isaac-sim/isaacsim#729's render livelock;
- Newton physics;
- `set_joint_targets`;
- the Y-up gravity tests (#6) and `draw_debug` (#7).

## What the code and the sources say

Each row is read from the code or from a source, not from memory. Isaac Sim's source is at
[isaac-sim/isaacsim](https://github.com/isaac-sim/isaacsim) (tags `v5.1.0` and `v6.2.0`). omni.physx's source is at
[NVIDIA-Omniverse/PhysX](https://github.com/NVIDIA-Omniverse/PhysX) under `omni/`, read at `release/110.3`, the
nearest published branch: Isaac Sim 6.2 runs Kit 110.4.0 (`deps/kit-sdk.packman.xml` at `v6.2.0`) and
`omni.physx.cooking` 110.4.4 (the 6.2.0 release notes). "Installed" means the copies on this machine: Isaac Sim 6.2 in
`D:\isaac`, and 5.1 (Kit 107.3.3) in `D:\isaacsim5.1`.

| # | Fact | Source |
|---|---|---|
| 1 | `test_14_04` calls `sim_control("play")` first. Nothing earlier plays physics after the G1 arrives in phase 10: phases 11 to 13 don't play, and recording doesn't start the timeline. So the G1's first physics load happens inside that `play` | `tests/test_scenarios.py` lines 808-812; `handlers/recording.py` has no `play()` |
| 2 | `get_joint_states` can't build an articulation on 5.1 or 6.2. `isaacsim.core.api.articulations` exports only `ArticulationGripper` and `ArticulationSubset` at both tags. `omni.isaac.core` is a deprecated extension at `v5.1.0` and gone at `v6.2.0`. The handler's `except Exception` turns the `ImportError` into an error result. `test_14_04` records that error as SKIP and passes | `handlers/robot.py` lines 196-205; `tests/test_scenarios.py` lines 814-817; `isaacsim.core.api/python/impl/articulations/__init__.py` at both tags |
| 3 | When the timeline plays, Isaac Sim loads physics from a Python callback: `SimulationManager._on_play` calls `initialize_physics()`, which calls `force_load_physics_from_usd()`. 5.1 does the same through `_warm_start` | `isaacsim.core.simulation_manager/python/impl/simulation_manager.py`: `v6.2.0` lines 431-440, 640-668, 711-733; `v5.1.0` lines 164-166, 234-237 |
| 4 | That binding doesn't release the GIL: `.def("force_load_physics_from_usd", wrapInterfaceFunction(&IPhysicsStageUpdate::forceLoadPhysicsFromUSD), ...)`. Carbonite's own bindings add `py::call_guard<py::gil_scoped_release>()` where they do release it | `omni/umbrella/bindings/BindingsPhysicsStageUpdate.cpp` line 90; Carbonite's `SettingsBindingsPython.h` and `TokensBindingsPython.h` for the idiom |
| 5 | Collision meshes are cooked as `carb.tasking` tasks on worker threads (`tasking->addTask(...)`). A synchronous request waits on the task's future with no timeout (`futureWait(-1)`, then `m_future.wait()`). A task the waiter finds not yet started runs on the waiting thread (`completeOpenTask`) | `omni/ovruntime/source/omni.physx.cooking/plugins/service/CookingTask.cpp` lines 154-175, 573-588; `CookingComputeService.cpp` lines 294, 810-825 |
| 6 | The cooking task logs from the worker: `CARB_LOG_INFO("ConvexMeshCookingTask: polygon limit reached, ...")`, and `CARB_LOG_WARN` when a hull isn't GPU-compatible. A log line carries no thread id, and a task run inline writes the same text. The hull's vertex limit is clamped to 64, the default, whatever `hullVertexLimit` says | `plugins/tasks/ConvexMeshCookingTask.cpp` lines 31-40, 126, 139-148 |
| 7 | Logging is synchronous by default. `/log/async`: "If true, logging a message does not block the thread calling the logging function ... Defaults to false". `ILog::log` "Sends the supplied message to all registered omni::log::ILogMessageConsumer objects", and "Each message may be sent to registered consumers in parallel" | [Carbonite logging](https://docs.omniverse.nvidia.com/kit/docs/carbonite/latest/docs/logging/Logging.html), [ILog](https://docs.omniverse.nvidia.com/kit/docs/carbonite/latest/api/classomni_1_1log_1_1ILog.html) |
| 8 | The bridge subscribes a Python function to `omni.log` when it starts, and Python code runs only with the GIL | `handlers/logging.py` (`log.add_message_consumer(self._on_log)`); `extension.py` lines 146-149 |
| 9 | NVIDIA documents the same kind of deadlock in Isaac Sim 6.2's own code: "the Python binding for shutdown_and_release_framework holds the GIL while releaseFrameworkAndShutdown() joins carb.tasking worker threads that may themselves be blocked waiting for the GIL" (NVBug 5948099) | `isaacsim.simulation_app/isaacsim/simulation_app/simulation_app.py` (`v6.2.0`) lines 991-995 |
| 10 | NVIDIA's own Python server can subscribe Python to Kit's log too, and warns about it: "Whether to publish incoming carb logging messages. Warning: enabling this feature may cause the application to freeze in certain circumstances", `carb_logs = false` | `isaacsim.code_editor.python_server/config/extension.toml` (`v6.2.0`) lines 28-30 |
| 11 | Kit's log defaults, the same in Kit 107.3 and 110.4: `level` and `fileLogLevel` "Info", `file` `${logs}/kit_${start_timestamp}.log`, `fileMaxCount` 30, `includeTimeStamp` true, `setElapsedTimeUnits` "milliseconds". Carbonite's `/log/fileFlushLevel` defaults to verbose, so every line is flushed at once | `kit/kernel/config/kit-core.json`, installed 6.2 and 5.1; [Carbonite logging](https://docs.omniverse.nvidia.com/kit/docs/carbonite/latest/docs/logging/Logging.html) |
| 12 | No test or experiment may call omni.physx's `release_local_mesh_cache()`. It reaches `UjitsoCookingComputeService::resetLocalMeshCacheContents`, which clears UJITSO's data store: the install's on-disk `kit/cache/DerivedDataCache`, 2.2 GB here, shared by RTX and Replicator and by any Isaac Sim run from this install. `get_cooking_statistics()` is "mainly needed for internal tests" | `omni/physx/bindings/_physx.pyi`: installed 6.2 lines 1987, 2021-2029; PhysX `ovphysx/ovruntime/source/omni.physx.cooking/plugins/ujitso/UjitsoCookingComputeService.cpp` (`main`) lines 515-538 |
| 13 | The experimental `Articulation` finds the articulation root differently by version: `fetch_articulation_root_api_prim_paths` in 6.2, `isaacsim.core.utils.prims.get_articulation_root_api_prim_path` in 5.1. `get_dof_positions()` and `get_dof_velocities()` return shape `(N, D)` | `isaacsim.core.experimental.prims/python/impl/articulation.py`: `v6.2.0` lines 577, 2010-2037; `v5.1.0` line 107 |
| 14 | `execute_script` logs nothing when a script raises: `handle_execute` catches the exception and returns its traceback | `handlers/misc.py` lines 109-111, 126-133 |
| 15 | SETUP.md tells a remote setup to pass the token on Kit's command line, `--/exts/ovmcp.bridge/token=<the token>`, and Kit writes its command line near the start of its log: the crashreporter's `commandLine:` and `[omni.kit.app.plugin] Cmd:` | `docs/SETUP.md` line 119; an installed 6.2 Kit log, lines 17 and 22 |
| 16 | A different upstream bug looks alike from outside, on the same GPU as this machine: `simulation_app.update()` "intermittently livelocks for 20-270+ seconds", "CPU pinned ~99% (one thread)", then "self-recovers". It is open on 6.0.1 under NVIDIA ticket 6649001 | [isaac-sim/isaacsim#729](https://github.com/isaac-sim/isaacsim/issues/729) |
| 17 | Isaac Sim 6.2's release notes list no known issue about hangs, cooking, the G1 or the Franka | [6.2.0 release notes](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/overview/release_notes.html) |
| 18 | Kit can hand Python its log in other ways too: the events `GLOBAL_EVENT_ERROR_LOG = 'omni.kit.app:error_log'` and `GLOBAL_EVENT_ERROR_LOG_IMMEDIATE = 'omni.kit.app:error_log:immediate'`, observed through `carb.eventdispatcher`, and omni.log's `add_channel_update_consumer` | `omni/kit/app/_app.pyi`: installed 6.2 lines 346-347, installed 5.1 lines 213-214 |

### The cause

**H1, confirmed by E1's py-spy dump and by E2:** Kit's main thread and a cooking worker deadlock over the GIL, through
our log subscription.

1. `play` runs `SimulationManager._on_play` in Python on the main thread, so the main thread holds the GIL. It calls
   `force_load_physics_from_usd()`, which keeps the GIL (fact 4). That call cooks the G1's collision meshes on
   worker threads and waits for each one (fact 5).
2. A cooking task logs (fact 6). `omni.log` runs every consumer on the thread that logged (fact 7). Our Python
   `_on_log` then waits for the GIL (fact 8).
3. The main thread waits for the task, and the task waits for the main thread's GIL. Neither moves. The bridge's event
   loop runs on that main thread, so nothing answers, and the cooking line is the last in the log.

**What H1 explains:**

- **The last log line** is the cooking task's own.
- **Phase 5 plays fine:** a cube needs no cooking, so no worker logs during that load.
- **Every run hangs again:** cooked data is finalised on the main thread after the task ends, so a Kit that was
  killed never cached it.
- **`main` before #3 hangs too:** the log subscription is older than #3.

**It needs all four conditions:**

- a cold cook, since a cache hit spawns no task;
- a task that runs on a worker, not on the waiting thread (fact 5);
- a line at a level the consumer gets;
- a Python consumer.

The regression test sets the first and the last, and makes the other two likely with several dense meshes. Only its
hang on `main` (step 2) shows that a worker logged (fact 6).

**Ruled out:**

- **H2, #729's livelock:** E1 showed Kit waiting (about a sixth of one core), not spinning. The worker's stack ends in
  `PyEval_AcquireThread` under omni.log's Python binding.
- **H3, only a slow cook:** E2 cooked the G1 cold in 0.6 s.

**Still open:** the Franka recorded in S8b of the modernization plan (E5 hasn't run), and whether 5.1 hangs the same
way (E5).

## Investigation

E1 and E2 ran (Findings) and decided the fix. The rest run on the main session's own Kit.

**Rules for every run:**

- port 8212, never the maintainer's Isaac Sim on 8211;
- `OMNI_KIT_ACCEPT_EULA` only as the maintainer set it;
- kill only the Kit process the session started.

**What each remaining experiment gates:**

- **Before the code it gates:** E8 before the log reader (step 3), E6 before D (step 7), E7 before `test_14_04`'s
  timeout (step 7) and the docs' cook time (step 8).
- **The upstream report only:** E3.
- **Alongside the build:** E4, E5 and E9.

| # | Experiment | What it shows | Gates |
|---|---|---|---|
| E1 | Reproduce with stacks: G1, `play`, py-spy | Done: H1 (Findings) | the fix |
| E2 | E1 after `log_buffer.stop()` | Done: `play` in 0.6 s (Findings) | the fix |
| E3 | **Without our bridge.** A `SimulationApp` script with no `ovmcp.bridge`: a new stage, a PhysicsScene, the G1 (`get_assets_root_path() + "/Isaac/Robots/Unitree/G1/g1.usd"`), `play`, 30 timed `app.update()` calls. Run (a) as is; (b) with `--enable isaacsim.code_editor.python_server --/exts/isaacsim.code_editor.python_server/carb_logs=true`, NVIDIA's own Python log subscriber (fact 10); (c) with `omni.log.get_log().add_message_consumer(lambda *args: None)` if (b) doesn't subscribe at start | That NVIDIA's stack alone deadlocks with any Python log consumer: (a) plays, (b) or (c) hangs. That is the repro to report, with nothing of ours in it | the upstream report |
| E4 | **Kit flags, subscription on.** E1's steps on a fresh Kit with a cold cache under (a) `/log/async` set true at runtime through `execute_script` before `play`; (b) `--/log/level=warn`; (c) `--/physics/cooking/ujitsoCollisionCooking=false` (E1's main thread waited inside `carb.ujitsoagent`) | A workaround for 0.2.0 users until a release carries A1; (a) also tests A2 | A3 |
| E5 | **The Franka, and 5.1.** E1's steps with `create_robot("franka", "/World/Franka")` on 6.2; then E1's steps with the G1 on Isaac Sim 5.1 | Whether S8b's Franka hang and Isaac Sim 5.1 hang the same way; the wording of Known issues and CHANGELOG | docs |
| E6 | **Joint states, on 6.2 and 5.1.** After a `play` that returns (E2's setup): `get_joint_states("/World/G1")` on today's code; an error naming `omni.isaac.core` is expected. Then through `execute_script`: the articulation root found by the bridge's USD walk (as `handle_get_robot_info` does), `Articulation(<root>)`, `is_physics_tensor_entity_valid()`, `dof_names`, and row 0 of `get_dof_positions().numpy()` and `get_dof_velocities().numpy()`. Do this while playing, paused and stopped. Time 20 constructions and reads, each with a new object. Then make 1,000 `get_joint_states`-shaped reads and compare Kit's memory and handle count before and after | D's read path on both versions, its behaviour while stopped, the cost of a new tensor view per call, and whether objects pile up | step 7 |
| E7 | **Cook time, warm.** E2 gave the cold figure: the G1 cooked in 0.6 s. Subscription off: `stop` and `play` again in one Kit, then `play` in a restarted Kit. Never `release_local_mesh_cache()` (fact 12) | How long a robot's play blocks Kit's main thread, cold and warm | steps 7 and 8 |
| E8 | **Kit's log file, on 6.2 and 5.1.** Read: `/log/file` as `carb.settings` returns it (resolved, or still holding `${logs}`, `${start_timestamp}` or `${pid}`); the values of `/log/level`, `/log/fileLogLevel`, `/log/fileFlushLevel` and `/log/async`; the first lines and the shape of a header line on each version; where the command line sits. Then, in one `execute_script`, log `carb.log_error("a\nb")`, a non-ASCII probe line, and `logging.getLogger("ovmcp.probe").error("x", exc_info=True)` inside an `except` block, and read the file's end at once, in-process. Last, the file's growth per minute at the default level, idle and with physics playing | The parser's input: path resolution, both header shapes, multi-line entries, encoding, flushing, how big a read can get, and which lines hold the command line | step 3 |
| E9 | **The GUI app, by the maintainer.** Isaac Sim 6.2's GUI with today's bridge, the G1, Play; then with the fix | That the GUI hangs too (its play path is the same) and that the fix holds there | step 8 |

## Findings

E1 and E2 ran on 2026-10-29, on Isaac Sim 6.2.0 (pip, headless, Windows, RTX 5090) on port 8212, with `main`'s
bridge (`2ea46d4`), through `create_robot("g1", ...)` then `sim_control("play")`. H1 holds: the hang is the bridge's
own `omni.log` consumer.

| Run | What happened |
|---|---|
| E1, bridge as it is, cold cook cache | `play` had no answer after 60 s; `/health` timed out for the next 8.5 minutes, when the run stopped; Kit's CPU time rose about 2.5 s per 15 s (about a sixth of one core), so waiting, not spinning |
| E1, `py-spy dump --native` of the hung Kit | **Main thread:** `run_isaac_port.py` `update` > `simulation_manager.py:668` `_on_play` > `:733` `initialize_physics` > `_physics` binding > `omni.physx.plugin` > `omni.physx.cooking.plugin` > `carb.ujitsoagent` > `carb.tasking` wait. **Thread 70636, a `carb.tasking` worker:** `carb.ujitsoagent` > `omni.physx.cooking.plugin` > `carb.dll` (logging) > `log\_log.cp312-win_amd64.pyd` (omni.log's Python binding) > `PyEval_AcquireThread`, waiting for the GIL the main thread holds |
| E2, a fresh Kit, cold cache, `log_buffer.stop()` through `execute_script` first | `play` answered in 0.6 s; `/health` answered at once and 11 s later, with physics running |

E8 and E6 ran on 2026-10-29 on the same Kit after E2 (6.2.0, the consumer still stopped), through `execute_script`;
neither could run on 5.1 (below). The lines below are invented to show the shapes, not copied.

| Run | What it found on 6.2 |
|---|---|
| E8, the settings | `/log/file` comes back resolved, with no `${...}` left, as an absolute path under the install's `kit/logs/Kit/<app>/<version>/kit_<date>_<time>.log`; `/log/level` and `/log/fileLogLevel` `Info`; `/log/fileFlushLevel` `verbose`, so every line is flushed; `/log/async` false; `/log/includeTimeStamp` true; `/log/setElapsedTimeUnits` `milliseconds`; `/log/fileAppend` false |
| E8, a header line | `2026-01-01T00:00:00Z [1,234,567ms] [Warning] [some.channel] the message`: a UTC timestamp, the elapsed time with thousands separators, the level spelled `Info`, `Warning`, `Error`, and the channel, empty (`[]`) for `carb.log_*` called from a script. The file's first line has no elapsed field: `2026-01-01T00:00:00Z [Info] [carb] Logging to file: <path>` |
| E8, multi-line entries | `carb.log_error("a\nb\nc")` writes `b` and `c` as lines of their own with no prefix, and `logging.error(..., exc_info=True)` writes the traceback the same way, its first line (`Traceback (most recent call last):`) unindented: any line that doesn't start with a header belongs to the entry before it |
| E8, encoding and flushing | A probe line with `é` and `✓`, and the two entries after it, were in the file and decoded as UTF-8 when read with `open(path, "rb")` from the same `execute_script`, right after logging them (309 bytes for the three) |
| E8, growth | 1.56 MB after 90 minutes of a Kit that ran both live suites twice: about 1 MB an hour at Info; a quiet Kit writes far less |
| E8, the command line | Near the top: the crash reporter's `commandLine:` (user name scrubbed) about line 17, and `[omni.kit.app.plugin] Cmd: ...` about line 22, each with every `--/...` setting in full: a token passed as `--/exts/ovmcp.bridge/token=...` would be there in the clear. Reading from the file's size when the extension starts skips both |
| E6, the root | The bridge's USD walk (`Usd.PrimRange(prim, Usd.TraverseInstanceProxies())`, the first prim with `UsdPhysics.ArticulationRootAPI`) finds the G1's root at `<robot>/pelvis` |
| E6, stopped | `Articulation(root)` builds (43 `dof_names`), and `is_physics_tensor_entity_valid()` is false: 65 to 120 ms. D answers "play or step the simulation first" here |
| E6, playing and paused | `is_physics_tensor_entity_valid()` true; `get_dof_positions()` and `get_dof_velocities()` give `(1, 43)` arrays; a new `Articulation` and both reads take 2 to 5 ms |
| E6, 1,000 reads | On this branch's bridge (`c40c74b`), the G1 played then paused: 1,000 `get_joint_states` reads, 43 DOF each, all answered. No growth: Kit's working set 5,020 MB before and 4,988 MB after, handles 4,044 and 4,026; 12.5 ms a read at the start, 14.1 ms at the end. D keeps a new object per call. After `stop`, the read errors "play or step the simulation first" |

**What E2 left behind:** Kit's cook cache, `kit/cache/DerivedDataCache`, was written during E2 and outlives the Kit.
The next G1 `play` on this machine cooks nothing and passes on unfixed code. Any evidence after E2 needs a cold cook
(Tests).

Step 2 and the fix's live runs, 2026-10-29, on 6.2.0 headless on port 8212, each on a fresh Kit:

| Run | What happened |
|---|---|
| 2a, `main`'s bridge, the consumer stopped, 8 static convex-hull spheres | `play` in 0.09 s; Kit's log file named all 8 spheres in `ConvexMeshCookingTask` lines |
| 2b, `main`'s bridge, the consumer on, the same 8 static spheres | `play` answered in 0.4 s: no hang, so the test as first written could pass on unfixed code. The next row changed the count and the body type together, so which of them makes the hang wasn't isolated |
| 2b, `main`'s bridge, the consumer on, 32 rigid-body spheres | No answer to `play` after 30 s: the hang. The test now uses 32 rigid bodies (`c785fbb`), and as written it stopped the run on `main`'s bridge after 60 s with its #5 message; that Kit was killed |
| The fix (`930e9b6` plus `c785fbb`), three fresh Kits, both live suites with nothing excluded | 126 passed in each; the only failures were #7's three `draw_debug` scenarios (fixed by its own PR). Each run played the G1 (phase 10, `test_14_04`'s joint reads among the passes) and the 32-sphere cold cook (`play answered; 32 spheres cooked`) |

**Isaac Sim 5.1 can't run on this machine.** Isaac Sim 5.1 (Kit 107.3.3, `D:\isaacsim5.1`, standalone, run
through `python.bat`) crashes in its own `SimulationApp` start, in the material library's `_preload_base_material`,
on the RTX 5090 with driver 617.42, before any bridge loads; three older crash dumps on that install show the same.
No 5.1 run is possible here, so the docs say `get_joint_states` is tested live on 6.2 and untested live on 5.x.

**Still to run:**

- on Isaac Sim 5.1, open while it can't start here: E6, E8, step 5's G1 suites and step 7's `get_joint_states`;
- E7 before the cook-time docs;
- E3 for the upstream report;
- E4, E5 and E9 alongside the build.

## Design

E1 and E2 settled the outcome: our log subscription is the cause. A1 is recommended; A2 is the fallback; A3 serves
0.2.0 users meanwhile. D is separate and applies anyway.

### A1: no Python callback on Kit's logging

`get_logs` reads Kit's log file instead of subscribing to `omni.log`.

- **No subscription.** The extension hands Kit's logging no Python callback in any form fact 18 lists: no
  `add_message_consumer`, `add_channel_update_consumer`, `add_logger` or `get_log_event_stream`, and no `error_log`
  event, by constant or by string. A CI test (Tests) scans `extension/ovmcp.bridge` and fails on any of them.
- **Where reading starts.** At startup the extension finds the file from `/log/file`, resolving `${...}` tokens
  through `carb.tokens` if the setting still holds them (E8). It records the file's size then. Reading starts there,
  as the subscription started at the extension's start. This also skips Kit's opening lines, which hold the command
  line (fact 15).
- **Each `/logs` request,** on the main thread, reads what Kit appended since the last read and parses it into the
  same `LogRing`. The query, `count`, `min_level`, `channel`, `search` and `since_index` keep their meaning, and
  `test_integration.py`'s use of `since_index` still holds.
- **Every read is capped:** at most the last 1 MB of the new bytes. 1 MB holds the ring's 2000 entries at up to
  500 bytes a line; E8's line lengths can move the cap. A day-long session (fact 11's Info level, measured by E8)
  then costs one bounded read, not a frozen main thread.
- **After a cut,** reading resumes at the first header line, not the first line start. The previous read's last entry
  is closed, so a traceback's tail beyond the cut never joins it.
- **Entries appear at once.** Each entry goes into the ring as soon as its header line is read. Continuation lines
  that arrive in a later read amend the ring's last entry, unless a cut came between.
- **The token is redacted.** The parser replaces the bridge token's value with `<redacted>` in every message,
  wherever it appears: a reload of the extension, or a script, could log it after startup.
- **In `ovmcp/core/logs.py`, Kit-free and unit-tested:**
  - the header-line parser, for every shape E8 finds on Kit 107 and Kit 110, the first lines included;
  - the header pattern, taking any separator inside the elapsed field (`[456,355ms]`; the comma may follow the
    locale);
  - continuation lines joining their entry, including across two reads, and never across a cut;
  - the tail reader: byte offsets, decoding with `errors="replace"`, `\r\n`, a partial last line kept for the next
    read, a shorter file starting over;
  - the token redaction;
  - the decision on the setting: an empty or unresolvable `/log/file` gives the error text naming `--/log/file=<path>`.
- **`handlers/logging.py`** keeps only the Kit calls: the setting, `carb.tokens`, and handing the core the token and
  the file.
- **Why:** it removes the whole class, not only the case we saw. A1 covers any Kit worker that logs while the main
  thread holds the GIL: physics cooking here, and asset loads or shader compiles elsewhere.
- **What the file holds:** Kit's file level is Info by default, the same as the global level our subscription
  received (fact 11). So by default `get_logs` sees what it saw before. `--/log/level=verbose` alone no longer adds
  verbose lines: they also need `--/log/fileLogLevel=verbose`. TOOLS.md says so. Every line is flushed at once
  (fact 11), which E8 checks.
- **What changes in an entry:**
  - `timestamp` becomes the file's text: the date and time, and the elapsed milliseconds where the line has them;
  - `module`, `source` and `func` are empty unless Kit's line carries them;
  - `total_captured` counts the entries parsed since the extension started, so bytes a capped read skips aren't
    counted.

### A2: keep the subscription, make logging asynchronous

The fallback, if E4a works and A1 can't read the file. The extension sets `/log/async` true at startup. A worker's log
call then returns at once, and Kit's own log thread waits for the GIL instead.

**Costs:**

- It changes a setting for the whole app; messages may appear "slightly out-of-order in the log" (Carbonite logging
  docs).
- Kit's log thread still contends for the GIL whenever Python runs.
- A log flush called with the GIL held would deadlock again.
- The guard test (Tests) would have to allow `add_message_consumer`.

**Rejected: pausing the subscription around `play`.** Play also comes from the GUI's button, from scripts and from
`step`, and the cooking messages lost meanwhile are the ones users need.

### A3: a workaround for 0.2.0

If E4 finds a flag that works, Known issues names it until a release carries A1.

### Upstream

The maintainer reports E3's repro on isaac-sim/isaacsim: the play callback holds the GIL across
`force_load_physics_from_usd` while cooking logs from workers, so any Python log consumer deadlocks Kit, NVIDIA's own
`carb_logs` option included (fact 10). The fix there, releasing the GIL in the binding, is NVIDIA's.

### D: `get_joint_states` through the articulation API Isaac Sim keeps

D has its own issue, #50 here until the main session opens it and puts its number in. It lands on this
branch, and the PR closes both. #5 doesn't need it to pass: `test_14_04` records SKIP on error (fact 2). Today's path
errors on 5.1 and 6.2.

- **The articulation root** comes from the bridge's own USD walk: the prim itself or the first descendant with
  `ArticulationRootAPI`, through instance proxies, as `handle_get_robot_info` already does. No version-specific
  lookup: 6.2 and 5.1 find roots differently (fact 13).
- **The read:** `isaacsim.core.experimental.prims.Articulation(<root>)`. Its source is in `v5.0.0`, `v5.1.0` and
  `v6.2.0`, but the live runs cover 6.2 only, since 5.1 can't run on this machine (Findings), so the docs say it
  is tested live on 6.2 and untested live on 5.x. The handler checks
  `is_physics_tensor_entity_valid()` first. It then reads `dof_names`, and row 0 of `get_dof_positions()` and
  `get_dof_velocities()`, which are `(N, D)`.
- **A new object per call,** unless E6 shows the cost matters. The cache goes: an object outlives a `stop`.
- **No physics load from the handler.** When the view isn't valid (stopped, or never played), the error is "play or
  step the simulation first". Loading physics from a handler would block the main thread the same way.
- **Without Isaac Sim's core** (USD Composer), the error names the missing extension.
- **Units:** radians for revolute joints and metres for prismatic ones. `set_joint_targets` takes degrees, USD's drive
  targets. TOOLS.md says both.
- **Alternatives:** `isaacsim.core.prims.SingleArticulation` is deprecated since 6.0.0 (its `extension.toml`).
  `omni.physics.tensors` directly would drop the dependency on Isaac Sim's core, but `create_simulation_view` takes
  different arguments in 5.1 and 6.2.

### Files

| File | Change |
|---|---|
| `extension/ovmcp.bridge/ovmcp/core/logs.py` | the parser, the tail reader, the redaction, the setting's decision |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/logging.py` | no consumer; the file's path and start offset, then reads before each query |
| `extension/ovmcp.bridge/ovmcp/bridge/extension.py` | no log subscription; the reader started with the token; no articulation cache to clear |
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/robot.py` | `handle_get_joint_states` as in D; `_articulation_cache` and `_clear_articulation_cache` go |
| `src/omniverse_mcp/tools/robot.py`, `src/omniverse_mcp/tools/misc.py` | the descriptions of `get_joint_states` and `get_logs` |
| `tests/test_logs.py` | the core's new cases, and the guard |
| `tests/test_integration.py` | the cold-cook test |
| `tests/test_scenarios.py` | `test_14_04` |
| docs | as in Docs |

## Compatibility

No one-way door moves.

- **The tool contract:** tool names, parameters, bounds and annotations stay. Only descriptions change, so
  `tests/fixtures/mcp-tools.json` doesn't.
- **The wire protocol:** `/logs` and `/robot/joint_states` keep their paths and request bodies.
- **`/logs` entries** keep their keys, but not all their meanings (A1, "What changes in an entry"):
  - `timestamp` is text;
  - `module`, `source` and `func` are empty unless Kit's line carries them;
  - `total_captured` counts parsed entries.

  `execute_script`'s `mcp.get_logs` sees the same. CHANGELOG and TOOLS.md say so.
- **What users notice:**
  - Kit no longer hangs when physics cooks collision meshes;
  - `get_logs` needs `--/log/fileLogLevel=verbose` as well as `--/log/level=verbose` for verbose lines;
  - `get_joint_states` reads joints, where it always errored on Isaac Sim 5.1 and 6.x: tested live on 6.2,
    untested live on 5.x. It errors while the timeline is stopped, saying to play first.
- **Settings:** the extension adds none. A2 would set Kit's `/log/async`, a Kit setting, not ours.
- **Kit apps:** Kit 107+ as before. `get_joint_states` needs Isaac Sim, as before. `get_logs` needs Kit's log file,
  which Kit apps write by default (fact 11).
- **Migration:** none.

## Steps

Test first: the regression test and the guard come before the fix, and the cold-cook test runs once against `main`'s
bridge.

1. **The remaining experiments,** as their gates say (Investigation); results go into Findings.
2. **The tests that fail today:**
   - the guard in `tests/test_logs.py`, which fails on `main` (it finds `add_message_consumer`);
   - the cold-cook test in `tests/test_integration.py`, in two runs on 6.2, each on a fresh Kit:
     - (a) its body through `play`, after `log_buffer.stop()`, then Kit's log file read directly. Its
       `ConvexMeshCookingTask` lines must name every sphere. If they don't, the meshes change until they do: a cook
       that logs nothing can't deadlock, and the test would prove nothing.
     - (b) the test as written, against `main`'s bridge. It should hang. The session kills that Kit and records the
       hang in Findings. This hang is the only evidence that a worker logged (fact 6). 5.1 stays open until E5.
3. **A1, core,** after E8: the parser, the tail reader, the redaction and the setting's decision in
   `ovmcp/core/logs.py`. The test data copies the shapes of E8's lines with invented paths, ids and values: real lines
   carry this machine's user folder and build ids. Proved by the new cases in `tests/test_logs.py`.
4. **A1, bridge:** the subscription goes, and the reader starts at the file's size. Proved by:
   - the guard passing;
   - the cold-cook test passing three times, each on a fresh Kit;
   - `test_24_*` and `test_integration.py`'s `set_material` log check passing.
5. **The G1 live:** `test_10_*` and `test_14_*` run again, on 6.2 headless and on 5.1 (5.1 open: Findings).
6. **A3, if E4 found a flag and the fix isn't released soon:** a Known issues line in its own docs-only PR (Q4).
7. **D,** after E6 and E7: `get_joint_states` as in D. `test_14_04` asserts success instead of recording a skip, and
   its `play` gets more than the suite's 10 s only if E7 says so. Proved live on 6.2; 5.1 open (Findings).
8. **Docs,** after E7 for the cook time: as in Docs, with the AGENTS.md trap row. The maintainer runs E9's second half
   on the GUI.
9. **Close with finish-work:**
   - `uv run tools/gate.py full`;
   - `review-code` until clean;
   - a draft PR that closes #5 and D's issue, and states the live runs: which suites, on Isaac Sim 6.2 headless,
     the GUI by the maintainer, and what they couldn't show. It names the departure from this plan: no run on
     Isaac Sim 5.1, which crashes in its own start on this machine (Findings).

## Tests

| Suite | What |
|---|---|
| Unit, CI: the guard (`tests/test_logs.py`) | Fails if any file under `extension/ovmcp.bridge` contains `add_message_consumer`, `add_channel_update_consumer`, `add_logger`, `get_log_event_stream` or `error_log`. `error_log` catches both event constants and both event strings, `'omni.kit.app:error_log'` and `'omni.kit.app:error_log:immediate'` (fact 18). It fails on `main` today. AGENTS.md's trap row names it |
| Unit, CI: the reader (`tests/test_logs.py`) | Invented lines in the shapes E8 finds, never copied lines: real ones carry this machine's user folder and build ids. Cases: both first-line shapes (Kit 107's without a timestamp, Kit 110's with a timestamp and no elapsed time); the elapsed field with a comma, a dot or no separator; every level; the channel; a multi-line `carb.log_error`; a logged traceback; continuation lines split across two reads, amending the ring's last entry; a cut landing on a traceback's continuation lines, which resumes at the next header and leaves the previous entry as it was; `\r\n`; invalid UTF-8 replaced, not raised; byte offsets after non-ASCII text; a partial last line kept for the next read; a shorter file starting over; a read over 1 MB cut to its last 1 MB; the token redacted wherever it appears; an empty or unresolved `/log/file` giving the error text. The existing ring and query tests stay. The coverage floor holds |
| Live, new: the cold-cook test (`tests/test_integration.py`, last in the suite) | Through `execute_script`, on a stage with a PhysicsScene: 32 dense mesh spheres, `Sphere_00` to `Sphere_31`, a few thousand vertices each, each jittered by its own seed drawn for this run. So every sphere is new to every cache, and no cache is cleared (fact 12). Each is a rigid body with `CollisionAPI` and the `convexHull` approximation: in step 2, 8 static colliders played on `main`'s bridge without a hang, and 32 rigid bodies hung it. Then `sim_control("play")` with a 60 s timeout, its time printed. Without an answer, the test calls `pytest.exit(...)`, naming #5 and saying Kit is hung and must be killed, so `test_scenarios.py` doesn't run into it. Assertions: `play` answers; `get_logs(count=2000, channel="omni.physx.cooking", search="ConvexMeshCookingTask")` names all 32 test prims. A cache hit spawns no task, so each name is a cook. That a worker logged is shown only by step 2's hang on `main`. Cleanup: stop, delete the spheres |
| Live, changed | `test_14_04` asserts that `get_joint_states` succeeds (D, step 7); its `play` keeps the suite's 10 s unless E7 says otherwise; `test_10_*` and `test_14_*` run again |
| Live, suites | `test_integration.py` and `test_scenarios.py` on Isaac Sim 6.2 headless, and on 5.1 once it can run here (Findings); E9 on the GUI by the maintainer |

**What neither shows:**

- **The deadlock needs Kit:** the guard keeps the cause out, and only the live test shows the hang gone.
- **USD Composer:** it has no Isaac Sim core, so `get_joint_states` errors there by design.
- **Linux:** the live runs are on Windows.
- **Isaac Sim 5.1:** it crashes in its own start on this machine, so nothing ran on it (Findings).
- **The Franka:** E5 alone, unless it shows a different cause.

## Docs

- **`docs/TOOLS.md`:**
  - `get_logs`: it reads Kit's log file from the extension's start; it holds Info and above by default, and verbose
    needs both `--/log/level=verbose` and `--/log/fileLogLevel=verbose`; the token is redacted; `timestamp` is text and
    `total_captured` counts parsed entries;
  - `get_joint_states`: tested live on 6.2 and untested live on 5.x, needs physics playing or paused, the units;
  - `sim_control`: a robot's first play cooks its collision meshes, and Kit answers nothing until it ends, with E7's
    numbers.
- **`docs/ARCHITECTURE.md`:**
  - line 113's "`logs.py` (the log ring and its query)", which gains Kit's log file reader;
  - the Threading Model's item 5;
  - the Log Buffer section;
  - the Robot System's `get_joint_states` line.
- **`README.md`:**
  - line 145 ("Driving a robot while physics plays hangs Isaac Sim 6.2 for now");
  - the Known issues entry for #5;
  - line 252's "need physics to have played once".
- **`docs/SETUP.md`:** the Troubleshooting row for #5.
- **`plugin/skills/simulate/SKILL.md`:** the `get_joint_states` steps and its Traps row ("play the simulation once
  first" becomes "play or pause, not stop").
- **`CHANGELOG.md`,** Unreleased:
  - Fixed: Kit no longer stops answering when physics plays with a robot on the stage (#5);
  - Fixed: `get_joint_states` reads joint states (#50): tested live on Isaac Sim 6.2, 5.1 untested live;
  - Changed: `get_logs` reads Kit's log file. `timestamp` is text, `module`, `source` and `func` can be empty,
    `total_captured` counts parsed entries, and verbose lines need `--/log/fileLogLevel=verbose`.
  - The versions affected follow E5.
- **`AGENTS.md`,** Traps, a row: "A Python `omni.log` consumer of ours deadlocked Kit: a cooking worker logged while
  the main thread held the GIL | #5 | No Python log hook in the bridge, enforced by `tests/test_logs.py`'s guard;
  `get_logs` reads Kit's log file".

## Risks

| Risk | Status |
|---|---|
| A warm cook cache makes the regression test pass on unfixed code | Resolved: each sphere has its own jitter, so every run's spheres are new to every cache; the test asserts that all 32, `Sphere_00` to `Sphere_31`, are named in cooking lines |
| The test, or an experiment, wipes the install's shared `DerivedDataCache` | Resolved: nothing calls `release_local_mesh_cache()` (fact 12) |
| The test's cooking logs nothing, or runs every task on the waiting thread, so it can't deadlock | Resolved by step 2 on 6.2: every sphere is named in cooking lines, and the test hangs on `main`'s bridge with 32 rigid bodies, where 8 static colliders didn't (Findings). 5.1 stays open: it can't run here |
| A regression hangs whichever Kit the suite runs against | Accepted: the test stops the run with `pytest.exit`, naming #5 and saying Kit must be killed, so the later suites don't pile timeouts on it |
| `get_logs` exposes the bridge token from Kit's command line | Resolved: reading starts at the file's size when the extension starts, and the parser redacts the token; a unit test covers it |
| A `/logs` read after a long session freezes the main thread | Resolved: every read is capped at 1 MB of the newest bytes |
| A1 misses messages: a Kit without a log file, or a global level below the file's | Accepted. Kit apps write one at Info by default (fact 11); the error names the flag, and TOOLS.md says how to get verbose lines |
| Another Python hook on Kit's threads comes back later | Resolved: the guard test fails in CI |
| #729's livelock stalls a play on this RTX 5090 even after the fix | Accepted: a stall with H2's signs (one core busy, recovery) is recorded as #729, not ours |
| The experimental Articulation API changes between releases | Accepted: D's error names the missing call, and the live suites on 6.2 catch it; 5.x is untested live |
| An experiment leaves a hung Kit | Resolved by the rules: the session kills only the process it started |

## Questions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | A1 (read Kit's log file) or A2 (asynchronous logging)? | A1: it removes the cause instead of moving the wait to another thread | As recommended (the maintainer, 2026-10-29) |
| Q2 | Report E3's repro on isaac-sim/isaacsim, from your account? | Yes, with NVIDIA's own `carb_logs` option as the trigger | As recommended (the maintainer, 2026-10-29) |
| Q3 | Will you run E9 on Isaac Sim 6.2's GUI, before and after the fix? | Yes: agents don't drive your Isaac Sim | As recommended (the maintainer, 2026-10-29) |
| Q4 | If E4 finds a working flag: a docs-only PR with it now, or wait for the fix? | Now, if the fix is more than a few days away | As recommended (the maintainer, 2026-10-29) |

The maintainer approved the plan on 2026-10-29. This fix lands first: the other plans' live runs that play physics
with a robot wait for it.

## Plan review

### Round 1

`review-plan` on Claude Opus 5.5 (`claude-opus-5-5`), 2026-10-29, on `f4592af` (the draft and E1 and E2's findings).
Verdict: `needs-fixes`, one major and eight minors, all fixed in `fc23d49`.

| # | Severity | Finding | Status |
|---|---|---|---|
| P1 | major | The regression test could pass on unfixed code: the deadlock needs a worker to log while cooking, and E2's warm `DerivedDataCache` cooks nothing. "Three fresh Kits" proves nothing either. No CI guard, and E5 hadn't run but the Franka was claimed to hang | Fixed: the cold-cook test (new meshes every run, `release_local_mesh_cache()`, cache misses and a worker's log line asserted), run once on `main`; the CI guard, named in the AGENTS.md row; no Franka claim (Tests, Steps 2 and 4, Risks). Round 2 replaced the cache release, the cache-miss count and the worker claim (P10 to P12) |
| P2 | minor | E8's `raise ValueError` through `execute_script` logs nothing (fact 14); Kit 107 and 110 headers differ | Fixed: `carb.log_error("a\nb")` and `logging.getLogger(...).error(..., exc_info=True)`; E8 on 5.1 too |
| P3 | minor | The file is Info by default, not every level | Fixed: fact 11; A1's "What the file holds"; TOOLS.md and CHANGELOG |
| P4 | minor | Only the first read was capped | Fixed: every read capped at 1 MB from a line start; a unit test |
| P5 | minor | Reading from Kit's start exposes the command line, where SETUP.md puts the token | Fixed: reading starts at the file's size when the extension starts, and the parser redacts the token; a unit test |
| P6 | minor | No closing steps | Fixed: Step 9, finish-work |
| P7 | minor | Which experiments gate what was unclear; outcome A still depended on E3b | Fixed: Investigation's gates and Findings' "Still to run"; E3 serves only the upstream report; the outcome table went |
| P8 | minor | `fetch_articulation_root_api_prim_paths` is 6.2-only; the reads are `(N, D)` | Fixed: the bridge's USD walk finds the root; `is_physics_tensor_entity_valid()` first; row 0 (D, fact 13) |
| P9 | minor | Not every `/logs` field survives; the empty-setting decision belonged in core | Fixed: Compatibility, CHANGELOG and TOOLS.md list `timestamp` and `total_captured`; the decision is in core with a unit test |

**Improvements:**

| Improvement | Answer |
|---|---|
| D gets its own issue on the same branch | taken: the main session opens it; the PR closes both |
| NVIDIA's `python_server` `carb_logs` option as a repro without our bridge | taken: E3b, and fact 10 |
| Isaac Sim 5.1 is installed at `D:\isaacsim5.1` (Kit 107.3.3) | taken: E5, E6 and E8 run on it; the old Q6 is gone |
| E4 adds `ujitsoCollisionCooking=false`, and sets `/log/async` at runtime | taken: E4a and E4c |
| `test_logs.py` cases from real logs | taken: the reader's row in Tests; round 2 made the data invented in the same shapes (P15) |
| E6 measures a new tensor view per call | taken: E6, and D's "a new object per call, unless E6 shows the cost matters" |
| E8's list: the setting's form, the values, header shapes, a multi-line entry, a non-ASCII probe read back at once, growth per minute, where the command line sits | taken: E8 |

### Round 2

`review-plan` on Claude Opus 5.5 (`claude-opus-5-5`), 2026-10-29, on `fc23d49`. Verdict: `approved`: no blocker or
major, and round 1's P1 to P9 confirmed fixed. Seven minors, all fixed in this revision.

| # | Severity | Finding | Status |
|---|---|---|---|
| P10 | minor | `release_local_mesh_cache()` clears the install's on-disk `DerivedDataCache` (2.2 GB here, shared by RTX, Replicator and the maintainer's Isaac Sim), so a test run would wipe it | Fixed: dropped from the test and from E7; fact 12 forbids it; a Risks row |
| P11 | minor | Cooking statistics are "mainly needed for internal tests", and the counter is unproven under UJITSO; 8 copies of one mesh cook once | Fixed: each sphere gets its own jitter; the test asserts 8 distinct spheres in `ConvexMeshCookingTask` lines, and step 2a checks that they appear |
| P12 | minor | A log line carries no thread id, so it doesn't show a worker logged; a raised `hullVertexLimit` is clamped to 64 | Fixed: fact 6; the limit dropped; step 2b's hang on `main` is the evidence, on 6.2, with 5.1 open until E5 |
| P13 | minor | The guard missed the `error_log` event strings and `add_channel_update_consumer` | Fixed: fact 18; the guard matches `error_log` and `add_channel_update_consumer` |
| P14 | minor | A capped read could cut inside a traceback and glue its tail onto the previous entry | Fixed: after a cut, reading resumes at the next header and the previous entry is closed; a unit case |
| P15 | minor | E8's real lines carry this machine's user folder and build ids | Fixed: the test data is invented in E8's shapes (step 3, Tests) |
| P16 | minor | Docs missed ARCHITECTURE.md line 113; E7's gate and `test_14_04`'s step disagreed; line 181 overflowed | Fixed: the Docs list; E7 gates step 7's timeout and step 8's docs; the line rewrapped |

**Improvements:**

| Improvement | Answer |
|---|---|
| On a `play` timeout the cold-cook test calls `pytest.exit(...)`, with a Risks row | taken: Tests and Risks |
| The header pattern takes any separator in the elapsed field | taken: A1 and the reader's cases |
| Emit each entry at once and amend the ring's last entry when a continuation comes later | taken: A1's "Entries appear at once" |
| E6 checks growth over 1,000 `get_joint_states` calls | taken: E6 |
| "5.1 and 6.x" unless 5.0 is checked | taken: Goal, D, Compatibility, Docs |
| D's issue number goes in once opened | taken: D names `#50` until then |
