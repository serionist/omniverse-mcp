---
title: Make twelve tools do what their answers say
issue: "#82"
status: draft
approved_by:
approved_at:
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
| R3 | `set_camera` | Without a target, the answer says it looks at the world origin; a target equal to the position is an error | `test_tools.py` |
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
| E5 | Straight along the up axis | Y-up: Isaac's call answered success with the camera at the origin, 64 degrees off the target, its centre of interest zero. Z-up: aimed, by its hand-written branch, but the centre of interest left at 42.4 for a distance of 7.5 | Q7: check after Isaac's call; set the centre of interest after either path |
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

**What it writes into.** Each part has one op, found by its name among the prim's ordered ops. An op with a suffix of
its own (a pivot, `xformOp:rotateZ:spin`) or an inverse op is another op, kept as it is and where it is.

| Part | Its op | When the prim has none |
|---|---|---|
| position | `xformOp:translate` | a translate op (double) first in the order: outermost, so it places the prim in the parent's space |
| rotation | the first unsuffixed rotate op: orient, any of the six Euler orders, or rotateX, Y or Z | rotateXYZ (float) for Euler angles, orient (double) for a quaternion: before the scale op, else before the first inverse op, else last |
| scale | `xformOp:scale` | a scale op (float) before the first inverse op, else last |

Those places are `XformCommonAPI`'s order (K7) and Kit's `[translate, orient, scale]`, so a prim with no ops gets the
ops today's code gives it, and a pivot pair stays around the rotation and scale. The kinds and precisions of ops it adds
are today's, not Kit's prim defaults (orient, double; E1), so `create_prim`'s output doesn't change.

**A value in the op's own kind and precision** (Q5):

- position and scale: a vector in the op's precision, half, float or double.
- rotation: Euler angles `[rx, ry, rz]` (rotateXYZ's meaning, as the tool says) or a quaternion `[w, x, y, z]`,
  normalised; converted through `Gf.Rotation` to the op's kind. An orient op takes the quaternion, an Euler op the
  angles for its order (U4). A single-axis op can't hold any rotation: it is replaced, in its place in the order, by
  rotateXYZ or orient.
- An op added where an attribute of its name already exists out of the order reuses that attribute's precision (U5).

**A prim placed by one matrix.** When the prim's only op is `xformOp:transform`, as converters often write, the matrix
itself changes: the position by `SetTranslateOnly`, exactly; a rotation or a scale through `Gf.Transform`, which
factors the matrix and builds it again with the new part (U3). A matrix op among other ops is another op, kept.

**Kept:** every other op, its value and its place; `!resetXformStack!` (U7); and, as `ClearXformOpOrder` leaves them
today, the attributes of ops it replaced, out of the order.

**Refused,** with nothing written:

- a position, or a scale list, that isn't 3 numbers; a rotation that isn't 3 or 4 numbers (ignored today); a zero
  quaternion;
- an op it would write that has time samples: `Set` writes the default value, which the samples hide at every time,
  so the answer would say success while nothing shows (Q6);
- a write another layer would hide: one of the stage's own layers stronger than the layer written, such as the session
  layer, holds an opinion on the prim's `xformOpOrder` or on an op it would write. The error names that layer. 0.2.3's
  writes into the root layer under the session layer's opinions failed with a USD error or moved nothing (E3, E4), and
  `set_prim_transform` on Kit's own camera now says why instead (Q14).

**What "position" means with a pivot:** the translate op's value, which Kit's Property panel shows as Translate and
`XformCommonAPI.SetTranslate` sets; the prim turns and scales about its pivot. `docs/TOOLS.md` says so.

**`clone_prim` (R8).** Copy n of `count`, from 0, moves by n times `offset`: `position_of(copy) + n * offset`, through
`set_local_transform`. Copy 0, and a single copy, are left as copied, as the description already says. A source whose
position can't be written (an animated translate op) is refused before anything is copied, as a taken target is
today.

**The callers:** `handle_transform`, `handle_create_prim`, `handle_clone_prim` and `handle_create_robot` call the core
and answer its `ValueError` as an error.

| Alternative | Why not |
|---|---|
| `XformCommonAPI` | Refuses orient and matrices (K7): Kit's own `[translate, orient, scale]` and matrix-placed assets are the prims that broke |
| Rewrite as translate, orient and scale, factoring a matrix first | Keeps the placement, but still drops the ops #82 asks to keep, a matrix and a pivot pair among them |
| Replace the rotate op by the kind given (Q5's other answer) | Reads back as written, but swaps an asset's orient for rotateXYZ, and back again at the next quaternion, leaving the old attribute each time |
| Kit's `TransformPrimCommand` | Kit-bound, so tested only live, and an undo entry for every call, where the bridge's other writes make none |

### The camera (R2, R3)

One helper in `handlers/camera.py`, `_aim_camera(camera_path, eye, target)`, which returns why it couldn't aim, or
`None`. `set_camera`, `look_at_prim` and `inspect_prim` call it; `_set_camera_xform` goes, its math moved to the core.

1. **Isaac Sim's `set_camera_view`,** when `isaacsim.core.utils.viewports` imports: Isaac Sim's path, as today (K1,
   K2, E2).
2. **The check:** `aim_error` compares the camera's world position with `eye` (within 1e-4 of the distance) and its -Z
   axis with the direction to `target` (within 0.5 degrees). When it is off, because there is no Isaac Sim or because
   Isaac's call left the camera unaimed (E5: straight down a Y-up stage's up axis, it put the camera at the origin; K2:
   no viewport), the USD look-at follows (Q7).
3. **The USD look-at,** `aim`: `look_at(eye, target, up_axis)`, `_set_camera_xform`'s math (right = world up x back;
   the X axis when looking straight along the up axis), taken into the camera's parent space, or none for a camera
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
(E3, E4). Live `test_12f` shows the fallback's own write moving the viewport before the PR.

