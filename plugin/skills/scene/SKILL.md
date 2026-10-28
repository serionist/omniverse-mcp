---
name: scene
description: >-
  Use when working on what is in an Omniverse or Isaac Sim stage: finding out what a scene holds, looking at it,
  placing, moving, creating or hiding prims, lighting and cameras, or checking that a change worked. Covers looking
  before acting, reading the captures, spatial reasoning with bounds, and the verification loop.
allowed-tools: >-
  mcp__plugin_omniverse-mcp_omniverse__get_sim_state mcp__plugin_omniverse-mcp_omniverse__get_scene_tree
  mcp__plugin_omniverse-mcp_omniverse__dump_scene mcp__plugin_omniverse-mcp_omniverse__get_prim_properties
  mcp__plugin_omniverse-mcp_omniverse__get_prim_bounds mcp__plugin_omniverse-mcp_omniverse__capture_viewport
  mcp__plugin_omniverse-mcp_omniverse__get_logs
---

# Work on a scene

The stage is a USD hierarchy of prims with paths such as `/World/Robot/base`. Edits apply at once; things move only
while physics plays. Never edit blind: look, change, look again.

## Steps

1. **Orient.** `get_sim_state` first: the up axis (Y or Z) decides which coordinate is height, `meters_per_unit` the
   scale of every number, and whether physics is playing.
2. **Find what is there.**
   - `get_scene_tree` for the hierarchy of a small scene; `dump_scene` writes a large one to a file, with properties
     filtered by type or name, to grep.
   - `get_prim_properties` for one prim's attributes; `get_prim_bounds` for its world box.
3. **Look.** `capture_viewport` writes three files to `mcp_output/captures/`: the image, the bounding boxes (each
   visible prim's screen box, world centre and size) and the instance segmentation (a colour per prim, with a legend).
   Read the boxes file for where things are; open the image when you need to see. `include_image=True` returns the
   image inline as well, at about 50K tokens: only when looking matters more than context.
   - A prim from every side: `inspect_prim`, which frames it, with `isolate=True` to hide everything else.
   - Another view: `set_camera` or `look_at_prim`, then capture.
   - Inside or behind something: `set_visibility(path, false)`, capture, then show it again.
   - Overlapping prims that look alike: the segmentation tells them apart.
4. **Place with numbers, not by eye.** `get_prim_bounds` of the thing and of what it goes on, compute the position
   on the up axis (an object rests on a surface when its bottom equals the surface's top), `set_prim_transform`, then
   capture to check.
5. **Change,** with `create_prim`, `set_prim_transform`, `clone_prim`, `set_material` or `set_visibility`.
   `clone_prim` refuses a target path that holds a prim, and `create_prim` one that holds a prim of another type:
   choose a free path, or delete the prim there first when the user wants it gone.
6. **Check every change** with another capture or `get_prim_bounds`. A tool that fails: `get_logs(min_level="warn")`
   shows what Kit reported.

## Light and black captures

Kit 105.1 and later have no default light, so a scene without lights captures black, and the capture says so.
`viewport_light("get")` shows the lighting mode and whether the stage has lights; `viewport_light(action="set",
mode="Default")` is the quickest fix, `mode="camera"` a light that follows the camera. When neither suits, add a light
to the stage with `create_prim` (`DistantLight`, `DomeLight`). Nothing relights the scene on its own.

## Traps

| Trap | What to do |
|---|---|
| The up axis guessed | `get_sim_state` before placing anything |
| A capture right after a camera move shows the old view | `inspect_prim` waits for the frames itself; after `set_camera` in a script, wait 20 frames |
| Segmentation missing or empty | it needs `omni.syntheticdata` (Isaac Sim has it), and the first capture after Kit starts can come back empty: capture again |
| Materials look grey at first | MDL compiles on first use: capture again before deciding a material is broken |
| `UsdGeom.Cube` and the like have no faces | implicit shapes, not meshes: `get_mesh_stats` counts only `UsdGeom.Mesh` |
| A new stage has no file | `save_scene` to a path before anything relies on one |
| A scene with thousands of instances | loading can take minutes, and tools answer slowly meanwhile: ask the user whether it has finished |
