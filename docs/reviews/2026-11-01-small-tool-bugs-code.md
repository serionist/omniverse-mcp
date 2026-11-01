---
subject: "Fix the small tool bugs the first AI scenario runs found (#105)"
base: main (d59667a)
head: 926ccab
date: 2026-11-01
round: 1
tier: "three fresh reviewers on Claude Opus, the lenses split; the major confirmed by a fresh refuter"
verdict: needs-fixes
---

# Review: Fix the small tool bugs the first AI scenario runs found

Read from the branch's diff against `main` at `d59667a`, over 1,500 lines, by three fresh reviewers, read only, each
with its own lenses:

| Reviewer | Lenses |
|---|---|
| (a) | implementation, kit-main-thread, bridge-security, compatibility, simplicity, on the extension |
| (b) | plan-and-intent, tool-contract, docs-freshness, the server's implementation |
| (c) | tests, harness-integrity |

The extension's reviewer checked edge cases with scratch scripts on usd-core 26.11. Nothing ran in Kit. The one major
went to a fresh refuter, who confirmed it. The fixes were made on the branch, then rebased onto `main` at `c4fd60e`
(#103, PR #115); the commits below are after that rebase.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tests/test_scenarios.py` `test_15_16` | The check that the turned Franka stays upright took its reference pose after `_start_physics()`, once PhysX had loaded and stepped the robot. A base the world-anchored root joint pulled back to the file's orientation at load would have been its own reference: the turn reads about 0, and the test passes with the Franka lying down. The only up check, its bounds, ran before physics. The refuter confirmed it, major: new behaviour without a test that can fail | fixed in `9d51967`: the base's world rotation is read from USD before play, in PhysX's order x, y, z, w (`USD_ROTATION`), and PhysX's pose at load and after 30 steps must each be within 1° of it |
| F2 | minor | `src/omniverse_mcp/tools/camera.py`, `tools/robot.py` | The plan promised `docs/TOOLS.md`'s sentences in the tools' descriptions too; only `capture_viewport`'s had them. `viewport_light` said to use it only for a black capture, `inspect_prim` said nothing of its warning, and `create_robot` didn't say a file without `upAxis` is left as it is. With a 0.3.0 extension in mode stage without lights, an agent reading `viewport_light` only reaches for it on a black image | fixed in `4a90bba`; `tests/test_contract.py` `test_a_description_says_what_the_tool_now_does` checks each sentence |
| F3 | minor | `core/robot.py` `stand_upright`, `handlers/robot.py` | A file whose root held a `double xformOp:rotateX:unitsResolve` out of the order: `AddRotateXOp` asked for float and USD raised `Tf.ErrorException`. The handler caught only `ValueError`, so it answered 500 and left the robot, and a retry was refused as taken | fixed in `4238c56`: `xform.py`'s `add_local_op` adds the op in an existing attribute's precision, where the writer places one (I5), and the handler removes the robot on a USD error too; `tests/test_robot.py` `test_a_turn_reuses_an_attribute_of_its_name_out_of_the_order_in_its_precision` |
| F4 | minor | `core/formatter.py` | `factors()` used `Factor`'s default tolerance, 1e-10 on the determinant, so a uniform world scale below about 4.6e-4, a millimetre asset under a parent scaled 0.1, had no `rot` line, against "45° at any scale" | fixed in `4e6d369`: `usd.py`'s `rotation_of` factors with 1e-30 and reads the rotation from the factored matrix; only a scale of 0 leaves `rot` out; `tests/test_formatter.py` `test_rot_at_a_tiny_scale_is_its_turn` at 0.0004 and 1e-6 |
| F5 | minor | `tests/test_robot.py`, `tests/test_robot_handler.py` | The summed op of P3's case was never read back: both tests checked the returned value only, so a regression that computed the sum but didn't set it would leave -90 while the answer says "now reads 0" | fixed in `4238c56`: both read the attribute back |
| F6 | minor | `tests/test_integration.py` `test_12j` | It counted only the lighting's warning. On a Kit whose unlit capture is all black, grid off or perhaps Isaac Sim 5.x, the black image's warning names the lighting instead, and the test would fail on a right answer | fixed in `612d90c`: it takes either warning, still once an `inspect_prim` call |

**Refuted,** each from the code:
- **The server:** 26.2's Verify needs TestCube though phase 26 names 23.2, but `Needs` resolve transitively, and 23
  needs 18.2. 2.2's quaternion on Z-up: each half starts with `new_scene`, Y-up. 20.6's A having faces: the issue's run
  saw 0 to 96,576 after the same steps. `_kit_app`'s partial line: IApp's `get_app_name` and `get_app_version` always
  return a value. CHANGELOG's Fixed before Changed: the repo's order, as in 0.2.3.
- **The extension:** R6's sign (-90 sends Z-up's up to +Y, as K1's test has it); the placement before an inverse op;
  a typeless or Scope root, or no `defaultPrim` (refused, `RemovePrim` cleans up, as on `main`); summing into an op
  already there (order kept, animated refused, both edits in the edit target); payloads (`create_robot` only
  references). `position` and `rotation` stay in the stage's frame (`_own` skips the suffixed op, and
  `_before(..., _is_units)`). R7's sources and fallbacks, and the shared material never written. `PhysxMaterialAPI` by
  `AddAppliedSchema`, copied by name and type in the edit target. R2's negative scale and shear. R3's clipping: behind,
  straddling, enclosing, beside, edge, half-size frame. R4's cost: `any()` stops at the first light, less than
  `_compute_screen_bboxes`' own walk, once a call. R8: read once, each getter tried, no node name, `/health` and
  `/sim/state` behind `refusal()` (`core/http.py:183`), no new route, no executor or thread.
