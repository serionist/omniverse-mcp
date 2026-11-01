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
four tools. The sixth, the log search, is the scenario's mistake. This plan fixes the five, on the server and in
the Kit extension, and corrects the six scenarios' Verify lines.

## Goal

When this is done, with this release's Kit extension:

| Row | Scenario | Tool | Real? | True when done | Shown by |
|---|---|---|---|---|---|
| R1 | 20.6 | `compare_prims` | yes | From A's 0 faces, the faces delta has no percentage, where it said `+0%`. Each delta has its own sign, where a vertex drop beside a face rise read `+-5` | `test_tools.py` |
| R2 | 2.2 | `get_prim_properties` | yes | `rot` is the world rotation with scale and shear taken out: 2.2's 45° turn at scale 0.5 reads `0.9239, 0, 0.3827, 0`, where it read 84°. Recordings' `state.txt` and `get_scene_tree`'s file give the same `rot` | `test_formatter.py`; live `test_02_02`, `test_08c` |
| R3 | 26.2 | `capture_viewport` | yes | A prim whose outline doesn't reach the image gets no box, where one beside the view got a box at the frame's edge. A box is the outline's part on the image | `test_bounds.py`; live `test_12i`, `test_12g`, `test_26_02` |
| R4 | 23.6 | `capture_viewport`, `inspect_prim` (Q2) | yes | Lighting that leaves the scene unlit, mode `off` or `stage` with no scene lights, gives a warning even when the grid keeps the image from being all black (Q1) | `test_tools_camera.py`, `test_camera_handler.py`; live `test_12j`, `test_23_06` |
| R5 | 24.6 | `get_logs` | no | Expected behaviour. A script's exception, `print` and stderr come back in `execute_script`'s answer and never reach Kit's log; `carb.log_*` calls do. The scenario says so, and so do `get_logs`' description and `docs/TOOLS.md` (Q3) | live `test_24_06` |
| R6 | 10.1 | `create_robot` | yes | A robot whose file authors another up axis than the stage's stands upright on it, as Kit stands a dropped file. On a Y-up stage that is every robot in Isaac Sim's library, all Z-up. The answer says when it turned one (Q4 to Q7) | `test_robot.py`, `test_robot_handler.py`, `test_tools.py`; live `test_27b`, `test_10_01`, `test_15_16` |

Why: each answer misleads an agent that trusts it. A rotation is off by 39°, a prim seems on screen when it isn't, an
unlit capture comes with no word on the light, and a percentage is made up. A robot lies on its side and falls over
when the simulation plays.

| In scope | Out of scope |
|---|---|
| The five bugs, and `compare_prims`' signs, found reading R1's code | A robot file whose `metersPerUnit` isn't the stage's (Q6) |
| `inspect_prim`'s warning, which has R4's blind spot (Q2) | The extension's `face_reduction_pct` for A's 0 faces: it stays `0`, and the server, its only reader, ignores it then |
| The six scenarios' Verify lines: 2.2, 10.1, 20.6, 23.6, 24.6, 26.2 | Scenario 2.1's DistantLight, which points up on a Y-up stage: #103's (see The probe, R4) |
| Descriptions, `docs/TOOLS.md`, `CHANGELOG.md` | Scenario 24.5's `since_index`, which the tool doesn't take: #103's |
| | A whole-frame `is_black`, which stays as it is: the renderer warming up still needs it |

## What the code, the sources and the probe say

### The code, at `876caca`

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

### The sources

Read on disk in Isaac Sim 6.2's install:

| # | What | Where |
|---|---|---|
| K1 | Kit's metrics assembler resolves a referenced file whose `upAxis`, `metersPerUnit` or `kilogramsPerUnit` differs from the stage's, "applying ... corrections to transform operations on top-level divergent prims". For a Z-up file on a Y-up stage its test expects `xformOp:rotateX:unitsResolve` = -90; a units difference adds `xformOp:scale:unitsResolve` | `omni.usd.metrics.assembler-110.1.2`: `docs/README.md`; `core/tests/referenceTests.py:180-205` |
| K2 | In mode Auto (`/metricsAssembler/operationMode` 3) it runs from the POST_DO callbacks of Kit's `CreateReferenceCommand`, `CreatePayloadCommand`, `AddReferenceCommand` and `AddPayloadCommand`: a drag and drop. A plain `AddReference` never reaches it. It also offers `resolve_hierarchy(stage_id, path)` to scripts | `omni.usd.metrics.assembler.ui-110.1.3`: `metricsAssemblerManager.py:164-200`, `:344-402` |
| K3 | With the assembler off, `CreateReferenceCommand` turns a file of another up axis itself when `/exts/omni.usd/commands/rotateOnCreatingReference` is set: a matrix that cycles the axes, so +Z goes to +Y and +X to +Z. The asset's up axis is `UsdGeom.GetStageUpAxis` of the file's stage, so an unauthored one counts as USD's fallback, Y | `omni.usd-1.19.11`: `usd_commands.py:5833-5850` |
| K4 | `xform.py` keeps a `:unitsResolve` op where it is, most local, and adds no op after one | `core/xform.py:7`, `:195` |