- **`set_camera`:** `except (ImportError, Exception)` goes: an exception in Isaac's call is an error, where 0.2.3 fell
  back to `_apply_xform`.
- **R3, in the server:** with no `target`, the answer says `looking at the world origin [0, 0, 0] (no target given)`
  (Q2); a `target` equal to `position` is refused before any request. Both hold with any extension; `look_at` refuses
  the same point too.
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

- An instance proxy is refused as inside an instance.
- A refusal changes nothing: `/World/Robot/Link is not deleted: it comes through a reference on /World/Robot
  (bot.usda). set_visibility hides it.`
- Then `RemovePrim`. A `False`, or the prim still defined after it, is an error too, as a defence.

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
| R4 | `core/material.py`: `set_surface(shader, colour, opacity, roughness, metallic)` | Writes all five on every call: `enable_opacity` is `opacity < 1`, `opacity_constant` always (Q3) |
| R5 | `core/formatter.py` | `format_scene_dump` walks first and returns the text with the number of prim blocks; the header's `prim_count` and `SCENE` line give that number; the handler answers it |
| R6 | `handlers/recording.py` | `A recording is already running: call stop_recording first`; while one is starting, `A recording is starting: wait for its answer, then call stop_recording`. The route keeps `force`, unadvertised (Q1) |
| R9 | server `tools/recording.py` | A `session_dir` with no anchor in either Windows' or POSIX's form (`PureWindowsPath(s).anchor == ""`) is joined to the server's working folder, the reverse of `h.rel`; an absolute one, in either form, goes as given, so a Kit app on another OS still gets its own paths (Q8) |
| R10 | server `tools/simulation.py` | `direction` divided by its length; a zero one is a `ToolError` before any request. Isaac Sim 6.2's PhysX already scales it (E6); the server's scaling makes the description true on any PhysX build, and the zero case an error of ours (Q13) |
| R11 | `core/formatter.py`: `format_scene_tree(stage, root, max_depth, include_properties)` | Lists levels 0 to `max_depth`; a prim at `max_depth` with children gets `children = N (truncated)` on its own block, as JSON mode does. The handler's text branch calls it, and `prim_count` stays the prims listed |
| R12 | server `tools/camera.py`, `tools/simulation.py` | `Distance: 5.0 (stage units)`, `dist=2.5 stage units`, `raycast`'s `Distance: 4.9500 (stage units)` |

### Older extensions

R3, R9, R10 and R12 are the server's: they hold with any extension. The other eight need this release's extension; an
older one behaves as today. As #74, #80 and #84 did, `docs/TOOLS.md` says under each tool what an extension of 0.2.3 or
older does, each `CHANGELOG.md` line says the fix is in the Kit extension, with the install command, and
`get_sim_state`'s note already names the command whenever the versions differ. No tool warns per call (Q9).

### Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | `start_recording`'s refusal: expose a `force` parameter (a schema change, a one-way door), or say `call stop_recording first`? | The message: `stop_recording` ends the recording and writes its metadata, where `force` drops it unwritten; the route keeps `force` for HTTP callers | |
| Q2 | `set_camera` without a target: aim at the origin and say so, or keep the camera's direction and only move it? | Say so: the description has said "the origin when omitted" since #83, and the other would change what a call does for anyone who relies on it | |
| Q3 | `set_material` without `opacity`: opaque, as `roughness` and `metallic` take their defaults on every call, or keep the material's opacity (a `None` default: a schema change)? | Opaque: one rule for the three values and no contract change; the description says a recolour sets all three | |
| Q4 | `delete_prim` on a prim USD can't remove: refuse, naming why, with nothing changed; deactivate it instead; or remove it from every local layer, as Kit's delete does? | Refuse: the call does what its name says or nothing, and the error names `set_visibility` | |
| Q5 | `set_prim_transform`'s rotation into a rotate op of another kind: convert it into that op, or replace the op in its place by the kind given? | Convert: every op stays as authored, which is #82's point; `get_prim_properties` gives the world rotation as a quaternion either way | |
| Q6 | An op with time samples: refuse, or write its default value as today, which the animation hides? | Refuse: success with nothing visible is the kind of bug #82 is about | |
| Q7 | After Isaac Sim's `set_camera_view`, check that the camera aims at the target, and take the USD look-at when it doesn't? | Yes, the more so after E5: straight down a Y-up stage's up axis, Isaac's call answered success with the camera at the origin, 64 degrees off. It changes Isaac Sim's behaviour only where the camera was left unaimed | |
| Q8 | `get_recording_frame`: read a relative `session_dir` from the server's working folder, where Kit read it from its own? | Yes: it is the form `start_recording` and `stop_recording` print, and no tool writes a recording under Kit's folder | |
| Q9 | An older extension: no warning per tool call, as for #74 and #84, with `docs/TOOLS.md` and `CHANGELOG.md` saying which fixes need this release's extension? | Yes: a warning per tool needs a marker in each answer, for fixes of a few lines each | |
| Q10 | One PR for the twelve rows, or the transforms and the camera (R2, R7, R8) apart from the rest? | One: the issue asks for it, the docs move once, and one live run covers all; the Steps keep the transform core in commits of its own, so a split stays possible | |
| Q11 | The script skill's trap row says neither a USD write nor `ViewportCameraState` moves the viewport camera reliably (from `8d684d6`, in March). E4: `ViewportCameraState` moved it exactly; a `UsdGeom.Xformable` write moved nothing because it lands in the edit target's layer, which the session layer, holding Kit's camera, outranks. Correct the row in this PR? | Yes, through `write-skill`: "a write in the stage's edit layer doesn't move Kit's viewport camera, whose ops the session layer holds: `await mcp.set_camera()` or `mcp.look_at()`, or `ViewportCameraState`" | |
| Q12 | The extras found reading the rows: `raycast`'s `m`, `set_camera`'s target equal to its position, a rotation that isn't 3 or 4 numbers, the camera fallback's parent space and `!resetXformStack!`, the centre of interest after either path (E5). In this PR? | Yes: the same kind of bug, a few lines each, each with its test | |
| Q13 | `raycast` (R10): Isaac Sim 6.2's PhysX scales the direction itself, so today's answers are right (E6), and only the description, "a unit vector: PhysX takes it as given", is wrong. Keep the server's scaling, or fix only the description? | Keep it, with the description fixed: two lines that make "any length but zero" true on every PhysX build, Kit 107's untried among them, and a zero direction an error of ours, where E6 didn't try what PhysX does with it | |
| Q14 | Write Kit's own cameras in the session layer, where Kit writes them (E2, E4), and refuse any transform write a stronger layer of the stage would hide, naming it, such as `set_prim_transform` on Kit's camera, whose code, `_apply_xform`, failed there with a USD error (E3)? | Yes: a session-layer edit isn't saved with the file, as Kit's own camera moves aren't, and the refusal turns E3's error and E4's silent no-op into an answer that says why | |

## Compatibility

No one-way door moves, with Q1 and Q3 as recommended.

| Door | Effect |
|---|---|
| Tool names, schemas, annotations | None: only descriptions change, which `tools/golden.py` strips; `tests/fixtures/mcp-tools.json` stays |
| Wire protocol | Same paths and bodies; `PROTOCOL` stays 1. `/scene/dump`'s `prim_count` counts the blocks written. `/scene/delete`, `/camera/*`, `/scene/transform`, `/scene/create`, `/scene/clone` and `/robot/create` can answer errors they didn't |
| The extension's id and settings | Unchanged |
| The output folder | The same files; `scene_dump.txt`'s header count means the blocks in it |