- **The tests:** the `load_simulation` refactor keeps every old test's meaning, since the timeline's getters are used
  only by `handle_sim_state`. `test_12i` is safe on either axis: `at()` swaps the scene, eye and up alike.
  `test_27b`'s import and `resolve_hierarchy` exist (`_metricsAssembler.pyi:72`), and a second turn fails the count,
  the value or the bounds. `set_kit_app`'s monkeypatch restores. No test reaches 8211. The 0.3 s sleep after stop is
  the suite's habit, not a stand-in for state. No skip, xfail, noqa, type ignore or `--no-verify`. `pyproject.toml`
  and the baseline untouched, the floor at 93%. The thresholds hold against the probes: rebound 0.789 against 0.3,
  pairs within 0.05, the near box at x 320.0 against 16 px, and the 24° and 29° slopes bracketing 0.5.

**Improvements,** all taken:

| # | What | Answer |
|---|---|---|
| I1 | The bug form's "Kit app and version" and "Operating system" fields point at `get_sim_state`'s `kit_app`, `kit_version` and `kit_os`, as its version fields do | taken, `44961c5` |
| I2 | `docs/TOOLS.md` `create_robot`'s Up axis paragraph: unlike Kit's assembler, it doesn't scale a file of other `metersPerUnit` (#112) | taken, `fd6d43b` |
| I3 | `docs/SETUP.md`'s black-capture row and the scenarios' Phase 23 note name the unlit warning too | taken, `fd6d43b` |
| I4 | The plan's Risks rows still open until step 11 record the live result once it has run | taken after the live run, below: both rows closed |
| I5 | `stand_upright` reuses the transform writer's placement and precision rule | taken, `4238c56` (`xform.py` `add_local_op`) |
| I6 | `on_startup` reads the Kit app's facts inside a try, so a getter raising an exception `kit_app_facts` doesn't catch costs only the facts, not the bridge's start | taken, `47acbcc`; no test: `extension.py`'s start-up has no harness |
| I7 | `_has_scene_lights` walks instance proxies, so a light an instanceable reference brings doesn't give a false "no lights" warning | taken, `47acbcc`; `tests/test_camera_handler.py` `test_a_light_inside_an_instance_counts` |
| I8 | `start_from` removes the physics attributes and `PhysxMaterialAPI` a `_PhysMat` already there holds and its new source lacks, so the copy is exact | taken, `47acbcc`; `tests/test_material.py` `test_start_from_keeps_nothing_the_new_source_lacks`, `test_start_from_none_leaves_physx_s_default` |
| I9 | `test_15_02b` drops a bare pair too, friction alone against a control, so restitution's PhysX default is checked against a control | taken, `651e52e` |
| I10 | The rotated robot's body differs in X and Z, so a rotation that was dropped can't read as one made | taken, `651e52e` |
| I11 | The Kit facts' test checks the module's own default, four facts each unknown | taken, `651e52e` |
| I12 | `test_23_06` puts lighting back to Default in its cleanup | taken, `651e52e` |
| I13 | `test_12i` checks the segmentation ran before reading its legend | taken, `612d90c` |

