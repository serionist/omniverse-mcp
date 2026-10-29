---
subject: "S6, strict tests, the Kit-free core, the import contracts and the coverage floor (PR #16)"
base: main (a0799ab)
head: d15963c
date: 2026-10-28
round: 1
tier: split (36 files: one fresh reviewer for the extension's code, one for the tests, the docs and the harness; findings checked against the code by the main session)
verdict: needs-fixes
---

# Review: S6, strict tests, the Kit-free core, the import contracts and the coverage floor

Read only, from the pack. The extension reviewer applied plan-and-intent, implementation, tool-contract,
kit-main-thread, bridge-security and compatibility; the harness reviewer applied tests, docs-freshness, simplicity and
harness-integrity. Every finding is a minor, so there is no round 2: the fixes are in `fc4b295`, checked in this
session.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `bridge/handlers/camera.py`, imports; `core/png.py` | camera.py imported the PNG writer at load, and the writer imports numpy at module level. In a Kit app without numpy on its path, `handlers/__init__.py` → `camera` → `core.png` would raise ImportError and every route would be gone, `/health` included; on main only segmentation and the screen boxes needed numpy (camera.py imported it lazily and `_is_image_black` treats it as optional). Not shown on a shipping Kit 107+ app, which all carry numpy. | Fixed: `encode_png` is imported in `_capture_instance_segmentation`, its one caller, beside that function's own numpy import; no Kit-bound module imports numpy at load. The scenario suite's segmentation tests pass live on it (Live run). |
| F2 | minor | `tools/gate.py`, `check_coverage_floor` | With no `fail_under` in pyproject.toml, `f"{floor:g}%"` raised TypeError, which `run_lane` doesn't catch: a traceback, and the rest of the gate never ran. It still failed closed. | Fixed: the detail is built only for a floor; the reason "pyproject.toml sets no fail_under" now reaches the table. Test: `test_no_floor_fails_with_its_reason`, on a throwaway repo. |
| F3 | minor | `tools/gate.py`, `check_coverage_floor` | The floor was compared with the range's left side, `origin/main`'s tip: once main raised its floor (S7 will), a branch cut before, that never touched it, failed `gate quick` with "the coverage floor fell". | Fixed: each range's floor is read at the merge base of its two ends, labelled with the base's name when they are the same commit. Tests: `test_a_branch_behind_main_keeps_the_floor_it_started_from`, `test_a_branch_that_lowers_the_floor_fails`. |
| F4 | minor | `tests/conftest.py`, `LIVE_HOST`, `LIVE_PORT` | The port was read at import with `int(os.environ.get(...))`, unlike the server, which treats an empty variable as unset: `OMNIVERSE_MCP_PORT=` or a non-number broke every test at collection, unit tests and the gate included. | Fixed: `live_bridge()` reads the address with the server's own `parse_args([])` when a live suite starts. By hand: the whole suite passes with `OMNIVERSE_MCP_PORT` empty and with `abc`. |
| F5 | minor | PR #16's description | It said "The live suites: see below." with nothing below, for a change to the Kit-bound handlers (REVIEW.md question 4). | Fixed: the description reports the live runs (below). |

Refuted, each from the code:

- **`children()` differs from `GetChildren()`:** `GetChildrenNames()` gives the names of
  `GetFilteredChildren(UsdPrimDefaultPredicate)` in the same order, and `GetChild` resolves them; an instance gives no
  children either way, and `isolation.take` handles `IsInstance()` first.
- **`Tf.Type.Find` or `GetChildrenNames` missing from older USD:** `IsA(class)` already relied on the same
  class-to-TfType lookup; `GetChildrenNames` predates USD 24.05, which Kit 107 ships.
- **numpy 1.26 breaks `NDArray[Any]` at runtime:** `numpy.typing.NDArray` exists from 1.21, and the calls used behave
  the same; the PNG bytes match main's.
- **`/logs` output changed:** `{"index": ..., **entry}` restores main's key order once `level_num` is stripped.
- **Relationships print differently:** the explicit branch writes the `<unreadable>` line main's caught AttributeError
  wrote.
- **The screen box drifts:** `screen_box` repeats main's arithmetic; Python's and numpy's `min` differ only on NaN.
- **Broken callers, Kit in the core, a route's security, threads:** no reference to a moved name is left; the core
  imports the standard library, pxr and numpy only; `http.py` changed only annotations and a `cast`; nothing new runs
  off Kit's main thread.
- **An ignore added for `core/formatter.py`:** the moved file's list shrank (`RUF059` and `SIM102` gone), and
  `TID252` left `recording.py` and `scene.py`.
- **A base of zeros, or a string `fail_under` on main:** `hooks.py` and `ci.yml` replace a zero or unknown base; a
  tree whose floor reads as None always fails, so main can't hold one.
- **A check weakened:** the baseline lost 11 entries, basedpyright gained strict on the core, and no skip, xfail,
  noqa or pragma was added beyond D11's marker.

Not covered: Kit 107 or USD 24.05 at runtime; the compatibility claims rest on the USD source, usd-core 26.11 and
Isaac Sim 6.2.

Improvements:

- The live suites' skip branches, which conftest made unreachable, and a docstring that said "skip": taken in
  `fc4b295`; each suite now checks the bridge and fails.
- `test_isolation.py` skipped without usd-core while the new pxr tests import it directly: taken; a missing usd-core
  fails it.
- `precision = 2` in `[tool.coverage.report]`, so 58.5% doesn't round up past a floor of 59: taken.

## Live run

Isaac Sim 6.2.0 (pip install, Python 3.12), headless, on port 8212 with this branch's `extension/`, beside the
maintainer's own Isaac Sim on 8211, which the runs never touched (`OMNIVERSE_MCP_PORT=8212`).

- At `d15963c`: integration 27/27. Scenarios 83 passed, 5 failed, 7 deselected (`test_10_*` and `test_14_*`, the G1
  robot that hangs Kit, #5). The 5 fail on main too: `test_05_03` and `test_07_02` assume a Y-up stage (#6), and
  `test_16_03` to `test_16_05` need `isaacsim.util.debug_draw` (#7). The recording's `state.txt` came from the moved
  formatter: 28 frames, the cube's Z changing and Y fixed at 3, which is #6.
- At `fc4b295`, after the fixes: the same, integration 27/27 and scenarios 83 passed with the same 5 failures.
- With `OMNIVERSE_MCP_SIM=1` and nothing listening (port 8213), the 27 integration tests fail with "connection
  refused" instead of skipping.
- Not shown: Kit 107 and Isaac Sim 5.x; USD Composer.

## Checks

- **Gate:** `uv run tools/gate.py full` passed all 14 checks on `d15963c` (446 passed, 124 skipped: the live suites,
  without `OMNIVERSE_MCP_SIM=1`) and on `fc4b295` (449 passed; coverage 59.55% against the floor of 59).
- **The live suites' address:** the whole suite passes with `OMNIVERSE_MCP_PORT` empty and with `abc`.
- **The formatter:** main's formatter and the new one, on the same usd-core stages, gave the same text in 9 cases
  (scene dumps with and without properties, filtered, depth-limited, a missing root; blocks with bounds and an empty
  prim; frames; values).
- **The log trap:** with the copy under the lock removed, `test_a_query_while_kit_logs_from_another_thread` failed 3
  runs in 3 with "deque mutated during iteration"; with it, it passed 3 in 3.
- **The import contracts:** a function-level `import carb` in `core/png.py`, and an `import ovmcp.core.protocol` in
  `config.py`, each broke its contract.
