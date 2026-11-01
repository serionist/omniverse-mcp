---
subject: "Bring create_prim's usd_path file to the stage's up axis and units, as create_robot does (#119)"
base: main (fb78292)
head: ba2865c
date: 2026-11-01
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split; no blocker or major, so no refuter"
verdict: needs-fixes
---

# Review: Bring create_prim's usd_path file to the stage's up axis and units, as create_robot does

Read from the branch's diff against `main` at `fb78292` by two fresh reviewers, read only, each with its own lenses:

| Reviewer | Lenses |
|---|---|
| (a) | implementation, kit-main-thread, bridge-security, compatibility, simplicity, on the extension |
| (b) | plan-and-intent, tool-contract, tests, docs-freshness, harness-integrity |

Both checked cases with scratch scripts on usd-core 26.11, (a) loading the handlers with Kit faked as the handler
tests do. Nothing ran in Kit. Six minors after merging the two reports, and no blocker or major, so no second round.
The fixes are on the branch after `ba2865c`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/metrics.py` `bring_to_stage`, through `xform.py` `add_local_op` | A file whose default prim is typeless or a `Scope`, Z-up in centimetres, at a new path on a Y-up metre stage, without `position`: the answer said success with a turn of -90 and a scale of 0.01, but the ops went onto a prim that isn't Xformable, so nothing moved. The same call with `position` refused. 42 of 179 bundled Isaac Sim `.usda` files that set a default prim have a typeless one | fixed in `ce1951f`: when a turn or scale is owed and the file's root is typeless or a `Scope`, the new prim is made an `Xform` in the edit layer first, so the file is brought rather than refused; a root of another type with no transform, a `Material` say, gets neither op. `tests/test_metrics.py` `test_a_file_whose_root_has_no_transform_is_made_an_xform_and_brought`, `test_a_file_whose_root_is_a_material_gets_no_turn_or_scale`; `tests/test_scene_handler.py` `test_create_prim_makes_a_typeless_file_root_an_xform_to_bring_it` |
| F2 | minor | `core/metrics.py` `not_brought` | A reference added to a prim already there could leave its physics values in the file's units with nothing in the answer, against Q1's A: `not_brought` compared the file's axis and `metersPerUnit` with the frame only, never the file's units with the stage's. A metre file under a robot `create_robot` scaled by 100 on a centimetre stage kept a contact offset of 0.03 where 3 was right; a file authoring only `kilogramsPerUnit` 0.001 on an Xform kept a mass of 2.0 read as kilograms | fixed in `ce1951f`: a reference this call added reports the values it leaves in the file's units, as `values`; one already there isn't reported. `tests/test_metrics.py` `test_a_reference_added_to_a_prim_already_there_reports_the_values_it_leaves_in_the_file_s_units`; `tests/test_scene_handler.py` `test_create_prim_on_a_prim_already_there_reports_masses_left_in_the_file_s_kilograms` |
| F3 | minor | `tests/test_integration.py` `test_07c`, `_RESOLVE_INTO` | The check of Kit's assembler couldn't fail: Kit's resolve layer goes in as the root layer's first sublayer, weaker than the root layer holding every op `create_prim` wrote, so the ops before and after and the turned-back file's turn read composed values that can't change, and the turned-back check accepted both outcomes. The first live run's "Kit's assembler leaves the turned-back file's turn at -90.0" was `create_prim`'s own op. Kit's change listener also resolves into a sublayer of the root layer, so TOOLS.md's "may lay it down again" was wrong | fixed in `e04ecd1` and `c1491d3`: the script reads each layer's own specs; the test asserts the edit layer's ops are unchanged, Kit's resolve layer holds no spec for any of them, and Kit writes no turn of its own for the turned-back file, pinned to the second live run below; TOOLS.md says Kit's resolve leaves the file as `create_prim` stood it. Live only |
| F4 | minor | `tools/_units.py` `not_brought_line`, `docs/TOOLS.md` | The advice "create_prim at a path under it" left the file on the stage twice: the reference this call added stays on the prim, unturned and unscaled | fixed in `777fdac`: the line says the reference stays, gives the `execute_script` call that removes it, then the new path; the answer carries the reference's path. `tests/test_tools.py` `test_create_prim_names_what_a_prim_already_there_lacks` |
| F5 | minor | `handlers/scene.py` `handle_create_prim`; the plan | Plan step 6's catch-all wasn't built: an exception other than `ValueError`, a USD error or `StepError` after `DefinePrim` left the prim, its ops and its values, as a 500, where `create_robot` removes its prim. The plan's Risks row said TOOLS.md names unloaded payloads; it didn't. Neither was in "What the build changed" | fixed in `ce1951f` and `21e41a3`: any exception takes away what the call made, others reading "Placing the prim failed: ..."; TOOLS.md's payload line; both recorded in the plan, whose Risks row on odd turns now names an ancestor referencing a Kit-saved file. `tests/test_scene_handler.py` `test_create_prim_that_fails_any_other_way_leaves_nothing_and_names_the_step` |
| F6 | minor | `tests/test_scene_handler.py` | The open step's `Tf.ErrorException` branch, a malformed file, had no test; only `FindOrOpen`'s `None` did | fixed in `ce1951f`: `test_create_prim_with_a_file_usd_can_t_read_makes_nothing` |

**Refuted,** each from the code or a scratch check:
- **#112's fixes through the move:** its E1 (a default written takes the samples beside it) and E2 (a value through a
  specializes arc converted once) hold: main's block and `metrics.py` differ by a section header, both tests moved
  byte for byte, and through `create_prim` E1's default goes 0.02 to 2 with samples 0, E2's Base and Arm both read 50,
  inside a frame scaled by 100 too. The 23 tests moved from `test_robot.py` differ only in imports and docstring.
- **Placing:** each axis and units at a new prim (five combinations, heights and contact offsets exact); a second call
  on the same path (one turn and one scale, `position`, `rotation` and `scale` before the `:unitsResolve` ops);
  inside an ancestor `create_robot` turned and scaled (the same file no op and its values by 100, a Y-up metre file
  stood with +90, the stage's own file turned back and scaled with `converted` null, a robot under the robot no op,
  the frame through a typeless parent); a relative `usd_path`, anchored to the edit layer as `AddReference` anchors it,
  with the root or a sublayer in another folder as edit target; files that can't be opened refused with no prim left;
  frames turned so neither Y nor Z is up, taken as the stage's and reported.
- **The rest:** the main thread (synchronous after one update, no executor); no route, auth or settings change; Kit 107
  has `ComputeAssetPathRelativeToLayer`, `GetResetXformStack` and `TransformDir`; import-linter holds; the tool
  contract unchanged; `_physics_exponents`' cache reloaded per test; `test_07c` on a Z-up stage and its cleanup; the new
  tests fail on main but for two guards; `create_robot`'s answer unchanged without a frame; CHANGELOG's bold Q4 line,
  AGENTS.md and ARCHITECTURE.md; no new ignore, skip or ratchet change.

**Improvements,** all taken, in `ce1951f` and `21e41a3`: `bring_to_stage` and `not_brought` read the stage's axis and
units, and the parent's frame, through `prim.GetStage()`, dropping the handlers' duplicated lines and three
parameters; `create_robot`'s two catch branches as one; a `test_tools.py` case for "turned so that neither Y nor Z is
up"; TOOLS.md's `usd_path` row says relative paths; a Risks line on `convert_units` over a whole environment, at
#112's measured 0.58 s for 12,000 prims.

## Live run

My own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, the branch's extension copied in.
`105-stage.py` set the stage's up axis before each step. "The three" are `test_integration.py -k "test_07c or test_27b
or test_27c" -s`.

