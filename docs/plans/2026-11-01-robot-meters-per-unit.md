---
title: Scale a robot file of other units to the stage, and convert its physics values
issue: "#112"
status: approved
approved_by: serionist
approved_at: 2026-11-01
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
by the same table (Q1), each by the units of the layer it is authored in. A live probe on Isaac Sim 6.2 compared the
two: the conversion this plan proposes gives Kit's value for every one of the probe robot's 22 values, and Kit's
assembler, run on top of it, changes nothing. Where the table contradicts itself, on angular acceleration drives, the
plan departs from it and a live test checks the departure (K11).

## Goal

When this is done, with this release's Kit extension:

- A robot file whose authored `metersPerUnit` differs from the stage's comes in at its real size: `create_robot`
  writes `xformOp:scale:unitsResolve`, the op Kit's metrics assembler writes on a drag and drop, beside #105's turn.
- Its physics values come in the stage's units: masses from a density, inertia, drives, prismatic limits, offsets and
  the rest, converted by the PhysX schema's own table of units, the one Kit's physics rules register (K5, K6), each by
  the units of the layer it is authored in (P1), where Kit takes one layer's for every value under the prim (K1). A
  robot of other units behaves as the same robot authored in the stage's units. An angular acceleration drive's
  gains, which hold no distance, stay as they are (K11).
- Its cameras' `focusDistance` and `clippingRange` come in the stage's units, as Kit's camera rules convert them
  (K12).
- The same for a file whose `kilogramsPerUnit` differs (Q3): its masses and forces converted, nothing scaled.
- The answer says what was done: the two units, the factor, the op's value after, how many values were converted,
  and any left in the file's units (Q5).

Why: an agent that drops a robot of other units on a stage gets a robot of the wrong size today, with no word on why.
A scale alone would give one of the right size that collapses when the simulation plays (the table under The
sources).

