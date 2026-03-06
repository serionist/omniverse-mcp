# Isaac Sim MCP Test Scenarios

Run each scenario in order. Record PASS/FAIL in `results/test_results.md`.

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

### 2.2 Transform Operations
- Move the cube: `set_prim_transform("/World/RedCube", position=[2,2,0])`
- Rotate it: `set_prim_transform("/World/RedCube", rotation=[0,45,0])`
- Scale it: `set_prim_transform("/World/RedCube", scale=0.5)`
- Verify: `get_prim_properties("/World/RedCube")` shows updated values

### 2.3 Delete Prim
- Delete the sphere: `delete_prim("/World/BlueSphere")`
- Verify: `get_scene_tree` no longer shows it
- Try deleting a non-existent prim: should return error

### 2.4 Bounding Box
- Call `get_prim_bounds("/World/RedCube")`
- Verify: returns center, dimensions, min, max, diagonal
- Dimensions should reflect the current scale

### 2.5 Spatial Reasoning
- Get bounds of Ground and RedCube
- Compute where to place the cube so it sits exactly on top of the ground
- Use `set_prim_transform` to move it there
- Verify with `get_prim_bounds` that the cube's min Y ~ ground's max Y

---

## Phase 3: Camera & Visual

### 3.1 Basic Viewport Capture
- Call `capture_viewport(640, 480)`
- Verify: returns an image

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
- `get_recording_frame(frame_index=0)` → cube at top
- `get_recording_frame(frame_index=5)` → cube lower or on ground
- Verify cube moved between frames

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

### 8.4 Grep-Friendly Check
- The file should be grep-able:
  - Search for `[/World/RedCube]` → finds prim header
  - Search for `pos =` → finds position lines
  - Search for `type = Cube` → finds cube types

---

## Phase 9: Extension Management

### 9.1 List Extensions
- `manage_extensions(action="list", search="replicator")`
- Verify: shows extensions with ON/OFF status

### 9.2 Enable/Disable Extension
- Find a disabled extension and try toggling it

---

## Phase 10: Robot Spawning

### 10.1 Spawn G1 Robot
- `create_robot("g1", position=[3, 0.74, 0])`
- Verify: returns prim path and joint list

### 10.2 Inspect Robot
- `inspect_prim("/World/G1", angles=["front", "right", "perspective"])`
- Verify: 3 images showing the robot

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
- Verify: 3 clones created

### 13.6 Clone Invalid Source
- `clone_prim("/World/Nonexistent", "/World/Clone")` → error

---

## Phase 14: Robot Control

### 14.1 Get Robot Info
- `get_robot_info("/World/G1")`
- Verify: returns joints, dof_count > 0, link_count

### 14.2 Robot Info on Non-Robot
- `get_robot_info("/World/RedCube")`
- Verify: dof_count = 0

### 14.3 Set Joint Targets
- Get first joint name from robot info
- `set_joint_targets("/World/G1", targets={joint_name: 0.0})`
- Verify: targets_set > 0

### 14.4 Get Joint States
- Play sim briefly, then pause
- `get_joint_states("/World/G1")`
- Verify: returns positions and dof_count

---

## Phase 15: Physics Properties & Forces

### 15.1 Set Mass
- `set_physics_properties("/World/RedCube", mass=5.0)`
- Verify: "mass=5.0" in applied list

### 15.2 Set Friction and Restitution
- `set_physics_properties("/World/RedCube", friction=0.8, restitution=0.3)`
- Verify: friction and restitution in applied list

### 15.3 Physics on Invalid Prim
- `set_physics_properties("/World/Nonexistent", mass=1.0)` → error

### 15.4 Apply Force
- Play sim, apply force to RedCube: `apply_force("/World/RedCube", force=[100,0,0])`
- Verify: success, check method

### 15.5 Apply Force to Invalid Prim
- `apply_force("/World/Nonexistent", force=[1,0,0])` → error

---

## Phase 16: Raycasting & Debug Draw

### 16.1 Raycast Hit
- Cast ray downward from [0,10,0] direction [0,-1,0]
- Verify: hit=true with prim_path and distance

### 16.2 Raycast Miss
- Cast very short ray into empty space
- Verify: hit=false (or just no error)

### 16.3 Draw Debug Line
- `draw_debug("line", start=[0,0,0], end=[5,5,0], color=[1,0,0])`
- Verify: success

### 16.4 Draw Debug Sphere
- `draw_debug("sphere", center=[0,2,0], radius=0.5, color=[0,1,0])`
- Verify: success

### 16.5 Draw Debug Points
- `draw_debug("points", points=[[0,0,0],[1,1,0],[2,0,0]], color=[0,0,1])`
- Verify: success

---

## Phase 17: Scene Lifecycle

### 17.1 Save Scene to File
- `save_scene(file_path="<temp_path>/mcp_test_scene.usd")`
- Verify: file_path and action in response

### 17.2 Create New Scene (destructive)
- `new_scene()`
- Verify: /World root prim exists in new scene

---

## Phase 18: Cleanup

### 18.1 Clean Up Scene
- Delete all test prims (including /World/Looks, clones)
- `sim_control("stop")`
- Verify: `get_scene_tree` shows minimal default prims
