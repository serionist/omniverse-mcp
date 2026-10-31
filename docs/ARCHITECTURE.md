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

Each tool registers through `_annotations.py`'s `tool()`, with its hints and its docstring as the description. The
SDK sends a docstring as `__doc__` holds it, which Python before 3.13 keeps indented as in the source, so `tool()`
passes it through `inspect.cleandoc`; `tests/test_contract.py` fails on a description that still carries it.

| Module | Tools |
|--------|-------|
| `scene.py` | Scene graph: tree, dump, properties, bounds, transform, create, delete, material, clone, visibility, save, open, new |
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
| `ovmcp/core/` | Kit-free core, unit-tested on usd-core and numpy without Kit, typed in strict mode; import-linter keeps `omni`, `carb`, `isaacsim` and `ovmcp.bridge` out of it: `http.py` (HTTP server, token and browser checks, routing), `token.py` (the token file), `protocol.py` (the handshake), `formatter.py` (the prim-block text), `bounds.py` (world boxes and their outline on screen), `capture.py` (the capture path's waits, each bounded by time, a call's bookkeeping, the frame-size limit, 4096 a side, for start_recording, capture_viewport and inspect_prim, Path Tracing's settle frames, and segmentation's colours), `png.py` (the PNG writer), `logs.py` (Kit's log file read into the log ring, and its query), `force.py` (apply_force's request, its refusals and the point it pushes at; from the stage's joints, the articulation a body is a link of and the fixed joint that holds it to the world), `framing.py`, `isolation.py`, `lighting.py`, `material.py` (set_material's OmniPBR, named by its MDL source), `robot.py` (whether create_robot was given a file or a name, and its prim's name; the articulation root get_joint_states reads), `usd_files.py` (where a USD file a tool is given loads from: a URL, a file on Kit's machine, Isaac Sim's asset library), `stage_open.py` (open_scene's checks before Kit closes the open stage, its sequence, its limits and its answer), `extensions.py` (whether an extension the bridge needs is on, can be turned on, or is absent), `debug_draw.py` (draw_debug's shapes as segments, its colours, and the book of drawings still due), `recording.py` (start_recording's request, the camera check, which updates take a frame and its number, and deleting a camera feed's render product from every layer), `serial.py`, `layers.py` (the files the open stage has loaded, which flatten_usd and export_prim_as_file refuse to write, and the layers Kit holds that they read again from disk), `xform.py` (every transform the bridge writes, into a prim's own xform ops, refused when it couldn't show, and a camera's aim, in the layer that holds its ops: Kit's session layer for Kit's own cameras), `deletion.py` (whether delete_prim can take a prim off the stage, from its composition arcs, and why not), `usd.py` (typed forms of pxr calls the stubs get wrong) |
| `ovmcp/bridge/handlers/` | Handler package: split into focused modules (camera, scene, scene_open, simulation, recording, robot, debug_draw, misc, usd_advanced, logging) with shared utilities in `_utils.py` (among them `enable_extension` and the capture to a file, `capture_file_png`, with `capture_feed_png` on it), `camera_feed.py` (a camera rendered at a size in a texture of its own, for a recording or a capture, with a capture's segmentation and its release) and `_mcp_bridge.py` |
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
`protocol` and `extension_version` as well, for people. A route the extension lacks, such as an older one's for a new
tool, answers 404 `Unknown endpoint`, and `bridge_call` adds that the extension is older than this MCP server, with
the install command; a new route leaves `PROTOCOL` alone, so the other tools go on working.

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
/scene/open          -> handle_open_scene
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
- `format_scene_dump()` - Recursively format an entire scene tree, with the number of prims written
- `format_scene_tree()` - get_scene_tree's text: path, type and position down to max_depth, a prim there with its count
  of children - `format_frame_state()` - Format a snapshot for recording

## Threading Model

1. The HTTP server runs on the Omniverse application's asyncio event loop
2. Handlers use `await omni.kit.app.get_app().next_update_async()` to sync with the main thread before accessing USD/PhysX state
3. Script execution (`execute_script`) runs `exec()` directly on the main thread with stdout/stderr captured via `io.StringIO`. It must run on the main thread because USD/Omniverse APIs are not thread-safe. If the code contains `await` expressions, it is automatically wrapped in an async function and awaited, allowing scripts to call async `mcp.*` methods while still running on the main thread's event loop
4. A capture waits for its feed's frames, then its file, and a settle for the viewport's frames, each wait bounded by time (`ovmcp/core/capture.py`): `asyncio.wait_for` and polls on the same loop, no thread, so a camera or a viewport that renders nothing fails the call rather than hanging it. A viewport frame wait observes Kit's `NEW_FRAME` event through omni.usd's `next_frame_async`, as an immediate observer, which Kit 110's own code says may fire on the renderer thread with async rendering. Isaac Sim's headless Python app renders synchronously (`asyncRendering = false`); its GUI renders asynchronously whenever the simulation is stopped or paused, since `isaacsim.core.throttling` (`enable_async = true` in `isaacsim.exp.full.kit`) turns async rendering on at startup and a few updates after each stop or pause, and off on play. On Isaac Sim 6.2 headless with async rendering turned on the same way, every `NEW_FRAME`, immediate or deferred, and every `DRAWABLE_CHANGED` came on the main thread (#57); the GUI itself, and other Kit apps such as USD Composer, are untested
5. The bridge hands Kit's logging no Python callback. Kit runs one on whichever thread logs, and a physics worker that
   logged waited for the GIL that the main thread held while it waited for the worker, so Kit hung
   ([#5](https://github.com/serionist/omniverse-mcp/issues/5)). `get_logs` reads Kit's log file on the main thread
   instead; `tests/test_logs.py` fails on any Python hook on Kit's logging in the extension
6. A camera feed (`handlers/camera_feed.py`), a recording's or a capture's, hears of each frame through a Python callback on its
   texture's drawable-changed event. On Kit 110 Kit calls it on the main thread in every timeline state (#25's
   E16); on Kit 107, whose event stream is another, nobody has measured. So it does no USD work and logs nothing, as
   #5 asks of a callback Kit may call from another thread: it only hands the frame to the captures waiting for it

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
viewport = await mcp.capture_viewport(width=1280, height=720)
bounds = await mcp.prim_bounds("/World/Cube")
await mcp.set_camera([5, 3, 5], target=[0, 0, 0])
result = bounds["result"]["center"]
```

**Async detection**: The execute handler tries to `compile()` the code. If it fails with SyntaxError (due to top-level `await`), it wraps the code in `async def __mcp_exec__():` and awaits it. This means sync scripts work exactly as before, and async scripts "just work" when they use `await`.

## Recording System

A recording renders its camera at its size through a camera feed of its own, so the user's viewport, its camera and
its size never change (#25):

1. **Start** checks the request (`core/recording.py`; a side up to 4096) and the camera: `camera_path`, or the active
   viewport's camera, must be a `UsdGeom.Camera`. It makes a `CameraFeed` (`handlers/camera_feed.py`): a texture from
   Kit's public `omni.kit.hydra_texture.create_hydra_texture`, rendering every update while the recording runs, as
   Replicator makes its render products but with no annotator, so Replicator's orchestrator, its capture settings and
   the timeline are left alone. It waits for the feed's first frame (`capture.FRAME_SECONDS`), then subscribes to the
   app's update stream.
2. **Each update,** `FrameClock` decides whether to take a frame: every `steps_per_frame` updates (the timeline's time
   codes a second over `fps`), unless the feed still awaits the last frame's render or four frames are still being
   written. A frame gets its number, its `sim_time` and the tracked prims' state (appended to `state.txt`) at its tick,
   so numbers never repeat (#69) and the state matches the time.
3. **A frame** is taken as the viewport's are: a `FileCapture` delegate queued on the feed is handed the feed's next
   drawable-changed frame (Events 2.0 since Kit 108.2, an event stream before), and `capture_feed_png` waits for the
   whole PNG (`capture.capture_png`). One that doesn't come in time is written as an empty file, keeping the numbers.
   Its image shows the simulation within one update of its tick.
4. **Frames stop** when the stage starts to close, another stage opens, or the camera goes: the feed would go on
   rendering something else (white for a deleted camera, the new stage's default camera after a new stage). Frames in
   flight end at once as empty files, and `stop_recording` and `get_sim_state` say why.
5. **Stop** drops the subscription, awaits the frames in flight, drops the feed, deletes its render product, and writes
   `metadata.json`, each step on its own so one that fails leaves the rest done. Kit writes a texture's render product
   into the root and session layers, whatever the edit target, and lists it in `/Render/OmniverseGlobalRenderSettings`'s
   `products`; both stay after the texture goes, so `camera_feed.discard` deletes them from every layer of the stage
   open then, or of the next one once it opens.

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

## Opening a Stage

`open_scene` (`handlers/scene_open.py`, its sequence in `core/stage_open.py`) opens a USD file through the USD
context's own open. Kit closes the open stage before it reads the file, so a file that fails to load leaves no stage
at all, as Kit's File > Open does. Everything that can refuse runs first (#79):

1. **Checks, the open stage untouched:**
   - the path rule, `create_robot`'s (`core/usd_files.py`), with Isaac Sim's asset root from
     `get_assets_root_path_async`, which doesn't stop Kit's loop as `get_assets_root_path` does;
   - `Usd.Stage.IsSupportedFile`, and no other open under way;
   - `omni.client.stat_async`, which must answer `OK`; `ERROR_NOT_SUPPORTED` passes under the asset library's root
     alone, as Isaac Sim's own check takes it;
   - a local file's header, through `Sdf.FileFormat.CanRead`, which a Git LFS pointer fails.

   The root and the stat share 20 s (`STAT_SECONDS`).
2. **The timeline stopped,** then an update, as Kit's File > Open does.
3. **The state read again,** and nothing awaited from there until `open_stage_with_callback` starts Kit's open, so no
   other request starts one in between. Kit refuses a second open itself, with `UsdContext busy`.
4. **The open,** waited for up to 80 s (`OPEN_SECONDS`), which leaves 20 s of the client's 120 s. Kit's loop runs
   during it, so another client's request meanwhile finds no stage. An open past 80 s goes on in Kit after the error.
5. **The answer,** two updates later, so the recording's and the drawings' update handlers have seen the new stage:
   the path handed to Kit, the stage it replaced, and the stage's axis, units, default prim and prim count, read as
   `/sim/state` reads them. A failed open's error follows the state after it: another open under way, no stage, or
   the stage open now.

Unsaved changes aren't asked about: on Isaac Sim 6.2, `has_pending_edit()` reads true after every new stage, open and
save, since Kit writes its own render settings into the root layer, so it can't tell a user's edits from Kit's.

## Robot System

The robot tools use a hybrid approach:

- **`create_robot`** loads a named robot from Isaac Sim's asset library, or a USD file, as a USD reference
  (`core/usd_files.py` says from where)
- **`get_robot_info`** traverses the USD hierarchy to find joints, reading types and limits from USD properties
- **`get_joint_states`** finds the articulation root as `get_robot_info` does (`core/robot.py`), then reads it
  through Isaac Sim's `isaacsim.core.experimental.prims.Articulation`, a new one per call, while physics plays or is
  paused; it never loads physics itself
- **`set_joint_targets`** sets USD drive target attributes directly, which works without articulation initialisation

## Viewport Capture

`capture_viewport` and `inspect_prim` render their camera at the size asked for through a camera feed made for the
call (`handlers/camera_feed.py`, as a recording's is, [Recording System](#recording-system)): a texture of the
camera at `width` x `height`. The image, the screen boxes and the instance segmentation all come from that feed, so
they are the camera's, at that size, and agree to a pixel (#51); before, the image and the segmentation were the
viewport's at its own size, and the boxes were scaled to the size asked for.

- **The image:** `capture_feed_png` in `handlers/_utils.py` hands a capture delegate the feed's next frame, then reads
  the file once the PNG is whole (`ovmcp.core.png.is_complete_png`), since on Kit 110 the capture reports done before
  the file is written. The answer's `width` and `height` are the image's own, from its PNG header; it is
  base64-encoded and sent in the HTTP response to the MCP server, which saves it as a PNG file.
- **The boxes:** projected with `omni.syntheticdata`'s `get_view_params` and `world_to_image`, which read a feed's
  `camera_path` and `resolution` as they read a viewport's, so they come from the camera captured, in the image's
  pixels.
- **The segmentation:** from the sensor turned on for the feed's render product when the feed is made
  (`enable_segmentation`), coloured in one pass (`core/capture.py`'s `colour_instances`).
- **The viewport:** never touched. `inspect_prim`'s orbit moves the viewport's camera, as the user sees, and the feed
  renders that camera; `capture_viewport` with a `camera_path` renders that camera without switching the viewport to
  it. A request without a size takes the viewport's resolution.

**Fresh frames:** a feed's first frame comes some 15 updates after it is made, so a drawing or a change made just
before the call is in the image, with either debug drawing extension (#51's E19), where a capture of the viewport
took the next frame it delivered, rendered about 3 updates before, and had to let frames pass first (#57). Path
Tracing renders `settle_frames` more, until it has all its samples (none more with Isaac Sim's 64 a frame). After a
camera move, each `inspect_prim` angle waits 20 of the feed's frames: the move shows from the third.

**Releasing a feed:** `omni.syntheticdata` keeps the graph it makes under the feed's render product in a registry,
and one left there when the render product goes makes Kit log `Invalid object in Py_Graph` on every update until the
next stage (#51's E16). So `release` runs, each step on its own so one that fails doesn't stop the rest: the sensor
off, the feed dropped, each registry graph under the render product popped and reset (`SyntheticData._nodeGraphs`
and `_reset_node_graph`, private, as Replicator's own render product teardown uses them) under the session layer, two
updates, then the render product deleted from every layer and from `/Render/OmniverseGlobalRenderSettings.products`,
now or, during a stage change, once a stage is open. A Kit whose `omni.syntheticdata` has no such registry gets no
segmentation, said in `segmentation_error`, rather than a leak. While a call runs its render product is in the stage,
and Kit marks the stage as edited, as it does when the viewport switches camera.

**Cold start:** the first capture after the app starts can come back black while the renderer warms up. A black
frame is reset and captured once more by itself, after 20 more of the feed's frames (`_capture_frame` in
`handlers/camera.py`); if it is still black, the answer says so, with the lighting mode.

**Every wait has a time limit** (`ovmcp/core/capture.py`; each limit is read when its wait runs):

| Wait | Limit |
|---|---|
| one frame of a capture's feed (its first, each of an angle's 20, a renderer reset's, and the capture's own `wait_for_result`), or of the viewport (each of a settle's 20) | 30 s (`FRAME_SECONDS`) |
| the file, after the frame | 10 s (`FILE_SECONDS`) |
| instance segmentation's first data after the sensor is enabled, read after each app update; after a wait that got nothing with this camera and size on this stage, until one gets data | 5 s (`SEGMENTATION_SECONDS`); 1 s (`SEGMENTATION_RETRY_SECONDS`) |
| an `inspect_prim` or `capture_viewport` call | 80 s (`CALL_SECONDS`), then 10 s (`CLEANUP_SECONDS`) for the settle after `isolate` |

- **Fails at once:** a capture whose `wait_for_result` names nothing captured (`[]` or `None`): no file will come.
- **Frame by frame:** a feed's frames are counted from its drawable-changed event (`CameraFeed.wait_frames`). A
  settle of the viewport waits through `next_viewport_frame_async`, one frame at a time (`_next_frame` in
  `handlers/_utils.py`), not `ViewportAPI.wait_for_rendered_frames`, which counts its subscribe call as a frame and
  leaves a cancelled wait's callback in the viewport. A Kit without the frame event pumps an app update for each
  frame instead, with a warning the first time.
- **A call stops:** in `inspect_prim`, a frame that never comes (`NoFrameError`, naming the camera) or the call's time
  running out (`OutOfTimeError`) stops the call, and the angles left are `Not captured`; after `NoFrameError`, the
  restore after `isolate` doesn't wait for frames. Any other error is its angle's alone.
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
- **In Kit's log:** a failed capture's step and seconds (a warning); a capture over 2 s, how long its frame and file
  took; each segmentation wait's updates and seconds; a feed release step that failed. `get_logs(search="capture")` and `search="segmentation"` find the
  bridge's lines; `channel="syntheticdata"` finds what `omni.syntheticdata` itself reported, whose lines rarely name
  it.

**Segmentation:** each capture turns the sensor on for its own feed, whose first data comes a frame or two later, and
reads it after each app update for up to 5 s, counting data only at the feed's size. An answer without segmentation
says why in `segmentation_error`. After a wait that got nothing, the next capture of that camera at that size on that
stage waits 1 s, until a read gets data, so `capture_viewport` doesn't pay 5 s on every call.

## Extension Lifecycle

- **on_startup**: Creates the HTTP server, binds to configured host:port, registers all routes. Enables the `omni.syntheticdata` instance segmentation sensor on the viewport once it exists; captures, which render through feeds of their own since #51, turn it on for each feed instead ([Viewport Capture](#viewport-capture))
- **on_shutdown**: Stops any active recording, cancelling its frames and dropping its camera feed, and drops the debug
  drawing subscription and its book (deleting and clearing nothing: the stage may be tearing down; a recording's
  render product stays on a stage that outlives the extension), clears caches, closes the HTTP server

The extension includes:
- **Content-Length validation**: Rejects request bodies over 100 MB
- **Connection limiting**: 20 handler slots, so at most 20 requests run at once
- **Health endpoint**: `GET /health` returns server status with error wrapping

The extension can be enabled/disabled from the application's extension manager (Window > Extensions). Disabling it stops the HTTP server; re-enabling restarts it.