### usd-core 26.11 (a scratch check, not kept)

| # | What it showed |
|---|---|
| U1 | Scenario 2.2's cube through `format_prim_block`: `rot = 0.7428, 0.0000, 0.6695, 0.0000`, 84.06°. `RemoveScaleShear().ExtractRotation()` and `Gf.Transform(m).GetRotation()` give `0.9239, 0, 0.3827, 0`, 45°. A cube turned (30, 45, 60) and scaled (1, 2, 3) under a parent turned (10, 20, 30) and scaled 2: `ExtractRotation` gives no rotation, `(1, 0, 0, 0)`; both others give the composed rotation (1e-12). A mirror, scale (-1, 1, 1), factors as a 180° rotation and scale (-1, -1, -1), both ways alike. A scale of 0 gives `(1, 0, 0, 0)` in all three |
| U2 | A layer's `upAxis` and `metersPerUnit` read from `layer.pseudoRoot.GetInfo(...)`, and `HasInfo` tells an unauthored one, whose fallback, `UsdGeom.GetFallbackUpAxis()`, is Y |
| U3 | Scenario 26.2's TestCube corners in front of the camera, projected by hand with the probe's camera (below), give the reported box `[597.5, 213.2, 640, 480]`. Their outline's left edge crosses y = 480 at x = 844, and the points where its edges cross the near plane lie far to the right, so no part of it lies on the 640 x 480 image |

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
`metersPerUnit = 1`.

| How the file was added | Ops on the robot's prim | Size x, y, z | Stands? |
|---|---|---|---|
| `create_robot("g1", position=[3, 0.74, 0])`, Y-up | `translate (3, 0.74, 0)`, `orient`, `scale`, the file's own | 0.496, 0.371, 1.323 | no |
| Kit's `CreateReferenceCommand`, Y-up | the same, then `xformOp:rotateX:unitsResolve` = -90, in the root layer. The stage gains a layer, `metrics:UnitsAdjust-...` | 0.496, 1.323, 0.371 | yes |
| A plain reference, then the assembler's `resolve_hierarchy` | the same op, in the root layer; no layer added | 0.496, 1.323, 0.371 | yes |
| `create_robot("franka")`, Y-up | `translate` | 0.335, 0.259, 1.115 | no |
| `create_robot("g1", position=[0, 0, 0.74])`, Z-up | `translate`, `orient`, `scale` | 0.496, 0.371, 1.323 | yes |

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

- **Extension:** `handle_capture` and `handle_camera_inspect` send `has_scene_lights` on every answer, not only a
  black one. `_has_scene_lights` walks the stage once, as it does for a black frame today.
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
Scenario 24.6 checks both halves.

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
and before `write_transform`, it adds `xformOp:rotateX:unitsResolve` with that value through `UsdGeom.Xformable`, in
the edit target's layer. That is the op Kit's metrics assembler writes on a drag and drop (K1, the probe), most local,
so:

- `position` and `rotation` stay in the stage's frame, in the file's own root ops outside the turn: `rotation=[0, 90,
  0]` on a Y-up stage turns the standing robot about Y.
- `set_prim_transform` later keeps the op where it is (K4), and so does Kit's own transform gizmo.
- A refusal from `write_transform` already removes what the call made, the op with it.
- A prim whose ops already hold `xformOp:rotateX:unitsResolve`, such as a file Kit resolved and saved, gets no second
  one, and its answer no turn.

The answer gains `up_axis_turn`: `{"file": "Z", "stage": "Y", "degrees": -90}`, or `null`. The server prints
`Turned upright: the file is Z-up and the stage Y-up (xformOp:rotateX:unitsResolve = -90, as Kit's metrics assembler
turns a dropped file)`. An older extension sends no field, and the server prints nothing.

Alternatives (Q4): Kit's `CreateReferenceCommand` or `AddReferenceCommand`, whose callbacks reach the assembler in
mode Auto, adds a layer to the user's stage (the probe) and does nothing in mode Warn or Disabled. Calling
`resolve_hierarchy` directly gives the same op in Isaac Sim, and scales a file of other units too. But it is Kit's C++,
testable only live, and absent where the assembler doesn't load. The op written here is the same op, in every Kit
app, and tested on usd-core.

