# Architecture

Omniverse MCP is two processes: the MCP server, which an AI client starts, and the bridge, the Kit extension
`ovmcp.bridge` inside a running Kit app (Kit 107 and up: Isaac Sim 5.x and up, USD Composer). This page is for
contributors; setting it up is in the [README](../README.md) and [SETUP.md](SETUP.md).

## Overview

```
                    stdio                      HTTP, with a token
  AI client     <----------->  omniverse-mcp  <----------------->  ovmcp.bridge
  (any MCP client)            (the MCP server)                    (inside the Kit app)
                                                                  port: 8211
```

**Why two processes?**

Kit apps (Isaac Sim, USD Composer) run as processes of their own, with their own Python, event loop and GPU
context, and other processes can't call into them. An MCP client starts a local server as its child process and
talks to it over stdio; Kit can't be that child process, so the server is a process of its own that reaches Kit
over HTTP.

The solution: an HTTP bridge.

## Component 1: MCP Server (`src/omniverse_mcp/`)

The MCP server is a standalone Python process that:

1. **Communicates with AI clients** via MCP stdio transport (stdin/stdout JSON-RPC)
2. **Defines the tool surface** - the MCP tools that AI assistants can call (`docs/TOOLS.md`)
3. **Forwards requests** to the Kit extension over HTTP
4. **Manages file output** - saves images as PNGs, writes large text to files, returns paths

### Key files

| File | Purpose |
|------|---------|
| `server.py` | `create_server()`: the MCP server on SDK v2 (`MCPServer`), file output helpers (`Helpers`), MCP resources; `main()` reads the flags and runs it. Importing it does nothing |
| `client.py` | HTTP/1.1 client with keep-alive connections to the extension; one request at a time, since the SDK runs tools on worker threads |
| `tools/` | Tool modules: each registers its MCP tools via `register(mcp, client, helpers)` |
| `__main__.py` | Entry point for `python -m omniverse_mcp`; the `omniverse-mcp` command runs `server.main` |

### Tool modules (`tools/`)

Tools are split into focused modules. Each calls the bridge through `_bridge.py`'s `bridge_call()`, which returns
the bridge's answer or raises `ToolError`: the client gets an error result (`isError`) with the bridge's message and
the last five lines of its traceback, or why the Kit app couldn't be reached.

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

The output folder is `mcp_output/` in the server's working directory, or `--output-dir`, made by the first file
written there, not at start. A file under the working directory is given by its relative path, any other by its
absolute path (`Helpers.rel`).

- **Images:** the bridge sends each capture as base64 PNG, and the server writes it to `captures/`.
  `capture_viewport(include_image=True)` also returns it inline as `ImageContent`.
- **Long text:** an answer over 1,000 characters goes to `responses/`.
- **Scene dumps and recordings:** Kit writes them itself, to the path the server passes, so with Kit on another
  machine they land on that machine. Each recording gets a timestamped folder.

This keeps the MCP context window clean - the AI reads files on demand rather than receiving megabytes of scene data inline.

### HTTP Client

`client.py` implements a custom HTTP/1.1 client (no external `requests` dependency) with:

