---
title: Scale a robot file of other units to the stage, and convert its physics values
issue: "#112"
status: draft
approved_by:
approved_at:
---

# Scale a robot file of other units to the stage, and convert its physics values

`create_robot` loads a robot file whose `metersPerUnit` isn't the stage's at the file's own scale: a robot authored in
metres comes in 100 times too small on a centimetre stage, and the answer says nothing. #105 stood a file of the
other up axis upright with the op Kit's metrics assembler writes, and left the units to this issue (its plan's Q6).

The installed Isaac Sim 6.2 answers the issue's question. Kit's assembler scales a file of other units with
`xformOp:scale:unitsResolve`, and a scale alone leaves most of a robot's physics in the file's units: on a
centimetre stage a metres robot's joint drives are 10,000 times too weak and its inertia 10,000 times too small. Kit
converts those values only through a physics extension of its own, whose table of units ships with the PhysX schema.
This plan recommends doing what Kit does with that extension loaded: the scale op, and every physics value converted
by the same table (Q1). A live probe on Isaac Sim 6.2 compared the two: the conversion this plan proposes gives
Kit's value for every one of the probe robot's 22 values, and Kit's assembler, run on top of it, changes nothing.

## Goal

When this is done, with this release's Kit extension:

- A robot file whose authored `metersPerUnit` differs from the stage's comes in at its real size: `create_robot`
  writes `xformOp:scale:unitsResolve`, the op Kit's metrics assembler writes on a drag and drop, beside #105's turn.
- Its physics values come in the stage's units: masses from a density, inertia, drives, prismatic limits, offsets and
  the rest, converted by the PhysX schema's own table of units, the one Kit's physics rules register (K5, K6). A
  robot of other units behaves as the same robot authored in the stage's units.
- The same for a file whose `kilogramsPerUnit` differs (Q3): its masses and forces converted, nothing scaled.
- The answer says what was done: the two units, the factor, the op's value after, how many values were converted,
  and any left in the file's units (Q5).

Why: an agent that drops a robot of other units on a stage gets a robot of the wrong size today, with no word on why.
A scale alone would give one of the right size that collapses when the simulation plays (the table under The
sources).

| In scope | Out of scope |
|---|---|
| `create_robot`, a file or a library robot | `create_prim`'s `usd_path`, which references a file the same way and gets neither #105's turn nor this scale (Q6) |
| `metersPerUnit`, and `kilogramsPerUnit` (Q3) | A file of other units nested inside the robot's file: its values are converted by the robot file's units (Risks) |
| The answer's line, the description, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md` | Re-converting when the file changes after the robot was added (Q4) |
| A unit-tested core on usd-core, and a live test of the behaviour on Isaac Sim 6.2 | Stages, as `open_scene` opens them: the stage's units are the ones everything else is measured in |

## What the code, the sources and the probe say

### The code, at `f5a27ed`

