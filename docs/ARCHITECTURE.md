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
2. **Defines the tool surface** -- 40 MCP tools that AI assistants can call
3. **Forwards requests** to the Isaac Sim extension via HTTP
4. **Manages file output** -- saves images as PNGs, writes large text to files, returns paths

### Key files

| File | Purpose |
|------|---------|
| `server.py` | FastMCP server, file output helpers (`_Helpers`), MCP resources |
| `client.py` | HTTP/1.1 client with keep-alive connections to the extension |
| `tools/` | Tool modules — each registers its MCP tools via `register(mcp, client, helpers)` |
| `__main__.py` | Entry point for `python -m isaac_sim_mcp` |

### Tool modules (`tools/`)

Tools are split into focused modules, each with its own `_call`/`_check_error` error wrappers:

| Module | Tools |
|--------|-------|
| `scene.py` | Scene graph: tree, dump, properties, bounds, transform, create, delete, material, clone, visibility, save, new |
| `camera.py` | Viewport: capture, set camera, look at, inspect (orbit), viewport light |
| `robot.py` | Robot: create, info, joint states, joint targets |
| `simulation.py` | Sim control, state, physics properties, apply force, raycast, debug draw |
| `recording.py` | Recording: start, stop, get frame |
| `usd_advanced.py` | Mesh stats, face count tree, flatten, export, variants, compare, material paths |
| `misc.py` | execute_script, manage_extensions, get_logs |

### Output management

The server manages a `mcp_output/` directory:

- **Images** are saved as PNG files by default. `capture_viewport(include_image=True)` also returns the viewport image inline as `ImageContent` for AI assistants that can see images directly
- **Large text responses** (>1000 characters) are written to files
- **Scene dumps** are always written to files
- **Recordings** get their own timestamped subdirectories

This keeps the MCP context window clean -- the AI reads files on demand rather than receiving megabytes of scene data inline.

### HTTP Client

`client.py` implements a custom HTTP/1.1 client (no external `requests` dependency) with:

- Persistent keep-alive connections
- Automatic reconnection on failure (1 retry, 2 total attempts)
- Configurable timeout (default 120s)
- Proper Content-Length framing with chunked body reading (avoids O(n²) buffer concatenation)
- JSON request/response encoding
- Structured logging via Python `logging` module

## Component 2: Omniverse Extension (`extension/`)

The extension is an Omniverse Kit extension that runs inside the application's process. It has full access to USD, PhysX, rendering, and all Omniverse/Isaac Sim APIs.

### Key files

| File | Purpose |
|------|---------|
| `extension.py` | HTTP server, request routing, lifecycle management |
| `handlers/` | Handler package — split into focused modules (camera, scene, simulation, recording, robot, misc, usd_advanced, logging) with shared utilities in `_utils.py` and `_mcp_bridge.py` |
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
/scene/mesh_stats    -> handle_mesh_stats
/scene/face_count_tree -> handle_face_count_tree
/scene/flatten       -> handle_flatten_usd
/scene/export        -> handle_export_prim
/scene/variant_selection -> handle_set_variant_selection
/scene/create_variant_structure -> handle_create_variant_structure
/scene/compare       -> handle_compare_prims
/scene/update_material_paths -> handle_update_material_paths
/viewport/light              -> handle_viewport_light
/logs                        -> handle_get_logs
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
3. Script execution (`execute_script`) runs `exec()` directly on the main thread with stdout/stderr captured via `io.StringIO`. It must run on the main thread because USD/Omniverse APIs are not thread-safe. If the code contains `await` expressions, it is automatically wrapped in an async function and awaited, allowing scripts to call async `mcp.*` methods while still running on the main thread's event loop
4. Viewport capture waits for render completion before reading back pixels
5. The log buffer's `_on_log` callback uses a `threading.Lock` since `omni.log` may fire from any thread

This means all handler code runs on the main thread -- there are no threading issues with USD access, but long-running handlers will block the simulation for the duration of their execution.

## Log Buffer

The extension captures Omniverse log messages in a ring buffer (`collections.deque`, default 2000 entries) via `omni.log.get_log().add_message_consumer()`. This captures all log sources: `carb.log_*()`, Python `logging`, and internal Kit/PhysX/USD messages.

- **Started** in `on_startup` before the HTTP server, so startup messages are captured
- **Stopped** in `on_shutdown` to clean up the consumer
- **Queried** via `GET/POST /logs` with filters for count, min_level, channel, search, since_index
- Each entry has: index (monotonic), level, channel, module, source (file:line), func, msg, timestamp

The log buffer is useful for diagnosing tool failures -- when an MCP tool returns an error, the AI can call `get_logs(min_level="warn")` to see what Omniverse reported internally (e.g., PhysX errors, USD composition failures, missing extensions).

## MCPBridge (execute_script internal API)

The `MCPBridge` class (`handlers/_mcp_bridge.py`) is injected into `execute_script` as the `mcp` variable. It provides async methods that call handler functions directly (in-process, no HTTP round-trip):

```python
# In execute_script code:
viewport = await mcp.capture_viewport(width=1280)
bounds = await mcp.prim_bounds("/World/Cube")
await mcp.set_camera([5, 3, 5], target=[0, 0, 0])
result = bounds["result"]["center"]
```

**Async detection**: The execute handler tries to `compile()` the code. If it fails with SyntaxError (due to top-level `await`), it wraps the code in `async def __mcp_exec__():` and awaits it. This means sync scripts work exactly as before, and async scripts "just work" when they use `await`.

## Recording System

The recording system captures simulation frames and optional prim state:

1. `start_recording` subscribes to the application's update event stream via `get_update_event_stream().create_subscription_to_pop()`
2. On each update tick, a step counter increments; when `_step_counter % _steps_per_frame == 0` a frame is captured (steps_per_frame is derived from sim FPS / recording FPS)
3. Each captured frame is saved as a PNG, and if tracking prims, their state is appended to `state.txt`
4. `stop_recording` releases the subscription (sets it to `None`) and writes `metadata.json`

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

- **on_startup**: Creates the HTTP server, binds to configured host:port, registers all routes. Pre-initializes the `omni.syntheticdata` segmentation sensor (with retry) so the first `capture_viewport` call returns segmentation data without needing warmup frames
- **on_shutdown**: Stops any active recording, clears caches, closes the HTTP server

The extension includes:
- **Content-Length validation**: Rejects request bodies over 100 MB
- **Connection limiting**: Maximum 20 concurrent connections via semaphore
- **Health endpoint**: `GET /health` returns server status with error wrapping

The extension can be enabled/disabled from the application's extension manager (Window > Extensions). Disabling it stops the HTTP server; re-enabling restarts it.
