---
subject: "Run the AI scenario suite as a skill (#102)"
base: main (67a5069)
head: f310ef4
date: 2026-11-01
round: 1
tier: "two fresh reviewers on Claude Opus, the change split in two: tools/scenarios.py with its tests, and everything else; the main session confirmed both majors"
verdict: needs-fixes
---

# Review: Run the AI scenario suite as a skill

Read from the branch's diff against `main`, 15 files and about 2,770 lines, split for its size. Reviewer A read
`tools/scenarios.py`, `tests/test_scenario_runs.py` and `tests/stub_tester.py`; reviewer B the skill, `test_project/`,
the settings, the docs, the plan's record and the PR draft. Neither ran anything. Two majors and seven minors, all
fixed: the script and its tests in `808ca66`, the tester's rules and the docs in `575adf8`. A second round follows,
since there were majors.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tools/scenarios.py`, `cmd_run` | The run command's own steps were untested: `settle`, the lock (taken, refused, given back), `run.json`'s keys, the `.cmd` refusal, and the `--allow-port-8211` and `--any-bridge` overrides. The only test entering `cmd_run` was `--dry-run`, which returns before the lock: emptying `settle` or dropping the lock's `unlink` passed every test, and in use every later run would be refused until the lock was deleted by hand | fixed in `808ca66`: `settle` and `claude_executable` move where tests reach them, and the run command is tested with Kit and the tester stood in for: `test_settle_stops_the_timeline_and_a_recording_left_running`, `test_a_run_writes_its_record_and_gives_its_lock_back`, `test_a_run_cut_short_gives_its_lock_back_and_writes_what_ran`, `test_a_held_lock_refuses_a_second_run`, `test_claude_must_be_on_path_and_not_a_cmd_shim_on_windows`, `test_allow_port_8211_passes_the_port_rule`, `test_any_bridge_passes_a_bridge_that_differs` |
| F2 | minor | `_read_event`, `run_sessions` | A session the script stops sends no result event, so its cost counted $0: the totals of step 9's phase 16 and 26 sessions were short, and after a stop the next `--max-budget-usd` ignored the stopped session's spend, so `--budget` stopped being a cap | fixed in `808ca66`: such a session counts its whole allowance as spent, and `results.md` says its cost is unknown: `test_a_stopped_session_counts_its_whole_allowance_and_its_cost_as_unknown` |
| F3 | minor | `_read_event` | Any `Skill` call counted as a load when made, so a bundled skill `dontAsk` refused showed as loaded, and "none in N sessions" dropped, weakening the guard against a run with no skill | fixed in `808ca66`: only an `omniverse-mcp:` skill whose result isn't an error counts: `test_only_a_plugin_skill_that_loaded_counts`; the stub's load now has its result |
| F4 | minor | `HealthWatch`, `cmd_run` | One watch served the whole run, so an unanswered probe at the end of one session counted against the next: a run could stop after about 112 s of real silence, inside the server's 120 s call limit | fixed in `808ca66`: a watch per session; `test_a_run_writes_its_record_and_gives_its_lock_back` checks the two sessions get two |
| F5 | minor | `run_session`, `cmd_run` | An interrupt or an error could leave the tester running (on Linux and macOS its own session keeps a terminal's Ctrl+C from it) with `execute_script` pre-approved and nothing watching; the lock was taken before its `try`, and `run.json` went unwritten | fixed in `808ca66`: `run_session` ends the tree in a `finally`, the lock is taken just before the `try` whose `finally` gives it back and writes `run.json`: `test_an_error_in_the_session_still_ends_the_tester`, `test_a_run_cut_short_gives_its_lock_back_and_writes_what_ran` |
| F6 | minor | `SessionRecord` | `run.json` lacked each session's start, end and tokens, which the plan's Results table lists | fixed in `808ca66`: recorded, the tokens from the result event's usage: `test_a_session_reads_its_model_skills_cost_and_rows`, `test_a_run_writes_its_record_and_gives_its_lock_back` |
| F7 | major | `test_project/AGENTS.md`, Code in `execute_script` | The rules allowed at most one awaited handler per script and named Phase 25's code as one that keeps to it, while 25.3 and 25.4 each await two: a tester must SKIP them, split them (which changes what they test) or break the rule, so their status would swing between runs, the noise the skill warns `compare` can't tell from a regression | fixed in `575adf8`: the one-await rule holds for the tester's own code, and a scenario's own code runs as written unless it imports `ovmcp.*` or waits for time. A live run of Phase 25 under it is pending |
| F8 | minor | `docs/releasing.md` step 2, the skill's step 4 | `compare --against v<last>` fails while no release has a run (v0.3.0 predates the suite), with no fallback given; later, a run matches a tag's squash merge only by a clean tree, which the runbook didn't ask for | fixed in `575adf8`: both say to run from a clean tree on the PR's final head, and while no release has a run, to compare with the newest run and say so |
| F9 | minor | `test_project/AGENTS.md`, Opened by hand | Opened by hand, `<run>/` meant nothing: only a run's prompt fills it in, and `<` and `>` are invalid in Windows paths, so 17.1's `save_scene` fails | fixed in `575adf8`: use an absolute folder of your own under `results/runs/` |

Refuted, each from the code or the files. Reviewer A: 8211 is checked before any token read or connection; the shell's
host and token don't reach the tester; the plugin's own server, other servers and memory are kept out, and the init
check fails closed; a slow probe doesn't delay the init check; CRLF folding applies to both sides; `taskkill` can't hit
a reused PID; the lock's `open("x")` is atomic; no `cmd.exe` parsing, as `.cmd` and `.bat` are refused; the stage rule
blocks URLs and temp files that still exist; setup doesn't cross 17 and 18; the tests aren't flaky; nothing needs
Python 3.12; the tests touch no real token or run. Reviewer B: the settings' allows are exact and pass the sweep, as
Q13 approved; `AGENTS.md` is at 150 lines with accurate rows; pytest doesn't break `results/`; `scenarios.md` matches
`parse()`; the skill follows `write-skill`; the guidance on judgement swings matches `compare`; the PR draft's facts
check out; `finish-work` step 3 is usable. Both: the writing rules are kept.

Improvements, with the coordinator's answers:

- IA1, fail closed when the tester acts before any init event: taken in `808ca66`,
  `test_a_session_that_acts_before_its_init_event_is_stopped`.
- IA2, stop the run on an init failure, which every session would meet: taken in `808ca66`,
  `test_a_failed_init_check_stops_the_run`.
- IA3, narrow the tester's reads: the working folder taken in `808ca66`, each session running in its own
  `mcp_output/<session>/` rather than `test_project/`; scoped `Read(...)` allows left, since path rules on Windows are
  unproven, the reason the plan dropped the Write path rules.
- IA4, tighter tests: taken in `808ca66`, the silent-Kit test renamed for what it checks, and the exact `--tools` value.
- IA5, a Kit app that refuses told apart from one that doesn't answer: taken in `808ca66`,
  `test_a_kit_that_answers_with_a_refusal_says_so`.
- IB1, the skill's run step keeps the port and any override `check` was given: taken in `575adf8`.
- IB2, the full run's time and cost said to be summed from two partial runs, and the sum recorded: taken in `575adf8`,
  in the skill and the plan's step 9 record.
- IB3, how `finish-work` picks the phases a change touches: taken in `575adf8`.
- IB4, the release step names the port: taken in `575adf8`.
- IB5, the PR cites Q13 beside the settings: taken in the PR draft.
- IB6, the plan's Tests line on the spot-check and its Risks row on scripts: taken in `575adf8`.

## Live run

Phase 25 alone on `7006994`, run `20261101-045626`, under F7's wording, on Isaac Sim 6.2.0 headless (Kit 110.4.0) at
8212 with the branch's bridge, the tester on `claude-opus-5-5`: phase-25 in 16 s for $0.15, loading
`omniverse-mcp:script`, then phase-27 in 10 s for $0.08; 9 PASS, and `compare` exited 0. The transcript shows 25.3
and 25.4 run as the scenarios write them, two awaited handlers in one script each: 25.3 read the new cube's centre
as [0, 1, 0], 25.4 captured with `has_image` true. No script imported `ovmcp.*` or waited for time. The other fixes
after `f310ef4` change the script, which the unit tests cover, or the docs, and need no live run.

## Checks

- `tests/test_scenario_runs.py`: 77 passed, twice.
- `uv run tools/gate.py full` on `575adf8`: 15 checks passed, 1648 tests passed and 206 skipped, coverage 96.85%.
- Live: none for the script's fixes, which the unit tests cover. F7 changes the tester's rules, so Phase 25 runs alone
  on the maintainer's test Kit at 8212 under the new wording before round 2.
