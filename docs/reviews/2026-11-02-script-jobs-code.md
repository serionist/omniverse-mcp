---
subject: "Run a long script as a job that Kit keeps rendering through, read and cancelled by id, a change to the tool contract and the routes (#158)"
base: main (6df788e)
head: aaca43f
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the compiler, the output router, the job board and the handlers; the tools, the contract, the docs, the live tests and the AI suite"
verdict: needs-fixes
---

# Review: Run a long script as a job

Read from the branch's diff against `main` at `6df788e` (39 files, about 3,500 lines with the plan) by two fresh
reviewers, read only, against the approved plan `docs/plans/2026-11-02-script-jobs.md` and the maintainer's agreement
on #158. One read `ovmcp/core/script.py`, `output.py`, `jobs.py`, `handlers/jobs.py`, `handle_execute` and their tests,
checking the compiler's behaviour on Python 3.11, 3.12 and 3.14; the other the server's three tools, the contract, the
docs, the live tests and outcome O7 against `tools/scenarios.py`. One major (G1), three minors. The two reviewers
numbered their findings apart: F for the first, G for the second; the plan's build notes use the same ids.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| G1 | major | `test_project/outcomes.md` O7, against `tools/scenarios.py` `run_sessions` and `settle` | O7 could never pass: the runner stops the timeline before every judge, and a stop puts each crate back where it hung, so a judge always found 150 crates 1 m up and the timeline stopped, against "rests on the floor" and "paused, not stopped" | fixed in `5ed515d`: `Play: 3 s` after the settle drops every released crate; Verify reads the release from `kinematicEnabled`, the poses after that play, the order and timing from the job's calls and `get_job()`; `test_the_real_outcomes_parse_with_no_problem` asserts `play == 3.0` and `get_job()` in the Verify. Checked live that a stop leaves `kinematicEnabled` as the script set it |
| F1 | minor | `core/output.py` `collect`, `handlers/misc.py` `handle_execute`, `core/jobs.py` `_run` | A script that replaced `sys.stdout` (`sys.stdout = io.StringIO()`, or `sys.__stdout__`) left it there for the session, where the old `/execute` swap put Kit's stream back: Kit's prints went to the replacement without limit | fixed in `8e24c77`, then `ba4cd61` (F4): the block puts the router back when its code replaced it; `test_a_block_puts_back_the_router_its_code_replaced`, `test_a_script_that_replaces_sys_stdout_leaves_the_router_in_place` (both parameters), `test_a_job_that_replaces_sys_stdout_leaves_the_router_in_place` |
| F2 | minor | `core/script.py` `NEVER_AWAITS`, `handlers/jobs.py` `handle_job_script` | A script that defines `async def main()` and ends with `asyncio.ensure_future(main())`, the usual Kit idiom, was refused, rightly, but told it "would hold Kit's main thread from its start to its end" and to await in its loop, which `main` already did | fixed in `8e24c77`: the refusal and the description say a coroutine only defined or scheduled doesn't count and to `await main()` at the top level; `test_a_script_that_only_schedules_its_coroutine_is_told_to_await_it`, and `test_contract.py` pins the description |
| F3 | minor | `core/output.py` `install`, `collect` | A request in flight when the bridge shut down resumed after `uninstall()` and put the old module's router back over Kit's stream, where the next instance stacked its own | fixed in `8e24c77`: after `uninstall` nothing is installed or put back; `test_after_uninstall_a_call_still_in_flight_installs_nothing`, `test_a_block_after_uninstall_puts_nothing_back` |

**Refuted,** from the code and from measurements on 3.11, 3.12 and 3.14:
- **A way past the token, `Origin` or `Host` checks:** the three `/jobs/*` routes join the same table, and `refusal()`
  runs before the route is looked up.
- **`file` widens access:** `/execute` already reads any file; the token stays the boundary.
- **`/execute` changed for indented or `yield` scripts:** the old wrapper failed on both too.
- **Top-level await's names:** `FunctionType(code, ns)()` writes them into the namespace; a returning script keeps the
  old `locals().get('result')`.
