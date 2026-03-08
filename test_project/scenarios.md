# Isaac Sim MCP Test Scenarios

Run each phase in order. Record results in `results/test_results.md` using the format from `CLAUDE.md`.

Status values: **PASS** | **FAIL** | **WARN** | **SKIP**

> Phases build on each other. If a phase creates prims, later phases may depend on them.
> After Phase 17 (`new_scene`), the scene is wiped — Phases 18+ create their own prims.
> Phases 24-26 test logging, async scripting, and camera settling (added after initial 23 phases).

---

## Phase 1: Connectivity & State

### 1.1 Health Check
- Call `get_sim_state`
- Verify: returns up_axis, prim_count, state (should be "stopped")

### 1.2 Scene Tree (Empty Scene)
- Call `get_scene_tree`
- Verify: returns at least a root prim
- Note the default prims that exist

---

## Phase 2: Scene Manipulation

### 2.1 Create Primitives
- Create a ground plane: `create_prim("/World/Ground", "Cube", position=[0,-0.05,0], scale=[10,0.1,10])`
- Create a cube: `create_prim("/World/RedCube", "Cube", position=[0,2,0], scale=0.3)`
- Create a sphere: `create_prim("/World/BlueSphere", "Sphere", position=[1,0.5,0], scale=0.2)`
- Create a light: `create_prim("/World/Light", "DistantLight", rotation=[45,0,0])`
- Verify: `get_scene_tree` shows all 4 new prims

### 2.2 Transform Operations (Individual)
- Move the cube: `set_prim_transform("/World/RedCube", position=[2,2,0])`
- Rotate it: `set_prim_transform("/World/RedCube", rotation=[0,45,0])`
- Scale it: `set_prim_transform("/World/RedCube", scale=0.5)`
- Verify: `get_prim_properties("/World/RedCube")` shows updated values

### 2.3 Transform Operations (Combined)
- Set all 3 at once: `set_prim_transform("/World/RedCube", position=[0,1,0], rotation=[0,0,0], scale=0.3)`
- Verify: `get_prim_properties("/World/RedCube")` shows all 3 updated together

### 2.4 Delete Prim
- Delete the sphere: `delete_prim("/World/BlueSphere")`
- Verify: `get_scene_tree` no longer shows it
- Try deleting a non-existent prim: should return error

### 2.5 Bounding Box
- Call `get_prim_bounds("/World/RedCube")`
- Verify: returns center, dimensions, min, max, diagonal
- Dimensions should reflect the current scale

### 2.6 Spatial Reasoning
- Get bounds of Ground and RedCube
- Compute where to place the cube so it sits exactly on top of the ground
- Use `set_prim_transform` to move it there
- Verify with `get_prim_bounds` that the cube's min Z ~ ground's max Z (or Y, depending on up axis)

### 2.7 Create Prim with Physics
- `create_prim("/World/PhysCube", "Cube", position=[2,2,0], scale=0.2, enable_physics=True)`
- Verify: `get_prim_properties("/World/PhysCube")` shows `physics:rigidBodyEnabled` and collision API
- Delete it after: `delete_prim("/World/PhysCube")`

---

## Phase 3: Camera & Visual

### 3.1 Basic Viewport Capture
- Call `capture_viewport(640, 480)`
- Verify: returns image path, bounding box file, segmentation files

### 3.2 Camera Positioning
- Call `set_camera(position=[5, 3, 5], target=[0, 0, 0])`
- Call `capture_viewport(640, 480)`
- Verify: camera shows the scene from an elevated angle

### 3.3 Look At Prim
- Call `look_at_prim("/World/RedCube", azimuth=0, elevation=20)`
- Call `capture_viewport(640, 480)`
- Verify: cube is centered in the frame

### 3.4 Look At with Auto-Distance
- Call `look_at_prim("/World/Ground")` (no distance specified)
- Call `capture_viewport(640, 480)`
- Verify: auto-computed distance shows the ground reasonably framed

