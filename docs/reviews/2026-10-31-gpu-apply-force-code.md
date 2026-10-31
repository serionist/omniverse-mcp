---
subject: "Push bodies through PhysX's tensor API under the Direct GPU API (#68)"
base: main (b3d1ba1)
head: b3ead8c
date: 2026-10-31
round: 1
tier: split (two fresh reviewers on Claude Opus: the product code; the tests and docs)
verdict: needs-fixes
---

# Review: apply_force through PhysX's tensor API under the Direct GPU API

Read from the branch's diff against `main`, 19 files and +1862/-307, split in two: the product code (`core/force.py`,
`handlers/simulation.py`, the tool) against the installed `omni.physics.tensors` 110.4.4 and the plan's approved
decisions; the tests and the docs. Five minors, as both reviewers rated them, each fixed by the author with a test
where one could fail without it. No second round follows, as none is a blocker or a major.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/simulation.py`, `handle_apply_force`; the plan | The path rule wasn't the one the maintainer approved. Q7 was approved as "the tensor path, if U5 shows the push lands", and the probe's E16 shows it lands on a CPU scene with the setting on; after the approval the plan and the code narrowed it to `/physics/suppressReadback` together with the first scene's `physxScene:enableGPUDynamics`, which wasn't put to the maintainer. It also left a gap: the setting on by hand outside Isaac Sim, with a scene without `PhysxSceneAPI` or no scene, read GPU dynamics as off, so the push took `apply_force_at_pos`, which can answer success and move nothing on a GPU scene (#58's E8) | fixed in `e69d40b`: the tensor path whenever the setting is true, and `gpu_dynamics` gone with its tests. The plan's "What it settles" and the Design's "Which path a push takes" say the approved rule, and that the narrowed one went back to it after this review; TOOLS.md, the tool's description, the `simulate` skill, ARCHITECTURE and the CHANGELOG say the rule so. `test_with_the_setting_on_every_scene_takes_the_tensor_path`, for a scene with GPU dynamics, a CPU scene, a scene that doesn't say and none: the last three fail against `b3ead8c`. `test_with_readback_on_every_scene_takes_apply_force_at_pos` guards the other side |
| F2 | minor | `handlers/simulation.py`, `_push_with_tensors` | A body whose name repeats deeper under its parent was refused. In `omni.physics.tensors` 110.4.4, `create_rigid_body_view(path)` matches a plain last component at any depth under its parent (`/physics/tensors/recursiveLeafPatternMatch`, on by default; `api.py` 248-315), so the view of `/World/Cube` holds `/World/Table/Cube` too: 2 rows, and the handler's `count != 1` answered "PhysX holds no rigid body at /World/Cube" for a body PhysX holds | fixed in `86e11d3`: refused only when the view's `prim_paths` lack the prim. Otherwise its row is its place there: the centre of mass comes from that row of `get_transforms` and `get_coms`, reshaped to `(count, 7)`; the force and the point go in as `(count, 3)` float32, zero but that row; the indices are `[row]` as uint32. `recursiveLeafPatternMatch` is left as it is. `test_a_body_whose_name_repeats_deeper_under_its_parent_is_pushed_alone_on_its_own_row`, at the centre of mass and at a given point, its twin first so the body is row 1: both fail against the handler before. `test_a_view_of_only_a_twin_is_a_body_physx_doesnt_hold` refuses a view without the prim. The fake view now matches as 110.4.4 does (`test_the_fake_view_matches_as_the_tensor_api_does`) |
| F3 | minor | `handlers/simulation.py`, the refusal without `omni.physics.tensors` or warp | The error said which module was missing and no next step | fixed in `2343169`: it says to turn the missing one on with `manage_extensions` (`omni.physics.tensors`, or `omni.warp.core` for warp), or to push with readback on, where `apply_force_at_pos` pushes (E15): stop the simulation, run `carb.settings.get_settings().set_bool('/physics/suppressReadback', False)` with `execute_script`, and play again. TOOLS.md's refusals table says so. `test_a_kit_app_without_the_tensor_api_or_warp_refuses_and_names_the_issue`: both of its cases fail against the handler before |
| F4 | minor | `handlers/simulation.py`, around line 363 | A comment gave a plan id as its reason, "(what E14 measured)"; the `finally`'s did the same with E5 | fixed in `0e8565c`: the warp frontend takes float32 data and 32-bit indices only (`as_contiguous_float32`, `as_contiguous_uint32`), and the backend reads each array on the device it was made on, so all three are made on the view's; invalidating our view leaves Isaac Sim's own valid, as measured on Isaac Sim 6.2 |
| F5 | minor | `tests/conftest.py`, the live tests' rule | A leftover `OMNIVERSE_MCP_GPU=1` turned a default live run into an all-skipped green one. A PowerShell `$env:` variable lasts the session, so after the GPU run `uv run pytest tests/test_integration.py tests/test_scenarios.py` with `OMNIVERSE_MCP_SIM=1` skipped every test, "runs the GPU module alone", and exited 0. `finish-work`'s Traps record the same trap for a refused token, guarded by `OMNIVERSE_MCP_SIM=1` making the suites fail rather than skip | fixed in `51e4e60`: `live_rule` decides each test; under both variables a live test that isn't `gpu` fails at setup, in a `tryfirst` `pytest_runtest_setup`, before any fixture, with "OMNIVERSE_MCP_GPU=1 is set: it runs the GPU module alone; unset it to run the live suites", so the run is red and never reaches Kit. `pytest tests/test_gpu_force.py` alone is unaffected. `test_which_tests_run_skip_or_fail` and `test_a_gpu_run_fails_the_other_live_tests_and_says_to_unset_it`; `test_a_gpu_run_fails_a_live_class_before_its_set_up_class` runs a real pytest on two live classes and shows the failing one's `setUpClass` never runs (with the hook made `trylast` it runs, and the test fails). CONTRIBUTING gives PowerShell's form as one line that sets the variables, runs the module and ends `Remove-Item Env:OMNIVERSE_MCP_GPU`, and bash's as a one-shot `VAR=1 cmd`; AGENTS.md's line on the live suites names the exception within its three lines, at 150 |

Refuted, each from the code:

- **The product code:** the arrays' shapes, dtypes and device against `api.py`: `(count, 3)` float32 for the force and
  the point, the indices uint32, all on `view.device`, the frontend's own; the devices of `get_coms` (the parameters',
  the CPU) and `get_transforms` (the simulation's), both read to the host with `.numpy()` before use; the quaternion's
  order, x, y, z, w in `get_transforms` and in `world_point`; `invalidate()` in the `finally`, which runs after a
  refusal inside the `try`, a failure and a push alike, and logs its own failure rather than answering it; nothing
  awaited between the pose and the push, as the handler's one `await` comes before the timeline is read; the catch's
  scope, `Exception` from the view's creation to the push only, with the step's error and the refusals before it and
  a cancellation a `BaseException`; the refusal order, tested; stopped winning over a missing module, as the import is
  tried only when the simulation isn't stopped; a bad step refusing a plain force too, since a scene whose
  `timeStepsPerSecond` isn't a positive number is one PhysX can't step either, which TOOLS.md lists; a force lasting
  past one step on the GPU, which E13 and E14 measured exact, 0 to 10 then 10 to 20; several scenes, the first in
  stage order giving the step, as documented; the tool contract, `tests/fixtures/mcp-tools.json` untouched and the
  descriptions outside it.
- **The tests and the docs:** `PhysicsChecks` collected twice, which has no test of its own to collect; the mixin's move
  changing anything, its 14 definitions AST-identical and the scenarios' 121 tests in the same order; `test_06`'s
  exact echo of a given point, which the handler answers as given; `test_01` passing on a Kit switched back, which
  CONTRIBUTING's restart after the module covers (the improvement below); the momentum checks telling a push from
  none, with gravity off, no contact and a 2% band around 10 or 5; the step read two ways, through `PhysxSceneAPI` in
  the test and by the attribute's name in the handler, both 1/60 on the test's scene, where a mismatch would fail
  each force's check; a transport error in `test_02`, which leaves Kit unanswering for `test_03`'s own calls before
  any switch; a restart undoing the switch, as the settings and the unsaved stage live in the running Kit only; the
  cleanup's print, which names the restart whether `set_device("cpu")` worked or not; TOOLS.md's no-mass row, which is
  the CPU path's, as the tensor path reads the centre of mass from the view's row of the body; the attributes
  `set_device` writes into the open stage, which a restart doesn't keep, as the stage isn't saved;
  `OMNIVERSE_MCP_GPU` as a one-way door, which only the tests read, never the console script; the collection rule,
  whose `gpu` case holds whatever `OMNIVERSE_MCP_SIM` is; `strict_markers`, with `gpu` in `pyproject.toml`'s markers;
  the writing rules.

Improvements:

| Improvement | Answer |
|---|---|
| A unit test that `tests/test_gpu_force.py`'s `pytestmark` names both `gpu` and `sim`, since #94's guard of a hung Kit keys on `sim` | taken in `51e4e60`: `test_the_gpu_module_is_marked_gpu_and_sim` |
| One walk of the stage for the physics scene per push | taken in `6ac1d9d`: after F1 only `step_seconds` looks, on the tensor path. `test_a_push_looks_for_the_physics_scene_once_at_most` counts the looks on both paths, none and one; against `b3ead8c` the tensor path looked twice |
| Name `apply_force_at_pos` where comments and docstrings said "today's call" | taken in `e69d40b` (`core/force.py` and the handler) and `6ac1d9d` (the tests) |
| The plan said the step's scene is one "which the answer names"; the error names it, the answer doesn't | taken in `466d7b9`: the plan says the error names it when its step can't be used |
| A live test that two paused impulses on one body add up on the Direct GPU API: #58's E4 measured that pushes add on the CPU pipeline, the GPU is unmeasured, and the tool says a paused push works | taken in `9526e57`: `test_15_two_impulses_while_paused_add_up`, after the switch in the module's order, two impulses of 10 N s then a check of 20; its failure gives the change it found, and says 10 would mean the tensor path sets the step's force rather than adding to it |
| Read `/physics/updateToUsd` in the default suites' setup, to catch a Kit a GPU run left switched | later: its value on a fresh Isaac Sim is unmeasured, so the check could refuse a good Kit; an issue to open once it is measured |

Not covered: the reviewers had no Kit and ran nothing live. Isaac Sim 5.1 and Kit 107 are untried. PhysX's own
default for a scene without `PhysxSceneAPI`, GPU dynamics or not, is unread; since F1 the path no longer depends on it.

## Live run

On `b3ead8c`, Isaac Sim 6.2.0 headless, a fresh Kit at 8212 for each run:

- **The GPU module,** `OMNIVERSE_MCP_SIM=1 OMNIVERSE_MCP_GPU=1 uv run pytest tests/test_gpu_force.py`: 14 passed in
  7.32 s. Every impulse of 10 N s moved the momentum by 10.0 (10.000001 on one link at a point), and every force of
  300 N over one step by 5.0, on lone cubes and an articulation's link, at the centre of mass and at a point. The
  off-centre cube was pushed at its authored centre of mass, 0.150 off its origin. After the switch:
  `suppress_readback` true, `gpu_dynamics` true, device `cuda:0`.
- **Both suites whole,** on another fresh Kit, on the CPU pipeline: 184 passed and 16 subtests in 152.53 s, phase 15
  through the moved helpers.

The fixes' re-run: pending.

## Checks

- **The gate,** `uv run tools/gate.py full`, on `9526e57`, the fixes, before the plan's rewrap (`6e11e86`): 1533
  passed and 201 skipped, coverage 96.59%.
- **Each fix's new tests against the code before it,** swapped in one file at a time: F1, `b3ead8c`'s handler and
  `core/force.py`, 3 of the 4 scenes with the setting on fail, the scene with GPU dynamics passing; F2, F3 and F5,
  the file before each fix, every new test of the fix failing; the scene walk, `b3ead8c`'s files, the tensor path's
  case failing with 2 looks. F5's real pytest fails with the hook made `trylast`, as the live class's `setUpClass`
  then runs.
