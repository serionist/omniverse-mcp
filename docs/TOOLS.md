# Tool Reference

Reference for every tool the MCP server provides.

- **Where answers go:** a text answer over 1,000 characters is written to `mcp_output/responses/` and the tool
  returns its path; images go to `mcp_output/captures/`, recordings to `mcp_output/recordings/`, and a scene dump to
  `mcp_output/scene_dump.txt`, which the next dump replaces. A file under the server's working folder is given by
  its relative path, any other by its absolute path. Open them with your client's file tool.
- **Prim blocks:** text about prims comes as a `[/prim/path]` header, then `key = value` lines, so you can grep for a
  path or a property.
- **Known issues** on Isaac Sim 6.2 are in the [README](../README.md#known-issues).

## Find a tool

| To | Use |
|---|---|
| see what is in the scene | `get_scene_tree`, or `dump_scene` for a large one |
| see how it looks | `capture_viewport`; `inspect_prim` for one object from several sides |
| read a prim's properties, size or place | `get_prim_properties`, `get_prim_bounds` |
| create, move, copy, hide or delete prims | `create_prim`, `set_prim_transform`, `clone_prim`, `set_visibility`, `delete_prim` |
| colour an object | `set_material` |
| point the camera | `set_camera`, `look_at_prim` |
| fix a black capture | `viewport_light` |
| play, pause, stop or step physics | `sim_control`; `get_sim_state` for where it stands |
| add a robot and move its joints | `create_robot`, `get_robot_info`, `get_joint_states`, `set_joint_targets` |
| record a run and look back at it | `start_recording`, `stop_recording`, `get_recording_frame` |
| set mass or friction, push, or probe | `set_physics_properties`, `apply_force`, `raycast` |
| count faces, or compare two prims or variants | `get_mesh_stats`, `get_prim_face_count_tree`, `compare_prims` |
| make or switch variants | `create_variant_structure`, `set_variant_selection` |
| write USD files | `save_scene`, `flatten_usd`, `export_prim_as_file`; `update_material_paths` after files move |
| start an empty scene | `new_scene` |
| find out why something failed | `get_logs` |
| do anything else in Kit's Python | `execute_script`; `manage_extensions` for Kit's extensions |

Each tool tells the client what it does to the Kit app, as MCP tool annotations. A client may use them to ask before
it runs one; they are hints, never security (the bridge's token is what keeps others out).

| Hints | What they mean | Tools |
|---|---|---|
| read-only | Queries and captures: nothing in the stage, the simulation or the viewport changes | `get_scene_tree`, `dump_scene`, `get_prim_properties`, `get_prim_bounds`, `get_mesh_stats`, `get_prim_face_count_tree`, `get_robot_info`, `get_joint_states`, `capture_viewport`, `get_sim_state`, `get_recording_frame`, `raycast`, `get_logs` |
| not destructive | Changes that destroy nothing: transforms, new prims, materials, variants, the camera, lights, the simulation | `set_prim_transform`, `create_prim`, `set_material`, `clone_prim`, `set_visibility`, `compare_prims`, `set_variant_selection`, `create_variant_structure`, `create_robot`, `set_joint_targets`, `set_camera`, `look_at_prim`, `inspect_prim`, `viewport_light`, `sim_control`, `start_recording`, `stop_recording`, `set_physics_properties`, `apply_force`, `draw_debug` |
| destructive | Deletes or overwrites prims, the whole stage, or USD files on disk | `delete_prim`, `save_scene`, `new_scene`, `flatten_usd`, `export_prim_as_file`, `update_material_paths` |
| destructive, open world | Runs Python or loads extensions inside the Kit app: anything can happen | `execute_script`, `manage_extensions` |

A value out of a parameter's range, or not one of its choices, is refused before the tool runs.

## Table of Contents

- [Scene Tools](#scene-tools) (11 tools)
- [Geometry & Mesh Tools](#geometry--mesh-tools) (3 tools)
- [USD Operations](#usd-operations) (2 tools)
- [Variant Tools](#variant-tools) (2 tools)
- [Material Tools](#material-tools) (2 tools)
- [Robot Tools](#robot-tools) (4 tools)
- [Camera Tools](#camera-tools) (5 tools)
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

Get the USD scene hierarchy as grep-friendly prim-block text.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/"` | Starting prim path |
| `max_depth` | int | `5` | Traversal depth, 0 (root alone) to 15 |

**Returns:** Prim-block text showing each prim's path, type, and world position. Written to file if output exceeds 1000 characters.

**When to use:** Quick scene overview for scenes under ~100 prims. For larger scenes, use `dump_scene`.

---

### `dump_scene`

Dump the full scene graph to a text file with all properties, bounding boxes, and transforms.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/"` | Starting prim path |
| `max_depth` | int | `15` | Max traversal depth; 0 for root alone |
| `include_properties` | bool | `true` | Include all USD properties per prim |
| `filter_types` | list[string] | `null` | Only include prims of these types (e.g., `["Mesh", "Xform"]`) |
| `property_filter` | list[string] | `null` | Only include properties containing these substrings |

**Returns:** File path to the dump. Use your file reading tool to examine specific parts.

**When to use:** Large scenes where you need full property data. The output is in prim-block format - grep for prim paths or property names.

---

### `get_prim_properties`

Get all properties of a specific prim in prim-block text format.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path (e.g., `"/World/Robot"`) |

**Returns:** Prim type, position, bounding box, and all USD properties.

---

### `get_prim_bounds`

Get the axis-aligned bounding box of a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path |

**Returns:** Centre, dimensions, min/max corners, and diagonal length. Essential for spatial reasoning - computing placement positions, checking overlaps, measuring distances.

---

### `set_prim_transform`

Set position, rotation, and/or scale of a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path |
| `position` | list[float] | `null` | `[x, y, z]` in metres |
| `rotation` | list[float] | `null` | Euler `[rx, ry, rz]` in degrees, or quaternion `[w, x, y, z]` |
| `scale` | float or list[float] | `null` | Uniform (single float) or per-axis `[sx, sy, sz]` |

Only provided parameters are changed; others are preserved.

---

### `create_prim`

Create a new prim in the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Where to create (e.g., `"/World/MyCube"`) |
| `prim_type` | string | `"Xform"` | USD type: `Cube`, `Sphere`, `Cylinder`, `Cone`, `Capsule`, `Xform`, `Camera`, `DistantLight`, `SphereLight`, etc. |
| `usd_path` | string | `null` | Load a USD file as a reference instead |
| `position` | list[float] | `null` | `[x, y, z]` |
| `rotation` | list[float] | `null` | Euler or quaternion |
| `scale` | float or list[float] | `null` | Scale |
| `enable_physics` | bool | `false` | Add RigidBody + Collision APIs |

A prim already at `prim_path` keeps its type: creating one of another type there is refused.

**When to use:** Creating geometric shapes, lights, cameras, or loading external USD assets.

---

### `delete_prim`

Delete a prim and all its children from the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path to delete |

---

### `clone_prim`

Deep-copy a prim and all its children to a new path. Supports batch cloning with offset. A target path that
already holds a prim is refused, before anything is copied.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | string | required | Prim to clone |
| `target_path` | string | required | Destination path |
| `count` | int | `1` | Number of copies, at least 1. Paths auto-suffixed: `_001`, `_002`, ... |
| `offset` | list[float] | `null` | `[x, y, z]` per-copy offset. Each clone shifts by this amount from the previous. |

**Example:** Clone a cube into a row of 5:
```
clone_prim("/World/Cube", "/World/CubeRow", count=5, offset=[2, 0, 0])
```

---

### `set_visibility`

Show or hide a prim and its descendants.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `visible` | bool | `true` | `true` to show, `false` to hide |

---

### `save_scene`

Save the current scene to a USD file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | `""` | Destination path. If empty, saves to the current file (overwrite). |

---

### `new_scene`

Discard the open scene, unsaved changes too, and start an empty one with a `/World` prim. The new stage is
Y-up, while Isaac Sim's robots and stages are Z-up: for robot work, open a Z-up stage or set the axis with
`execute_script` (`UsdGeom.SetStageUpAxis(omni.usd.get_context().get_stage(), UsdGeom.Tokens.z)`) before adding
anything.

No parameters.

---

## Geometry & Mesh Tools

### `get_mesh_stats`

Get face/vertex/triangle counts for a mesh prim or subtree.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Prim to analyse (includes all descendant meshes) |

**Returns:** Per-mesh breakdown and totals (faces, vertices, triangles, mesh count). Written to file if many meshes.

**When to use:** Checking a geometry budget, or what a simplification saved.

---

### `get_prim_face_count_tree`

Get scene tree with face counts per mesh and subtree totals.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/World"` | Starting prim path |
| `max_depth` | int | `10` | Max traversal depth; 0 for root alone |

**Returns:** Prim-block text where each mesh shows `faces`, `vertices`, `triangles` and each group shows `subtree_faces` total.

**When to use:** Quick overview of where geometry budget is spent in a scene, without needing individual `get_mesh_stats` calls.

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

**Returns:** Side-by-side stats (faces, vertices, triangles, meshes, bounds, materials) with deltas and percentage change.

**When to use:** Checking what a simplified copy or another variant changed. Bounds are measured afresh after each
variant switch.

---

## USD Operations

### `flatten_usd`

Flatten a USD file: resolve all references, payloads, sublayers into a single self-contained file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output_path` | string | required | Where to write the flattened USD file |
| `input_path` | string | `""` | Source USD file (default: current stage) |

**Returns:** Input/output paths and number of layers resolved.

**When to use:** Before modifying a component (flatten first so all references are resolved), preparing a file for external tools.

---

### `export_prim_as_file`

Export a prim subtree as a standalone USD file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root of the subtree to export |
| `output_path` | string | required | Destination file (.usd, .usda or .usdc; .usdc by default) |

**Returns:** Output path, target root prim name, material count, up axis.

Flattens the source (resolves all references) and includes materials even if they live outside the exported subtree. Output is self-contained and can be imported into Blender or other DCC tools.

---

## Variant Tools

### `set_variant_selection`

Switch variant selection on a prim with proper viewport refresh.

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

Create variant set boilerplate on a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `variant_set_name` | string | required | Name for the new variant set |
| `variant_names` | list[string] | required | List of variant names to create (e.g., `["focused", "shell"]`) |
| `default_variant` | string | `""` | Which variant to select by default (default: first in list) |

**Returns:** Prim path, variant set name, created variants, default selection.

---

## Material Tools

### `set_material`

Apply a PBR material (OmniPBR) to a prim with colour and surface properties.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `color` | list[float] | required | `[r, g, b]` diffuse colour. 0-1 floats or 0-255 ints (auto-detected) |
| `opacity` | float | `1.0` | 0.0 (transparent) to 1.0 (opaque); nothing outside that |
| `roughness` | float | `0.5` | 0.0 (glossy) to 1.0 (matte); nothing outside that |
| `metallic` | float | `0.0` | 0.0 (plastic) to 1.0 (metal); nothing outside that |
| `material_path` | string | `""` | Custom material prim path (auto-generated under `/World/Looks/` if omitted) |

---

### `update_material_paths`

Bulk-update material reference paths in a subtree.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `old_prefix` | string | required | Path prefix to find (e.g., `"/OldProject/Materials"`) |
| `new_prefix` | string | required | Replacement prefix (e.g., `"/World/Materials"`) |
| `prim_path` | string | `"/"` | Root of subtree to update (default: entire stage) |

**Returns:** Number of updated references and list of affected prims.

Updates both relationship targets (material bindings) and asset path attributes (texture file paths) that start with `old_prefix`.

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
is an error, and so is a prim already at `prim_path`.

---

### `get_robot_info`

Get robot joint information from USD (no simulation needed).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |

**Returns:** Articulation status, DOF count, link count, and per-joint details (name, type, limits, drive type).

---

### `get_joint_states`

Get current joint positions and velocities.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |

**Returns:** each degree of freedom's name, position and velocity: radians and radians per second for revolute
joints, metres and metres per second for prismatic ones. `set_joint_targets` takes degrees for revolute joints.

- **Physics playing or paused:** joint states come from physics, so a stopped simulation is an error that says to
  play or step it first. The tool never starts physics itself.
- **The robot:** `prim_path` itself, or the first prim under it with `UsdPhysics.ArticulationRootAPI`, as
  `get_robot_info` finds it.
- **Isaac Sim:** it reads through `isaacsim.core.experimental.prims.Articulation`, which Isaac Sim 5.1 and 6.x
  ship; it is tested live on 6.2, not yet on 5.x. A Kit app without it, such as USD Composer, gets an error
  naming it.

---

### `set_joint_targets`

Set joint drive position targets.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |
| `targets` | dict or list | `null` | `{joint_name: value}` dict or `[v0, v1, ...]` list. Values in degrees (revolute) or metres (prismatic). |

Works by setting USD drive target attributes directly - does not require articulation initialisation.

---

## Camera Tools

### `set_camera`

Set the viewport camera position and optionally aim it at a target.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `position` | list[float] | required | `[x, y, z]` camera position in world space |
| `target` | list[float] | `null` | `[x, y, z]` point to look at |

---

### `look_at_prim`

Point the viewport camera at a prim from a given angle. Auto-computes distance from object size.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `distance` | float | `null` | Camera distance in metres, above 0 (auto if omitted) |
| `azimuth` | float | `45.0` | Horizontal angle: 0=front, 90=right, 180=back, 270=left |
| `elevation` | float | `30.0` | Vertical angle above horizontal |

---

### `inspect_prim`

Orbit-capture: take screenshots from 14 systematic angles around a prim using a cube-based approach (6 face centres + 8 cube corners). The camera distance is fitted so the prim's bounding sphere fills the captured frame with a 10px margin. Optionally includes instance segmentation at each angle.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `angles` | list[string] | all 14 | Angle names to capture (see below) |
| `width` | int | `640` | Image width per capture, at least 1 |
| `height` | int | `480` | Image height per capture, at least 1 |
| `zoom_offset` | float | `0.0` | Adjust the fitted distance: `-0.3` is 30% closer, `0.5` is 50% further; must be greater than `-1` |
| `isolate` | bool | `false` | Hide everything but the prim while capturing (lights stay on); visibility is restored exactly afterwards. What it cannot hide (inside an instance, or with time-sampled visibility) is listed as `WARNING (isolate)` |
| `include_segmentation` | bool | `false` | Also capture instance segmentation at each angle |

**Available angles (14 total):**

*Face centres (6):* `front`, `back`, `right`, `left`, `top`, `bottom`

*Cube corners (8):* `top_front_right`, `top_front_left`, `top_back_right`, `top_back_left`, `bottom_front_right`, `bottom_front_left`, `bottom_back_right`, `bottom_back_left`

Each angle is saved as a separate PNG file. When `include_segmentation` is true, each angle also saves a segmentation image + legend; an angle without one says why (`seg: ERROR`), such as no data within 5 s of the sensor being enabled. Default captures all 14 angles for full coverage.

A call takes about 90 s at most, under the server's 120 s timeout: 80 s for the angles, then up to 10 s to restore `isolate`. An angle that fails says why on its line; once the viewport renders no frame (30 s with none) or the 80 s run out, the angles left say `Not captured`, so the angles already captured come back. Each angle's image waits 4 frames of the viewport before it is taken, as `capture_viewport`'s does, so it holds what was done before the call.

`angles` also takes `[azimuth, elevation]` pairs in degrees. An unknown angle name, a non-numeric `width`, `height` or `zoom_offset`, or an orthographic viewport camera (such as `/OmniverseKit_Top`; switch to `/OmniverseKit_Persp`) is refused with an error.

---

### `capture_viewport`

Capture the viewport and save **3 files** for full scene understanding:

1. **Viewport image** (PNG) - what the camera sees
2. **Bounding boxes** (TXT) - screen-space pixel coordinates for each visible prim, plus world-space centre and dimensions
3. **Instance segmentation** (PNG + legend TXT) - each prim rendered as a unique colour, with a legend mapping colours to prim paths

Use files 2 and 3 to understand which object is where in the viewport image.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | int | `640` | Image width, at least 1 |
| `height` | int | `480` | Image height, at least 1 |
| `camera_path` | string | `""` | Camera prim to render from (default: active viewport camera) |
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

> **Note:** Instance segmentation requires `omni.syntheticdata` (included in Isaac Sim). Without it, or when it gives no data, the viewport image and bounding boxes are still returned, and `Segmentation: ERROR` says why. After a stage opens, the bridge enables the sensor again and waits up to 5 s for its first data; when none comes, later captures on that stage don't wait again until one gets data.

> **Black image detection:** If the captured image is all-black, the response includes a `WARNING` with the lighting mode and whether scene lights exist. Use the `viewport_light` tool to check the lighting mode and change it if needed, then recapture. No automatic light changes are made.

> **What was done just before shows:** Kit renders a few updates behind the app, so the frame it delivers next is a
> few updates old. A capture lets 4 frames of the viewport pass before it captures, so a drawing or any change made
> just before the call is in the image. It costs those 4 frames: about 20 to 70 ms, at 190 to 60 frames a second.

---

### `viewport_light`

Query or set the viewport's lighting mode. Non-destructive: it changes how the viewport lights the scene, not the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | `"get"` | `"get"`, `"set"`, or the legacy `"set_camera_light"` |
| `mode` | string | `""` | For `set`: `"off"`, `"camera"`, `"stage"`, or a light rig such as `"Default"`, `"Colored Lights"`, `"Grey Studio"` |
| `enabled` | bool | `true` | For `set_camera_light`: `true` is mode `"camera"`, `false` is `"stage"` |

**Actions:**
- **get** - Returns the current lighting mode, the available modes, whether the scene has lights, and a list of all scene light prims (path, type, intensity)
- **set** - Switches the lighting mode. Light rigs need the viewport's lighting menu (`omni.kit.viewport.menubar.lighting`); without it, `"camera"` and `"stage"` still work, and anything else returns an error rather than a false success
- **set_camera_light** - Legacy alias for `set` with `"camera"` or `"stage"`

**When to use:** When `capture_viewport` reports a black image, use `viewport_light("get")` to diagnose, then `viewport_light(action="set", mode="Default")` (a light rig) or `mode="camera"` (a light that follows the camera) and recapture.

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
- **step** - Advance one physics step

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
- `extension_version`, `server_version` - the Kit extension's release, from the bridge's handshake, and this server's
- `note` - only when the bridge's release differs from the server's: the command that installs the matching one

**When to use:** Always call this first to understand the environment (especially up axis and whether physics is running).

---

## Recording Tools

### `start_recording`

Start recording simulation frames to disk. It records the active viewport, from its camera at its own size: aim it
with `set_camera` or `look_at_prim` first. `camera_path`, `width` and `height` are ignored for now
([#25](https://github.com/serionist/omniverse-mcp/issues/25)), and the answer carries a `WARNING` line when it is
given a `camera_path`, or a size other than 640x480: the server can't tell 640x480 asked for from the default. The
recording's `metadata.json` still lists the camera and size asked for, not the ones used. Frames are taken every few
app updates, whether or not the simulation plays: play it to record motion. Unlike `capture_viewport`, a frame doesn't
wait for the renderer to catch up, so its image shows the scene a few updates before its `sim_time`
([#57](https://github.com/serionist/omniverse-mcp/issues/57)).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fps` | int | `5` | Capture rate (frames per second), at least 1 |
| `width` | int | `640` | At least 1; ignored for now: frames come at the active viewport's size |
| `height` | int | `480` | At least 1; as `width` |
| `camera_path` | string | `""` | Ignored for now: frames come from the active viewport's camera |
| `track_prims` | list[string] | `null` | Prim paths to track state for (includes descendants) |
| `property_filter` | list[string] | `null` | Only record properties containing these substrings |

**Workflow:**
1. `start_recording(fps=10, track_prims=["/World/Robot"])`
2. `sim_control("play")`
3. Wait for desired duration...
4. `stop_recording()`
5. `get_recording_frame(0)`, `get_recording_frame(5)`, etc. to review

When `track_prims` is set, a `state.txt` file is written alongside frames in prim-block format. Each frame is separated by `=== FRAME t=X.XXX step=N ===` headers.

---

### `stop_recording`

Stop the active recording session. No parameters.

**Returns:** Frame count, duration, output directory, and state file path (if tracking prims).

---

### `get_recording_frame`

Get a specific frame from a recording session as a PNG.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `frame_index` | int | `0` | Frame number (0-based), not negative |
| `session_dir` | string | `""` | Session directory (uses last recording if empty) |

---

## Physics Tools

### `set_physics_properties`

Set physics material properties on a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `mass` | float | `null` | Mass in kg, not negative (applies MassAPI); 0 unsets it, so density decides |
| `density` | float | `null` | Density in kg/m^3, not negative; 0 unsets it; a mass set wins over it |
| `friction` | float | `null` | Friction coefficient, not negative (usually 0-1) |
| `restitution` | float | `null` | Bounciness, 0 (no bounce) to 1 (full bounce) |

Automatically applies the required USD physics APIs (`MassAPI`, `PhysicsMaterialAPI`, etc.) if not already present.

---

### `apply_force`

Push a rigid body through PhysX, so its mass counts: at `position`, or at its centre of mass when it is left out.
The simulation must be playing or paused. A body can be an articulation's link, such as a robot's: the push moves
the whole robot. The robot's momentum changes by the impulse, so its speed changes by the impulse over the robot's
mass, not the link's, and the link turns about its joints as well. Measured on Isaac Sim 6.2, on PhysX's CPU
pipeline.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Rigid body prim, a robot's link among them |
| `force` | list[float] | required | `[fx, fy, fz]`: an impulse in N s, or a force in N for one physics step |
| `position` | list[float] | `null` | World-space point to push at; the body's centre of mass, as PhysX holds it, when omitted |
| `impulse` | bool | `false` | `true` for an impulse in N s, which changes the velocity at once by `force / mass`; `false` for a force in N for one physics step, which changes it by `force * dt / mass`, `dt` being the physics step (1/60 s by default). One call can't hold a force over many steps: for a sustained push, give an impulse of force times seconds, the same change in velocity at once |

**Refused,** before anything is applied:

| When | Why |
|---|---|
| the simulation is stopped | PhysX holds no bodies then; paused works |
| PhysX runs with its Direct GPU API (`/physics/suppressReadback` is true, as Isaac Sim sets it for a GPU device) | the push returns and moves nothing, as measured on Isaac Sim 6.2 ([#68](https://github.com/serionist/omniverse-mcp/issues/68)): run physics on the CPU to push a body |
| the body is disabled (`physics:rigidBodyEnabled` is false) | PhysX holds it as a static body, which no force moves |
| the body is kinematic (`physics:kinematicEnabled` is true) | PhysX takes the force and moves it only by its transform |
| PhysX holds no rigid body at `prim_path` | nothing to push; `get_logs(min_level="warn")` may say why |
| a fixed joint holds the body to the world, or welds it to a body one holds | no force moves it, as measured on the Franka's base. That is an enabled `UsdPhysics.FixedJoint` whose other end is the world, a static prim or a disabled body, excluded from articulations or not. The error names the articulation when the body is a robot's fixed base or welded to one |
| `position` is left out and PhysX gives the body no mass | no centre of mass to push at: give a `position` |

**Returns:** `position`, the world point pushed at; `at`, `given` or `centre of mass`; `method`, `physx`. A point off
the centre of mass turns the body as well as moving it. Newtons assume a stage in metres and kilograms: PhysX works
in the stage's units (`meters_per_unit` in `get_sim_state`). The centre of mass comes from PhysX's
unit-tests interface (`get_mass_information`), which NVIDIA may change between Kit releases; without it the call is
an error, never a push at another point. All of this is the Kit extension's: one from 0.2.0 nudges
`physics:velocity` instead, and its answer says `method: velocity`.

---

### `raycast`

Cast a ray into the scene and return what it hits.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `origin` | list[float] | required | `[x, y, z]` start point |
| `direction` | list[float] | required | `[dx, dy, dz]` direction (normalised automatically) |
| `max_distance` | float | `1000.0` | Maximum ray length, above 0 |

**Returns:** Hit prim path, hit position, surface normal, and distance. Returns "No hit" if ray doesn't intersect anything.

---

## Debug Tools

### `draw_debug`

Draw debug lines in the viewport for `duration` seconds: a line, a polyline, a sphere as three crossing lines, or a
small cross per point. Every line is 2 pixels wide.

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

- **Drawings belong to their stage:** `new_scene` or opening another stage drops them, and no drawing is made while a
  stage opens or closes.
- **Captures:** on Isaac Sim 6.x, drawings show in `capture_viewport`'s image, headless too, with either extension,
  however soon after `draw_debug` the capture comes (checked live on 6.2). On Isaac Sim 5.x this is untested live.
- **A wrong shape is an error:** an unknown `shape`, a vector that isn't three finite numbers, or a missing part, such
  as `start` for a line.
- **The fix is in the Kit extension:** a bridge from 0.2.0 or before draws for one frame, and fails headless.
  `uvx omniverse-mcp extension install`, then restart Kit.

---

## Extension Tools

### `manage_extensions`

List, enable, or disable Omniverse extensions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | `"list"` | `"list"`, `"enable"`, or `"disable"` |
| `extension_id` | string | `""` | Required for enable/disable |
| `search` | string | `""` | Filter extension list by name (for list) |
| `enabled_only` | bool | `false` | Only show enabled extensions (for list) |

**When to use:** Before using features that depend on optional extensions (e.g., Replicator, measurement tools), check if they're enabled and enable them if needed.

---

## Logging Tools

### `get_logs`

Get recent entries of the Kit app's log.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `count` | int | `50` | Number of recent entries to return, at least 1 (the buffer keeps 2000) |
| `min_level` | string | `""` | Minimum severity: `verbose`, `info`, `warn`, `error`, `fatal`, or `""` for every level |
| `channel` | string | `""` | Filter by log channel substring (e.g. `"omni.physx"`, `"omni.usd"`) |
| `search` | string | `""` | Filter by message substring (case-insensitive) |

**When to use:** After any tool returns an error, call `get_logs(min_level="warn")` to see what Omniverse reported internally. PhysX errors, USD composition failures, missing extensions, and other diagnostics are captured here.

**How it works:** each call reads what Kit added to its log file since the last, from where the file ended when the
extension started, into a ring of the latest 2000 entries.

- **What Kit's file holds:** Info and above by default, from `carb.log_*()`, Python `logging` and Kit's own
  extensions. Verbose lines need Kit started with both `--/log/level=verbose` and `--/log/fileLogLevel=verbose`.
  A Kit app whose `/log/file` setting is empty gets an error naming `--/log/file=<path>`.
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

Set `result = <value>` to return JSON-serialisable data to the AI assistant.

**Example (sync):**
```python
stage = omni.usd.get_context().get_stage()
result = [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
```

**Example (async, with the `mcp` bridge):**
```python
# Using await auto-detects async mode
viewport = await mcp.capture_viewport(width=1280)
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
