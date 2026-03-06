# Architecture

Omniverse MCP uses a two-process architecture to bridge AI assistants with a running NVIDIA Omniverse application (Isaac Sim 5.1+, USD Composer, or any Kit-based app).

## Overview

```
                    stdio                     HTTP/REST
  AI Assistant  <----------->  MCP Server  <----------->  Omniverse Extension
  (any MCP client)            (Python)                    (runs inside Kit app)
                              port: n/a                   port: 8211
```

**Why two processes?**

Omniverse Kit-based applications (Isaac Sim, USD Composer, etc.) run as self-contained processes with their own Python runtime, event loop, and GPU context. External processes cannot directly call into them. The MCP protocol requires stdio transport, which is incompatible with running inside Kit's process.

The solution: an HTTP bridge.

## Component 1: MCP Server (`isaac_sim_mcp/`)

The MCP server is a standalone Python process that:

1. **Communicates with AI clients** via MCP stdio transport (stdin/stdout JSON-RPC)
2. **Defines the tool surface** -- 32 tools that AI assistants can call
3. **Forwards requests** to the Isaac Sim extension via HTTP
4. **Manages file output** -- saves images as PNGs, writes large text to files, returns paths

### Key files

| File | Purpose |
|------|---------|
| `server.py` | FastMCP server, all 32 tool definitions, file output helpers |
| `client.py` | HTTP/1.1 client with keep-alive connections to the extension |
| `__main__.py` | Entry point for `python -m isaac_sim_mcp` |

### Output management

The server manages a `mcp_output/` directory:

- **Images** are always saved as PNG files (never sent inline as base64)
- **Large text responses** (>1000 characters) are written to files
- **Scene dumps** are always written to files
- **Recordings** get their own timestamped subdirectories

This keeps the MCP context window clean -- the AI reads files on demand rather than receiving megabytes of scene data inline.

### HTTP Client

`client.py` implements a custom HTTP/1.1 client (no external `requests` dependency) with:

- Persistent keep-alive connections
- Automatic reconnection on failure (2 retry attempts)
- Proper Content-Length framing
- JSON request/response encoding

## Component 2: Omniverse Extension (`extension/`)

The extension is an Omniverse Kit extension that runs inside the application's process. It has full access to USD, PhysX, rendering, and all Omniverse/Isaac Sim APIs.

### Key files

| File | Purpose |
|------|---------|
| `extension.py` | HTTP server, request routing, lifecycle management |
| `handlers.py` | All endpoint handler implementations (2000+ lines) |
| `formatter.py` | Prim-block text format utilities |
| `config/extension.toml` | Extension metadata and default settings |

### HTTP Server

The extension runs an asyncio HTTP server on the application's event loop (same pattern as the built-in Jupyter extension). This is important -- it shares the event loop with Kit, so handlers can use `await omni.kit.app.get_app().next_update_async()` to synchronize with the main thread.

### Request routing

`extension.py` maintains a routes dictionary mapping URL paths to handler functions:

```
/health              -> handle_health
/execute             -> handle_execute
/scene/tree          -> handle_scene_tree
/scene/dump          -> handle_scene_dump
/scene/prim          -> handle_prim_properties
/scene/bounds        -> handle_prim_bounds
/scene/transform     -> handle_transform
/scene/create        -> handle_create_prim
/scene/delete        -> handle_delete_prim
/scene/material      -> handle_set_material
/scene/clone         -> handle_clone_prim
/scene/visibility    -> handle_set_visibility
/scene/save          -> handle_save_scene
/scene/new           -> handle_new_scene
/robot/create        -> handle_create_robot
/robot/info          -> handle_get_robot_info
/robot/joint_states  -> handle_get_joint_states
/robot/joint_targets -> handle_set_joint_targets
/sim/control         -> handle_sim_control
/sim/capture         -> handle_capture
/sim/state           -> handle_sim_state
/camera/set          -> handle_camera_set
/camera/look_at      -> handle_camera_look_at
/camera/inspect      -> handle_camera_inspect
/physics/properties  -> handle_set_physics_properties
/physics/apply_force -> handle_apply_force
/physics/raycast     -> handle_raycast
/debug/draw          -> handle_draw_debug
/recording/start     -> handle_recording_start
/recording/stop      -> handle_recording_stop
/recording/frame     -> handle_recording_frame
/extensions/list     -> handle_extensions_list
/extensions/manage   -> handle_extensions_manage
```