| Where | What it does |
|---|---|
| `handlers/robot.py:101-129`, `handle_create_robot` | Opens the file's layer (`Sdf.Layer.FindOrOpen`), reads its up axis, defines the prim, adds a plain reference, writes #105's turn (`stand_upright`), then `write_transform`; a refusal removes what the call made. No units are read |
| `core/robot.py:41-78` | `UP_AXIS_OP`, `file_up_axis(layer)` (the authored `upAxis`, else None: #105's Q5), `up_axis_turn`, `stand_upright(prim, degrees)`: a new op through `xform.add_local_op`, before the first inverse op, else last; a held one gets the sum; an animated one is refused |
| `core/xform.py:180-201` | A part's own op is unsuffixed: `set_prim_transform`'s scale never touches a `:unitsResolve` op, and a new own op goes before them (`_is_units`) |
| server `tools/robot.py:53-91` | `_turned_line` prints #105's `up_axis_turn`; the description says a file of another `upAxis` is stood upright |
| `docs/TOOLS.md:591-599` | "Unlike Kit's metrics assembler, it doesn't scale a file whose `metersPerUnit` isn't the stage's: #112" |
| `tests/test_integration.py:32-63`, `:1492-1535` | `test_27` and `test_27b` write robot files that author no `metersPerUnit` (Q2) |

### The sources

Read on disk in Isaac Sim 6.2's install (`isaacsim/extscache/`), and in the UsdPhysics and Omni Physics docs:

| # | What | Where |
|---|---|---|
| K1 | Kit's assembler compares each composed layer's `upAxis`, `metersPerUnit` and `kilogramsPerUnit` with the stage's. It resolves xform ops "on top-level divergent prims" with `xformOp:scale:unitsResolve` (a metres file on a centimetre stage: 100) and `xformOp:rotateX:unitsResolve`, and converts attribute values only for rules registered with it: `resolvedValue = value * (MPU / stageMPU) ^ metersExponent * (KGPU / stageKGPU) ^ kilogramsExponent`, MPU being the units of the layer the value is authored in. With no rules it "only resolves xformOps" | `omni.usd.metrics.assembler-110.1.2`: `docs/README.md:10-15`, `:131`; `core/tests/referenceTests.py:104-125` |
| K2 | By default it writes a resolved value "to the strongest layer that defines each attribute", the referenced file's own layer for a robot's values; `set_resolve_layer` sends them elsewhere | the same `README.md:93` |
| K3 | A drag and drop, in mode Auto, runs `TransformPrimSRTCommand` on the prim, then resolves it into an anonymous layer, `metrics:UnitsAdjust-<md5>.metricsAssembler`, inserted first among the root layer's sublayers and never written to disk. It records the prim in the root layer's `customLayerData["metricsAssembler"]`, so opening the stage again resolves it again, and a change listener resolves it again when it resyncs | `omni.usd.metrics.assembler.ui-110.1.3`: `metricsAssemblerManager.py:344-385`; `tools.py:29-58`, `:92-115`, `:255-330` |
| K4 | Isaac Sim's own `add_reference_to_stage` checks `check_layers` and, when the units differ, adds the reference through Kit's `AddReference` command, so the assembler resolves it; without the assembler's UI it warns "convert the file into right units" | `isaacsim.core.experimental.utils`: `impl/stage.py:491-510`; the deprecated `isaacsim.core.utils`: `stage.py:340-363` |
| K5 | `omni.usd.metrics.assembler.physics` registers a rule for every attribute of `pxr.PhysicsSchemaTools.units_db.usd_attribute_units` with a distance or mass exponent, and for the ones whose units depend on the prim (a limit on a revolute or a prismatic joint, a drive of type force or acceleration) asks `units.get_attribute_unit_exponents(name, prim)` per prim. Its tests: on a centimetre stage of `kilogramsPerUnit` 0.1, a prismatic limit of 1 becomes 100, gravity 9.8 becomes 980 | `omni.usd.metrics.assembler.physics-110.4.4`: `metricsAssemblerPhysics.py:25-90`; `tests/tests.py:57-148` |
| K6 | The table: exponents `(mass, distance, degrees, seconds, radians)` per attribute. `physics:mass` (1, 0), `physics:density` (1, -3), `physics:diagonalInertia` (1, 2), `physics:centerOfMass` (0, 0), an angular force drive's stiffness (1, 2, -1, -2), a linear one's (1, 0, 0, -2), a prismatic limit (0, 1), a revolute one in degrees. Joints' `physics:localPos0` and `localPos1` aren't in it | `omni.usd.schema.physx-110.4.4`: `pxr/PhysicsSchemaTools/units_db.py:861-1198`; `units.py:31-73` |
| K7 | Every Isaac Sim 6.2 app loads the physics rules. Its GUI app names them (`isaacsim.exp.full.kit:137`). Its base app, which `SimulationApp`'s default, `isaacsim.exp.base.python.kit`, builds on, names the assembler's UI (`:125`) and the deprecated `isaacsim.core.utils` (`:24`), which depends on the physics rules: so they come to the base and headless apps only through an extension "deprecated since Isaac Sim 6.0.0". P1 found them on in the session's headless Kit | `isaacsim/apps/`; `extsDeprecated/isaacsim.core.utils/config/extension.toml:16-28`; `isaacsim.simulation_app`'s `simulation_app.py:253-260` |
| K8 | "The joint space relative to each body is a translation and orientation only ... this local joint space is fixed in the prim's local space, which of course CAN be scaled using the prim's own Xform scaling": a joint frame scales with its body. And: "before simulation, all values can be converted using the respective unit conversion metadata", which in Kit is the assembler's job | OpenUSD: `usd_physics_page_front` (Jointed Bodies), `wp_rigid_body_physics` (Units) |
| K9 | "As scale is not supported in most physics engines, the collision shape sizes already contain the scale": a collider scales with its prim | Omni Physics: `dev_guide/schemas/usdphysics` (`UsdPhysicsShapeDesc`) |
| K10 | omni.physx keeps a body's `xformOp:rotateX:unitsResolve` and `xformOp:scale:unitsResolve` in place when it writes the body's pose back | `omni.physx.tests-110.4.4`: `PhysicsRigidBodyAPI.py:163-213` |

So a metres robot on a centimetre stage, with the scale op alone (factor 100):

| Quantity | What PhysX gets | With Kit's physics rules (K6) |
|---|---|---|
| Shapes, joint frames, centre of mass | right: they ride the prim's scale (K8, K9) | unchanged |
| Mass, authored | right: kilograms both sides | unchanged |
| Mass from a density | 10^6 too heavy: kg/m³ read as kg/cm³ over a volume in cm³ | ×10^-6 |
| Diagonal inertia | 10^4 too small: kg·m² read as kg·cm² | ×10^4 |
| Revolute limits, angular targets | right: degrees | unchanged |
| Prismatic limits, linear targets | 100 times too short | ×100 |
| Angular drive stiffness, damping, max force | 10^4 too weak | ×10^4 |
| Linear drive stiffness, damping | right: N/m has no distance in stage terms (K6: (1, 0, 0, -2)) | unchanged |
| Linear drive max force | 100 times too weak | ×100 |
| Contact and rest offsets | 100 times too small | ×100 |
| Gravity | the stage's physics scene, in its own units | not the robot's |

The robot looks right and its arm can't hold itself up. Left at the file's scale, it is a coherent robot 1/100 of
its size under real gravity, the issue's case today.

### usd-core 26.11 (a scratch check, not kept)

| # | What it showed |
|---|---|
| U1 | The probe's robot file, referenced into a centimetre stage, converted as Design proposes with Isaac Sim's own `units.py` and `units_db.py` loaded by path: inertia (0.1, 0.2, 0.3) to (1000, 2000, 3000), density 1000 to 0.001, the hinge's stiffness 1000 to 10^7, the slide's upper limit 0.04 to 4 and its stiffness 500 unchanged, the centre of mass and both joints' `localPos0` unchanged. A contact offset inside an instance can't be written and is left |
| U2 | Writing a converted time sample into the stage's layer hides every sample of the file's: the stronger layer's samples win whole. Written one at a time, a velocity sampled `{0: 0, 10: 0.1}` came out `{0: 0, 10: 0}`. Read all, then write all: `{0: 0, 10: 10}` |
| U3 | The root layers of the ten `ROBOT_ASSETS` robots #105 downloaded, read with `Sdf.Layer`: all author `metersPerUnit = 1` and none `kilogramsPerUnit`. Six compose more files: a `configuration/` sublayer (anymal_c, carter_v1, go1, jetbot, spot, ur10) or references to `Props/` files (anymal_c, carter_v1, go1, panda_instanceable's 12) |

### The probe

`112-probe.py`, in the session's scratchpad's `112/`, run by the session through `112-probe.sh` on its headless Isaac
Sim 6.2 at port 8212 (`SimulationApp`, so `isaacsim.exp.base.python.kit`) with main's extension at `f5a27ed`. Exit
0, an empty stderr; `112-probe.out.txt` beside it. It worked on in-memory stages in USD's stage cache, as the
assembler's own tests do, and resolved into an anonymous layer of each, so neither the open stage nor the robot file
was touched. The robot: a fixed base with a mass, an inertia and a centre of mass, a collider with a contact offset;
an arm with a density and an instanced pad whose collider has a contact offset; a hinge with an angular force drive;
a slide with a linear force drive, a 0.04 limit and a sampled target velocity.

| # | What it asked | What it showed |
|---|---|---|
| P1 | What is on | `omni.usd.metrics.assembler`, its UI and its physics rules on, and `isaacsim.core.utils` (K7); `omni.usd.metrics.assembler.usdgeom` off. `pxr.PhysicsSchemaTools.units` imports, 265 entries. Operation mode 3 (Auto), the change listener on, `conformToXformCommonAPI` off |
| P2 | A metres file on a centimetre stage, `resolve_hierarchy` with the physics rules on | The op `xformOp:scale:unitsResolve` = (100, 100, 100), double, and not in the resolve layer, whose text the probe printed: so in the root layer, which defines the prim. In the resolve layer, as K6's exponents give: inertia ×10^4, density ×10^-6, the hinge's stiffness, damping and max force ×10^4, the slide's limits, target position, sampled target velocity (`{0: 0, 10: 10}`), max force and max joint velocity ×100, the contact offset ×100, the articulation's sleep threshold ×10^4. Also written at their own value: both masses, the slide's stiffness and damping, its lower limit 0. Not written: the centre of mass, both joints' `localPos0`, the hinge's limits, target and max joint velocity (degrees). The pad's contact offset, inside the instance, stays 0.03 from the file. A second resolve changes nothing; the file's layer isn't dirty |
| P3 | A Z-up metres file on a Y-up centimetre stage | `[xformOp:rotateX:unitsResolve -90, xformOp:scale:unitsResolve (100, 100, 100)]`: the turn first, both double |
| P4 | A file that authors no `metersPerUnit` | Kit takes it as in the stage's units: `check_layers` reads it as 1 on a metre stage and 0.01 on a centimetre one, not divergent, and `resolve_hierarchy` writes nothing. Not USD's fallback |
| P5 | Design's conversion (the op in float, the values times the factor in the stage's root layer), then Kit's resolve on top | 13 values converted, the pad's contact offset left as inside an instance. Every one of the 22 values read equals Kit's from P2 (to 1e-4, samples included). Kit's resolve after it adds no op, leaves the op at 100 in float, changes no value, and writes none of the 13 into its layer: only the four it writes at their own value (both masses, the slide's stiffness and damping) |

## Design

Q1's option A, as recommended.

### The core (`core/robot.py`, Kit-free)

| Name | What |
|---|---|
| `UNITS_OP` | `"xformOp:scale:unitsResolve"` |
| `file_units(layer)` | The file's authored `metersPerUnit` and `kilogramsPerUnit`, each None when the root layer doesn't author it (Q2, Q3) |
| `units_factors(file, stage)` | `(distance, mass)`: file over stage for each authored one, 1 for one not authored; None when both are 1 within 1e-9 |
| `scale_to_stage(prim, factor)` | Writes `UNITS_OP` = `(f, f, f)` in double precision, as Kit writes it (P3), through `xform.add_local_op`, which gains a precision argument (float stays its default, so #105's turn is unchanged). The bridge calls it after #105's turn, so the op lands where Kit puts it: after the turn, before the first inverse op, else last (P3; a uniform scale and a turn commute, so the world matrix is the same either way). A root that holds the op already, as a robot Kit resolved and saved, gets it multiplied, as #105's turn gets the sum; an animated one is refused. Gives the op's value after |
| `convert_physics(root, factors, exponents)` | For every prim of `Usd.PrimRange(root)` and each attribute it authors a value for: `exponents(name, prim)` gives `(mass, distance)` or None; the factor is `distance ** d * mass ** m`. Every time sample and the default, when the default is what resolves, are read first, then written times the factor into the edit target (U2). Numbers and `Gf` vectors are converted; a value the factor leaves as it is (0, ±inf) isn't written; any other type is left. Values under the root inside an instance, which USD lets no one override, are left (Q5). Gives the count converted and the paths left |

`exponents` is an argument, so the core never imports NVIDIA's module: the unit tests pass a small table, the bridge
passes the PhysX schema's. Where Kit writes a value the factor leaves as it is (P2's masses), the core writes none:
the value from the file is the same, and an override that changes nothing would hide a later change to the file.

### The bridge (`handlers/robot.py`)

After #105's turn and before `write_transform`, with the layer it already opened:

1. `units_factors(file_units(layer), (UsdGeom.GetStageMetersPerUnit(stage), UsdPhysics.GetStageKilogramsPerUnit(stage)))`.
2. A distance factor: `scale_to_stage(prim, distance)`.
3. Either factor: `convert_physics(prim, factors, _physics_exponents())`. `_physics_exponents` imports
   `pxr.PhysicsSchemaTools.units`, the module Kit's physics rules read (K5), and maps its 5-tuple to `(mass,
   distance)`; a dict (units it can't tell for that prim) or None is None. Where it doesn't import, a Kit app
   without the PhysX schema, nothing is converted and the answer says so.
4. A refusal or a `Tf.ErrorException` removes the prim as today: `RemovePrim` takes the converted values with it,
   since they sit under the prim's path in the same layer.

The answer gains `units_scale`, or `null` when the units agree:

```json
{"meters_per_unit": {"file": 1.0, "stage": 0.01}, "kilograms_per_unit": null, "factor": 100.0,
 "op": 100.0, "op_name": "xformOp:scale:unitsResolve", "converted": 37, "left": [], "table": true}