- **A NaN `wait`:** `get_job` bounds it `ge=0, le=100`, which refuses NaN; only a caller with the token could send one,
  and that caller can run `/execute`.
- **The board's `closed` refusing every start after a re-enable:** Kit drops the extension's modules on disable, so a
  fresh board is built, as the recording handler relies on.
- **Contexts not kept per task in Kit, a second cancel, `KeyboardInterrupt`, a cancel between a job's last step and its
  callback, `asyncio.to_thread` printing into a job, a `wait=100` read holding a handler slot:** each checked; none is
  a defect.
- **`get_job` should not be `READS`, `cancel_job` should be `DESTROYS`:** the hints describe Kit's state, not the
  bridge's bookkeeping; `stop_recording` and `sim_control` are `EDITS`.
- **`cancel_job(" ")`, `wait=100` past the client's timeout, the tool count, the judge's tools, `get_job` in the
  skill's `allowed-tools`, `test_06b`'s cleanup, `duration(59.99)`:** each checked against the code; none is a defect.

**The build's departures,** each judged sound: a script's result as `{"return_value"}` with the job's `output` apart;
the fallback that wraps the syntax tree, so line numbers and strings keep; tracebacks naming `<string>`, as `exec()`
did; `sys.exit` failing the job (Isaac Sim 6.2 quits anyway under `fastShutdown`, as it did through `/execute`); a
10,000-character unterminated line counted as a line.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Keep only the text after a bare `\r` in a pending line, so a redrawn progress bar reads as its latest state | taken in `8e24c77`: `test_a_progress_bar_redrawn_with_carriage_returns_reads_as_its_latest_state`, `test_a_redrawn_line_never_grows_past_its_latest_state` |
| I2 | `Router.isatty()` false while the writing task has a sink, so no library writes colour codes into an answer | taken in `8e24c77`: `test_a_task_with_a_sink_is_no_terminal` |
| I3 | The script skill: never call `sys.exit`, Isaac Sim quits | taken in `8e24c77` |
| I4 | O7's Verify points the judge at `get_job()`, since it sees the job's code cut at 600 characters | taken in `5ed515d` |
| I5 | `test_06b` prints every 5 steps, not 30, so a capture between two reads can't land between prints | taken in `8e24c77` |
| I6 | `get_job`'s `wait` says other calls through this server wait meanwhile (the client's one lock) | taken in `8e24c77` |

**Not covered:** the gate on `aaca43f` and the live suites (run after, below); whether `on_shutdown` runs before Kit's
own scripting shutdown under `fastShutdown`, which needs Kit's C++ order; the cancel safety of every handler a job
awaits through `mcp` (the capture handler's was read: it releases its feed in a `finally`). The PR's title must name
the tool contract and the routes, as `AGENTS.md`'s one-way doors ask.

## Round 2

- **Where:** `aaca43f..8e24c77`, the fixes for G1 and F1 to F3 and improvements I1 to I6, by a fresh reviewer, read
  only, with round 1's findings.
- **Verdict:** clean, with one new minor (F4), fixed and checked in this session.

Each fix was confirmed by its test, each failing without its fix: G1's by its parse test; F1's three tests fail
without `_put_back`; F2's on the old text; F3's two. I1's two tests fail without `_redrawn`, and its edge cases (`""`,
a lone `\r`, `\r\n` split across writes) were traced. For G1 the reviewer found PhysX's own docs say a stop restores
transforms and velocities only, so `kinematicEnabled` should survive; the live run confirmed it.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F4 | minor | `core/output.py` `collect`, `_put_back` | F1's fix put back each block's own router, which may be one installed over another task's redirect: a job's `redirect_stdout(buf)` across an await, a call that starts and ends inside it, and every later Kit print went to the dead `buf`; at `aaca43f` the same sequence left Kit's router in place, so a regression for a script that restores its stream | fixed in `ba4cd61`: the block puts back the first router this module installed for each stream, the one over Kit's own, and only when something else is there; the overlap test fails without it, and the reviewer's `f1_overlap.py` ends with Kit's router in place and Kit's prints on Kit's stream |

