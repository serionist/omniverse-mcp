---
subject: "Pass the live suites on Isaac Sim 5.1, and say what was tested (#99)"
base: main (0913600)
head: 8c09523
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus"
verdict: clean
---

# Review: Pass the live suites on Isaac Sim 5.1, and say what was tested

Read from the branch's diff against `main`, 7 files and +60/-25: `TestColdCook`'s count of cooking lines, the GPU
module's device setter, and the docs that say what was tested. The reviewer read `logs.py`'s ring and `misc.py`'s
`/execute` namespace, which the test changes rely on, and ran nothing. No blocker or major; the three minors are fixed
in `6a60735`, so no second round follows.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_integration.py`, `TestColdCook` | The mark was `total_captured`, the index the next entry gets (`logs.py` numbers entries from 0), so `since_index=mark` dropped the first line after it: a cooking line first after the mark goes uncounted, and Kit 107 counts 31 of 32, Kit 110 misses a sphere's name. It can't pass falsely, only fail | fixed in `6a60735`: the newest entry's index, `total_captured - 1`. With it, a probe on both Kits counted 32 lines from before the scene and none after the play when the play waits 1 s: Kit starts cooking as the prims are authored. So the count stays from before the scene, and the earlier "31 from before the play" was this off-by-one, not a sphere cooked while the scene was made |
| F2 | minor | `docs/TOOLS.md` (`get_robot_info`, `draw_debug`'s captures), `handlers/robot.py` | Three places still called 5.x untested, which the 5.1 run's `test_14_04` and `test_16_08` now cover; the docs disagreed with the README | fixed in `6a60735`: tested live on 6.2 and 5.1 |
| F3 | minor | README, `docs/ARCHITECTURE.md`, CHANGELOG, `docs/SETUP.md` | "5.1 needs NVIDIA's 580 driver branch" had no platform, where only Linux was measured, and the SETUP row named the Linux file, `librtx.scenedb.plugin.so` | fixed in `6a60735`: "on Linux", the measured drivers in ARCHITECTURE with 5.1 on Windows untested, and the row names `rtx.scenedb.plugin` |

Refuted, each from the code: `UsdPhysics` unimported in the switch script, which `/execute`'s namespace provides
(`misc.py`); the joined strings, which `textwrap.indent` indents whole, with `set_device` a local of the wrapped
function; the `getattr` fallback, which takes `set_device` wherever it exists, so 6.2 runs as before; a weaker check on
Kit 110, where any line naming the run's root takes the branch that needs all 32 names; an unbounded poll, which stops
5 s on, each call under the client's timeout and the live run's hang guard; the channel filter, a substring, which
matches Kit 107's `omni.physx.cooking.plugin`; `count=2000`, applied after the filters.

Improvements:

- The same off-by-one in `test_19_set_material`'s `since`, whose absence check of "SdrShaderNode" skipped the first
  line after its mark: taken, the newest entry's index as in F1. A shared helper for the two: left, two lines with
  the same comment read as plainly.
- A second mark just before the play, requiring most lines after it: left, since Kit starts cooking as the prims are
  authored (measured on 6.2 and 5.1): with a pause before the play none come after it, so the check would turn on
  timing.

Not covered: the gate and CI, which the brief left out (the gate passed on `8c09523`); the PR text, not yet written.
