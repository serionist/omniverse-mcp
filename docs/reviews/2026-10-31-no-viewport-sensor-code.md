---
subject: "Stop turning on the viewport's instance segmentation at startup (#76)"
base: main (7749c8a)
head: d30595a
date: 2026-10-31
round: 1
tier: standard (one fresh reviewer on Claude Sonnet; findings checked against the code by the author)
verdict: needs-fixes
---

# Review: the viewport's own segmentation sensor

Read from the branch's diff: `extension.py` without `_init_sensors`, ARCHITECTURE.md's `on_startup` line and the
changelog, against every reader of `omni.syntheticdata` in the extension and the live suites. Two minors, fixed, so
no second round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_scenarios.py`, `test_17_04_segmentation_after_a_new_stage` | Its docstring said the bridge enables instance segmentation again on every stage open, which it no longer does, and its first check read the viewport's own sensor and asserted it empty on 17.3's new stage, which nothing turns on any more, so the check could no longer fail | fixed in `3c2b331`: both suites ask `omni.syntheticdata` whether the viewport's own sensor is on, without turning it on (`VIEWPORT_SEGMENTATION_ON` in `tests/conftest.py`): the new `test_10b` on the stage Kit starts with, where 0.2.3 had turned it on, after a capture that has its segmentation; and 17.4 on the new stage, which catches a re-enable on stage open coming back. The docstring says what the code does |
| F2 | minor | `docs/ARCHITECTURE.md`, `on_startup` | The bullet was one line of about 390 characters, where the one below it wraps at 120 | fixed in `3c2b331` |

Refuted, each from the code:

- **Something still reads the viewport's own sensor:** `camera.py`'s `_segmentation` reads the capture feed's, which
  `camera_feed.py`'s `enable_segmentation` turns on; `get_active_viewport` elsewhere reads the viewport's camera and
  size; `recording.py` reads no sensor; the live suites' `_SENSORS` wraps the call made with the feed.
- **A stage-open re-enable elsewhere:** none; `_init_sensors` was the only place that turned the viewport's sensor on.
- **AGENTS.md's Traps row for `d688f31`:** it already reads "Sensor turned on for each capture's own feed".
- **Anything left behind:** `asyncio` is still used by `_get_event_loop`; the sensor imports were inside the method.

Improvements:

| Improvement | Answer |
|---|---|
| Say in the PR that another extension can still turn the viewport's sensor on | taken: the PR says so |

Not covered: the reviewer ran nothing; how `get_instance_segmentation` behaves on a viewport whose sensor was never on
was left to the live run, which no longer reads it.

## Live run

Isaac Sim 6.2.0 headless, my own Kit at 8212, fresh each run, `OMNIVERSE_MCP_SIM=1`.

- **`main`'s extension (`1b761cb`), the branch's `test_10b`:** fails as it should, on the stage Kit started with:
  the viewport's own sensor is on.
- **The branch at `8b44164`:** `test_10b` alone passed on the stage Kit started with: "The capture had its
  segmentation; the viewport's own sensor is off". Then both live suites whole, three times, each on a fresh Kit:
  - 183 passed and 16 subtests, 1 failed: scenario `test_06_04_frames_follow_the_simulation`, which records a cube
    falling for 1.5 s. The run's filter kept only its name, not its message, and Kit's log has nothing on it;
  - 184 passed and 16 subtests in 148.30 s, "The cube from image row 70 to 152 over 27 frames";
  - 184 passed and 16 subtests in 146.45 s, the same over 29 frames.
- In each, 17.4 found the viewport's sensor off on the new stage and the capture's segmentation there, `test_15c`
  read segmentation after 16 reads, and the capture checks counted 7 paths under `/Render`, where `main` counts 14:
  the viewport's own sensor graph is no longer there.
- **06.04:** it failed this afternoon on `main`'s extension too, on a Kit a repro script had used first, with "too few
  frames with the cube"; on fresh Kits with `main`'s and #82's extensions it passed each time. A recording renders
  through a feed of its own, and the viewport's sensor isn't on its path, so the failure isn't put down to this
  change; it is a timing check on 1.5 s of play.

Not shown: other Kit apps; another extension that turns the viewport's sensor on still can.

## Checks

- **The gate:** `uv run tools/gate.py full` passed on `d30595a`: 1444 passed and 184 skipped, coverage 96.52%; on
  `8b44164`, after merging `main` (#90): coverage 96.53%.
