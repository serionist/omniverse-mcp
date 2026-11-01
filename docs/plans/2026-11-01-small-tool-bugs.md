---
title: Fix the small tool bugs the first AI scenario runs found
issue: "#105"
status: draft
approved_by:
approved_at:
---

# Fix the small tool bugs the first AI scenario runs found

#105 lists six things the first AI scenario runs (#102) saw on Isaac Sim 6.2. A live probe ran each of them before
any code, on the session's headless Isaac Sim 6.2 at port 8212 with main's 0.3.0 extension. Five are real bugs, in
four tools. The sixth, the log search, is the scenario's mistake. A seventh, R7, came from #104's code review (PR
#108): `set_physics_properties` given one of friction and restitution sets the other to USD's 0. A second probe
confirmed it, and found it wider: a physics material the body had before loses all its values. The maintainer added
an eighth, R8: `get_sim_state` names the Kit app and its version, so a bug report (#109) needs no Help > About. This
plan fixes the six real ones, adds R8, on the server and in the Kit extension, and corrects five scenarios' Verify
lines.

## Goal

When this is done, with this release's Kit extension:

| Row | Scenario | Tool | Real? | True when done | Shown by |
|---|---|---|---|---|---|
| R1 | 20.6 | `compare_prims` | yes | From A's 0 faces, the faces delta has no percentage, where it said `+0%`. Each delta has its own sign, where a vertex drop beside a face rise read `+-5` | `test_tools.py` |
| R2 | 2.2 | `get_prim_properties` | yes | `rot` is the world rotation with scale and shear taken out: 2.2's 45° turn at scale 0.5 reads `0.9239, 0, 0.3827, 0`, where it read 84°. Recordings' `state.txt` and `get_scene_tree`'s file give the same `rot` | `test_formatter.py`; live `test_02_02`, `test_08c` |
| R3 | 26.2 | `capture_viewport` | yes | A prim whose outline doesn't reach the image gets no box, where one beside the view got a box at the frame's edge. A box is the outline's part on the image | `test_bounds.py`; live `test_12i`, `test_12g`, `test_26_02` |
| R4 | 23.6 | `capture_viewport`, `inspect_prim` (Q2) | yes | Lighting that leaves the scene unlit, mode `off` or `stage` with no scene lights, gives a warning even when the grid keeps the image from being all black (Q1) | `test_tools_camera.py`, `test_camera_handler.py`; live `test_12j`, `test_23_06` |
| R5 | 24.6 | `get_logs` | no | Expected behaviour. A script's exception, `print` and stderr come back in `execute_script`'s answer and never reach Kit's log; `carb.log_*` calls do. #103 rewrote 24.6 to say so (`a65189f`); `get_logs`' description and `docs/TOOLS.md` say it too (Q3) | live `test_24_06` |
| R6 | 10.1 | `create_robot` | yes | A robot whose file authors another up axis than the stage's stands upright on it, as Kit stands a dropped file. On a Y-up stage that is every robot in Isaac Sim's library, all Z-up. The answer says when it turned one (Q4 to Q7) | `test_robot.py`, `test_robot_handler.py`, `test_tools.py`; live `test_27b`, `test_10_01`, `test_15_16` |
| R7 | none; #108's review | `set_physics_properties` | yes | The material the call binds holds friction and restitution both: the values given, and for one left out, the value the body had, from the physics material bound before or PhysX's default, where it became 0. With Q8's A, everything else the replaced material held stays too, so "a value left out stays as it is" holds | `test_material.py`, `test_physics_handler.py` (new); live `test_15_02b` |
| R8 | none; the maintainer's | `get_sim_state` | an addition | The answer names the Kit app, its version and Kit's version, and with Q10 the OS of Kit's machine: `kit_app = Isaac-Sim Python 6.2.0`, `kit_version = 110.4.0+feature.386251.187cf21b.gl`. The `report-bug` skill, the server's instructions and `docs/AI_GUIDE.md` read them from it and ask the user only when they read `unknown` | `test_bridge_token.py`, `test_tools.py`, `test_physics_handler.py`, `test_bug_reports.py`; live `test_01`, `test_02` |

Why: each answer misleads an agent that trusts it. A rotation is off by 39°, a prim seems on screen when it isn't, an
unlit capture comes with no word on the light, and a percentage is made up. A robot lies on its side and falls over
when the simulation plays. A body given only a bounce slides as on ice. R8 makes a bug report automatic: the one
thing #109's skill still asks the user is the Kit app.

| In scope | Out of scope |
|---|---|
| The five bugs, and `compare_prims`' signs, found reading R1's code | A robot file whose `metersPerUnit` isn't the stage's (Q6) |
| `inspect_prim`'s warning, which has R4's blind spot (Q2) | The extension's `face_reduction_pct` for A's 0 faces: it stays `0`, and the server, its only reader, ignores it then |
| Five scenarios' Verify lines: 2.2, 10.1, 20.6, 23.6, 26.2 | Scenario 2.1's DistantLight, which points up on a Y-up stage: #103's (see The probe, R4) |
| Descriptions, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, the READMEs, the scene skill, `CHANGELOG.md` | Scenarios 24.5's `since_index` and 24.6's text: #103's; 24.6 there now logs one error and raises another (`a65189f`) |
| R7, in the Kit extension; the server's answer stays as #108 made it | A whole-frame `is_black`, which stays as it is: the renderer warming up still needs it |
| R8, on both sides, and its follow-on in #109's texts: the `report-bug` skill, the server's instructions, `docs/AI_GUIDE.md`, `tests/test_bug_reports.py` | R7's material name, shared by prims of the same name, which the description already says: Q9 and a follow-up issue |
| | `tools/scenarios.py`'s `KIT_FACTS`, which could read R8's `/health` fields but still needs `/execute` for the bridge's folder |

## What the code, the sources and the probe say

### The code, at `3b2b0cf` (#108 merged)

| Row | Where | What it does |
|---|---|---|
| R1 | `handlers/usd_advanced.py:369-370` | `face_pct = ... if stats_a["total_faces"] > 0 else 0`: from 0 faces the percentage is 0 |
| R1 | server `tools/usd_advanced.py` `compare_prims` | One `sign`, from the faces delta, goes in front of every delta: `+` for 0 and up, nothing below. A vertex drop beside a face rise prints `+-5`, and a vertex rise beside a face drop prints `9` |
| R2 | `core/formatter.py:109-113`, `format_prim_block` | `world_xform.ExtractRotation()`. `GfMatrix4d::ExtractRotation` assumes a pure rotation; with a scale it gives a wrong angle, or none under a scaled parent with a non-uniform scale (U1). `get_prim_properties`, `get_scene_tree`'s file (`format_scene_dump`) and recordings (`format_frame_state`) all print this line |
| R3 | `core/bounds.py:91-111`, `screen_box` | The axis-aligned rectangle of the projected corners, clamped to the viewport; None only when that rectangle is wholly off it. A box's outline is a polygon, so its rectangle can reach the frame's corner when the polygon doesn't |
| R4 | `handlers/camera.py:133-146`, `_is_image_black` | True when no pixel of the whole image is above 5 |
| R4 | `handlers/camera.py:779-794`, `handle_capture` | Sends `has_scene_lights` only when the image is black |
| R4 | server `tools/camera.py:137-149` (`capture_viewport`), `:358-367` (`inspect_prim`) | A warning only when `is_black`; its text then names the lighting mode |
| R5 | `handlers/misc.py:96-114`, `handle_execute` | Swaps stdout and stderr for buffers, catches the script's exception and returns it with its traceback: nothing reaches Kit's log. `core/http.py:236` logs only a handler's own exception |
| R6 | `handlers/robot.py:101-109`, `handle_create_robot` | `DefinePrim`, then a plain `GetReferences().AddReference(url)`, then `write_transform`. No up axis is read |
| R7 | `handlers/simulation.py:134-162`, `handle_set_physics_properties` | With friction or restitution, it defines `/World/PhysicsMaterials/<prim name>_PhysMat` with `MaterialAPI` when it isn't there, writes only the values given, and binds it to the prim for physics, in place of any physics material bound before. A value left out is unauthored on a new material, so PhysX reads USD's fallback, 0 (U4), not the value the body had. A material bound before, an asset's for example, loses all its values, its density and PhysX's own attributes too |
| R7 | server `tools/simulation.py`, `_physics_values` (#108) | Prints the values the route echoes, the ones given; one left out "stays as it was", which the description says too |
| R8 | server `tools/simulation.py:77-107`, `get_sim_state` | Prints `/sim/state`'s state, time, fps, prim count, axis and units, then `extension_version`, which the client keeps from the `GET /bridge` handshake (`core/http.py:100`), and `server_version` |
| R8 | `handlers/simulation.py:72-97`, `handle_sim_state`; `handlers/misc.py:27-42`, `handle_health` | Nothing about the Kit app. `/health` gives the protocol and extension version, for people |
| R8 | `core/protocol.py`; `bridge/extension.py:85` | Holds the extension's version, which `on_startup` sets from its id |
| R8 | #109's texts (PR #110) | The `report-bug` skill's step 3 has the agent ask the user for the Kit app and its version (Help > About), and for Kit's OS when Kit runs on another machine; its table's first row is `Kit app and version`; the server's instructions and `docs/AI_GUIDE.md` list the Kit app beside `get_sim_state`'s two versions; `tests/test_bug_reports.py` checks the instructions and the skill name `server_version` and `extension_version` |

### The sources

Read on disk in Isaac Sim 6.2's install:

| # | What | Where |
|---|---|---|
| K1 | Kit's metrics assembler resolves a referenced file whose `upAxis`, `metersPerUnit` or `kilogramsPerUnit` differs from the stage's, "applying ... corrections to transform operations on top-level divergent prims". For a Z-up file on a Y-up stage its test expects `xformOp:rotateX:unitsResolve` = -90; a units difference adds `xformOp:scale:unitsResolve` | `omni.usd.metrics.assembler-110.1.2`: `docs/README.md`; `core/tests/referenceTests.py:180-205` |
| K2 | In mode Auto (`/metricsAssembler/operationMode` 3) it runs from the POST_DO callbacks of Kit's `CreateReferenceCommand`, `CreatePayloadCommand`, `AddReferenceCommand` and `AddPayloadCommand`: a drag and drop. A plain `AddReference` never reaches it. It also offers `resolve_hierarchy(stage_id, path)` to scripts | `omni.usd.metrics.assembler.ui-110.1.3`: `metricsAssemblerManager.py:164-200`, `:344-402` |
| K3 | With the assembler off, `CreateReferenceCommand` turns a file of another up axis itself when `/exts/omni.usd/commands/rotateOnCreatingReference` is set: a matrix that cycles the axes, so +Z goes to +Y and +X to +Z. The asset's up axis is `UsdGeom.GetStageUpAxis` of the file's stage, so an unauthored one counts as USD's fallback, Y | `omni.usd-1.19.11`: `usd_commands.py:5833-5850` |
| K4 | `xform.py` keeps a `:unitsResolve` op where it is, most local, and adds no op after one | `core/xform.py:7`, `:195` |
| K5 | A physics material bound to the physics scene prim is the scene's default material, which PhysX gives a collider bound to none; omni.physx's own demo binds one so, with friction 0.5 | `omni.physx.demos-110.4.4`: `scenes/MaterialRestitutionDemo.py:25-34` |
| K6 | `omni.kit.app`'s `IApp`: `get_app_name()` "App name. It is app/name setting if defined, otherwise same as `filename`"; `get_app_version()` "Version in kit file or kit version"; `get_kit_version()` "Full kit version, e.g. `103.5+release.7032.aac30830...`"; `get_platform_info()` a dict | Isaac Sim 6.2's kernel: `kit/kernel/py/omni/kit/app/_app.pyi:77-115`, `:127` |

### usd-core 26.11 (a scratch check, not kept)

| # | What it showed |
|---|---|
| U1 | Scenario 2.2's cube through `format_prim_block`: `rot = 0.7428, 0.0000, 0.6695, 0.0000`, 84.06°. `RemoveScaleShear().ExtractRotation()` and `Gf.Transform(m).GetRotation()` give `0.9239, 0, 0.3827, 0`, 45°. A cube turned (30, 45, 60) and scaled (1, 2, 3) under a parent turned (10, 20, 30) and scaled 2: `ExtractRotation` gives no rotation, `(1, 0, 0, 0)`; both others give the composed rotation (1e-12). A mirror, scale (-1, 1, 1), factors as a 180° rotation and scale (-1, -1, -1), both ways alike. A scale of 0 gives `(1, 0, 0, 0)` in all three |
| U2 | A layer's `upAxis` and `metersPerUnit` read from `layer.pseudoRoot.GetInfo(...)`, and `HasInfo` tells an unauthored one, whose fallback, `UsdGeom.GetFallbackUpAxis()`, is Y |
| U3 | Scenario 26.2's TestCube corners in front of the camera, projected by hand with the probe's camera (below), give the reported box `[597.5, 213.2, 640, 480]`. Their outline's left edge crosses y = 480 at x = 844, and the points where its edges cross the near plane lie far to the right, so no part of it lies on the 640 x 480 image |
| U4 | `UsdPhysics.MaterialAPI` applied with nothing authored: `physics:staticFriction`, `physics:dynamicFriction`, `physics:restitution` and `physics:density` all read 0, unauthored |
| U5 | usd-core has no `pxr.PhysxSchema`. A prim with `PhysxMaterialAPI` added by name (`AddAppliedSchema`) lists only `PhysicsMaterialAPI` in `GetAppliedSchemas()`, and `HasAPI("PhysxMaterialAPI")` is false; its `apiSchemas` list op holds both, and a `physxMaterial:frictionCombineMode` attribute reads back by name with its type, `token` |
| U6 | The root layers of the ten robots in `ROBOT_ASSETS`, from Isaac Sim 6.2's asset server (`Assets/Isaac/6.2/Isaac/Robots/...`), read with `Sdf.Layer` alone: every one authors `upAxis = "Z"` and `metersPerUnit = 1`. Their default prims author `[translate, orient, scale]` (anymal_c, carter_v1, g1, go1, spot, ur10) or no ops (go2, h1, jetbot, panda_instanceable); none has a pivot or an inverse op |

### The probe: R1 to R6

`105-probe.py`, run by the session through `105-probe.sh` (both in its scratchpad's `105/`) on a fresh headless Isaac
Sim 6.2.0 at port 8212 with main's 0.3.0 extension. It exited 0 with an empty stderr. Each row's scene is on a Y-up
stage, as the scenario run's was, and R6 also on a Z-up one.

| # | What | What it showed |
|---|---|---|
| R1 | `compare_prims` through the server | A Cube (0 faces) to a 4-quad mesh: `faces: +4 (+0%)`. A 1-face, 9-vertex mesh to a 2-face, 4-vertex one: `faces: +1 (+100.0%)`, `vertices: +-5`. Back to 0 faces: `-100.0%`, right |
| R2 | 2.2's three `set_prim_transform` calls, then `get_prim_properties` | Ops `translate (2, 2, 0)`, `rotateXYZ (0, 45, 0)`, `scale 0.5`; `rot = 0.7428, 0.0000, 0.6695, 0.0000`. Kit's own `ExtractRotation` gives 84.06°, `RemoveScaleShear().ExtractRotation()` 45.00° |
| R3 | 26.2's scene: a 2 m `/World/TestCube` at (3, 0.5, 0), `/World/SettleTest` at (0, 1, 0), `set_camera` on SettleTest at azimuth 45, elevation 30 | The camera at (1.5309, 2.25, 1.5309), focal length 18.1476, horizontal aperture 20.955, clipping from 0.01. TestCube's box `[597.4, 213.1, 640, 480]`, and 0 pixels of it in the segmentation, whose legend names SettleTest alone. From 26.2's rounded eye (1.53, 2.25, 1.53), the same. From 26.1's eye (5, 3, 5), TestCube shows, 63,074 pixels, box `[386.2, 145, 640, 460.8]`: the control |
| R4 | Each lighting mode at 320 x 240, then stage lighting with scenario 2.1's light and with it turned down. The table below. No warning in any case, and `is_black` false in every one | |
| R5 | A nonce raised, printed, written to stderr, and logged with `carb.log_error` and `carb.log_warn` | The raise came back as the answer's error, `print` and stderr in its `stdout` and `stderr`. Kit's log file, `/log/file`, holds only the two `carb` lines (`[Error] []` and `[Warning] []`). `get_logs(search=...)` finds those two, at levels error and warn, and none of the other three; `total_captured` went from 2516 to 2518. The scenario run's "780 the whole session" was a quiet Kit: the server sends every call over one kept-alive connection, so the bridge logs no new connection lines |
| R6 | `create_robot` and Kit's own paths for the same file. The table below | |

R4, the brightest channel of each pixel, over the prims (the segmentation's non-black pixels, 18,152) and off them
(the background and Kit's grid):

| Lighting | Prim pixels above 5 | Their median | Off-prim pixels above 5 | `is_black` | Warning |
|---|---|---|---|---|---|
| `camera` | 18,152 (100%) | 183 | 20,613 | false | none |
| `off` | 365 (2%, edges against the grid) | 0 | 20,355 | false | none |
| `stage`, no lights | 361 (2%) | 0 | 20,362 | false | none |
| `Default` | 18,152 (100%) | 152 | 20,576 | false | none |
| `stage`, 2.1's DistantLight, rotation (45, 0, 0), pointing (0, 0.707, -0.707): up | 12,768 (70%) | 254 | 20,644 | false | none |
| `stage`, the same light turned to (-45, 0, 0), pointing (0, -0.707, -0.707): down | 16,243 (89%) | 254 | 20,666 | false | none |

So on a Y-up stage scenario 2.1's light points up and lights only the faces that face +Z. Turned to (-45, 0, 0) it
points down. On a Z-up stage (45, 0, 0) already points down, at (0, 0.707, -0.707). That is #103's to settle.

R6, Isaac Sim 6.2's settings: `/metricsAssembler/operationMode` 3 (Auto), `rotateOnCreatingReference` false, and new
stages Z-up (`/persistent/app/stage/upAxis`). `g1.usd` and `panda_instanceable.usd` both author `upAxis = "Z"` and
`metersPerUnit = 1`, as do the other eight of `ROBOT_ASSETS` (U6).

| How the file was added | Ops on the robot's prim | Size x, y, z | Stands? |
|---|---|---|---|
| `create_robot("g1", position=[3, 0.74, 0])`, Y-up | `translate (3, 0.74, 0)`, `orient`, `scale`, the file's own | 0.496, 0.371, 1.323 | no |
| Kit's `CreateReferenceCommand`, Y-up | the same, then `xformOp:rotateX:unitsResolve` = -90, in the root layer. The stage gains a layer, `metrics:UnitsAdjust-...` | 0.496, 1.323, 0.371 | yes |
| A plain reference, then the assembler's `resolve_hierarchy` | the same op, in the root layer; no layer added | 0.496, 1.323, 0.371 | yes |
| `create_robot("franka")`, Y-up | `translate` | 0.335, 0.259, 1.115 | no |
| `create_robot("g1", position=[0, 0, 0.74])`, Z-up | `translate`, `orient`, `scale` | 0.496, 0.371, 1.323 | yes |

### The probe: R7

`105-probe-r7.py`, beside the first, run by the session through `105-probe-r7.sh` on the same Kit, exit 0, an empty
stderr. On a Y-up stage with gravity 9.81, a ground whose physics material has friction and restitution 0 with
combine mode `max`, so each contact takes the body's own values. Then 1 kg boxes, each with or without a bound physics
material and the tool called with one value. The sliders start at 4 units/s along X, and the friction PhysX applies
is their deceleration over their first 0.3 s, over g. The droppers fall 1.25, and the restitution shows in their
rebound. 90 updates, 1.48 s of simulation:

| Body | What it has | Its material, as USD reads it before playing | What PhysX did |
|---|---|---|---|
| `SlideDefault` | no material | none | slid 1.406, deceleration 4.905: friction 0.50 |
| `SlideRestitutionOnly` | the tool with `restitution=0` alone | its new `_PhysMat`, both frictions unauthored, read as 0 | slid 5.933, no deceleration: friction 0 |
| `SlideFriction05` | the tool with `friction=0.5` | both frictions 0.5 authored, restitution unauthored | slid 1.406: friction 0.50, as the default |
| `SlideRubber` | a bound material of friction 0.9 | `/World/Mats/Rubber`, 0.9 | slid 0.688: friction 0.90 |
| `SlideRubberThenRestitution` | that material, then the tool with `restitution=0` | the tool's `_PhysMat` in its place, frictions unauthored | slid 5.933: friction 0, Rubber's 0.9 lost |
| `DropDefault` | no material | none | no rebound: restitution 0 |
| `DropFrictionOnly` | the tool with `friction=0.5` alone | restitution unauthored | no rebound, as the default |
| `DropBouncy` | a bound material of restitution 0.8 | `/World/Mats/Bouncy`, 0.8 | rebounded 0.789 above rest |
| `DropBouncyThenFriction` | that material, then the tool with `friction=0.5` | the tool's `_PhysMat` in its place, restitution unauthored | no rebound: Bouncy's 0.8 lost |

So PhysX reads an unauthored value as USD's 0, and its own default is dynamic friction 0.5 and restitution 0. Static
friction isn't measured apart: a box sent sliding shows the dynamic friction only. A call that gives restitution alone
on a bare body takes its friction from 0.5 to 0. On a body with a material of its own, either call takes away what
that material held. Friction alone on a bare body changes nothing else, since PhysX's default restitution is 0
already.

### The probe: R8

`105-probe-r8.py`, run by the session through `105-probe-r8.sh` on the same Kit, exit 0. It read and changed nothing:

| What | Isaac Sim 6.2.0 headless, Windows |
|---|---|
| `/health` today | `stage_path`, `up_axis`, `meters_per_unit`, `recording_active`, `protocol` 1, `extension_version` 0.3.0 |
| `/sim/state` today | `state`, `sim_time`, `fps`, `prim_count`, `up_axis`, `meters_per_unit`, `recording_active` |
| `get_app_name()` | `Isaac-Sim Python`, as the `/app/name` setting |
| `get_app_version()` | `6.2.0`, as `/app/version`; `get_app_version_short()` `6.2` |
| `get_kit_version()` | `110.4.0+feature.386251.187cf21b.gl`, as `get_build_version()`; `get_kit_version_short()` `110.4` |
| `get_app_filename()` | `isaacsim.exp.base.python` |
| `get_kernel_version()` | `210.4.11+release.15522.174283e4.gl` |
| `get_platform_info()` | `{'config': 'release', 'platform': 'windows-x86_64', 'python_version': 'cp312'}` |
| Python's `platform.platform()` in Kit | `Windows-11-10.0.26300-SP0` (`platform.system()` `Windows`) |

Each Kit app names itself in its kit file's `/app/name`; this headless one runs `isaacsim.exp.base.python`, named
`Isaac-Sim Python`, and Isaac Sim's GUI app has a kit file and name of its own. The three getters are what a bug form's "Kit app and version" needs; `platform.platform()` names
the OS and its build, where `get_platform_info()` names only the platform Kit was built for.

## Design

### R1: `compare_prims`' deltas (server only)

The server prints each delta with its own sign (`f"{v:+d}"`: `+4`, `-5`, `+0`). It gives the faces percentage only
when A has faces: `faces: +4 (A has 0 faces)`. It decides that from `a["total_faces"]`, never from
`face_reduction_pct`, so it works the same with any extension. The description's "the change in faces as a
percentage" gains "when A has faces".

### R2: the rotation `rot` prints (`core/formatter.py`)

`rot` is read from `world_xform.RemoveScaleShear().ExtractRotation()`: the world matrix with its scale and shear
taken out, which `Gf` factors as `Gf.Transform` does (U1). A mirrored prim reads as Gf factors it, a rotation with a
negative scale; a prim scaled to 0 reads as no rotation. Both are as before for an unscaled prim. The line keeps its
format, a quaternion `w, x, y, z`, and the description and `docs/TOOLS.md` say so.

`RemoveScaleShear` rather than `Gf.Transform`: one call, and it gives the matrix back unchanged when it can't factor it,
where the formatter must never raise.

### R3: a box is the outline's part on the image (`core/bounds.py`)

`screen_box(points, viewport, image)` keeps its signature and callers. It takes the points' outline, their convex
hull (Andrew's monotone chain), and clips it to the viewport, 0 to 1 on both axes (Sutherland-Hodgman). The box is
the clipped polygon's bounding rectangle, scaled to the image and rounded as today.

- **None** when nothing of it lies on the viewport, or what lies there has no width or no height: a polygon that only
  touches the frame's edge or corner has no pixel on it.
- **A pinhole camera's points** are the box's corners in front of the camera and where its edges cross the near plane
  (`project_in_front`, #90). Their hull is the projection of the box's part in front, so the clip is exact.
- **A fisheye camera's points** are Kit's own projection of the 8 corners (`world_to_image`), which isn't linear.
  There the hull is an approximation, as the rectangle was.
- **What it still bounds:** the prim's world box, not its pixels. A prim hidden behind another, or one whose world
  box reaches into the view while its mesh doesn't, still gets a box. The description already says "visible" only
  of the segmentation. `docs/TOOLS.md` says a box is the prim's world box where it lies on the image.

Alternatives: clipping the box in 3D against the frustum's planes gives the same polygon with more code; checking the
segmentation for the prim's pixels would drop occluded prims too, which the boxes are for.

### R4: a warning when the lighting leaves the scene unlit (Q1, Q2)

`is_black` keeps its meaning, a whole frame with no pixel above 5, and its retry after a renderer reset: a cold
renderer gives that. Kit 110's captures show the grid in any lighting, so lighting that lights nothing no longer
makes a black frame. That case was the reason for the check (AGENTS.md, Traps: "Kit 105.1+ has no default light").
It gets a check of its own, from the lighting rather than the pixels (Q1, option A):

- **Extension:** `handle_capture` and `handle_camera_inspect` send `has_scene_lights` with a black image, as today,
  and with lighting mode `stage`, the one mode whose warning reads it. `_has_scene_lights` walks the whole stage on
  Kit's main thread, so the other modes don't pay for it on every capture.
- **Server:** one helper, `_unlit_warning(lighting_mode, has_scene_lights)`, used by both tools. It gives a warning
  for mode `off`, and for `stage` when `has_scene_lights` is `False`:
  `WARNING: Lighting mode is 'off': the scene's surfaces render black, though Kit's grid still shows. {LIGHTING_ADVICE}`,
  and for stage, `WARNING: Lighting mode is 'stage' and the scene has no lights: ...`.
- **The order:** an all-black image keeps today's warning, which names the mode already. The unlit warning comes when
  the image isn't all black. `inspect_prim` gives it once per call, as it does the black one, and its isolate note
  stays with the black one.
- **An older extension** sends `has_scene_lights` only with a black image, so `off` still warns and `stage` without
  lights doesn't.

### R5: no code (Q3)

The scenario was written in March, when a Python hook took Kit's log, and `handle_execute` never logged a script's
exception then either. `execute_script`'s description already says the exception, stdout and stderr come back in its
answer. `get_logs`' description and `docs/TOOLS.md` gain: "A script's own exception, print and stderr come back in
execute_script's answer and never reach Kit's log; carb.log_error and the other carb.log_* calls in a script do."

#103 fixed scenario 24.6's text (`a65189f`): its script now writes `carb.log_error('log_test_error')`, which
`get_logs` finds, then raises `RuntimeError('log_test_raise')`, which it doesn't. #105 leaves the text alone; only
its live twin, `test_24_06`, which #103 left as it was, comes to check what the text says.

### R6: a robot stands on a stage of the other up axis (Q4 to Q7)

A Kit-free function in `core/robot.py`, `up_axis_turn(layer, stage_up_axis)`, returns the degrees about X that stand
the file's root prim on the stage, or None:

| The file's `upAxis` (authored) | The stage's | Degrees about X | Why |
|---|---|---|---|
| Z | Y | -90 | +Z goes to +Y, +X stays +X: K1's value |
| Y | Z | +90 | +Y goes to +Z |
| the stage's own | | None | |
| not authored | | None (Q5) | A file that doesn't say could be either |

`handle_create_robot` already opens the file's layer (`Sdf.Layer.FindOrOpen`, before the prim). After the reference,
and before `write_transform`, it writes `xformOp:rotateX:unitsResolve` in the edit target's layer. That is the op
Kit's metrics assembler writes on a drag and drop (K1, the probe), and it goes where Kit puts it: before the first
inverse op, else last, as `xform.py`'s `_before(order, _is_inverse)` places one. Kit keeps an inverse op last
(K1's test asserts it after a resolve), so a pivot pair stays around the turn, and the robot lands where Kit puts it.
So:

- `position` and `rotation` stay in the stage's frame, in the file's own root ops outside the turn: `rotation=[0, 90,
  0]` on a Y-up stage turns the standing robot about Y.
- `set_prim_transform` later keeps the op where it is (K4), and so does Kit's own transform gizmo.
- A refusal from `write_transform` already removes what the call made, the op with it.
- **A file whose root already has the op,** such as a robot Kit dropped into a stage and saved as a file of its own:
  that op turns the file's content to the file's own up axis, and the turn from the file to the stage is still owed.
  Both are turns about X, so the stage's layer writes the sum into the same op, its order unchanged (`AddXformOp`
  refuses a name already in the order). A Z-up robot saved into a Y-up file, -90, given to a Z-up stage, +90, gets 0:
  its content was Z-up all along. The answer reports the turn added.

The answer gains `up_axis_turn`: `{"file": "Z", "stage": "Y", "degrees": -90, "op": -90}`, or `null`, where
`degrees` is the turn this call added and `op` the value the op holds after it. The server names both, so an agent
that reads the op back finds what the answer said:
`Turned upright: the file is Z-up and the stage Y-up, so -90° about X went into xformOp:rotateX:unitsResolve, which
now reads -90, as Kit's metrics assembler turns a dropped file`. In P3's case, a Y-up file whose op holds -90 on a
Z-up stage, it reads `... +90° about X, added to xformOp:rotateX:unitsResolve, which now reads 0`. An older extension
sends no field, and the server prints nothing.

Alternatives (Q4): Kit's `CreateReferenceCommand` or `AddReferenceCommand`, whose callbacks reach the assembler in
mode Auto, adds a layer to the user's stage (the probe) and does nothing in mode Warn or Disabled. Calling
`resolve_hierarchy` directly gives the same op in Isaac Sim, and scales a file of other units too. But it is Kit's C++,
testable only live, and absent where the assembler doesn't load. The op written here is the same op, in every Kit
app, and tested on usd-core.

### R7: the material the call binds starts from the body's values (`core/material.py`, Q8)

The probe showed both halves: a value left out becomes 0, and a material bound before is replaced whole. The tool's
promise, "a value left out stays as it is", is kept by writing every value, the left-out ones as PhysX applies them
now. Before it binds its material, the handler reads, for static friction, dynamic friction and restitution, what the
body has:

1. **The physics material bound to it:** `UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics")`, which
   falls back to an all-purpose binding, when that material has `MaterialAPI`: its values as USD reads them, authored
   or the fallback 0, which is what PhysX reads (the probe's `SlideRestitutionOnly`).
2. **Else the physics scene's default material** (K5): the one bound to the stage's `UsdPhysics.Scene` prim.
3. **Else PhysX's own default:** constants in the core, as the probe measured them: dynamic friction 0.5 and
   restitution 0. Static friction is taken as 0.5 too, PhysX's default beside its dynamic one. The live test compares
   a body the tool gave one value with a control that has no material and no call, on the same floor and slopes, so
   a PhysX whose default differs from these constants fails it.

It then writes all three into its material: the value given, else the one read. The rule is the same whether the
call makes the material, rebinds it in place of another, or finds it bound already. In the last case a value read is
the material's own, so nothing left out changes. A material an older extension made with a value unauthored reads 0
and keeps it, which is what PhysX gave the body.

**What else it takes (Q8):** the probe's `SlideRubberThenRestitution` and `DropBouncyThenFriction` lost every value
of the material they had, not one. That material may hold more than the three values: a density, which sets the mass
of a body without one, and `PhysxMaterialAPI`'s combine modes and compliant contact. With Q8's A the new material
copies every authored `physics:` and `physxMaterial:` attribute of the material its values come from, and its
`PhysxMaterialAPI`, before writing the values given, so the body behaves as before in everything the call didn't
name. That is the one bound before, or the physics scene's default material when the values come from it (step 2):
a scene default with `frictionCombineMode = max` keeps its combine mode on the body too.

**How it copies on usd-core too (U5):** usd-core has no `PhysxSchema`, so `HasAPI` and `GetAppliedSchemas()` can't
see `PhysxMaterialAPI` there. The copy reads the source's composed `apiSchemas` list op, applies what it holds by name
with `AddAppliedSchema("PhysxMaterialAPI")`, and copies each attribute by its name, its type name and its value.

**The shared material (Q9):** the material is `/World/PhysicsMaterials/<prim name>_PhysMat`, shared by every prim of
that name, as the description says. Writing all three values makes that sharing reach further: a call on one prim now
writes values nobody named into a material another prim of the same name uses (Risks). Q9 asks whether to keep the
name now and give each prim its own in a follow-up.

All of it is Kit-free in `core/material.py`, beside `set_material`'s material: `physics_values(prim)` (the three, and
the material they come from), `start_from(material, source)` (Q8's copy) and the PhysX defaults. The answer stays as
#108 made it: the values given, and the APIs applied.

### R8: `get_sim_state` names the Kit app (Q10)

The Kit app can't change while Kit runs, so the extension reads it once:

- **`core/protocol.py`,** which holds the extension's version, gains `kit_app_facts(app)`: from the object passed in,
  `get_app_name()`, `get_app_version()` and `get_kit_version()` (K6), each in a try of its own, so one a Kit app
  lacks, or that raises, reads `unknown` and the others still come; and with Q10, `platform.platform()`, Python's
  name for the OS Kit runs on. Kit-free: the app is an argument.
- **`extension.py`'s `on_startup`** stores `kit_app_facts(omni.kit.app.get_app())` beside the extension version.
- **`/sim/state` and `/health`** answer `kit_app_name`, `kit_app_version`, `kit_version` and, with Q10, `kit_os`.
  `/sim/state` is the route `get_sim_state` calls; `/health` reports them for people, as it does the protocol, and
  keeps them, with a unit test of its own. The wire field is `kit_app_name`, so `kit_app` means one thing: the
  answer's line, the name and version together. The `GET /bridge` handshake stays as it is: the server needs nothing
  from it before a tool call, and `core/http.py` would have to be handed the facts.
- **The server,** `get_sim_state`, prints them before the two versions:

  ```text
  kit_app = Isaac-Sim Python 6.2.0
  kit_version = 110.4.0+feature.386251.187cf21b.gl
  kit_os = Windows-11-10.0.26300-SP0
  extension_version = 0.4.0
  server_version = 0.4.0
  ```

  `kit_app` is `kit_app_name` and `kit_app_version` in one line, as the bug form's "Kit app and version" asks. An
  older extension sends none of them: each line reads `unknown`, through `r.get`, never a `KeyError`.

**#109's texts (PR #110, on `main` before this code),** so a report no longer asks the user for what the answer has:

- **`plugin/skills/report-bug/SKILL.md`,** through `write-skill`. Step 3's `get_sim_state` bullet gathers `kit_app`,
  `kit_version` and `kit_os` with the two versions. Its "The Kit app and its version: ask the user (Help > About in
  the app)" becomes: ask only for one that reads `unknown`, an extension older than this release. Its OS bullet
  reports Kit's OS from `kit_os`, and this machine's only when it differs: the agent usually can't see
  `OMNIVERSE_MCP_HOST`, so it can't tell when Kit runs elsewhere. The table's first row, from `kit_app` and
  `kit_version`, shows `Isaac-Sim Python 6.2.0 (Kit 110.4.0+feature.386251.187cf21b.gl)`.
- **`src/omniverse_mcp/server.py`'s instructions** and **`docs/AI_GUIDE.md`'s bullet:** "A report holds the Kit app
  and version, the OS and the client; server_version and extension_version from get_sim_state" becomes "A report
  holds kit_app, kit_version, kit_os, server_version and extension_version from get_sim_state (ask the user for any
  that reads unknown); this machine's OS when it differs, and the client". A client without the plugin, such as
  Cursor with a 0.4.0 server and a 0.3.0 extension, so still asks for what the answer lacks (P8).
- **`tests/test_bug_reports.py`'s versions test** asserts `kit_app` and `kit_version`, and `kit_os` with Q10, in the
  instructions, the skill and `docs/AI_GUIDE.md`, beside `server_version` and `extension_version`.

### Older extensions

| Row | With an extension of 0.3.0 or older |
|---|---|
| R1 | Fixed: the server alone |
| R2, R3, R6, R7 | As today; the server can't tell |
| R4 | `off` warns; `stage` with no lights doesn't |
| R8 | `kit_app`, `kit_version` and `kit_os` read `unknown`, and the skill asks the user, as before R8 |

`docs/TOOLS.md` says so in each section, and CHANGELOG names the extension install, as #82 did.

### Decisions for the maintainer

| Q | Question | Options | Recommendation |
|---|---|---|---|
| Q1 | R4: what finds the unlit scene? | **A.** The lighting: mode `off`, or `stage` with no scene lights. Certain of its cause, cheap, and without the segmentation. It misses a light that points away. **B.** The pixels: the median brightness of the segmentation's prim pixels at 5 or less (the probe: 0 when unlit, 152 or more when lit). It catches a light aimed away too, but needs `omni.syntheticdata`, and a scene of black materials would warn. **C.** Both | A: it is the case the check was made for, and its warning can name the fix with certainty |
| Q2 | R4: `inspect_prim` too? | Yes, through the same helper; or `capture_viewport` alone, as the issue's row says | Yes: the same blind spot, one helper, and `inspect_prim` already sends the lighting mode |
| Q3 | R5: what changes? | **A.** A sentence in `get_logs`' description and `docs/TOOLS.md`; #103's 24.6 already expects a raised error not to be found. **B.** Also, the bridge logs a script's exception to Kit's log as a warning, so `get_logs` finds it | A: the exception is already in the answer the agent reads, and B would put every failed experiment in the user's Kit log |
| Q4 | R6: how is the robot stood up? | **A.** The op Kit's assembler writes, written by the core. **B.** Kit's `resolve_hierarchy` where the assembler loads, A elsewhere | A (Design, R6) |
| Q5 | R6: a file that authors no `upAxis`? | **A.** Leave it as it is. **B.** Take USD's fallback, Y, as Kit's `CreateReferenceCommand` does (K3): on Isaac Sim's Z-up stages such a file is turned | A: a turn on a guess lays down a robot that stood. The answer says nothing then, as today |
| Q6 | R6: a file of other `metersPerUnit`? | **A.** Out of scope, a new issue. **B.** A line in the answer naming the two. **C.** Scale it too (`xformOp:scale:unitsResolve`), physics' values unscaled | A: no file in Isaac Sim's library differs, and C scales the geometry without its masses and drives |
| Q7 | R6: someone who stood a robot themselves, with `rotation=[-90, 0, 0]` on a Y-up stage, now gets it turned twice | **A.** CHANGELOG's Fixed entry says so, and to drop that rotation. **B.** Under Breaking changes | A: the schema doesn't change, and the answer's line names the turn |
| Q8 | R7: what does the material the call binds take from one it replaces? The probe: a body with a material of its own lost all of it, Rubber's friction 0.9 to a restitution-only call and Bouncy's restitution 0.8 to a friction-only one | **A.** Every authored `physics:` and `physxMaterial:` attribute, and `PhysxMaterialAPI`, of the material the values come from: the one bound before, or the physics scene's default material when they come from it, so a scene default's combine mode survives too. Then the values given. **B.** The friction and restitution alone; a replaced material's density and PhysX attributes go, as today | A: the description promises a value left out stays as it is, B keeps that only for the two values the tool names, and a lost density changes the body's mass |
| Q9 | R7: the material stays `<prim name>_PhysMat`, shared by prims of one name, and now each call writes all its values (P5) | **A.** Keep the name now: a Risks row, a CHANGELOG sentence, and a follow-up issue for B. **B.** Name the material after the prim's whole path, so each prim has its own; the description and `docs/TOOLS.md` change | A in this change, B as a follow-up best landed in the same release, since R7 widens the cross-talk. B costs less than it looks (round 2): R7's step 1 reads from whatever `<name>_PhysMat` a prim is bound to, so the next call moves an old binding over to the prim's own material |
| Q10 | R8: report the OS Kit runs on as well, `kit_os`, from Python's `platform.platform()` in Kit's process (`Windows-11-10.0.26300-SP0`)? | **A.** Yes: the bug form asks for both machines' OS when Kit runs on another one (`OMNIVERSE_MCP_HOST`), and the skill would no longer ask. **B.** No: the app and its version only, as the issue's row asks | A: one more line, and the remote case reports itself too. On Linux it names the kernel and glibc, not the distribution, which is enough for a report (round 2) |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change: `tests/fixtures/mcp-tools.json` holds
  `get_sim_state`'s `{}` in and `result: string` out, which stay, and `tools/golden.py` leaves descriptions out. The
  wire protocol, as AGENTS.md's door names it, is the paths, the auth header and the token file's place: the routes
  keep their paths and gain answer fields only, `has_scene_lights` in mode `stage`, `up_axis_turn`, and R8's
  `kit_app_name`, `kit_app_version`, `kit_version` and `kit_os` on `/sim/state` and `/health`. `PROTOCOL` stays 1: an older
  server ignores a field it doesn't read.
- **What users notice:**
  - `rot` lines change for every scaled prim, in `get_prim_properties`, `get_scene_tree`'s file and recordings'
    `state.txt`.
  - Captures list fewer boxes: none for a prim beside the view, and smaller ones for a prim whose outline crosses a
    corner of the frame.
  - Unlit captures warn.
  - On a Y-up stage, every library robot, and any file authoring Z-up, now stands where it lay: its links' positions,
    its bounds and what it does when the simulation plays change. A robot already in a scene is left as it is.
    Q7 for someone who turned one themselves.
  - `set_physics_properties` with one of friction or restitution keeps the other, where it set it to 0: a body given
    a bounce no longer slides as on ice. A body that did so already keeps what it has. A call now writes all three
    values into the material prims of one name share (Q9).
  - `get_sim_state` has three lines more, four with Q10.
- **Kit apps:** R6's op is plain USD, so every Kit app gets it. It is the op Kit's assembler writes; whether the
  assembler, run on the stage later, leaves it alone is checked live (Risks).

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the three probes, R1 to R8, and this plan settled on them | `105-probe.out.txt`, `105-probe-r7.out.txt` and `105-probe-r8.out.txt` in the session's scratchpad |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 1b | Before any code: rebase the branch onto `origin/main`, `d59667a` (#110) or later, so step 9 has #110's files; the tests' "fails at" base moves with it | `git log` shows #110 under the plan's commits |
| 2 | R1: the server's deltas | `tests/test_tools.py` |
| 3 | R2: `core/formatter.py` | `tests/test_formatter.py` |
| 4 | R3: `core/bounds.py` | `tests/test_bounds.py` |
| 5 | R4: `has_scene_lights` on every answer; the server's `_unlit_warning` for both tools | `tests/test_camera_handler.py`, `tests/test_tools_camera.py`, `tests/test_tools.py` |
| 6 | R6: `core/robot.py`'s `up_axis_turn`, `handle_create_robot`, the server's line | `tests/test_robot.py`, `tests/test_robot_handler.py`, `tests/test_tools.py` |
| 7 | R7: `core/material.py`'s physics values, `handle_set_physics_properties` | `tests/test_material.py`, `tests/test_physics_handler.py` |
| 8 | R8: `core/protocol.py`'s `kit_app_facts`, `on_startup`, `/sim/state` and `/health`, `get_sim_state`'s lines | `tests/test_bridge_token.py`, `tests/test_physics_handler.py`, `tests/test_tools.py` |
| 9 | R8's follow-on in #109's texts (PR #110, merged by then): the `report-bug` skill through `write-skill`, the server's instructions, `docs/AI_GUIDE.md` | `tests/test_bug_reports.py`; the gate's skill checks |
| 10 | Docs, and the five scenarios' Verify lines (Docs, below) | The gate's checks; `tests/test_contract.py` unchanged |
| 11 | The live tests below, run by the session on Isaac Sim 6.2 headless at 8212: the new and changed tests alone on a fresh Kit's Z-up stage and again on a Y-up one, then both suites whole | No failure beyond `main`'s on the same Kit |
| 12 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fix has a test that fails at the base the code starts from, `origin/main` at `d59667a` or later (step 1b), named first. The `3b2b0cf` below is the plan's base, where each was read.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_tools.py` | R1: A with 0 faces prints `faces: +4 (A has 0 faces)` and no `%`; a vertex drop beside a face rise prints `vertices: -5`, a vertex rise beside a face drop `vertices: +9`, a zero `+0`; the existing case's `faces: -60 (-60.0%)` stays. R6: an answer with `up_axis_turn` prints the turned line with the turn added and the op's value, one without it or with `null` doesn't; one whose `op` differs from its `degrees`, P3's `+90` into an op that now reads 0, names both (P7) |
| `tests/test_formatter.py` | R2: 2.2's cube gives `rot = 0.9239, 0.0000, 0.3827, 0.0000`; U1's cube under a scaled, turned parent gives the composed rotation; an unscaled turned prim reads as before; a prim scaled 0 gives `1.0000, 0.0000, 0.0000, 0.0000` and doesn't raise; a recording's frame (`format_frame_state`) gives the same `rot` |
| `tests/test_bounds.py` | R3: the probe's 26.2 TestCube, through the probe's camera and `project_in_front`, is None (a box `[597.4, 213.1, 640, 480]` at `3b2b0cf`); the same camera's SettleTest box, as the probe measured within 0.5 px; a triangle wholly beyond a frame's corner, whose rectangle reaches in, is None; a triangle across a corner is boxed by its part on the frame; an outline that touches only an edge is None; points inside the frame are as before. `test_an_outline_partly_off_screen_is_clamped_to_the_viewport` gives a box's four corners, where its two points stood for a box's rectangle; their segment alone, which no box projects to, gets a case of its own |
| `tests/test_camera_handler.py` | R4: `handle_capture` and `handle_camera_inspect` send `has_scene_lights`, true and false, in mode `stage` with an image that isn't black, and leave it out in mode `camera` |
| `tests/test_tools_camera.py` | R4: `off` warns, with `is_black` false and with `has_scene_lights` absent (an older extension); `stage` with `has_scene_lights` false warns, with it absent doesn't; `camera`, `Default` and `stage` with lights don't; an all-black image gives today's warning and not a second; `inspect_prim` warns once for `off` |
| `tests/test_robot.py` | R6: `up_axis_turn` for Z on Y (-90), Y on Z (+90), the same axis and an unauthored one (None), from layers made in memory |
| `tests/test_robot_handler.py` | R6: a file authoring Z-up, tall along its Z, on a Y-up stage: the prim's last op is `xformOp:rotateX:unitsResolve` = -90, its world box tallest along Y, its base at `position`; `rotation=[0, 90, 0]` turns it about the stage's Y; a Y-up file on a Z-up stage gets +90; the same axis and an unauthored file get no op; a refusal after the reference leaves no op and no prim; the answer's `up_axis_turn`; a later `set_transform` keeps the op where it was. A root with a pivot pair, pivot (0.2, 0, 0.3): the op goes before `!invert!xformOp:translate:pivot`, and the world matrix is Kit's for that order, not one off by Rx·p - p (P4). A Y-up file whose root holds `xformOp:rotateX:unitsResolve` = -90, on a Z-up stage: the op reads 0 and the order is unchanged; on a Y-up stage, -90 unchanged and no turn (P3) |
| `tests/test_material.py` | R7: `physics_values` reads a bound material's authored values and its unauthored ones as 0; an all-purpose binding when there is no physics one; a bound material without `MaterialAPI` as none; the physics scene's default material; PhysX's default with neither. `start_from` copies the `physics:` and `physxMaterial:` attributes and `PhysxMaterialAPI`, added by name as usd-core sees it (U5), from a bound material and from the scene's default one (Q8), and nothing from the material it is given as its own |
| `tests/test_physics_handler.py` (new) | `handlers/simulation.py` loaded with Kit faked, as `tests/test_force_handler.py` loads it, on a usd-core stage. R7: restitution alone on a bare prim writes PhysX's default friction, static and dynamic, and the restitution given (friction unauthored at `3b2b0cf`); on a prim bound to a material of friction 0.9 and density 1000 with a combine mode, keeps all three; friction alone keeps a bound material's restitution 0.8; a second call keeps the first call's values; both given, as today; the answer is as #108's server reads it |
| `tests/test_bridge_token.py` | R8: `kit_app_facts` with a fake app gives its three values; a getter that raises, and one the app lacks, read `unknown` and leave the others; with Q10, `kit_os` is `platform.platform()` |
| `tests/test_physics_handler.py` | R8: `handle_sim_state` answers the stored facts, `kit_app_name` among them, beside what it answers today |
| `tests/test_misc_handler.py` (new) | `handlers/misc.py` loaded with Kit faked, as `tests/test_force_handler.py` loads `simulation.py`. R8: `handle_health` answers the stored facts beside the protocol and the extension's version, so `/health` isn't covered by live `test_01` alone |
| `tests/test_tools.py` | R8: the `get_sim_state` Case's `/sim/state` gains the fields, and the answer `kit_app = Isaac-Sim Python 6.2.0`, `kit_version = ...` and `kit_os = ...`, before `extension_version`; a `/sim/state` without them, an older extension's, prints `unknown` for each and raises nothing |
| `tests/test_bug_reports.py` | R8: the instructions, the skill and `docs/AI_GUIDE.md` name `kit_app` and `kit_version`, and `kit_os` with Q10, beside `server_version` and `extension_version`; the instructions and the guide say to ask for one that reads `unknown` |
| `tests/test_contract.py` | Unchanged |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_integration.py` `test_01`, `test_02_sim_state` | R8: `/health` and `/sim/state` answer `kit_app_name`, `kit_app_version` and `kit_version`, none `unknown`, and `kit_os` with Q10; through the server (`call_tool`), `get_sim_state`'s `kit_app` line |
| `test_08c_get_prim_properties_reads_a_scaled_prim_s_rotation` | Through the server (`call_tool`): 2.2's cube's `rot` |
| `test_12i_a_prim_beside_the_view_gets_no_screen_box` | 26.2's scene and eye, placed with `at()` as `test_12g` does: the side cube has no box and no segmentation pixels; the near cube's box is as the probe measured |
| `test_12g` | Unchanged: its prim across the camera's plane still runs off the right edge |
| `test_12j_an_unlit_capture_warns` | Through the server: `off`, and `stage` on a stage with no lights, warn in `capture_viewport` and `inspect_prim`; `camera` doesn't; the mode found is set back in the test's cleanup |
| `test_27b_a_robot_file_of_the_other_up_axis_stands` | A file the test writes, as `test_27` does, authoring the up axis the stage hasn't: it stands, tallest along the stage's up axis, with the op; then, where `omni.metrics.assembler.core` imports, `resolve_hierarchy` on it leaves one turn and the robot standing |
| `test_scenarios.py` `test_02_02` | Asserts the `rot` line, as scenario 2.2 now verifies |
| `test_10_01` | The G1's bounds are tallest along the up axis, on either |
| `test_15_02b_restitution_alone_keeps_the_friction` | The R7 probe's bodies, as a test, each against a control on the same floor: a box bound to a material of friction 0.9, then given restitution alone, decelerates as the same box left untouched does (within 0.05); a bare box given restitution alone, as a bare box with no material and no call does; one bound to a material of restitution 0.8, then given friction alone, rebounds as its untouched twin. On slopes of 24° (tan 0.45) and 29° (tan 0.55), a bare box given restitution alone rests or slides as the control beside it does. No constant is asserted, so a PhysX whose defaults differ from the core's fails it (P1) |
| `test_15_16` | On a Y-up stage it now pushes a turned Franka. After a few steps of play, before the push, the robot's bounds are still tallest along the stage's up axis, and its base link's turn from PhysX's pose is the create's, within 1°: the world-anchored root joint didn't pull it back to the file's orientation (P2) |
| `test_23_06` | Through the server: the `off` warning, the mode left as set |
| `test_24_06` | Runs 24.6's script as #103 wrote it: `log_test_error`, which `carb.log_error` wrote, is found at level error; `log_test_raise`, which the script raised, isn't, and comes back in the answer's error |
| `test_26_02` | Adds a cube beside the view: no box for it |

**What neither shows:** USD Composer, which isn't on this machine; Kit 107, unless the session has Isaac Sim 5.1 at
hand; a GUI viewport, since port 8211 is the maintainer's. Kit's assembler in mode Warn or Disabled is not tried: R6
doesn't go through it.

## Docs

- **`docs/TOOLS.md`:** each section below, with what an extension of 0.3.0 or older does.
- **The tools' descriptions,** the same sentences, in `src/omniverse_mcp/tools/`.
- **`test_project/scenarios.md`,** five Verify lines: the table below. 24.6 is #103's (R5).
- **`CHANGELOG.md`,** under Unreleased: below.
- **`AGENTS.md`'s Traps:** the "no default light" row's guard gains "and a warning for lighting that lights nothing"
  (R4); its core list gains nothing new, since `protocol.py`, `material.py` and `robot.py` are listed. The file stays
  at 150 lines.
- **`docs/ARCHITECTURE.md`** (P6): the core list's `material.py` adds set_physics_properties' physics material (the
  values a body has, and the copy), `robot.py` the turn a file of another up axis gets, and `protocol.py` the Kit
  app's name and versions (R8); the Robot System's `create_robot` bullet, the turn; and the `/health` sentence: it
  reports the Kit app too, for people.
- **`plugin/skills/scene/SKILL.md`,** through `write-skill` (P6): "a scene without lights captures black, and the
  capture says so" becomes "renders black, Kit's grid alone showing, and the capture warns".
- **`README.md`'s Troubleshooting** (P6): "A capture comes back black: the answer says so" becomes "A capture comes
  back black, or its prims do: the answer warns, with the lighting mode".
- **`new_scene`'s description and section** (P6): "Isaac Sim's robots and stages are Z-up: for robot work, open a Z-up
  stage" becomes "create_robot stands Isaac Sim's robots upright on either axis, but its other assets and stages are
  Z-up: for robot work, open a Z-up stage".
- **R8's follow-on in #109's texts:** the `report-bug` skill, the server's instructions and `docs/AI_GUIDE.md`, as
  Design R8 says.

| Row | Description and `docs/TOOLS.md` |
|---|---|
| R1 | `compare_prims`: "with B minus A, and the change in faces as a percentage when A has faces" |
| R2 | `get_prim_properties`: its world rotation is `rot`, a quaternion `w, x, y, z`, with any scale taken out. `start_recording`'s state file and `get_scene_tree`'s file give the same line |
| R3 | `capture_viewport`'s boxes file: a box is the prim's world box where it lies on the image; a prim wholly outside the image has none, beside the view as behind the camera |
| R4 | `capture_viewport`, `inspect_prim`, `viewport_light`'s When to use: a warning for an all-black image, and for lighting that lights nothing (mode `off`, or `stage` with no scene lights) though Kit's grid still shows |
| R5 | `get_logs`: Q3's sentence |
| R6 | `create_robot`: a file whose `upAxis` isn't the stage's stands upright on it, turned about X by `xformOp:rotateX:unitsResolve` as Kit's metrics assembler turns a dropped file, and the answer says so; `position` and `rotation` stay in the stage's frame; Isaac Sim's robots are Z-up, so each is turned on a Y-up stage; a file that authors no `upAxis` is left as it is |
| R7 | `set_physics_properties`: the material it binds starts from the body's own: the physics material bound to it before, else the physics scene's default material, else PhysX's default, so the friction or restitution left out stays as it is (and with Q8's A, that material's density and PhysX attributes too). The sentence on prims of one name sharing the material adds that a call writes all its values for each of them (Q9) |
| R8 | `get_sim_state`: the description's list gains the Kit app, its version and Kit's, and with Q10 the OS Kit runs on; Returns gains `kit_app`, `kit_version` and `kit_os`, each `unknown` with an older extension |

No scenario covers R7 (15.2 gives both values), so no Verify line changes for it.

| Scenario | Its Verify line becomes |
|---|---|
| 2.2 | `get_prim_properties("/World/RedCube")` shows the three ops set, and `rot = 0.9239, 0.0000, 0.3827, 0.0000`: the 45° turn about Y as a quaternion `w, x, y, z`, the 0.5 scale taken out |
| 10.1 | Returns the prim path and joint list. The G1 stands: `get_prim_bounds("/World/G1")` is tallest, about 1.32, along the stage's up axis (`get_sim_state`); on a Y-up stage the answer says it was turned upright, its file being Z-up |
| 20.6 | Returns a/b stats and the deltas. TestCube is a Cube, not a mesh, so A has 0 faces: the faces delta has no percentage, and each delta has its own sign |
| 23.6 | `capture_viewport()` gives a `WARNING` that lighting mode `off` leaves the scene unlit though the grid shows, naming `viewport_light` |
| 26.2 | The cube is visible in the capture, and `/World/TestCube`, beside this view, has no box in the boxes file |

`CHANGELOG.md`, under Unreleased:

```markdown
### Fixed

- **`get_prim_properties` reads a scaled prim's rotation:** `rot` came from the world matrix with its scale left in,
  so a 45° turn at scale 0.5 read as 84°, and a prim under a scaled parent could read as not turned. Recordings'
  `state.txt` and `get_scene_tree`'s file gave the same `rot`. The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit (#105).
- **`capture_viewport` gives no box to a prim beside the view:** it boxed any prim whose corners' rectangle reached
  the image, so a cube beside the view got a box at the frame's edge. A box is now the prim's outline where it lies
  on the image. The fix is in the Kit extension (#105).
- **`capture_viewport` and `inspect_prim` warn when the lighting lights nothing:** mode `off`, or `stage` with no
  scene lights. The warning came only with an all-black image, and Kit's grid keeps one from being all black. With
  an older Kit extension, only `off` warns (#105).
- **`compare_prims` gives no percentage from 0 faces,** where it said `+0%`, and each delta its own sign, where a
  drop in vertices beside a rise in faces read `+-5` (#105).
- **`create_robot` stands a robot upright on a stage of the other up axis,** as Kit stands a dropped file: Isaac
  Sim's robots are Z-up, and on a Y-up stage they lay on their side. The answer says when it turned one. **A call
  that turned the robot itself, with `rotation=[-90, 0, 0]`, now turns it twice: drop that rotation.** The fix is in
  the Kit extension (#105).
- **`set_physics_properties` keeps the friction when given only restitution, and the reverse:** the physics material
  it made held only the value given, so PhysX read USD's 0 for the other, and a body given a bounce slid as on ice.
  A physics material the prim had before, such as an asset's, was replaced, and every value it held went with it.
  The material now starts from the body's own, the one bound before, the physics scene's default or PhysX's.
  Prims of one name still share the material, so a call on one now sets all its values for each of them. The fix is
  in the Kit extension (#105).

### Added

- **`get_sim_state` names the Kit app, its version and Kit's, and the OS Kit runs on:** `kit_app = Isaac-Sim Python
  6.2.0`, `kit_version = 110.4.0+...`, `kit_os = Windows-11-...`. A bug report your assistant drafts takes them from
  there. They come from the Kit extension: run `uvx omniverse-mcp extension install`, then restart Kit; until then
  they read `unknown`, and the assistant asks you (#105).
```

## Risks

| Risk | Status |
|---|---|
| Kit's assembler, run later on the stage (a user's "resolve", or its change listener), adds a second turn to a robot `create_robot` turned | Checked by `test_27b` where the assembler loads; if it does, the fix moves to Q4's B. Open until step 11 |
| A robot under a turned parent: the turn compares the file with the stage, not with the parent's frame | Accepted: Kit's assembler compares layers the same way |
| A fixed-base robot turned at its root: the Franka's root joint anchors its base to the world, and could pull it back to the file's orientation when physics starts | Open until step 11: `test_15_16` steps the turned Franka and checks it still stands (P2). If it doesn't, the turn reaches into the root joint's frame too, a design change for the maintainer |
| R3's hull for a fisheye camera approximates its curved projection | Accepted: as the rectangle did; Isaac Sim's cameras are pinhole by default |
| R3 drops a box an agent relied on, for a prim whose world box reaches the frame's corner only through its rectangle | Accepted: that prim wasn't on the image |
| R4's warning on every capture while the user keeps lighting `off` on purpose | Accepted: one line, which says why the prims are black |
| R2 changes `rot` in recordings compared across releases | Accepted: the old value was wrong; CHANGELOG says so |
| R7's PhysX default is a constant the probe measured on Isaac Sim 6.2's PhysX (dynamic friction 0.5, restitution 0), the static one taken as 0.5; another PhysX could differ | Accepted: `test_15_02b` compares bodies the tool gave one value with controls that had none, on each run of the suites, so a difference fails it (P1) |
| R7 writes all three values into `<prim name>_PhysMat`, which prims of one name share: two Frankas, `friction=1.0` on `/World/Franka_1/panda_leftfinger`, then `restitution=0.2` on `/World/Franka_2/panda_leftfinger`, and the second writes Franka_2's old friction over Franka_1's 1.0. Cloned environments, as Isaac Lab makes them, hit it (P5) | Accepted for now (Q9's A): a CHANGELOG sentence, and a follow-up issue to name the material after the prim's whole path |
| R8: a Kit app whose `IApp` lacks a getter, or one that raises | Accepted: each fact reads `unknown` on its own, and the others still come |
| R7 on a stage of several physics scenes: the default material is read from the first | Accepted: one scene is the usual case, and which scene owns a body is PhysX's to say |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, read only, 2026-11-01, on `264f8fa`. **Verdict:** needs-answers: no
blocker or major, six minors, Q1 to Q8 unanswered and Q9 new. **Now:** P1 to P6 fixed, Q8 widened, Q9 added and
improvements 1 to 4 taken, in the commit after `264f8fa`; R8 and Q10, which the maintainer added after the round,
are in the same commit, for round 2.

Checked and holding: R7's probe (frictions 0.5, 0, 0.9, 0; rebound 0.789) and R3's boxes and pixel counts read as the
plan says; K1, K2 and K5 match the installed code; Kit's assembler re-resolves only paths it stored itself.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | `test_15_02b` gives each bare box restitution alone, so after the fix it measures the constants the handler wrote, not PhysX's default. On a Kit whose PhysX defaults to static friction 0.6, the test passes and the tool takes a bare body from 0.6 to 0.5 | fixed: each body is compared with a control that has no material and no call, on the same floor and slopes, and no constant is asserted (Tests; Design R7, step 3; Risks) |
| P2 | minor | The Risks row said `test_15_16` checks a turned fixed-base robot live; that test only checks the base's refusal and the hand's push. The Franka's world-anchored root joint could pull its base back to the file's orientation, and the test would still pass | fixed: `test_15_16` steps the turned Franka and checks it stays tallest along the up axis, its base link turned as created, within 1°; the Risks row is open until that runs |
| P3 | minor | "A prim whose ops already hold `xformOp:rotateX:unitsResolve` gets no second one" is wrong: `create_robot` refuses an existing prim, so the op can only come from the file's root, and the file-to-stage turn is still owed. A Z-up robot saved into a Y-up file (root op -90), given to a Z-up stage, would lie on its side | fixed: the stage's layer writes the sum into that op, its order unchanged, and the answer reports the turn added (Design R6; a `test_robot_handler.py` case) |
| P4 | minor | `UsdGeom.Xformable` appends the op after a trailing inverse op, where Kit keeps the inverse op last; a root with a pivot pair would land offset by Rx·p - p from where Kit puts it | fixed: the op goes before the first inverse op, else last, as `xform.py`'s `_before(order, _is_inverse)` places one; a pivot case in `test_robot_handler.py`; "keeps the op last" is now "keeps the op where it was" |
| P5 | minor | R7 writes all three values plus Q8's copy into `<prim name>_PhysMat`, which prims of one name share: a call on one prim resets values a call on a same-named prim set, beyond what the Out-of-scope row covered | fixed: a Risks row with the two-Franka case, a CHANGELOG sentence, and Q9 (keep the name now, give each prim its own in a follow-up) |
| P6 | minor | Docs that still describe the old behaviour: `docs/ARCHITECTURE.md`'s core list and Robot System bullet, `plugin/skills/scene/SKILL.md:48`, `README.md:256`; optionally `new_scene`'s reason for a Z-up stage | fixed: each in Docs, `new_scene`'s too |

**Refuted:**

- Q8's copy changing a shared material such as Rubber: it copies into the tool's own material; the shared one is
  never written.
- A material on a referenced layer: composed reads and `HasAuthoredValue` work across references, and the binding is
  written in the edit target.
- A binding with a purpose: `ComputeBoundMaterial("physics")` falls back to an all-purpose binding, and an ancestor's
  physics binding beats the prim's own all-purpose one, as PhysX applies it.
- A second turn from Kit's assembler: `stage_opened` resolves only paths saved in `customLayerData`,
  `prim_copy_callback` only paths registered from a drop; `create_robot` adds neither. `test_27b` still checks it.
- The tool contract: `tools/golden.py` strips descriptions; `mcp-tools.json` stays; no one-way door.
- The protocol: the new answer fields are additive; `PROTOCOL` moves only when the sides stop understanding each other.
- The writing rules: clean.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 to Q8 | Decisions for the maintainer | The reviewer agrees with each: Q1 A, Q2 yes, Q3 A, Q4 A with P3 and P4 fixed, Q5 A (the probe shows Isaac Sim 6.2's fallback up axis is Y), Q6 A, Q7 A with its CHANGELOG sentence in bold (done). Q8 A, copying from the physics scene's default material too when the values come from it (taken into Q8) | open |
| Q9 | P5: the shared `<prim name>_PhysMat` that R7 widens | A now, B in a follow-up issue | open |

**Improvements:**

1. `has_scene_lights` only in mode `stage`, the one mode whose warning reads it, which spares a whole-stage traversal
   on Kit's main thread for every other capture: taken (Design R4).
2. `start_from` and `PhysxMaterialAPI` on usd-core, which has no `PhysxSchema`: taken. The copy reads the composed
   `apiSchemas` list op, applies by name with `AddAppliedSchema`, and copies attributes by name and type (U5, Design
   R7).
3. The other robots' up axes: taken. All ten of `ROBOT_ASSETS` author `upAxis = "Z"` and `metersPerUnit = 1`, and
   none has a pivot or an inverse op on its root (U6), so the docs' "each is turned on a Y-up stage" holds.
4. The base commit in Tests: taken, `3b2b0cf`.

### Round 2

**How:** one fresh reviewer, Claude Opus, read only, 2026-11-01, on `cb9ef59`: R8 and round 1's fixes. **Verdict:**
approved: no blocker or major, three minors; no further round. **Now:** P7 to P9 fixed and improvements 1 to 5
taken, in the commit after `cb9ef59`. Q1 to Q10 wait on the maintainer.

| # | Sev | Finding | Status |
|---|---|---|---|
| P7 | minor | In P3's case the answer names a value the op doesn't hold: a Y-up file with the op at -90, given to a Z-up stage, is answered `= 90` while the op reads 0. An agent checking with `get_prim_properties` might "fix" it with `rotation=[90, 0, 0]` and lay the robot down | fixed: `up_axis_turn` carries the turn added and the op's value after it, and the line names both, "+90° about X, added to xformOp:rotateX:unitsResolve, which now reads 0"; a `test_tools.py` case (Design R6) |
| P8 | minor | Only the skill kept the fallback: the server's instructions and `docs/AI_GUIDE.md` lose "ask the user". Cursor with server 0.4.0 and extension 0.3.0 would report `kit_app = unknown`, where today the agent asks | fixed: both say "(ask the user for any that reads unknown)", and `tests/test_bug_reports.py` checks it (Design R8) |
| P9 | minor | CHANGELOG's Added entry, "where it asked you for Help > About", describes a change between two unreleased states: #110's entry is also under Unreleased on `d59667a` | fixed: the clause is gone; the entry says what the fields are and that the assistant asks while they read `unknown` |

**Refuted:**

- `/health` unauthenticated: `core/http.py:180-185`'s refusal runs on every request before routing.
- `platform.platform()` naming the machine: it never uses the node name (CPython 3.12, `platform.py:1220-1290`).
- Reading the facts at start-up: nothing changes while Kit runs, and a reload runs `on_startup` again.
- One getter hiding the others: each has its own try; K6 matches `_app.pyi:77, 85, 105, 127`.
- An older bridge crashing the server: it is read with `r.get`, as `test_tools.py:801` does today.
- P4's order: it holds (`xform.py:198, 358, 368`).
- P3's op: it keeps its place, and the refusal's `RemovePrim` removes it; only the message was wrong (P7).
- P1's slopes: tan 0.45 and 0.55 bracket 0.5.
- P2, P5 and P6: fixed as asked. Main's #110 texts read as the plan quotes them. The writing rules: clean.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q9 | The shared `<prim name>_PhysMat` | The reviewer agrees: A now, B as a follow-up best landed in the same release, and cheaper than it looked, since R7's step 1 reads from whatever `<name>_PhysMat` a prim is bound to and the next call moves it over (taken into Q9) | open |
| Q10 | `kit_os` | The reviewer agrees with A; on Linux it names the kernel and glibc, not the distribution, which is enough (taken into Q10) | open |

**Improvements:**

1. Keep R8's fields in `/health`, which is for people, with a `handle_health` unit test: taken (`tests/test_misc_handler.py`).
2. `docs/AI_GUIDE.md` in `test_bug_reports.py`'s versions test: taken.
3. The wire field `kit_app_name`, so `kit_app` means one thing, the answer's line: taken.
4. #110's files before step 9: taken, step 1b rebases onto `origin/main` at `d59667a` or later before any code, and
   the tests' "fails at" base moves with it.
5. The skill reports Kit's OS from `kit_os`, and this machine's only when it differs: taken.
