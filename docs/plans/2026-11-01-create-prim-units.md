---
title: Bring create_prim's usd_path file to the stage's up axis and units, as create_robot does
issue: "#119"
status: draft
approved_by:
approved_at:
---

# Bring create_prim's usd_path file to the stage's up axis and units, as create_robot does

`create_prim(usd_path=...)` references a file as it is: a Z-up prop on a Y-up stage lies on its side, and a
centimetre asset on a metre stage comes in 100 times too large, its physics values in the file's units.
`create_robot` stands a file of the other up axis upright since #105, and #112 scales a file of other units and
converts its physics values, in a Kit-free core. This plan has `create_prim` call that same core, so the two tools
bring the same file in alike, as Kit's metrics assembler brings a dropped one.

Reading `create_prim` shows three things `create_robot` never meets: a prim already at `prim_path` takes the
reference (Q1), a prim can be made inside an asset already brought to the stage (Q2), and the file is never opened,
so one that can't be opened makes an empty prim reported as created (Q3). Kit's own tests answer Q2: Kit measures a
file referenced inside a prim it resolved against that prim's frame, not the stage (K1). This plan does the same, for
both tools.

## Goal

When this is done, with this release's Kit extension:

- `create_prim` with a `usd_path` whose authored `upAxis`, `metersPerUnit` or `kilogramsPerUnit` isn't the stage's
  brings the file to the stage as `create_robot` brings a robot file: `xformOp:rotateX:unitsResolve` stands it
  upright, `xformOp:scale:unitsResolve` scales it to its real size, and its physics values and cameras' distances are
  converted by #112's rules. The answer says so, in the same lines as `create_robot`'s.
- A file placed inside an asset already brought to the stage (a robot `create_robot` turned, a prop Kit dropped) is
  measured against the frame it lands in: the stage's, turned and scaled by its ancestors' `:unitsResolve` ops, as
  Kit's assembler measures it (K1, Q2). Its physics values are still converted to the stage's units. `create_robot`
  does the same.
- A reference added to a prim already at `prim_path` goes on as the file is, and the answer says what it left and how
  to get it (Q1).
- A file that can't be opened is refused before anything is made, as `create_robot` refuses one (Q3).
- A file that authors no `upAxis` or `metersPerUnit` is left as it is, as #105's Q5 and #112's Q2 settled.

Why: an agent loading a prop or a scene part with `create_prim` gets a different result from `create_robot` for the
same file, and from Kit's own drag and drop.

| In scope | Out of scope |
|---|---|
| `create_prim`'s `usd_path`: the turn, the scale, the physics values, the answer | Payloads: `create_prim` adds a reference only, and offers no payload (a payload inside the file is under Risks) |
| The frame a prim lands in, for `create_prim` and `create_robot` (Q2) | `create_prim` loading Isaac Sim's library paths (`/Isaac/...`) as `create_robot` does: `usd_path` stays an absolute path or a URL |
| Refusing a file that can't be opened (Q3) | What #112 left: a nested file of other units gets no op of its own, re-converting when the file changes, mimic gearing |
| Moving #105's and #112's file core out of `core/robot.py` into `core/metrics.py`, shared by both tools | `clone_prim` and `open_scene`: a copy keeps its source's ops, and a stage's units are the ones all else is measured in |

## What the code, the sources and the checks say

### The code, at `84acfa5` (and #112's plan)

