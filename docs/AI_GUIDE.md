# Omniverse MCP - AI Assistant Guide

> **This file is a template.** Copy it into your project's AI instruction file (e.g., `CLAUDE.md`, `.cursorrules`, or equivalent) so your AI assistant knows how to use the Omniverse MCP tools effectively.

## Context

You are connected to a running NVIDIA Omniverse application (Isaac Sim 5.1+, USD Composer, etc.) via the Omniverse MCP. The scene is a USD stage -- a hierarchy of "prims" with paths like `/World/Robot/body`. Objects only move during physics playback; scene edits are instant.

**Always call `get_sim_state()` first** to learn the up axis (Y or Z), whether physics is running, and the scene scale.

## Recommended Companion: Context7 MCP

AI models are not trained on Omniverse/Isaac Sim APIs. Before writing any `execute_script` code, use the Context7 MCP to look up the correct API:
- Library ID: `isaac-sim/isaacsim`
- Example: "how to set joint positions on an articulation"

This prevents hallucinated API calls. Without it, `execute_script` code will frequently fail.

## Workflow

```
1. get_sim_state()           -> learn up axis, sim state
2. capture_viewport()        -> see the scene (image + bboxes + segmentation)
3. get_scene_tree()          -> understand the prim hierarchy
4. [make changes]            -> create/transform prims, spawn robots
5. capture_viewport()        -> verify changes visually
6. sim_control("play")       -> start physics
7. start_recording() + play  -> capture behavior over time
8. stop_recording()          -> review frames
```

## Best Practices

### Always look before you act

`capture_viewport()` is your primary tool for understanding the scene. It returns three files every time:
1. **Viewport image** (PNG) -- what the camera sees
2. **Bounding boxes** (TXT) -- screen-space pixel coordinates + world-space bounds for every visible prim
3. **Instance segmentation** (PNG + legend TXT) -- each prim rendered as a unique color, with a legend mapping colors to prim paths

**Use capture_viewport liberally.** Call it at the start to understand the scene, after every significant change to verify results, and whenever you need spatial information.

### Scene discovery

When exploring an unfamiliar scene:
1. `capture_viewport()` -- see the full scene, read the bounding box file to identify what's where
2. `get_scene_tree()` -- understand the prim hierarchy
3. Move the camera with `set_camera()` or `look_at_prim()` to examine specific areas
4. Use `inspect_prim()` to orbit-capture an object from multiple angles
5. Hide objects with `set_visibility(path, false)` then `capture_viewport()` again to see what's behind/inside them
6. Re-show with `set_visibility(path, true)` when done

### Spatial reasoning

Use bounding boxes for accurate placement:
```
1. get_prim_bounds("/World/desk")   -> center, dimensions
2. get_prim_bounds("/World/apple")  -> center, dimensions
3. set_prim_transform("/World/apple", position=[computed])
4. capture_viewport()               -> verify placement visually
```

Cross-reference the bounding box file from `capture_viewport()` with the viewport image -- the screen_bbox tells you exactly where each prim appears in the image, so you can verify positions match your intent.

### Investigating complex scenes

For scenes with many nested or overlapping objects:
- **Peel layers**: Hide outer objects (`set_visibility`) to reveal internal structure, capture, then restore
- **Use segmentation**: The instance segmentation image lets you distinguish overlapping objects that look similar in the viewport -- each gets a unique color
- **Filter by region**: Read the bounding box file and focus on prims whose screen_bbox falls in the area of interest
- **Orbit captures**: Use `inspect_prim()` to see an object from multiple angles when a single view isn't enough
- **World bounds**: The bounding box file includes `world_center` and `world_dimensions` for every visible prim -- use these for spatial math without needing `get_prim_bounds()` calls

### Verification loop

After any change, verify:
```
[make change] -> capture_viewport() -> check image + bboxes -> adjust if needed
```
Do not assume changes worked. Always visually confirm.

## Output Files

- Viewport captures -> `mcp_output/captures/viewport_NNNN.png`
- Bounding boxes -> `mcp_output/captures/viewport_NNNN_bboxes.txt`
- Segmentation -> `mcp_output/captures/viewport_NNNN_segmentation_NNNN.png` + `_legend.txt`
- Large text -> `mcp_output/responses/*.txt`
- Scene dumps -> `mcp_output/scene_dump.txt`
- Recordings -> `mcp_output/recordings/rec_TIMESTAMP/`

Data uses prim-block format (`[/path]` headers, `key = value` lines), not JSON.

## execute_script

Pre-loaded: `omni`, `carb`, `Usd`, `UsdGeom`, `UsdLux`, `UsdPhysics`, `Sdf`, `Gf`. Set `result = <value>` to return data.

**Fallback strategy:** Every MCP tool can be replicated via `execute_script` using the Omniverse Python API directly. If a tool returns an error, you can fall back to writing the equivalent Python code. Use Context7 (`isaac-sim/isaacsim`) or the [NVIDIA Omniverse docs](https://docs.omniverse.nvidia.com/) to find the correct API.

## Available Robots (Isaac Sim)

franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal

## Common Pitfalls

- **Wrong up axis**: Always check with `get_sim_state()` before placing objects
- **Blind edits**: Always `capture_viewport()` after changes -- don't assume they worked
- **Object falls through ground**: Missing `UsdPhysics.CollisionAPI`
- **Joint states empty**: Sim must have played at least once
- **API guessing**: Use Context7 -- don't guess Omniverse APIs
- **Large scenes**: Use `dump_scene` instead of `get_scene_tree` with properties
- **Tool errors**: If any MCP tool fails, fall back to `execute_script` with the equivalent Python code
- **Can't see inside**: Hide outer prims with `set_visibility` to reveal internal structure