```

`kilograms_per_unit` is set when it differs (Q3); `factor`, `op` and `op_name` are null when only the mass differs;
`left` holds the first 10 paths left, `left_count` all of them; `table` is false where the PhysX schema's module
doesn't import.

### The server (`tools/robot.py`)

`_scaled_line(units)`, after #105's turned line:

```text
Scaled to the stage's units: the file is in metersPerUnit 1 and the stage 0.01, so xformOp:scale:unitsResolve now
reads 100, and 37 physics values (masses, inertia, drives, limits) were converted to the stage's units, as Kit's
metrics assembler does with its physics rules
```

Then, when they apply: "N values inside instances stay in the file's units, which USD lets no one override: <paths>",
and "This Kit app has no PhysX schema to read units from, so the robot's physics values stay in the file's units".
A mass-only case says "Converted to the stage's units: the file is in kilogramsPerUnit 0.001 and the stage 1 ...".
An older extension sends no field, and nothing is printed.

The description's "A file whose upAxis isn't the stage's is stood upright on it" gains: "and one whose
metersPerUnit isn't is scaled to it, its physics values converted, as Kit's metrics assembler does".

### Alternatives (Q1)

- **B, Kit's assembler:** `resolve_hierarchy` with `set_resolve_layer` on the edit target's layer, where
  `omni.metrics.assembler.core` imports. In Isaac Sim 6.2 it gives the values A gives (P5), in every app (K7, P1).
  But its physics values come only where the physics rules are on, and Isaac Sim's base and headless apps have them
  only through the deprecated `isaacsim.core.utils` (K7): the release that drops it leaves them the scale alone,
  and so would any Kit app without them. It is Kit's C++, testable only live; it also writes the values it leaves
  as they are (P2's masses); and #105's Q4 chose the core's own op for these reasons.
- **C, the file's scale, and the answer says so:** the robot stays a coherent miniature; the agent can't fix it with
  the tools, since `set_prim_transform`'s scale is D.
- **D, the scale alone, the answer warning:** the robot looks right and its drives and inertia are off by 10^4.

## Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | How does `create_robot` take a file of other `metersPerUnit`? | **A.** The scale op and every physics value converted, by the PhysX schema's own table, in the core. **B.** Kit's assembler, where it loads. **C.** The file's scale; the answer names the units and the factor. **D.** The scale alone, the answer warning that physics values stay in the file's units | A: the robot is the right size and behaves as the same robot in the stage's units, in every Kit app with the PhysX schema, tested on usd-core. Its values are Kit's (P5), without depending on the physics rules being on. B gives Kit's values in Isaac Sim 6.2 too, but in its base and headless apps only through a deprecated extension (K7), and D wherever the rules are off; C and D leave a robot that is wrong in size or in physics | |
| Q2 | A file that authors no `metersPerUnit`? | **A.** Take it as in the stage's units and leave it as it is: what Kit's assembler does (P4), and what #105's Q5 does for `upAxis`. **B.** Take USD's fallback, 0.01, which Kit doesn't (P4) | A: Kit's own reading, and a hand-written file, such as `test_27`'s and `test_27b`'s, is in metres far more often than in centimetres: B would shrink it to 1/100 on Isaac Sim's stages. The answer says nothing then, as today | |
| Q3 | A file of other `kilogramsPerUnit`? | **A.** In the same pass: masses, densities, inertia and forces converted by file over stage, nothing scaled; an unauthored one left as it is, as Q2. **B.** `metersPerUnit` only, as the issue names | A: the same table and the same pass, and Kit's assembler compares both (K1). None of Isaac Sim's library robots authors `kilogramsPerUnit` (U3), so it never changes them | |
| Q4 | Where do the converted values go? | **A.** The edit target's layer, as #105's turn: saved with the stage, and a later change to those values in the robot's file no longer shows. **B.** An anonymous layer as Kit's drop (K3): never saved, so a saved and reopened stage loses them unless Kit's assembler, recording the prim in `customLayerData`, resolves it again | A: what the call did stays done, with or without Kit's assembler; B ties the robot to Kit's UI extension | |
| Q5 | Values inside an instance, such as a collider's contact offset in an instanceable robot's meshes, which no layer of the stage can override? | **A.** Leave them, as Kit's assembler does (P2: the pad's contact offset stays the file's), and name them in the answer. **B.** Turn those instances into ordinary prims (`SetInstanceable(False)`) so every value converts. **C.** Refuse the robot | A: Kit leaves them too, and Isaac Sim's instanceable robots keep their bodies, joints and drives outside the instances. B changes the robot's structure for a contact offset | |
| Q6 | `create_prim`'s `usd_path` references a file as `create_robot` does, with neither #105's turn nor this scale | **A.** Out of scope: a new issue for both. **B.** In this change | A: `create_prim` adds any file, and a turn or a scale there needs its own answer line and docs | |
| Q7 | Someone who scaled a robot of other units themselves, with `set_prim_transform(scale=...)`, now gets it scaled twice | **A.** CHANGELOG's Fixed entry says so, in bold, as #105's Q7. **B.** Under Breaking changes | A: the schema doesn't change, and the answer's line names the scale | |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change (`tests/fixtures/mcp-tools.json` stays). The
  route keeps its path and gains an answer field, `units_scale`; `PROTOCOL` stays 1.
- **What users notice:** a robot of other units comes in at its size, with its physics in the stage's units, and the
  answer says so. On Isaac Sim's own stages with its library robots nothing changes: all are in metres (#105's U6).
  Q7 for someone who scaled one themselves.
- **Older extensions:** nothing is scaled; the server prints nothing. `docs/TOOLS.md` says so.
- **Kit apps:** the op is plain USD. The values convert wherever `pxr.PhysicsSchemaTools.units` imports; elsewhere
  the answer says they didn't.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the probe, P1 to P5, and this plan settled on it: Q2's and Q5's rows, the op's order and precision, the second conversion | `112-probe.out.txt` |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | Core: `file_units`, `units_factors`, `scale_to_stage`, `convert_physics` | `tests/test_robot.py` |
| 3 | Bridge: `handle_create_robot`, `_physics_exponents`, the answer's `units_scale` | `tests/test_robot_handler.py` |
| 4 | Server: `_scaled_line`, the description | `tests/test_tools.py`; `tests/test_contract.py` unchanged |
| 5 | Docs (below) | the gate's checks |
| 6 | Live: the tests below, run by the session on Isaac Sim 6.2 headless at 8212, on a Z-up stage and a Y-up one, then both suites whole | no failure beyond `main`'s on the same Kit |
| 7 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fails at `f5a27ed`, where it can.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_robot.py` | `file_units` reads authored units and None for unauthored ones. `units_factors`: metres on centimetres 100, centimetres on metres 0.01, the same None, an unauthored file None (Q2), a mass-only file `(1, f)`. `scale_to_stage`: the op in double, after the turn as P3 has it and before an inverse op, a held op multiplied with its order and precision unchanged, an animated one refused; `add_local_op` without a precision still adds a float op. `convert_physics` with a small table: a distance exponent of 2 multiplies by f², a mass exponent by the mass factor, (0, 0) and attributes not in the table untouched, a value of 0 or inf not written; a sampled value `{0: 0, 10: 0.1}` comes out `{0: 0, 10: 10}` (U2); a default beside samples both converted; a value inside an instance left and listed; a string left |
| `tests/test_robot_handler.py` | With a fake `pxr.PhysicsSchemaTools.units` in `sys.modules` giving NVIDIA's 5-tuples: a metres file on a centimetre stage gets the op at 100, its world box 100 times the file's, its inertia, density and angular drive converted, its centre of mass and joint frames not, and `units_scale` as Design shows; a Z-up metres file on a Y-up centimetre stage gets both ops, the turn first (P3); the probe's robot, written in the test, gives P2's values for each of its 22, the pad's contact offset left and named; the same units or an unauthored file get no op and `null`; without the module, the op and `table: false`; a mass-only file converts its masses with no op; a refusal after the conversion leaves no prim and no override |
| `tests/test_tools.py` | `create_robot`'s answer with `units_scale` prints the line, with the values left and without the table; one without it or with `null` prints none |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_27c_a_robot_file_of_other_units_behaves_as_in_the_stage_s` | Two files the test writes: a fixed-base arm with one hinge, its angular drive holding the arm level against gravity, in metres, and the same arm in centimetres (every length ×100, inertia and the drive ×10^4, the max force ×10^4). On Isaac Sim's metre stage the centimetre one gets the op at 0.01 and the same world box as the metre one; after the same steps of play, its hinge sags as the metre one's does, within 1%. Then, where `omni.metrics.assembler.core` imports, `resolve_hierarchy` on it changes no value and adds no op (P5) |
| `test_27`, `test_27b` | Unchanged, files with no `metersPerUnit`: no op (Q2) |