| Where | What it does |
|---|---|
| `handlers/scene.py:259-322`, `handle_create_prim` | Checks the transform, then `DefinePrim(prim_path)` and `GetReferences().AddReference(usd_path)`, the path as given. Never opens the file. A prim already there of the same type takes the reference; `held` tells a reference its edit layer already listed, so a refusal takes away only a reference this call `added`. A refusal from `write_transform` removes the prim the call `made`, else that reference |
| server `tools/scene.py:158-195` | Prints `Created {type} at {path}` and nothing of the file |
| `handlers/robot.py:57-145`, `handle_create_robot` | Refuses a prim already there; opens the file first (`usd_file_url`, `Sdf.Layer.FindOrOpen`), refusing one it can't open; then #105's turn, `write_transform`, and any refusal removes the prim |
| `core/robot.py:41-78` | #105: `UP_AXIS_OP`, `file_up_axis`, `up_axis_turn`, `stand_upright` |
| #112's plan, Design | Adds to `core/robot.py` `UNITS_OP`, `Units`, `Factors`, `Exponents`, `layer_units`, `units_factors`, `scale_to_stage`, `unit_exponents`, `convert_units` (its uncommitted work also has `Converted` and `Table`); to `handlers/robot.py` `_physics_exponents()`, the PhysX schema's table, and the answer's `units_scale`; to `tools/robot.py` `_scaled_line`. The turn, scale and conversion all compare the file with the stage |
| `tests/test_scene_handler.py:174-242` | `create_prim`'s handler on usd-core: the refusals and what each takes away |
| `tests/test_integration.py:520-542`, `test_07b` | References `_ROBOT_USDA`, which authors no `upAxis` or `metersPerUnit`: unchanged by this plan |

### The sources