### Older extensions

| Row | With an extension of 0.3.0 or older |
|---|---|
| R1 | Fixed: the server alone |
| R2, R3, R6 | As today; the server can't tell |
| R4 | `off` warns; `stage` with no lights doesn't |

`docs/TOOLS.md` says so in each section, and CHANGELOG names the extension install, as #82 did.

### Decisions for the maintainer

| Q | Question | Options | Recommendation |
|---|---|---|---|
| Q1 | R4: what finds the unlit scene? | **A.** The lighting: mode `off`, or `stage` with no scene lights. Certain of its cause, cheap, and without the segmentation. It misses a light that points away. **B.** The pixels: the median brightness of the segmentation's prim pixels at 5 or less (the probe: 0 when unlit, 152 or more when lit). It catches a light aimed away too, but needs `omni.syntheticdata`, and a scene of black materials would warn. **C.** Both | A: it is the case the check was made for, and its warning can name the fix with certainty |
| Q2 | R4: `inspect_prim` too? | Yes, through the same helper; or `capture_viewport` alone, as the issue's row says | Yes: the same blind spot, one helper, and `inspect_prim` already sends the lighting mode |
| Q3 | R5: what changes? | **A.** The scenario, and a sentence in `get_logs`' description and `docs/TOOLS.md`. **B.** Also, the bridge logs a script's exception to Kit's log as a warning, so `get_logs` finds it | A: the exception is already in the answer the agent reads, and B would put every failed experiment in the user's Kit log |
| Q4 | R6: how is the robot stood up? | **A.** The op Kit's assembler writes, written by the core. **B.** Kit's `resolve_hierarchy` where the assembler loads, A elsewhere | A (Design, R6) |
| Q5 | R6: a file that authors no `upAxis`? | **A.** Leave it as it is. **B.** Take USD's fallback, Y, as Kit's `CreateReferenceCommand` does (K3): on Isaac Sim's Z-up stages such a file is turned | A: a turn on a guess lays down a robot that stood. The answer says nothing then, as today |
| Q6 | R6: a file of other `metersPerUnit`? | **A.** Out of scope, a new issue. **B.** A line in the answer naming the two. **C.** Scale it too (`xformOp:scale:unitsResolve`), physics' values unscaled | A: no file in Isaac Sim's library differs, and C scales the geometry without its masses and drives |
| Q7 | R6: someone who stood a robot themselves, with `rotation=[-90, 0, 0]` on a Y-up stage, now gets it turned twice | **A.** CHANGELOG's Fixed entry says so, and to drop that rotation. **B.** Under Breaking changes | A: the schema doesn't change, and the answer's line names the turn |

## Compatibility

- **One-way doors:** none. No tool's name, schema or annotations change (`tests/fixtures/mcp-tools.json` stays). The
  wire protocol gains two answer fields, `has_scene_lights` on every capture and inspection, and `up_axis_turn`, and
  loses none.
- **What users notice:**
  - `rot` lines change for every scaled prim, in `get_prim_properties`, `get_scene_tree`'s file and recordings'
    `state.txt`.
  - Captures list fewer boxes: none for a prim beside the view, and smaller ones for a prim whose outline crosses a
    corner of the frame.
  - Unlit captures warn.
  - On a Y-up stage, every library robot, and any file authoring Z-up, now stands where it lay: its links' positions,
    its bounds and what it does when the simulation plays change. A robot already in a scene is left as it is.
    Q7 for someone who turned one themselves.
- **Kit apps:** R6's op is plain USD, so every Kit app gets it. It is the op Kit's assembler writes; whether the
  assembler, run on the stage later, leaves it alone is checked live (Risks).

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: the probe, R1 to R6, and this plan settled on it | `105-probe.out.txt` in the session's scratchpad |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | R1: the server's deltas | `tests/test_tools.py` |
| 3 | R2: `core/formatter.py` | `tests/test_formatter.py` |
| 4 | R3: `core/bounds.py` | `tests/test_bounds.py` |
| 5 | R4: `has_scene_lights` on every answer; the server's `_unlit_warning` for both tools | `tests/test_camera_handler.py`, `tests/test_tools_camera.py`, `tests/test_tools.py` |
| 6 | R6: `core/robot.py`'s `up_axis_turn`, `handle_create_robot`, the server's line | `tests/test_robot.py`, `tests/test_robot_handler.py`, `tests/test_tools.py` |
| 7 | Docs, and the six scenarios' Verify lines (Docs, below) | The gate's checks; `tests/test_contract.py` unchanged |
| 8 | The live tests below, run by the session on Isaac Sim 6.2 headless at 8212: the new and changed tests alone on a fresh Kit's Z-up stage and again on a Y-up one, then both suites whole | No failure beyond `main`'s on the same Kit |
| 9 | `finish-work`: the gate in full, `review-code` | |