### 3.5 Multi-Angle Inspect
- Call `inspect_prim("/World/RedCube", angles=["front", "right", "top"])`
- Verify: returns 3 images from different angles
- The cube should be visible and centered in each

---

## Phase 4: Script Execution

### 4.1 Basic Print
- `execute_script("print('Hello MCP!')")`
- Verify: stdout contains "Hello MCP!"

### 4.2 Return Value
- `execute_script("result = {'version': 1, 'test': True}")`
- Verify: return_value is {"version": 1, "test": True}

### 4.3 USD API Access
- ```python
  execute_script("""
  stage = omni.usd.get_context().get_stage()
  result = [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]
  """)
  ```
- Verify: returns list of root prim paths

### 4.4 Error Handling
- `execute_script("raise ValueError('test error')")`
- Verify: returns error with "test error" and traceback

### 4.5 Add Physics via Script
- Add PhysicsScene, RigidBody, and Collision to RedCube:
  ```python
  execute_script("""
  stage = omni.usd.get_context().get_stage()
  if not stage.GetPrimAtPath('/World/PhysicsScene').IsValid():
      UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
  ground = stage.GetPrimAtPath('/World/Ground')
  if not ground.HasAPI(UsdPhysics.CollisionAPI):
      UsdPhysics.CollisionAPI.Apply(ground)
  cube = stage.GetPrimAtPath('/World/RedCube')
  if not cube.HasAPI(UsdPhysics.RigidBodyAPI):
      UsdPhysics.RigidBodyAPI.Apply(cube)
  if not cube.HasAPI(UsdPhysics.CollisionAPI):
      UsdPhysics.CollisionAPI.Apply(cube)
  result = 'physics added'
  """)
  ```
- Verify: returns "physics added"
- Verify with `get_prim_properties("/World/RedCube")` — should show physics:rigidBodyEnabled

---

## Phase 5: Simulation & Physics

### 5.1 Play/Pause/Stop
- `sim_control("play")` → verify state is "playing"
- `sim_control("pause")` → verify state is "paused"
- `sim_control("stop")` → verify state is "stopped"

### 5.2 Step
- `sim_control("step")` → verify a single frame was advanced

### 5.3 Gravity Test
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `capture_viewport()` — cube should be at y=3
- `sim_control("play")`, wait briefly, `sim_control("stop")`
- `get_prim_bounds("/World/RedCube")` — center Y should be < 3 (fell due to gravity)
- `capture_viewport()` — verify visually

---

## Phase 6: Recording (Basic)

### 6.1 Record a Falling Cube
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `start_recording(fps=5, width=320, height=240)`
- `sim_control("play")`
- Wait ~2 seconds
- `sim_control("stop")`
- `stop_recording()`
- Verify: frame_count > 0, output_dir exists

### 6.2 Review Frames
- `get_recording_frame(frame_index=0)` → should return image path
- Read the frame image — verify it is non-empty (file size > 0)
- `get_recording_frame(frame_index=<last>)` → cube lower or on ground
- Verify: images show cube at different positions

---

## Phase 7: Recording with Prim State Tracking

### 7.1 Record with track_prims
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `start_recording(fps=10, width=320, height=240, track_prims=["/World/RedCube"])`
- `sim_control("play")`
- Wait ~2 seconds
- `sim_control("stop")`
- `stop_recording()`
- Verify: response includes `state_file` path

### 7.2 Validate state.txt Format
- Read the `state.txt` file
- Verify header: `# Isaac Sim MCP Recording State`
- Verify frame markers: `=== FRAME t=X.XXX step=N ===`
- Verify prim blocks: `[/World/RedCube]` with `type = Cube`
- Verify position data: `pos = X.XXXX, Y.XXXX, Z.XXXX`
- Verify Y position decreases across frames (gravity)

### 7.3 Record with property_filter
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `start_recording(fps=10, track_prims=["/World/RedCube"], property_filter=["xformOp", "physics"])`
- `sim_control("play")`, wait ~1s, `sim_control("stop")`, `stop_recording()`
- Read `state.txt`: should only show properties matching "xformOp" or "physics"

---

