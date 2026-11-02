# Omniverse MCP Outcome Scenarios

The AI scenario suite's outcomes (#146, `docs/plans/2026-11-02-outcome-scenarios.md`). Each is a request in a user's
words: an agent gets the **Ask** alone, with the plugin's skills and the brief in `assistant.md`, and chooses its own
tools. A judge then checks the **Verify** lines, which the agent never sees, with the read-only tools alone.
`uv run tools/scenarios.py run` runs them after the scripted phases; `--outcomes O1,O3` picks some.

Each outcome's fields, in this order:

- **Given:** `none`, or a fenced python block the runner sends through `/execute` after `new_scene()` and before the
  agent starts. The runner also sets the viewport's lighting to `stage` first, so a stage without lights renders black.
- **Ask:** the request, all the agent gets.
- **Verify:** what the judge checks, each a fact about the stage, a capture or the answer.
- **Calls:** `any`, or `no execute_script`: an agent that calls `execute_script` anyway gets WARN at best. The tool
  path each such line expects, for reading a standing WARN as the agent's choice or a missing tool: O1, `create_prim`,
  `set_material`, and `viewport_light` (a light rig or the camera light) or a light whose intensity
  `set_prim_attribute` sets; O3, `get_mesh_stats`; O4, `get_prim_properties`, then `set_physics_properties` with
  `collision=True` (or a friction or restitution, which adds the collider too); O5, `inspect_prim` or `set_camera`
  with `capture_viewport`; O6, `get_logs`; O7, `run_script_job` with a script that awaits each update, then `get_job`
  until it ends, work that outlasts the 120 s an `execute_script` call gets (#158).
- **Play:** `none`, or seconds: after the agent, the runner plays the simulation that long and pauses it, so the
  judge reads where physics put things.

`new_scene()` makes a Z-up stage in metres with `/World`, the frame a user's agent gets. Heights below are along Z.

---

## O1: A Red Cube on the Ground, Shown

Given: none

Ask: Put a red cube, 50 cm on a side, sitting on a ground plane, and show me a picture of it.

Verify:
- A cube whose box (`get_prim_bounds`) is 0.5 m on each side, within 1 cm, in the stage's units
  (`get_sim_state`'s `meters_per_unit`)
- The cube reads red: its bound material's diffuse colour, or with no material its display colour, has red at least
  0.5 and green and blue at most 0.3
- A ground under the cube, a plane or a flat box at least 1 m across, the cube's bottom within 1 cm of its top
- A capture the assistant gave shows the red cube on the ground, lit: the cube is red, not black. The stage started
  with no light and the viewport lit by the stage's lights alone

Calls: no execute_script

Play: none

## O2: How Long the Ball Takes to Land

Given:

```python
import omni.usd
from pxr import Gf, UsdGeom, UsdPhysics

stage = omni.usd.get_context().get_stage()
UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
ground = UsdGeom.Cube.Define(stage, "/World/Ground")
ground.CreateSizeAttr(1.0)
UsdGeom.XformCommonAPI(ground).SetTranslate(Gf.Vec3d(0.0, 0.0, -0.05))
UsdGeom.XformCommonAPI(ground).SetScale(Gf.Vec3f(10.0, 10.0, 0.1))
ball = UsdGeom.Sphere.Define(stage, "/World/Ball")
ball.CreateRadiusAttr(0.1)
UsdGeom.XformCommonAPI(ball).SetTranslate(Gf.Vec3d(0.0, 0.0, 2.0))
```

Ask: There's a ball hanging above the ground in my scene. Make it fall onto the ground when the simulation plays,
and tell me how long it takes to land.

Verify:
- `/World/Ball` has a rigid body and a collider; `/World/Ground` has a collider and no rigid body
- After the runner's play, the ball's bottom (`get_prim_bounds`) is within 1 cm of the ground's top, at 0
- The answer says how long the fall takes: 0.62 s, within 0.1 s (the ball's bottom falls 1.9 m)

Calls: any

Play: 2 s

## O3: Which Part Has the Most Triangles

Given:

```python
import omni.usd
from pxr import Gf, UsdGeom

stage = omni.usd.get_context().get_stage()


def mesh(path, sides, faces):
    # A strip of separate faces: what get_mesh_stats counts is the faces and their sides, not their shape.
    made = UsdGeom.Mesh.Define(stage, path)
    made.CreatePointsAttr([Gf.Vec3f(i * 0.01, k * 0.01, 0.0) for i in range(faces) for k in range(sides)])
    made.CreateFaceVertexCountsAttr([sides] * faces)
    made.CreateFaceVertexIndicesAttr(list(range(sides * faces)))


UsdGeom.Xform.Define(stage, "/World/Machine")
UsdGeom.Xform.Define(stage, "/World/Machine/Base")
mesh("/World/Machine/Base/Body", 4, 60)
UsdGeom.Xform.Define(stage, "/World/Machine/Arm")
mesh("/World/Machine/Arm/Upper", 3, 55)
mesh("/World/Machine/Arm/Lower", 3, 55)
UsdGeom.Xform.Define(stage, "/World/Machine/Head")
mesh("/World/Machine/Head/Shell", 3, 100)
```

Ask: My machine at /World/Machine is made of a few parts. Which part has the most triangles, and how many triangles
does the whole machine have?

Verify:
- The answer names Base as the part with the most triangles: 120, from 60 quads. By faces Arm leads, 110 to Base's
  60, so an answer that ranks by faces names Arm, wrongly
- The answer gives the machine's total as 330 triangles (Base 120, Arm 110, Head 100)

Calls: no execute_script

Play: none

## O4: The Box Falls Through the Floor

Given:

```python
import omni.usd
from pxr import Gf, UsdGeom, UsdPhysics

stage = omni.usd.get_context().get_stage()
UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
floor = UsdGeom.Cube.Define(stage, "/World/Floor")
floor.CreateSizeAttr(1.0)
UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0.0, 0.0, -0.05))
UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(6.0, 6.0, 0.1))
box = UsdGeom.Cube.Define(stage, "/World/Box")
box.CreateSizeAttr(0.5)
UsdGeom.XformCommonAPI(box).SetTranslate(Gf.Vec3d(0.0, 0.0, 1.0))
UsdPhysics.RigidBodyAPI.Apply(box.GetPrim())
UsdPhysics.CollisionAPI.Apply(box.GetPrim())
```

Ask: When I press play, the box in my scene falls straight through the floor. Find out why and fix it.

Verify:
- `/World/Floor` has a collider with collision on, and no rigid body; `/World/Box` keeps its rigid body and collider
- After the runner's play, the box's bottom (`get_prim_bounds`) is within 1 cm of the floor's top, at 0
- The answer says the floor had no collider

Calls: no execute_script

Play: 2 s

## O5: The Table From Above and From the Side

Given:

```python
import omni.usd
from pxr import Gf, UsdGeom, UsdLux

stage = omni.usd.get_context().get_stage()


def box(path, size, at, colour):
    # Colours of their own, so a view from above tells the top from the floor and the book from the top.
    made = UsdGeom.Cube.Define(stage, path)
    made.CreateSizeAttr(1.0)
    made.CreateDisplayColorAttr([Gf.Vec3f(*colour)])
    UsdGeom.XformCommonAPI(made).SetTranslate(Gf.Vec3d(*at))
    UsdGeom.XformCommonAPI(made).SetScale(Gf.Vec3f(*size))


box("/World/Floor", (6.0, 6.0, 0.02), (0.0, 0.0, -0.01), (0.25, 0.25, 0.25))
UsdGeom.Xform.Define(stage, "/World/Table")
wood = (0.55, 0.35, 0.18)
box("/World/Table/Top", (1.2, 0.8, 0.05), (0.0, 0.0, 0.75), wood)
for i, (x, y) in enumerate([(-0.55, -0.35), (0.55, -0.35), (-0.55, 0.35), (0.55, 0.35)]):
    box(f"/World/Table/Leg{i}", (0.05, 0.05, 0.725), (x, y, 0.3625), wood)
box("/World/Table/Book", (0.2, 0.3, 0.04), (0.35, 0.15, 0.795), (0.1, 0.25, 0.75))
UsdLux.DomeLight.Define(stage, "/World/Sky").CreateIntensityAttr(1000.0)
sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
sun.CreateIntensityAttr(3000.0)
# A light shines along its own -Z, straight down on a Z-up stage: this tilts it to 50 degrees above the horizon, so
# it lights the table's top and its sides.
UsdGeom.XformCommonAPI(sun).SetRotate(Gf.Vec3f(-40.0, 0.0, -30.0))
```

Ask: Show me the table at /World/Table from above and from the side.

Verify:
- The answer gives at least two captures of the table, lit
- One looks down on it: the top's wood-coloured rectangle, with the blue book near one corner, and the legs hidden
  under it or only at its corners
- One looks at it from the side, from about the top's height or below: the legs stand on the floor under the top
- The table is whole and near the middle of each

Calls: no execute_script

Play: none

## O6: What Errors Kit Logged

Given:

```python
import carb

carb.log_warn("ovmcp-outcome-O6: the conveyor's belt speed is close to its limit")
carb.log_error("ovmcp-outcome-O6: the conveyor's belt speed is NaN, so the conveyor stopped")
```

Ask: Has Kit logged any errors recently? Tell me what the latest ones say.

Verify:
- The answer quotes or closely paraphrases the error "the conveyor's belt speed is NaN, so the conveyor stopped", as
  an error
- It doesn't call the warning ("the conveyor's belt speed is close to its limit") an error; naming it as a warning
  is fine
- Naming older errors as well, such as one an earlier phase logged, is no fault: `get_logs` gives no times

Calls: no execute_script

Play: none

## O7: Release the Crates One at a Time

Given:

```python
import omni.usd
from pxr import Gf, UsdGeom, UsdPhysics

stage = omni.usd.get_context().get_stage()
UsdGeom.SetStageMetersPerUnit(stage, 1.0)
UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
floor = UsdGeom.Cube.Define(stage, "/World/Floor")
floor.CreateSizeAttr(1.0)
UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0.0, -0.05, 0.0))
UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(12.0, 0.1, 10.0))
UsdPhysics.CollisionAPI.Apply(floor.GetPrim())
UsdGeom.Xform.Define(stage, "/World/Crates")
for i in range(150):
    # 15 rows of 10, 0.6 m apart, each held 1 m up by a crane: a kinematic body stays where it is put.
    crate = UsdGeom.Cube.Define(stage, f"/World/Crates/Crate_{i:03d}")
    crate.CreateSizeAttr(0.3)
    UsdGeom.XformCommonAPI(crate).SetTranslate(Gf.Vec3d(-2.7 + 0.6 * (i % 10), 1.0, -4.2 + 0.6 * (i // 10)))
    UsdPhysics.CollisionAPI.Apply(crate.GetPrim())
    UsdPhysics.RigidBodyAPI.Apply(crate.GetPrim()).CreateKinematicEnabledAttr(True)
```

Ask: The 150 crates under /World/Crates hang 1 m above the floor, held by a crane. Release them one at a time,
Crate_000 first, letting each fall and settle for 3 seconds of simulation before you release the next, and tell me
where they came to rest. Leave the simulation paused when you're done, so they stay where they landed.

Verify:
- No crate under `/World/Crates` is held any more: none has `physics:kinematicEnabled` true
  (`get_scene_tree` of `/World/Crates` with `include_properties` writes every crate's values to one file)
- Each crate rests on the floor: its bottom (`get_prim_bounds`) within 1 cm of the floor's top, at 0, and its centre
  within 5 cm in X and Z of where it hung, Crate_i at x = -2.7 + 0.6 (i mod 10), z = -4.2 + 0.6 (i div 10); check at
  least Crate_000, Crate_074 and Crate_149
- The crates were released one at a time, in order, each after the one before had 3 s of simulation: the
  assistant's calls show it, a job's script or the calls themselves. Some 450 s of simulation in all, minutes at
  any speed Kit runs, more than one `execute_script` call's 120 s
- The timeline is paused (`get_sim_state`), not stopped: a stop puts every crate back where it hung
- The answer says where they came to rest: on the floor under where each hung, as a list, a range or a summary

Calls: no execute_script

Play: none