## Tests

Each fix has a test that fails at `876caca`, named first.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_tools.py` | R1: A with 0 faces prints `faces: +4 (A has 0 faces)` and no `%`; a vertex drop beside a face rise prints `vertices: -5`, a vertex rise beside a face drop `vertices: +9`, a zero `+0`; the existing case's `faces: -60 (-60.0%)` stays. R6: an answer with `up_axis_turn` prints the turned line, one without it or with `null` doesn't |
| `tests/test_formatter.py` | R2: 2.2's cube gives `rot = 0.9239, 0.0000, 0.3827, 0.0000`; U1's cube under a scaled, turned parent gives the composed rotation; an unscaled turned prim reads as before; a prim scaled 0 gives `1.0000, 0.0000, 0.0000, 0.0000` and doesn't raise; a recording's frame (`format_frame_state`) gives the same `rot` |
| `tests/test_bounds.py` | R3: the probe's 26.2 TestCube, through the probe's camera and `project_in_front`, is None (a box `[597.4, 213.1, 640, 480]` at `876caca`); the same camera's SettleTest box, as the probe measured within 0.5 px; a triangle wholly beyond a frame's corner, whose rectangle reaches in, is None; a triangle across a corner is boxed by its part on the frame; an outline that touches only an edge is None; points inside the frame are as before. `test_an_outline_partly_off_screen_is_clamped_to_the_viewport` gives a box's four corners, where its two points stood for a box's rectangle; their segment alone, which no box projects to, gets a case of its own |
| `tests/test_camera_handler.py` | R4: `handle_capture` and `handle_camera_inspect` send `has_scene_lights`, true and false, with an image that isn't black |
| `tests/test_tools_camera.py` | R4: `off` warns, with `is_black` false and with `has_scene_lights` absent (an older extension); `stage` with `has_scene_lights` false warns, with it absent doesn't; `camera`, `Default` and `stage` with lights don't; an all-black image gives today's warning and not a second; `inspect_prim` warns once for `off` |
| `tests/test_robot.py` | R6: `up_axis_turn` for Z on Y (-90), Y on Z (+90), the same axis and an unauthored one (None), from layers made in memory |
| `tests/test_robot_handler.py` | R6: a file authoring Z-up, tall along its Z, on a Y-up stage: the prim's last op is `xformOp:rotateX:unitsResolve` = -90, its world box tallest along Y, its base at `position`; `rotation=[0, 90, 0]` turns it about the stage's Y; a Y-up file on a Z-up stage gets +90; the same axis and an unauthored file get no op; a refusal after the reference leaves no op and no prim; the answer's `up_axis_turn`; a later `set_transform` keeps the op last |
| `tests/test_contract.py` | Unchanged |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_integration.py` `test_08c_get_prim_properties_reads_a_scaled_prim_s_rotation` | Through the server (`call_tool`): 2.2's cube's `rot` |
| `test_12i_a_prim_beside_the_view_gets_no_screen_box` | 26.2's scene and eye, placed with `at()` as `test_12g` does: the side cube has no box and no segmentation pixels; the near cube's box is as the probe measured |
| `test_12g` | Unchanged: its prim across the camera's plane still runs off the right edge |
| `test_12j_an_unlit_capture_warns` | Through the server: `off`, and `stage` on a stage with no lights, warn in `capture_viewport` and `inspect_prim`; `camera` doesn't; the mode found is set back in the test's cleanup |
| `test_27b_a_robot_file_of_the_other_up_axis_stands` | A file the test writes, as `test_27` does, authoring the up axis the stage hasn't: it stands, tallest along the stage's up axis, with the op; then, where `omni.metrics.assembler.core` imports, `resolve_hierarchy` on it leaves one turn and the robot standing |
| `test_scenarios.py` `test_02_02` | Asserts the `rot` line, as scenario 2.2 now verifies |
| `test_10_01` | The G1's bounds are tallest along the up axis, on either |
| `test_15_16` | Unchanged; on a Y-up stage it now pushes a turned Franka, whose base the fixed joint still holds |
| `test_23_06` | Through the server: the `off` warning, the mode left as set |
| `test_24_06` | The raised sentinel isn't found; a `carb.log_error` sentinel is, at level error |
| `test_26_02` | Adds a cube beside the view: no box for it |

