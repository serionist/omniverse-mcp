---
subject: "Scenario suite: lighting, order and stale Verify lines (#103)"
base: main (876caca)
head: a65189f
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only; the main session checked the finding against the text and the runs"
verdict: needs-fixes
---

# Review: Scenario suite: lighting, order and stale Verify lines

Read from the branch's diff against its merge base `876caca`, `test_project/scenarios.md` alone (git merge-tree showed
no conflicts with `origin/main` at `3b2b0cf`), against the bridge's code and two AI scenario runs on Isaac Sim 6.2. The
reviewer ran nothing. One minor, fixed in `2e3e933`; no second round, as there was no major.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `test_project/scenarios.md`, 5.3 | The new last Verify line needs the cube on the ground, but the wait before it was still "briefly". The cube falls 2.65 units, about 0.74 s at 1 m per unit: a tester who plays half a second sees it mid-air, so the bounds check passes and "on the ground" fails, a WARN or FAIL the text causes. Both live runs happened to wait 2.1 to 2.25 s | fixed in `2e3e933`: "wait ~2 s (get_sim_state's `time`)", as 6.1 and 7.1 say |

Refuted, each from the code or the runs:
- **2.1's light:** `rotateXYZ` turns about X first (`xform.py`), so `[-50,30,0]` sends -Z to (-0.32, -0.77, -0.56).
  It lights the +X, side and top faces on a Y-up stage, and the same faces, still pointing down, on a Z-up one
  unswapped. `inspect_prim`'s front, right and top are lit on both.
- **The intensities:** `UsdLux` and `omni` are in the script's namespace, and `viewport_light` reads
  `inputs:intensity` (23.1 answered `intensity=1000.0`). The defaults are 50000 for a DistantLight and 1 for a
  DomeLight, as the text says.
- **24.6:** the bridge catches a script's exception and returns it without logging it. Run `20261101-115226` found
  `[ERROR] : log_test_error` and nothing for `log_test_raise`.
- **2.1's red cube:** `set_material` reuses `/World/Looks/RedCube_Mat`, so 12.1 still answers right, and 15.2 binds
  with purpose "physics", so the red binding stays. 16.8 aims away from the cube, and 21.x are on a new stage. No
  later Verify line contradicts it.
- **5.2, 13.5, 17.4 and 21.1:** each matches the code and the runs. A step is two updates, 0.033 s at 60. Clone
  offsets step from the first copy. A Cube's size is 2, so a scale of 0.25 makes it 0.5. The answer reads
  "Updated 1 references in 1 prims".
- **16.6, 16.7 and 17.3:** drawings expire on `time.monotonic()`, the clock the scenarios read.
- **16.8 and 16.9:** the `mcp` object has no `draw_debug`, so an `ovmcp.*` import is needed. `test_16_08` and
  `test_16_09` cover them.
- **22.5:** `left` is azimuth 270 (-X), so TestCube at +X stands behind the robot. Isolate never hides a light.
- **Standalone phases:** setup sessions cover 3, 5, 12, 13, 16, 22, 23 and 26, and 26 resolves through 23.2.
- **The rest:** the writing rules hold, there is no attribution, and each commit ends `Refs #103`.

Improvements, with the coordinator's answers:

1. Phase 23 needed all of 18.1 for its dome, while 18.1 also holds the mesh-stats checks: a `get_mesh_stats`
   regression would FAIL 18.1, and the SKIP rule would hide 23.1 and 23.4's lighting results. Taken in `2e3e933`:
   18.2, which 19, 21, 22 and 23 already need, makes the dome. Phase 23 needs `18.2` again, and the setup-26
   expectation in `tests/test_scenario_runs.py` is back as `main` has it.
2. Phase 18's note said the dome lights every capture after it, though the rig and the camera light hide it in
   Phases 23 and 26. Taken in `2e3e933`: "every capture of Phases 19 to 22".
3. The pytest twins have drifted: `test_02_01` still lights at `[45,0,0]` and 50000, `test_24_05` still tests
   `since_index` on the bridge, and `test_24_06` asserts nothing about the log. Open: the maintainer decides whether
   it lands in #103.
4. The red cube is unchecked in Phases 3, 12, 13 and 16 since `a65189f`. Taken by the main session: a confirming run
   of those phases.
5. The PR names the new WARNs in `20261101-115226` that come from the tools, outside #103: 6.1 and 6.3 (frames about
   twice the asked fps) and 24.3 (a truncated call stack matching "MCP"). Taken by the main session, in the PR text.

## Live run

All on Isaac Sim 6.2.0 headless (Kit 110.4.0) at 8212, Windows, with `main`'s 0.3.0 bridge:

- **The light check,** a script of the branch's own, not committed, calling the tools through the MCP server in
  process. It settled the lights before `2decbc9`:
  - `[45,0,0]` gave black captures, and `inspect_prim` warned all-black.
  - `[-50,30,0]` lit every view, but at the default 50000 three quarters of 3.2's frame was white and the red cube
    pink. At 3000 the cube was plainly red on a grey ground.
  - On the second half, a DistantLight and a DomeLight at 1 left the Franka nearly black. A DomeLight at 1000 lit it
    from all five of 22.2's angles.
  - It also confirmed 5.2's 2/60 s step, 24.5's marker coming last, and the count-with-clock reads of 16.6 and 17.3.
- **Run `20261101-113702`,** at `2a3346a`, phases 2-3, 5, 6, 10, 12, 13, 16-18 and 21-24: 73 PASS, 1 FAIL, 5 WARN,
  1 SKIP.
  - Fixed against earlier runs: 3.2, 3.3, 3.5, 5.2, 6.1, 6.2, 6.4-6.9, 10.2, 12.8, 13.5, 16.8, 21.1, 22.1, 22.2,
    22.4, 22.5 and 24.5.
  - Left to #105: 2.2, 10.1 and 23.6.
  - Fixed in `a65189f`: 24.6's FAIL and the WARNs of 5.3 and 6.3. 16.9's SKIP is expected, as it is pytest's.
- **Run `20261101-115226`,** at `a65189f`, phases 5, 6 and 24: 5.3 and 24.6 PASS, and 6.3's frames show the cube red
  (110 to 124 red pixels each).
- **What could not be shown:** Z-up rests on the arithmetic; USD Composer and Isaac Sim 5.x weren't run. `2e3e933`'s
  dome in 18.2 and 5.3's wait ran in no live run: the dome's two calls are those `20261101-113702` ran in 18.1, and
  the dry run shows a setup with 18.2 before Phases 19, 21, 23 and 26 run alone.

## Checks

- `tests/test_scenario_runs.py`: 77 passed at each commit.
- `uv run tools/gate.py full` on `a65189f` and on `2e3e933`: 15 checks passed, 1673 tests passed and 206 skipped,
  coverage 96.85%.