## Phase 8: Scene Dump (Prim-Block Format)

### 8.1 Full Scene Dump
- `dump_scene(root="/World", include_properties=True)`
- Read the file — verify prim-block format:
  - Header: `# Isaac Sim MCP Scene Dump`
  - Scene marker: `=== SCENE root=/World prims=N ===`
  - Prim blocks with `[/path]`, `type = ...`, `pos = ...`

### 8.2 Filtered by Type
- `dump_scene(root="/World", filter_types=["Cube"])`
- Read: only Cube prims should appear

### 8.3 Filtered by Property
- `dump_scene(root="/World", property_filter=["physics", "collision"])`
- Read: only physics/collision properties in each block

### 8.4 Dump without Properties
- `dump_scene(root="/World", include_properties=False)`
- Read: prim blocks should show type and position but NO property listings

### 8.5 Grep-Friendly Check
- The file from 8.1 should be grep-able:
  - Search for `[/World/RedCube]` → finds prim header
  - Search for `pos =` → finds position lines
  - Search for `type = Cube` → finds cube types

---

## Phase 9: Extension Management

### 9.1 List Extensions
- `manage_extensions(action="list", search="replicator")`
- Verify: shows extensions with ON/OFF status

### 9.2 Enable/Disable Extension
- Find a safe disabled extension from the list
- Enable it: `manage_extensions(action="enable", extension_id="<id>")`
- Verify: success
- Disable it again: `manage_extensions(action="disable", extension_id="<id>")`
- Verify: success, extension is back to disabled

---

## Phase 10: Robot Spawning

### 10.1 Spawn G1 Robot
- `create_robot("g1", position=[3, 0.74, 0])`
- Verify: returns prim path and joint list

### 10.2 Inspect Robot
- `inspect_prim("/World/G1", angles=["front", "right", "top_front_right"])`
- Verify: 3 images showing the robot from cube-based angles

### 10.3 Record Robot with State Tracking
- `start_recording(fps=10, track_prims=["/World/G1"], property_filter=["joint", "pos"])`
- `sim_control("play")`, wait ~2s, `sim_control("stop")`, `stop_recording()`
- Read `state.txt`: should show G1 hierarchy with joint/position data changing per frame

### 10.4 Invalid Robot
- `create_robot("nonexistent_robot")` → should return error

---

## Phase 11: Error Cases

### 11.1 Invalid Prim Path
- `get_prim_properties("/Nonexistent/Path")` → error
- `set_prim_transform("/Nonexistent/Path", position=[0,0,0])` → error
- `delete_prim("/Nonexistent/Path")` → error
- `get_prim_bounds("/Nonexistent/Path")` → error

### 11.2 Invalid Sim Control
- `sim_control("invalid_action")` → error

### 11.3 Script Syntax Error
- `execute_script("def broken(")` → error with traceback

### 11.4 Double Recording
- Start a recording, then try `start_recording()` again → error

### 11.5 Stop Without Recording
- `stop_recording()` when none active → error

---

## Phase 12: Materials

### 12.1 Set Material - Basic Color
- `set_material("/World/RedCube", color=[1,0,0])`
- Verify: returns material_path, color=[1,0,0]

### 12.2 Set Material - 0-255 Color Range
- `set_material("/World/Ground", color=[128,128,128])`
- Verify: color auto-normalized to ~0.5 each channel

### 12.3 Set Material - PBR Properties
- `set_material("/World/RedCube", color=[0.8,0.1,0.1], roughness=0.2, metallic=0.9)`
- Verify: roughness=0.2, metallic=0.9 in response

### 12.4 Set Material - Opacity
- `set_material("/World/RedCube", color=[1,0,0], opacity=0.5)`
- Verify: opacity=0.5

### 12.5 Set Material - Custom Path
- `set_material("/World/RedCube", color=[0,1,0], material_path="/World/Looks/MyGreenMat")`
- Verify: material_path="/World/Looks/MyGreenMat"

### 12.6 Set Material - Invalid Prim
- `set_material("/World/Nonexistent", color=[1,0,0])` → error