**Refuted:** Markdown lines over 120 characters in `CHANGELOG.md` and `docs/TOOLS.md` (no rule checks them); the
descriptions drifting from the contract (`tests/fixtures/mcp-tools.json` holds none).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I7 | `on_startup` sets the router module's closed flag back, for the rare re-enable where Kit doesn't import the module afresh, which would leave every `execute_script` with empty output | taken in `ba4cd61`: `output.reopen()`; `test_uninstall_puts_the_streams_back` |
| I8 | Don't cut `run_script_job`'s `code` at 600 characters for a judge: a longer job that prints only a summary can't be checked for order | taken in `ba4cd61`: 4,000 characters; a test in `test_scenario_runs.py` |

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, each suite run on a fresh Kit:

- **At `aaca43f`,** before the fixes: both live suites 210 passed on a Z-up stage and 210 on a Y-up stage, with
  `test_06b_a_script_job_runs_while_kit_answers` and `test_06c_a_job_is_cancelled_and_a_plain_loop_is_refused`.
- **After round 1's fixes:** `test_06b` failed. Printing every 5 steps (I5) made `get_job`'s answer pass 1,000
  characters, and the whole answer went to a file, so the test found no `state = completed` in it. Fixed in the tool
  (`5becae7`): the summary stays inline and only the long part goes to a file the answer names. A stop leaves
  `physics:kinematicEnabled` as a script set it during play (`[False, True]` before and after the stop), so O7's
  `Play: 3 s` holds. O7 (run `20261102-200045`): WARN; the agent ran one job of 4 min 6 s that released all 150 crates
  in order, 3.00 s apart, and the judge found them on the floor; the WARN is three short `execute_script` calls
  against O7's `Calls: no execute_script`.
- **At `ba4cd61`,** the final fixes: 209 passed and 1 failed on a Z-up stage, 210 passed on a Y-up stage; `test_06b`
  and `test_06c` passed on both. The failure is `test_16_08_draw_debug_reaches_a_capture`, "a capture ended 1.00 s
  after its draw: Kit was slow", with other sessions' sims on the GPU; it failed the same way on #156's branch and
  passed on Y-up here. Filed as #172.
- **O7 at `ba4cd61`** (run `20261102-203938`): WARN, for its Calls line alone. The agent's one job printed 150 lines,
  Crate_000 to Crate_149 in order, about 3.02 s apart, 4 min 13 s of real time; the judge found `kinematicEnabled`
  false on all 150 and the crates checked on the floor, 0.2 mm from where they hung. The two `execute_script` calls
  only read: the timeline's end time and looping, before a 450 s job, and the 150 bodies' poses from PhysX.

- **After the rebase onto `7d30015`** (#156's `get_performance`, #159's Z-up `new_scene`, #163, #168), O7's Given
  moved to a Z-up floor (`72e3875`): with another session's windowed Isaac Sim on the GPU, 211 passed and 2 failed
  on Z-up and on Y-up. `test_15_07` and `test_15_08` time a spin by the wall clock and turned 4.44 and 3.46 degrees
  against 5; `TestGetPerformance`'s heavier-stage test read 15.78 against 12.02 ms. With that sim gone, 212 passed
  and `TestGetPerformance` failed alone (20.63 against 8.01 ms after a capture). Run three times each, alternating
  `main`'s extension and this branch's on one machine, that test failed once on each (filed as #175), and phase 15
  passed in #155's runs under the lighter load, so neither is this change's. O7 on the Z-up floor (run
  `20261102-211224`): WARN for its Calls line alone (three short reads); one job of 8 min 1 s, the GPU shared,
  released the 150 crates in order, 3.02 s of simulation apart, each within 1 mm of its place on the floor.
- **The rebase onto #155's merge** (`8f3c401`) met conflicts in `AGENTS.md` and `docs/ARCHITECTURE.md` alone; the
  gate passed on it, and the next live run, #157's, runs both.

**What it couldn't show:** Kit 107 (Isaac Sim 5.1 fails in its own start-up on this machine), and whether
`on_shutdown` runs before Kit's scripting shutdown under `fastShutdown`.
