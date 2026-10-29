---
subject: "Place and check the scenario suite's heights along the stage's up axis (#6)"
base: main (2ea46d4)
head: 2dfd8f0
date: 2026-10-29
round: 1
tier: light (one fresh reviewer on a test-only change)
verdict: clean
---

# Review: the scenario suite on either up axis

Read from the diff, `tests/test_scenarios.py` in full, and the handlers it relies on. No blocker or major; one minor
left, one improvement taken.

- **The cause holds:** sim state reports the stage's up axis (`handlers/simulation.py`); phase 4.5's physics scene has
  no gravity direction, so gravity runs down the up axis; the old 5.3 and 7.2 read Y, which stays at 3.0 on Isaac
  Sim's Z-up stage of a first run. `new_scene` (17.2) makes the stage Y-up, so a second run passed.
- **No test is weaker:** 2.5 and 5.3 assert the same along the up axis, and 5.3 now fails if gravity acts on the wrong
  axis. 7.2 is stricter: the old one skipped its check on a single frame and passed on any change, a rise included; the
  new one needs several frames and a fall of over 0.1 below the first. A cube that never fell fails it.
- **The vectors:** on Y-up, each is what it was; on Z-up the ground is a floor and each object sits above it.
- **No axis mixed mid-suite:** 17.2 sorts after phases 1 to 16; each of 6.1 to 7.3 reads the axis itself.

Minor, left: `test_project/scenarios.md`'s older prose keeps Y vectors (6.1, 7.1, 7.3, 15.4); the note added at its
top covers them.

Improvement taken: a comment that phases 22 to 26 rely on 17.2's Y-up stage.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for this run with `main`'s bridge; the maintainer's Isaac Sim on
8211 was not touched. `-k "not test_10_ and not test_14_"` (#5):

- **First run after Kit started, the stage Z-up:** 116 passed, #7's three `draw_debug` failing. 2.5 placed the cube at
  Z=0.55; 5.3 `Before Z=3.00, After Z=0.55`; 7.2 `first=2.75, lowest=0.55, frames=33`.
- **Second run, the stage Y-up after 17.2:** 116 passed, the same three failing. 5.3 `Before Y=3.00, After Y=0.55`;
  7.2 `first=2.79, lowest=0.55, frames=26`.

## Checks

`uv run tools/gate.py full` passed on the branch.