**What neither shows:** USD Composer, whose stages are in centimetres, isn't on this machine: `test_27c` puts the
file of other units on Isaac Sim's metre stage instead. Kit 107 (Isaac Sim 5.x), whose PhysX schema may lack
`PhysicsSchemaTools.units`, unless the session has it at hand.

## Docs

- **`docs/TOOLS.md`,** `create_robot`: a paragraph, Units, in place of the "#112" sentence: a file whose
  `metersPerUnit` or `kilogramsPerUnit` isn't the stage's is scaled with `xformOp:scale:unitsResolve` and its physics
  values converted by the PhysX schema's table of units, as Kit's assembler does with its physics rules; a file that
  authors none is left as it is, as Kit leaves it; values inside instances stay, as Kit leaves them, and the answer
  names them; a file nested inside the robot's is taken in the robot file's units; with an extension of 0.3.0 or
  older, nothing is scaled.
- **The description,** the sentence in Design.
- **`docs/ARCHITECTURE.md`:** the core list's `robot.py` adds "and the scale and the physics values that bring a file
  of other units to the stage's"; the Robot System's `create_robot` bullet, the same.
- **`CHANGELOG.md`,** under Unreleased, Fixed:

  ```markdown
  - **`create_robot` brings a robot file of other units to the stage's:** a robot in metres on a centimetre stage
    came in 100 times too small. It is now scaled, as Kit scales a dropped file, and its physics values (masses,
    inertia, drives, limits) are converted to the stage's units, so it behaves as the same robot authored in them.
    The answer says when. **A call that scaled the robot itself now scales it twice: drop that scale.** The fix is in
    the Kit extension (#112).
  ```