### 12.7 Set Material - Invalid Color
- `set_material("/World/RedCube", color=[1,0])` → error (needs 3 values)

### 12.8 Verify Material Visually
- Apply red material, look_at_prim, capture_viewport
- Verify: cube should appear colored (not default white/gray)

---

## Phase 13: Visibility & Cloning

### 13.1 Hide a Prim
- `set_visibility("/World/RedCube", visible=False)`
- Verify: visible=false in response

### 13.2 Show a Prim
- `set_visibility("/World/RedCube", visible=True)`
- Verify: visible=true in response

### 13.3 Visibility on Invalid Prim
- `set_visibility("/World/Nonexistent", visible=False)` → error

### 13.4 Clone a Single Prim
- `clone_prim("/World/RedCube", "/World/RedCube_Clone")`
- Verify: clone exists via `get_prim_properties`

### 13.5 Clone Multiple Copies with Offset
- `clone_prim("/World/RedCube", "/World/CloneBatch", count=3, offset=[2,0,0])`
- Verify: 3 clones created (`/World/CloneBatch_001`, `_002`, `_003`)

### 13.6 Clone - Verify Offset Positions
- Get bounds of each clone from 13.5
- Verify: each clone is offset by [2,0,0] from the previous one

### 13.7 Clone Invalid Source
- `clone_prim("/World/Nonexistent", "/World/Clone")` → error

---

## Phase 14: Robot Control

### 14.1 Get Robot Info
- `get_robot_info("/World/G1")`
- Verify: returns joints, dof_count > 0, link_count > 0

### 14.2 Robot Info on Non-Robot
- `get_robot_info("/World/RedCube")`
- Verify: returns dof_count = 0 (not an articulation)

### 14.3 Set Joint Targets
- Get first joint name from robot info
- `set_joint_targets("/World/G1", targets={joint_name: 0.0})`
- Verify: targets_set > 0

### 14.4 Get Joint States
- Play sim briefly, then pause
- `get_joint_states("/World/G1")`
- Verify: returns positions and dof_count > 0

---

## Phase 15: Physics Properties & Forces

### 15.1 Set Mass
- `set_physics_properties("/World/RedCube", mass=5.0)`
- Verify: "mass=5.0" in applied list

### 15.2 Set Friction and Restitution
- `set_physics_properties("/World/RedCube", friction=0.8, restitution=0.3)`
- Verify: friction and restitution in applied list

### 15.3 Set Density
- `set_physics_properties("/World/RedCube", density=1000.0)`
- Verify: "density=1000.0" in applied list

### 15.4 Physics on Invalid Prim
- `set_physics_properties("/World/Nonexistent", mass=1.0)` → error

### 15.5 Apply Force (Basic)
- Play sim, apply force to RedCube: `apply_force("/World/RedCube", force=[100,0,0])`
- Verify: success, returns method used

### 15.6 Apply Force with Impulse
- Play sim: `sim_control("play")`
- `apply_force("/World/RedCube", force=[50,0,0], impulse=True)`
- Verify: response shows "impulse" mode

### 15.7 Apply Force at Offset Position
- Play sim: `sim_control("play")`
- `apply_force("/World/RedCube", force=[0,100,0], position=[0.1,0,0])`
- Verify: success (off-center force should cause torque)
- `sim_control("stop")`

### 15.8 Apply Force to Invalid Prim
- `apply_force("/World/Nonexistent", force=[1,0,0])` → error

---

## Phase 16: Raycasting & Debug Draw

### 16.1 Raycast Hit
- `sim_control("play")` (PhysX needs running sim)
- Cast ray downward from [0,10,0] direction [0,-1,0]: `raycast(origin=[0,10,0], direction=[0,-1,0])`
- Verify: hit=true with prim_path and distance

### 16.2 Raycast Miss
- Cast ray into empty space: `raycast(origin=[100,100,100], direction=[0,1,0], max_distance=1.0)`
- Verify: hit=false
- `sim_control("stop")`

