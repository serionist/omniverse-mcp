---
title: Say where the timeline starts and ends and what it does there, in get_sim_state
issue: "#180"
status: draft
approved_by:
approved_at:
---

# Say where the timeline starts and ends and what it does there, in get_sim_state

## Goal

`get_sim_state` gives the timeline's current time and its time codes a second, but not its range or what it does at
its end. An agent about to run a simulation can't tell whether the timeline will reach its end first, and reads it
with `execute_script`: outcome O7's agent did, before a 450 s job (run `20261102-203938`, #180).

The range is short more often than not: Kit's own default is `persistent.app.stage.timeCodeRange = [0, 100]`
(`omni.kit.stage_templates`), 1.7 s at 60 time codes a second, and a file with no authored range runs from 0 to 0,
which Isaac Sim's throttling extension warns plays "over a single frame". Isaac Sim's own new stage runs 1,000,000
codes (`app.stage.timeCodeRange` in `isaacsim.exp.base.kit`), 16,666.7 s, which no run reaches. Kit's timeline tests
say what happens at the end (`omni.timeline`'s `tests.py`, Kit 107 and 110): a looping timeline goes back to its start,
`elapsed % (end - start) + start`; one that doesn't loop pauses at its end, `time` equal to the end.

When this is done, `get_sim_state` answers one more line after `fps`, saying the range and what happens at its end:
`timeline = 0.000 to 1.000 s, then pauses at 1.000 s (not looping)`, or
`timeline = 0.000 to 16666.667 s, then back to 0.000 s (looping)`; and a `note` when the range is one frame or less.
The skills an agent plans a run with send it there first.

In scope: the three facts, the line, the note, the docs and skills. Out of scope: setting the range or the looping
(`sim_control` doesn't, and no case asks).

## Design

- **The core:** `ovmcp/core/timeline.py` (Kit-free, typed against a `Protocol` of the three getters, as
  `core/sweep.py`'s `Timeline`): `timeline_range(timeline) -> dict` gives `start_time`, `end_time` and `looping`, read
  together; tested directly, as `tests/test_bridge_token.py` tests `kit_app_facts`. Seconds in and out: Kit 110's
  `omni.timeline` `docs/TIME_PARAMETERS.md` says every time parameter is seconds, `play` aside.
- **The extension:** `handle_sim_state` (`ovmcp/bridge/handlers/simulation.py`) adds the three, as it calls
  `is_playing()` and `get_current_time()`, with no guard: Kit 107's and 110's interfaces both have the getters.
- **The server:** `get_sim_state` (`src/omniverse_mcp/tools/simulation.py`) adds
  `timeline = {start:.3f} to {end:.3f} s, then back to {start:.3f} s (looping)` or
  `..., then pauses at {end:.3f} s (not looping)`, only when the bridge sent all three; and
  `note = the timeline's range is one frame or less: playing loops over a single frame, so time-accumulating sensors
  and controllers produce nothing` when `end - start <= 1/fps`. An extension from before this sends none, and the
  line is left out, as `job` and `recording_note` are. The description says what the line tells an agent: a wait for
  `time` to pass the end never finishes while the timeline loops, and a timeline that doesn't loop pauses at its end,
  physics with it. `docs/TOOLS.md`'s `time` row ("elapsed simulation time") says a loop or a stop takes it back to
  the start.
- **The skills:** the `simulate` skill's Orient step and the `script` skill's job step say to read the `timeline`
  line before a long run; `docs/AI_GUIDE.md` says the same for clients without the plugin.
- **Alternatives:** a separate `get_timeline` tool, rejected: a change to the tool contract for three facts
  `get_sim_state` is already the place for. Kit's own word alone (`looping`), rejected by the fit: the agent then
  translates it, where the line can say what happens.

## Compatibility

No one-way door: `/sim/state` gains three answer fields, additive under the same protocol number, and the tool's
schema, name and hints are unchanged (the contract fixture holds no descriptions). An older extension gives no
`timeline` line; an older server ignores the fields.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `core/timeline.py` and `handle_sim_state`'s three fields | `tests/test_timeline.py` (the three from a fake timeline, both loopings); `tests/test_physics_handler.py`'s `/sim/state` tests with a fake timeline that has the getters |
| 2 | The server's line and note, only when all three came; the description | `tests/test_tools.py`: both loopings, a one-frame range's note, an older extension's answer with no line; `tests/test_contract.py` pins the description's phrase |
| 3 | Docs and skills | review |
| 4 | Live: on a stage of its own, the test sets end 1.0 s with looping off and plays: the line reads `0.000 to 1.000 s, then pauses at 1.000 s`, and the state reads paused at 1.000; looping on, playing past the end takes `time` back below 1.0; then the end and looping are put back, and what a loop does to a falling body is printed | a test in `test_integration.py`, Z-up |
| 5 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

Unit: the core's, the handler's and the tools' above (CI). Live: the new integration test on Isaac Sim 6.2 at 8212,
one run (the batch rule), on any Kit app since it sets its own range. Not shown: Kit 107 live (Isaac Sim 5.1 fails in
its own start-up on this machine; its stubs and tests have the getters and the same end behaviour); what PhysX does to
bodies at a loop, printed by the live test, not asserted.

## Docs

`docs/TOOLS.md` (`get_sim_state`'s answer, its `time` row), `CHANGELOG.md` under Unreleased, Changed; the `simulate`
and `script` skills; `docs/AI_GUIDE.md`; `docs/ARCHITECTURE.md`'s core module list (`timeline.py`) and `AGENTS.md`'s
core row, folded into an existing line (150 lines).

## Risks

- **A Kit app whose timeline reports an end before its start:** the line prints what Kit gives; accepted.
- **What physics does at a loop:** not documented in the installs read; the live test prints it, and the docs say
  only what it shows.

## Plan review

### Fit

The plan at `afde13c`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-03, with this repo's `fit-plan`.
The change's own question: is one `timeline` line the right way for an agent to learn whether a long run reaches the
timeline's end, and does the plan say enough about the end? Answers by the author, 2026-11-03, on the maintainer's
delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | Say what happens at the end, from Kit's own timeline tests (a loop goes back to the start, no loop pauses at the end), in the line, the description and `docs/TOOLS.md`, whose `time` row calls it elapsed time | taken: Goal, Design |
| I2 | The measured 16,666.7 s is Isaac Sim's setting, which no run reaches; Kit's default is 100 codes and an unauthored file 0 to 0: the live check sets its own short range, plays to the end, loops, and puts it back | taken: Goal, Step 4 |
| I3 | A note when the range is one frame or less, as Isaac Sim's throttling warns only in Kit's log | taken: Design |
| I4 | Lines in the `simulate` and `script` skills and `docs/AI_GUIDE.md`, where an agent plans a run | taken: Design, Docs |
| I5 | The reader in a Kit-free core module typed against a Protocol, tested directly; the handler test in `test_physics_handler.py`'s `/sim/state` block | taken: Design, Step 1 |
| I6 | Read the three together, no per-getter omission: every supported Kit has them, and a half-filled answer reads wrong | taken: Design |
| I7 | Cite Kit's `TIME_PARAMETERS.md` for seconds | taken: Design |

Noticed on the way, for Round 1: per-field omission gave a half-filled answer read as "not looping" (gone with I6);
the live check pinned Isaac Sim's range and ran on whatever stage Kit had (gone with I2).
