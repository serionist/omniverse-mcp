---
title: Make twelve tools do what their answers say
issue: "#82"
status: approved
approved_by: serionist
approved_at: 2026-10-31
---

# Make twelve tools do what their answers say

#82 lists twelve tools whose answer says success, or gives a hint, that doesn't match what they did: seven in its
body, five in the maintainer's comment. #83 made each description say what the code does today. This plan fixes the
code, and each description and its `docs/TOOLS.md` section move with it. One fix needs a design of its own:
`_apply_xform`, which writes every transform the bridge sets.

## Goal

When this is done, with this release's Kit extension:

| Row | Tool | True when done | Shown by |
|---|---|---|---|
| R1 | `delete_prim` | A prim it can't remove (another layer defines it, or a reference or payload on a prim above brings it) is refused, naming why, with nothing changed; a prim it deletes is gone | `test_deletion.py`, `test_scene_handler.py`; live `test_07b` |
| R2 | `set_camera`, `look_at_prim`, and `inspect_prim` (E4) | They aim in every Kit app: through Isaac Sim's `set_camera_view` where it loads, through the camera's own ops, in the layer that holds them, elsewhere; nothing is left in the stage's root layer; `look_at_prim` no longer wipes a camera's rotation | `test_camera_handler.py`, `test_xform.py`; live `test_12f` (the fallback forced), `test_11`, `test_12` |
| R3 | `set_camera` | A position equal to the target it aims at, the world origin when none is given, is an error. What the answer says without a target is left to #77's merged camera tool (Q2) | `test_tools.py` |
| R4 | `set_material` | `opacity=1` makes a material opaque again | `test_material.py`, `test_scene_handler.py`; scenario `12_04` |
| R5 | `dump_scene` | "Dumped N prims" and the file's header count the prim blocks written | `test_formatter.py`, `test_scene_handler.py`; scenario `08_01` |
| R6 | `start_recording` | A second start says to call `stop_recording`, not to pass `force=True` | `test_recording_handler.py`; scenario `11_04` |
| R7 | `set_prim_transform`, and `create_prim` and `create_robot`'s transform | Position, rotation and scale go into the prim's own ops; a pivot, any other op, a matrix op and `!resetXformStack!` stay | `test_xform.py`, `test_scene_handler.py`; live `test_08b` |
| R8 | `clone_prim` | With `offset`, copy n moves n times the offset from the source, its ops and placement kept; the first copy is left as copied | `test_scene_handler.py`; live `test_21b`, scenario `13_05` |
| R9 | `get_recording_frame` | The folder `start_recording` and `stop_recording` print, relative to the server's working folder, finds the frame | `test_tools.py` |
| R10 | `raycast` | The description takes a `direction` of any length but zero, as PhysX does (E6); the server scales it to a unit vector, and a zero one is an error (Q13) | `test_tools.py`; E6 |
| R11 | `get_scene_tree` | Text mode stops at `max_depth`, and a prim there that has children says how many | `test_formatter.py`, `test_scene_handler.py`; live `test_03b` |
| R12 | `look_at_prim`, `inspect_prim`, `raycast` | Distances are labelled stage units, not `m` | `test_tools.py` |

Why: each answers success, or a hint the agent can't follow, while the scene isn't what the answer says. An agent that
trusts the answer builds on a scene that isn't there.

| In scope | Out of scope |
|---|---|
| The twelve rows, and the extras found reading them (Q12): `raycast`'s `m`, `set_camera`'s target equal to its position, a rotation that isn't 3 or 4 numbers, the camera fallback's parent space, `!resetXformStack!` and centre of interest | Tool schema changes: names, types, defaults, bounds and hints stay (Compatibility; Q1, Q3) |
| One transform writer in the Kit-free core for `set_prim_transform`, `create_prim`, `create_robot`, `clone_prim` and the camera fallback | Deactivating a prim USD can't remove (Q4); animated transforms, which are refused (Q6) |
| Descriptions, `docs/TOOLS.md`, `CHANGELOG.md`, `docs/ARCHITECTURE.md`'s core list, `AGENTS.md`'s core list (the same line), the script skill's camera trap (Q11) | Isaac Sim's own `set_camera_view`, beyond checking what it did (Q7) |
| | The camera override 0.2.3's fallback left in a stage's root layer (E3, E4): left as it is, outranked by the session layer |
| | `capture_viewport`'s box for a prim behind the camera (E3): its own issue |

## What the code and the sources say

### The code, at `f26642c`