### 16.3 Draw Debug Line
- `draw_debug("line", start=[0,0,0], end=[5,5,0], color=[1,0,0])`
- Verify: success

### 16.4 Draw Debug Sphere
- `draw_debug("sphere", center=[0,2,0], radius=0.5, color=[0,1,0])`
- Verify: success

### 16.5 Draw Debug Points
- `draw_debug("points", points=[[0,0,0],[1,1,0],[2,0,0]], color=[0,0,1])`
- Verify: success

### 16.6 Debug Draw Visual Check
- `capture_viewport()` after 16.3-16.5
- Verify: debug shapes visible in viewport (or note if they aren't — some renderers don't show debug draws in captures)

---

## Phase 17: Scene Lifecycle

### 17.1 Save Scene to File
- `save_scene(file_path="results/mcp_test_scene.usd")`
- Verify: file_path and action in response

### 17.2 Create New Scene
- `new_scene()`
- Verify: `get_scene_tree` shows minimal default prims (just /World or similar)
- Note: this wipes all prims from Phases 2-16. Phases 18+ create their own.

---

## Phase 18: Geometry & Mesh Analysis

> **Setup:** Phase 17.2 wiped the scene. This phase creates its own prims.
>
> **Note:** Procedural prims (`UsdGeom.Cube`, `Sphere`, etc.) are implicit surfaces, not `UsdGeom.Mesh`, and return 0 faces/vertices. Only actual `UsdGeom.Mesh` prims (robots, imported models) have countable geometry.

### 18.1 Mesh Stats on Robot (Mesh Geometry)
- Spawn a robot: `create_robot("franka", position=[0, 0, 0])`
- `get_mesh_stats("/World/Franka")`
- Verify: total_faces > 0, total_vertices > 0, mesh_count > 0, meshes array populated

### 18.2 Mesh Stats on Procedural Prim (Expected Zero)
- Create a cube: `create_prim("/World/TestCube", "Cube", position=[3,0.5,0])`
- `get_mesh_stats("/World/TestCube")`
- Verify: total_faces=0, mesh_count=0 (procedural prims are not UsdGeom.Mesh — this is expected)

### 18.3 Mesh Stats on Invalid Prim
- `get_mesh_stats("/World/Nonexistent")` → error

### 18.4 Face Count Tree
- `get_prim_face_count_tree("/World")`
- Verify: hierarchical tree showing Franka with subtree_faces > 0, TestCube with 0

### 18.5 Face Count Tree with Depth Limit
- `get_prim_face_count_tree("/World", max_depth=1)`
- Verify: only top-level children shown, no deeper nesting

---

## Phase 19: USD Operations

### 19.1 Flatten USD (Current Stage)
- Save scene first: `save_scene(file_path="results/test_flatten_source.usda")`
- `flatten_usd("results/test_flatten_output.usdc")`
- Verify: success, output file path returned

### 19.2 Flatten USD (External File)
- `flatten_usd("results/test_flatten_output2.usdc", "results/test_flatten_source.usda")`
- Verify: success, flattened from the external file

### 19.3 Export Prim as File
- `export_prim_as_file("/World/TestCube", "results/exported_cube.usdc")`
- Verify: success, returns prim_path, output_path, target_root, materials_included, up_axis

### 19.4 Export Prim with Materials
- First apply a material: `set_material("/World/TestCube", color=[1,0,0])`
- `export_prim_as_file("/World/TestCube", "results/exported_cube_mats.usdc")`
- Verify: success, materials_included > 0 (materials are always included automatically)

### 19.5 Export Invalid Prim
- `export_prim_as_file("/World/Nonexistent", "results/fail.usdc")` → error

---

## Phase 20: Variant Tools

### 20.1 Create Variant Structure
- `create_variant_structure("/World/TestCube", "detail", ["high", "low"])`
- Verify: returns variant_set, variants list, prim_path

### 20.2 Create Variant Structure with Default
- `create_variant_structure("/World/Franka", "lod", ["full", "proxy"], default_variant="full")`
- Verify: default_variant="full" in response

