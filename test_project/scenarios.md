# Omniverse MCP Test Scenarios

The AI scenario suite. `run-scenarios` (`uv run tools/scenarios.py run`) gives each phase to a headless tester of its
own, whose rules are `AGENTS.md`; a client opened here by hand reads them through `CLAUDE.md`.

Status values: **PASS** | **FAIL** | **WARN** | **SKIP**

> Each phase opens with a `Needs:` line: the scenarios whose prims or state it uses, which a run of that phase alone
> runs first. Phases 1 to 17 and 18 to 27 are two halves, each started on a new stage, and no `Needs:` line crosses
> them. Phase 27 ends every run.
> A path that starts `<run>/` lies in the run's folder, which a run fills in.
> Phases 18 to 21 and 27 have no twin in `tests/test_scenarios.py`.
> Vectors below are written for a Y-up stage, which `new_scene` makes. On a Z-up stage (`get_sim_state`'s `up_axis`;
> Isaac Sim's own new stage is Z-up), swap each vector's Y and Z, so heights stay along the up axis and the ground
> stays a floor.

---

## Phase 1: Connectivity & State

Needs: none

### 1.1 Health Check
- Call `get_sim_state`
- Verify: returns up_axis, prim_count, state (should be "stopped")

### 1.2 Scene Tree (Empty Scene)
- Call `get_scene_tree`
- Verify: returns at least a root prim
- Note the default prims that exist

---

## Phase 2: Scene Manipulation

Needs: none

### 2.1 Create Primitives
- Create a ground plane: `create_prim("/World/Ground", "Cube", position=[0,-0.05,0], scale=[10,0.1,10])`
- Create a cube: `create_prim("/World/RedCube", "Cube", position=[0,2,0], scale=0.3)`, and make it red, as the
  phases after it look for it by colour: `set_material("/World/RedCube", color=[1,0,0])`
- Create a sphere: `create_prim("/World/BlueSphere", "Sphere", position=[1,0.5,0], scale=0.2)`
- Create a light: `create_prim("/World/Light", "DistantLight", rotation=[-50,30,0])`, then
  `execute_script("UsdLux.DistantLight(omni.usd.get_context().get_stage().GetPrimAtPath('/World/Light')).CreateIntensityAttr(3000.0)")`.
  A distant light shines along its own -Z. This rotation turns it down onto the scene from the side 3.2's camera
  stands on, lighting the faces turned to +X, the side and the top, on a Y-up stage and a Z-up one alike: keep it as
  it is on either, unswapped. 3000 is Kit's own sun's intensity, where the default 50000 washes the scene out white
- Verify: `get_scene_tree` shows all 4 new prims, and the cube's material under `/World/Looks`

### 2.2 Transform Operations (Individual)
- Move the cube: `set_prim_transform("/World/RedCube", position=[2,2,0])`
- Rotate it: `set_prim_transform("/World/RedCube", rotation=[0,45,0])`
- Scale it: `set_prim_transform("/World/RedCube", scale=0.5)`
- Verify: `get_prim_properties("/World/RedCube")` shows the three ops set, and `rot = 0.9239, 0.0000, 0.3827, 0.0000`:
  the 45° turn about Y as a quaternion `w, x, y, z`, the 0.5 scale taken out

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

Needs: 2.1

### 3.1 Basic Viewport Capture
- Call `capture_viewport(640, 480)`
- Verify: returns image path, bounding box file, segmentation files; the image is 640x480, the size asked for, not the
  viewport's (#51)

### 3.2 Camera Positioning
- Call `set_camera(position=[5, 3, 5])`, with no target
- Call `capture_viewport(640, 480)`
- Verify: the answer says it looks at `[0, 0, 0]`, the world origin, as no target was given; the camera shows the scene
  from an elevated angle, the origin in the middle: aimed, not only moved, in any Kit app

### 3.3 Look At Prim
- Call `set_camera(prim_path="/World/RedCube", azimuth=0, elevation=20)`
- Call `capture_viewport(640, 480)`
- Verify: cube is centred in the frame, and the answer names the cube and gives the distance in stage units

### 3.4 Look At with Auto-Distance
- Call `set_camera(prim_path="/World/Ground")` (no distance specified)
- Call `capture_viewport(640, 480)`
- Verify: auto-computed distance shows the ground reasonably framed

### 3.5 Multi-Angle Inspect
- Call `inspect_prim("/World/RedCube", angles=["front", "right", "top"])`
- Verify: returns 3 images from different angles, auto-fit distance > 0
- The cube should fill the frame (auto-fit computes distance from FOV + bounding sphere)

---

## Phase 4: Script Execution

Needs: 2.1

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

Needs: 2.1, 4.5

### 5.1 Play/Pause/Stop
- `sim_control("play")` → verify state is "playing"
- `sim_control("pause")` → verify state is "paused"
- `sim_control("stop")` → verify state is "stopped"

### 5.2 Step
- `get_sim_state`, then `sim_control("step")`, then `get_sim_state` again
- Verify: the step's answer says paused, and `time` moved on by the two app updates a step plays, as `sim_control`'s
  description says: about 2 / fps (0.033 s at 60)

### 5.3 Gravity Test
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- Aim at the cube's column, which keeps it in view as it falls: `set_camera(position=[5,3,5], target=[0,1.5,0])`
- `capture_viewport()`: the cube's center should be 3 along the up axis
- `sim_control("play")`, wait ~2 s (get_sim_state's `time`), `sim_control("pause")` (a stop puts the cube back)
- `get_prim_bounds("/World/RedCube")`: its center along the up axis should be < 3 (fell due to gravity)
- `capture_viewport()`: verify visually that the cube is lower, on the ground

---

## Phase 6: Recording (Basic)

Needs: 2.1, 4.5

### 6.1 Record a Falling Cube
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `start_recording(fps=5, width=320, height=240)`
- Verify: the answer says `320x240 from /OmniverseKit_Persp` (the viewport's camera), with no `WARNING` line
- `sim_control("play")`
- Wait ~2 seconds
- `sim_control("stop")`
- `stop_recording()`
- Verify: frame_count > 0, output_dir exists

### 6.2 Review Frames
- `get_recording_frame(frame_index=0)` → should return image path
- Read the frame image — verify it is non-empty (file size > 0)
- `get_recording_frame(frame_index=<last>)` → cube lower or on ground
- Verify: images show cube at different positions, each 320x240 whatever the viewport's size

### 6.3 Record from a Camera
- `execute_script` making a camera `/World/RecCam` 8 units along X, looking at the cube's column (focal length 18)
- Aim the viewport away: `set_camera(position=[20,1,0], target=[30,1,0])`
- `start_recording(fps=10, width=160, height=120, camera_path="/World/RecCam")`, wait 1 s, `stop_recording()`
- Verify: every frame is 160x120 and shows the red cube; `capture_viewport()` still shows the view aimed away,
  with no red, and the viewport's camera and size are as before

### 6.4 to 6.9 What a Recording Shows, Refuses, Leaves and Says
- Reset the cube to height 3; `start_recording(fps=10, camera_path="/World/RecCam")`, play ~1.5 s, pause, then
  `stop_recording()`: the cube is lower in the last frame than in the first (pausing, not stopping, keeps it down)
- `camera_path="/World/RedCube"` or a path with no prim, and `width=4097`: each an error, and nothing recording
- While recording, the answer's `render_product` is a prim on the stage; after `stop_recording()` it is gone
- At `fps=30`, `metadata.json` numbers its frames 0, 1, 2, ... with none repeated, each with its file
- Delete the recording's camera mid-recording: `get_sim_state` shows `recording_note`, frames stop, and
  `stop_recording()` ends with a `Note:` saying the camera is gone

---

## Phase 7: Recording with Prim State Tracking

Needs: 2.1, 4.5

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
- Verify header: `# Omniverse MCP Recording State`
- Verify frame markers: `=== FRAME t=X.XXX step=N ===`
- Verify prim blocks: `[/World/RedCube]` with `type = Cube`
- Verify position data: `pos = X.XXXX, Y.XXXX, Z.XXXX`
- Verify the position along the up axis falls from the first frame (gravity)

### 7.3 Record with property_filter
- Reset cube: `set_prim_transform("/World/RedCube", position=[0,3,0])`
- `start_recording(fps=10, track_prims=["/World/RedCube"], property_filter=["xformOp", "physics"])`
- `sim_control("play")`, wait ~1s, `sim_control("stop")`, `stop_recording()`
- Read `state.txt`: should only show properties matching "xformOp" or "physics"

---

## Phase 8: Scene Dump (Prim-Block Format)

Needs: 2.1, 4.5

### 8.1 Full Scene Dump
- `get_scene_tree(root="/World", include_properties=True)`
- Verify: the answer says how many prims it wrote, to depth 15, and where the file is
- Read the file — verify prim-block format:
  - Header: `# Omniverse MCP Scene Dump`
  - Scene marker: `=== SCENE root=/World prims=N ===`
  - Prim blocks with `[/path]`, `type = ...`, `pos = ...`
  - N, and the answer's "Dumped N prims", equal the number of `[/path]` blocks in the file

### 8.2 Filtered by Type
- `get_scene_tree(root="/World", filter_types=["Cube"], include_properties=True)`
- Read: only Cube prims should appear, each with its attributes

### 8.3 Filtered by Property
- `get_scene_tree(root="/World", property_filter=["physics", "collision"])`
- Read: only physics/collision properties in each block

### 8.4 Dump without Attribute Values
- `get_scene_tree(root="/World", filter_types=["Cube"])`
- Read: Cube blocks with type, position, rotation and box, but NO attribute listing

### 8.5 Grep-Friendly Check
- The file from 8.1 should be grep-able:
  - Search for `[/World/RedCube]` → finds prim header
  - Search for `pos =` → finds position lines
  - Search for `type = Cube` → finds cube types

---

## Phase 9: Extension Management

Needs: none

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

Needs: 2.1, 4.5

### 10.1 Spawn G1 Robot
- `create_robot("g1", position=[3, 0.74, 0])`
- Verify: returns prim path and joint list. The G1 stands: `get_prim_bounds("/World/G1")` is tallest, about 1.32,
  along the stage's up axis (`get_sim_state`); on a Y-up stage the answer says it was turned upright, its file
  being Z-up

### 10.2 Inspect Robot
- `inspect_prim("/World/G1", angles=["front", "right", "top_front_right"])`
- Verify: 3 images showing the robot from cube-based angles, auto-fit distance > 0

### 10.3 Record Robot with State Tracking
- `start_recording(fps=10, track_prims=["/World/G1"], property_filter=["joint", "pos"])`
- `sim_control("play")`, wait ~2s, `sim_control("stop")`, `stop_recording()`
- Read `state.txt`: should show G1 hierarchy with joint/position data changing per frame

### 10.4 Invalid Robot
- `create_robot("nonexistent_robot")` → should return error

---

## Phase 11: Error Cases

Needs: none

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
- Start a recording, then try `start_recording()` again → error saying to call `stop_recording` first, not to pass
  `force`

### 11.5 Stop Without Recording
- `stop_recording()` when none active → error

---

## Phase 12: Materials

Needs: 2.1

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
- `set_material("/World/RedCube", color=[1,0,0], opacity=1)`
- Verify: the answer says opacity=1.0, and the cube is opaque again

### 12.5 Set Material - Custom Path
- `set_material("/World/RedCube", color=[0,1,0], material_path="/World/Looks/MyGreenMat")`
- Verify: material_path="/World/Looks/MyGreenMat"

### 12.6 Set Material - Invalid Prim
- `set_material("/World/Nonexistent", color=[1,0,0])` → error

### 12.7 Set Material - Invalid Color
- `set_material("/World/RedCube", color=[1,0])` → error (needs 3 values)

### 12.8 Verify Material Visually
- Apply red material, `set_camera(prim_path=...)` on the cube, capture_viewport
- Verify: cube should appear colored (not default white/gray)

---

## Phase 13: Visibility & Cloning

Needs: 2.1

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
- Verify: 3 clones created (`/World/CloneBatch_001`, `_002`, `_003`): `_001` on the cube itself, `_002` [2,0,0] from
  it and `_003` [4,0,0], each with the cube's own xform ops

### 13.6 Clone - Verify Offset Positions
- Get bounds of each clone from 13.5
- Verify: each clone is offset by [2,0,0] from the previous one

### 13.7 Clone Invalid Source
- `clone_prim("/World/Nonexistent", "/World/Clone")` → error

---

## Phase 14: Robot Control

Needs: 2.1, 4.5, 10.1

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
- Play sim briefly, then pause: the play answers (#5)
- `get_robot_info("/World/G1")`
- Verify: the structure as in 14.1, its Joints list inline or in a file the answer names, and a `Joint states` block
  with a position and a velocity for each of its DOF
- Stop, then `get_robot_info("/World/G1")` again
- Verify: the structure again, no error, and `Joint states: not read:` saying to play or step the simulation first

---

## Phase 15: Physics Properties & Forces

Needs: 2.1, 4.5, 10.1

### 15.1 Set Mass
- `set_physics_properties("/World/RedCube", mass=5.0)`
- Verify: the answer says `mass=5.0` and `applied MassAPI`

### 15.2 Set Friction and Restitution
- `set_physics_properties("/World/RedCube", friction=0.8, restitution=0.3)`
- Verify: the answer says `friction=0.8 (static and dynamic)`, `restitution=0.3` and `PhysicsMaterial` among the
  APIs applied

### 15.3 Set Density
- `set_physics_properties("/World/RedCube", density=1000.0)`
- Verify: the answer says `density=1000.0` and `applied MassAPI`
- Note: the mass 15.1 set still wins over the density, under USD's rules; nothing to check

### 15.4 Physics on Invalid Prim
- `set_physics_properties("/World/Nonexistent", mass=1.0)` → error

### 15.5 Apply Force (Basic)
- Play sim, apply force to RedCube: `apply_force("/World/RedCube", force=[100,0,0])`
- Verify: the answer ends `(centre of mass, method: physx)`: PhysX's own push, at the centre of mass. With
  `/physics/suppressReadback` on, as under the Direct GPU API, it says `method: tensor`

### 15.6 Impulse and Force by Mass
- A 5 kg cube of its own, gravity off, away from the scene; play
- `apply_force(cube, force=[10,0,0], impulse=True)`: its speed along X becomes about 2 (10 N s / 5 kg)
- Stop, play, `apply_force(cube, force=[10,0,0])`: about `10 * dt / 5`, a force lasting one physics step
  (`dt` 1/60 s by default)

### 15.7 Apply Force at Offset Position
- The same kind of cube; play
- An impulse without `position` moves it without turning it
- Stop, play; one at a point 0.2 above its centre along the up axis turns it

### 15.8 Centre of Mass Off the Origin
- A cube whose `physics:centerOfMass` is off its origin, sideways
- An impulse without `position` lands on the centre of mass and doesn't turn it; one at its origin does

### 15.9 Apply Force While Stopped
- `sim_control("stop")`, then `apply_force` on a rigid body → error: PhysX holds no bodies

### 15.10 Apply Force to a Kinematic Body
- A cube with `physics:kinematicEnabled` true; play; `apply_force` → error

### 15.11 Apply Force to a Robot Link
- Stopped, lift `/World/G1` 20 units, so it falls with nothing to touch; play, then pause
- Its speed along X over 12 steps, from PhysX's poses and masses; `apply_force(pelvis, force=[100,0,0],
  impulse=True)`; its speed over 12 more steps
- Verify: the speed changed by 100 / the robot's mass (about 2.92) within 2%, before it landed; put it back after

### 15.12 Apply Force to a Disabled Body
- A cube with `physics:rigidBodyEnabled` false; play; `apply_force` → error: PhysX holds it as a static body

### 15.13 Apply Force to Invalid Prim
- `apply_force("/World/Nonexistent", force=[1,0,0])` → error

### 15.14 Apply Force to a Link of a Free Articulation
- Two 5 kg cubes of their own on a hinge, an articulation rooted on their Xform, gravity off; play, then pause
- `apply_force(second cube, force=[10,0,0], impulse=True)` between two measures of their speed along X
- Verify: the speed changed by 1.0 (10 N s / 10 kg) within 2%

### 15.15 Apply Force to a Body Fixed to the World
- The same pair with a fixed joint from the world to the first cube, and a cube bolted to the world
- `apply_force` on the bolted cube, then on the first cube → error each time: a fixed joint holds it to the world,
  naming the articulation for the cube in one
- A sideways impulse on the second cube: success; over 30 steps it moves, the first doesn't

### 15.16 Apply Force to Isaac Sim's Franka
- `create_robot("franka", ...)` away from the scene; play, then pause
- `apply_force` on `panda_link0` → error: held to the world by a fixed joint, as the base of the articulation
- `apply_force` on `panda_hand` → success

---

## Phase 16: Raycasting & Debug Draw

Needs: 2.1, 4.5

### 16.1 Raycast Hit
- `sim_control("play")` (PhysX needs running sim)
- Cast ray downward from [0,10,0] direction [0,-1,0]: `raycast(origin=[0,10,0], direction=[0,-1,0])`
- Verify: hit=true with prim_path and distance

### 16.2 Raycast Miss
- Cast ray into empty space: `raycast(origin=[100,100,100], direction=[0,1,0], max_distance=1.0)`
- Verify: hit=false
- `sim_control("stop")`

The line count below is `isaacsim.util.debug_draw`'s, read with Kit's clock in one short `execute_script`:
`from isaacsim.util.debug_draw import _debug_draw; import time; result = [_debug_draw.acquire_debug_draw_interface().get_num_lines(), round(time.monotonic(), 2)]`.
A drawing lasts its `duration` in seconds of that clock, 5 by default. Read the count before 16.3; each step from 16.6
on starts once it is back there. To see a drawing go, read again and again, a call at a time: nothing waits inside a
script.

### 16.3 Draw Debug Line
- `draw_debug("line", start=[0,0,0], end=[5,5,0], color=[1,0,0])`
- Verify: success, drawn with `isaacsim.util.debug_draw` on Isaac Sim

### 16.4 Draw Debug Sphere
- `draw_debug("sphere", center=[0,2,0], radius=0.5, color=[0,1,0])`
- Verify: success

### 16.5 Draw Debug Points
- `draw_debug("points", points=[[0,0,0],[1,1,0],[2,0,0]], color=[0,0,1])`
- Verify: success

### 16.6 A Drawing Expires
- Read the count, then `draw_debug("line", start=[0,0,0], end=[0,1,0], duration=10)`, then read it again until it
  falls
- Verify: up by 1 until the line's 10 s are up, then back where it was: every read less than 10 s after the read
  before the drawing shows it, and every read more than 10 s after the first read after it doesn't

### 16.7 Two Drawings
- Read the count; a 30 s line, then a 10 s sphere; then read it again until it is back where it was
- Verify: up by 4 at the first read after the sphere; up by 1 once the sphere's 10 s are up (the line, drawn again
  after the clear); back where it was once the line's 30 s are up, each judged by Kit's clock as in 16.6

### 16.8 Debug Draw Visual Check
- Aim the camera away from the red cube, at empty space, and read the render products under
  `/Render/OmniverseKit/HydraTextures` with a short `execute_script`; `capture_viewport()` holds no red
- `draw_debug("lines", ..., duration=10)` a red zigzag across the view, then `capture_viewport()`
- Verify: the zigzag shows in the capture, and the render products, read again, are the ones read before the
  captures: each capture's own render went with it (#51)
- Not judged here, so it leaves this row's status alone: a drawing captured at once, 5 times over, through
  `draw_debug`'s handler and `mcp.capture_viewport()` in one script. That needs an `ovmcp.*` import and five awaited
  captures, which the tester's rules forbid; pytest's `test_16_08` checks it, live

### 16.9 The omni.debugdraw Backend
- pytest's, not this suite's: `test_16_09` switches the bridge's drawing to `omni.debugdraw` with the bridge's own
  `choose_backend`, an `ovmcp.*` import, and no tool switches it: Isaac Sim draws with `isaacsim.util.debug_draw`
  whenever it has it
- SKIP it, naming `test_16_09`, and call nothing

---

## Phase 17: Scene Lifecycle

Needs: none

### 17.1 Save Scene to File
- `save_scene(file_path="<run>/kit/mcp_test_scene.usd")`
- Verify: file_path and action in response

### 17.2 Create New Scene
- `new_scene()`
- Verify: `get_scene_tree` shows minimal default prims (just /World or similar)
- Note: this wipes all prims from Phases 2-16. Phases 18+ create their own.

### 17.3 A New Stage Forgets the Old One's Drawings
- The line count and Kit's clock, from one short `execute_script`:
  `from isaacsim.util.debug_draw import _debug_draw; import time; result = [_debug_draw.acquire_debug_draw_interface().get_num_lines(), round(time.monotonic(), 2)]`
- Read it; `draw_debug("line", ..., duration=30)`, then `new_scene()`, then `draw_debug("sphere", ..., duration=10)`;
  then read it again, a call at a time, until the sphere's 10 s are up, and once more after that
- Verify: the first read after the sphere is the sphere's 3 alone, and once the sphere's 10 s are up the count is
  back where it started, at that read and the next: the old stage's line never comes back

### 17.4 Segmentation on the New Stage
- `execute_script` with `result = int(omni.syntheticdata.sensors.get_instance_segmentation(get_active_viewport()).size)`
  (import `omni.syntheticdata` and `get_active_viewport` from `omni.kit.viewport.utility`)
- Verify: 0. `omni.syntheticdata` drops its sensors on every stage open, so the new stage has no segmentation yet
- `create_prim("/World/SegmentationCube", "Cube", position=[0, 0.5, 0], scale=0.25)`, a cube 0.5 across
- `inspect_prim("/World/SegmentationCube", angles=["front"], include_segmentation=True)`
- Verify: the angle has a segmentation file with the cube in its legend, and no `seg: ERROR`: the bridge turned the
  sensor on for the capture's own render and waited for its first data
- Clean up: `delete_prim("/World/SegmentationCube")`

### 17.5 A New Stage Stops a Recording
- `start_recording(fps=10, width=320, height=240)`, then `new_scene()`, then `stop_recording()`
- Verify: no frames after the new stage, a `Note:` naming the stage, and the answer's `render_product` not on the
  new stage

### 17.6 Segmentation After Captures and a New Stage
- `create_prim("/World/SegmentedCaptureCube", "Cube", ...)`, `set_camera(prim_path=...)` on it, and two
  `capture_viewport(320, 240)`
- `new_scene()`, the cube again, and a third capture
- Verify: each capture's segmentation has the cube in its legend, and `get_logs(search="Py_Graph")` finds nothing
  since the first: each capture freed its segmentation graphs, so `omni.syntheticdata` tripped on none at the new
  stage (#51)

### 17.7 An Opened File Stops a Recording and Drops the Drawings
- `save_scene(file_path="<run>/kit/opened_scene.usda")`, then `start_recording(fps=10, width=320, height=240)` and
  `draw_debug("line", start=[0, 0, 0], end=[1, 0, 0], duration=30)`, then `open_scene("<run>/kit/opened_scene.usda")`, then
  `stop_recording()`
- Verify: no frames after the open, a `Note:` naming the stage, the answer's `render_product` not on the opened
  stage, the line gone within 5 s, and a capture of a cube with its segmentation on the opened stage

---

## Phase 18: Geometry & Mesh Analysis

Needs: none

> **Setup:** the half starts on a new stage, with no prims and no light. This phase makes its own prims, and 18.2 the
> dome that lights every capture of Phases 19 to 22.
>
> **Note:** Procedural prims (`UsdGeom.Cube`, `Sphere`, etc.) are implicit surfaces, not `UsdGeom.Mesh`, and return 0 faces/vertices. Only actual `UsdGeom.Mesh` prims (robots, imported models) have countable geometry.

### 18.1 Mesh Stats on Robot (Mesh Geometry)
- Spawn a robot: `create_robot("franka", position=[0, 0, 0])`
- `get_mesh_stats("/World/Franka")`
- Verify: the totals, mesh_count > 0, total_faces > 0 and total_vertices > 0, then the tree under `/World/Franka`
  with `subtree_faces` > 0 on the prims above its meshes; a `max_depth` large enough to reach the meshes lists each
  one with its faces, vertices and triangles

### 18.2 Mesh Stats on Procedural Prim (Expected Zero)
- Light the stage: `create_prim("/World/DomeLight", "DomeLight")`, then
  `execute_script("UsdLux.DomeLight(omni.usd.get_context().get_stage().GetPrimAtPath('/World/DomeLight')).CreateIntensityAttr(1000.0)")`.
  A dome lights a prim from every side Phase 22 views it from, and its default intensity, 1, is too dim to see by
- Create a cube: `create_prim("/World/TestCube", "Cube", position=[3,0.5,0])`
- `get_mesh_stats("/World/TestCube")`
- Verify: total_faces=0, mesh_count=0 (procedural prims are not UsdGeom.Mesh — this is expected)

### 18.3 Mesh Stats on Invalid Prim
- `get_mesh_stats("/World/Nonexistent")` → error

### 18.4 Face Count Tree
- `get_mesh_stats("/World", max_depth=10)`
- Verify: the totals, then a hierarchical tree showing Franka with subtree_faces > 0, TestCube with 0, and no
  `# total:` line

### 18.5 Face Count Tree with Depth Limit
- `get_mesh_stats("/World", max_depth=1)`
- Verify: the same totals as 18.4, and only top-level children shown, no deeper nesting

---

## Phase 19: USD Operations

Needs: 18.2

### 19.1 Flatten USD (Current Stage)
- Save scene first: `save_scene(file_path="<run>/kit/test_flatten_source.usda")`
- `flatten_usd("<run>/kit/test_flatten_output.usdc")`
- Verify: success, output file path returned

### 19.2 Flatten USD (External File)
- `flatten_usd("<run>/kit/test_flatten_output2.usdc", "<run>/kit/test_flatten_source.usda")`
- Verify: success, flattened from the external file

### 19.3 Export Prim as File
- `export_prim_as_file("/World/TestCube", "<run>/kit/exported_cube.usdc")`
- Verify: success, returns prim_path, output_path, target_root, materials_included, up_axis

### 19.4 Export Prim with Materials
- First apply a material: `set_material("/World/TestCube", color=[1,0,0])`
- `export_prim_as_file("/World/TestCube", "<run>/kit/exported_cube_mats.usdc")`
- Verify: success, materials_included > 0 (materials are always included automatically)

### 19.5 Export Invalid Prim
- `export_prim_as_file("/World/Nonexistent", "<run>/kit/fail.usdc")` → error

---

## Phase 20: Variant Tools

Needs: 18.1, 18.2

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
- Verify: returns a/b stats (faces, vertices, triangles, mesh_count, bounds, materials) and the deltas. TestCube is
  a Cube, not a mesh, so A has 0 faces: the faces delta has no percentage, and each delta has its own sign

### 20.7 Compare Prims (Variant)
- `compare_prims(prim_path="/World/TestCube", variant_set="detail", variant_a="high", variant_b="low")`
- Verify: returns a/b stats for each variant and delta

### 20.8 Compare Prims - Invalid
- `compare_prims()` (no args) → error about missing arguments

---

## Phase 21: Material Path Updates

Needs: 18.2

### 21.1 Update Material Paths
- Bind a material at a path of its own: `set_material("/World/TestCube", color=[1,0,0], material_path="/World/Looks/TestMat")`
- `update_material_paths("/World/Looks", "/World/NewLooks", "/World")`
- Verify: the answer gives one count of the paths it changed, bindings and asset paths together, at least 1 (the
  cube's binding), and names `/World/TestCube` among its prims

### 21.2 Update Material Paths - No Matches
- `update_material_paths("/Nonexistent/Looks", "/Other/Looks", "/World")`
- Verify: success with 0 updates (no error, just nothing to do)

---

## Phase 22: Enhanced Inspect Prim

Needs: 18.1, 18.2

> **Auto-fit:** `inspect_prim` computes camera distance from the prim's bounding sphere and camera FOV,
> so the prim fills the viewport with ~10px margin. The `zoom_offset` parameter adjusts this:
> negative = closer, positive = further, 0 = auto-fit default.
>
> **Isolate:** `isolate=True` hides everything but the target during capture, in the session layer: the target's
> siblings at every level from the root down, never a light (a prim that holds a light keeps it on and only its
> other children are hidden). Afterwards each prim's visibility is put back exactly as it was. Instances it would
> have to look inside, and prims with time-sampled session visibility, are left as they are and named in
> `isolate_warnings`.

### 22.1 Inspect with Segmentation
- `inspect_prim("/World/TestCube", angles=["front", "right"], include_segmentation=True)`
- Verify: each capture has segmentation image + legend in addition to the viewport image

### 22.2 Inspect with Cube Corner Angles
- `inspect_prim("/World/Franka", angles=["top_front_right", "top_back_left", "bottom_front_right", "bottom"])`
- Verify: 4 images from the cube-based angle presets, robot visible in each

### 22.3 Inspect Non-Existent Prim
- `inspect_prim("/World/Nonexistent")` → error

### 22.4 Inspect with Zoom Offset
- `inspect_prim("/World/Franka", angles=["front"], zoom_offset=-0.3)` → closer (30% shorter distance)
- `inspect_prim("/World/Franka", angles=["front"])` → default auto-fit
- Verify: zoom_offset=-0.3 produces a smaller distance than the default
- The zoomed-in capture should show the prim larger in the frame

### 22.5 Inspect with Isolate
- `inspect_prim("/World/Franka", angles=["left"])`, then the same with `isolate=True`
- Verify: the first image shows `/World/TestCube` behind the robot; the second's answer says `isolated` on its first
  line, and its image shows the robot alone, still lit by 18.2's dome: isolate hides every other prim, never a light
- After capture, other prims should be restored (check with `capture_viewport`)

---

## Phase 23: Viewport Lighting

Needs: 18.2

> **Lighting modes:** The MCP exposes all Omniverse viewport lighting options:
> `"off"`, `"camera"`, `"stage"`, and light rig presets (`"Default"`, `"Colored Lights"`, `"Grey Studio"`).
>
> **No auto-fix:** The MCP never auto-switches lighting. It warns about black images, and about lighting that
> lights nothing (mode `off`, or `stage` with no scene lights) though Kit's grid shows, but the user/AI must
> explicitly set the desired mode.

### 23.1 Get Lighting State
- `viewport_light("get")`
- Verify: returns `lighting_mode` (string), `available_modes` (list), `has_scene_lights` (bool), `scene_lights` (list)
- `available_modes` should include at least `"off"`, `"camera"`, `"stage"`; the scene has lights, and the list names
  18.2's `/World/DomeLight` with its intensity, 1000, and no path under `/OmniKit_Viewport_LightRig`, the viewport's
  light rig, whatever the mode

### 23.2 Set Lighting Mode — Default Rig
- `viewport_light("set", mode="Default")`
- Verify: `lighting_mode="Default"` in response
- `viewport_light("get")`: a line names the light rig 'Default', which lights the viewport in place of the stage's
  lights; the scene still has lights, and the list still names 18.2's `/World/DomeLight` and no path under
  `/OmniKit_Viewport_LightRig`
- `capture_viewport()` → scene should be lit with the Default light rig

### 23.3 Set Lighting Mode — Camera Light
- `viewport_light("set", mode="camera")`
- Verify: `lighting_mode="camera"` in response

### 23.4 Set Lighting Mode — Stage
- `viewport_light("set", mode="stage")`
- Verify: `lighting_mode="stage"` in response
- `capture_viewport()`: lit by the stage's own light alone, 18.2's dome, which the rig and the camera light hid

### 23.5 Legacy set_camera_light Action
- `viewport_light("set_camera_light", enabled=True)`
- Verify: success (backward compatibility)
- `viewport_light("set_camera_light", enabled=False)`
- Verify: success

### 23.6 Black Image Detection (No Auto-Fix)
- Set lighting to off: `viewport_light("set", mode="off")`
- `capture_viewport()` → a WARNING naming lighting mode `off` and `viewport_light`: Kit's grid keeps the image from
  being all black, so the warning is the lighting's; where a Kit renders it all black, the black image's names it
- The MCP should NOT auto-enable camera light or change the mode
- Response should include `lighting_mode` field showing current mode
- Fix it manually: `viewport_light("set", mode="Default")`
- `capture_viewport()` → image should now be lit, no WARNING

---

## Phase 24: Logging

Needs: none

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

### 24.5 Get Logs by Count
- `execute_script("carb.log_warn('log_count_marker')")`, then `get_logs(count=5)`, then `get_logs(count=1)`
- Verify: 5 entries, then 1, each count the first number of its answer's header; the entries come oldest first, so
  the marker's line is the last of the 5, or near the end when Kit logged after it

### 24.6 Get Logs After Error
- A script that writes an error to Kit's log, then raises another:
  ```python
  execute_script("""
  carb.log_error('log_test_error')
  raise RuntimeError('log_test_raise')
  """)
  ```
- `get_logs(count=10, search="log_test_error")`, then `get_logs(count=10, search="log_test_raise")`
- Verify: the script's answer carries the `RuntimeError` with its traceback; the first search finds the logged line,
  at level error; the second finds nothing, since the bridge answers a script's exception rather than logging it

---

## Phase 25: Async Script Execution (MCP Bridge)

Needs: none

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

Needs: 23.2

> **Note:** These tests verify that camera moves properly settle before capture.
> The camera handlers now use `_settle_viewport()` (20 frames) instead of 1-2 `_next_update()` calls.

### 26.1 Camera Set + Immediate Capture
- `set_camera(position=[5, 3, 5], target=[0, 0, 0])`
- Immediately: `capture_viewport(640, 480)` — do NOT add any delay
- Verify: captured image is not black and shows the scene from the expected angle
- Repeat 3 times with different camera positions to test consistency

### 26.2 Look At + Immediate Capture
- Create a test prim: `create_prim("/World/SettleTest", "Cube", position=[0, 1, 0], scale=0.5)`
- `set_camera(prim_path="/World/SettleTest", azimuth=45, elevation=30)`
- Immediately: `capture_viewport(640, 480)`
- Verify: the cube is visible in the capture, and `/World/TestCube`, beside this view, has no box in the boxes
  file
- Clean up: `delete_prim("/World/SettleTest")`

---

## Phase 27: Cleanup

Needs: none

### 27.1 Clean Up Scene
- `sim_control("stop")`, and `stop_recording()` if `get_sim_state` says one runs
- `new_scene()`, which drops every prim the run made, whichever phases ran
- Verify: `get_scene_tree` shows only a new stage's own prims