## Round 2

**Where:** the fixes, `b2094b1..1c2088f` (round 1's head after the rebase onto `c4fd60e`, to the record's commit), read
by one fresh reviewer, Claude Opus, read only, with scratch checks on usd-core 26.11. **Verdict:** clean: F1 to F6 are
each fixed, with a test that fails without the fix; one new minor, F7, so no third round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tests/test_scenarios.py` `test_15_16` | Round 1's | fixed: `USD_ROTATION` against PhysX's pose at load and after 30 steps fails on a base pulled back at load |
| F2 | minor | the three descriptions | Round 1's | fixed: `tests/test_contract.py` `test_a_description_says_what_the_tool_now_does` |
| F3 | minor | `stand_upright`, `handle_create_robot` | Round 1's | fixed: `tests/test_robot.py` `test_a_turn_reuses_an_attribute_of_its_name_out_of_the_order_in_its_precision` |
| F4 | minor | `core/formatter.py` | Round 1's | fixed: `tests/test_formatter.py` `test_rot_at_a_tiny_scale_is_its_turn` |
| F5 | minor | the summed op's tests | Round 1's | fixed: both read the attribute back |
| F6 | minor | `test_12j` | Round 1's | fixed: either warning, once an `inspect_prim` call |
| F7 | minor | `core/usd.py` `rotation_of` | A prim whose world scale on one axis is under about 3e-16 of the others', but not 0, passes the tolerance of 1e-30, and `Factor` can't recover a ratio past double precision: `rotateY 30` at scale (1, 1, 1e-16) printed `rot = 1.0000, 0.0000, 2686424.8522, 0.0000`, where `main` printed no `rot` line. The quaternion's length was 4.8e6 at 3.16e-16, 26864 at 1e-20, 1.29 at 1e-29, and 1.0 at 1e-15. The comment "only a scale of 0 makes a matrix with no rotation to read" overclaimed | fixed in `bf84a65`: a factored rotation whose length isn't 1, within 1e-6, gives none; the comment reworded; `tests/test_formatter.py` `test_a_prim_too_flat_to_factor_has_no_rot_line` at 1e-16, and 1e-15 still read |

**Refuted:**
- **I7's cost:** `handle_capture` already walks `/World` with instance proxies every call, for its boxes
  (`camera.py:342`).
- **I8 reaching other materials:** its only caller passes the tool's own `_PhysMat` (`simulation.py:152-158`); the
  sharing is Q9's accepted risk, for #113, and `RemoveProperty` acts only on the edit target.
- **I6:** `carb.log_warn` isn't a Python log hook (AGENTS.md, Traps, #5).
- **I9 to I13:** each sound: I10's `[1.5, 2, 1]` is distinct, `kit_app()` returns a copy, and `_segmentation` gives an
  error string with no PNG.
- **The rebase:** `test_24_06` is `c4fd60e`'s; the Verify lines of 2.2, 10.1, 20.6 and 26.2, and the Phase 23 note,
  sit well with #103's text.
- **The writing rules:** clean.

**Improvements,** all taken, in `f17b1d7`:

| # | What | Answer |
|---|---|---|
| 1 | 23.6's Verify names only the lighting's warning: word it as a warning naming lighting mode `off` and `viewport_light`, so a Kit that renders the unlit capture all black passes too | taken |
| 2 | A handler test with a `float3 xformOp:rotateX:unitsResolve` on the file's root, pinning the `Tf.ErrorException` catch and the robot's removal | taken: `tests/test_robot_handler.py` `test_a_usd_error_writing_the_turn_leaves_no_robot` |
| 3 | I6's warning was logged before the log reader starts, so `get_logs` never showed it: read the facts after `start_log_reader` | taken |
| 4 | `test_12j` counted any "Image is all-black" as the lighting's, so a lit stage whose capture is black for a renderer not yet warm would fail: count only the texts that name the lighting | taken, on `e1a47f7`'s version of the test |

## Live run

Run by the session on its own headless Isaac Sim 6.2.0 (Kit 110.4.0+feature.386251.187cf21b.gl), Windows, RTX 5090,
at port 8212, with the branch's extension from `1c2088f`, through `105-live.sh`. `105-stage.py` printed the stage's
up axis before each step, and made it the step's with `new_scene` where it differed. Outputs in the session's
scratchpad, `105/`:

| Step | Stage | What ran | Result | File |
|---|---|---|---|---|
| 1 | Z-up | the new and changed integration tests: `test_01_health`, `test_02_sim_state`, `test_08c`, `test_12g`, `test_12i`, `test_12j`, `test_27b` | 7 passed, 3 subtests | `105-live-1-new-tests-z-up.txt` |
| 2 | Z-up, then Y-up after 17.2's `new_scene` | both live suites whole | 193 passed | `105-live-2-suites.txt` |
| 3 | Y-up | step 1's integration tests | 1 failed (`test_12j`, mode stage), 7 passed, 2 subtests | `105-live-3-y-up.txt` |
| 3 | Y-up | `test_scenarios.py`: `test_02_01`, `test_02_02`, `test_10_01`, `test_15_02b`, `test_15_16` | 5 passed | `105-live-3-y-up.txt` |
| 3, rerun at `e1a47f7` | Y-up | step 1's integration tests | 7 passed, 3 subtests | `105-live-3b-y-up-rerun.txt` |
| 1, rerun at `e1a47f7` | Z-up | `test_12j` | 1 passed, 3 subtests | `105-live-1b-z-up-12j.txt` |
| 1, after round 2, extension from `bc125ef` on a fresh Kit | Z-up | step 1's integration tests | 7 passed, 3 subtests | `105-live-4-z-up.txt` |
| 3, after round 2, the same Kit | Y-up | step 1's integration tests | 7 passed, 3 subtests | `105-live-5-y-up.txt` |

Round 2 changed `on_startup` (the Kit app's facts read after the log reader starts) and `rotation_of` (F7), so a
fresh Kit took `bc125ef`'s extension: `test_01_health` and `test_02_sim_state` show the facts still read, `test_08c`
the rotation, and Kit's log had no "read unknown" warning.

- **The failure:** `test_12j` read `has_scene_lights` once, in the lighting mode it found, Default, which step 2's
  `test_23_06` leaves. A light rig puts lights of its own on the stage, and mode stage takes them away. So the read
  said lit, and the stage-mode capture rightly warned that it wasn't. A read-only probe, `105-probe-lights.py`, showed
  mode Default and only the rig's lights, `/OmniKit_Viewport_LightRig/Lights/DomeLight` and `.../DistantLight`, found
  alike by `Traverse` and by the walk over instance proxies. The test was wrong, not the bridge. Fixed in `e1a47f7`:
  each mode's expectation is read after switching to it.
- **The plan's open risks:** `test_27b` (Kit's assembler adds no second turn) and `test_15_16` (the turned Franka holds
  USD's pose at load and after 30 steps) passed on the Y-up stage. Both Risks rows are closed (I4).
- **What it couldn't show:** Isaac Sim 5.x (Kit 107); Linux; USD Composer, which isn't on this machine; the GPU module,
  `test_gpu_force.py`, not run as `apply_force` didn't change.

## Checks

- **The gate:** `uv run tools/gate.py full` after the fixes and the rebase onto `c4fd60e`.
- **The live suites:** not run at `926ccab`. The live script, `105-live.sh` in the session's scratchpad, now runs the
  new integration tests on a Z-up stage, both suites whole, then the new integration tests and the scenario tests
  whose Y-up branch only shows there (`test_02_01`, `test_02_02`, `test_10_01`, `test_15_02b`, `test_15_16`) on a
  Y-up stage. Before each step it prints the stage's up axis, and makes it the one the step needs with `new_scene`.