| In scope | Out of scope |
|---|---|
| `create_robot`, a file or a library robot | `create_prim`'s `usd_path`, which references a file the same way and gets neither #105's turn nor this scale (Q6: #119) |
| `metersPerUnit`, and `kilogramsPerUnit` (Q3) | A file nested inside the robot's whose units differ: its values are converted by its own units, but its geometry gets no op of its own, as Kit's assembler would give it; and nothing is done for a robot file in the stage's units that holds one (Risks) |
| Physics values, and cameras' `focusDistance` and `clippingRange` | Re-converting when the file changes after the robot was added (Q4) |
| The answer's line, the description, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md` | Stages, as `open_scene` opens them: the stage's units are the ones everything else is measured in |
| A unit-tested core on usd-core, and a live test of the behaviour on Isaac Sim 6.2 | Mimic joints' gearing beyond what the table says (Risks) |

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

Read on disk in Isaac Sim 6.2's install (`isaacsim/extscache/`), in Isaac Sim 5.1's (`D:\isaacsim5.1\extscache\`),
and in the UsdPhysics, Omni Physics and PhysX docs:

| # | What | Where |
|---|---|---|
| K1 | Kit's assembler compares each composed layer's `upAxis`, `metersPerUnit` and `kilogramsPerUnit` with the stage's. It resolves xform ops "on top-level divergent prims" with `xformOp:scale:unitsResolve` (a metres file on a centimetre stage: 100) and `xformOp:rotateX:unitsResolve`, and converts attribute values only for rules registered with it: `resolvedValue = value * (MPU / stageMPU) ^ metersExponent * (KGPU / stageKGPU) ^ kilogramsExponent`. With no rules it "only resolves xformOps". Which layer's MPU: not each value's own. #119's probe (N5) put one prim referencing a centimetre file, then a metre file, on a metre stage: Kit wrote one op of 0.01 and converted the metre file's contact offset by the centimetre file's units too, so it takes one layer's units for every value under the prim it resolves | `omni.usd.metrics.assembler-110.1.2`: `docs/README.md:10-15`, `:131`; `core/tests/referenceTests.py:104-125`; `119-probe.out.txt` N5, in the session's scratchpad's `119/` |
| K2 | By default it writes a resolved value "to the strongest layer that defines each attribute", the referenced file's own layer for a robot's values; `set_resolve_layer` sends them elsewhere | the same `README.md:93` |
| K3 | A drag and drop, in mode Auto, runs `TransformPrimSRTCommand` on the prim, then resolves it into an anonymous layer, `metrics:UnitsAdjust-<md5>.metricsAssembler`, inserted first among the root layer's sublayers and never written to disk. It records the prim in the root layer's `customLayerData["metricsAssembler"]`, so opening the stage again resolves it again, and a change listener resolves it again when it resyncs | `omni.usd.metrics.assembler.ui-110.1.3`: `metricsAssemblerManager.py:344-385`; `tools.py:29-58`, `:92-115`, `:255-330` |
| K4 | Isaac Sim's own `add_reference_to_stage` checks `check_layers` and, when the units differ, adds the reference through Kit's `AddReference` command, so the assembler resolves it; without the assembler's UI it warns "convert the file into right units" | `isaacsim.core.experimental.utils`: `impl/stage.py:491-510`; the deprecated `isaacsim.core.utils`: `stage.py:340-363` |
| K5 | `omni.usd.metrics.assembler.physics` registers a rule for every attribute of `pxr.PhysicsSchemaTools.units_db.usd_attribute_units` with a distance or mass exponent, and for the ones whose units depend on the prim (a limit on a revolute or a prismatic joint, a drive of type force or acceleration) asks `units.get_attribute_unit_exponents(name, prim)` per prim. Its tests: on a centimetre stage of `kilogramsPerUnit` 0.1, a prismatic limit of 1 becomes 100, gravity 9.8 becomes 980 | `omni.usd.metrics.assembler.physics-110.4.4`: `metricsAssemblerPhysics.py:25-90`; `tests/tests.py:57-148` |
| K6 | The table: exponents `(mass, distance, degrees, seconds, radians)` per attribute. `physics:mass` (1, 0), `physics:density` (1, -3), `physics:diagonalInertia` (1, 2), `physics:centerOfMass` (0, 0), an angular force drive's stiffness (1, 2, -1, -2), a linear one's (1, 0, 0, -2), a prismatic limit (0, 1), a revolute one in degrees. Joints' `physics:localPos0` and `localPos1` aren't in it | `omni.usd.schema.physx-110.4.4`: `pxr/PhysicsSchemaTools/units_db.py:861-1198`; `units.py:31-73` |
| K7 | Every Isaac Sim 6.2 app loads the physics rules. Its GUI app names them (`isaacsim.exp.full.kit:137`). Its base app, which `SimulationApp`'s default, `isaacsim.exp.base.python.kit`, builds on, names the assembler's UI (`:125`) and the deprecated `isaacsim.core.utils` (`:24`), which depends on the physics rules: so they come to the base and headless apps only through an extension "deprecated since Isaac Sim 6.0.0". P1 found them on in the session's headless Kit | `isaacsim/apps/`; `extsDeprecated/isaacsim.core.utils/config/extension.toml:16-28`; `isaacsim.simulation_app`'s `simulation_app.py:253-260` |
| K8 | "The joint space relative to each body is a translation and orientation only ... this local joint space is fixed in the prim's local space, which of course CAN be scaled using the prim's own Xform scaling": a joint frame scales with its body. And: "before simulation, all values can be converted using the respective unit conversion metadata", which in Kit is the assembler's job | OpenUSD: `usd_physics_page_front` (Jointed Bodies), `wp_rigid_body_physics` (Units) |
| K9 | "As scale is not supported in most physics engines, the collision shape sizes already contain the scale": a collider scales with its prim | Omni Physics: `dev_guide/schemas/usdphysics` (`UsdPhysicsShapeDesc`) |
| K10 | omni.physx keeps a body's `xformOp:rotateX:unitsResolve` and `xformOp:scale:unitsResolve` in place when it writes the body's pose back | `omni.physx.tests-110.4.4`: `PhysicsRigidBodyAPI.py:163-213` |
| K11 | An acceleration drive "behaves as if the body had unit mass": "the engine compensates for joint inertia each step", so "stiffness = naturalFrequency²". Its gains hold no mass and no distance: (deg/s²)/deg and (deg/s²)/(deg/s). The table's linear acceleration gains say so, (0, 0, 0, -2) and (0, 0, 0, -1); its angular ones keep the force drive's m², (0, 2, -1, -2) and (0, 2, -1, -1), for `drive:angular`, `rotX`, `rotY` and `rotZ` alike. Which variant applies: `units.py` takes Force when the drive's `physics:type` is valid and `force`, else Acceleration | PhysX: `ovphysx/docs/guides/articulation_stability.md` (Acceleration Drives), `simulation_setup/joints.md` (Joint Drive); `units_db.py:1135-1198`; `units.py:64-74` |
| K12 | `omni.usd.metrics.assembler.usdgeom` registers two rules, by attribute name: `focusDistance` and `clippingRange`, distance exponent 1, "in scene units" by UsdGeomCamera; `focalLength` and the apertures, in tenths of a scene unit, are left for the renderer. Isaac Sim 6.2's GUI app loads it (`isaacsim.exp.full.kit:138`); P1 found it off in the headless app | `omni.usd.metrics.assembler.usdgeom-0.1.0`: `metricsAssemblerUsdGeom.py:11-50`; `tests/cameraTests.py:71-125` |
| K13 | Kit 107 (Isaac Sim 5.1) has the same table: `omni.usd.schema.physx-107.3.26`'s `units.py` is 6.2's but for its header, and its `units_db` holds 300 entries to 6.2's 265, the 262 they share all equal. It has the assembler, its UI and the physics rules (`107.3.1`, `107.3.26`), and no camera rules | `D:\isaacsim5.1\extscache\` |

So a metres robot on a centimetre stage, with the scale op alone (factor 100):

| Quantity | What PhysX gets | With Kit's physics rules (K6) |
|---|---|---|
| Shapes, joint frames, centre of mass | right: they ride the prim's scale (K8, K9) | unchanged |
| Mass, authored | right: kilograms both sides | unchanged |
| Mass from a density | 10^6 too heavy: kg/m³ read as kg/cm³ over a volume in cm³ | ×10^-6 |
| Diagonal inertia | 10^4 too small: kg·m² read as kg·cm² | ×10^4 |
| Revolute limits, angular targets | right: degrees | unchanged |
| Prismatic limits, linear targets | 100 times too short | ×100 |
| Angular force drive stiffness, damping, max force | 10^4 too weak | ×10^4 |
| Angular acceleration drive stiffness, damping | right: no distance in them (K11) | ×10^4, 10^4 too stiff |
| Linear drive stiffness, damping | right: N/m has no distance in stage terms (K6: (1, 0, 0, -2)) | unchanged |
| Linear drive max force | 100 times too weak | ×100 |
| Contact and rest offsets | 100 times too small | ×100 |
| A camera's focus distance and clipping range | 100 times too short | ×100, with the camera rules (K12) |
| Gravity | the stage's physics scene, in its own units | not the robot's |

The robot looks right and its arm can't hold itself up. Left at the file's scale, it is a coherent robot 1/100 of
its size under real gravity, the issue's case today.

### usd-core 26.11 (scratch checks, not kept)

| # | What it showed |
|---|---|
| U1 | The probe's robot file, referenced into a centimetre stage, converted as Design proposes with Isaac Sim's own `units.py` and `units_db.py` loaded by path: inertia (0.1, 0.2, 0.3) to (1000, 2000, 3000), density 1000 to 0.001, the hinge's stiffness 1000 to 10^7, the slide's upper limit 0.04 to 4 and its stiffness 500 unchanged, the centre of mass and both joints' `localPos0` unchanged. A contact offset inside an instance can't be written and is left |
| U2 | Writing a converted time sample into the stage's layer hides every sample of the file's: the stronger layer's samples win whole. Written one at a time, a velocity sampled `{0: 0, 10: 0.1}` came out `{0: 0, 10: 0}`. Read all, then write all: `{0: 0, 10: 10}` |
| U3 | The root layers of the ten `ROBOT_ASSETS` robots #105 downloaded, read with `Sdf.Layer`: all author `metersPerUnit = 1` and none `kilogramsPerUnit`. Six compose more files: a `configuration/` sublayer (anymal_c, carter_v1, go1, jetbot, spot, ur10) or references to `Props/` files (anymal_c, carter_v1, go1, panda_instanceable's 12) |
| U4 | Where a value comes from: `attr.GetResolveInfo(t).GetNode()` is the node it resolved in, and `node.layerStack` holds its layers and its root (`identifier.rootLayer`): a value in a robot file's sublayer gives the robot file as its root, one in a file the robot references gives that file. `GetResolveInfo` at default time reports the default's source, with no arguments the samples', and the two can differ; a source of None has no node. `kilogramsPerUnit` reads back from a layer's root with `HasInfo` |
| U5 | A stronger layer's default over a weaker layer's samples: `GetTimeSamples()` is empty and every time reads the default, so the samples are converted only where they resolve |

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
| `Units`, `Factors`, `Exponents` | Named tuples: `Units(meters, kilograms)`, a layer's `metersPerUnit` and `kilogramsPerUnit`, each None where it authors none; `Factors(distance, mass)`; `Exponents(mass, distance)`, the first two of the table's five |
| `layer_units(layer)` | What the layer's root authors (Q2, Q3): the robot file's units are its root layer's |
| `units_factors(file, stage)` | `Factors`, file over stage for each one the file authors, 1 for one it doesn't; None when both are 1 within 1e-9 |
| `scale_to_stage(prim, factor)` | Writes `UNITS_OP` = `(f, f, f)` in double precision, as Kit writes it (P3), through `xform.add_local_op`, which gains a precision argument (float stays its default, so #105's turn is unchanged). The bridge calls it after #105's turn, so the op lands where Kit puts it: after the turn, before the first inverse op, else last (P3; a uniform scale and a turn commute, so the world matrix is the same either way). A root that holds the op already, as a robot Kit resolved and saved, gets it multiplied by the file's factor, as #105's turn gets the sum; an animated one is refused. Gives the op's three values after |
| `unit_exponents(name, prim, table)` | A value's `Exponents`: the core's own two rules first, then `table(name, prim)`. A `focusDistance` or a `clippingRange`, (0, 1), as Kit's camera rules (K12). An angular drive's stiffness or damping (`drive:angular`, `rotX`, `rotY`, `rotZ`) whose drive isn't of type force, (0, 0), where the table says (0, 2) (K11). None where neither says |
| `convert_units(root, file, stage, table)` | For every prim of `Usd.PrimRange(root)` and each attribute it authors a value for, with exponents other than (0, 0): the default, when the default is what resolves at default time, and every time sample, when samples are what resolve at other times (U4, U5), written times its factor into the edit target. Every value of the robot is read before any is written (U2; review E2: a value written under the robot shows through an inherits or specializes arc to another of its prims), and a default written takes the samples beside it, changed or not, since it would beat them at every time (review E1). Each value's units are those its own layer authors, else those of its layer stack's root, else the robot file's (P1, U4), and its factor is `(meters / stage meters) ** distance * (kilograms / stage kilograms) ** mass`. Numbers and `Gf` vectors are converted; a value the factor leaves as it is (a factor of 1, a value of 0 or ±inf) isn't written; any other type is left. Values under the root inside an instance, which USD lets no one override, and values from value clips or splines are left (Q5). Gives the count converted and the paths left |

`table` is an argument, so the core never imports NVIDIA's module: the unit tests pass a small table, the bridge
passes the PhysX schema's. Where Kit writes a value the factor leaves as it is (P2's masses), the core writes none:
the value from the file is the same, and an override that changes nothing would hide a later change to the file.

The units of each value's own layer, not the robot file's (P1): a robot Kit dropped on a centimetre stage and saved
holds the op at 100 and its values in the metre file it references, since Kit never saves what it converted (K3). Put
on a metre stage, its op becomes 1, and its values, in a layer of the stage's units, stay as they are. A sublayer that
authors no units, such as a robot's `configuration/` file (U3), takes its file's; a referenced file that authors none
takes the robot file's, the likelier guess for a file shipped with the robot than the stage's, which Kit takes. Kit's
assembler isn't the model here: it takes one layer's units for every value under the prim (K1), and would convert
the saved robot's metre values by the centimetre file's.

An angular acceleration drive departs from the table (K11): with the table, a metre robot's acceleration drives would
be 10^4 times too stiff on a centimetre stage, where its force drives are right. `test_27c` checks the departure
live: if the twin on an acceleration drive sags differently on the centimetre stage, the table was right and the rule
goes.

### The bridge (`handlers/robot.py`)

After #105's turn and before `write_transform`, with the layer it already opened:

1. `factors = units_factors(layer_units(layer), stage_units)`, the stage's being
   `Units(UsdGeom.GetStageMetersPerUnit(stage), UsdPhysics.GetStageKilogramsPerUnit(stage))`.
2. A distance factor: `scale_to_stage(prim, factors.distance)`.
3. Either factor: `convert_units(prim, file_units, stage_units, table)`, `table` being `_physics_exponents()`. It
   imports `pxr.PhysicsSchemaTools.units`, the module Kit's physics rules read (K5), once per load of the handlers,
   and maps its 5-tuple to `Exponents`; a dict (units it can't tell for that prim) or None is None. Where it doesn't
   import, a Kit app without the PhysX schema, the table gives None for every name: only the cameras' two values
   convert, and the answer says the physics values didn't.
4. Any exception from the turn to the placing removes the prim, as a refusal does today: `RemovePrim` takes the
   converted values with it, since they sit under the prim's path in the same layer. A `ValueError` or a
   `Tf.ErrorException` keeps today's error; any other names the step: "Converting the robot's values to the stage's
   units failed: KeyError: ... The robot was not added".

The answer gains `units_scale`, or `null` when the units agree:

```json
{"meters_per_unit": {"file": 1.0, "stage": 0.01}, "kilograms_per_unit": null, "factor": 100.0,
 "op": [100.0, 100.0, 100.0], "op_name": "xformOp:scale:unitsResolve", "converted": 37, "left": [],
 "left_count": 0, "table": true}
```

`kilograms_per_unit` is set when it differs (Q3); `factor`, `op` and `op_name` are null when only the mass differs;
`op` is the op's three values after, which differ from the factor's when the file's root held the op; `left` holds the
first 10 paths left, `left_count` all of them; `table` is false where the PhysX schema's module doesn't import.

### The server (`tools/robot.py`)

`_scaled_line(units)`, after #105's turned line:

```text
Scaled to the stage's units: the file's metersPerUnit is 1 and the stage's 0.01, so a factor of 100 went into
xformOp:scale:unitsResolve, which now reads 100; 37 values (masses, inertia, drives, limits, camera distances) were
converted to the stage's units, as Kit's metrics assembler converts them with its physics rules
```

A root that held the op: "so a factor of 0.01 was multiplied into xformOp:scale:unitsResolve, which now reads 1",
the factor and the op named both, as #105's turned line names the turn and the op. Then, when they apply: "N values
stay in the file's units: inside instances, which USD lets no one override, animated by value clips or splines, or of
a type that doesn't multiply: <paths>", and "This Kit app has no PhysX schema to read units from, so the robot's
physics values stay in the file's units", where the first line names only camera distances and Kit's camera rules. A
mass-only case says "Converted to the stage's units: the file's kilogramsPerUnit is 0.001 and the stage's 1; ...". An
older extension sends no field, and nothing is printed.

The description gains a sentence after "A file that authors no upAxis is left as it is.": "A file whose
metersPerUnit or kilogramsPerUnit isn't the stage's is brought to the stage's units, as Kit's metrics assembler
brings a dropped file with its physics rules: scaled, its physics values converted, and the answer says so; one that
authors neither is left as it is."

### Alternatives (Q1)

- **B, Kit's assembler:** `resolve_hierarchy` with `set_resolve_layer` on the edit target's layer, where
  `omni.metrics.assembler.core` imports. In Isaac Sim 6.2 it gives the values A gives (P5), in every app (K7, P1).
  But its physics values come only where the physics rules are on, and Isaac Sim's base and headless apps have them
  only through the deprecated `isaacsim.core.utils` (K7): the release that drops it leaves them the scale alone,
  and so would any Kit app without them. It is Kit's C++, testable only live; it also writes the values it leaves
  as they are (P2's masses), converts angular acceleration gains by the table (K11), and #105's Q4 chose the core's
  own op for these reasons.
- **C, the file's scale, and the answer says so:** the robot stays a coherent miniature; the agent can't fix it with
  the tools, since `set_prim_transform`'s scale is D.
- **D, the scale alone, the answer warning:** the robot looks right and its drives and inertia are off by 10^4.

## Decisions for the maintainer

| Q | Question | Options | Recommendation | Answer |
|---|---|---|---|---|
| Q1 | How does `create_robot` take a file of other `metersPerUnit`? | **A.** The scale op and every physics value converted, by the PhysX schema's own table, in the core. **B.** Kit's assembler, where it loads. **C.** The file's scale; the answer names the units and the factor. **D.** The scale alone, the answer warning that physics values stay in the file's units | A: the robot is the right size and behaves as the same robot in the stage's units, in every Kit app with the PhysX schema, tested on usd-core. Its values are Kit's (P5), without depending on the physics rules being on. B gives Kit's values in Isaac Sim 6.2 too, but in its base and headless apps only through a deprecated extension (K7), and D wherever the rules are off; C and D leave a robot that is wrong in size or in physics | A, as recommended (serionist, 2026-11-01) |
| Q2 | A file that authors no `metersPerUnit`? | **A.** Take it as in the stage's units and leave it as it is: what Kit's assembler does (P4), and what #105's Q5 does for `upAxis`. **B.** Take USD's fallback, 0.01, which Kit doesn't (P4) | A: Kit's own reading, and a hand-written file, such as `test_27`'s and `test_27b`'s, is in metres far more often than in centimetres: B would shrink it to 1/100 on Isaac Sim's stages. The answer says nothing then, as today | A, as recommended (serionist, 2026-11-01) |
| Q3 | A file of other `kilogramsPerUnit`? | **A.** In the same pass: masses, densities, inertia and forces converted by file over stage, nothing scaled; an unauthored one left as it is, as Q2. **B.** `metersPerUnit` only, as the issue names | A: the same table and the same pass, and Kit's assembler compares both (K1). None of Isaac Sim's library robots authors `kilogramsPerUnit` (U3), so it never changes them | A, as recommended (serionist, 2026-11-01) |
| Q4 | Where do the converted values go? | **A.** The edit target's layer, as #105's turn: saved with the stage, and a later change to those values in the robot's file no longer shows. **B.** An anonymous layer as Kit's drop (K3): never saved, so a saved and reopened stage loses them unless Kit's assembler, recording the prim in `customLayerData`, resolves it again | A: what the call did stays done, with or without Kit's assembler; B ties the robot to Kit's UI extension | A, as recommended (serionist, 2026-11-01) |
| Q5 | Values inside an instance, such as a collider's contact offset in an instanceable robot's meshes, which no layer of the stage can override? | **A.** Leave them, as Kit's assembler does (P2: the pad's contact offset stays the file's), and name them in the answer. **B.** Turn those instances into ordinary prims (`SetInstanceable(False)`) so every value converts. **C.** Refuse the robot | A: Kit leaves them too, and Isaac Sim's instanceable robots keep their bodies, joints and drives outside the instances. B changes the robot's structure for a contact offset | A, as recommended (serionist, 2026-11-01) |
| Q6 | `create_prim`'s `usd_path` references a file as `create_robot` does, with neither #105's turn nor this scale | **A.** Out of scope: a new issue for both. **B.** In this change | A: `create_prim` adds any file, and a turn or a scale there needs its own answer line and docs | A: #119, "create_prim's usd_path ignores the file's upAxis and metersPerUnit, as create_robot did" (serionist, 2026-11-01) |
| Q7 | Someone who scaled a robot of other units themselves, with `set_prim_transform(scale=...)`, now gets it scaled twice | **A.** CHANGELOG's Fixed entry says so, in bold, as #105's Q7. **B.** Under Breaking changes | A: the schema doesn't change, and the answer's line names the scale | A, as recommended (serionist, 2026-11-01) |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change (`tests/fixtures/mcp-tools.json` stays). The
  route keeps its path and gains an answer field, `units_scale`; `PROTOCOL` stays 1.
- **What users notice:** a robot of other units comes in at its size, with its physics in the stage's units, and the
  answer says so. On Isaac Sim's own stages with its library robots nothing changes: all are in metres (#105's U6).
  Q7 for someone who scaled one themselves.
- **Older extensions:** nothing is scaled; the server prints nothing. `docs/TOOLS.md` says so.
- **Kit apps:** the op is plain USD. The values convert wherever `pxr.PhysicsSchemaTools.units` imports, Kit 107 among
  them (K13); elsewhere the answer says they didn't.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the probe, P1 to P5, and this plan settled on it: Q2's and Q5's rows, the op's order and precision, the second conversion | `112-probe.out.txt` |
| 1 | This plan, the branch's first commit; review round 1 and the maintainer's answers | `review-plan`, then the maintainer |
| 2 | Core: `Units`, `Factors`, `Exponents`, `layer_units`, `units_factors`, `scale_to_stage`, `unit_exponents`, `convert_units`; `add_local_op`'s precision | `tests/test_robot.py` |
| 3 | Bridge: `handle_create_robot`, `_physics_exponents`, the answer's `units_scale`, the cleanup on any exception | `tests/test_robot_handler.py` |
| 4 | Server: `_scaled_line`, the description | `tests/test_tools.py`; `tests/test_contract.py`'s description check; the golden file unchanged |
| 5 | Docs (below) | the gate's checks |
| 6 | Live: the tests below, run by the session on Isaac Sim 6.2 headless at 8212, on a Z-up stage and a Y-up one, then both suites whole | no failure beyond `main`'s on the same Kit |
| 7 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fails at `f5a27ed`, where it can.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_robot.py` | `layer_units` reads authored units and None for unauthored ones. `units_factors`: metres on centimetres 100, centimetres on metres 0.01, the same None, an unauthored file None (Q2), a mass-only file `(1, f)`, both off 1. `scale_to_stage`: the op in double, after the turn as P3 has it and before an inverse op, a held op multiplied with its order and precision unchanged, an animated one refused; `add_local_op` without a precision still adds a float op. `unit_exponents`: a camera's two values (0, 1); an angular drive's stiffness and damping (0, 0) on an acceleration drive and the table's on a force one; a linear drive's the table's. `convert_units` with a small table: a distance exponent of 2 multiplies by f², a mass exponent by the mass factor, both factors off 1 with density's (1, -3), (0, 0) and attributes not in the table untouched, a value of 0 or inf not written; a sampled value `{0: 0, 10: 0.1}` comes out `{0: 0, 10: 10}` (U2); a default and samples from two layers of their own units, each by its own; P1's saved robot: a centimetre file holding a reference to a metre file, on a metre stage, leaves the metre file's values; a sublayer that authors no units takes its file's, a referenced file that authors none the robot file's; a value inside an instance left and listed; a string left |
| `tests/test_robot_handler.py` | With a fake `pxr.PhysicsSchemaTools.units` in `sys.modules` giving NVIDIA's 5-tuples: a metres file on a centimetre stage gets the op at 100, its world box 100 times the file's, its inertia, density and angular drive converted, its centre of mass and joint frames not, and `units_scale` as Design shows; a Z-up metres file on a Y-up centimetre stage gets both ops, the turn first (P3); the probe's robot, written in the test, gives P2's values for each of its 22, the pad's contact offset left and named; a camera's two distances converted; the same units or an unauthored file get no op and `null`; without the module, the op, the cameras and `table: false`; a mass-only file converts its masses with no op; a file whose root holds the op gets it multiplied, the answer naming factor and op; a refusal after the conversion, and any other exception during it, leaves no prim and no override, the error naming the step |
| `tests/test_tools.py` | `create_robot`'s answer with `units_scale` prints the line, with a held op, with the values left and without the table, and the mass-only line; one without it or with `null` prints none |
| `tests/test_contract.py` | `test_a_description_says_what_the_tool_now_does` finds the description's new sentence |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_27c_a_robot_file_of_other_units_behaves_as_in_the_stage_s` | One robot file the test writes, in metres, Z-up: a base fixed to the world at its origin, two arms along X on hinges about Y, held near level against gravity: one on an angular force drive, its mass from a density over its collider; its twin on an angular acceleration drive, its mass and inertia authored. Two stages the test writes and opens, as `test_31` opens its copy, Z-up, each with a physics scene of earth gravity in its units: one in metres, one in centimetres. On each, `create_robot` the file, play to 3 s and to 4 s of simulation, and read both hinges from `get_joint_states`: settled, they agree within 0.2%. On the centimetre stage the answer gives the op at 100 and the force arm's world box is 100 times the metre stage's. Each arm's sag angle, unitless, matches across the stages within 2%, and is more than 0.02 rad. Then Kit's assembler, where it imports, resolved into an anonymous layer on the centimetre stage, adds no op and changes none of the values the call converted (P5); what it makes of the acceleration drive's stiffness, which its table converts, is printed. With the scale alone the force arm's drive would be 10^4 times too weak; with the table's acceleration entry the twin 10^4 times too stiff. The suite's stage comes back from its saved copy after |
| `test_27`, `test_27b` | Unchanged, files with no `metersPerUnit`: no op (Q2) |

**What neither shows:** USD Composer, whose stages are in centimetres, isn't on this machine: `test_27c` writes a
centimetre stage instead. Kit 107 (Isaac Sim 5.1) has the same table and the physics rules (K13), so the conversion is
the same there; no live run on it is planned. Its Kit has no camera rules, so a camera dropped there keeps its
distances, where `create_robot` converts them. Mimic joints' gearing (Risks).

## Docs

- **`docs/TOOLS.md`,** `create_robot`: a paragraph, Units, in place of the "#112" sentence: a file whose
  `metersPerUnit` or `kilogramsPerUnit` isn't the stage's is scaled with `xformOp:scale:unitsResolve` and its physics
  values converted by the PhysX schema's table of units, as Kit's assembler does with its physics rules, each by the
  units of the layer it is authored in; its cameras' focus distance and clipping range too, as Kit's camera rules
  do; an angular acceleration drive's gains stay as they are; a file that authors none is left as it is, as Kit
  leaves it; values inside instances stay, as Kit leaves them, and the answer names them; a file nested inside the
  robot's gets no op of its own; a drive target animated in the file then wins over a later `set_joint_targets`
  (P3); with an extension of 0.3.0 or older, nothing is scaled.
- **The description,** the sentence in Design.
- **`docs/ARCHITECTURE.md`:** the core list's `robot.py` adds "and the scale and the physics values that bring a file
  of other units to the stage's"; the Robot System's `create_robot` bullet, the same.
- **`CHANGELOG.md`,** under Unreleased, Fixed:

  ```markdown
  - **`create_robot` brings a robot file of other units to the stage's:** a robot in metres on a centimetre stage
    came in 100 times too small. It is now scaled, as Kit scales a dropped file, and its physics values (masses,
    inertia, drives, limits) and its cameras' focus distance and clipping range are converted to the stage's units,
    so it behaves as the same robot authored in them. The answer says when. **A call that scaled the robot itself
    now scales it twice: drop that scale.** `create_prim`'s `usd_path` doesn't yet (#119). The fix is in the Kit
    extension: run `uvx omniverse-mcp extension install`, then restart Kit (#112).
  ```

- **`AGENTS.md`:** nothing: `robot.py` is listed, as "robot files".

## Risks

| Risk | Status |
|---|---|
| Kit's assembler, run on the robot later, converts the values a second time | Closed by P5 on Isaac Sim 6.2: after Design's conversion, Kit's resolve added no op and wrote none of the converted values, since they sit in the stage's own layer, of the stage's units. `test_27c` checks it again on a stage Kit opened. Kit's drop path doesn't reach a `create_robot` prim: it resolves only prims a drop or its stage record names (#105's round 1). Accepted: an angular acceleration drive's gains, left in the file's layer, are what Kit's resolve, run by hand, would still convert by its table (K11); `test_27c` prints what it makes of them |
| `pxr.PhysicsSchemaTools.units` missing or changed in another Kit | Accepted: missing, nothing but the cameras converts and the answer says so; changed so that a call raises, the robot isn't added and the error names the step. Kit 107's is the same (K13) |
| A file nested inside the robot's, of units of its own | Accepted: its values are converted by its own units (P1), but its geometry gets no op of its own, and a robot file in the stage's units isn't walked at all, so a nested file of other units there stays as it is. Isaac Sim's robots compose a sublayer or `Props/` files beside a root in metres (U3); `docs/TOOLS.md` names it |
| Angular acceleration gains: the plan departs from the table, which Kit's physics rules follow (K11) | Open until `test_27c` runs: its twin sags as on the metre stage, or the table was right and the rule goes |
| Mimic joints' gearing: the table gives `physxMimicJoint:rot*:gearing` (0, 1, -1) whatever the joints, where the same file's schema entry gives that only from an angular joint to a linear one, (0, -1) the other way and (0, 0) otherwise, so a mimic between two joints of one kind would be geared ×100 on a centimetre stage | Accepted, unverified: no test or library robot of other units has one; converted by the table, as Kit converts it |
| Converted time samples, written into the edit target, win over a default written there later: `set_joint_targets` writes a default `targetPosition`, which the layer's own samples beat at every time, where before its default beat the file's samples. Kit's drop writes into a weaker sublayer and avoids it | Accepted: needs a drive target animated in a file of other units; `docs/TOOLS.md` names it |
| Values inside instances stay in the file's units (Q5) | Accepted with Q5's A: named in the answer |
| A converted value masks a later change to it in the robot's file (Q4) | Accepted with Q4's A: what Kit's drop avoids by resolving again on every open |
| A large robot's traversal on Kit's main thread | Accepted: only when the units differ, and a read of each authored attribute, about what `get_robot_info` does |
| Float precision: a float attribute times 10^4 | Accepted: Kit's assembler writes the same floats |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, read only, 2026-11-01, on `5eb5cb9`, with four usd-core scripts of its own
(`review-nested.py`, `review-drives.py`, `review-samples.py`, `review-types.py`, in the session's scratchpad's
`112/`). **Verdict:** approved: no blocker or major, four minors; no further round. **Now:** P1 to P4 fixed and
improvements 1 to 7 taken, in the commit after `5eb5cb9`. The maintainer answered Q1 to Q7 after it: all A.

Checked and holding: K1, K2, K5, K6, K7 and K10 match the installed sources; P1 to P5 read the probe's output right;
the writing rules hold.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | The held-op case the plan names, "a robot Kit resolved and saved", comes out the right size with the wrong physics: Kit never saves the values it converted (K3), so they sit in the nested file's layer, in that file's units. A Composer centimetre file whose default prim is a dropped metre robot holding the op at 100, put on a metre stage: the op becomes 1, right, but stiffness and inertia are multiplied by 1e-4 and the robot collapses, while the answer says they were converted as Kit does (`review-nested.py`: the strongest opinion is in the metre file) | fixed: each value's units are those its own layer authors, else its layer stack root's, else the robot file's (U4), which Kit's assembler doesn't do: it takes one layer's for the whole prim (K1, corrected after #119's probe); the op keeps the file's factor, and the answer names the factor and the op when they differ (improvement 3; Design, Tests) |
| P2 | minor | The plan takes NVIDIA's table as physics truth; P5 shows only that the plan equals Kit, which reads the same table, and `test_27c` checked one force drive. Two kinds of entry contradict the table's others: an angular acceleration drive's stiffness (0, 2, -1, -2) and damping (0, 2, -1, -1) keep m², where the linear acceleration entries keep only time; and mimic gearing is (0, 1, -1) whatever the joints. A centimetre robot with angular acceleration drives on a metre stage gets its stiffness ×1e-4 and falls, while the answer says converted. Library robots author force or no type (`review-drives.py`) | fixed: `test_27c` is one metre file on a metre stage and a centimetre stage it writes, a hinge on a force drive, its twin on an acceleration drive and one link's mass from a density, the sag angles compared within 2%; a centimetre twin built with NVIDIA's table would check the table against itself. Angular acceleration gains are taken as (0, 0) (K11), which the twin checks live; mimic gearing is in Risks, unverified |
| P3 | minor | Converted time samples written into the edit target hide any default written there later: `set_joint_targets` writes a default `targetPosition` into that layer, and the layer's own samples win at every time; before, its default beat the file's samples. Kit's anonymous sublayer is weaker than the root, so Kit's drop avoids it. Rare: needs an animated drive target in a file of other units (`review-samples.py`: left in the file, t=5 reads the default 42; converted into the root, t=5 reads the sample 5) | fixed: named in Risks and in `docs/TOOLS.md` |
| P4 | minor | Isaac Sim 6.2's GUI app also converts cameras' `focusDistance` and `clippingRange` (`omni.usd.metrics.assembler.usdgeom`, `isaacsim.exp.full.kit:138`); P1 found it off only in the headless app. A centimetre robot's camera on a metre stage keeps USD's fallback near plane of 1, so a capture through it loses everything within 1 m | fixed: both converted with a distance exponent of 1, authored values only, as Kit's camera rules do (K12; Design, Tests, Docs) |

**Refuted:**

- Degrees left alone: a revolute limit is (0, 0, 1), factor 1; P2 shows the hinge untouched.
- U2 reads everything first, and `GetResolveInfo(Default)` reports Default when a default sits beside samples.
- "Any other type is left" dropping values: all 176 of Isaac Sim 6.2's attributes with units are a float, a double or
  a 3-vector (`review-types.py`).
- The refusal's cleanup: `RemovePrim(made)` takes the overrides and samples under the prim in the edit target.
- `position` and `rotation`: the handler writes the position into the unsuffixed translate, outside the units ops.
- The tool contract: `golden.py` strips descriptions and titles; schema and annotations unchanged; no one-way door.
- The general nested-file case: deferred openly; P1 covers only the held-op case the plan names.
- Kit converting a second time: P5's resolve layer holds none of the 13 converted values.
- The main thread: synchronous USD in the handler, no executor.
- `test_27c` a real check: with the scale alone the centimetre arm's drive is 10^4 too stiff, its sag about 1e-4 of
  the metre arm's; a wrong exponent fails it too.
- The `kilogramsPerUnit` arithmetic: Kit's own test changes the mass factor (`tests.py:133-144`).

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 to Q7 | Decisions for the maintainer | The reviewer agrees with each: Q1 A, with P1's per-layer rule and P2's live check (B rests on a deprecated extension, K7); Q2 A; Q3 A; Q4 A, with P3 named; Q5 A; Q6 A, the follow-up issue filed; Q7 A | All A, as recommended; Q6's issue is #119 (serionist, 2026-11-01) |

**Improvements:**

1. Kit 107 is at hand: `D:\isaacsim5.1` has `omni.usd.schema.physx-107.3.26`, whose `units.py` holds the same
   function and whose robot rows match; correct "What neither shows", and offer `test_27c` there: taken, as K13 and
   "What neither shows"; no 5.1 run is planned.
2. Wider cleanup: `_physics_exponents` checks the module once, and the handler removes the robot on any exception
   during the conversion, where the design caught only a failed import and today's `ValueError` and
   `Tf.ErrorException`: taken (Design, the bridge, step 4).
3. When a held op makes the factor and the op differ, the answer names both, as #105's P7 did for the turn: taken,
   with P1.
4. The description's new sentence in `test_contract.py`'s `test_a_description_says_what_the_tool_now_does`, as
   #105's F2: taken.
5. A core test with both factors off 1 and a negative exponent (density): taken.
6. `test_27c` gives one link its mass by density, so PhysX's mass over a scaled collider is checked live (factor
   10^-6): taken, with P2.
7. Named fields: the exponents as `(mass, distance)`, the factors as `(distance, mass)`: taken, `Exponents`,
   `Factors` and `Units`.
