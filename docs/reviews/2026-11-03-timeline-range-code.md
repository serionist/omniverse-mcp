---
subject: "Say where the timeline starts and ends and what it does there, in get_sim_state (#180)"
base: main (15bdbc7)
head: 22ba8b4
date: 2026-11-03
round: 1
tier: "one fresh reviewer on Claude Opus, every lens. One minor, so no second round"
verdict: clean
---

# Review: The timeline's range in get_sim_state

Read from the branch's diff against `main` at `15bdbc7` (18 files, about 430 lines with the plan) by one fresh
reviewer, read only, against the approved plan `docs/plans/2026-11-03-timeline-range.md`. It ran the unit suite (2,923
passed) and a script over fps from 0.5 to 10,000 and starts from -3 to 1e8 time codes for the one-frame check. One
minor; fixed in `1fad9e7` and checked live in this session.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| R1 | minor | `tests/test_integration.py` `test_02b_...` | The loop half set the time back to the start before playing, so 0.5 s of play never reached the end: it passed with looping broken, and `093951b`'s sentence that a loop doesn't reset physics rested on a printout that measured a seek, not a loop | fixed in `1fad9e7`: looping on from 0.9 s with nothing else reset, the time required below 0.9 after 0.5 s, which only the wrap gives; measured live, back to 0.383 s, the falling body at -0.322 before the loop and -6.911 after, so the sentence stands |

**Refuted:** the one-frame check at any start and fps (the script, and Kit's tests pushing an end to start plus one
frame); the line and note against Kit's own timeline tests (a loop to the start, no loop a pause at the end, a stop to
the start), and `play()` using the timeline's own looping; an older extension (no line unless all three fields come,
tested) and an older server (reads the fields it names); putting the range back (start then end restores any range);
the cleanup deleting a physics scene it didn't make (an error dict, not a raise); every wait bounded; each unit test
failing without its code; "Kit's new stage runs under 2 s" (`[0, 100]` at 60 a second); two `note` lines; the plan's
one 122-character line (a dated record; the gate's plans check passes).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Register the stop last, so it runs first, before the body is deleted and the range put back | taken in `1fad9e7` |
| I2 | `tests/test_tools.py`'s `_sim_state_text` repeats the file's `_call` | taken in `1fad9e7` |

**Not covered:** Kit 107 live (Isaac Sim 5.1 fails in its own start-up on this machine; its stubs have the getters);
CI and the PR's text, before the PR.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, on a Z-up stage:

- **At `22ba8b4`:** both live suites, 221 passed and 1 failed. `test_02b` passed: the line read
  `0.000 to 1.000 s, then pauses at 1.000 s (not looping)` and the timeline paused at 1.000 s. The failure was
  `TestGetPerformance`'s heavier-stage check ("measured twice: 8.08 ms, 9.81 ms"), #175, which fails on `main` too.
- **At `1fad9e7`:** `test_02b` alone, passed: looping from 0.900 s, back to 0.383 s; the falling body at -0.322 m at
  the end and before the loop, -6.911 m after it.

**What it couldn't show:** Kit 107; Kit's own `[0, 100]` default range, which an Isaac Sim stage overrides (the test
sets its own range, so it runs the same on any Kit app).