What users notice:

| Before | After |
|---|---|
| `delete_prim` answered "Deleted" for a prim that stayed, after removing the edit layer's overrides of it | Refused, naming why, with nothing changed |
| Outside Isaac Sim, `set_camera` and `look_at_prim` failed with a USD error on Kit's own camera and left an override of it in the root layer (E3), and moved a scene camera without aiming it, `look_at_prim` resetting its rotation; `inspect_prim` captured every angle from where Kit's camera stood (E4) | Aimed in every Kit app, Kit's own camera in the session layer, as Kit does |
| In Isaac Sim, straight down a Y-up stage's up axis, `set_camera` put the camera at the origin and answered success (E5) | Aimed |
| `set_prim_transform` on a prim whose ops a stronger layer holds, such as Kit's camera, failed with a USD error | Refused, naming the layer (Q14) |
| `set_camera` without a target named only the position | Says it looks at the world origin; a target equal to the position is an error |
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
  today, as `docs/TOOLS.md` says; `uvx omniverse-mcp extension install`, then a restart of Kit, as `get_sim_state`'s
  note says. An older server on the new extension gets the eight extension fixes; its own text is as before.
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
| 4 | The transforms through the core: `handle_transform`, `handle_create_prim`, `handle_clone_prim`, `handle_create_robot`; `_apply_xform` gone (R7, R8) | `tests/test_scene_handler.py` (new) |
| 5 | The camera: `_aim_camera` for `set_camera`, `look_at_prim` and `inspect_prim` (R2) | `tests/test_camera_handler.py` |
| 6 | `core/deletion.py` and `handle_delete_prim` (R1) | `tests/test_deletion.py`, `tests/test_scene_handler.py` |
| 7 | `core/formatter.py`: the tree's text and the dump's count, and their handlers (R5, R11) | `tests/test_formatter.py`, `tests/test_scene_handler.py` |
| 8 | `core/material.py`'s `set_surface` (R4); the recording refusals (R6) | `tests/test_material.py`, `tests/test_scene_handler.py`, `tests/test_recording_handler.py` |
| 9 | The live tests below | Run by the session on Isaac Sim 6.2 headless |
| 10 | The docs | `tests/test_contract.py` unchanged; the gate's AGENTS.md and skill checks |
| 11 | `finish-work`: the gate in full, both live suites in full, `review-code` | No live failure beyond `main`'s on the same Kit |

## Tests

