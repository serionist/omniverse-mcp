# Tool Reference

Complete reference for all 32 MCP tools provided by Omniverse MCP.

## Table of Contents

- [Scene Tools](#scene-tools) (12 tools)
- [Robot Tools](#robot-tools) (4 tools)
- [Camera Tools](#camera-tools) (4 tools)
- [Simulation Tools](#simulation-tools) (2 tools)
- [Recording Tools](#recording-tools) (3 tools)
- [Physics Tools](#physics-tools) (3 tools)
- [Debug Tools](#debug-tools) (1 tool)
- [Extension Tools](#extension-tools) (1 tool)
- [Script Execution](#script-execution) (1 tool)
- [MCP Resources](#mcp-resources)

---

## Scene Tools

### `get_scene_tree`

Get the USD scene hierarchy as grep-friendly prim-block text.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/"` | Starting prim path |
| `max_depth` | int | `5` | Traversal depth (max 15) |

**Returns:** Prim-block text showing each prim's path, type, and world position. Written to file if output exceeds 1000 characters.

**When to use:** Quick scene overview for scenes under ~100 prims. For larger scenes, use `dump_scene`.

---

### `dump_scene`

Dump the full scene graph to a text file with all properties, bounding boxes, and transforms.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `root` | string | `"/"` | Starting prim path |
| `max_depth` | int | `15` | Max traversal depth |
| `include_properties` | bool | `true` | Include all USD properties per prim |
| `filter_types` | list[string] | `null` | Only include prims of these types (e.g., `["Mesh", "Xform"]`) |
| `property_filter` | list[string] | `null` | Only include properties containing these substrings |

**Returns:** File path to the dump. Use your file reading tool to examine specific parts.

**When to use:** Large scenes where you need full property data. The output is in prim-block format -- grep for prim paths or property names.

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

**Returns:** Center, dimensions, min/max corners, and diagonal length. Essential for spatial reasoning -- computing placement positions, checking overlaps, measuring distances.

---

### `set_prim_transform`

Set position, rotation, and/or scale of a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path |
| `position` | list[float] | `null` | `[x, y, z]` in meters |
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

**When to use:** Creating geometric shapes, lights, cameras, or loading external USD assets.

---

### `delete_prim`

Delete a prim and all its children from the scene.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Full USD path to delete |

---

### `set_material`

Apply a PBR material (OmniPBR) to a prim with color and surface properties.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `color` | list[float] | required | `[r, g, b]` diffuse color. 0-1 floats or 0-255 ints (auto-detected) |
| `opacity` | float | `1.0` | 0.0 (transparent) to 1.0 (opaque) |
| `roughness` | float | `0.5` | 0.0 (glossy) to 1.0 (matte) |
| `metallic` | float | `0.0` | 0.0 (plastic) to 1.0 (metal) |
| `material_path` | string | `""` | Custom material prim path (auto-generated under `/World/Looks/` if omitted) |

---

### `clone_prim`

Deep-copy a prim and all its children to a new path. Supports batch cloning with offset.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source_path` | string | required | Prim to clone |
| `target_path` | string | required | Destination path |
| `count` | int | `1` | Number of copies. Paths auto-suffixed: `_001`, `_002`, ... |
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

Create a fresh empty scene with a `/World` root prim and Y-up axis.

No parameters.

---

## Robot Tools

### `create_robot`

Spawn a robot from the asset library (Isaac Sim only).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `robot_type` | string | required | Robot name or full USD asset path |
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

You can also pass a full USD file path as `robot_type` to load any custom robot asset.

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

**Note:** Requires the simulation to have played at least once to populate joint state data.

---

### `set_joint_targets`

Set joint drive position targets.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Root prim of the robot |
| `targets` | dict or list | `null` | `{joint_name: value}` dict or `[v0, v1, ...]` list. Values in degrees (revolute) or meters (prismatic). |

Works by setting USD drive target attributes directly -- does not require articulation initialization.

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
| `distance` | float | `null` | Camera distance in meters (auto if omitted) |
| `azimuth` | float | `45.0` | Horizontal angle: 0=front, 90=right, 180=back, 270=left |
| `elevation` | float | `30.0` | Vertical angle above horizontal |

---

### `inspect_prim`

Orbit-capture: take screenshots from multiple angles around a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `angles` | list[string] | `["front", "right", "back", "left", "top"]` | Angle names to capture |
| `width` | int | `800` | Image width per capture |
| `height` | int | `600` | Image height per capture |
| `distance` | float | `null` | Camera distance (auto from object size) |

**Available angles:** `front`, `right`, `back`, `left`, `top`, `perspective`

Each angle is saved as a separate PNG file.

---

### `capture_viewport`

Capture a screenshot from the viewport and save as a PNG file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `width` | int | `1280` | Image width |
| `height` | int | `720` | Image height |
| `camera_path` | string | `""` | Camera prim to render from (default: active viewport camera) |

**Returns:** File path to the saved PNG. Use your file reading tool to view the image.

---

## Simulation Tools

### `sim_control`

Control the simulation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | required | `"play"`, `"pause"`, `"stop"`, or `"step"` |

- **play** -- Start or resume physics simulation
- **pause** -- Pause simulation (state preserved)
- **stop** -- Stop simulation and reset to initial state
- **step** -- Advance one physics step

---

### `get_sim_state`

Get the current simulation state. No parameters.

**Returns:**
- `state` -- `playing`, `paused`, or `stopped`
- `up_axis` -- `Y` or `Z`
- `time` -- Elapsed simulation time in seconds
- `fps` -- Current frames per second
- `prim_count` -- Total number of prims in the scene
- `meters_per_unit` -- Stage scale factor

**When to use:** Always call this first to understand the environment (especially up axis and whether physics is running).

---

## Recording Tools

### `start_recording`

Start recording simulation frames to disk.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fps` | int | `5` | Capture rate (frames per second) |
| `width` | int | `640` | Frame width |
| `height` | int | `480` | Frame height |
| `camera_path` | string | `""` | Camera to record from |
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
| `frame_index` | int | `0` | Frame number (0-based) |
| `session_dir` | string | `""` | Session directory (uses last recording if empty) |

---

## Physics Tools

### `set_physics_properties`

Set physics material properties on a prim.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Target prim |
| `mass` | float | `null` | Mass in kg (applies MassAPI) |
| `density` | float | `null` | Density in kg/m^3 |
| `friction` | float | `null` | Friction coefficient (0-1) |
| `restitution` | float | `null` | Bounciness (0=no bounce, 1=full bounce) |

Automatically applies the required USD physics APIs (`MassAPI`, `PhysicsMaterialAPI`, etc.) if not already present.

---

### `apply_force`

Apply a force or impulse to a rigid body. Simulation must be playing.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prim_path` | string | required | Rigid body prim |
| `force` | list[float] | required | `[fx, fy, fz]` in Newtons (force) or N*s (impulse) |
| `position` | list[float] | `null` | World-space application point (default: center of mass) |
| `impulse` | bool | `false` | `true` for instantaneous impulse, `false` for continuous force |

---

### `raycast`

Cast a ray into the scene and return what it hits.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `origin` | list[float] | required | `[x, y, z]` start point |
| `direction` | list[float] | required | `[dx, dy, dz]` direction (normalized automatically) |
| `max_distance` | float | `1000.0` | Maximum ray length |

**Returns:** Hit prim path, hit position, surface normal, and distance. Returns "No hit" if ray doesn't intersect anything.

---

## Debug Tools

### `draw_debug`

Draw debug visualization in the viewport.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `shape` | string | required | `"line"`, `"sphere"`, or `"points"` |
| `color` | list[float] | `[1,0,0]` | `[r, g, b]` in 0-1 range |
| `duration` | float | `5.0` | Display duration in seconds |
| `start` | list[float] | `null` | Line start `[x,y,z]` (for `shape="line"`) |
| `end` | list[float] | `null` | Line end `[x,y,z]` (for `shape="line"`) |
| `center` | list[float] | `null` | Sphere center `[x,y,z]` (for `shape="sphere"`) |
| `radius` | float | `0.1` | Sphere radius (for `shape="sphere"`) |
| `points` | list[list[float]] | `null` | List of `[x,y,z]` points (for `shape="points"`) |
| `size` | float | `5.0` | Point size (for `shape="points"`) |

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

Set `result = <value>` to return JSON-serializable data to the AI assistant.

**Example:**
```python
stage = omni.usd.get_context().get_stage()
result = [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
```

**When to use:** Complex operations not covered by other tools -- custom physics queries, batch operations, accessing APIs that don't have dedicated tools.

**Fallback strategy:** Every MCP tool in this server can be replicated via `execute_script` using the Omniverse Python API directly. If any tool returns an error, you can fall back to writing the equivalent Python code. Use Context7 (`isaac-sim/isaacsim`) or the [NVIDIA Omniverse docs](https://docs.omniverse.nvidia.com/) to look up the correct API rather than guessing.

---

## MCP Resources

Two MCP resources are available for clients that support resource subscriptions:

| URI | Description |
|-----|-------------|
| `isaac://scene/tree` | Current scene hierarchy (auto-updated) |
| `isaac://sim/state` | Current simulation state |
