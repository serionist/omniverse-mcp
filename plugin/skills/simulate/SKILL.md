---
name: simulate
description: >-
  Use when running physics in Omniverse or Isaac Sim: playing, pausing, stepping or stopping the simulation, mass,
  friction and forces, raycasts, spawning and driving robots (Franka, UR10, G1, Spot and the rest), or recording a run
  to review frame by frame afterwards.
allowed-tools: >-
  mcp__plugin_omniverse-mcp_omniverse__get_sim_state mcp__plugin_omniverse-mcp_omniverse__get_robot_info
  mcp__plugin_omniverse-mcp_omniverse__get_joint_states mcp__plugin_omniverse-mcp_omniverse__raycast
  mcp__plugin_omniverse-mcp_omniverse__get_recording_frame mcp__plugin_omniverse-mcp_omniverse__get_prim_bounds
  mcp__plugin_omniverse-mcp_omniverse__capture_viewport mcp__plugin_omniverse-mcp_omniverse__get_logs
---

# Simulate, drive robots, record

Edits to the stage are instant; motion happens only while the timeline plays. `stop` resets the stage to how it was
before play, so pause to look at a moment in the middle.

## Steps

1. **Orient.** `get_sim_state`: the up axis decides which way gravity pulls, and whether the timeline plays.
2. **Physics on what moves.** `create_prim(..., enable_physics=True)` gives a prim a rigid body and collision;
   `set_physics_properties` sets mass, density, friction and restitution. Without a collider an object falls through
   the ground.
3. **Robots.** `create_robot` spawns one of franka, ur10, carter, jetbot, g1, go1, go2, h1, spot or anymal from
   Isaac Sim's asset library (Isaac Sim only), or a robot's own USD file, a path or a URL, in any Kit app.
   `get_robot_info` lists its joints; `get_joint_states` reads them while the simulation plays or is paused, and
   `set_joint_targets` drives them.
4. **Run.** `sim_control("play")`, `"pause"`, `"step"` or `"stop"`. `apply_force` pushes a rigid body through
   PhysX while the simulation plays or is paused, at its centre of mass unless a `position` is given: an impulse
   acts at once, a force for one physics step, so a sustained push is an impulse of force times seconds. It can't
   push an articulation's links, a robot's among them, yet
   ([#58](https://github.com/serionist/omniverse-mcp/issues/58)). `raycast` needs the
   simulation to have played.
5. **Record what happens.** `start_recording` with `track_prims`, play, then `stop_recording`: each frame's image and
   the tracked prims' state land in `mcp_output/recordings/<session>/`. `get_recording_frame` reads one frame back.
   Frames come from `camera_path` (the viewport's camera when empty) at `width` x `height`, 640x480 unless given,
   without moving the viewport; they stop, with a note, if the stage changes or the camera is deleted.
6. **Check** with `get_prim_bounds`, `get_joint_states` or a capture, rather than assuming the run did what was
   asked. A tool that fails: `get_logs(min_level="warn")`.

## Traps

| Trap | What to do |
|---|---|
| `get_joint_states` errors | play or pause, not stop: it reads physics, which a stop drops |
| `raycast` finds nothing | play first: it uses PhysX |
| A stopped run loses the state you wanted | `pause`, not `stop`, to look at it |
| Gravity along the wrong axis | the up axis from `get_sim_state`: a Y-up stage falls along -Y |