Each row's fix has a test that fails at `f26642c`, named first below.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_scene_handler.py` (new) | `handlers/scene.py` loaded from its file with Kit faked and `_utils.py` from its own, as `tests/test_camera_handler.py` and `tests/test_camera_feed.py` do, on a usd-core stage. R1: a part of a referenced file refused, its root-layer `over` kept, and a prim of the root layer deleted. R4: `opacity` 0.5 then 1 leaves `enable_opacity` false. R5: a subtree's dump counts its blocks. R7: a pivot stack keeps its pivot, and its position lands in the translate op; a matrix-only prim keeps its matrix op; `!resetXformStack!` stays; an animated op and a two-number rotation are errors. R8: a matrix-placed and a pivoted source's copies sit at n times the offset, ops kept. R11: text mode at `max_depth` 0 and 1 |
| `tests/test_camera_handler.py` | The harness has no `isaacsim`, so the fallback runs; its camera is defined in the stage's session layer with Kit's ops, as E1 found Kit's. R2: `set_camera` and `look_at_prim` leave the camera's -Z on the target within 0.5 degrees, written in the session layer, the root layer holding no spec of it (fail at `f26642c` with E3's `AddXformOp` error); `inspect_prim`'s angles too (unmoved at `f26642c`, E4); a scene camera under a moved parent; a fake `set_camera_view` that leaves the camera at the origin, as E5's, is followed by the USD look-at (Q7); the centre of interest after either path |
| `tests/test_recording_handler.py` | R6: the refusal while one runs, and while one starts, names `stop_recording` and not `force` |
| `tests/test_tools.py` | R3: no target gives `the world origin`; a target equal to the position is an error with no request sent. R9: a relative `session_dir` is sent absolute; `C:\rec`, `\\host\share\rec` and `/home/rec` go as given. R10: `[0, 0, -2]` is sent as `[0, 0, -1]`; zero is an error with no request sent. R12: the three distances' text |
| `tests/test_xform.py` (new) | Every case of the transform writer: no ops; `[translate, orient, scale]`; `[translate, rotateXYZ, scale]`; XformCommonAPI's pivot stack; each Euler order and orient from either input, checked by matrix (U4); a single-axis op replaced in its place; half, float and double; an attribute out of the order with another precision (U5); a matrix-only prim's position, rotation and scale; `!resetXformStack!`; each refusal, with nothing written, a session layer's `xformOpOrder` over a root-layer write among them (Q14); `position_of`; `look_at` on Y-up and Z-up and straight along the up axis; `aim` under a moved parent, with `!resetXformStack!`, with a centre of interest, and on a camera the session layer holds, which it writes there (E1, E4) |
| `tests/test_deletion.py` (new) | U1's four cases; a `def` in the session layer; a variant on a prim above; a reference authored in a sublayer; an instance proxy |
| `tests/test_formatter.py` | The dump's count with `max_depth` and `filter_types`, and its header; `format_scene_tree` |
| `tests/test_material.py` | `set_surface` |
| `tests/test_contract.py` | Unchanged: the golden file stays |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session:

| Test | What |
|---|---|
| `test_integration.py` `test_07b_a_part_of_a_referenced_file_is_not_deleted` | A file with a child, referenced; `set_transform` on the child (a root-layer `over`); `delete_prim` is an error naming the reference; the child and the `over` stay |
| `test_08b_set_transform_keeps_a_pivot_and_a_matrix` | A pivot stack and a matrix-only prim made by `execute`; position and rotation set; the ops and world positions read back |
| `test_11`, `test_12` | The camera's -Z within 0.5 degrees of the target, read by `execute`; `test_11` also straight down a Y-up stage's up axis, where Isaac's call alone left the camera at the origin (E5) |
| `test_12f_the_camera_aims_without_isaac_sim` | `isaacsim.core.utils.viewports` set to `None` in `sys.modules`, with the live suite's 60 s undo, as E3 did; `set_camera`, `look_at_prim` and one `inspect_prim` angle aim; the target is centred in a capture and in the viewport's own frame, as E4 measured; the camera's ops are written in the session layer and the root layer gains nothing |
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
  `deletion.py` (whether `delete_prim` can remove a prim, and why not).
- **`AGENTS.md`'s core list,** the same line: "transforms, prim deletion". The file stays at 150 lines.
- **`plugin/skills/script/SKILL.md`'s camera trap,** through `write-skill`, with E4's reason (Q11).
- **`handlers/camera.py`:** `_set_camera_xform`'s docstring, which says a USD write doesn't move the viewport camera
  reliably, goes with the function.
- **`test_project/scenarios.md`:** 3.2, 3.3, 12.4 and 13.5 verify what the live scenarios check.
- **`CHANGELOG.md`,** under Unreleased, below.

| Row | Description and `docs/TOOLS.md` |
|---|---|
| R1 | Replace "USD keeps a prim ... though the answer says deleted, so check with get_scene_tree" with: a prim another layer defines too, or one a reference or payload on a prim above brings, such as a part of a referenced asset, is refused, naming why, and nothing changes; `set_visibility` hides it |
| R2 | Drop "Aiming needs Isaac Sim: other Kit apps only move the camera, without aiming it". TOOLS.md: Isaac Sim's `isaacsim.core.utils.viewports` where it loads, and the camera's own ops elsewhere, in the layer that holds them (the session layer, for Kit's own cameras); `inspect_prim`'s section says the same of its angles |
| R3 | `set_camera`: the answer says when it looks at the origin; an error for a target equal to the position |
| R4 | `set_material`: `opacity`, `roughness` and `metallic` are set on every call, each to its default when left out, so a call without `opacity` makes the material opaque |
| R5 | `dump_scene`: returns the file's path and how many prims it wrote |
| R6 | `start_recording`: TOOLS.md's "One at a time" bullet gains the older extension's `force=True` line |
| R7 | `set_prim_transform`: replace the "rewrites the prim's xform ops ... loses that placement" sentence with: it writes into the prim's own ops, the position into its translate op, the rotation into its rotate or orient op in that op's kind, the scale into its scale op, adding an op it lacks; other ops, a pivot among them, stay; a prim placed by one matrix has that matrix changed; an animated op, or ops a stronger layer holds, such as a Kit camera's, are an error. `create_prim`: "takes the new transform" as `set_prim_transform` writes it |
| R8 | `clone_prim`: replace the "rewritten as set_prim_transform does ... lose that placement" sentence with: with `offset`, copy n moves n times `offset` from the source in the parent's space, its ops and placement kept; the first copy, and a single copy, are left as copied |
| R9 | `get_recording_frame`: `session_dir`'s field and the description: as `start_recording` and `stop_recording` give it, relative to this server's working folder, or an absolute path on Kit's machine |
| R10 | `raycast`: `direction`'s field: any length but zero, where it said "a unit vector: PhysX takes it as given" (E6); the distance is in stage units |
| R11 | `get_scene_tree`: `max_depth`'s field and the description: a prim at `max_depth` that has children says how many, as `children = N (truncated)`; nothing below it is listed |
| R12 | `look_at_prim`, `inspect_prim`: TOOLS.md's answer line says stage units |

`CHANGELOG.md`, under Unreleased:

```markdown
### Fixed

- **`delete_prim` refuses a prim it can't remove, where it answered "Deleted" and the prim stayed:** one another layer
  defines too, or one a reference or payload on a prim above brings, such as a part of a referenced robot. The error
  says which, nothing changes, and `set_visibility` hides such a prim. The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit (#82).
- **`set_camera`, `look_at_prim` and `inspect_prim` aim the camera in every Kit app.** Without Isaac Sim's
  `isaacsim.core.utils.viewports` they wrote the camera's transform into the stage's root layer, which Kit's own
  viewport camera, held in the session layer, ignores: `set_camera` and `look_at_prim` failed with a USD error,
  `inspect_prim` took every angle from where the camera stood, and each left an override of the camera in the root
  layer. A scene camera moved without turning, and `look_at_prim` reset its rotation. They now aim the camera in the
  layer that holds it, as Kit does. In Isaac Sim, a camera looking straight down a Y-up stage's up axis, which Isaac's
  call left at the origin, is aimed too. The fix is in the Kit extension (#82).
- **`set_camera` without a `target` says it looks at the world origin,** where its answer named only the position. A
  `target` equal to `position` is an error, where it answered success with nothing to look at (#82).
- **`set_material` makes a material opaque again with `opacity=1`:** it wrote the opacity only below 1, so a material
  made see-through stayed so. A call that leaves `opacity` out now makes the material opaque, as one that leaves out
  `roughness` or `metallic` sets theirs. The fix is in the Kit extension (#82).
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
  numbers, which they ignored, a zero quaternion, an xform op with animation, whose value they set where the animation
  hides it, and ops a stronger layer holds, such as Kit's viewport camera's, where they failed with a USD error. The
  fix is in the Kit extension (#82).
```

## Risks

| Risk | Status |
|---|---|
| The transform writer serves five tools: a mistake there places prims wrongly everywhere | Accepted: a unit test per op kind, precision, pivot and matrix case; live `test_08b`, `test_21b`, and every live test that creates or moves a prim |
| Converting into another Euler order gives other angles for the same rotation | Accepted: tested by matrix; TOOLS.md says the op keeps its kind |
| The camera's write lands in the root layer and saves a camera override into the user's file | Resolved by E1, E2, E4: `aim` writes the layer that holds the camera's ops, the session layer for Kit's own; unit tests check the root layer gains no spec, and live `test_12f` too |
| The viewport doesn't follow a USD write, as the trap row says | Resolved by E4: it follows the composed transform; 0.2.3's writes were outranked. Live `test_12f` checks the fallback's own write in the viewport's frame |
| Kit's session layer defines prims under `/World`, so the delete check refuses them | Resolved by E7: only Kit's cameras, and overs under `/Render` |
| A stage that went through 0.2.3's fallback keeps an override of Kit's camera in its root layer (E3, E4) | Accepted: outranked by the session layer, so harmless; this change writes none and removes none |
| E6 ran one PhysX build; a zero direction's PhysX answer is unmeasured | Accepted: the server scales the direction and refuses zero, whatever PhysX does (Q13) |
| The stubs type `GetCompositionArcs` as another class and `GetIntroducingLayer` as never `None` | Accepted: typed forms in `core/usd.py`, as for the stubs' other gaps; the baseline doesn't grow |
| Users notice: a recolour makes a material opaque, a relative `session_dir` changes meaning, new refusals | Accepted: CHANGELOG's Fixed and Changed say so (Q3, Q8) |
| Another branch in flight edits CHANGELOG's Unreleased or TOOLS.md | Accepted: rebase on `origin/main` before the PR |
| The GUI, Kit 107 and USD Composer untried | Accepted: the PR says so |

## Plan review

Not reviewed yet: E1 to E8 are in, and round 1 follows.
