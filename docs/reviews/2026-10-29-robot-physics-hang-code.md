---
subject: "Keep Kit answering when physics plays with a robot on the stage (#5, #50)"
base: main (b818449)
head: 930e9b6
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer on Claude Opus 5.5, read only; findings checked against the code by the main session)
verdict: needs-fixes
---

# Review: Kit's log read from its file, and joint states through the experimental Articulation

Read from the branch's diff against `main`, each touched file, the plan, and Kit's installed sources for Isaac Sim 6.2
and 5.1 (`omni/kit/app/_app.pyi`, `isaacsim.core.experimental.prims`, `isaacsim.core.simulation_manager`). One major,
fixed by `c785fbb`; three minors, fixed in `3d5d675` and `515fae6`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tests/test_integration.py`, `TestColdCook` and `_COLD_COOK_SCENE` | The cold-cook test didn't reproduce #5: 8 static convex-hull colliders cook without Kit's main thread waiting on the cooking workers, so `play` answered on `main`'s bridge (step 2a in 0.09 s, 2b in 0.4 s) and the test passed on unfixed code (REVIEW.md question 3) | fixed: `c785fbb`, 32 rigid bodies, whose shapes PhysX cooks while physics loads, with the main thread waiting. On `main`'s bridge the test as written stopped the run after 60 s with its #5 message; `c40c74b` records step 2 in the plan |
| F2 | minor | `tests/test_logs.py`, the guard | The match was case-sensitive, so `GLOBAL_EVENT_ERROR_LOG` and `GLOBAL_EVENT_ERROR_LOG_IMMEDIATE` (6.2 `omni/kit/app/_app.pyi:346-347`, 5.1 `:213-214`) passed it, and the immediate event is dispatched on the thread that logs, the #5 path | fixed: `3d5d675`, the scan lowercases what it reads; `test_the_guard_finds_each_hook` holds a sample of each hook name, both constants and both event names, and `test_the_guard_lets_logging_itself_pass` keeps `carb.log_error` out |
| F3 | minor | `tests/test_integration.py`, the cooked-spheres check (`c785fbb`) | `f"{root}/Sphere_{i}" in e["msg"]` let `Sphere_10` to `Sphere_31` match `Sphere_1` to `Sphere_3`, so a sphere that never cooked could count | fixed: `3d5d675`, `Sphere_00` to `Sphere_31` in the scene and the check |
| F4 | minor | the plan's Findings; the docs | E6's 1,000-call memory and handle check, step 2's outcome, and E6 and E8 on 5.1 were unrecorded | step 2 is in the plan (`c40c74b`); E6's check ran live (Live run) and is in Findings (`515fae6`). Isaac Sim 5.1 can't run on this machine: it crashes in its own `SimulationApp` start, before any bridge loads. So `get_joint_states`' docs, description and CHANGELOG line say it is tested live on 6.2, with 5.1 shipping the same class, untested live (`3d5d675`). E6 and E8 on 5.1 stay open |

Refuted, each from the code or the sources:

- **R1, a short configured token mangles the logs:** by design, redaction wins; SETUP.md asks for a long random
  token. An empty token can't happen (`extension.py:90`, `or new_token()`), and `redact` returns the text unchanged
  for one.
- **R2, a token split across lines escapes redaction:** Kit doesn't wrap lines; a partial last line waits whole
  (`end = data.rfind(b"\n") + 1`); after a cut the partial line is dropped (`_in_line`).
- **R3, a file replaced mid-run reuses the old offset:** Kit never swaps its file mid-run, and a shorter file resets
  the reader (`size < self._offset`).
- **R4, `Articulation()` loads physics while stopped:** it calls `_on_physics_ready` only when
  `_physics_sim_view__warp is not None` (6.2 `articulation.py:186-188`, 5.1 `:162-164`), which a stop clears
  (6.2 `simulation_manager.py:813-815`, 5.1 `:173-176`).
- **R5, Python callbacks leak per call:** both versions wrap bound methods in `weakref.proxy` (6.2
  `simulation_manager.py:1212-1215`, 5.1 `:737` and `:750`), and `Prim.__del__` deregisters them.
- **R6, the experimental prims are missing headless:** `isaacsim.exp.base.kit` enables them on 5.1 and 6.2, and
  `base.python.kit` depends on `isaacsim.exp.base`.
- **R7, Kit 107's header shapes don't parse:** every dated line in the newest 5.1 log and in all 31 local 6.2 logs
  matches `_HEADER`, the undated first line and `[24,251ms]` included; `[ext: ...] deps:` lines are continuations,
  rightly.
- **R8, `pytest.exit` is swallowed inside `unittest`:** `_pytest/unittest.py:301-302` re-raises `Exit` from
  `addError`; the run exits 2, not 1, but it stops.
- **R9, the timeout isn't a `TimeoutError`:** `client.py:172` re-raises it.
- **R10, `play` answers before physics loads:** `simulation.py:49` awaits `_next_update()` after `timeline.play()`.
- **R11, `carb.tokens` lacks the leave-token flag on Kit 107:** both stubs have
  `RESOLVE_FLAG_LEAVE_TOKEN_IF_NOT_FOUND = 1`.
- **R12, a `since_index` poller misses amended lines:** main-thread messages are written on the reader's own thread;
  a worker's message split across two reads is negligible.
- **R13, the tool breaks on a text `timestamp`:** it formats only `level`, `channel` and `msg` (`misc.py`).
- **R14, the `/logs` or `get_joint_states` fields change the contract:** `tests/fixtures/mcp-tools.json` is unchanged;
  only descriptions moved.

Also checked, no finding: no Python log hook is left in the extension; the reader runs only in `/logs` and
`mcp.get_logs`, on the main thread with no awaits, each read capped at 1 MB and 1 byte; `get_logs` sees a bridge
error right after it (Kit flushes every line, E8); an empty or unresolved `/log/file` returns the error naming
`--/log/file=<path>`; nothing calls `release_local_mesh_cache` or `get_cooking_statistics`, or touches
`DerivedDataCache`; the docs, CHANGELOG and AGENTS.md's Traps follow the Writing rules; ruff's per-file ignores only
shrink.

| Improvement | Answer |
|---|---|
| I1: F2's fix with a self-test of the matcher, so the guard's own reach is tested | taken with F2 (`3d5d675`) |
| I2: `LogRing.amend` copied the whole message for each continuation line, quadratic; Kit's extension dependency dump is some 1,650 lines and 130 KB in one entry | taken (`3d5d675`): a read gathers an entry's lines and joins them once, and a later read's continuation lines amend it once; `test_a_long_entry_is_joined_once_a_read` |
| I3: under a format other than Kit's default no line parses, and `get_logs` came back as an empty success | taken (`3d5d675`): the answer carries a `note` with the number of lines and the format `get_logs` reads, and the tool prints it; `test_logs_say_when_no_line_starts_an_entry`, `test_get_logs_passes_on_the_bridges_note`; TOOLS.md and CHANGELOG say so |
| I4: F3's fix, `Sphere_{i:02d}` | taken with F3 (`3d5d675`) |

Not covered: the reviewer ran nothing (the gate, the unit tests, the live suites); USD Composer, Linux, and Isaac Sim
5.1 live.

## Live run

Isaac Sim 6.2.0 (pip, headless, Windows, RTX 5090) on port 8212, a fresh Kit started for each run; the maintainer's
Isaac Sim on 8211 was not touched.

- **Step 2a, `main`'s bridge with its log consumer stopped, 8 static convex-hull spheres:** `play` in 0.09 s; Kit's
  log file named all 8 spheres in `ConvexMeshCookingTask` lines.
- **Step 2b, `main`'s bridge with the consumer on:** the same 8 static spheres played in 0.4 s, no hang (F1). With 32
  rigid-body spheres `play` had no answer after 30 s: the hang. As written in `c785fbb`, the test stopped the run on
  `main`'s bridge after 60 s with its #5 message, and that Kit was killed.
- **The fix, `930e9b6` with `c785fbb`, three fresh Kits, both live suites with nothing excluded:** 126 passed in each;
  the only failures were #7's three `draw_debug` scenarios, which its own PR fixes. Each run played the G1 (phase 10,
  and `test_14_04`'s joint reads, paused and then stopped) and the 32-sphere cold cook (`play answered; 32 spheres
  cooked`).
- **E6's growth check, on `c40c74b`:** the G1 played, then paused; 1,000 `get_joint_states` reads, 43 DOF each, all
  answered. Kit's working set was 5,020 MB before and 4,988 MB after, its handles 4,044 and 4,026; a read took
  12.5 ms at the start and 14.1 ms at the end. No growth, so a new `Articulation` per call stays. After `stop`, the
  read errors "No physics view of /World/G1_E6/pelvis: play or step the simulation first; joint states are read
  while it plays or is paused".

Not shown live: the round's fixes in `3d5d675`, which change the guard, the cold cook's sphere names and the log
reader's joins and note; Isaac Sim 5.1, which crashes here before any bridge loads; the GUI (E9, the maintainer's).

## Checks

`uv run tools/gate.py full` passed on `930e9b6` (773 tests, 94.04%) and on the round's fixes, `515fae6` (785 tests,
94.08%).
