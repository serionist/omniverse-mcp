---
title: Say where the timeline starts and ends and whether it loops, in get_sim_state
issue: "#180"
status: draft
approved_by:
approved_at:
---

# Say where the timeline starts and ends and whether it loops, in get_sim_state

## Goal

`get_sim_state` gives the timeline's current time and its time codes a second, but not its range or whether it loops.
An agent about to run a long simulation can't tell whether the timeline will reach its end first, and reads it with
`execute_script`: outcome O7's agent did, before a 450 s job (run `20261102-203938`, #180). Measured on Isaac Sim 6.2.0
(Kit 110.4.0): a stage from `new_scene()` runs from 0 s to 16,666.7 s (1,000,000 time codes at 60 a second) and loops.

When this is done, `get_sim_state` answers one more line, `timeline = 0.000 to 16666.667 s, looping` (or
`not looping`), beside `time` and `fps`, from the bridge's `/sim/state`.

In scope: the three facts, the line, the docs. Out of scope: setting the range or the looping (`sim_control` doesn't,
and no case asks); what the timeline does at its end when it doesn't loop, which nothing here measured.

## Design

- **The extension:** `handle_sim_state` (`ovmcp/bridge/handlers/simulation.py`) adds `start_time` and `end_time` in
  seconds, from `timeline.get_start_time()` and `get_end_time()`, and `looping`, from `timeline.is_looping()`, beside
  `sim_time`, which is already seconds from `get_current_time()`. Each is read on its own and left out when the getter
  is missing or raises, as `kit_app_facts` reads the Kit app's facts: Kit 107's (Isaac Sim 5.1's `omni.timeline`
  stubs) and Kit 110's interfaces both have the three getters.
- **The server:** `get_sim_state` (`src/omniverse_mcp/tools/simulation.py`) adds
  `timeline = {start:.3f} to {end:.3f} s, looping|not looping` after `fps`, only when the bridge sent `end_time`; an
  extension from before this sends none, and the line is left out, as `job` and `recording_note` are. Its description
  names the timeline's range and looping among what it gives.
- **Alternatives:** a separate `get_timeline` tool, rejected: a new tool is a change to the tool contract for three
  facts `get_sim_state` is already the place for. Putting them in `time = ...`'s line, rejected: the line's form is
  read by agents and tests as one number.

## Compatibility

No one-way door: `/sim/state` gains three answer fields, additive under the same protocol number, and the tool's
schema, name and hints are unchanged (the contract fixture holds no descriptions). An older extension gives no
`timeline` line; an older server ignores the fields.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | The extension's three fields, each left out when its getter is missing or raises | a handler test with a fake timeline: the fields from the getters; a timeline without `is_looping` gives the other two |
| 2 | The server's line, only when `end_time` came; the description | `tests/test_tools.py`: the line from a bridge that sends the fields, both loopings; none from one that doesn't; `tests/test_contract.py` pins the description's phrase |
| 3 | Docs | review |
| 4 | Live: `get_sim_state` on a new stage reads `timeline = 0.000 to 16666.667 s, looping` | a line in `test_integration.py`'s sim-state test, Z-up |
| 5 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

Unit: the handler test and the tool tests above (CI). Live: the integration suite's sim-state test on Isaac Sim 6.2 at
8212, one run (the batch rule). Not shown: Kit 107 live (Isaac Sim 5.1 fails in its own start-up on this machine; its
stubs have the getters).

## Docs

`docs/TOOLS.md` (`get_sim_state`'s answer), `CHANGELOG.md` under Unreleased, Changed. `docs/ARCHITECTURE.md` lists
routes, not answer fields: no change.

## Risks

- **A Kit app whose timeline reports an end before its start, or none:** the line prints what Kit gives; accepted.
- **Seconds or time codes:** `get_current_time()` is seconds on Kit 107 and 110 (the handler's comment and the live
  `time` line); `get_start_time()` and `get_end_time()` are the same unit, measured: 16,666.7 for 1,000,000 codes.

## Plan review

None yet.
