---
subject: "Add set_prim_attribute, which sets one attribute of a prim, such as a light's intensity (#151)"
base: main (6a6982c)
head: 808c345
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the Kit-free core; the route, tool and docs. Minors only, so no second round"
verdict: clean
---

# Review: Add set_prim_attribute

Read from the branch's diff against `main` at `6a6982c` (24 files, about 1,500 lines with the plan) by two fresh
reviewers, read only, against the approved plan `docs/plans/2026-11-02-prim-attribute-tool.md` and the maintainer's
agreement on #151. One read `ovmcp/core/attribute.py`, `write_blocker` and `tests/test_attribute.py`, measuring on
usd-core 26.11; the other the handler, route, client, tool, contract, docs and live tests. Four minors, no blocker or
major; all fixed in `cbedc57`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_attribute.py`, `test_a_colour_on_a_mesh_whose_extent_is_animated_is_set` | No test failed without round 2's rule that the extent is touched only when the box changed: the cache mesh's points were only time-sampled, so the box at the default time was `None` and the comparison never ran; with `_same_box` always false, a colour on a sphere whose extent the session layer holds was refused unnoticed | fixed: the cache mesh has a default `points` beside its samples, and `test_a_colour_on_a_sphere_whose_extent_the_session_layer_holds_is_set` is new; both fail with `_same_box` always false |
| F2 | minor | `ovmcp/core/attribute.py`, `_one` | A `Vec3d` or `Vec4d` was written as `1, 2, 3`, where `get_prim_properties` writes `1.0000, 2.0000, 3.0000`, and a `quath[]` element came back bracketed twice | fixed: double vectors go to `format_value`, a `Quath` is written real then imaginary as `Quatf` and `Quatd` are; `test_shown_writes_values_as_get_prim_properties_does` and `test_a_colour_of_doubles_is_shown_as_get_prim_properties_shows_it` |
| F3 | minor | `ovmcp/core/attribute.py`, `convert` | An integer past a double's range (`OverflowError`), a control character in an asset path (`Tf.ErrorException`) and a lone surrogate in a string or token (`UnicodeEncodeError`) raised past the handler's `ValueError`, a 500 with a traceback | fixed: each a `ValueError` naming the type, nothing written; six rows in `test_a_value_that_doesn_t_fit_is_refused_with_nothing_written` |
| F4 | minor | `tests/test_scenarios.py`, `test_23_07_set_a_light_s_intensity` | Its `mkdtemp` folder stayed behind after every live run, as 23.06's did | fixed: both register `shutil.rmtree` as a cleanup |

**Refuted,** from the code and from measurements:
- **The undo leaves something behind:** each branch measured exact (the old default put back, a default cleared, a
  property removed, the overs a write made dropped under `Sdf.CleanupEnabler`); an empty over already in the layer
  goes too, which holds no opinion.
- **The extent plugins raise after the write:** a turned Cylinder, Capsule or Cone, mismatched `widths`, a broken
  PointInstancer and an empty Mesh each give `None` or an empty box, never an error.
- **The layer rule, ranges, conversions, refusals, time samples and closest names:** each measured as the plan says.
- **The route's guard:** `Origin`, `Host` and the token are checked before the body is read or the route found.
- **Update then lookup, and the main thread:** as `handle_delete_prim`, no executor.
- **The value's types through the schema's union:** `true` stays a bool, `1` an int, `"3000"` a string the extension
  refuses by name; a test now pins each type end to end.
- **The contract:** only the new tool, in order, with `EDITS` hints.
- **An older extension:** an unknown route comes back with the install advice.
- **The hints and security:** an asset path or a script node's input reaches no further than `create_prim`'s
  `usd_path`, and the token already allows `/execute`.

**A correction to the build's own report,** found by the core reviewer: in usd-core `SphereLight`, `RectLight`,
`DiskLight` and `CylinderLight` are `Boundable` (`DistantLight` and `DomeLight` aren't), and their extent follows
`inputs:radius` under the extent rule; an intensity leaves the box as it was, so it never touches the extent.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | A bare session over with no arc on a user's referenced prim sent its writes to the session layer, lost on save | taken: `_holds` skips it, through `spec_has_arcs` in `ovmcp/core/usd.py`; `test_a_stray_bare_session_over_on_a_user_s_prim_doesn_t_send_its_write_to_the_session_layer` |
| I2 | Every relationship's refusal pointed at `set_material`, a joint's `physics:body0` too | taken: only `material:binding*`; a `physics:body0` row |
| I3 | The second tool test sent `[5]` for a double, which the extension refuses, with a token note for a radius | taken: an extent case, a `color3f` list case and a token note case |
| I4 | Pin the value's JSON type end to end | taken: `test_set_prim_attribute_keeps_the_value_s_json_type` |
| I5 | Type the value's list items: `list[Any]` gave the contract's only untyped `items` | taken: `list[float \| bool \| str \| list[float]]`; whole floats are accepted for int types, bools stay bools |
| I6 | `viewport_light`'s description and rig answer name the new tool for a light's intensity | taken |
| I7 | `scenarios.md`'s light intensities set with `execute_script` (Phase 1, 18.2) | left: changes the scripted phases' calls, for an issue of its own |

**Not covered:** the gate and CI, the live suites and the PR's text, which the reviewers could not run or read; the
PR gives them.

**After the review,** `85aeb9a`: a list's items are typed `bool | int | float | str | list[int | float]`, so a whole
number in a list stays an int and an int64 keeps its precision; checked in this session with its tool test.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension rebased onto `db64f77` (#150),
each suite run on a fresh Kit:

- Both live suites: 208 passed on a Z-up stage and 208 on a Y-up stage, with
  `test_23c_set_prim_attribute_sets_a_light_and_a_sphere_s_size_with_its_box` and
  `test_23_07_set_a_light_s_intensity` among them.
- AI scenario phase 23 (run `20261102-181113`): every row PASS; 23.7's tester set the dome light to 500 with
  `set_prim_attribute`, read `written to the stage's root layer` and saw 500.0 in `viewport_light`'s answer.
- O1 twice (runs `20261102-181229`, `20261102-181322`): PASS both, no `execute_script` either time; the first agent set
  the cube's size and the ground plane's axis and size with `set_prim_attribute`, four calls.
- The first O1 judge noted the cube's `extent` reading ±1 beside `size = 0.5`. Measured on the same Kit:
  `create_prim`'s Cube authors no extent, so the tool, as planned, has no extent to update, and `get_prim_bounds` reads
  0.5 m from the size; the prim block prints the schema's fallback. Filed as #163.
