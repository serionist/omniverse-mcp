---
subject: "S7b, pin the tool contract: hints, bounds, the golden file (PR #24)"
base: main (4f67227)
head: a441986
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer, who read the handlers behind each bound and hint; findings checked against the code by the main session)
verdict: clean
---

# Review: S7b, pin the tool contract: hints, bounds, the golden file

Read from the pack (the scope diff without the generated `tests/fixtures/mcp-tools.json`, and the input schemas
dumped before and after the change), the handlers in `extension/ovmcp.bridge/`, the installed `mcp` 2.3.0's source
and OpenUSD's docs through Context7. The reviewer confirmed the schema claim: the same parameter names, the same 87
defaults and 27 `required` lists, and 35 added keys, only `minimum`, `maximum`, `exclusiveMinimum` and `enum`. Five
minors, so no round 2; all fixed in `c085cdf`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tools/scene.py`, `tools/usd_advanced.py`, `tools/simulation.py` | Bounds refused a 0 the handlers gave meaning to. `max_depth=0` is the root alone (`if depth > max_depth:`, the root at depth 0) in `get_scene_tree`, `dump_scene` and `get_prim_face_count_tree`. `UsdPhysicsMassAPI` ignores a mass or density of 0, so `set_physics_properties(mass=0)` was the only way back to a mass from density after `mass=5`; `gt=0` refused it. | Fixed: `ge=0` on the three depths and on mass and density, each description saying what 0 does. The golden file and `docs/TOOLS.md` follow; the live smoke ran `get_scene_tree(root="/World", max_depth=0)` and `set_physics_properties(mass=0)`. |
| F2 | minor | `tools/simulation.py`, `draw_debug`; `sim_control`, `manage_extensions` | The `Literal` left out `"lines"`, which the handler draws (`elif draw_type == "lines":`, a polyline through `points`). Both actions' handlers lower-case the action, so `"Play"` worked and is now refused, and CHANGELOG didn't say so. | Fixed: `"lines"` in the `Literal`, `points` described for it, `docs/TOOLS.md` too; CHANGELOG's Breaking bullet names lower case. |
| F3 | minor | bridge `handlers/scene.py`, `handle_clone_prim`, `handle_create_prim` | `EDITS` says nothing is destroyed, but `Sdf.CopySpec` replaces a destination's spec and children, so `clone_prim("/World/Cube", "/World/Table")` wiped an existing Table; `DefinePrim(path, "Xform")` turned an existing Cube into an Xform. A client that runs non-destructive tools without asking would run either. | Fixed in the bridge, keeping `EDITS` true: a clone refuses any destination that holds a prim, a whole batch before it copies anything, and a create refuses a prim of another type (the same type, or a typeless prim, still works). Live test: `test_21_clone_and_create_refuse_to_overwrite`; CHANGELOG under Breaking. |
| F4 | minor | `tools/simulation.py`, `tools/recording.py` | Descriptions promised what the bridge ignores: `draw_debug`'s `duration` is read and unused; its `size` defaulted to 5.0 in the schema, sent only when not 5.0, so the handler's 0.05 drew and `size=5.0` couldn't be asked for; `start_recording`'s `camera_path`, `width` and `height` are stored but `_record_tick` captures the active viewport at its size; `apply_force` without `position` pushes at the world origin, not the centre of mass. | Fixed: each description says what happens now and names #25, opened for the handlers; `size` defaults to 0.05 and is sent when it differs, CHANGELOG under Fixed. |
| F5 | minor | `tools/_params.py`, `camera.py`, `robot.py`, `simulation.py`, `scene.py`, `docs/TOOLS.md` | American spellings in new prose ("meters", "centers", "center", "normalized", "color", "initialization", "visualization"), against AGENTS.md's British spelling. | Fixed in the prose; parameter names such as `center` and `color` stay, being the contract. |

Refuted, each from the code:

- **A refused value reaches the agent without a reason:** `mcp/server/mcpserver/tools/base.py` raises
  `ToolError(f"Error executing tool {self.name}: {exc}")` from the `ValidationError`; the live smoke shows each
  message.
- **`get_logs(count=0)` returned every entry:** an accident of `entries[-0:]`, never documented; `count=2000` does
  the same.
- **Refusing `min_level="WARN"` is a regression:** before, an unknown name filtered nothing (`test_logs.py`); CHANGELOG
  names the change.
- **The golden test can pass vacuously or let a change through:** names, types, bounds, defaults, `required`, hints,
  output schemas and resources are all in the file; only prose is stripped, a parameter named `title` stays
  (`test_prose_goes_and_a_parameter_named_like_it_stays`), and an empty listing doesn't match 41 tools.
- **Hints against the handlers:** `capture_viewport` puts the camera back in a `finally` (`READS`); `get_joint_states`
  only builds a physics view (`READS`); `inspect_prim` moves the camera and leaves it (`EDITS`); `viewport_light`'s
  `Literal` matches its handler; the table in `docs/TOOLS.md` matched the code, 13, 20, 6 and 2.

Not covered by the reviewer: Q1 (the gate) and Q4 and Q12 (the PR text, the live suites), as it ran nothing and the PR
wasn't open; the author ran them (below). kit-main-thread and bridge-security found nothing in the reviewed commit; the
F3 fix reads the stage in handlers that already run on Kit's main thread after `_next_update()`, and touches no route,
token or header.

Improvements:

- **`zoom_offset` bounded `gt=-1`,** where `apply_zoom` already refused it inside Kit: taken in `c085cdf`.
- **A test that each tool sits in `docs/TOOLS.md`'s hints row for its annotation,** a table kept by hand that the
  golden file doesn't cover: taken, `test_the_tool_reference_lists_each_tool_under_its_hints`.
- **An in-memory call showing a bound refuses before the bridge,** now `min(max_depth, 15)` is gone: taken,
  `test_a_value_out_of_range_is_refused_before_the_bridge` (no request reaches the mock bridge).

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for this run, loading `ovmcp.bridge` from the branch's
`extension/`; the maintainer's own Isaac Sim on 8211 was not touched.

- **`a441986`:** the live suites, `-k "not test_10_ and not test_14_"` (#5): 109 passed, then 110 on a second run;
  the failures were #7's `test_16_03` to `16_05` (`omni.debugdraw` is gone in 6.2), plus once
  `test_22_01_inspect_with_segmentation` ("Viewport capture produced no output"), which passed three times alone and
  in the second full run. The suites call the bridge directly, which that commit didn't change.
- **`c085cdf`:** after a restart, to load the changed handler: 109 passed, 5 failed, each failing on `main` too: #6's
  `test_05_03` and `test_07_02` (Y-up gravity) and #7's three. The new `test_21_clone_and_create_refuse_to_overwrite`
  passed.
- **The MCP tools, through SDK v2's in-memory client** (the S7a smoke script, extended): every bound and `Literal`
  refused with pydantic's message and nothing reaching Kit (`max_depth` 16 and -1, `count` 0, `width` 0, `opacity`
  1.5, `zoom_offset` -1, unknown actions, shapes and `"WARN"`); the accepted values ran (`"step"`, `min_level="warn"`,
  `max_depth=0`, `mass=0`); `create_prim` over a Cube as a Sphere and `clone_prim` onto a taken path were refused with
  the new messages; four calls at once and both resources answered. `draw_debug` fails as #7 says.

Not shown: `"lines"` drawing, as every `draw_debug` fails on 6.2 (#7); a Kit app other than Isaac Sim 6.2.

## Checks

`uv run tools/gate.py full` passed on `a441986` (562 tests, coverage 79.01%, floor raised from 78 to 79); on
`c085cdf`, 564 unit tests, ruff, basedpyright and the golden file pass.