### Response format

All endpoints return JSON:

```json
{
  "status": "success",
  "result": { ... }
}
```

```json
{
  "status": "error",
  "error": "description of what went wrong"
}
```

Image data (viewport captures) is base64-encoded in the response and decoded/saved by the MCP server.

## Prim-Block Text Format

Scene and prim data uses a custom text format designed for grep-friendliness:

```
[/World/Robot]
type = Xform
pos = 0.0000, 1.0000, 0.0000
physics:mass = 5.0

[/World/Robot/arm]
type = Mesh
pos = 0.0000, 1.5000, 0.0000
```

**Why not JSON?**

JSON is hard to search with standard tools. With prim-block format:
- `grep '\[/World/Robot\]'` finds a specific prim
- `grep 'physics:mass'` finds a property across all prims
- `grep -A20 '\[/path\]'` gets a prim and its properties
- Line-oriented format works naturally with file reading tools that support line ranges

The format is implemented in `formatter.py` with functions for:
- `format_value()` -- Convert USD values (Vec3f, Quatd, Matrix4d, etc.) to readable strings
- `format_prim_block()` -- Format a single prim as a text block
- `format_scene_dump()` -- Recursively format an entire scene tree
- `format_frame_state()` -- Format a snapshot for recording

## Threading Model

1. The HTTP server runs on the Omniverse application's asyncio event loop
2. Handlers use `await omni.kit.app.get_app().next_update_async()` to sync with the main thread before accessing USD/PhysX state
3. Script execution (`execute_script`) uses `exec()` with stdout captured via `io.StringIO`
4. Viewport capture waits for render completion before reading back pixels

This means all handler code runs on the main thread -- there are no threading issues with USD access, but long-running handlers will block the simulation for the duration of their execution.

## Recording System

The recording system captures simulation frames and optional prim state:

1. `start_recording` registers an update callback on the application's event loop
2. On each update tick, the callback checks if enough time has elapsed since the last capture
3. If so, it captures a viewport frame (PNG) and optionally writes prim state to `state.txt`
4. `stop_recording` unregisters the callback and writes `metadata.json`

State tracking uses the prim-block format with frame headers:
```
=== FRAME t=0.000 step=0 ===
[/World/Robot]
type = Xform
pos = 0.0000, 1.0000, 0.0000

=== FRAME t=0.200 step=1 ===
[/World/Robot]
type = Xform
pos = 0.0000, 0.9500, 0.0000
```

## Robot System

The robot tools use a hybrid approach:

- **`create_robot`** looks up USD asset paths from a built-in library and loads them as USD references
- **`get_robot_info`** traverses the USD hierarchy to find joints, reading types and limits from USD properties
- **`get_joint_states`** uses Isaac Sim's Articulation API (requires sim to have played once)
- **`set_joint_targets`** sets USD drive target attributes directly, which works without articulation initialization

## Viewport Capture

Viewport capture uses `omni.kit.viewport.utility.capture_viewport_to_file()`. The captured image is read back, base64-encoded, and sent in the HTTP response to the MCP server, which decodes it and saves it as a PNG file.

**Cold-start note:** The first capture after launching the application may return a black or incomplete image because the renderer hasn't fully initialized. A second capture typically works correctly.

## Extension Lifecycle

- **on_startup**: Creates the HTTP server, binds to configured host:port, registers all routes
- **on_shutdown**: Closes the HTTP server, cleans up resources

The extension can be enabled/disabled from the application's extension manager (Window > Extensions). Disabling it stops the HTTP server; re-enabling restarts it.