**What neither shows:** USD Composer, which isn't on this machine; Kit 107, unless the session has Isaac Sim 5.1 at
hand; a GUI viewport, since port 8211 is the maintainer's. Kit's assembler in mode Warn or Disabled is not tried: R6
doesn't go through it.

## Docs

- **`docs/TOOLS.md`:** each section below, with what an extension of 0.3.0 or older does.
- **The tools' descriptions,** the same sentences, in `src/omniverse_mcp/tools/`.
- **`test_project/scenarios.md`,** the six Verify lines: the table below.
- **`CHANGELOG.md`,** under Unreleased: below.
- **`AGENTS.md`'s Traps:** the "no default light" row's guard gains "and a warning for lighting that lights nothing"
  (R4). The file stays at 150 lines.

| Row | Description and `docs/TOOLS.md` |
|---|---|
| R1 | `compare_prims`: "with B minus A, and the change in faces as a percentage when A has faces" |
| R2 | `get_prim_properties`: its world rotation is `rot`, a quaternion `w, x, y, z`, with any scale taken out. `start_recording`'s state file and `get_scene_tree`'s file give the same line |
| R3 | `capture_viewport`'s boxes file: a box is the prim's world box where it lies on the image; a prim wholly outside the image has none, beside the view as behind the camera |
| R4 | `capture_viewport`, `inspect_prim`, `viewport_light`'s When to use: a warning for an all-black image, and for lighting that lights nothing (mode `off`, or `stage` with no scene lights) though Kit's grid still shows |
| R5 | `get_logs`: Q3's sentence |
| R6 | `create_robot`: a file whose `upAxis` isn't the stage's stands upright on it, turned about X by `xformOp:rotateX:unitsResolve` as Kit's metrics assembler turns a dropped file, and the answer says so; `position` and `rotation` stay in the stage's frame; Isaac Sim's robots are Z-up, so each is turned on a Y-up stage; a file that authors no `upAxis` is left as it is |

| Scenario | Its Verify line becomes |
|---|---|
| 2.2 | `get_prim_properties("/World/RedCube")` shows the three ops set, and `rot = 0.9239, 0.0000, 0.3827, 0.0000`: the 45° turn about Y as a quaternion `w, x, y, z`, the 0.5 scale taken out |
| 10.1 | Returns the prim path and joint list. The G1 stands: `get_prim_bounds("/World/G1")` is tallest, about 1.32, along the stage's up axis (`get_sim_state`); on a Y-up stage the answer says it was turned upright, its file being Z-up |
| 20.6 | Returns a/b stats and the deltas. TestCube is a Cube, not a mesh, so A has 0 faces: the faces delta has no percentage, and each delta has its own sign |
| 23.6 | `capture_viewport()` gives a `WARNING` that lighting mode `off` leaves the scene unlit though the grid shows, naming `viewport_light` |
| 24.6 | `execute_script("raise RuntimeError('log_test_error')")` answers the error with its traceback, and `get_logs(count=10, search="log_test_error")` finds nothing: a script's exception comes back in its answer, not in Kit's log. Then `execute_script("carb.log_error('log_test_logged')")`, and `get_logs(count=10, search="log_test_logged")` finds one entry at level error |
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
  Sim's robots are Z-up, and on a Y-up stage they lay on their side. The answer says when it turned one. A call that
  turned the robot itself, with `rotation=[-90, 0, 0]`, now turns it twice: drop that rotation. The fix is in the
  Kit extension (#105).
```

## Risks

| Risk | Status |
|---|---|
| Kit's assembler, run later on the stage (a user's "resolve", or its change listener), adds a second turn to a robot `create_robot` turned | Checked by `test_27b` where the assembler loads; if it does, the fix moves to Q4's B. Open until step 8 |
| A robot under a turned parent: the turn compares the file with the stage, not with the parent's frame | Accepted: Kit's assembler compares layers the same way |
| A fixed-base robot turned at its root: PhysX holds a fixed base where it starts, so the turn holds | Checked live by `test_15_16` on a Y-up stage |
| R3's hull for a fisheye camera approximates its curved projection | Accepted: as the rectangle did; Isaac Sim's cameras are pinhole by default |
| R3 drops a box an agent relied on, for a prim whose world box reaches the frame's corner only through its rectangle | Accepted: that prim wasn't on the image |
| R4's warning on every capture while the user keeps lighting `off` on purpose | Accepted: one line, which says why the prims are black |
| R2 changes `rot` in recordings compared across releases | Accepted: the old value was wrong; CHANGELOG says so |

## Plan review

Not reviewed yet.