| Step | Extension | Stage | What ran | Result |
|---|---|---|---|---|
| 1 | `ba2865c` | Z-up | the three | 3 passed |
| 2 | `ba2865c` | Y-up | the three | 3 passed |
| 3 | `ba2865c` | Z-up | both live suites whole | 199 passed |
| 4 | `21e41a3` | Z-up | the three | 3 passed. `test_07c`: "Kit's resolve layer holds {}", the edit layer's four ops unchanged, "Kit's own turn of the turned-back file: None (create_prim wrote -90.0)" |
| 5 | `21e41a3` | Y-up | the three | 3 passed, the same with the turns the other way (outer -90, the turned-back file 90) |
| 6 | `21e41a3` | Z-up | both live suites whole | 199 passed |
| 7 | `21e41a3`, tests at `c1491d3` | Z-up | `test_07c -s`, pinned | 1 passed, the same lines as step 4 |
| 8 | `21e41a3`, tests at `c1491d3` | Y-up | `test_07c -s`, pinned | 1 passed, the same lines as step 5 |

Steps 4 and 5 are what `c1491d3` pinned; steps 7 and 8 ran the pinned test. The extension didn't change after `21e41a3`. Not shown: Isaac Sim 5.x, Linux, USD Composer, a file under an asset Kit's
own drag and drop made (Kit's listener path, which `test_07c` stands in for by running Kit's resolve on the outer
prim).