| Row | Where | What it does |
|---|---|---|
| R1 | `handlers/scene.py:331-346` | `stage.RemovePrim(prim_path)`, its result ignored; answers "Prim deleted" |
| R2 | `handlers/camera.py:492-508` | `set_camera`: `except (ImportError, Exception)` falls back to `_apply_xform(cam, position=...)`: a scene camera moves and keeps its old rotation, and loses any op `_apply_xform` doesn't know. Kit's own camera: an error, and an empty `xformOpOrder` left in the root layer (E3) |
| R2 | `handlers/camera.py:561-574` | `look_at_prim`: on `ImportError`, `ClearXformOpOrder()` and a translate op: a scene camera's rotation is wiped; Kit's own camera, the same error as `set_camera`'s (E3) |
| R2 | `handlers/camera.py:69-124`, `679-684` | `inspect_prim`'s fallback, `_set_camera_xform`, has the look-at's math, but writes the world matrix as the local transform (wrong under a moved parent), clears every op, writes into the edit target's layer, which the session layer outranks for Kit's own camera, so nothing moves (E4), and returns silently for a missing prim or `eye == target` |
| R3 | `handlers/camera.py:490`; server `tools/camera.py:215-220` | The handler aims at `[0, 0, 0]` and answers `target: None`; the server prints "looking at" only for a target given |
| R4 | `handlers/scene.py:401-403` | `enable_opacity` and `opacity_constant` are written only when `opacity < 1` |
| R5 | `handlers/scene.py:162`; `core/formatter.py:162` | The answer counts `stage.Traverse()`, the file's header `Usd.PrimRange(root)`: neither `max_depth` nor `filter_types` |
| R6 | `handlers/recording.py:28`, `94` | "Stop it first, or use force=True to override.": the route takes `force`, the tool doesn't |
| R7 | `handlers/_utils.py:262-336` | Reads translate, rotateXYZ, orient and scale ops, the last of each type winning: an inverse pivot is `TypeTranslate` and its `Get()` gives the pivot's own value (U6), so a pivot can be read as the position. `ClearXformOpOrder()` then drops every other op, a matrix op and `!resetXformStack!` among them. A rotation of another length is ignored |
| R7 | callers | `scene.py:275` (`set_prim_transform`), `:314` (`create_prim`), `:469` (`clone_prim`); `robot.py:99` (`create_robot`); `camera.py:506-508` (`set_camera`'s fallback) |
| R8 | `handlers/scene.py:459-469` | Reads the first `TypeTranslate` op (a pivot, if it comes first), or the origin; `_apply_xform(position=cur + offset * i)` for every copy but the first, and for a single copy too (`i = 0`: no move, its ops rewritten) |
| R9 | server `tools/recording.py:88`, `111`; handler `recording.py:389` | The server prints the session folder relative to its own working folder (`h.rel`); Kit joins `session_dir` to Kit's |
| R10 | server `tools/simulation.py:154`; handler `simulation.py:304` | `direction` goes as given to `raycast_closest(origin, unitDir, distance)` |
| R11 | `handlers/scene.py:49-58`, `106-116` | Text mode lists levels 0 to `max_depth`, then the next level's prims that have children, each as `children = N (truncated)`, and drops the rest; JSON mode puts the count on the prim at `max_depth` |
| R12 | server `tools/camera.py:250`, `307`; `tools/simulation.py:162` | `Distance: {d}m`, `dist={d}m`, and `raycast`'s `Distance: {d:.4f}m` |

### The sources

Read on disk in Isaac Sim 6.2's install, and through Context7 (OpenUSD):

| # | What | Where |
|---|---|---|
| K1 | `isaacsim.core.utils` is deprecated since Isaac Sim 6.0 (`extsDeprecated`), but `isaacsim.exp.base.kit` still loads it: on 6.2, `set_camera` and `look_at_prim` take Isaac's path today; a release that drops it would run the fallback | `apps/isaacsim.exp.base.kit:24`; the extension's `extension.toml` |
| K2 | `set_camera_view` is Kit's `ViewportCameraState`: `set_position_world`, then `set_target_world`, after making `omni:kit:centerOfInterest`. A target straight above or below (same x and y) gets a rotate op written by hand, which assumes Z up; with no active viewport it logs a warning and returns with nothing moved | `isaacsim/core/utils/viewports.py:37-110` |
| K3 | `ViewportCameraState` (`omni.kit.viewport.utility`, in every Kit app with a viewport, USD Composer's too) writes through `TransformPrimCommand` in the camera's parent space, and sets the centre of interest; it raises without a viewport | `omni.kit.viewport.utility-2.1.2`, `camera_state.py` |
| K4 | Kit's `DeletePrimsCommand` (destructive, its default) refuses an "ancestral" prim, one that a reference or payload on an ancestor brings (`omni.usd.check_ancestral`), and removes the prim's specs from every local layer; non-destructive, it deactivates | `omni.usd-1.19.11`: `usd_commands.py:1365`, `_impl/utils.py:984` |
| K5 | `raycast_closest`'s `unit_dir`: "Normalized direction of the ray" | `omni.physics-110.4.4`, `_physics.pyi:839` |
| K6 | `RemovePrim` removes the edit target's specs only, and "you probably want `UsdPrim::SetActive(false)`" | OpenUSD, `UsdStage::RemovePrim` |
| K7 | `XformCommonAPI`'s order is `[translate, translate:pivot, rotate (one of six Euler orders), scale, !invert!translate:pivot]`; it takes neither orient nor a matrix, so it can't set Kit's `[translate, orient, scale]` or a matrix-placed prim | OpenUSD, `UsdGeomXformCommonAPI` |
| K8 | `AddXformOp` fails for an op already in the order, and errors for an existing attribute of that name with another precision; `SetXformOpOrder(ops, resetXformStack)` reorders | OpenUSD, `UsdGeomXformable` |

Isaac Sim 5.1's USD (Kit 107) has `PrimCompositionQuery` too (`omni.usd.libs-1.0.1`'s `pxr/Usd`).

### On usd-core 26.11 (scratch probes, not kept)

| # | What it showed |
|---|---|
| U1 | The removal check below, on four prims: a root-layer `def` and a prim that references a file can go; a part of a referenced file (with a root-layer `over`) and a sublayer's `def` are refused, each naming why |
| U2 | `RemovePrim` returns `False` when the edit layer holds nothing at the path, and leaves the prim; it removes an `over` and returns `True` |
| U3 | `Gf.Transform` factors a scale-rotate-translate matrix and gives it back (1e-9); a new rotation keeps its scale and translation |
| U4 | For `rotateABC`, `Gf.Rotation.Decompose` with the axes reversed (C, B, A), the angles stored by axis as (x, y, z), gives the op's matrix back for all six orders (1e-5); `Rx * Ry * Rz` is a rotateXYZ op |
| U5 | `AddOrientOp(PrecisionDouble)` over a `quatf` attribute out of the order raises `Tf.ErrorException`: a new op must reuse an existing attribute's precision |
| U6 | `!invert!xformOp:translate:pivot` has `TypeTranslate`, and its `Get()` gives the pivot's own value |
| U7 | `SetXformOpOrder(ops, GetResetXformStack())` keeps `!resetXformStack!` |

### Live: E1 to E8

Measured before any code by `82-live-probe.sh`, which runs `82-live-probe.py`, both in the session's scratchpad, on a
fresh Isaac Sim 6.2.0 headless at port 8212 with `f26642c`'s extension (0.2.3), each camera case on a Y-up and a Z-up
stage. A first attempt hung Kit's renderer at E2's capture, later "Out of resource descriptors", an RTX hang of #54's
kind; the run on a fresh Kit went through with no step failed.

| # | What | What it showed | What it decides |
|---|---|---|---|
| E1 | The viewport camera, Kit's defaults | `/OmniverseKit_Persp`: `def` in the session layer, which holds its ops, `[translate (double), rotateXYZ (float), scale (float)]`, and `omni:kit:centerOfInterest`; the root layer holds an empty `over` of it. `isaacsim.core.utils.viewports` imports. Kit's prim defaults: `[translate, orient, scale]`, double, rotation order ZYX | The fallback writes into the camera's own ops, in the session layer; ops the writer adds keep today's kinds and precisions, so `create_prim`'s output doesn't change |
| E2 | Isaac's path, `set_camera` and `look_at_prim` | Aimed exactly (0.000 degrees off), the ops kept as `[translate, rotateXYZ, scale]`, written into the session layer with the centre of interest, the root layer untouched. The target's box in a capture and the red target in the viewport's own frame sat within 0.007 of the centre | What the fallback must match, and where it must write |
| E3 | The fallback forced, as 0.2.3 does it | Both tools answered an error, USD's `AddXformOp: 'xformOp:translate' already exists in xformOpOrder`: `ClearXformOpOrder` wrote an empty order into the root layer, which the session layer's order outranks, so the translate op was still in the composed order. The camera didn't move, and the root layer kept the empty `xformOpOrder` | R2 for Kit's own camera is an error and a camera override left in the user's root layer, not a move without aiming; the issue's "never aim" holds for a scene camera, which the root layer holds |
| E4 | A USD look-at (0.2.3's `_set_camera_xform`), then Kit's `ViewportCameraState` | `_set_camera_xform` "wrote" and nothing moved, then or 3 s later: its `xformOp:transform` and order went into the root layer, under the session layer's. `ViewportCameraState` aimed exactly, writing the session layer, and the viewport's own frame and a capture showed the target centred | The viewport follows the camera's composed transform; a write in a weaker layer is hidden. `inspect_prim`'s fallback is this same call, so outside Isaac Sim it captures every angle from where Kit's camera stood. The fallback writes in the layer that holds the camera's ops (Design); Q11's trap row is wrong in its reason |
| E5 | Straight along the up axis | Y-up: Isaac's call answered success with the camera at the origin, 64 degrees off the target, its centre of interest zero. Z-up: aimed, by its hand-written branch, but the centre of interest left at 42.4 for a distance of 7.5. The cause (round 1, P1): `set_target_world`'s `SetLookAt(...).GetInverse()` (`camera_state.py:174`) is singular there, so the inverse is FLT_MAX times identity, which `TransformPrimCommand` factors into a scale of about 3.4e38 with translate 0 | Q7: check after Isaac's call, its scale too, and put the camera's ops back before the USD look-at; set the centre of interest after either path |
| E6 | `raycast`, directions of length 1, 2 and 0.5 | The same hit and distance, 4.95, for all three; length 2 with `max_distance=3` missed, length 0.5 with 6 hit: PhysX scales the direction itself and reads `max_distance` along the ray. No log line | R10's wrong answer doesn't happen on Isaac Sim 6.2; the description's "a unit vector: PhysX takes it as given" is what's wrong (Q13) |
| E7 | `delete_prim`, and Kit's other layers after an isolate inspect | The session layer held `def`s only for Kit's four cameras and `over`s under `/Render`: nothing under `/World`. `/World/FromSub`, a sublayer's: "Prim deleted", and it stayed defined. `/World/Ref`, referencing a file: gone. `/World/Ref/Link`'s own result is hidden, since the probe deleted `/World/Ref` after it; U1 and U2 cover it, and live `test_07b` checks it | R1 reproduced; the check refuses nothing under `/World` on the session layer's account |
| E8 | `set_material` 0.5, then 1 | After `opacity=1`: `enable_opacity` still true, `opacity_constant` still 0.5 | R4 reproduced |

Found on the way, outside #82: E3's capture, with the camera facing away, gave the target a box (`core/bounds.py`'s
`screen_box` reads no depth, so a prim behind the camera is mirrored into the image). Its own issue.

## Design

### The transform writer (R7, R8, and R2's fallback)

`_apply_xform` and `_validate_vec3` go. A Kit-free `ovmcp/core/xform.py`, tested on usd-core, writes every transform the
bridge sets:

- `set_local_transform(prim, position=None, rotation=None, scale=None, layer=None)`: writes into `layer`, the edit
  target's when `None`; `ValueError` with the reason, before anything is written.
- `position_of(prim)`: what `position` means for that prim, for `clone_prim`'s offset.
- `look_at(eye, target, up_axis)`, `aim(camera, eye, target)` and `aim_error(camera, eye, target)`, for the camera (R2).

**What it writes into.** Each part has its own ops, found by name among the prim's ordered ops. An op with a suffix of
its own (a pivot, `xformOp:rotateZ:spin`, Kit's metrics assembler's `:unitsResolve` ops) or an inverse op is another
op, kept as it is and where it is.

| Part | Its ops | When the prim has none |
|---|---|---|
| position | `xformOp:translate` | the prim's `xformOp:transform`, if it has one (below); else a translate op (double) first in the order: outermost, so it places the prim in the parent's space |
| rotation | every unsuffixed rotate op: orient, any of the six Euler orders, rotateX, Y or Z | the prim's `xformOp:transform`, if it has one; else rotateXYZ (float) for Euler angles, orient (double) for a quaternion: before the scale op, else before the first inverse op, else last |
| scale | `xformOp:scale` | the prim's `xformOp:transform`, if it has one; else a scale op (float) before the first inverse op, else last |

Those places are `XformCommonAPI`'s order (K7) and Kit's `[translate, orient, scale]`, so a prim with no ops gets the
ops today's code gives it, and a pivot pair stays around the rotation and scale. An op added never goes after a
`:unitsResolve` op, which stays most local, as `TransformPrimCommand` places them (`usd_commands.py:2210-2236`). The
kinds and precisions of ops it adds are today's, not Kit's prim defaults (orient, double; E1), so `create_prim`'s output
doesn't change.

**A value in the op's own kind and precision** (Q5):

- position and scale: a vector in the op's precision, half, float or double.
- rotation: Euler angles `[rx, ry, rz]` (rotateXYZ's meaning, as the tool says) or a quaternion `[w, x, y, z]`,
  normalised.
  - **Into an op of the same kind,** as given: Euler angles into rotateXYZ, the quaternion into orient. A round trip
    through `Gf.Rotation` would store `[0, 120, 0]` as about `[180, 60, 180]` (round 1, P3).
  - **Across kinds,** converted through `Gf.Rotation`: an orient op takes the quaternion, an Euler op the angles for
    its order (U4).
  - **Kit's triple:** three unsuffixed single-axis ops on three different axes, as `TransformPrimCommand` writes them
    (`[rotateZ, rotateY, rotateX]`, `usd_commands.py:2350-2364`), take the rotation decomposed into their axes, in
    their order (Q15).
  - **Any other rotation ops:** a single-axis op alone can't hold any rotation, and any other set of unsuffixed rotate
    ops would compose with whatever is written: all of them are replaced together by one rotateXYZ or orient, in the
    first one's place.
- An op added where an attribute of its name already exists out of the order reuses that attribute's precision (U5).

**A prim with a matrix op.** When the prim has an unsuffixed `xformOp:transform`, as converters often write, a part
with no op of its own goes into that matrix, rather than a new op outside it, as `TransformPrimCommand` does: the
position by `SetTranslateOnly`, exactly; a rotation or a scale through `Gf.Transform`, which factors the matrix and
builds it again with the new part (U3). A matrix `Gf.Transform` can't factor, a singular one such as a scale of 0
leaves, refuses a rotation or a scale, saying so, where its clamped factors would lose the rotation and answer success
(round 1, P9); its position can still be set.

**Kept:** every other op, its value and its place; `!resetXformStack!` (U7); and, as `ClearXformOpOrder` leaves them
today, the attributes of ops it replaced, out of the order.

**Refused,** with nothing written:

- a position, or a scale list, that isn't 3 numbers; a rotation that isn't 3 or 4 numbers (ignored today); a zero
  quaternion. `check_transform(position, rotation, scale)` makes these checks alone, before any prim is touched;
- an op it would write that has time samples, by the layer that holds them (Q6). Samples in the written layer or a
  stronger one hide the default value it writes, so the answer would say success while nothing shows. Samples only in
  weaker layers, such as an animated asset's, are overridden by that default, which freezes the animation;
- a write another layer would hide: one of the stage's own layers stronger than the layer written, such as the session
  layer, holds an opinion on the prim's `xformOpOrder` or on an op it would write. The error names that layer. 0.2.3's
  writes into the root layer under the session layer's opinions failed with a USD error or moved nothing (E3, E4), and
  `set_prim_transform` on Kit's own camera now says why instead (Q14);
- an instance proxy, as inside an instance, naming the instance, where USD would raise its own error.

A refusal names a layer by its file path, and the session layer as "Kit's session layer" (compared with
`stage.GetSessionLayer()`), never by an anonymous layer's identifier.

**What "position" means with a pivot:** the translate op's value, which Kit's Property panel shows as Translate and
`XformCommonAPI.SetTranslate` sets; the prim turns and scales about its pivot. `docs/TOOLS.md` says so.

**`clone_prim` (R8).** Copy n of `count`, from 0, moves by n times `offset`: `position_of(copy) + n * offset`, through
`set_local_transform`, in the root layer, where `Sdf.CopySpec` put the copy: with a sublayer as the edit target, a move
there would be refused as hidden, with copies already made (round 1, P6). Copy 0, and a single copy, are left as
copied, as the description already says. A source whose position can't be written (an animated translate op) is
refused before anything is copied, as a taken target is today.

**The callers:** `handle_transform`, `handle_create_prim`, `handle_clone_prim` and `handle_create_robot` call the core
and answer its `ValueError` as an error.

- **`create_prim` and `create_robot`** run `check_transform` before `DefinePrim`, so a malformed value makes nothing.
  `create_robot("franka", rotation=[0, 90])` would otherwise make the prim, refuse, and refuse the retry as taken
  (round 1, P5).
- **A refusal found only after the prim exists,** such as an animated root op in the referenced file, removes what the
  call made (a prim it created, never one that was there) and says why. Built so: with the missing parents
  `DefinePrim` made for it, found before by `_first_missing` in `handlers/_utils.py`.
- **Built so,** the entry points: `check_transform` checks the values and gives `Parts`; `write_transform(prim, parts,
  layer)` writes them and `check_writable` plans without writing; `set_local_transform` is the two in one. `clone_prim`
  also takes its copies away when one copy's move is refused after the source passed, since a copy composes apart from
  its source ("Nothing was copied"), where the plan checked only the source.

| Alternative | Why not |
|---|---|
| `XformCommonAPI` | Refuses orient and matrices (K7): Kit's own `[translate, orient, scale]` and matrix-placed assets are the prims that broke |
| Rewrite as translate, orient and scale, factoring a matrix first | Keeps the placement, but still drops the ops #82 asks to keep, a matrix and a pivot pair among them |
| Replace the rotate op by the kind given (Q5's other answer) | Reads back as written, but swaps an asset's orient for rotateXYZ, and back again at the next quaternion, leaving the old attribute each time |
| Kit's `TransformPrimCommand` | Kit-bound, so tested only live, and an undo entry for every call, where the bridge's other writes make none |

### The camera (R2, R3)

One helper in `handlers/camera.py`, `_aim_camera(camera_path, eye, target)`, which returns why it couldn't aim, or
`None`. `set_camera`, `look_at_prim` and `inspect_prim` call it; `_set_camera_xform` goes, its math moved to the core.

0. **The same point:** `eye` equal to `target` is refused before any write, where Isaac's same-x-and-y branch would
   turn the camera first (round 1, P7).
1. **Isaac Sim's `set_camera_view`,** when `isaacsim.core.utils.viewports` imports: Isaac Sim's path, as today (K1,
   K2, E2). The camera's ops and their values are taken first, as a snapshot.
2. **The check:** `aim_error` compares the camera's world position with `eye` (within 1e-4 of the eye-to-target
   distance plus 1e-6 of the eye's distance from the origin, so a float translate far out doesn't fail it), its -Z axis
   with the direction to `target` (within 0.5 degrees), and its world scale with the snapshot's. When it is off,
   because there is no Isaac Sim or because Isaac's call left the camera unaimed, the snapshot is put back and the USD
   look-at follows (Q7). Isaac's call leaves it off straight down a Y-up stage's up axis, at the origin with a scale of
   about 3.4e38 (E5); `inspect_prim`'s top and bottom may leave a near-singular scale of about 1.7e6 with the direction
   right, which only the scale shows (round 1, P1); and with no viewport it moves nothing (K2).
3. **The USD look-at,** `aim`: `look_at(eye, target, up_axis)`, `_set_camera_xform`'s math (right = world up x back;
   the X axis when looking straight along the up axis; built so: within 2.5 degrees of the up axis, minus the front
   axis stands in for the up, which keeps the matrix orthonormal, where the old right vector was skewed near
   vertical, and keeps the view continuous with an aim from the front: the X axis on a Y-up stage, -X on a Z-up one),
   taken into the camera's parent space, or none for a camera
   with `!resetXformStack!`, and written by `set_local_transform` as a position and a quaternion into the camera's own
   ops: Kit's camera keeps `[translate, rotateXYZ, scale]`, as Kit's own call keeps it (E1, E2).
   - **The layer:** the strongest of the stage's own layers that holds an opinion on the camera's `xformOpOrder`, when
     it outranks the edit target; otherwise the edit target. For Kit's own cameras that is the session layer, where
     Kit's own call writes (E2, E4), so the viewport follows and nothing lands in the user's root layer. A write in the
     root layer is outranked there and moves nothing (E3, E4).
4. **The centre of interest,** after either path: `omni:kit:centerOfInterest`, when the camera has it, is set to the
   target in the camera's space, in the same layer, as `ViewportCameraState` does (K3), so the user's next orbit turns
   about the target. Isaac's own branch for a Z-up camera looking straight down left it at 42.4 for a distance of 7.5
   (E5).
5. **The check again:** still off is an error naming why, such as an animated op.

Why a USD write is enough: the viewport renders the camera's composed transform. `ViewportCameraState`'s write, a
`TransformPrimCommand` into the session layer, moved the viewport's own frame onto the target on both axes (E4), and
0.2.3's writes moved nothing only because the root layer is outranked by the session layer's opinions on Kit's camera
(E3, E4). Live `test_12f` shows the fallback's own write moving the viewport before the PR; should it not, the
fallback calls `ViewportCameraState` where it loads.

- **`set_camera`:** `except (ImportError, Exception)` goes: an exception in Isaac's call is an error, where 0.2.3 fell
  back to `_apply_xform`.
- **R3, in the server:** a `position` equal to the target it aims at, the origin when none is given, is refused before
  any request; it holds with any extension, and `_aim_camera` and `look_at` refuse the same point too. The answer
  without a target stays as it is: #77's merged camera tool settles what it says (Q2).
- **`look_at_prim`:** its own fallback goes.
- **`inspect_prim`:** an angle whose aim fails says why, as an angle whose capture fails does. Its fallback in 0.2.3
  is the `_set_camera_xform` call that moved nothing on Kit's camera in E4, so outside Isaac Sim every angle showed the
  same view; live `test_12f` captures an angle with the fallback forced.

| Alternative | Why not |
|---|---|
| `ViewportCameraState` as the fallback (K3, what Isaac's call uses; it aimed exactly, E4) | Kit-bound, so tested only live; it raises without a viewport, and its `SetLookAt` breaks down straight down a Y-up stage's up axis, where Isaac's call through it put the camera at the origin (E5) |
| `_set_camera_xform` as it is, as the issue names it | Writes into the edit target's layer, which moved nothing on Kit's own camera (E4); writes a world matrix as the local transform, wrong under a moved parent; clears the camera's ops. Its math stays, in the core |
| Trust `set_camera_view` | E5 and K2's no-viewport case answer success with the camera unaimed |

### `delete_prim` (R1)

A Kit-free check before the removal, `ovmcp/core/deletion.py`: `why_kept(prim, edit_layer)`, what would still define
the prim after `RemovePrim` in the edit target's layer, or `None`. It reads `Usd.PrimCompositionQuery`'s arcs (U1):

| Arc | Defines the prim after the removal when | The refusal names |
|---|---|---|
| root (the stage's own layers) | another layer of the stack, a sublayer or the session layer, defines it (`def` or `class`) | that layer |
| ancestral: a reference, payload, inherit, specialize or variant on a prim above | its target defines it | the prim above, and the arc's kind |
| on the prim itself, authored in the edit layer | never: it goes with the prim's spec | |
| on the prim itself, authored in another layer | its target defines it | that layer |

- An instance proxy is refused as inside an instance, naming the instance prim, which `set_visibility` can hide
  whole: it can't author on the proxy itself (`core/isolation.py` says so) (round 1, P11).
- A refusal changes nothing: `/World/Robot/Link is not deleted: it comes through a reference on /World/Robot
  (bot.usda). set_visibility hides it.` A layer is named by its file path, the session layer as "Kit's session layer".
- Then `RemovePrim`. A `False`, or the prim still defined after it, is an error too, as a defence.
- The answer to a delete carries `checked: true`, which tells the server the extension made the check (P14).

Kit's own delete (K4) refuses an ancestral prim and removes the prim's specs from every local layer. This refuses both,
since a sublayer is another file the user may not mean to edit, and says which. In Kit the session layer holds `def`s
only for Kit's own cameras, and nothing under `/World` after an `isolate` inspect (E7), so the session layer makes the
check refuse no prim under `/World`. A Kit camera is refused, since the root layer doesn't define it.

| Alternative (Q4) | Why not |
|---|---|
| Deactivate (`SetActive(False)`) what USD can't remove, as K6 advises, and say so | The prim always leaves the stage, but under the name delete, and stays in the file; its own issue if agents need it |
| Remove from every local layer, as Kit's delete does | Edits sublayers, other files |
| Check after the removal only | Honest, but removes the edit layer's overrides, such as a `set_prim_transform`'s, before saying the prim stayed (U2) |

### The others

| Row | End | Change |
|---|---|---|
| R4 | `core/material.py`: `set_surface(shader, colour, opacity, roughness, metallic)`; server `tools/scene.py` | Writes all five on every call: `enable_opacity` is `opacity < 1`, `opacity_constant` always (Q3). The server's answer prints `opacity` on every call, where it left it out at 1, so a recolour that makes a material opaque says so |
| R5 | `core/formatter.py` | `format_scene_dump` walks first and returns the text with the number of prim blocks; the header's `prim_count` and `SCENE` line give that number; the handler answers it |
| R6 | `handlers/recording.py` | `A recording is already running: call stop_recording first`; while one is starting, `A recording is starting: wait for its answer, then call stop_recording`. The route keeps `force`, unadvertised (Q1) |
| R9 | server `tools/recording.py` | A `session_dir` with no anchor in either Windows' or POSIX's form (`PureWindowsPath(s).anchor == ""`) is joined to the server's working folder, the reverse of `h.rel`; an absolute one, in either form, goes as given, so a Kit app on another OS still gets its own paths (Q8) |
| R10 | server `tools/simulation.py` | `direction` divided by its length; a zero one is a `ToolError` before any request. Isaac Sim 6.2's PhysX already scales it (E6); the server's scaling makes the description true on any PhysX build, and the zero case an error of ours (Q13) |
| R11 | `core/formatter.py`: `format_scene_tree(stage, root, max_depth, include_properties)` | Lists levels 0 to `max_depth`; a prim at `max_depth` with children gets `children = N (truncated)` on its own block, as JSON mode does. The handler's text branch calls it, and `prim_count` stays the prims listed |
| R12 | server `tools/camera.py`, `tools/simulation.py` | One spelling everywhere: `Distance: 5.0 stage units`, `dist=2.5 stage units`, `raycast`'s `Distance: 4.9500 stage units` |

### Older extensions

R3, R9, R10 and R12 are the server's: they hold with any extension. The other eight need this release's extension; an
older one behaves as today. As #74, #80 and #84 did, `docs/TOOLS.md` says under each tool what an extension of 0.2.3 or
older does, each `CHANGELOG.md` line says the fix is in the Kit extension, with the install command, and
`get_sim_state`'s note already names the command whenever the versions differ (Q9).

`delete_prim` is the exception: it destroys work, and the plugin pins the server while the extension waits for
`extension install`, so a new server on a 0.2.3 extension would print "Deleted" for a prim that stays, under a
description that says such prims are refused (round 1, P14). An answer without `checked: true` gets one more line:
`This Kit extension, older than the server, answers deleted for a prim another layer keeps: check with get_scene_tree`.
The marker rather than a version compare, so a later server on an extension that has the check, though older, says
nothing wrong. The other tools don't warn per call (Q9).

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | `start_recording`'s refusal: expose a `force` parameter (a schema change, a one-way door), or say `call stop_recording first`? | The message: `stop_recording` ends the recording and writes its metadata, where `force` drops it unwritten; the route keeps `force` for HTTP callers | As recommended (2026-10-31) |
| Q2 | `set_camera` without a target: aim at the origin and say so, or keep the camera's direction and only move it? | Say so: the description has said "the origin when omitted" since #83, and the other would change what a call does for anyone who relies on it | Dropped (2026-10-31): the answer without a target stays as it is; #77's merged camera tool settles it |
| Q3 | `set_material` without `opacity`: opaque, as `roughness` and `metallic` take their defaults on every call, or keep the material's opacity (a `None` default: a schema change)? | Opaque: one rule for the three values and no contract change; the description says a recolour sets all three | As recommended (2026-10-31) |
| Q4 | `delete_prim` on a prim USD can't remove: refuse, naming why, with nothing changed; deactivate it instead; or remove it from every local layer, as Kit's delete does? | Refuse: the call does what its name says or nothing, and the error names `set_visibility` | As recommended (2026-10-31) |
| Q5 | `set_prim_transform`'s rotation into a rotate op of another kind: convert it into that op, or replace the op in its place by the kind given? | Convert: every op stays as authored, which is #82's point; `get_prim_properties` gives the world rotation as a quaternion either way | As recommended (2026-10-31) |
| Q6 | An op with time samples (restated in round 1, P4). Samples in the written layer or a stronger one hide the default value the tool writes; samples only in a weaker layer, such as an animated asset's, are overridden by it, which freezes the animation. Refuse both, saying which by layer, or write in the second case and say the animation is frozen? | Refuse both, with the reason by layer: success with nothing visible, or an animation silently stopped, is the kind of bug #82 is about | As recommended (2026-10-31) |
| Q7 | After Isaac Sim's `set_camera_view`, check that the camera aims at the target, and take the USD look-at when it doesn't? | Yes, the more so after E5: straight down a Y-up stage's up axis, Isaac's call answered success with the camera at the origin, 64 degrees off. It changes Isaac Sim's behaviour only where the camera was left unaimed | As recommended (2026-10-31) |
| Q8 | `get_recording_frame`: read a relative `session_dir` from the server's working folder, where Kit read it from its own? | Yes: it is the form `start_recording` and `stop_recording` print, and no tool writes a recording under Kit's folder | As recommended (2026-10-31) |
| Q9 | An older extension (restated in round 1, P14). `delete_prim`, which destroys work: one added line to its answer when the extension made no check ("this Kit extension, older than the server, answers deleted for a prim another layer keeps: check with get_scene_tree"). The other tools: no warning per call, as for #74 and #84, with `docs/TOOLS.md` and `CHANGELOG.md` saying which fixes need this release's extension? | Yes to both. A plugin update moves the server ahead of the extension, so a new description over an old `delete_prim` would say "refused" while the prim stays. The line keys on the answer's `checked` marker, not the handshake's version, so a later server on an older extension that has the check says nothing wrong. The other fixes are a few lines each, and `get_sim_state`'s note names the install command | As recommended (2026-10-31) |
| Q10 | One PR for the twelve rows, or the transforms and the camera (R2, R7, R8) apart from the rest? | One: the issue asks for it, the docs move once, and one live run covers all; the Steps keep the transform core in commits of its own, so a split stays possible | As recommended (2026-10-31) |
| Q11 | The script skill's trap row says neither a USD write nor `ViewportCameraState` moves the viewport camera reliably (from `8d684d6`, in March). E4: `ViewportCameraState` moved it exactly; a `UsdGeom.Xformable` write moved nothing because it lands in the edit target's layer, which the session layer, holding Kit's camera, outranks. Correct the row in this PR? | Yes, through `write-skill`: "a write in the stage's edit layer doesn't move Kit's viewport camera, whose ops the session layer holds: `await mcp.set_camera()` or `mcp.look_at()`, or `ViewportCameraState`" | As recommended (2026-10-31) |
| Q12 | The extras found reading the rows: `raycast`'s `m`, `set_camera`'s target equal to its position, a rotation that isn't 3 or 4 numbers, the camera fallback's parent space and `!resetXformStack!`, the centre of interest after either path (E5). In this PR? | Yes: the same kind of bug, a few lines each, each with its test | As recommended (2026-10-31) |
| Q13 | `raycast` (R10): Isaac Sim 6.2's PhysX scales the direction itself, so today's answers are right (E6), and only the description, "a unit vector: PhysX takes it as given", is wrong. Keep the server's scaling, or fix only the description? | Keep it, with the description fixed: two lines that make "any length but zero" true on every PhysX build, Kit 107's untried among them, and a zero direction an error of ours, where E6 didn't try what PhysX does with it | As recommended (2026-10-31) |
| Q14 | Write Kit's own cameras in the session layer, where Kit writes them (E2, E4), and refuse any transform write a stronger layer of the stage would hide, naming it, such as `set_prim_transform` on Kit's camera, whose code, `_apply_xform`, failed there with a USD error (E3)? | Yes: a session-layer edit isn't saved with the file, as Kit's own camera moves aren't, and the refusal turns E3's error and E4's silent no-op into an answer that says why | As recommended (2026-10-31) |
| Q15 | A rotation into several unsuffixed single-axis rotate ops, such as the `[rotateZ, rotateY, rotateX]` Kit's `TransformPrimCommand` writes (round 1, P2): write the rotation decomposed into Kit's triple, or replace the three together with one rotateXYZ? | Kit's triple: every op stays as authored, as Q5 has it for a single rotate op | As recommended (2026-10-31) |

## Compatibility

No one-way door moves, with Q1 and Q3 as recommended.

| Door | Effect |
|---|---|
| Tool names, schemas, annotations | None: only descriptions change, which `tools/golden.py` strips; `tests/fixtures/mcp-tools.json` stays |
| Wire protocol | Same paths and bodies; `PROTOCOL` stays 1. `/scene/dump`'s `prim_count` counts the blocks written; `/scene/delete`'s answer gains `checked: true`. `/scene/delete`, `/camera/*`, `/scene/transform`, `/scene/create`, `/scene/clone` and `/robot/create` can answer errors they didn't |
| The extension's id and settings | Unchanged |
| The output folder | The same files; `scene_dump.txt`'s header count means the blocks in it |

What users notice:

| Before | After |
|---|---|
| `delete_prim` answered "Deleted" for a prim that stayed, after removing the edit layer's overrides of it | Refused, naming why, with nothing changed |
| Outside Isaac Sim, `set_camera` and `look_at_prim` failed with a USD error on Kit's own camera and left an override of it in the root layer (E3), and moved a scene camera without aiming it, `look_at_prim` resetting its rotation; `inspect_prim` captured every angle from where Kit's camera stood (E4) | Aimed in every Kit app, Kit's own camera in the session layer, as Kit does |
| In Isaac Sim, straight down a Y-up stage's up axis, `set_camera` put the camera at the origin and answered success (E5) | Aimed |
| `set_prim_transform` on a prim whose ops a stronger layer holds, such as Kit's camera, failed with a USD error | Refused, naming the layer (Q14) |
| `set_camera` with a position equal to the point it looks at answered success with nothing to look at | An error |
| A material made see-through stayed so at `opacity=1` | Opaque; a call that leaves `opacity` out makes it opaque too (Q3) |
| "Dumped N prims" counted the stage | The prims written |
| A second `start_recording` said to pass `force=True` | Says to call `stop_recording` |
| `set_prim_transform`, `create_prim` and `create_robot` rewrote the ops as translate, rotate and scale, dropping a pivot, a matrix and `!resetXformStack!`, and could read a pivot as the position | Write into the prim's own ops and keep the rest; a rotation goes into the prim's rotate op in its kind (Q5); an animated op, a rotation that isn't 3 or 4 numbers and a zero quaternion are errors |
| `clone_prim`'s copies of a matrix-placed or pivoted source lost that placement, and a single copy's ops were rewritten | Each copy keeps its placement and moves by n times the offset; the first is left as copied |
| A relative `session_dir` was read from Kit's folder | From the server's, where the tools' paths are relative to (Q8) |
| `raycast`'s description asked for a unit vector, though Isaac Sim 6.2's PhysX takes any length (E6) | Any length; the server scales it; zero is an error (Q13) |
| `get_scene_tree`'s text listed part of the level after `max_depth` | Stops at `max_depth`, with each prim's count of children |
| Distances said `m` | Stage units |

- **Mixed releases:** a new server on an older extension gets R3, R9, R10 and R12, and the other eight behave as
  today, as `docs/TOOLS.md` says, `delete_prim`'s answer adding that the extension doesn't check (Q9);
  `uvx omniverse-mcp extension install`, then a restart of Kit, as `get_sim_state`'s note says. An older server on the new extension gets the eight extension fixes; its own text is as before.
- **Kit apps:** live on Isaac Sim 6.2 headless only. Kit 107 (Isaac Sim 5.x) and USD Composer are untried: the USD
  calls are in Kit 107's USD too, and the fallback is what such apps run.

## Steps

Each step builds and passes `uv run tools/gate.py quick`; the PR ends with `finish-work`.

| Step | What | Proven by |
|---|---|---|
| 0 | Done: E1 to E8, run by the session (`82-live-probe.sh`), and this plan settled on them | The probe's output, in Live: E1 to E8 |
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | The server's rows: R3, R9, R10, R12 | `tests/test_tools.py` |
| 3 | `core/xform.py` | `tests/test_xform.py` |
| 4 | The transforms through the core: `handle_transform`, `handle_create_prim`, `handle_clone_prim`, `handle_create_robot` (R7, R8). `_apply_xform` stays for `set_camera`'s fallback until step 5 (round 1, P12) | `tests/test_scene_handler.py` (new), `tests/test_robot_handler.py` (new) |
| 5 | The camera: `_aim_camera` for `set_camera`, `look_at_prim` and `inspect_prim` (R2); `_apply_xform` and `_validate_vec3` go | `tests/test_camera_handler.py` |
| 6 | `core/deletion.py` and `handle_delete_prim` (R1); `delete_prim`'s line for an older extension (Q9) | `tests/test_deletion.py`, `tests/test_scene_handler.py`, `tests/test_tools.py` |
| 7 | `core/formatter.py`: the tree's text and the dump's count, and their handlers (R5, R11) | `tests/test_formatter.py`, `tests/test_scene_handler.py` |
| 8 | `core/material.py`'s `set_surface` and the answer's opacity (R4); the recording refusals (R6) | `tests/test_material.py`, `tests/test_scene_handler.py`, `tests/test_tools.py`, `tests/test_recording_handler.py` |
| 9 | The live tests below | Run by the session on Isaac Sim 6.2 headless: `82-live.sh` in its scratchpad runs the new and changed integration tests alone on a fresh Kit, both suites whole, then the integration tests again on the Y-up stage the suites leave. The scenario checks run within the whole suites only, since they need its earlier phases (built so) |
| 10 | The docs | `tests/test_contract.py` unchanged; the gate's AGENTS.md and skill checks |
| 11 | `finish-work`: the gate in full, both live suites in full, `review-code` | No live failure beyond `main`'s on the same Kit |

## Tests

Each row's fix has a test that fails at `f26642c`, named first below.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_scene_handler.py` (new) | `handlers/scene.py` loaded from its file with Kit faked and `_utils.py` from its own, as `tests/test_camera_handler.py` and `tests/test_camera_feed.py` do, on a usd-core stage. R1: a part of a referenced file refused, its root-layer `over` kept, and a prim of the root layer deleted. R4: `opacity` 0.5 then 1 leaves `enable_opacity` false. R5: a subtree's dump counts its blocks. R7: a pivot stack keeps its pivot, and its position lands in the translate op; a matrix-only prim keeps its matrix op; `!resetXformStack!` stays; an animated op and a two-number rotation are errors; `create_prim` with a two-number rotation makes no prim (P5). R8: a matrix-placed and a pivoted source's copies sit at n times the offset, ops kept; with a sublayer as the edit target, the copies move in the root layer (P6). R11: text mode at `max_depth` 0 and 1 |
| `tests/test_robot_handler.py` (new) | `handlers/robot.py` loaded the same way: `create_robot` from a file places the robot through the core, and a malformed rotation makes no prim (P5) |
| `tests/test_camera_handler.py` | The harness has no `isaacsim`, so the fallback runs; its camera is defined in the stage's session layer with Kit's ops, as E1 found Kit's. R2: `set_camera` and `look_at_prim` leave the camera's -Z on the target within 0.5 degrees, written in the session layer, the root layer holding no spec of it (fail at `f26642c` with E3's `AddXformOp` error); `inspect_prim`'s angles too (unmoved at `f26642c`, E4); a scene camera under a moved parent; a fake `set_camera_view` that writes what Kit wrote in E5, translate 0 and a scale of FLT_MAX, is followed by the snapshot put back and the USD look-at, the scale 1 again (Q7, P1); a fake that aims right but leaves a scale of 1.7e6 is caught by the scale; the centre of interest after either path; a position equal to the target is refused with the camera unchanged and the fake never called (P7) |
| `tests/test_recording_handler.py` | R6: the refusal while one runs, and while one starts, names `stop_recording` and not `force` |
| `tests/test_tools.py` | R3: a target equal to the position, and `position=[0, 0, 0]` with no target, are errors with no request sent (P7). R9: a relative `session_dir` is sent absolute; `C:\rec`, `\\host\share\rec` and `/home/rec` go as given. R10: `[0, 0, -2]` is sent as `[0, 0, -1]`; zero is an error with no request sent. R12: the three distances' text, one spelling. R1: an answer without `checked` gets the older extension's line, one with it doesn't (Q9). R4: `opacity=1.0` is printed |
| `tests/test_tools_camera.py` | `:286` and `:295`'s `dist=5.0m` become stage units (R12) |
| `tests/test_xform.py` (new) | Every case of the transform writer: no ops; `[translate, orient, scale]`; `[translate, rotateXYZ, scale]`; XformCommonAPI's pivot stack; each Euler order and orient from either input, checked by matrix (U4); `[0, 120, 0]` into rotateXYZ and a quaternion into orient read back as given (P3); Kit's `[rotateZ, rotateY, rotateX]` triple (Q15); a single-axis op, and another mix of rotate ops, replaced in the first one's place; half, float and double; an attribute out of the order with another precision (U5); a matrix-only prim's position, rotation and scale; a matrix among other ops taking the part with no op of its own; a singular matrix refusing a rotation and a scale but taking a position (P9); a new op before a `:unitsResolve` op; `!resetXformStack!`; each refusal, with nothing written: a session layer's `xformOpOrder` over a root-layer write (Q14), samples in the written layer, in a stronger one and only in a weaker one, each with its reason (P4), an instance proxy naming its instance, a layer named by path and the session layer as Kit's; `check_transform`; `position_of`; `look_at` on Y-up and Z-up, straight along the up axis, and refusing the same point (P7); `aim` under a moved parent, with `!resetXformStack!`, with a centre of interest, and on a camera the session layer holds, which it writes there (E1, E4); `aim_error`'s position, direction and scale, a float translate far from the origin passing |
| `tests/test_deletion.py` (new) | U1's four cases; a `def` in the session layer, named as Kit's session layer; a variant on a prim above; a reference authored in a sublayer; an instance proxy, naming its instance (P11). Still deleted (P10): a root-layer `def` under a referenced prim, such as `/World/Franka/panda_hand/Cam`; a root-layer `def` with a sublayer's `over` |
| `tests/test_formatter.py` | The dump's count with `max_depth` and `filter_types`, and its header; `format_scene_tree` |
| `tests/test_material.py` | `set_surface` |
| `tests/test_contract.py` | Unchanged: the golden file stays |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session. Built so: the camera probe both suites use is
`CAMERA_AIM` in `tests/conftest.py`, beside the suites' other shared Kit code:

| Test | What |
|---|---|
| `test_integration.py` `test_07b_a_part_of_a_referenced_file_is_not_deleted` | A file with a child, referenced; `set_transform` on the child (a root-layer `over`); `delete_prim` is an error naming the reference; the child and the `over` stay |
| `test_08b_set_transform_keeps_a_pivot_and_a_matrix` | A pivot stack and a matrix-only prim made by `execute`; position and rotation set; the ops and world positions read back |
| `test_11`, `test_12` | The camera's -Z within 0.5 degrees of the target, read by `execute`; `test_11` also straight down a Y-up stage's up axis, where Isaac's call alone left the camera at the origin with a scale of about 3.4e38 (E5, P1): its scale op reads 1 again, and a capture shows the target centred |
| `test_12f_the_camera_aims_without_isaac_sim` | `set_camera_view` wrapped with the live suite's `_WRAP` as a recorder that moves nothing, so the check finds the camera unaimed and the USD look-at must aim it: Q7's path, live, with the recorder showing Isaac's call ran once. Then `isaacsim.core.utils.viewports` set to `None` in `sys.modules`, as E3 did, and the recorder shows no call. Both ways, `set_camera`, `look_at_prim` and one `inspect_prim` angle aim; the target is centred in a capture and in the viewport's own frame, as E4 measured; the camera's ops are in the session layer and the root layer gains nothing. Each change is undone in the test's cleanup, the 60 s timer only a backstop (P8) |
| `test_21b_clone_offset_keeps_each_copy_s_placement` | A matrix-placed source, `count=3`, an offset; the copies' world positions |
| `test_03b_scene_tree_text_stops_at_max_depth` | `/World` at depth 0 says its children's count, and no child block follows |
| `test_scenarios.py` `03_02`, `03_03`, `08_01`, `11_04`, `12_04`, `13_05` | The aim; `prim_count` equals the blocks in the file; the refusal names `stop_recording`; `enable_opacity` false after `opacity=1`; copies at n times the offset |

**What neither shows:** USD Composer, which isn't on this machine; Kit 107, since Isaac Sim 5.1 doesn't start here
(#25); the GUI's viewport, since port 8211 is the maintainer's; the server's rows through a real MCP client
(`tests/test_tools.py` runs them through the SDK's in-memory client against the mock bridge).

## Docs

- **`docs/TOOLS.md`,** each row's section, as in the table below, with a line on what an extension of 0.2.3 or older
  does.
- **The tools' descriptions,** the same sentences, in `src/omniverse_mcp/tools/`.
- **`docs/ARCHITECTURE.md`'s core list:** `xform.py` (every transform the bridge writes, and the camera's look-at),
  `deletion.py` (whether `delete_prim` can remove a prim, and why not); its list of the formatter's functions
  (`:260-264`) gains `format_scene_tree()` (P13).
- **`AGENTS.md`'s core list,** the same line: "transforms, prim deletion". The file stays at 150 lines.
- **`plugin/skills/script/SKILL.md`'s camera trap,** through `write-skill`, with E4's reason (Q11).
- **`handlers/camera.py`:** `_set_camera_xform`'s docstring, which says a USD write doesn't move the viewport camera
  reliably, goes with the function.
- **`test_project/scenarios.md`:** 3.2, 3.3, 8.1, 11.4, 12.4 and 13.5 verify what their twins in `test_scenarios.py`
  check (P13).
- **The eight tools #77 merges in pairs** (`set_camera` and `look_at_prim`, `get_scene_tree` and `dump_scene`,
  `get_robot_info` and `get_joint_states`, `get_mesh_stats` and `get_prim_face_count_tree`): their descriptions and
  `docs/TOOLS.md` sections change only by the sentence each fix needs, since #77 rewrites them (the maintainer,
  2026-10-31).
- **`CHANGELOG.md`,** under Unreleased, below.

| Row | Description and `docs/TOOLS.md` |
|---|---|
| R1 | Replace "USD keeps a prim ... though the answer says deleted, so check with get_scene_tree" with: a prim another layer defines too, or one a reference or payload on a prim above brings, such as a part of a referenced asset, is refused, naming why, and nothing changes; `set_visibility` hides it, or its instance for a prim inside one. TOOLS.md: with an older extension, the answer's added line (Q9) |
| R2 | Drop "Aiming needs Isaac Sim: other Kit apps only move the camera, without aiming it". TOOLS.md: Isaac Sim's `isaacsim.core.utils.viewports` where it loads, and the camera's own ops elsewhere, in the layer that holds them (the session layer, for Kit's own cameras); `inspect_prim`'s section says the same of its angles |
| R3 | `set_camera`: an error for a position equal to the point it looks at, its target or the origin |
| R4 | `set_material`: `opacity`, `roughness` and `metallic` are set on every call, each to its default when left out, so a call without `opacity` makes the material opaque; the answer gives all three |
| R5 | `dump_scene`: returns the file's path and how many prims it wrote |
| R6 | `start_recording`: TOOLS.md's "One at a time" bullet gains the older extension's `force=True` line |
| R7 | `set_prim_transform`: replace the "rewrites the prim's xform ops ... loses that placement" sentence with: it writes into the prim's own ops, the position into its translate op, the rotation into its rotate or orient ops in their kind, the scale into its scale op, adding an op it lacks; other ops, a pivot among them, stay; a part with no op of its own goes into the prim's matrix (`xformOp:transform`) when it has one; an animated op, ops a stronger layer holds, such as a Kit camera's, and a rotation or scale on a matrix that can't be factored are errors. `create_prim`: "takes the new transform" as `set_prim_transform` writes it |
| R8 | `clone_prim`: replace the "rewritten as set_prim_transform does ... lose that placement" sentence with: with `offset`, copy n moves n times `offset` from the source in the parent's space, its ops and placement kept; the first copy, and a single copy, are left as copied |
| R9 | `get_recording_frame`: `session_dir`'s field and the description: as `start_recording` and `stop_recording` give it, relative to this server's working folder, or an absolute path on Kit's machine |
| R10 | `raycast`: `direction`'s field: any length but zero, where it said "a unit vector: PhysX takes it as given" (E6); the distance is in stage units |
| R11 | `get_scene_tree`: `max_depth`'s field and the description: a prim at `max_depth` that has children says how many, as `children = N (truncated)`; nothing below it is listed |
| R12 | `look_at_prim`, `inspect_prim`, `raycast`: TOOLS.md's answer lines say `stage units`, one spelling |

`CHANGELOG.md`, under Unreleased:

```markdown
### Fixed

- **`delete_prim` refuses a prim it can't remove, where it answered "Deleted" and the prim stayed:** one another layer
  defines too, or one a reference or payload on a prim above brings, such as a part of a referenced robot. The error
  says which, nothing changes, and `set_visibility` hides such a prim. The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit. Until then, `delete_prim`'s answer says to check with
  `get_scene_tree` (#82).
- **`set_camera`, `look_at_prim` and `inspect_prim` aim the camera in every Kit app.** Without Isaac Sim's
  `isaacsim.core.utils.viewports` they wrote the camera's transform into the stage's root layer, which Kit's own
  viewport camera, held in the session layer, ignores: `set_camera` and `look_at_prim` failed with a USD error,
  `inspect_prim` took every angle from where the camera stood, and each left an override of the camera in the root
  layer. A scene camera moved without turning, and `look_at_prim` reset its rotation. They now aim the camera in the
  layer that holds it, as Kit does. In Isaac Sim, a camera looking straight down a Y-up stage's up axis, which Isaac's
  call left at the origin, is aimed too. The fix is in the Kit extension (#82).
- **`set_camera` refuses a `position` equal to the point it looks at,** its `target` or the world origin when none
  is given, where it answered success with nothing to look at (#82).
- **`set_material` makes a material opaque again with `opacity=1`:** it wrote the opacity only below 1, so a material
  made see-through stayed so. A call that leaves `opacity` out now makes the material opaque, as one that leaves out
  `roughness` or `metallic` sets theirs, and the answer gives the opacity every time. The fix is in the Kit extension
  (#82).
- **`dump_scene` counts the prims it wrote,** where "Dumped N prims" counted the whole stage and the file's
  `prim_count` the whole subtree, past `max_depth` and `filter_types`. The fix is in the Kit extension (#82).
- **A second `start_recording` says to call `stop_recording`,** where it said to pass `force=True`, which the tool
  doesn't take. The fix is in the Kit extension (#82).
- **`set_prim_transform` keeps a prim's other xform ops:** it rewrote them as translate, rotate and scale and dropped
  the rest, so a pivot went, a pivot could be read as the position, and a prim placed by a matrix (`xformOp:transform`),
  as imported assets often are, lost that placement. The position, rotation and scale now go into the prim's own ops,
  the rotation in its op's kind, and a matrix is changed in place; `create_prim` and `create_robot` place a prim the
  same way. The fix is in the Kit extension (#82).
- **`clone_prim` with `offset` keeps each copy's placement,** moving copy n by n times the offset from the source:
  copies of a source placed by a matrix or about a pivot lost that placement, and a single copy had its ops rewritten.
  The fix is in the Kit extension (#82).
- **`get_recording_frame` reads the folder `start_recording` and `stop_recording` print,** relative to the server's
  working folder, where Kit read a relative `session_dir` from its own folder and answered "Frame not found" (#82).
- **`raycast` takes a `direction` of any length but zero,** where its description asked for a unit vector and said
  PhysX takes it as given: Isaac Sim 6.2's PhysX scales it itself, and the server now does so before sending it, for
  any other. A zero direction is an error (#82).
- **`get_scene_tree` stops at `max_depth`, and a prim there says how many children it has,** where the text listed the
  next level's prims that had children and left out the rest, so a childless prim there looked absent. The fix is in
  the Kit extension (#82).
- **`look_at_prim`, `inspect_prim` and `raycast` give distances in stage units,** where they printed `m`: on a stage in
  centimetres, centimetres labelled metres (#82).

### Changed

- **`set_prim_transform`, `create_prim` and `create_robot` refuse what they can't show:** a rotation that isn't 3 or 4
  numbers, which they ignored; a zero quaternion; an xform op with animation, whose value they set where the animation
  hid it or froze it; ops a stronger layer holds, such as Kit's viewport camera's, where they failed with a USD error;
  and a rotation or scale on a matrix that can't be factored, which lost the rotation. `create_prim` and
  `create_robot` refuse before making the prim. The fix is in the Kit extension (#82).
```

## Risks

| Risk | Status |
|---|---|
| The transform writer serves five tools: a mistake there places prims wrongly everywhere | Accepted: a unit test per op kind, precision, pivot and matrix case; live `test_08b`, `test_21b`, and every live test that creates or moves a prim |
| Converting into another Euler order gives other angles for the same rotation | Accepted: tested by matrix; TOOLS.md says the op keeps its kind |
| The camera's write lands in the root layer and saves a camera override into the user's file | Resolved by E1, E2, E4: `aim` writes the layer that holds the camera's ops, the session layer for Kit's own; unit tests check the root layer gains no spec, and live `test_12f` too |
| The viewport doesn't follow a USD write, as the trap row says | Resolved in reason by E4: it follows the composed transform; 0.2.3's writes were outranked. Live `test_12f` decides, on the fallback's own write in the viewport's frame; should it fail, the fallback calls `ViewportCameraState` where it loads |
| Isaac's call leaves a scale only a check of the scale shows (E5, P1) | Accepted: `aim_error` compares the scale, and the snapshot is put back before the USD look-at; how RTX renders a camera scaled 3.4e38 is untried |
| Kit's session layer defines prims under `/World`, so the delete check refuses them | Resolved by E7: only Kit's cameras, and overs under `/Render` |
| A stage that went through 0.2.3's fallback keeps an override of Kit's camera in its root layer (E3, E4) | Accepted: outranked by the session layer, so harmless; this change writes none and removes none |
| E6 ran one PhysX build; a zero direction's PhysX answer is unmeasured | Accepted: the server scales the direction and refuses zero, whatever PhysX does (Q13) |
| The stubs type `GetCompositionArcs` as another class and `GetIntroducingLayer` as never `None` | Accepted: typed forms in `core/usd.py`, as for the stubs' other gaps; the baseline doesn't grow |
| Users notice: a recolour makes a material opaque, a relative `session_dir` changes meaning, new refusals | Accepted: CHANGELOG's Fixed and Changed say so (Q3, Q8) |
| Another branch in flight edits CHANGELOG's Unreleased or TOOLS.md | Accepted: rebase on `origin/main` before the PR |
| The GUI, Kit 107 and USD Composer untried | Accepted: the PR says so |

## Plan review

### Round 1

**How:** two fresh reviewers the session started, Claude, 2026-10-31, on `8601a05`: A on the transform core and the
camera rows, B on the other rows, compatibility, tests and docs. Each read `AGENTS.md`, `REVIEW.md`, `lenses.md`, the
plan, #82 and the files the plan names. Nothing was run.

**Verdict:** `approved`: each reviewer approved their scope, with no blocker or major; fourteen minors, all fixed;
Q6 and Q9 restated and Q15 added in this round. The maintainer answered Q1 to Q15 on 2026-10-31: as recommended,
but Q2, dropped with R3's line for a call without a target, which #77's merged camera tool settles. No round 2.

**Now:** P1 to P14 fixed in the commit after `8601a05`; eight improvements taken, one left.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | Isaac's `set_camera_view` straight along the up axis leaves a FLT_MAX scale. On a Y-up stage, `set_camera([2, 8, -1], [2, 0.5, -1])`: `set_target_world`'s `SetLookAt().GetInverse()` (`camera_state.py:174`) is singular, so the inverse is FLT_MAX times identity, which `TransformPrimCommand` factors into a scale of about 3.4e38 with translate 0, E5's numbers. The check saw only the position, the USD look-at kept the scale, and the centre of interest landed in a frame scaled by 3.4e38; `inspect_prim`'s top and bottom may leave a scale of about 1.7e6 with the direction right, which passes the check | fixed: the camera's ops are taken as a snapshot before Isaac's call; `aim_error` compares the world scale too; the snapshot is put back before the USD look-at (Design, The camera, steps 1 and 2); E5's row names the cause; the unit fake writes Kit's FLT_MAX scale; `test_11`'s straight-down case reads the scale op and checks a capture |
| P2 | minor | Kit's `TransformPrimCommand` writes `[translate, rotateZ, rotateY, rotateX, scale]` (`usd_commands.py:2350-2364`): replacing only the first rotate op leaves the other two composed in | fixed: every unsuffixed rotate op is the rotation; Kit's triple takes it decomposed into its axes (Q15), any other set is replaced together by one op in the first one's place; `test_xform.py` |
| P3 | minor | Angles round-tripped through `Decompose` into an op of the same kind: `rotation=[0, 120, 0]` reads back as about `(180, 60, 180)` | fixed: Euler angles into rotateXYZ and a normalised quaternion into orient go as given; only a change of kind converts; a test reads the op's value |
| P4 | minor | The animated-op refusal's premise is wrong for samples in a weaker layer: a stronger layer's default beats them (OpenUSD's value resolution), so the write freezes the animation rather than being hidden | fixed: the rule by layer, in the Design's refusals; Q6 restated; `test_xform.py` covers samples in the written, a stronger and a weaker layer |
| P5 | minor | `create_prim` and `create_robot` answer an error after making the prim (`scene.py:305-314`, `robot.py:94-99`): `create_robot("franka", rotation=[0, 90])` is refused, and the retry says the prim exists | fixed: `check_transform` before `DefinePrim`; a refusal found only after removes what the call made and says why; `test_scene_handler.py`, new `test_robot_handler.py` |
| P6 | minor | `clone_prim` copies into the root layer but moves in the edit target: with a sublayer as the edit target, copy 1's move is refused as hidden, with copies left behind | fixed: the copies move in the root layer; a test with a sublayer as the edit target |
| P7 | minor | A position equal to the target still reaches Isaac's call: `set_camera(position=[0, 0, 0])` with no target, Isaac's same-x-and-y branch turns the camera, then `look_at` refuses | fixed: `_aim_camera` refuses before any write; the server compares the position with the effective target, the origin when none is given; tests in `test_xform.py`, `test_camera_handler.py` and `test_tools.py` |
| P8 | minor | `test_12f` can't tell the fallback from Isaac's path: both write the session layer and centre the target; and the 60 s self-undo could fire mid-test | fixed: `set_camera_view` wrapped as a recorder that moves nothing, so Q7's path runs live and the recorder shows Isaac's call ran; then the import forced off and the recorder showing none; each undone in the test's cleanup, the timer a backstop |
| P9 | minor | A matrix that can't be factored: `set_prim_transform(scale=0)` on a matrix-only prim, then `scale=1`: `Factor` fails and clamps, the rotation is lost, and the answer says success | fixed: a rotation or a scale on such a matrix is refused, saying why; a position still goes through `SetTranslateOnly`; `test_xform.py` |
| P10 | minor | The Tests miss what `delete_prim` must still delete | fixed: `test_deletion.py` deletes a root-layer `def` under a referenced prim (`/World/Franka/panda_hand/Cam`) and a root-layer `def` with a sublayer's `over` |
| P11 | minor | The instance-proxy refusal sends the agent to `set_visibility`, which can't author on a proxy (`core/isolation.py` says so; `MakeInvisible` would raise) | fixed: the refusal names the instance prim, which `set_visibility` can hide whole |
| P12 | minor | Step 4 isn't buildable alone: `handle_camera_set`'s fallback imports `_apply_xform` (`camera.py:506`) until step 5, and basedpyright doesn't check `ovmcp/bridge` to catch it | fixed: `_apply_xform` goes in step 5 |
| P13 | minor | Docs and Tests miss files: `docs/ARCHITECTURE.md:260-264`, the formatter's functions; `test_project/scenarios.md`'s 8.1 and 11.4; `tests/test_tools_camera.py:286` and `:295` (`dist=5.0m`) | fixed: listed in Docs and Tests |
| P14 | minor | A user who updates the plugin but not the extension: a new server on a 0.2.3 extension prints "Deleted" for a prim that stays, under a description that says such prims are refused. Q9's reason was wrong: `client.extension_version` comes from the handshake (`client.py:129`), and `get_sim_state` uses it | fixed: Q9 restated; `delete_prim`'s answer adds one line when the extension made no check, keyed on its new `checked` marker (Design, Older extensions); `test_tools.py` |

**Refuted:**

- **Reviewer A:**
  - A raw USD write doesn't move Kit's viewport: it does; `TransformPrimCommand` is `xform_op.Set` under an
    `EditContext` on the session layer, and E4 showed it.
  - Isaac's Z-up-only branch mis-aims a Y-up camera looking front or back: it writes (0, 0, 0) or (0, 180, 0), aimed
    and upright.
  - A position equal to the target writes NaN through Isaac's call: the same-x-and-y branch runs instead; that is P7.
  - The hidden-write rule refuses referenced prims: a referenced layer is weaker than the stage's own.
  - U4's Euler convention: Kit uses the same.
  - An aim failure stops the remaining `inspect_prim` angles: only `NoFrameError` and `OutOfTimeError` stop them.
  - A single copy with an offset should move: the description says it never does.
  - Kit 107 differs: Isaac Sim 5.1's `set_camera_view` has the same logic.
  - USD off the main thread: none.
- **Reviewer B:**
  - Field descriptions move `mcp-tools.json`: `tools/golden.py` strips descriptions.
  - R9's join breaks a remote Kit app: it rebuilds the string Kit wrote; across OSes it was already broken.
  - R10's scaling changes answers: a no-op where PhysX normalises (E6).
  - The session layer or `isolate` makes the delete check refuse `/World` prims: `isolate` writes `over`s, and only
    `def` and `class` count (E7).
  - Render products defined in the root and session layers are refused: the honest answer.
  - R4 writes inputs onto a shader that isn't OmniPBR: today's code already does.
  - Q3 makes a recolour opaque: the explicit owner call.
  - R5 counts the pseudo-root's block: consistent with the file.
  - R11 lists less: documented.
  - `AGENTS.md` over 150 lines: only a line grows longer.
  - The plan doesn't end with `review-code`: step 11's `finish-work` runs it.
  - A one-way door moves: none.

**Owner calls** of this round (all fifteen in Design, Decisions for the maintainer):

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q6 | Restated (P4): samples in the written or a stronger layer hide the write; samples only in a weaker layer are overridden, freezing the animation. Refuse both, by layer, or write in the second case and say so? | Refuse both, with the reason by layer | As recommended (2026-10-31) |
| Q9 | Restated (P14): one added line to `delete_prim`'s answer when the extension made no check; no warning per call for the other tools? | Yes to both | As recommended (2026-10-31) |
| Q15 | New (P2): Kit's `[rotateZ, rotateY, rotateX]` triple: write the rotation decomposed into it, or replace the three with one rotateXYZ? | Kit's triple | As recommended (2026-10-31) |

**Improvements:**

| Improvement | Answer |
|---|---|
| Name Kit's session layer as "Kit's session layer", compared with `stage.GetSessionLayer()`, not by its anonymous identifier | taken: the transform writer's and `delete_prim`'s refusals |
| `set_material`'s answer prints the opacity on every call, so a recolour that makes a material opaque says so | taken: The others, R4 |
| One spelling of stage units everywhere (R12) | taken |
| Follow `TransformPrimCommand`'s op placement (`usd_commands.py:2210-2236`): set aside `:unitsResolve` ops rather than adding a new op after them; write into an `xformOp:transform` among other ops rather than adding a translate outside it | taken: What it writes into; A prim with a matrix op |
| The Risks row "Resolved by E4": `test_12f` decides, and `ViewportCameraState` where it loads if it fails | taken: Risks; Design, The camera |
| `set_local_transform` refuses an instance proxy as inside an instance, naming the instance, instead of USD's raw error | taken |
| A `create_robot` handler test through the core | taken: `tests/test_robot_handler.py` |
| The aim check's position tolerance, relative plus absolute, so a float translate far from the origin doesn't fail it | taken: Design, The camera, step 2 |
| Keep R11's text listing the next level's prims that have children | left: the text mode drops the next level as JSON does; it is documented, and matches the name `max_depth` |

**Not covered:** nothing was run. USD Composer's camera ops, and how RTX renders a camera scaled 3.4e38, can't be
checked without Kit. `PrimCompositionQuery` on Kit 107 was taken from U1 and Isaac Sim 5.1's `pxr` on disk.
