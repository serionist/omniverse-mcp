---
subject: "Name Kit's log levels as carb numbers them, and filter on them (PR #23)"
base: main (f576ac3)
head: a694ec7
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: name Kit's log levels as carb numbers them, and filter on them

Read only, with probes: the reviewer ran `tests/test_logs.py` against variants of `logs.py`, and read carb's headers
in two local Isaac Sim installs. One minor, in the PR's text; fixed with the improvements in
`5e0868e`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | PR #23's description, "Tested by" | It said nothing in the live suites reads levels; `test_scenarios.py`'s `test_24_02_get_logs_level_filter` asserts each entry after `min_level="warn"` is named warn, error or fatal. That test passed on the old table without testing anything: the old threshold kept only fatal messages, which the old table named `warn`. | Fixed: the description says so, and the test now logs a warning and an info message of its own and checks the filter keeps one and drops the other (below). |

Refuted, each from a source or a probe:

- **Another Kit numbers the levels differently:** `carb/logging/Log.h` has `kLevelVerbose = -2` to `kLevelFatal = 2`
  and `omni/log/ILog.h` `eVerbose = -2` to `eFatal = 2` (`eDisabled = 3` never comes with a message), the same in
  Kit 107.3.3 (Isaac Sim 5.1) and 107.3.1 (Isaac Sim 5.0); with the author's read on Isaac Sim 6.2, that covers the
  supported range. USD Composer ships the same carb, not tested.
- **Something else reads the numbers:** `logs.py` strips `level_num`; the server's `get_logs` formats the name only;
  the client and the in-script `mcp.get_logs` pass `min_level` through; the docs name the levels, no numbers.
- **The `min_level` contract changed:** the same five names, case-sensitive as before; an unknown or empty name
  filters nothing.
- **The tests miss a part:** on main's `logs.py`, two tests fail; with the new table and the old filter,
  `min_level="warn"` fails; with an unknown name taken as 0, the `"nonsense"` case fails.

Improvements:

- Cite `carb/logging/Log.h` in `logs.py` rather than "read on Isaac Sim 6.2": taken.
- Let `test_24_02` catch #21: taken. It logs a warning and an info message through `carb.log_*` with a marker of its
  own, and asserts `min_level="warn"` returns the warning, named `warn`, and `min_level="info"` both.
- The thread test's writer used levels 3 and 4, which Kit doesn't: taken, it uses -2 to 2.
- `### Fixed` before `### Changed` in CHANGELOG: left; the file orders its sections by importance.

## Live run

Isaac Sim 6.2.0, headless, port 8212, this branch's extension. Before the review, `get_logs` named the levels seen
info, warn and error, and `min_level` warn, error and fatal kept the right invented messages. After it, phase 24 of
the scenario suite (6 tests, `test_24_02` among them) passed twice in one Kit session.

## Checks

- **Gate:** `uv run tools/gate.py full` passed all 14 checks on `a694ec7` and after the fixes.
