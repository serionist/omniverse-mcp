---
subject: "Give new_scene an up axis and units, Z-up in metres by default, a change to the tool contract (#159)"
base: main (6df788e)
head: f95e73b
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; a major, so a second round on the fix"
verdict: needs-fixes
---

# Review: Give new_scene an up axis and units

Read from the branch's diff against `main` at `6df788e` (22 files, about 1,100 lines with the plan) by one fresh
reviewer, read only, with every lens, against the approved plan `docs/plans/2026-11-02-new-scene-frame.md` and the
maintainer's agreement on #159, with usd-core to settle two claims. The extension, the server, the contract, the docs
and the AI suites hold; one major in the live suite.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tests/test_scenarios.py`, `test_22_00_create_inspect_target` | With phases 22 to 26 reading the stage's axis, phase 22's target (a default 2 m Cube, since `create_prim` takes no size) stood on the origin column, 0 to 2 m up, and nothing removed it before phase 26, whose kept cube (1.1 to 1.9 m up) sat inside it on either axis: 26.4's capture held no blue pixels and failed "the move doesn't show" on every run | fixed in `b274c29`: `test_22_06` deletes the target; the target is given the 0.8 m and colour it reads as |

**Refuted:**
- **A session-layer opinion overriding `set_frame`:** Kit's own "Set up axis" writes the root layer, a new stage's
  edit target, and main's `SetStageUpAxis` read back in live runs.
- **O5's sun:** `(-40, 0, -30)` on Z is the old Y direction with Y and Z swapped, 50 degrees above the horizon.
- **O2, O4, O5's Givens:** each swaps correctly; floors' tops at 0, the ball's fall and the table's legs as before.
- **A huge integer or `inf` for `meters_per_unit`:** refused before Kit discards the stage, by the server or
  `frame_of`.
- **17.7 and 17.8 changing the frame before 22, 17.3 and 17.5 on Z:** they reopen 17.6's Y stage, and read the axis.
- **Test 31's `new_scene()`, the plugin skills, `AI_GUIDE.md`, the instructions, `assistant.md`:** none depends on
  a Y-up `new_scene`.
- **The harness:** nothing loosened; `test_scenario_runs.py`'s check is stricter.
- **The protocol number:** optional keys and a missing `up_axis` for an older extension, as #149 and #150.
- **The build's departures** (`frame_of` beside `set_frame`, per-key defaults, O5's sun, `ARCHITECTURE.md`'s line,
  17.2's order, the warning's extra clause): each sound.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Give phase 22's target the size and colour it reads as (`scale=0.4`, `set_material`) | taken: `b274c29` |

**Not covered:** the gate, the live suites and the AI run (run separately, below); USD Composer's and Isaac Sim 5.x's
Kit sources; bridge-security, which nothing here touches.

## Round 2

**Where:** `f95e73b..b274c29`, by one fresh reviewer on Claude Opus, read only. **Verdict:** clean.

F1 fixed: `test_22_06_remove_inspect_target` deletes the target, and unittest's name order runs it after `test_22_05`
and before phase 23, so nothing of phase 22 is on the column when `_kept_scene` places its cube, on either axis; the
covering test is `test_26_04`'s "the move doesn't show" on the live run. Phase 22 works with a 0.8 m target (framing,
zoom, isolate measured against `framing.py`); `tearDownClass`'s second delete gets a harmless error back. No new
findings.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I2 | The new comment described the 2 m cube; at 0.8 m the target stands in front of the kept cube | taken: `150ef1c` |
| I3 | 26.1's and 26.2's cubes, on the same column, were deleted only at the end of a passing test; on cleanup instead, so a failure there can't hide the kept cube | taken: `150ef1c` |

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension at `b274c29`:

- The suites twice in a row on one Kit, the first on Isaac Sim's own Z-up stage, the second on the Y-up stage 17.6
  leaves: 209 passed each time, `test_17_02`, `test_22_06` and `test_26_04` among them.
- Phases 22 to 26 alone after `new_scene()`, which answered `up_axis = Z`, `meters_per_unit = 1.0`: 34 passed.
- AI phase 17 and outcomes O2, O4 and O5 on a fresh Kit (run `20261102-191234`): every row PASS. 17.2's tester read
  `up_axis` Z and `meters_per_unit` 1.0 from both the answer and `get_sim_state`; 17.3 called
  `new_scene(up_axis="Y")` as the prompt asked; O2, O4 and O5 ran on the new Z-up default with their Givens swapped,
  the ball and box resting at z 0 and O5's table lit from its swapped sun. The round 2 improvements (`150ef1c`)
  change only phase 26's cleanup and a comment.