Read on disk in Isaac Sim 6.2's install (`isaacsim/extscache/`) and in Isaac Sim 5.1's (`D:\isaacsim5.1\extscache\`):

| # | What | Where |
|---|---|---|
| K1 | Kit's assembler's recursive test: a metre file referenced at `/World/xformInst` on a centimetre stage, resolved (×100); then the same file at `/World/xformInst/xformInst`, defined in the stage's root layer. Its cube sits at 100 before the nested prim is resolved and still at 100 after, and the nested prim gets `xformOp:scale:unitsResolve`: the nested file is measured against the frame it lands in, already metres, not against the stage. Kit 107's test is the same | `omni.usd.metrics.assembler-110.1.2`: `core/tests/referenceTests.py:239-276`; `-107.3.1`: the same test |
| K2 | Attribute values are converted against the stage: `resolvedValue = value * (MPU / stageMPU) ^ metersExponent * ...`, MPU being the units of the layer the value is authored in | the same `docs/README.md:131` |
| K3 | A payload is resolved as a reference is: `xformOp:scale:unitsResolve` on the prim holding it | the same `core/tests/payloadTests.py:102-122` |
| K4 | `/metricsAssembler/conformToXformCommonAPI`, off by default (#112's P1 read it off in the session's Kit): when on, Kit writes the turn and the scale into the prim's own `rotateXYZ` and `scale` ops, with no `:unitsResolve` op | the same `docs/README.md:23`; `referenceTests.py:207-235` |

### usd-core 26.11 (scratch checks, `119/usd-checks.py` in the session's scratchpad, not kept)

| # | What it showed |
|---|---|
| U1 | A relative `usd_path`: `AddReference` anchors it to the layer it is authored in, so `props/box.usda` composes the file beside the stage's own. `Sdf.Layer.FindOrOpen("props/box.usda")` from another working folder finds nothing; `FindOrOpen(Sdf.ComputeAssetPathRelativeToLayer(edit_layer, usd_path))` finds the layer the prim composes. An absolute path or a URL anchors to itself |
| U2 | A metre Z-up box, 1 tall, under a prim that references the same file and holds `rotateX:unitsResolve` -90 and `scale:unitsResolve` 100, on a centimetre Y-up stage: with no ops of its own it stands 100 tall along Y, as its ancestor's does. Given the stage's ops (-90, ×100) as well, it is 10,000 long and lies along -Z |
| U3 | `AddReference` twice with the same file keeps one reference |

### The probe (pending)

`119-probe.py`, in the session's scratchpad's `119/`, run through `119-probe.sh` on the session's headless Isaac Sim 6.2
at 8212 with main's extension. In-memory stages in USD's stage cache, resolved into an anonymous layer of each, as
#112's probe did; nothing is turned on or off. It reads what Kit's `resolve_hierarchy` writes in five cases:

| # | Case | What it settles |
|---|---|---|
| N1 | A metre file under a resolved metre prim, on a centimetre stage: the inner prim's ops, both shapes' world boxes, both contact offsets and their layer | K1's value read out: the inner op at 1, and whether its contact offset is converted against the stage (2) or the frame (0.02) |
| N2 | A Z-up and a Y-up file under a resolved Z-up prim, on a metre Y-up stage | No turn for the Z-up file, +90 for the Y-up one |
| N3 | A metre file under a plain Xform holding a scale of 100 of its own, on a centimetre stage | Whether Kit counts a parent's own scale as the frame's units: this plan doesn't |
| N4 | A metre file under a prim that references a metre file but holds no op, on a centimetre stage | Whether Kit tells the frame by the ancestors' ops, as this plan does, or by their composition |
| N5 | One prim referencing a centimetre file and a metre file, on a metre stage | What Kit does with two references of different units on one prim (Q1) |

## Design

Q1 to Q4's A, as recommended.

### The core (`core/metrics.py`, Kit-free)

A pure move first: #105's and #112's functions leave `core/robot.py` for `core/metrics.py`, named after Kit's metrics
assembler, whose job they do; `core/robot.py` keeps what is a robot's (`is_usd_file`, `robot_prim_path`,
`articulation_root`). Their tests move from `tests/test_robot.py` to `tests/test_metrics.py`. Alternative: import
them from `core/robot.py` into the scene handler; left, since a module named for robots would then hold
`create_prim`'s rules.

Then a type and three functions:

| Name | What |
|---|---|
| `Frame` | Named tuple `(up_axis, meters, prims)`: the up axis and `metersPerUnit` of the frame a new prim lands in, and the ancestors whose `:unitsResolve` ops made it differ from the stage's |
| `frame_of(parent, stage_axis, stage_meters)` | Walks `parent` and its ancestors. Each `xformOp:scale:unitsResolve` in an ancestor's op order multiplies the frame's `metersPerUnit` by its first value: a prim scaled ×100 on a centimetre stage holds metres. Each `xformOp:rotateX:unitsResolve` adds its degrees: a net -90 on a Y-up stage makes the frame Z-up, +90 on a Z-up stage Y-up, 0 the stage's; any other net turn is taken as the stage's (Risks). Ops not in the order, and an ancestor's own unsuffixed ops, a user's scale among them, don't count (N3) |
| `bring_to_stage(prim, layer, frame, stage, table)` | The sequence #105 and #112 put in `create_robot`'s handler, in one place: the turn from the file's up axis to the frame's (`file_up_axis`, `up_axis_turn`, `stand_upright`); the scale by the file's `metersPerUnit` over the frame's (`layer_units`, `units_factors`, `scale_to_stage`); and, when the file's units aren't the stage's, `convert_units(prim, file, stage, table)`, against the stage as Kit converts values (K2), whatever the frame. Gives `Brought(up_axis_turn, units_scale)`, the two answer fields as #105 and #112 define them, built here so both tools send the same and usd-core tests them. `table` None (no PhysX schema in this Kit) converts only the cameras' two values and sets `units_scale.table` false, as #112 has it |
| `not_brought(layer, frame)` | For a prim already there (Q1): the file's up axis and units beside the frame's where they differ, else None |

### The bridge

- **`handlers/_utils.py`:** `_physics_exponents()` moves here from `handlers/robot.py`, so both handlers read the
  PhysX schema's table the one way.
- **`handle_create_robot`:** `frame_of(prim.GetParent(), ...)` and `bring_to_stage` in place of its own steps; its
  answer gains `frame`. A robot made under a turned or scaled asset is no longer turned or scaled twice (Q2).
- **`handle_create_prim`,** in this order:
  1. The transform checked, as today.
  2. With a `usd_path`: the file opened, before anything is made, at the path the reference will compose:
     `Sdf.ComputeAssetPathRelativeToLayer(edit_layer, usd_path)` (U1), then `Sdf.Layer.FindOrOpen`. A
     `Tf.ErrorException` or None is refused: "Could not open <path>: ... Nothing was created" (Q3). The reference
     itself keeps `usd_path` as given, as today.
  3. The type check, `made` and `held`, as today; `DefinePrim` and `AddReference`, as today.
  4. A prim this call made (`made`): `bring_to_stage(prim, layer, frame_of(prim.GetParent(), ...), stage_units,
     _physics_exponents())`. A prim already there that took the reference now (`added`): nothing is written, and
     `not_brought(layer, frame)` goes into the answer (Q1). A prim that already held it: nothing, as today.
  5. `write_transform`, as today: `position`, `rotation` and `scale` go into the prim's own ops, before the
     `:unitsResolve` ops (`core/xform.py`'s `_is_units`), so they stay in the parent's frame and `scale=2` makes the
     file twice its real size.
  6. Any exception from step 4 to step 5 takes away what the call made, as today's refusal does: the prim it made,
     whose `RemovePrim` takes the ops and the converted values with it, all under its path in the edit layer; else
     the reference it added. A `ValueError` or a `Tf.ErrorException` keeps today's error and its ". Nothing was
     created"; any other names the step, as #112's: "Converting the file's values to the stage's units failed:
     KeyError: ... Nothing was created".
  7. `enable_physics`, as today, then the answer.

The answer gains, beside `prim_path` and `type`:

```json
{"up_axis_turn": {"file": "Z", "stage": "Y", "degrees": -90.0, "op": -90.0,
                  "op_name": "xformOp:rotateX:unitsResolve"},
 "units_scale": {"meters_per_unit": {"file": 0.01, "stage": 1.0}, "kilograms_per_unit": null, "factor": 0.01,
                 "op": [0.01, 0.01, 0.01], "op_name": "xformOp:scale:unitsResolve", "converted": 3, "left": [],
                 "left_count": 0, "table": true},
 "frame": null, "not_brought": null}
```

`up_axis_turn` and `units_scale` are #105's and #112's, null when nothing was done. `frame` is
`{"up_axis": "Z", "meters_per_unit": 1.0, "prims": ["/World/Robot"]}` when an ancestor's `:unitsResolve` ops make
the frame differ from the stage's; the turn's degrees and the scale's factor are then against it. `not_brought` is
`{"prim_path": ..., "file": {"up_axis": "Z", "meters_per_unit": 0.01}, "frame": {"up_axis": "Y", "meters_per_unit":
1.0}}` when a reference went onto a prim already there as the file is.

### The server

- **`tools/_units.py`** (new): `_turned_line` and `_scaled_line` move here from `tools/robot.py`, with a frame line
  and a `not_brought` line, and `units_lines(result)` gives all four for both tools:

  ```text
  Turned upright: the file is Z-up and the stage Y-up, so -90° about X went into xformOp:rotateX:unitsResolve, which
  now reads -90, as Kit's metrics assembler turns a dropped file
  Measured against the frame it lands in, not the stage's: /World/Robot's :unitsResolve ops make it Z-up, in
  metersPerUnit 1
  Left as the file is: /World/Shelf was there before this call, so its reference went on unturned and unscaled
  (the file Z-up in metersPerUnit 0.01, the stage Y-up in 1); delete_prim it and create_prim again to have it brought
  to the stage
  ```

  With a frame, the turned and scaled lines name "the frame it lands in" where they name the stage. An older
  extension sends none of the fields, and nothing is printed.
- **`create_prim`'s description,** in place of "usd_path adds its reference to a prim already there.": "A usd_path
  file whose upAxis, metersPerUnit or kilogramsPerUnit isn't the stage's is brought to the stage as create_robot
  brings a robot file: turned upright, scaled, its physics values converted, and the answer says so; one that
  authors none is left as it is. usd_path adds its reference to a prim already there as the file is. A file that
  can't be opened is an error."

### Alternatives

- **Kit's assembler** (`resolve_hierarchy`) for `create_prim`: #112's Q1 B, turned down there for reasons that hold
  here (its physics rules reach Isaac Sim's base and headless apps only through a deprecated extension), and the
  two tools would then differ.
- Q1 to Q3 hold the rest.

## Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | `create_prim` puts `usd_path`'s reference on a prim already at `prim_path`. Which prims are turned, scaled and converted? | **A.** Only a prim this call makes. A reference added to a prim already there goes on as the file is, and the answer says so and how to get it brought. **B.** Also a prim already there that composes no reference or payload, such as an Xform made first; its edit-layer spec is copied aside before the call and put back on a refusal, since `RemovePrim` would take the prim itself. **C.** Every prim | A: it never turns or scales content the call didn't bring, and the case it must get right, `create_prim` called again on the same path and file to move the prim, is a prim that already holds the reference, where a second turn would lay it down (U3). B serves an Xform made first, a rare order, for a snapshot of the edit layer; C turns whatever else the prim holds (N5) | |
| Q2 | A prim made inside an asset already brought to the stage, such as a gripper file under a robot `create_robot` turned, or a part under a prop Kit dropped and scaled? | **A.** Measure the file against the frame it lands in: the stage's, turned and scaled by the ancestors' `:unitsResolve` ops, as Kit's recursive test does (K1); physics values still against the stage (K2). For `create_prim` and `create_robot`. **B.** Against the stage, as `create_robot` does today. **C.** B, and a line naming the ancestor | A: what Kit does, and the only one that leaves the file its real size and upright: with B, a metre file inside a metre asset on a centimetre stage comes in 100 times too large, and a Z-up file inside a turned robot lies on its side (U2), where today, with no op at all, both come out right by their ancestor's. The probe reads Kit's values (N1, N2) and how it tells the frame (N3, N4); where Kit differs, the plan says so and this is asked again | |
| Q3 | A `usd_path` that can't be opened: today it makes an empty prim, answered as created | **A.** Refused before anything is made, as `create_robot` refuses one: "Could not open <path>: ...". **B.** Referenced as today, nothing turned or scaled, a line saying the file couldn't be read | A: the file has to be read for its units anyway, and an empty prim reported as created helps no one. The path is anchored as the reference anchors it (U1), so a relative path that composes today still opens | |
| Q4 | Someone who turned or scaled such a prim themselves, with `rotation` or `scale`, now gets it turned or scaled twice | **A.** CHANGELOG's Fixed entry says so, in bold, as #105's Q7 and #112's Q7. **B.** Under Breaking changes | A: the schema doesn't change, and the answer names the turn and the scale | |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change (`tests/fixtures/mcp-tools.json` stays;
  `golden.py` strips descriptions). `/scene/create` keeps its path and gains answer fields, `up_axis_turn`,
  `units_scale`, `frame` and `not_brought`; `/robot/create` gains `frame`. `PROTOCOL` stays 1.
- **What users notice:** a file of another up axis or other units comes in upright at its real size, its physics in
  the stage's units, and the answer says so; Q4 for a call that did it itself; a file that can't be opened is refused
  (Q3); a robot or a file placed inside a turned or scaled asset is no longer turned or scaled twice (Q2). A file
  of the stage's own up axis and units, or one that authors neither, comes in as today.
- **Older extensions:** nothing is turned or scaled, and the server prints nothing. `docs/TOOLS.md` says so.
- **Kit apps:** the ops are plain USD; the values convert where `pxr.PhysicsSchemaTools.units` imports, as #112.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | The probe, N1 to N5, run by the session; this plan updated on what it shows | `119-probe.out.txt` |
| 1 | This plan, the branch's first commit; review round 1 and the maintainer's answers | `review-plan`, then the maintainer |
| 2 | #112 merged: rebase onto main | its core and handler on the branch |
| 3 | The move, no behaviour change: `core/robot.py`'s turn and units to `core/metrics.py`, their tests to `tests/test_metrics.py`; `_physics_exponents` to `handlers/_utils.py`; `_turned_line` and `_scaled_line` to `tools/_units.py` | the moved tests pass unchanged |
| 4 | Core: `Frame`, `frame_of`, `bring_to_stage`, `not_brought`; `handle_create_robot` calls them | `tests/test_metrics.py`, `tests/test_robot_handler.py` |
| 5 | Bridge: `handle_create_prim` | `tests/test_scene_handler.py` |
| 6 | Server: `units_lines`, `create_prim`'s lines and description | `tests/test_tools.py`; `tests/test_contract.py`; the golden file unchanged |
| 7 | Docs (below) | the gate's checks |
| 8 | Live: the tests below, run by the session on Isaac Sim 6.2 headless at 8212, on a Z-up stage and a Y-up one, then both suites whole | no failure beyond `main`'s on the same Kit |
| 9 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fails on main with #112 merged, where it can.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_metrics.py` | The moved tests, unchanged. `frame_of`: no ancestor ops give the stage's and no prims; an ancestor scaled ×100 on a centimetre stage gives metres, naming it; two ancestors multiply; -90 on a Y-up stage gives Z, +90 on a Z-up stage Y, the two on two ancestors cancel; an op not in the order, and a user's unsuffixed scale of 100, don't count; a net turn of 180 gives the stage's axis. `bring_to_stage`: a Z-up centimetre file on a Y-up metre stage gets the turn then the scale and both answer fields; U2's file under U2's ancestor gets no op and its contact offset ×100, with the frame; a Y-up file under a turned Z-up frame on a Y-up stage gets +90; a file in the frame's units on a stage of others gets no op and its values converted; an unauthored file gets nothing, written or answered; `table` None converts only the cameras' values and says so. `not_brought`: both sides where they differ, None where they agree or the file authors neither |
| `tests/test_scene_handler.py` | A Z-up centimetre file on a Y-up metre stage, at a new path: the ops `[file's own, rotateX:unitsResolve, scale:unitsResolve]`, the world box tallest along Y at 1/100 of the file's numbers, the answer's fields; with `position`, `rotation=[0, 90, 0]` and `scale=2`: the position in the parent's frame, the turn about the stage's Y, the box twice its real size. With a fake `pxr.PhysicsSchemaTools.units`, as #112's handler tests: a contact offset and a density converted. The same axis and units, and an unauthored file: no op, null fields. Under U2's ancestor: no op of its own, `frame` in the answer. A plain Xform already at the path: the reference added, no op, no value written, `not_brought` set. The same call twice: one turn, one scale, the prim moved, `not_brought` null. A refusal after the turn (an animated root op in a Z-up file): no prim, no override left. A table that raises `KeyError`: no prim, the error naming the conversion. A file that can't be opened: refused, no prim. A relative `usd_path` beside a stage saved in a folder: opened from there (U1). The tests there today pass unchanged |
| `tests/test_robot_handler.py` | `create_robot` under U2's ancestor: no op of its own, `frame` in the answer (Q2) |
| `tests/test_tools.py` | `create_prim`'s answer with `up_axis_turn` and `units_scale` prints `create_robot`'s lines; `frame` prints the frame line and the two lines name the frame; `not_brought` prints its line; an answer without the fields, an older extension's, prints only `Created ...`. `create_robot`'s frame line |
| `tests/test_contract.py` | `test_a_description_says_what_the_tool_now_does` finds `create_prim`'s new sentence |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_07c_a_file_of_the_other_up_axis_and_units_comes_in_as_kit_brings_it` | A box file the test writes, of the up axis the stage hasn't and a `metersPerUnit` 1/100 of the stage's, tall along its own up axis, with a collider's contact offset. `create_prim` at a new path: the answer's turn and scale, the box tallest along the stage's up axis at its real size, the contact offset converted. Where `omni.metrics.assembler.core` imports, Kit's `resolve_hierarchy` after it adds no op and changes no value, as `test_27b` checks the turn. The same file under it: no op of its own, the same size, `frame` naming the outer prim. `create_prim` again at the outer path with a new `position`: the ops unchanged, the box moved. Every prim deleted after |
| `test_27b`, #112's `test_27c` | Again, `create_robot` now on the shared core |

**What neither shows:** Kit 107 (Isaac Sim 5.1) has the same assembler test (K1) and #112's table; no live run on
it is planned. USD Composer's centimetre stages: `test_07c` writes a file of other units relative to the stage
instead. Kit with `conformToXformCommonAPI` on (K4, Risks).

## Docs

- **`docs/TOOLS.md`,** `create_prim`: the `usd_path` row, "brought to the stage's up axis and units as
  `create_robot` brings a robot file"; a paragraph, Up axis and units: the turn, the scale and the converted values
  as `create_robot`'s paragraphs say, pointing there for the detail; the frame a prim lands in; a prim already there
  gets the reference as the file is, and the answer says so; a file that authors none is left as it is; a file that
  can't be opened is an error; `scale` multiplies the file's real size; with an extension of 0.3.0 or older, nothing
  is turned or scaled. `create_robot`: the frame sentence, and #112's "create_prim doesn't yet" taken out.
- **The description,** the sentences in Design.
- **`docs/ARCHITECTURE.md`:** the core list gains `metrics.py` ("a referenced file's up axis and units brought to the
  frame it lands in: the turn, the scale and the physics values, for create_robot and create_prim"), and `robot.py`'s
  entry loses them; the Robot System's `create_robot` bullet points at `core/metrics.py`.
- **`AGENTS.md`:** the `ovmcp/core/` list gains "a referenced file's up axis and units".
- **`CHANGELOG.md`,** under Unreleased, Fixed, and #112's entry loses "`create_prim`'s `usd_path` doesn't yet (#119)":

  ```markdown
  - **`create_prim` brings a `usd_path` file of another up axis or other units to the stage's, as `create_robot`
    does:** a Z-up prop on a Y-up stage lay on its side, and a centimetre asset on a metre stage came in 100 times
    too large, its physics values in the file's units. It is now turned upright and scaled with the ops Kit's
    metrics assembler writes, its physics values and its cameras' distances converted, and the answer says so. A
    file placed inside an asset already turned or scaled, by either tool or by Kit, is measured against that
    asset's frame, as Kit measures it, so it isn't turned or scaled twice. A reference added to a prim already
    there goes on as the file is, and the answer says so. A file that can't be opened is now an error, where it
    made an empty prim. **A call that turned or scaled such a prim itself, with `rotation` or `scale`, now turns or
    scales it twice: drop that.** The fix is in the Kit extension (#119).
  ```

- **Plugin skills, README, `test_project/scenarios.md`:** none name `usd_path`'s units; nothing changes.

## Risks

| Risk | Status |
|---|---|
| Kit's assembler, run on the prim later, turns, scales or converts it a second time | Closed for `create_robot` by #112's P5 and `test_27b`; `create_prim` writes the same ops and values through the same core, and `test_07c` checks it |
| Kit tells a nested prim's frame some other way than by its ancestors' ops (N3, N4), or converts its values against the frame (N1) | Open until the probe runs: where Kit differs, this plan says so and Q2 is asked again |
| `conformToXformCommonAPI` on: Kit writes its turn and scale into a prim's own ops, which `frame_of` doesn't count (K4) | Accepted: off by default; a file placed inside such an asset is measured against the stage, as `create_robot` does today |
| A net ancestor turn that is none of -90, +90 or 0 | Accepted: taken as the stage's axis; only hand-written ops give one |
| A prim already there gets nothing (Q1) | Accepted with Q1's A: the answer says what it left and how to get it |
| A payload inside the file that isn't loaded: its values aren't converted, and loading it later brings them in the file's units | Accepted: Kit loads payloads by default; `docs/TOOLS.md` names it |
| A file with no default prim: the reference brings nothing, and the ops land on an empty prim | Accepted: an empty prim, as today, now with the ops |
| Refusing a file that can't be opened breaks a call that referenced a file to be written later | Accepted with Q3's A: named in CHANGELOG |
| The move from `core/robot.py` | Closed by step 3: no behaviour change, the moved tests pass unchanged |
| What #112 accepted: a nested file of other units, values inside instances, time samples beating a later default, a converted value masking a file change, mimic gearing | As #112's Risks, for `create_prim` too |

## Plan review

None yet: `review-plan` writes each round here.