### 20.3 Set Variant Selection
- `set_variant_selection("/World/TestCube", "detail", "low")`
- Verify: old_selection, new_selection="low", available_variants

### 20.4 Set Variant Selection - Invalid Variant
- `set_variant_selection("/World/TestCube", "detail", "nonexistent")` → error listing available variants

### 20.5 Set Variant Selection - Invalid Variant Set
- `set_variant_selection("/World/TestCube", "nonexistent_set", "value")` → error listing available variant sets

### 20.6 Compare Prims (Direct)
- `compare_prims(prim_path_a="/World/TestCube", prim_path_b="/World/Franka")`
- Verify: returns a/b stats (faces, vertices, triangles, mesh_count, bounds, materials) and delta

### 20.7 Compare Prims (Variant)
- `compare_prims(prim_path="/World/TestCube", variant_set="detail", variant_a="high", variant_b="low")`
- Verify: returns a/b stats for each variant and delta

### 20.8 Compare Prims - Invalid
- `compare_prims()` (no args) → error about missing arguments

---

## Phase 21: Material Path Updates

### 21.1 Update Material Paths
- Ensure a material exists: `set_material("/World/TestCube", color=[1,0,0], material_path="/World/Looks/TestMat")`
- `update_material_paths("/World/Looks", "/World/NewLooks", "/World")`
- Verify: returns updated_bindings count, updated_asset_paths count

### 21.2 Update Material Paths - No Matches
- `update_material_paths("/Nonexistent/Looks", "/Other/Looks", "/World")`
- Verify: success with 0 updates (no error, just nothing to do)

---

## Phase 22: Enhanced Inspect Prim

### 22.1 Inspect with Segmentation
- `inspect_prim("/World/TestCube", angles=["front", "right"], include_segmentation=True)`
- Verify: each capture has segmentation image + legend in addition to the viewport image

### 22.2 Inspect with Cube Corner Angles
- `inspect_prim("/World/Franka", angles=["top_front_right", "top_back_left", "bottom_front_right", "bottom"])`
- Verify: 4 images from the cube-based angle presets, robot visible in each

### 22.3 Inspect Non-Existent Prim
- `inspect_prim("/World/Nonexistent")` → error

---

## Phase 23: Viewport Lighting

### 23.1 Get Lighting State
- `viewport_light("get")`
- Verify: returns camera_light_on (bool), has_scene_lights (bool), scene_lights list

### 23.2 Enable Camera Light
- `viewport_light("set_camera_light", enabled=True)`
- Verify: camera_light_on=true in response
- `capture_viewport()` → scene should be lit

### 23.3 Disable Camera Light
- `viewport_light("set_camera_light", enabled=False)`
- Verify: camera_light_on=false in response

### 23.4 Black Image Detection
- Delete all lights if any exist
- Disable camera light: `viewport_light("set_camera_light", enabled=False)`
- `capture_viewport()` → should include WARNING about all-black image with lighting diagnostics
- Enable camera light: `viewport_light("set_camera_light", enabled=True)`
- `capture_viewport()` → image should now be lit, no WARNING

---

## Phase 24: Logging

### 24.1 Get Logs (Default)
- Call `get_logs()`
- Verify: returns entries array, total_captured > 0, buffer_size > 0
- Note the number of entries returned

### 24.2 Get Logs with Level Filter
- Call `get_logs(count=20, min_level="warn")`
- Verify: all returned entries have level "warn", "error", or "fatal"
- If no warn+ entries exist, verify empty entries array (not error)

### 24.3 Get Logs with Search Filter
- Call `get_logs(search="MCP")`
- Verify: all returned entry messages contain "MCP" (case-insensitive)
- The MCP bridge logs its own startup, so there should be matches

### 24.4 Get Logs with Channel Filter
- Call `get_logs(channel="omni")`
- Verify: all returned entries have a channel containing "omni"

### 24.5 Get Logs with since_index
- Call `get_logs(count=5)` → note the last entry's `index`
- Call `get_logs(since_index=<last_index>)` → should return only entries after that index
- Verify: all returned entries have index > the noted index