- **`AGENTS.md`:** nothing: `robot.py` is listed, as "robot files".

## Risks

| Risk | Status |
|---|---|
| Kit's assembler, run on the robot later, converts the values a second time | Closed by P5 on Isaac Sim 6.2: after Design's conversion, Kit's resolve added no op and wrote none of the converted values, since they sit in the stage's own layer, of the stage's units. `test_27c` checks it again on Kit's own stage. Kit's drop path doesn't reach a `create_robot` prim: it resolves only prims a drop or its stage record names (#105's round 1) |
| `pxr.PhysicsSchemaTools.units` missing or changed in another Kit (Kit 107) | Accepted: nothing converts and the answer says so; the op is still written |
| A file nested inside the robot's file, of units of its own: its values are converted by the robot file's units, where Kit uses the units each layer authors, and the stage's for one that authors none (P4) | Accepted: Isaac Sim's robots compose a sublayer or `Props/` files beside a root in metres (U3); `docs/TOOLS.md` names it |
| Values inside instances stay in the file's units (Q5) | Accepted with Q5's A: named in the answer |
| A converted value masks a later change to it in the robot's file (Q4) | Accepted with Q4's A: what Kit's drop avoids by resolving again on every open |
| A large robot's traversal on Kit's main thread | Accepted: only when the units differ, and a read of each authored attribute, about what `get_robot_info` does |
| Float precision: a float attribute times 10^4 | Accepted: Kit's assembler writes the same floats |

## Plan review

None yet: `review-plan` writes it.
