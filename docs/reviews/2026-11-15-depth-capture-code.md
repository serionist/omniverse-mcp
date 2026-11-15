---
subject: "Capture a depth image, raw distances and each prim's nearest distance, on request (#203)"
base: main (11e06f7)
head: dd91c78
date: 2026-11-15
round: 1
tier: "one fresh reviewer on Claude Opus, every lens. Three minors, so no second round"
verdict: clean
---

# Review: Depth in capture_viewport

Read from the branch's diff against `main` at `11e06f7` (19 files, about 1,470 lines with the plan) by one fresh
reviewer, read only, against the approved plan `docs/plans/2026-11-15-depth-capture.md` and omni.syntheticdata
0.6.17's source on disk. Three minors: two fixed in the commit after `dd91c78`, one open until the live run.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_integration.py` `test_12k_...` | Step 5's checks only partly built: the nothing-hit check compared `depth_image`'s count with itself, and nothing read the depth sensor off between calls | fixed: `inf` must be exactly where the segmentation shows no prim (black), and the kept feed's `sensors_on` must be empty after the call |
| F2 | minor | `tests/test_camera_handler.py` `_segments` | The fake colouring ignored `distances`, so a capture that passed `None`, or dropped `depth_nearest`, passed every unit test | fixed: the fake returns the distances' minimum, and the test asserts it in `depth_nearest` |
| F3 | minor | the plan | No Progress: Step 1's and Step 5's numbers (the unit, the far clip, the release, the 4096 capture's time) aren't recorded | open: the live run on Isaac Sim 6.2 records them; `test_12k`'s 0.1 m tolerance fails if the unit is wrong |

**Refuted:** a depth enable that raises leaving a type to disable (omni.syntheticdata skips a node it never made);
`DistanceToCamera` missing on an older Kit (it raises before the append, and the call gives `depth_error`); depth's
shape (`get_sensor_array` gives height x width, and the code takes either); `inspect_prim`'s behaviour (the same
answer and error through `_segmentation_ids` and the colouring); `np.minimum.at` (on the flattened inverse, float64
from `inf`, names two ids share taking the minimum, sky never winning); `test_12k`'s expected distance and its 4096
capture's time; the server tool's argument order and lines.

**Not covered:** live behaviour, without Kit; Kit 107's omni.syntheticdata, as the plan accepts.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | A NaN under a prim's id spreads through `np.minimum.at` and drops that prim's distance: apply the value rule too, or `np.fmin.at` | open |
| I2 | The legend's `{:.4g}` prints `1.235e+04` for a prim 123 m away on a centimetre stage: `.6g` | open |
| I3 | `_turn_segmentation_off`, `_free_segmentation_graphs`, `segmented` and the release's step label now cover every sensor: sensor-wide names | open |
