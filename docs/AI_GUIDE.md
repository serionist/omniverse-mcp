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
2. get_scene_tree()          -> see what exists
3. [make changes]            -> create/transform prims, spawn robots
4. capture_viewport()        -> verify visually (image + bboxes + segmentation)
5. sim_control("play")       -> start physics
6. start_recording() + play  -> capture behavior over time
7. stop_recording()          -> review frames
```

## Spatial Positioning

Use bounding boxes for accurate placement:
```
1. get_prim_bounds("/World/desk")   -> center, dimensions
2. get_prim_bounds("/World/apple")  -> center, dimensions
3. set_prim_transform("/World/apple", position=[computed])
4. capture_viewport()               -> verify
```

## Scene Understanding with capture_viewport

`capture_viewport()` outputs 3 files every time you call it:
1. **Viewport image** -- what the camera sees (PNG)
2. **Bounding boxes** -- screen-space pixel coordinates + world-space bounds for each visible prim (TXT)
3. **Instance segmentation** -- unique color per prim (PNG + legend TXT)

Use the bounding box file to know which prim occupies which part of the image. Use the segmentation image + legend to visually identify prims by color. This is especially useful for verifying object placement, identifying occluded objects, and spatial reasoning.

## Output

- Viewport captures -> `mcp_output/captures/viewport_NNNN.png`
- Bounding boxes -> `mcp_output/captures/viewport_NNNN_bboxes.txt`
- Segmentation -> `mcp_output/captures/viewport_NNNN_segmentation_NNNN.png`
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

- **Wrong up axis**: Always check before placing objects
- **Object falls through ground**: Missing `UsdPhysics.CollisionAPI`
- **Joint states empty**: Sim must have played at least once
- **API guessing**: Use Context7 -- don't guess Omniverse APIs
- **Large scenes**: Use `dump_scene` instead of `get_scene_tree` with properties
- **Tool errors**: If any MCP tool fails, fall back to `execute_script` with the equivalent Python code