### 24.6 Get Logs After Error
- Execute a script that causes an error: `execute_script("raise RuntimeError('log_test_error')")`
- Call `get_logs(count=10, search="log_test_error")`
- Verify: the error appears in the log entries

---

## Phase 25: Async Script Execution (MCP Bridge)

> **Note:** These tests verify the `mcp` bridge object available inside `execute_script`.
> Scripts using `await` are automatically detected as async and wrapped accordingly.

### 25.1 Async Scene Tree via MCP Bridge
- ```python
  execute_script("""
  tree = await mcp.scene_tree()
  result = tree['status']
  """)
  ```
- Verify: return_value is "success"

### 25.2 Async Sim State via MCP Bridge
- ```python
  execute_script("""
  state = await mcp.sim_state()
  result = {
      'up_axis': state['result']['up_axis'],
      'status': state['status']
  }
  """)
  ```
- Verify: return_value has up_axis and status="success"

### 25.3 Async Create and Query
- ```python
  execute_script("""
  await mcp.create_prim('/World/McpTestCube', 'Cube', position=[0, 1, 0])
  bounds = await mcp.prim_bounds('/World/McpTestCube')
  result = bounds['result']['center']
  """)
  ```
- Verify: return_value is approximately [0, 1, 0]
- Clean up: `delete_prim("/World/McpTestCube")`

### 25.4 Async Camera and Capture
- ```python
  execute_script("""
  await mcp.set_camera([5, 3, 5], target=[0, 0, 0])
  cap = await mcp.capture_viewport(width=320, height=240)
  result = {
      'status': cap['status'],
      'has_image': 'image_base64' in cap.get('result', {})
  }
  """)
  ```
- Verify: status="success", has_image=True

### 25.5 Async Logs via MCP Bridge
- ```python
  execute_script("""
  logs = await mcp.get_logs(count=5)
  result = {
      'count': logs['result']['count'],
      'status': logs['status']
  }
  """)
  ```
- Verify: status="success", count >= 0

### 25.6 Sync Script Still Works
- Verify that regular (non-async) scripts still work after async tests:
  ```python
  execute_script("result = 42")
  ```
- Verify: return_value is 42

### 25.7 Mixed Sync and Async in Same Script
- ```python
  execute_script("""
  import math
  x = math.sqrt(144)
  state = await mcp.sim_state()
  result = {'sqrt': x, 'up_axis': state['result']['up_axis']}
  """)
  ```
- Verify: return_value has sqrt=12.0 and a valid up_axis

### 25.8 Async Script Error Handling
- ```python
  execute_script("""
  bounds = await mcp.prim_bounds('/World/Nonexistent_MCP_Test')
  result = bounds['status']
  """)
  ```
- Verify: return_value is "error" (MCP bridge returns error responses, doesn't raise exceptions)

---

## Phase 26: Camera Frame Settling

> **Note:** These tests verify that camera moves properly settle before capture.
> The camera handlers now use `_settle_viewport()` (20 frames) instead of 1-2 `_next_update()` calls.

### 26.1 Camera Set + Immediate Capture
- `set_camera(position=[5, 3, 5], target=[0, 0, 0])`
- Immediately: `capture_viewport(640, 480)` — do NOT add any delay
- Verify: captured image is not black and shows the scene from the expected angle
- Repeat 3 times with different camera positions to test consistency

### 26.2 Look At + Immediate Capture
- Create a test prim: `create_prim("/World/SettleTest", "Cube", position=[0, 1, 0], scale=0.5)`
- `look_at_prim("/World/SettleTest", azimuth=45, elevation=30)`
- Immediately: `capture_viewport(640, 480)`
- Verify: the cube is visible in the capture
- Clean up: `delete_prim("/World/SettleTest")`

---

## Phase 27: Cleanup

### 27.1 Clean Up Scene
- `sim_control("stop")`
- Delete all test prims: `/World/Franka`, `/World/TestCube`, `/World/Looks`, `/World/NewLooks`, and any other prims created during testing
- Verify: `get_scene_tree` shows minimal default prims