- Persistent keep-alive connections
- The bridge token on every request (see [The bridge token](#the-bridge-token)), read again after a 401
- A handshake, `GET /bridge`, at the start of every new connection; an extension of another protocol is refused
  with the command that installs this server's: `uvx omniverse-mcp==X.Y.Z extension install`, or from a checkout
  `uv run --project <checkout> omniverse-mcp extension install`
- Automatic reconnection on failure (1 retry, 2 total attempts)
- A 120-second timeout on each request; the bridge's capture calls answer within about 90 s, under it
  ([Viewport Capture](#viewport-capture))
- Proper Content-Length framing with chunked body reading (avoids O(n²) buffer concatenation)
- JSON request/response encoding
- Structured logging via Python `logging` module

## Component 2: the Kit extension (`extension/ovmcp.bridge/`)

The extension, the bridge, runs inside the Kit app's process. It has full access to USD, PhysX, rendering, and all Omniverse/Isaac Sim APIs.

### Delivery

The wheel carries the extension of its own release as `omniverse_mcp/_extension/ovmcp.bridge`, so the server and the
extension come from one release. `omniverse-mcp extension install` (`src/omniverse_mcp/kit_extension.py`) copies it to
`exts/ovmcp.bridge` in the user's data folder (`%LOCALAPPDATA%\omniverse-mcp` on Windows,
`~/Library/Application Support/omniverse-mcp` on macOS, `$XDG_DATA_HOME/omniverse-mcp` or
`~/.local/share/omniverse-mcp` on Linux), and Kit's extension search paths take that `exts` folder once.

- **Whole or not at all:** the copy is made in the data folder, outside `exts` where Kit would see half of it, and
  swapped in by renaming, so no module a new release dropped is left to load. A swap that fails, as on Windows while a
  Kit app holds the folder, puts the old one back; when even that fails, the old one stays in the data folder and the
  message says where.
- **A checkout** has no `_extension` folder in its editable install: the command copies `extension/ovmcp.bridge`, and
  Kit can as well point at the checkout's `extension/` folder.
- **`extension path`** prints the `exts` folder, and fails while nothing is installed there.

### Key files

| File | Purpose |
|------|---------|
| `ovmcp/bridge/extension.py` | Kit lifecycle: makes the token, starts the core's HTTP server with the routes |
| `ovmcp/core/` | Kit-free core, unit-tested on usd-core and numpy without Kit, typed in strict mode; import-linter keeps `omni`, `carb`, `isaacsim` and `ovmcp.bridge` out of it: `http.py` (HTTP server, token and browser checks, routing), `token.py` (the token file), `protocol.py` (the handshake), `formatter.py` (the prim-block text), `bounds.py` (world boxes and their outline on screen), `capture.py` (the capture path's waits, each bounded by time, and a call's bookkeeping), `png.py` (the PNG writer), `logs.py` (Kit's log file read into the log ring, and its query), `force.py` (apply_force's request, its refusals and the point it pushes at), `framing.py`, `isolation.py`, `lighting.py`, `material.py` (set_material's OmniPBR, named by its MDL source), `robot.py` (where create_robot loads a USD file from, and its prim's name; the articulation root get_joint_states reads), `extensions.py` (whether an extension the bridge needs is on, can be turned on, or is absent), `debug_draw.py` (draw_debug's shapes as segments, its colours, and the book of drawings still due), `serial.py`, `usd.py` (typed forms of pxr calls the stubs get wrong) |
| `ovmcp/bridge/handlers/` | Handler package: split into focused modules (camera, scene, simulation, recording, robot, debug_draw, misc, usd_advanced, logging) with shared utilities in `_utils.py` (among them `enable_extension`) and `_mcp_bridge.py` |
| `config/extension.toml` | Extension metadata and default settings |

### HTTP Server

The extension runs an asyncio HTTP server on the application's event loop (same pattern as the built-in Jupyter extension). This is important - it shares the event loop with Kit, so handlers can use `await omni.kit.app.get_app().next_update_async()` to synchronise with the main thread.

### The bridge token

`/execute` runs any Python inside the app, so the bridge answers only a client that holds its token.

| Step | What happens |
|---|---|
| Kit starts the extension | A new random token (or the `token` setting, if set); once the port is bound, it is written to the token file, readable by this user only |
| The MCP server opens a connection | `GET /bridge` first, with no body: the token is checked, and the extension's `protocol` compared with the server's |
| The MCP server sends a request | `Authorization: Bearer <token>`, from `OMNIVERSE_MCP_TOKEN` or else the token file |
| Kit restarts | A new token; the server's handshake gets a 401, it reads the file again and retries once |
| The extension stops | The token file is removed, if this instance wrote it |

The token file is `bridge-<port>.token` in:

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\omniverse-mcp\` |
| Linux | `$XDG_STATE_HOME/omniverse-mcp/`, else `~/.local/state/omniverse-mcp/` |
| macOS | `~/Library/Application Support/omniverse-mcp/` |

`OMNIVERSE_MCP_STATE_DIR` overrides the folder on both sides. On Windows the folder's permissions are what keep the
file private (`%LOCALAPPDATA%` is per user), so an override must point at a folder only you can read.

A request is refused, and its connection closed, before its body is read when:

- it has no token or a wrong one (401);
- it carries an `Origin` header (403). Browsers send one on every POST, so a web page cannot reach the bridge;
- the bridge is bound to loopback and the `Host` header names something else (403), which stops DNS rebinding.

A connection that sends nothing for 5 minutes is closed (the client reconnects without notice), and one that takes
over 10 seconds to send its headers too. Connections without the token never hold one of the 20 handler slots.

`GET /bridge` is answered by the HTTP server itself, whatever state Kit is in. The server refuses an extension whose
`protocol` differs from its own, or that has no `/bridge`, and says which side to update. Another
`extension_version` on the same protocol is not refused: the client keeps it, and `get_sim_state` reports it beside
the server's, with the install command when it differs from the extension the server carries. `/health` reports
`protocol` and `extension_version` as well, for people.

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

The format is implemented in `ovmcp/core/formatter.py` with functions for:
- `format_value()` - Convert USD values (Vec3f, Quatd, Matrix4d, etc.) to readable strings
- `format_prim_block()` - Format a single prim as a text block
- `format_scene_dump()` - Recursively format an entire scene tree
- `format_frame_state()` - Format a snapshot for recording

## Threading Model

1. The HTTP server runs on the Omniverse application's asyncio event loop
2. Handlers use `await omni.kit.app.get_app().next_update_async()` to sync with the main thread before accessing USD/PhysX state
3. Script execution (`execute_script`) runs `exec()` directly on the main thread with stdout/stderr captured via `io.StringIO`. It must run on the main thread because USD/Omniverse APIs are not thread-safe. If the code contains `await` expressions, it is automatically wrapped in an async function and awaited, allowing scripts to call async `mcp.*` methods while still running on the main thread's event loop
4. Viewport capture waits for fresh frames, the viewport's frame, then its file, each wait bounded by time (`ovmcp/core/capture.py`): `asyncio.wait_for` and polls on the same loop, no thread, so a viewport that renders nothing fails the call rather than hanging it. A frame wait observes Kit's `NEW_FRAME` event through omni.usd's `next_frame_async`, as an immediate observer, which Kit 110's own code says may fire on the renderer thread with async rendering. Isaac Sim's headless Python app renders synchronously (`asyncRendering = false`); its GUI renders asynchronously whenever the simulation is stopped or paused, since `isaacsim.core.throttling` (`enable_async = true` in `isaacsim.exp.full.kit`) turns async rendering on at startup and a few updates after each stop or pause, and off on play. On Isaac Sim 6.2 headless with async rendering turned on the same way, every `NEW_FRAME`, immediate or deferred, and every `DRAWABLE_CHANGED` came on the main thread (#57); the GUI itself, and other Kit apps such as USD Composer, are untested
5. The bridge hands Kit's logging no Python callback. Kit runs one on whichever thread logs, and a physics worker that
   logged waited for the GIL that the main thread held while it waited for the worker, so Kit hung
   ([#5](https://github.com/serionist/omniverse-mcp/issues/5)). `get_logs` reads Kit's log file on the main thread
   instead; `tests/test_logs.py` fails on any Python hook on Kit's logging in the extension

This means all handler code runs on the main thread - there are no threading issues with USD access, but long-running handlers will block the simulation for the duration of their execution.

## Kit's log

`get_logs` reads Kit's log file; `ovmcp/core/logs.py` holds the reader and the ring, and `handlers/logging.py` only
hands it Kit's `/log/file` setting and the bridge token.

- **Where reading starts:** where the file ended when the extension started. Kit's first lines hold its command
  line, where a remote setup can pass the bridge token.
- **Each `POST /logs`,** on the main thread, reads what Kit appended since the last, at most the newest 1 MB, then
  filters the ring by count, min_level, channel, search and since_index.
- **An entry** starts with a header line, such as `2026-01-01T00:00:00Z [1,234ms] [Warning] [omni.physx] text`; the
  lines after it that start none, a multi-line message or a traceback, join its `msg`, in a later read too. After a
  read that skipped bytes, reading resumes at the next header.
- **Each entry** has: index (monotonic), level, channel, msg, timestamp (the line's text), and module, source and
  func, which Kit's file leaves empty. The bridge token is replaced by `<redacted>`.
- **A `/log/file` that is empty,** or holds a `${...}` token `carb.tokens` can't resolve, makes `/logs` an error that
  names `--/log/file=<path>`.

The log is useful for diagnosing tool failures - when an MCP tool returns an error, the AI can call `get_logs(min_level="warn")` to see what Omniverse reported internally (e.g., PhysX errors, USD composition failures, missing extensions).

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

## Debug Drawing

`draw_debug` (`handlers/debug_draw.py`) draws with `isaacsim.util.debug_draw`, or `omni.debugdraw` in a Kit app
without it, turned on at the first call by `enable_extension` (`handlers/_utils.py`) when the app has it on disk.

1. The handler draws a shape's segments at once and adds them to the book (`core/debug_draw.py`), with the stage's
   id and the moment they expire, by `time.monotonic()`.
2. While the book holds a drawing, one subscription to the update event stream runs on the main thread: it drops
   drawings that expired or belong to another stage, then clears and draws the rest again, since
   `isaacsim.util.debug_draw`'s clear takes every line. `omni.debugdraw` forgets a line after a frame, so with it the
   book's lines are drawn on every update.
3. A clear waits for an update with the stage `OPENED`, never while it opens or closes, and the subscription goes
   once nothing is left.

## Robot System

The robot tools use a hybrid approach:

- **`create_robot`** loads a named robot from Isaac Sim's asset library, or a USD file, as a USD reference
  (`core/robot.py` says from where)
- **`get_robot_info`** traverses the USD hierarchy to find joints, reading types and limits from USD properties
- **`get_joint_states`** finds the articulation root as `get_robot_info` does (`core/robot.py`), then reads it
  through Isaac Sim's `isaacsim.core.experimental.prims.Articulation`, a new one per call, while physics plays or is
  paused; it never loads physics itself
- **`set_joint_targets`** sets USD drive target attributes directly, which works without articulation initialisation

## Viewport Capture

Viewport capture uses `omni.kit.viewport.utility.capture_viewport_to_file()`, through `capture_viewport_png` in `handlers/_utils.py`: each capture writes a file of its own, read once the PNG is whole (`ovmcp.core.png.is_complete_png`), since on Kit 110 the capture reports done before the file is written. The image is base64-encoded and sent in the HTTP response to the MCP server, which decodes it and saves it as a PNG file.

**Fresh frames:** Kit captures the next frame the viewport delivers, which the renderer made about 3 updates before:
Isaac Sim keeps 3 stage frames of history for it (`/app/settings/fabricDefaultStageFrameHistoryCount`). Captured
at once, a drawing or a change made just before was missing (#57). So `capture_viewport` and `inspect_prim` let
`FRESH_FRAMES` (4) frames of the viewport pass before they capture. Measured on Isaac Sim 6.2 headless, rendering
synchronously and asynchronously: 2 frames were always enough, 3 for the longest trail seen. Frames carry no number
that would tell their age (`swh_frame_number` is `-1` there), so the wait counts them. Recording asks for none:
its ticks would take about twice as long and overlap, and overlapping ticks write over each other's frames (#69);
its frames still show the scene a few updates before their `sim_time`.

**Cold start:** the first capture after the app starts can come back black while the renderer warms up. A black
frame is reset and captured once more by itself (`_capture_frame` in `handlers/camera.py`); if it is still black,
the answer says so, with the lighting mode.

**Every wait has a time limit** (`ovmcp/core/capture.py`; each limit is read when its wait runs):

| Wait | Limit |
|---|---|
| one frame of the viewport: each of a settle's 20, a renderer reset's, a capture's 4 fresh ones, and the capture's own `wait_for_result` | 30 s (`FRAME_SECONDS`) |
| the file, after the frame | 10 s (`FILE_SECONDS`) |
| instance segmentation's first data after the sensor is enabled, read after each app update | 5 s (`SEGMENTATION_SECONDS`) |
| an `inspect_prim` or `capture_viewport` call | 80 s (`CALL_SECONDS`), then 10 s (`CLEANUP_SECONDS`) for the settle after `isolate` |

- **Fails at once:** a capture whose `wait_for_result` names nothing captured (`[]` or `None`), and a viewport with
  no render texture yet: no file will come for either. `capture_viewport` and `inspect_prim` reach the render texture
  check only after their fresh frames, which such a viewport doesn't deliver, so there they fail after
  `FRAME_SECONDS`, as a viewport that rendered no frame; recording, without fresh frames, still fails at once.
- **Frame by frame:** a settle and a capture's fresh frames wait through `next_viewport_frame_async`, one frame at a
  time (`_next_frame` in `handlers/_utils.py`), not `ViewportAPI.wait_for_rendered_frames`, which counts its
  subscribe call as a frame and leaves a cancelled wait's callback in the viewport. A Kit without the frame event
  pumps an app update for each frame instead, with a warning the first time.
- **A call stops:** in `inspect_prim`, a frame that never comes (`NoFrameError`) or the call's time running out
  (`OutOfTimeError`) stops the call, and the angles left are `Not captured`; after `NoFrameError`, the restore after
  `isolate` doesn't wait for frames. Any other error is its angle's alone.
- **Under the server's timeout:** 80 s plus 10 s leaves 30 s of the client's 120 s for encoding the images and
  sending them; `tests/test_capture.py` holds the sum under the client's timeout.
- **Outside a call:** `set_camera`, `look_at_prim` and `viewport_light` give a settle or reset 30 s for all its
  frames, and answer as before, with a warning in Kit's log, when the frames don't come. A recording frame gets 30 s,
  then 10 s for its file, and is the empty marker when they run out.
- **Kit versions:** run live on Isaac Sim 6.2 (Kit 110) only. Kit 107's capture, frame wait and `omni.syntheticdata`
  sources were read and match Kit 110's where this relies on them, but Isaac Sim 5.x is untested live: 5.1 crashed
  in its own start on the test machine, before any extension loaded.
- **Timers on Kit's loop:** they fire only while the loop runs, so a main thread blocked by a shader compile delays
  them.
- **In Kit's log:** a failed capture's step and seconds (a warning); a capture over 2 s, how long its fresh frames,
  frame and file took, with the app's stage frame history; each segmentation wait's updates and seconds. `get_logs(search="capture")` and `search="segmentation"`
  find the bridge's lines; `channel="syntheticdata"` finds what `omni.syntheticdata` itself reported, whose lines
  rarely name it.

**Segmentation:** `omni.syntheticdata` drops its sensors on every stage open (`new_scene`, an opened file). A capture
that reads the instance segmentation sensor empty enables it again and reads it after each app update for up to 5 s.
An answer without segmentation says why in `segmentation_error`. A wait that got nothing is not repeated on that stage
and render product until a read gets data, so `capture_viewport` doesn't pay it on every call.

## Extension Lifecycle

- **on_startup**: Creates the HTTP server, binds to configured host:port, registers all routes. Enables the `omni.syntheticdata` instance segmentation sensor once the viewport exists, so the first capture after the app starts has segmentation; Kit drops it on every stage open, and a capture that finds it empty enables it again ([Viewport Capture](#viewport-capture))
- **on_shutdown**: Stops any active recording, drops the debug drawing subscription and its book (clearing nothing:
  the stage may be tearing down), clears caches, closes the HTTP server

The extension includes:
- **Content-Length validation**: Rejects request bodies over 100 MB
- **Connection limiting**: 20 handler slots, so at most 20 requests run at once
- **Health endpoint**: `GET /health` returns server status with error wrapping

The extension can be enabled/disabled from the application's extension manager (Window > Extensions). Disabling it stops the HTTP server; re-enabling restarts it.
