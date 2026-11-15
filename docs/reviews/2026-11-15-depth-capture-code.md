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
| F3 | minor | the plan | No Progress: Step 1's and Step 5's numbers (the unit, the far clip, the release, the 4096 capture's time) aren't recorded | fixed: the plan's Progress, from the live run below |

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
| I1 | A NaN under a prim's id spreads through `np.minimum.at` and drops that prim's distance: apply the value rule too, or `np.fmin.at` | taken |
| I2 | The legend's `{:.4g}` prints `1.235e+04` for a prim 123 m away on a centimetre stage: `.6g` | taken |
| I3 | `_turn_segmentation_off`, `_free_segmentation_graphs`, `segmented` and the release's step label now cover every sensor: sensor-wide names | taken |

## Live run

On Isaac Sim 6.2.0-rc.14 (Kit 110.4.0), `isaacsim.exp.base.kit` headless on Windows 11, port 8212, Z-up, metres, started
with `--/rtx/hydra/supportMultiTickRate=false`, 2026-11-15, on a local merge of this branch (at `b0f89aa`) and #198's:

- `test_integration.py::test_12k`: passed. The cube's nearest distance 1.582 against 1.581 from the camera's eye to
  its box; `inf` exactly where the segmentation is black; the kept feed's sensors off after the call; a capture with
  depth after a physics run; a 4096 x 4096 capture with depth in 3.4 s; nothing left once the feed is released.
- `test_integration.py`: 87 passed, 1 failed, `TestCaptureSweepAgents::test_a_stopped_timeline_repeats_an_agent_and_a_time_doesn_t`,
  repeated sweep captures 2.19 of 255 apart against 2.0, which its own message puts at about 3.2 with the multi-tick
  flag the Kit ran with.
- `test_scenarios.py`: 135 of 136 in two runs; 26.03 failed in all three runs (five captures at one size counted 5
  RTX view assignments in Kit's log, not 2). Unsettled: it may be this change's capture path or this Kit's launch
  (another session started it, its log elsewhere, with the multi-tick flag); a run of `main` on the same launch
  settles it.
- I1 to I3 (`np.fmin.at`, the legend's precision, the renames) came after the run; unit tests cover them.
