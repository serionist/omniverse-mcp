# Tool Reference

Reference for every tool the MCP server provides.

- **Where answers go:** a text answer over 1,000 characters is written to `mcp_output/responses/` and the tool
  returns its path; `get_mesh_stats` and `get_robot_info` write only their long part there, the tree, or the Joints
  list and the joint states that don't fit, and keep the rest inline. Images go to `mcp_output/captures/`, recordings to `mcp_output/recordings/`, and
  `get_scene_tree`'s dump, with properties or a filter, to `mcp_output/scene_dump.txt`, which the next dump replaces.
  A file under the server's working folder is given by its relative path, any other by its absolute path. Open them
  with your client's file tool.
- **Prim blocks:** text about prims comes as a `[/prim/path]` header, then `key = value` lines, so you can grep for a
  path or a property.
- **Known issues** on Isaac Sim 6.2 are in the [README](../README.md#known-issues).

## Find a tool

| To | Use |
|---|---|
| see what is in the scene | `get_scene_tree`; with `include_properties` or a filter, a file of many prims' values |
| see how it looks | `capture_viewport`; `inspect_prim` for one object from several sides |
| read a prim's properties, size or place | `get_prim_properties`, `get_prim_bounds` |
| create, move, copy, hide or delete prims | `create_prim`, `set_prim_transform`, `clone_prim`, `set_visibility`, `delete_prim` |
| colour an object | `set_material` |
| point the camera, at a point or a prim | `set_camera` |
| fix a black capture | `viewport_light` |
| play, pause, stop or step physics | `sim_control`; `get_sim_state` for where it stands |
| add a robot, read and move its joints | `create_robot`, `get_robot_info`, `set_joint_targets` |
| record a run and look back at it | `start_recording`, `stop_recording`, `get_recording_frame` |
| set mass or friction, push, or probe | `set_physics_properties`, `apply_force`, `raycast` |
| count faces and find where they are, or compare two prims or variants | `get_mesh_stats`, `compare_prims` |
| make or switch variants | `create_variant_structure`, `set_variant_selection` |
| write USD files | `save_scene`, `flatten_usd`, `export_prim_as_file`; `update_material_paths` after files move |
| open a USD file as the stage, or start an empty one | `open_scene`, `new_scene` |
| find out why something failed | `get_logs` |
| do anything else in Kit's Python | `execute_script`; `manage_extensions` for Kit's extensions |

Each tool tells the client what it does to the Kit app, as MCP tool annotations. A client may use them to ask before
it runs one; they are hints, never security (the bridge's token is what keeps others out).

| Hints | What they mean | Tools |
|---|---|---|
| read-only | Queries and captures: nothing in the stage, the simulation or the viewport changes (a capture's render of its own is in the stage while it runs, and leaves Kit's unsaved-edits flag set) | `get_scene_tree`, `get_prim_properties`, `get_prim_bounds`, `get_mesh_stats`, `get_robot_info`, `capture_viewport`, `get_sim_state`, `get_recording_frame`, `raycast`, `get_logs` |
| not destructive | Changes that destroy nothing: transforms, new prims, materials, variants, the camera, lights, the simulation | `set_prim_transform`, `create_prim`, `set_material`, `clone_prim`, `set_visibility`, `compare_prims`, `set_variant_selection`, `create_variant_structure`, `create_robot`, `set_joint_targets`, `set_camera`, `inspect_prim`, `viewport_light`, `sim_control`, `start_recording`, `stop_recording`, `set_physics_properties`, `apply_force`, `draw_debug` |
| destructive | Deletes or overwrites prims, the whole stage, or USD files on disk | `delete_prim`, `save_scene`, `open_scene`, `new_scene`, `flatten_usd`, `export_prim_as_file`, `update_material_paths` |
| destructive, open world | Runs Python or loads extensions inside the Kit app: anything can happen | `execute_script`, `manage_extensions` |

`set_physics_properties` deletes one prim of its own: the physics material an extension of 0.3.0 or older gave the
prim, once no prim binds it and after its values have moved into the prim's own. Nothing is lost, so it stays not
destructive.

A value out of a parameter's range, or not one of its choices, is refused before the tool runs.

## Table of Contents

- [Scene Tools](#scene-tools) (11 tools)
- [Geometry & Mesh Tools](#geometry--mesh-tools) (2 tools)
- [USD Operations](#usd-operations) (2 tools)
- [Variant Tools](#variant-tools) (2 tools)
- [Material Tools](#material-tools) (2 tools)
- [Robot Tools](#robot-tools) (3 tools)
- [Camera Tools](#camera-tools) (4 tools)
- [Simulation Tools](#simulation-tools) (2 tools)
- [Recording Tools](#recording-tools) (3 tools)
- [Physics Tools](#physics-tools) (3 tools)
- [Debug Tools](#debug-tools) (1 tool)
- [Extension Tools](#extension-tools) (1 tool)
- [Logging Tools](#logging-tools) (1 tool)
- [Script Execution](#script-execution) (1 tool)
- [MCP Resources](#mcp-resources)

---

## Scene Tools

### `get_scene_tree`

List the stage's prims under `root` as prim blocks: each one's path, type and world position, to `max_depth`. With
`include_properties`, `filter_types` or `property_filter`, Kit writes the blocks to a file instead, with each prim's
values.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/"` | Starting prim path |
| `max_depth` | int | `null` | Levels below `root`, 0 up: 5 when left out, or 15 with properties or a filter |
| `include_properties` | bool | `false` | Each prim's rotation, world box and attribute values, written by Kit to `mcp_output/scene_dump.txt` |
| `filter_types` | list[string] | `null` | Only prims of these types (e.g., `["Mesh", "Xform"]`), written to the file; the others' children are still walked |
| `property_filter` | list[string] | `null` | Only properties whose names hold one of these (e.g., `["joint"]`), written to the file; it takes the properties with it |

**The list,** when none of `include_properties`, `filter_types` or `property_filter` is given (an empty list counts as
not given): each prim's path, type and world position, answered inline, or written to
`mcp_output/responses/scene_tree_NNNN.txt` when over 1,000 characters. A prim at `max_depth` that has children says
how many, as `children = N (truncated)`, and nothing below it is listed. An extension of 0.2.3 or older lists instead
the next level's prims that have children, and leaves out the rest of that level.

**The file,** with `include_properties`, or a `filter_types` or `property_filter` that isn't empty: Kit writes the
blocks to `mcp_output/scene_dump.txt`, replacing the last, and the answer gives its path, how many prim blocks it
holds, which the file's header says too, and how deep it went: `Dumped 120 prims under /World, to depth 15 (48,213
bytes) -> mcp_output/scene_dump.txt`. Its blocks don't mark a prim whose children were left out.

- Each block holds the prim's type, world position, rotation, world box and physics flags, and every attribute's
  value with `include_properties`, or those `property_filter` names.
- `filter_types` alone writes those flags and boxes for the types it names, without attribute values. Over every type
  that form has no call of its own: `include_properties=True` gives the full blocks, `get_prim_bounds` one prim's box.
- Kit writes the file itself, so with Kit on another machine it lands there. An extension of 0.2.3 or older counts
  every prim on the stage.
- The output is in prim-block format: grep for prim paths or property names, or read it in parts.

Neither lists the prims inside an instanceable prim, as Isaac Sim's robot assets often are: `get_mesh_stats` looks
inside.

**When to use:** to find prim paths before acting on them; the list is the lightest look at a scene. The file is for
many prims' values at once; `get_prim_properties` reads one prim inline.

---

### `get_prim_properties`

Get one prim as a prim block: its type, world position and rotation, world bounding box, physics flags, and every
attribute's value.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path (e.g., `"/World/Robot"`) |

**Returns:** Prim type, position, bounding box, and all USD properties. Relationships, such as a material binding, are
named without their targets. The world rotation, `rot`, is a quaternion `w, x, y, z` with any scale and shear taken
out, so a 45° turn reads as 45° at any scale; a prim scaled to 0 on an axis, or so near it, under about 1e-15 of
its other axes, that double precision can't tell its rotation, has no `rot` line. `get_scene_tree`'s file and `start_recording`'s `state.txt` give the same line. With an extension of 0.3.0 or
older, a scaled prim's `rot` is off: Kit read it with the scale left in.

**When to use:** to read one prim. `get_prim_bounds` when only its size and place matter, `get_scene_tree` to find
paths, and with `include_properties` for many prims at once, written to a file.

---

### `get_prim_bounds`

Get a prim's world-space, axis-aligned bounding box, its descendants included.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path |

**Returns:** Centre, dimensions, min/max corners, and diagonal length, in the stage's units. Essential for spatial reasoning - computing placement positions, checking overlaps, measuring distances.
A prim with no geometry, such as an empty Xform, gets a 0.1 box at its position rather than an error.

---

### `set_prim_transform`

Set a prim's position, rotation or scale relative to its parent.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path |
| `position` | list[float] | `null` | `[x, y, z]` relative to the parent, in the stage's units |
| `rotation` | list[float] | `null` | Euler `[rx, ry, rz]` in degrees, or quaternion `[w, x, y, z]` |
| `scale` | float or list[float] | `null` | Uniform (single float) or per-axis `[sx, sy, sz]` |

Only provided parameters are changed; others are preserved.

- **Local, not world:** values are in the parent's space; `get_prim_properties` gives a prim's world position.
- **Its xform ops:** it writes into the prim's own ops, as Kit's Property panel shows them, and keeps every other op
  where it is, a pivot, Kit's `:unitsResolve` ops and `!resetXformStack!` among them:
  - the position into the prim's `xformOp:translate`, which a pivot turns and scales the prim about;
  - the rotation into its rotate or orient ops, in their kind: Euler angles into a `rotateXYZ` op and a quaternion into
    an `orient` op as given, either converted into an op of the other kind or another Euler order, and into Kit's
    `[rotateZ, rotateY, rotateX]` split across the three. A single-axis op alone, or another mix of rotate ops, is
    replaced in its place by one `rotateXYZ` or `orient`;
  - the scale into its `xformOp:scale`;
  - a part with no op of its own into the prim's matrix (`xformOp:transform`) when it has one, as imported assets often
    do; else a new op: translate first, rotateXYZ or orient before the scale, scale before an inverse pivot.
- **Errors, with nothing written:** a prim that doesn't exist, or one that can't be transformed; a rotation that isn't
  3 or 4 numbers, or a zero quaternion; an op with animation (time samples), whose value set here would be hidden, or
  would freeze the animation of a weaker layer, such as an asset's; ops a stronger layer holds, such as a Kit camera's,
  in its session layer, where a value set in the stage's layer wouldn't show; a rotation or scale on a matrix that
  can't be factored, a singular one such as a scale of 0 leaves.
- **An extension of 0.2.3 or older** rewrites the ops as translate, rotateXYZ (orient for a quaternion) and scale, and
  drops every other op: a pivot goes, can be read as the position, and a prim placed by a matrix loses that placement.

**When to use:** to move, turn or size a prim. To aim the viewport camera, use `set_camera`; to push a rigid body
while physics runs, `apply_force`.

---

### `create_prim`

Create a new prim in the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Where to create (e.g., `"/World/MyCube"`) |
| `prim_type` | string | `"Xform"` | USD type: `Cube`, `Sphere`, `Cylinder`, `Cone`, `Capsule`, `Xform`, `Camera`, `DistantLight`, `SphereLight`, etc. |
| `usd_path` | string | `null` | Reference a USD file instead: an absolute path on Kit's machine, a URL, or a path relative to the stage's file; brought to the stage's up axis and units as `create_robot` brings a robot file |
| `position` | list[float] | `null` | `[x, y, z]` relative to the parent |
| `rotation` | list[float] | `null` | Euler or quaternion |
| `scale` | float or list[float] | `null` | Scale |
| `enable_physics` | bool | `false` | Add RigidBody + Collision APIs |

A prim already at `prim_path` keeps its type: creating one of another type there is refused, and one of the same type
takes the new transform, written into its own ops as `set_prim_transform` writes it. A transform it can't write makes
nothing: a malformed one is refused before the prim is made, and one refused once it is there (an animated op in a
referenced file, say) takes away what the call made. A `usd_path` adds its reference to a prim already there, and takes
it away again when the transform is refused. A `usd_path` that can't be opened is an error, and nothing is made; a
relative one is read beside the stage's file, as the reference reads it. Missing parents are made as typeless prims.
`enable_physics` puts both APIs on the prim itself, so a shape falls and collides while the simulation plays; the
meshes under an Xform or a referenced file's root get no Collision API of their own.

**Up axis and units:** a `usd_path` file whose `upAxis`, `metersPerUnit` or `kilogramsPerUnit` isn't the stage's is
brought to the stage as `create_robot` brings a robot file, and as Kit's metrics assembler brings a dropped one: turned
upright in `xformOp:rotateX:unitsResolve`, scaled to its real size in `xformOp:scale:unitsResolve`, and its physics
values and its cameras' distances converted to the stage's units. `create_robot`'s Up axis and Units paragraphs give
the detail, the values left as they are among it. The answer says what was done. A file whose root has no
transform, typeless or a `Scope`, as many of Isaac Sim's assets have it, is made an `Xform` in the stage's layer to
hold the ops; a root of another type USD gives no transform, such as a `Material`, holds nothing a turn or a scale
would move, and gets neither. A payload inside the file that isn't loaded has its values left in the file's units,
and loading it later brings them in so; Kit loads payloads when it opens a stage.

- **The frame it lands in:** a file made inside an asset already brought to the stage, by either tool or by Kit's drop,
  is measured against the frame that asset's `:unitsResolve` ops make, as Kit measures it: a metre part under a metre
  robot on a centimetre stage needs no scale of its own, and a Z-up part under a turned Z-up robot no turn. A prim's
  own scale is the user's and doesn't change the frame. Its physics values are still converted to the stage's units.
  A file of the stage's own axis inside a turned asset is turned back and stands upright, where Kit's assembler
  leaves it lying down. Kit's change listener, resolving again an asset its drop made when a prim under it is made,
  writes its own values into a layer first among the root layer's sublayers: the stage's own layer, where
  `create_prim` writes, outranks it, but with a sublayer as the edit target Kit's value may show instead and lay the
  file down.
- **A prim already there** gets the reference as the file is, unturned and unscaled, its physics values in the file's
  units: the prim may hold other content, which a turn or a scale would move too. The answer says what the file's
  content needs beside the frame inside the prim, and which values stay in the file's units. The reference stays on
  the prim; to have the file brought instead, take it off with `execute_script`, as the answer shows, then
  `create_prim` at a new path, such as one under the prim. `create_prim` again on a prim it made from the same file,
  to move it, turns and scales nothing a second time.
- **`position`, `rotation` and `scale`** stay in the parent's frame, outside the units ops: `scale=2` makes the file
  twice its real size.
- A file that authors neither is left as it is, wherever it lands. With an extension of 0.3.0 or older, nothing is
  turned or scaled.

**When to use:** Creating geometric shapes, lights, cameras, or loading external USD assets. To copy a prim, use
`clone_prim`; for a robot, `create_robot`.

---

### `delete_prim`

Delete a prim and everything under it, by removing what the stage's edit layer holds at that path.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path to delete |

- **What it can't delete:** a prim another layer defines too (a sublayer, or Kit's session layer), or one a reference,
  payload, inherit, specialize or variant on a prim above brings, such as a part of a referenced asset. The call is
  refused, saying which, and nothing changes. `set_visibility` hides such a prim; for a prim inside an instance, the
  error names the instance, which `set_visibility` hides whole. A prim that references a file is deleted with its
  reference.
- **An extension of 0.2.3 or older** answers "Deleted" for such a prim and leaves it, with what the edit layer held of
  it removed: the answer then adds "This Kit extension, older than the server, answers deleted for a prim another
  layer keeps: check with get_scene_tree".

Kit's undo doesn't record the delete, and the file on disk keeps the prim until `save_scene`.

---

### `clone_prim`

Copy a prim with everything under it to a new path, once or as a row of `count` copies. A target path that
already holds a prim is refused, before anything is copied.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | string | required | Prim to clone |
| `target_path` | string | required | Destination path |
| `count` | int | `1` | Number of copies, at least 1. One goes to `target_path`; more go to `target_path_001`, `_002`, ... |
| `offset` | list[float] | `null` | `[x, y, z]` per-copy offset, in the parent's space. The first copy sits on the source, and each next one shifts by this amount from the previous, so a single copy never moves. |

It copies what the stage's root layer holds at `source_path`, its references included, so a prim from a sublayer, or
from inside a referenced asset, can't be copied whole. With `offset`, copy n moves n times `offset` from the source in
the parent's space, through its own translate op, or its matrix for a prim placed by one, its other ops and placement
kept; the first copy, and a single copy, are left as copied. A source whose position can't be written, such as an
animated translate, is refused before anything is copied. An extension of 0.2.3 or older rewrites the moved copies',
and a single copy's, xform ops as translate, rotate and scale, so copies of a prim placed by a matrix or about a pivot
lose that placement.

**Example:** Clone a cube into a row of 5, the first on the cube and each 2 further along x:
```
clone_prim("/World/Cube", "/World/CubeRow", count=5, offset=[2, 0, 0])
```

---

### `set_visibility`

Show or hide a prim and its descendants, in the viewport and in captures; the prim stays in the stage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `visible` | bool | `true` | `true` to show, `false` to hide |

Showing a prim under a hidden parent shows the parent and hides the parent's other children, as USD's `MakeVisible`
does. A prim that has no visibility, such as a material, is an error.

**When to use:** to see inside or behind something, then show it again. `delete_prim` removes a prim, and
`inspect_prim`'s `isolate` hides all but one prim for its captures.

---

### `save_scene`

Write the open stage's root layer to a USD file: back to the stage's own file, or as a copy at `file_path`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | `""` | Destination path, on Kit's machine; never another file the open stage has loaded. If empty, saves to the current file (overwrite). |

- **Without `file_path`:** it overwrites the file the stage was opened from, and fails for a stage never saved, such as
  `new_scene`'s.
- **With `file_path`:** it overwrites any file there, and the stage stays tied to its own file, or to none, so a later
  `save_scene()` without a path still writes there, or fails.
- **Another file the open stage has loaded is refused** before anything is written: a sublayer, its session layer, or
  a referenced or payload file it has loaded. Writing the root layer there would replace a file the open scene is made
  of, while Kit kept that layer as it was. The path is compared as `flatten_usd`'s `output_path` is: as USD takes it,
  and for a file that exists as the file system does, a link or a `file:` URL included. The stage's own file, by any
  of those names, is a save. A file Kit holds outside the open stage with unsaved edits is refused too, since writing
  it would lose them; one with none is read again after the write, so the next open gets the new file.
- **Only the root layer** is written: sublayers and referenced files stay as they are, still referenced. For one
  self-contained file, use `flatten_usd`; for one prim's subtree, `export_prim_as_file`.

---

### `open_scene`

Open a USD file as the stage, in place of the open one, which goes with its unsaved changes: call `save_scene` first
to keep it. `new_scene` starts an empty stage instead.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | The USD file: a path on Kit's machine, a URL, or a path in Isaac Sim's asset library |

- **Paths, as `create_robot` reads them:**
  - a path on Kit's machine; a relative one is read from the folder Kit was started in, as `save_scene` writes one;
  - a URL as given: `omniverse://`, `https://`, `file:///`;
  - a path in Isaac Sim's asset library, such as `/Isaac/Environments/Simple_Room/simple_room.usd`, under the
    library's root (Isaac Sim only).
- **Refused, with the open stage kept:**
  - a file that isn't there, or a URL Kit can't reach;
  - a type USD doesn't open (`.usd`, `.usda`, `.usdc` and `.usdz` do, and whatever Kit's plugins add, such as
    `.obj` or `.gltf` in Isaac Sim);
  - a local file that holds no USD, such as a Git LFS pointer;
  - a library path when Isaac Sim's asset library can't be found;
  - a call while Kit opens or closes a stage.
- **A file that passes those checks and still fails to load leaves no stage open:** Kit closes the open stage before
  it reads the file, as its own File > Open does. The error says so; `open_scene` another file, or `new_scene`.
- **On the way:** the simulation is stopped first; a recording that runs stops taking frames, and `draw_debug`'s
  drawings go. Opening the stage's own file reloads it from disk.
- **Time:** the checks take at most 20 s and the open 80 s; a small file opens in under a second, Isaac Sim's
  `simple_room.usd` over HTTPS in about 2.5 s. An open past 80 s goes on in Kit after the error: no stage is open
  until it has, so tools that read the stage fail, and `get_sim_state` answers once it has opened.
- **An extension of 0.2.2 or older** has no `open_scene`: the error says the Kit extension is older than this MCP
  server, with the command that installs this release's extension; then restart Kit.

**Returns:** `Opened` with the path or URL handed to Kit, `replaced` with the stage it replaced (`an unsaved stage`
for one never saved), then `up_axis`, `meters_per_unit`, `default_prim` and `prim_count`, as `get_sim_state` reports
them. A `note` line each:

- a file that sets no `upAxis` or `metersPerUnit`: USD reads them as Y and 0.01, centimetres;
- a `.usdz`, which can't be saved back: `flatten_usd`, or `save_scene` with a `.usd` or `.usda` `file_path`;
- a stage Kit calls read-only, such as an `https://` URL's: `save_scene` needs a `file_path`;
- the simulation was playing or paused, and is stopped now.

A recording that stopped gives its `recording_note`, as `get_sim_state` does.

---

### `new_scene`

Discard the open scene, unsaved changes too, and start an empty one with a `/World` prim. The new stage is Y-up.
`create_robot` stands Isaac Sim's Z-up robots upright on it, but Isaac Sim's other assets and its stages are Z-up:
for robot work, open a Z-up stage with `open_scene` or set the axis with
`execute_script` (`UsdGeom.SetStageUpAxis(omni.usd.get_context().get_stage(), UsdGeom.Tokens.z)`) before adding
anything. Call `save_scene` first to keep the old stage. The new stage has no file, so `save_scene` needs a `file_path`
for it. A recording that runs stops taking frames, and `draw_debug`'s drawings go.

No parameters.

---

## Geometry & Mesh Tools

### `get_mesh_stats`

Count the faces, vertices and triangles of every mesh at or under a prim: the totals, then the prims under it to
`max_depth`, each mesh with its counts and each prim above meshes with `subtree_faces`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Prim to analyse (includes all descendant meshes) |
| `max_depth` | int | `2` | Levels of the tree below `prim_path` to list, 0 up; 0 for `prim_path` alone |

**Returns:** the totals, then the tree:

```text
[/World/Franka]
meshes = 25
total_faces = 120000
total_vertices = 60000
total_triangles = 240000

# face_count_tree root=/World/Franka
[/World/Franka]
type = Xform
subtree_faces = 120000
...
```

- **The totals** count every mesh at or under `prim_path`, and always come inline.
- **The tree** lists `prim_path`, its children and theirs to `max_depth`: each mesh with `faces`, `vertices` and
  `triangles`, each prim above meshes with `subtree_faces`. Prims below `max_depth` aren't listed, but count in the
  totals and in their ancestors' `subtree_faces`; a deeper call costs Kit no more, since the whole subtree is counted
  at any depth. When the whole answer passes 1,000 characters, the tree goes to
  `mcp_output/responses/mesh_stats_NNNN.txt`, a line giving its path, and the totals stay inline.
- **Only `UsdGeom.Mesh` prims count,** inside instances too, which `get_scene_tree` doesn't list: implicit shapes such
  as `Cube` and `Sphere` have no faces. A mesh without face data is in the tree with 0 faces, and not in the totals.

**When to use:** checking a geometry budget, what a simplification saved, or where the faces are: a heavy subtree is
the next call's `prim_path`. `compare_prims` puts two prims or variants side by side.

---

### `compare_prims`

Compare two prims or two variants: mesh counts, bounds, materials.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path_a` | string | `""` | First prim (mode 1: direct comparison) |
| `prim_path_b` | string | `""` | Second prim (mode 1) |
| `prim_path` | string | `""` | Prim with variants (mode 2: variant comparison) |
| `variant_set` | string | `""` | Variant set name (mode 2) |
| `variant_a` | string | `""` | First variant name (mode 2) |
| `variant_b` | string | `""` | Second variant name (mode 2) |

**Returns:** Side-by-side stats (faces, vertices, triangles, meshes, bounds, materials), then B minus A, each with
its own sign, and the change in faces as a percentage when A has faces; from 0 faces it says `A has 0 faces`.

Mode 2 wins when all four of its parameters are given. It switches the selection to each variant in turn, then back to
the one before. A variant name is not checked: one not in the set measures the prim with none of the set's variants.

**When to use:** Checking what a simplified copy or another variant changed. Bounds are measured afresh after each
variant switch. For one prim's counts, use `get_mesh_stats`.

---

## USD Operations

### `flatten_usd`

Write a stage flattened into one USD file: its references, payloads and sublayers resolved into a single layer.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_path` | string | required | Where to write the flattened USD file, on Kit's machine; a file there is overwritten, but never one the open stage has loaded |
| `input_path` | string | `""` | Source USD file (default: the open stage, unsaved edits included) |

**Returns:** Input/output paths and number of layers resolved.

Textures and other files the stage points at are not copied.

- **Kit's session layer is left out,** as Kit's own File > Save Flattened As leaves it out: what Kit keeps for the
  session and never saves, such as the viewport's light rig, a light mode's hiding of the stage's own lights, and
  Kit's own cameras. The open stage is flattened from its root layer and the layers under it, unsaved edits included;
  a muted sublayer and a payload it hasn't loaded stay out of the file, and so does an edit made while the session
  layer was Kit's edit target, as with Kit's own command. An extension of 0.3.0 or older wrote the
  session layer in too: a flatten in a light mode such as Default gave a file lit by the rig, with the scene's own
  lights hidden.
- **An `input_path` Kit has loaded** is flattened as Kit holds it, unsaved edits included, and the open stage is left
  as it is: its own file, a sublayer, or a referenced or payload file. A file Kit holds that the open stage doesn't use
  is read again from disk first, unless it has unsaved edits, so a file changed since Kit loaded it is flattened as it
  is now. One USD can't open, with no file there or none it reads, is an error.
- **An `output_path` the open stage has loaded is refused** before anything is written: its own file, a sublayer, its
  session layer, or a referenced or payload file it has loaded (an unloaded payload's file or a muted sublayer's isn't
  one). Writing it would replace a file under the open scene. The path is taken as USD takes it (relative, `..`, either
  slash) and, for a file that exists, as the file system does: another case on Windows or a Mac, a link to it under
  any name, or a `file:` URL. Name another path, or use `save_scene` to save the open stage to its own file. A file Kit
  holds outside the open stage with unsaved edits is refused too, by its own file name rather than through a link,
  since writing it would lose them; one with none is read again after the write, so the next open gets the new file.

**When to use:** Before modifying a component (flatten first so all references are resolved), preparing a file for external tools.
`save_scene` keeps the references and writes only the root layer; `export_prim_as_file` writes one prim's subtree.

---

### `export_prim_as_file`

Export a prim subtree as a standalone USD file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root of the subtree to export |
| `output_path` | string | required | Destination file (.usd, .usda or .usdc; .usdc by default); never one the open stage has loaded |

**Returns:** Output path, target root prim name, material count, up axis.

Flattens the source (resolves all references) and includes materials even if they live outside the exported subtree. Output is self-contained and can be imported into Blender or other DCC tools.
The prim becomes `/<its name>` and the file's default prim, with the stage's up axis and units. `output_path` is on
Kit's machine and is overwritten; textures and other files the subtree points at are not copied. As with
`flatten_usd`, Kit's session layer is left out, so a light Kit's light mode hides is written as the scene has it, and
an `output_path` the open stage has loaded is refused before anything is written, and so is one Kit holds with unsaved
edits; a file Kit holds without any is written and read again. An error too when the prim doesn't exist, or comes from
Kit's session layer alone, as Kit's own cameras and the viewport's light rig do.

---

## Variant Tools

### `set_variant_selection`

Select a variant in a prim's variant set, and wait until the viewport shows it. The set and the variant must exist:
an error lists the ones there.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Prim with variant sets |
| `variant_set` | string | required | Name of the variant set (e.g., `"model"`) |
| `variant_name` | string | required | Variant to select (e.g., `"shell"`) |

**Returns:** Old and new selection, available variants.

**Important:** switch variants with this tool, not `execute_script`: a variant switched in a script can leave the
old geometry in the viewport, and this tool refreshes it.

---

### `create_variant_structure`

Add a variant set of empty variants to a prim and select one, ready to fill and to switch between with
`set_variant_selection`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `variant_set_name` | string | required | Name for the new variant set |
| `variant_names` | list[string] | required | List of variant names to create (e.g., `["focused", "shell"]`) |
| `default_variant` | string | `""` | Which variant to select (default, or a name not in the list: the first in the list) |

**Returns:** Prim path, variant set name, created variants, default selection.

A set or variant that already exists is kept and added to, never replaced. The variants hold nothing until you author
into them, with `execute_script`.

---

## Material Tools

### `set_material`

Colour a prim with an OmniPBR material: make the material, or update the one at its path, set its colour and surface
values, and bind it to the prim in place of its binding. The binding reaches the prim's children unless they have
bindings of their own.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `color` | list[float] | required | `[r, g, b]` diffuse colour. 0-1 floats or 0-255 ints (auto-detected) |
| `opacity` | float | `1.0` | 0.0 (transparent) to 1.0 (opaque); nothing outside that |
| `roughness` | float | `0.5` | 0.0 (glossy) to 1.0 (matte); nothing outside that |
| `metallic` | float | `0.0` | 0.0 (plastic) to 1.0 (metal); nothing outside that |
| `material_path` | string | `""` | Custom material prim path (`/World/Looks/<prim name>_Mat` if omitted) |

`opacity`, `roughness` and `metallic` are set on every call, each to its default when left out, so a call without
`opacity` makes the material opaque; the answer gives all three. An extension of 0.2.3 or older writes the opacity only
below 1, so a material it made see-through stays so. Without `material_path`, prims of the same name share one material,
so colouring one recolours the rest: give `material_path` to keep them apart, or to share one on purpose. For friction
and bounce, use `set_physics_properties`; to repoint bindings after materials move, `update_material_paths`.

---

### `update_material_paths`

Rewrite every path under a subtree that starts with `old_prefix` to start with `new_prefix` instead.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `old_prefix` | string | required | Path prefix to find, matched as text (e.g., `"/OldProject/Materials/"`) |
| `new_prefix` | string | required | Replacement prefix (e.g., `"/World/Materials/"`) |
| `prim_path` | string | `"/"` | Root of subtree to update (default: entire stage) |

**Returns:** Number of updated references and list of affected prims.

Updates both relationship targets, such as material bindings, and asset path attributes, such as texture files, that
start with `old_prefix`. It isn't limited to materials: any relationship or asset path that matches changes, a joint's
bodies or a shader's source file among them, so end the prefix with `/` and keep it specific. Nothing checks that the new paths
exist. Kit's undo doesn't record the change, and a failure part way keeps the edits made before it.

**When to use:** After copying USD assets to a new directory where material paths need updating.

---

## Robot Tools

### `create_robot`

Add a robot: one of Isaac Sim's by name (Isaac Sim only), or any robot from its USD file, in any Kit app.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `robot_type` | string | required | A robot name from the table below, or a USD file |
| `prim_path` | string | `""` | Scene path (auto-generated if empty) |
| `position` | list[float] | `null` | `[x, y, z]` spawn position |
| `rotation` | list[float] | `null` | Euler or quaternion |

**Available robots:**

| Name | Type | Description |
|------|------|-------------|
| `franka` | Manipulator | Franka Emika Panda 7-DOF arm |
| `ur10` | Industrial arm | Universal Robots UR10 |
| `carter` | Wheeled | NVIDIA Carter wheeled robot |
| `jetbot` | Wheeled | NVIDIA JetBot |
| `g1` | Humanoid | Unitree G1 humanoid (43 DOF) |
| `go1` | Quadruped | Unitree Go1 |
| `go2` | Quadruped | Unitree Go2 |
| `h1` | Humanoid | Unitree H1 humanoid |
| `spot` | Quadruped | Boston Dynamics Spot |
| `anymal` | Quadruped | ANYbotics ANYmal |

A USD file as `robot_type` loads from a path on the Kit app's machine, a URL (`omniverse://`, `https://`), or a
path in Isaac Sim's asset library (`/Isaac/...`), which goes under the library's root; its case is kept. Without
`prim_path`, the prim is named after the file: `/World/MyBot` for `.../MyBot.usd`. A file that can't be opened
is an error, and so is a prim already at `prim_path`. `position` and `rotation` go into the robot's own root ops, as
`set_prim_transform` writes them; a malformed one is refused before the robot is added, and one refused after it (an
animated root op in the file) takes the robot away again.

**Up axis:** a file whose `upAxis` isn't the stage's is stood upright on it, as Kit's metrics assembler stands a
file dropped on the stage: a turn about X in `xformOp:rotateX:unitsResolve`, -90 for a Z-up file on a Y-up stage and
+90 the other way, before any inverse op on the robot's root, else last. Every robot of the table above is Z-up, so
each is turned on a Y-up stage. `position` and `rotation` stay in the stage's frame, outside the turn:
`rotation=[0, 90, 0]` on a Y-up stage turns the standing robot about Y. A file whose root holds that op already, as
one Kit resolved and saved, gets the turn added to it. A file that authors no `upAxis` is left as it is. The answer
says when it turned one, the turn added and the op's value after. `set_prim_transform` keeps the op where it is.
With an extension of 0.3.0 or older, nothing is turned, and a library robot lies on its side on a Y-up stage.

**Units:** a file whose `metersPerUnit` or `kilogramsPerUnit` isn't the stage's is brought to the stage's units, as
Kit's metrics assembler brings a dropped file with its physics rules, so it behaves as the same robot authored in
them:

- **The scale:** a file of other `metersPerUnit` is scaled by file over stage in `xformOp:scale:unitsResolve`, a
  double op after the turn upright, before any inverse op, else last: a metre robot on a centimetre stage reads 100.
  A file whose root holds that op already, as one Kit resolved and saved, gets it multiplied.
- **The physics values:** converted by the PhysX schema's table of units, the one Kit's physics rules read: masses
  from a density, inertia, drives, prismatic limits and targets, contact offsets and the rest. Each value is taken in
  the units of the layer it is authored in; a sublayer that authors none, in its file's, and a file the robot
  references that authors none, in the robot file's. A file of other `kilogramsPerUnit` has its masses, inertia and
  forces converted and nothing scaled.
- **Cameras:** a camera's `focusDistance` and `clippingRange` are converted too, as Kit's camera rules convert them.
- **Left as they are:** an angular acceleration drive's stiffness and damping, which hold no distance, where the table
  gives them square metres, which would hold the joint rigid on a centimetre stage. PhysX then holds the same gains
  and inertia, in stage terms, as for the robot authored in the stage's units, yet it settles such a drive further
  on a centimetre stage: an arm that sagged 0.169 rad on a metre stage sagged 0.262 on a centimetre one. So an angular
  acceleration drive isn't shown to behave as in the stage's units; force drives do. Also left: values inside
  instances, which no layer of the stage can override, as Kit leaves them, and values animated by value clips or
  splines, and the answer names them; a file that authors neither unit, taken in the stage's units, as Kit takes it;
  a file nested inside the robot's, of units of its own, gets no scale of its own.
- **Where they go:** the stage's layer, with the robot. A later change to those values in the robot's file no longer
  shows, and a drive target the file animates wins over `set_joint_targets`, whose value goes into the same layer,
  where the converted samples are stronger.
- **The answer** says when: the two units, the factor, the op's value after, how many values were converted, and those
  left. A Kit app without the PhysX schema changes only the scale and the cameras, and the answer says so. With an
  extension of 0.3.0 or older, nothing is scaled.

**The frame it lands in:** a robot made inside an asset already brought to the stage is turned and scaled against the
frame that asset's `:unitsResolve` ops make, as `create_prim`'s Up axis and units paragraph says, so it isn't turned
or scaled a second time; the answer names the frame. `create_prim` brings a `usd_path` file the same way.

---

### `get_robot_info`

Read a robot: its structure from USD, at any time, and where its joints are from physics, while the simulation plays
or is paused.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |

**Returns:** the robot's path, whether it is an articulation, its DOF and link counts, then two lists:

- **Joints,** from USD: each joint's name, type, limits and drive. Limits are as USD holds them: degrees for revolute
  joints, stage units for prismatic ones. They come in the order a list of `set_joint_targets` follows, fixed joints
  included; the DOF count leaves fixed joints out.
- **Joint states,** from physics: each degree of freedom's name, position and velocity, in physics' own order. Radians
  and radians per second for revolute joints, stage units and stage units per second for prismatic ones;
  `set_joint_targets` takes degrees for revolute joints. They are the first articulation's at or under `prim_path`,
  found as `UsdPhysics.ArticulationRootAPI` marks it, and read through Isaac Sim's
  `isaacsim.core.experimental.prims.Articulation`, which Isaac Sim 5.1 and 6.x ship; tested live on 6.2 and 5.1. The
  tool never starts physics itself.

```text
Robot: /World/Franka
Articulation: True
DOF: 9
Links: 11
Joints (12):
  panda_joint1 (PhysicsRevoluteJoint [-166.0, 166.0] drive=angular)
  ...
Joint states (9 DOF, from physics: radians for revolute joints, ... set_joint_targets takes degrees):
  panda_joint1: pos=0.0000 vel=0.0000
  ...
```

- **No joint states:** stopped, with no articulation under `prim_path`, or in a Kit app without Isaac Sim, such as USD
  Composer, the structure comes with one line in place of the joint states, `Joint states: not read:` and why, such
  as `No physics view of /World/Franka: play or step the simulation first`. Only a prim that isn't there, or a Kit app
  that can't be reached, is an error.
- **Long answers:** the header lines always stay inline. When the whole answer passes 1,000 characters, as a Franka's
  does, the Joints list goes to `mcp_output/responses/robot_info_NNNN.txt`, a line giving its path, and the joint
  states, or their `not read` line, stay inline; joint states that pass 1,000 characters with the header, as a G1's
  43 do, go to the file too, after the Joints list.

**When to use:** before driving a robot, whatever the simulation's state, and to see where its joints are now.

---

### `set_joint_targets`

Set the position targets of a robot's joint drives, which physics drives the joints toward while the simulation plays.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |
| `targets` | dict or list | `null` | Required in practice: `{joint_name: value}` dict or `[v0, v1, ...]` list. Values in degrees (revolute) or stage units (prismatic). |

Works by setting USD drive target attributes directly - does not require articulation initialisation, or physics
running. A dict sets the joints it names and skips names it doesn't find; a list follows the order of
`get_robot_info`'s Joints list, fixed joints included, not of its joint states. A joint without a drive gets one, with
stiffness 1000 and damping 100. The answer counts the targets set.

---

## Camera Tools

### `set_camera`

Move the viewport's camera and aim it, at a world point or at a prim. The parameters say which: `position` for a
point, `prim_path` for a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `position` | list[float] | `null` | `[x, y, z]` where the camera stands, in world space: for a point |
| `target` | list[float] | `null` | `[x, y, z]` the world point it looks at, the world origin when left out: for a point |
| `prim_path` | string | `""` | A prim to frame instead: the camera aims at the centre of its world box |
| `distance` | float | `null` | From the prim's centre in stage units, above 0; 2.5 times its largest side when left out |
| `azimuth` | float | `null` | Degrees around the prim: 0 the front (+Y on a Z-up stage, +Z on a Y-up one), 90 the right (+X), 180 the back, 270 the left; 45 when left out |
| `elevation` | float | `null` | Degrees above the horizontal; 30 when left out |

- **A point:** `position`, and `target`, the world origin when left out. The answer is `Camera at [5, 3, 5] looking
  at [0, 0, 0]`; without a `target` it adds `, the world origin: no target was given`. A `position` equal to the
  point it looks at, its `target` or the origin, is an error.
- **A prim:** `prim_path`, and the camera goes around the centre of the prim's world box at `distance`, `azimuth` and
  `elevation`, aimed at that centre. The answer names the prim and the centre, `Camera at [3.0619, 3.0619, 3.0]
  looking at the centre of /World/Cube, [0.0, 0.0, 0.5]`, then the distance in stage units and the two angles. A prim
  that doesn't exist is an error.
- **A mix of the two is refused before the camera moves,** with an error saying what to drop: `prim_path` with
  `position` or `target` (to aim from a point at a prim, `get_prim_bounds` gives its centre), or `distance`, `azimuth`
  or `elevation` without `prim_path`. So is a call with neither `position` nor `prim_path`.

It moves whichever camera the viewport looks through, a scene camera included, and the user sees the move. Aiming
goes through Isaac Sim's `isaacsim.core.utils.viewports` where it loads, and through the camera's own ops elsewhere,
in the layer that holds them: Kit's session layer for Kit's own cameras. An extension of 0.2.3 or older aims only in
Isaac Sim.

**When to use:** for a view from coordinates you choose, or of one prim given only its path. `inspect_prim` captures
a prim from up to 14 sides in one call; to capture from another camera without moving the viewport,
`capture_viewport`'s `camera_path`.

---

### `inspect_prim`

Orbit-capture: take screenshots from 14 systematic angles around a prim using a cube-based approach (6 face centres + 8 cube corners). The camera distance is fitted so the prim's bounding sphere fills the captured frame with a 10px margin, at `width` x `height`. Optionally includes instance segmentation at each angle.

The orbit moves whichever camera the viewport looks through, a scene camera included, as the user sees, and leaves it at
the last angle; each angle is rendered from that camera at `width` x `height` in a render of the call's own, as
`capture_viewport`'s is. It aims the camera at each angle as `set_camera` does, Kit's own camera in Kit's session layer;
an angle it can't aim says why. An extension of 0.2.3 or older aims only in Isaac Sim, so elsewhere every angle shows
the view the camera had. The first line gives the distance in stage units and the size; with an extension of 0.2.2 or
older, whose images are the viewport's size, a `WARNING` says so when it isn't the size asked for, with the command that
installs this release's extension.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `angles` | list[string] | all 14 | Angle names to capture (see below) |
| `width` | int | `640` | Image width per capture, 1 to 4096; the camera is rendered at this size |
| `height` | int | `480` | Image height per capture, 1 to 4096 |
| `zoom_offset` | float | `0.0` | Adjust the fitted distance: `-0.3` is 30% closer, `0.5` is 50% further; must be greater than `-1` |
| `isolate` | bool | `false` | Hide everything but the prim while capturing (lights stay on); visibility is restored exactly afterwards. What it cannot hide (inside an instance, or with time-sampled visibility) is listed as `WARNING (isolate)` |
| `include_segmentation` | bool | `false` | Also capture instance segmentation at each angle |

**Available angles (14 total):**

*Face centres (6):* `front`, `back`, `right`, `left`, `top`, `bottom`

*Cube corners (8):* `top_front_right`, `top_front_left`, `top_back_right`, `top_back_left`, `bottom_front_right`, `bottom_front_left`, `bottom_back_right`, `bottom_back_left`

Each angle is saved as a separate PNG file. An all-black angle gets `capture_viewport`'s warning, once a call; so does lighting that lights nothing, mode `off` or `stage` with no scene lights, though the images show Kit's grid. When `include_segmentation` is true, each angle also saves a segmentation image + legend; an angle without one says why (`seg: ERROR`), such as no data within 5 s of the sensor being enabled. Default captures all 14 angles for full coverage.

A call takes about 90 s at most, under the server's 120 s timeout: 80 s for the angles, then up to 10 s to restore `isolate`. An angle that fails says why on its line; once the camera renders no frame (30 s with none) or the 80 s run out, the angles left say `Not captured`, so the angles already captured come back. Each angle waits 20 frames of the call's render after the camera moves before it is taken, so it holds the camera's new place and what was done before the call.

`angles` also takes `[azimuth, elevation]` pairs in degrees. An unknown angle name, a `width` or `height` that isn't a whole number from 1 to 4096, a non-numeric `zoom_offset`, or an orthographic viewport camera (such as `/OmniverseKit_Top`; switch to `/OmniverseKit_Persp`) is refused with an error.

---

### `capture_viewport`

Capture a camera at `width` x `height` and save **3 files** for full scene understanding:

1. **Viewport image** (PNG) - what the camera sees
2. **Bounding boxes** (TXT) - screen-space pixel coordinates for each visible mesh or shape under `/World`, plus world-space centre and dimensions. A box is the prim's world box where its outline lies on the image: a prim wholly outside the image has none, beside the view as behind the camera, and one across the camera's plane is boxed by its part in front. The box bounds the world box, not the prim's pixels, so a prim hidden behind another still has one; the segmentation shows what is seen. With an extension of 0.3.0 or older, a prim beside the view can get a box at the frame's edge
3. **Instance segmentation** (PNG + legend TXT) - each prim rendered as a unique colour, with a legend mapping colours to prim paths

Use files 2 and 3 to understand which object is where in the viewport image. Aim first with `set_camera`, at a point
or a prim; for one prim from every side, use `inspect_prim`.

All three come from one frame of `camera_path`, rendered at `width` x `height` in a render of the call's own, so the boxes are in the image's pixels and from the camera captured. The viewport the user sees keeps its camera and size. That render uses the viewport's renderer settings, but it is a view of its own: not pixel for pixel what the viewport shows (on average about 2 of 255 apart). While it runs the app renders one view more: about a third fewer updates a second at 640x480, headless.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | int | `640` | Image width, 1 to 4096; the camera is rendered at this size |
| `height` | int | `480` | Image height, 1 to 4096 |
| `camera_path` | string | `""` | Camera prim to render from (default: the viewport's camera); a path with no prim, or one that isn't a `Camera`, is refused |
| `include_image` | bool | `false` | Return the viewport image inline as `ImageContent` so AI can see it directly. Files are always saved regardless. |

**Output files:**
- `mcp_output/captures/viewport_NNNN.png` - viewport screenshot
- `mcp_output/captures/viewport_NNNN_bboxes.txt` - screen bounding boxes in prim-block format
- `mcp_output/captures/viewport_NNNN_segmentation_NNNN.png` - instance segmentation image
- `mcp_output/captures/viewport_NNNN_segmentation_NNNN_legend.txt` - colour-to-prim mapping

**Bounding box format:**
```
[/World/table]
type = Mesh
screen_bbox = [120.0, 200.0, 480.0, 600.0]
world_center = [0.0, 0.5, 0.0]
world_dimensions = [1.0, 1.0, 1.0]
```

> **Note:** Instance segmentation and the bounding boxes require `omni.syntheticdata` (included in Isaac Sim). Without it only the viewport image comes. When it gives no segmentation data, the image and bounding boxes are still returned, and `Segmentation: ERROR` says why. Each capture turns the sensor on for its own render and waits up to 5 s for its first data; when none comes, later captures of that camera at that size on that stage wait 1 s, until one gets data.

> **Black image detection:** If the captured image is all-black, the response includes a `WARNING` with the lighting mode and whether scene lights exist. Kit's grid shows in any lighting, so a scene the lighting leaves unlit is rarely all black: lighting mode `off`, or `stage` with no scene lights, gets a `WARNING` of its own that the scene's surfaces render black, though the grid shows. Use the `viewport_light` tool to check the lighting mode and change it if needed, then recapture. No automatic light changes are made. With an extension of 0.3.0 or older, only `off` gets that warning: the extension says whether the stage has lights only with a black image.

> **An extension of 0.2.2 or older** captures the viewport at its own size and scales the boxes to the size asked for, so the two disagree. The `Viewport:` line gives the image's own size, read from its header, and a `WARNING` line says the boxes are for another size, with the command that installs this release's extension; `inspect_prim` says the same of its images.

> **What was done just before shows:** a capture's render is made for the call, and its first frame comes some 15
> updates later, so a drawing or any change made just before the call is in the image. Path Tracing gets the frames
> it needs for all its samples (none more with Isaac Sim's 64 a frame).

---

### `viewport_light`

Query or set the viewport's lighting mode. Non-destructive: it changes how the viewport lights the scene, not the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | `"get"` | `"get"`, `"set"`, or the legacy `"set_camera_light"` |
| `mode` | string | `""` | For `set`: `"off"`, `"camera"`, `"stage"`, or a light rig such as `"Default"`, `"Colored Lights"`, `"Grey Studio"` |
| `enabled` | bool | `true` | For `set_camera_light`: `true` is mode `"camera"`, `false` is `"stage"` |

**Actions:**
- **get** - Returns the current lighting mode, the available modes, whether the stage has lights of its own, and those lights (path, type, intensity): the first 20, then `... and N more`. A light inside an instance counts, marked `inside an instance, read only`, since USD refuses edits there. A light rig's lights never count: Kit puts them on the stage under `/OmniKit_Viewport_LightRig`, and they light the viewport, not the stage. In a rig mode a line names the rig, and says the stage's surfaces render black in mode `"stage"` when the stage has no lights of its own
- **set** - Switches the lighting mode. Light rigs need the viewport's lighting menu (`omni.kit.viewport.menubar.lighting`); without it, `"camera"` and `"stage"` still work, and anything else returns an error rather than a false success
- **set_camera_light** - Legacy alias for `set` with `"camera"` or `"stage"`

**When to use:** When `capture_viewport` or `inspect_prim` reports a black image, or lighting that lights nothing, use `viewport_light("get")` to diagnose, then `viewport_light(action="set", mode="Default")` (a light rig) or `mode="camera"` (a light that follows the camera) and recapture.

---

## Simulation Tools

### `sim_control`

Control the simulation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | required | `"play"`, `"pause"`, `"stop"`, or `"step"` |

- **play** - Start or resume physics simulation
- **pause** - Pause simulation (state preserved)
- **stop** - Stop simulation and reset to initial state
- **step** - Play for two app updates, then pause

**Returns:** the state the timeline is left in. `get_sim_state` reads it without changing it; `get_robot_info`'s joint
states and `apply_force` need the simulation playing or paused.

**A robot's first play** cooks its collision meshes, and the Kit app answers nothing until that ends: the G1 cooked
from scratch in 0.6 s on Isaac Sim 6.2 with an RTX 5090. Kit keeps what it cooked, so the same meshes cook again
only when they change. Before the fix for [#5](https://github.com/serionist/omniverse-mcp/issues/5), the bridge's
log hook made that first play hang Kit.

---

### `get_sim_state`

Get the current simulation state. No parameters.

**Returns:**
- `state` - `playing`, `paused`, or `stopped`
- `up_axis` - `Y` or `Z`
- `time` - Elapsed simulation time in seconds
- `fps` - the timeline's time codes per second, not the render rate
- `prim_count` - Total number of prims in the scene
- `meters_per_unit` - Stage scale factor
- `kit_app` - the Kit app and its version, such as `Isaac-Sim Python 6.2.0`
- `kit_version` - Kit's own version, such as `110.4.0+feature.386251.187cf21b.gl`
- `kit_os` - the OS Kit runs on, as Python's `platform.platform()` names it there, such as `Windows-11-10.0.26300-SP0`;
  on Linux the kernel and glibc, not the distribution
  (the three read `unknown` with an extension of 0.3.0 or older: a bug report then asks the user, Help > About)
- `extension_version`, `server_version` - the Kit extension's release, from the bridge's handshake, and this server's
- `recording_note` - only while a recording runs whose frames stopped early: why
- `note` - only when the bridge's release differs from the server's: the command that installs the matching one

**When to use:** Always call this first to understand the environment (especially up axis and whether physics is running).

---

## Recording Tools

### `start_recording`

Start recording simulation frames to disk. It records `camera_path`, or the active viewport's camera when empty, at
`width` x `height`, through a render of its own: the viewport, its camera and its size stay as they are, in the GUI
too. A side of more than 4096 pixels is refused. The answer names the camera, the size and `render_product`, the
prim the recording renders into, which it deletes at stop.

- **When frames come:** one every 1/`fps` seconds of the recording's own clock, at most one an app update; play the
  simulation to record motion.
  - The clock runs with the simulation while it plays, `sim_control("step")`'s steps included: frames are 1/`fps` s
    of `sim_time` apart. A simulation faster than real time, 1.25 to 2.5 times headless on Isaac Sim 6.2, so gives
    more than `fps` frames a second by the wall clock.
  - It runs with the wall clock while the simulation is stopped or paused, or plays a timeline whose time doesn't move
    (a file with no time-code range): `fps` frames a second, whatever Kit's update rate.
  - The first frame comes on the first update after the start, which waits for the camera's first render and, under
    Path Tracing, for the samples a capture waits for.
  - A frame shows the simulation within one update of its `sim_time`. Frames asked for faster than they can be
    written, or than Kit updates, are skipped rather than sent late in a burst, which the frames' `sim_time` and
    `wall_time` in `metadata.json` show; each frame keeps a number of its own.
- **Ending a recording:** it takes frames while the simulation is stopped too, and `sim_control("stop")` puts the
  scene back where it started. To end on the run's last state, pause the simulation, or call `stop_recording`, before
  you stop it.
- **Kit's grid:** frames taken while the simulation is stopped or paused show it, as the viewport does. Isaac Sim 6.2
  hides it while the simulation plays, in the viewport and in the recording alike; other Kit apps show what their
  viewport does.
- **What it costs:** the extra render runs every update while the recording does, at the frame's size. Headless on
  Isaac Sim 6.2 it took a third of the app's updates at 640x480 and three quarters at 4096x4096; each update still
  advances the simulation as before, so the run takes longer, not differently.
- **When frames stop:** if the stage changes (`new_scene`, `open_scene`) or the camera is deleted, since the render
  would show something else then. `get_sim_state` and `stop_recording` say why.
- **One at a time:** while a recording runs, another start is refused, saying to call `stop_recording` first; an
  extension of 0.2.3 or older says to pass `force=True`, which the tool doesn't take: call `stop_recording`.
- **An extension of 0.2.2 or older** records the active viewport at its own size: the answer then carries a
  `WARNING` line naming the `camera_path`, `width` or `height` it ignores, with the command that installs this
  release's extension.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fps` | int | `5` | Frames a second, at least 1: of simulation while it plays, by the clock while not |
| `width` | int | `640` | Frame width in pixels, 1 to 4096 |
| `height` | int | `480` | Frame height in pixels, 1 to 4096 |
| `camera_path` | string | `""` | The camera to record (a `UsdGeom.Camera`); the active viewport's camera when empty |
| `track_prims` | list[string] | `null` | Prim paths to track state for (includes descendants) |
| `property_filter` | list[string] | `null` | Only record properties containing these substrings |

**Workflow:**
1. `start_recording(fps=10, track_prims=["/World/Robot"])`
2. `sim_control("play")`
3. Wait for desired duration...
4. `stop_recording()`
5. `get_recording_frame(0)`, `get_recording_frame(5)`, etc. to review

When `track_prims` is set, a `state.txt` file is written alongside frames in prim-block format, each frame's state read at its tick, at its `sim_time`. Each frame is separated by `=== FRAME t=X.XXX step=N ===` headers.

---

### `stop_recording`

Stop the active recording session. No parameters. It waits for the frames still being written, deletes the
recording's render product and writes `metadata.json`: the frames' camera, size and times, what they span, and
`ended` when frames stopped early.

**Returns:** Frame count, duration, output directory, state file path (if tracking prims), and a `Note:` line when
frames stopped early or the cleanup failed in part, saying why. The first line also says what the frames span, as
`Stopped. 33 frames, 4.99s: 3.00 s of simulation played, 2.00 s stopped or paused -> ...`; `metadata.json` has both
as `simulation_seconds` and `idle_seconds`.

- **`simulation_seconds`:** the simulation the recording played through.
- **`idle_seconds`:** the wall seconds it ran while the simulation didn't move: stopped, paused, or playing a timeline
  whose time doesn't move.
- **The frame count** comes out near `fps` times their sum, fewer when frames were skipped. An extension of 0.3.0 or
  older answers neither, and the line names the duration alone.

---

### `get_recording_frame`

Copy one recorded frame to a new PNG in `mcp_output/captures/`, and return its path and, once the recording has
stopped, the frame's simulation time.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `frame_index` | int | `0` | Frame number (0-based), not negative |
| `session_dir` | string | `""` | The session folder as `start_recording` and `stop_recording` give it, relative to this server's working folder, or an absolute path on Kit's machine, in either Windows' or POSIX's form (uses the last recording started since the extension started, the running one included, if empty) |

Kit writes a recording's frames itself, as `frame_00000.png` and on in the session folder: with Kit on this machine you
can also open them there, and with Kit on another this tool brings one here. A frame Kit failed to capture comes back
as an empty file; a frame number past the last is an error.

---

## Physics Tools

### `set_physics_properties`

Set a prim's mass or density, and its friction or restitution, for PhysX; a value left out stays as it is.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `mass` | float | `null` | Mass in kg, not negative (applies MassAPI); 0 unsets it, so density decides |
| `density` | float | `null` | Density in kg/m^3, not negative; 0 unsets it; a mass set wins over it |
| `friction` | float | `null` | Friction coefficient, not negative (usually 0-1), set as both static and dynamic friction |
| `restitution` | float | `null` | Bounciness, 0 (no bounce) to 1 (full bounce) |

- **Mass or density** makes the prim a rigid body (`RigidBodyAPI`) if it isn't one, so a static collider starts to fall
  when the simulation plays.
- **Friction or restitution** adds the Collision API if missing, and sets them on the prim's own physics material, a
  child of the prim named `PhysMat` (`/World/Cube/PhysMat` for `/World/Cube`), bound to the prim for physics only.
  That material starts from the body's own: the physics material bound to it before (a physics binding, else an
  all-purpose one, with `PhysicsMaterialAPI`), else the one bound to the physics scene, its default, else PhysX's own
  (friction 0.5, restitution 0). So the friction or restitution left out stays as PhysX applied it, and so does
  everything else the replaced material held: its density and `PhysxMaterialAPI`'s attributes, such as combine modes,
  are copied over.
- **Copies and clones:** the material goes where its prim goes. `delete_prim` removes it with the prim, and
  `save_scene`, `flatten_usd` and `export_prim_as_file` carry it. A copy made with `clone_prim`, or by Isaac Sim's
  cloner with `copy_from_source`, takes a material of its own, so a call on the original leaves the copy as it was. A
  clone that inherits from its source, as Isaac Sim's cloner makes them by default, composes its material from the
  source's: a call on the source reaches each clone that no call has given values of its own, and the answer names
  them. A call on the clone writes its own, and leaves the source as it was.
- **Refused,** a call with friction or restitution, before anything is written, the mass given with it included: on
  an inactive prim, an instance (an instanceable prim with its reference or payload) or a prim inside one, which USD
  lets hold no prim of its own; the error for a prim inside an instance names its instance. A call on the instance's
  parent instead gives the parent's material to every prim under it that has none of its own, the other instances
  there too. A child named `PhysMat` that isn't a `Material` is the user's own, and is refused too. A call with only
  mass or density binds no material, and isn't refused.
- **A prim bound to an older extension's shared material,** `/World/PhysicsMaterials/<prim name>_PhysMat`, which
  extensions of 0.3.0 and older gave every prim of one name, moves to its own on its next call, with the values it
  had. The call that moves the last prim off it deletes it, and `/World/PhysicsMaterials` once that leaves it empty,
  when the material is exactly that path, a `Material` with `PhysicsMaterialAPI` that only the edit layer holds at
  that path, holding no prim of its own, and no prim binds it, nor a material composed from it. It stays, and the
  answer says why, when:
  - another prim still binds it, the called prim's links and other descendants included;
  - another layer holds it, or it is composed from another path, through a reference, inherit or specialize;
  - it holds prims of its own, which deleting it would take with it;
  - the stage holds a prim under which the walk can't see, where a prim could bind it: an inactive prim with
    something under it, an unloaded payload, or a prim with variant sets, whose variants not selected aren't on the
    stage.

  A material under any other path, a user's own, is never deleted. With an extension of 0.3.0 or older, a value left
  out on a new material is USD's 0, and a material bound before is replaced with all it held.
- **The walk:** a call with friction or restitution reads every prim's material bindings, on Kit's main thread, to
  find the other prims the write reaches and whether the older material may go: about 1 s per 100,000 prims on
  usd-core, whatever their number of properties. It doesn't enter instances: a prim in an instance's prototype that
  binds the material isn't named.

**Returns:** each value set, as the Kit extension set it, then the material bound, then the APIs applied:
`Physics on /World/RedCube: friction=0.8 (static and dynamic), restitution=0.3; material /World/RedCube/PhysMat;
applied PhysicsMaterial`. Friction says `(static and dynamic)`, as it is set as both; a mass or density of 0 says it
is unset. `RigidBodyAPI` and `CollisionAPI` are named only when the call added them, so the prim became a rigid body
or a collider; `MassAPI` and `PhysicsMaterial` whenever their values were set. A call without a value sets nothing
and says so. Then, when there are any:

- the other prims the write changed, the first five named: `also changes 2 prims: /World/envs/env_1/Robot/link,
  /World/envs/env_2/Robot/link`;
- the older shared material: `deleted its old material, /World/PhysicsMaterials/Box_PhysMat, which no prim binds now`,
  or `kept its old material, /World/PhysicsMaterials/Box_PhysMat: 1 prim still binds it: /World/Shelf/Box`.

The material and these clauses need the Kit extension of this release.

**When to use:** for how a prim behaves in physics. Its look is `set_material`'s; to make a new prim physical in one
call, use `create_prim` with `enable_physics`.

---

### `apply_force`

Push a rigid body through PhysX, so its mass counts: at `position`, or at its centre of mass when it is left out.
The simulation must be playing or paused. A body can be an articulation's link, such as a robot's: the push moves
the robot through its joints. A floating robot touching nothing gains the impulse as momentum, so its speed changes
by the impulse over the whole robot's mass, not the link's. A fixed-base robot's link turns about its joints, and a
robot on the ground loses some of the push to friction. Measured on Isaac Sim 6.2, on PhysX's CPU pipeline.

Under PhysX's Direct GPU API, which Isaac Sim turns on for a GPU device (`SimulationManager.set_device("cuda:0")`),
PhysX's own push returns and moves nothing, so the call pushes through PhysX's tensor API, `omni.physics.tensors`
with warp, as measured on Isaac Sim 6.2 ([#68](https://github.com/serionist/omniverse-mcp/issues/68)). It takes that
path whenever `/physics/suppressReadback` is true, the setting that API runs with, whatever the physics scene says of
GPU dynamics: the tensor API pushes on a CPU scene with the setting on too. With the setting off, GPU dynamics
included, the call keeps PhysX's own push, which moves the body there. The tensor API has no impulse, so an impulse
goes in as the force that gives it over one physics step.

Under the Direct GPU API a second push on a body before the next physics step replaces the first, where on the CPU
pipeline the two add: two impulses of 10 N s on one body while paused change its momentum by 10, not 20, as measured
on Isaac Sim 6.2. So push once per body per step, combining pushes into one, such as one impulse of 20 N s. Pushes on
different bodies each land.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Rigid body prim, a robot's link among them |
| `force` | list[float] | required | `[fx, fy, fz]`: an impulse in N s, or a force in N for one physics step |
| `position` | list[float] | `null` | World-space point to push at; the body's centre of mass, as PhysX holds it, when omitted |
| `impulse` | bool | `false` | `true` for an impulse in N s, which changes the velocity at once by `force / mass`; `false` for a force in N for one physics step, which changes it by `force * dt / mass`, `dt` being the physics step: 1 over the physics scene's `physxScene:timeStepsPerSecond`, 1/60 s when the scene leaves it unset or there is none. One call can't hold a force over many steps: for a sustained push, give an impulse of force times seconds, the same change in velocity at once |

**Refused,** before anything is applied:

| When | Why |
|---|---|
| the prim has no `RigidBodyAPI` | it is no rigid body: `set_physics_properties` or `create_prim`'s `enable_physics` makes one |
| the simulation is stopped | PhysX holds no bodies then; paused works |
| `/physics/suppressReadback` is true and the Kit app lacks `omni.physics.tensors` or warp | the push then goes through them. The error names the one missing, and says to turn it on with `manage_extensions`, or to push with readback on: stop the simulation, set `/physics/suppressReadback` to false through `execute_script`, and play again |
| `/physics/suppressReadback` is true and the physics scene's `physxScene:timeStepsPerSecond` isn't a positive number | the push then needs the step's length |
| the body is disabled (`physics:rigidBodyEnabled` is false) | PhysX holds it as a static body, which no force moves |
| the body is kinematic (`physics:kinematicEnabled` is true) | PhysX takes the force and moves it only by its transform |
| PhysX holds no rigid body at `prim_path` | nothing to push; `get_logs(min_level="warn")` may say why |
| a fixed joint holds the body to the world, or welds it to a body one holds | no force moves it, as measured on the Franka's base. That is an enabled `UsdPhysics.FixedJoint` whose other end is the world, a static prim, a disabled body or a kinematic one, excluded from articulations or not. The error names the articulation when the body is a robot's fixed base or welded to one |
| `position` is left out and PhysX gives the body no mass | no centre of mass to push at: give a `position` |

**Returns:** the push, the world point pushed at, whether that was the point `given` or the `centre of mass`, and the
path the push took: `method: physx`, PhysX's own push, or `method: tensor`, its tensor API with
`/physics/suppressReadback` on. For example,
`Applied impulse [0.0, 0.0, 10.0] to /World/Cube at [0.0, 0.1, 2.0] (centre of mass, method: physx)`. A point off
the centre of mass turns the body as well as moving it. Newtons assume a stage in metres and kilograms: PhysX works in the stage's units (`meters_per_unit` in `get_sim_state`). The
centre of mass comes from PhysX's unit-tests interface (`get_mass_information`), which NVIDIA may change between Kit
releases, or with the setting on from the tensor API's view of the body; without it the call is an error, never a
push at another point. All of this is the Kit extension's: one from 0.2.0 nudges `physics:velocity` instead, and its
answer says `method: velocity`; one from 0.2.3 refuses every push while `/physics/suppressReadback` is true.

---

### `raycast`

Cast a ray through PhysX and return the closest collider it hits.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `origin` | list[float] | required | `[x, y, z]` start point in world space |
| `direction` | list[float] | required | `[dx, dy, dz]` direction in world space, of any length but zero: the server scales it to a unit vector, as Isaac Sim 6.2's PhysX also does |
| `max_distance` | float | `1000.0` | Maximum ray length in stage units, above 0 |

**Returns:** Hit prim path, hit position, surface normal, and distance in stage units. Returns "No hit" if ray doesn't
intersect anything. The prim named is the rigid body hit, or a static collider itself.

- **Colliders only:** prims with the Collision API, which `create_prim`'s `enable_physics` adds, are hit; plain meshes
  are not.
- **PhysX must know the scene:** play or step the simulation once first, or the ray may find nothing, or fail.

**When to use:** to find what lies along a line, such as the ground under a point; `get_prim_bounds` measures a prim
you already know.

---

## Debug Tools

### `draw_debug`

Draw debug lines in the viewport for `duration` seconds: a line, a polyline, a sphere as three crossing lines, or a
small cross per point. Every line is 2 pixels wide. Use it to mark points, rays or paths, such as a `raycast`'s hit,
for a capture or the user to see; nothing is added to the stage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `shape` | string | required | `"line"`, `"lines"` (joins `points` in order), `"sphere"`, or `"points"` |
| `color` | list[float] | `null` | `[r, g, b]` colour in 0-1, each value clamped to 0-1 (red `[1,0,0]` when omitted) |
| `duration` | float | `5.0` | How long it shows, in seconds from the call, above 0: real time, whether the simulation plays or not |
| `start` | list[float] | `null` | Line start `[x,y,z]` (for `shape="line"`) |
| `end` | list[float] | `null` | Line end `[x,y,z]` (for `shape="line"`) |
| `center` | list[float] | `null` | Sphere centre `[x,y,z]` (for `shape="sphere"`) |
| `radius` | float | `0.1` | Sphere radius, above 0 (for `shape="sphere"`) |
| `points` | list[list[float]] | `null` | List of `[x,y,z]` points (for `shape="points"` and `"lines"`) |
| `size` | float | `0.05` | How far each point's cross reaches, in stage units, above 0 (for `shape="points"`) |

**Returns:** what was drawn, how long it shows and the extension that drew it:
`Drew 1 debug element(s): line, for 5.0 s (isaacsim.util.debug_draw)`.

**How it draws:**

| Kit app | Extension | What to know |
|---|---|---|
| Isaac Sim 5.x and 6.x | `isaacsim.util.debug_draw`, turned on at the first call if it is off | Its lines stay until cleared, and its clear takes every line drawn with it. So when one drawing expires, lines other code drew with this extension go too, and the bridge draws its own again. |
| Other Kit apps that ship it | `omni.debugdraw` | It shows a line for one frame, so the bridge draws its lines again on every update. |
| Neither | none | An error naming both. |

- **Drawings belong to their stage:** `new_scene`, `open_scene` or another stage opened drops them, and no drawing is
  made while a stage opens or closes.
- **Captures:** drawings show in `capture_viewport`'s image, headless too, with either extension, however soon after
  `draw_debug` the capture comes (checked live on Isaac Sim 6.2 and 5.1).
- **A wrong shape is an error:** an unknown `shape`, a vector that isn't three finite numbers, or a missing part, such
  as `start` for a line.
- **The fix is in the Kit extension:** a bridge from 0.2.0 or before draws for one frame, and fails headless.
  `uvx omniverse-mcp extension install`, then restart Kit.

---

## Extension Tools

### `manage_extensions`

List the Kit app's extensions, or turn one on or off in the running app.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | `"list"` | `"list"`, `"enable"`, or `"disable"` |
| `extension_id` | string | `""` | Required for enable/disable |
| `search` | string | `""` | Filter extension list by name or id, in any case (for list) |
| `enabled_only` | bool | `false` | Only show enabled extensions (for list) |

- **list** only reads: each extension's id, version and whether it is on, the first 50 shown with the total.
- **enable** and **disable** last until Kit restarts, and answer whether the extension is on afterwards: `enabled=False`
  after an enable means it didn't take. Disabling one that other tools use breaks them, and disabling `ovmcp.bridge`
  cuts the server off from Kit.

**When to use:** Before using features that depend on optional extensions (e.g., Replicator, measurement tools), check if they're enabled and enable them if needed.
Or when a tool names an extension it lacks, such as `omni.syntheticdata` for segmentation.

---

## Logging Tools

### `get_logs`

Get the latest entries of the Kit app's log, by level, channel or text.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `count` | int | `50` | Number of recent entries to return, at least 1 (the buffer keeps 2000) |
| `min_level` | string | `""` | Minimum severity: `verbose`, `info`, `warn`, `error`, `fatal`, or `""` for every level |
| `channel` | string | `""` | Filter by log channel substring (e.g. `"omni.physx"`, `"omni.usd"`) |
| `search` | string | `""` | Filter by message substring anywhere in the message (case-insensitive) |

**When to use:** After any tool returns an error, call `get_logs(min_level="warn")` to see what Omniverse reported internally. PhysX errors, USD composition failures, missing extensions, and other diagnostics are captured here.

**What an entry shows:** `[LEVEL] <channel>: <message>`, the channel whole and the message's first 200 characters.

- **A longer message** ends its shown part with ` ... (+N characters)`, N the characters cut, such as
  `(+2,345 characters)`.
- **With `search`,** which matches the whole message, an entry whose match doesn't end within the first 200 gets a
  `matched:` line: the line of the message that holds the match, cut to 80 characters either side of it, with `...`
  at each end cut. A callstack, such as Kit's deprecation warnings, often matches only in a later frame.

```
  [INFO ] carb: `get_update_event_stream` is deprecated. Use Events 2.0. Callstack:   File "...\asyncio\events.py", line 88, in _run
    self._context.run(self._ ... (+695 characters)
    matched: File "c:/users/ada/kit/exts/omniverse-mcp/extension/ovmcp.bridge/ovmcp/bridge/handlers/camera_feed.py", line 161, in add
```

**How it works:** each call reads what Kit added to its log file since the last, from where the file ended when the
extension started, into a ring of the latest 2000 entries.

- **What Kit's file holds:** Info and above by default, from `carb.log_*()`, Python `logging` and Kit's own
  extensions. Verbose lines need Kit started with both `--/log/level=verbose` and `--/log/fileLogLevel=verbose`.
  A Kit app whose `/log/file` setting is empty gets an error naming `--/log/file=<path>`.
- **What it never holds:** an `execute_script` script's own exception, `print` and stderr, which come back in
  that call's answer instead. A script's `carb.log_error()` and the other `carb.log_*()` calls do reach it.
- **Kit's default line format:** `<time> [<elapsed>] [<Level>] [<channel>] <message>`. A `/log/include*` or
  `/log/detail` setting can change it; when Kit has written lines and none reads as an entry, the answer says
  so instead of coming back empty.
- **An entry:** `index`, `level`, `channel`, `msg`, `timestamp`, and `module`, `source` and `func`, which Kit's
  file doesn't carry, so they are empty. `timestamp` is the line's own text, its time and elapsed milliseconds, such
  as `2026-01-01T00:00:00Z [1,234ms]`. A message's further lines, such as a traceback, are part of its `msg`.
- **`total_captured`** counts the entries read since the extension started. A call reads at most the newest 1 MB,
  so a burst larger than that between two calls leaves its oldest lines uncounted.
- **The bridge token** is replaced by `<redacted>` wherever a message holds it.
- **No hook on Kit's logging:** the bridge used to subscribe Python to Kit's log, which hung Kit when a physics
  worker logged while the main thread held Python's lock
  ([#5](https://github.com/serionist/omniverse-mcp/issues/5)).

---

## Script Execution

### `execute_script`

Execute arbitrary Python code inside the running Omniverse application.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | required | Python code to execute |

**Pre-loaded in the script namespace:**

| Variable | Module | Description |
|----------|--------|-------------|
| `omni` | `omni` | Omniverse Kit APIs |
| `carb` | `carb` | Carbonite (logging, settings) |
| `Usd` | `pxr.Usd` | Core USD |
| `UsdGeom` | `pxr.UsdGeom` | Geometry and transforms |
| `UsdLux` | `pxr.UsdLux` | Lights |
| `UsdPhysics` | `pxr.UsdPhysics` | Physics APIs |
| `Sdf` | `pxr.Sdf` | Layer/path manipulation |
| `Gf` | `pxr.Gf` | Math: vectors, matrices, quaternions |
| `mcp` | `MCPBridge` | Async access to MCP handlers (see below) |

Set `result = <value>` to return JSON-serialisable data to the AI assistant; anything else comes back as its `str`.
stdout and stderr come back too, and an exception as an error with the traceback's last lines. The script runs on
Kit's main thread, so one that blocks freezes Kit: the call gives up after 120 s, and the script runs on.

**Example (sync):**
```python
stage = omni.usd.get_context().get_stage()
result = [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
```

**Example (async, with the `mcp` bridge):**
```python
# Using await auto-detects async mode
viewport = await mcp.capture_viewport(width=1280, height=720)
bounds = await mcp.prim_bounds("/World/Cube")
await mcp.set_camera([5, 3, 5], target=[0, 0, 0])
state = await mcp.sim_state()
result = {"center": bounds["result"]["center"], "sim": state["result"]["state"]}
```

**Available `mcp` methods** (all async, use `await`):

| Method | Description |
|--------|-------------|
| `mcp.capture_viewport(width, height, camera_path)` | Capture viewport with bboxes + segmentation |
| `mcp.set_camera(position, target)` | Position the viewport camera |
| `mcp.look_at(prim_path, distance, azimuth, elevation)` | Point camera at a prim |
| `mcp.inspect(prim_path, angles, width, height, zoom_offset=0.0, isolate=False)` | Orbit-capture from multiple angles, auto-fitted |
| `mcp.scene_tree(root, max_depth)` | Get scene hierarchy |
| `mcp.prim_properties(prim_path)` | Get all prim properties |
| `mcp.prim_bounds(prim_path)` | Get world-space bounding box |
| `mcp.set_transform(prim_path, position, rotation, scale)` | Move/rotate/scale a prim |
| `mcp.create_prim(prim_path, prim_type, **kwargs)` | Create a prim |
| `mcp.delete_prim(prim_path)` | Delete a prim |
| `mcp.set_material(prim_path, color, opacity, roughness, metallic)` | Create and bind a material |
| `mcp.sim_control(action)` | play/pause/stop/step |
| `mcp.sim_state()` | Get simulation state |
| `mcp.get_logs(count, min_level, channel, search)` | Get recent log entries |

Each method returns the full handler response dict with `"status"` and `"result"` keys. They run inside Kit.

**When to use:** Complex operations not covered by other tools - custom physics queries, batch operations, accessing APIs that don't have dedicated tools. Use async `mcp.*` methods when you need to chain multiple MCP operations in a single script (e.g., capture viewport, analyse, reposition, recapture).

**Fallback strategy:** Every MCP tool in this server can be replicated via `execute_script` using the Omniverse Python API directly. If any tool returns an error, you can fall back to writing the equivalent Python code. Use Context7 (`isaac-sim/isaacsim`) or the [NVIDIA Omniverse docs](https://docs.omniverse.nvidia.com/) to look up the correct API rather than guessing.

---

## MCP Resources

Two MCP resources, read when the client asks for them:

| URI | Description |
|-----|-------------|
| `omniverse://scene/tree` | Current scene hierarchy |
| `omniverse://sim/state` | Current simulation state |
