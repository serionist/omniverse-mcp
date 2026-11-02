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
| `scene.py` | Scene graph: tree (listed, or dumped by Kit to a file), properties, bounds, transform, create, delete, material, clone, visibility, save, open, new |
| `camera.py` | Viewport: capture, set camera (at a point or a prim), inspect (orbit), viewport light |
| `robot.py` | Robot: create, info with the joint states, joint targets |
| `simulation.py` | Sim control, state, physics properties, apply force, raycast, debug draw |
| `recording.py` | Recording: start, stop, get frame |
| `sweep.py` | capture_sweep: the shots, or a shots file the server reads, sent as a job |
| `usd_advanced.py` | Mesh stats with the face count tree, flatten, export, variants, compare, material paths |
| `misc.py` | execute_script, run_script_job, get_job, cancel_job, manage_extensions, get_logs |

### Output management

The output folder is `mcp_output/` in the server's working directory, or `--output-dir`, made by the first file
written there, not at start. A file under the working directory is given by its relative path, any other by its
absolute path (`Helpers.rel`).

- **Images:** the bridge sends each capture as base64 PNG, and the server writes it to `captures/`.
  `capture_viewport(include_image=True)` also returns it inline as `ImageContent`.
- **Long text:** an answer over 1,000 characters goes to `responses/`. `get_mesh_stats`, `get_robot_info` and
  `get_job` write only their long part there (`Helpers.write_response`), the tree, the Joints list and the joint
  states that don't fit, or a job's lines, output, traceback and long result, and keep the rest inline: the totals,
  the counts and the joint states that fit, or the job's state, time, last line, count of lines and error.
- **Scene dumps, recordings and sweeps:** Kit writes them itself, to the path the server passes, so with Kit on
  another machine they land on that machine. Each recording gets a timestamped folder in `recordings/`, each
  sweep the folder its name gives in `sweeps/`.

This keeps the MCP context window clean - the AI reads files on demand rather than receiving megabytes of scene data inline.

### HTTP Client

`client.py` implements a custom HTTP/1.1 client (no external `requests` dependency) with:

- Persistent keep-alive connections
- The bridge token on every request (see [The bridge token](#the-bridge-token)), read again after a 401
- A handshake, `GET /bridge`, at the start of every new connection; an extension of another protocol is refused
  with the command that installs this server's: `uvx omniverse-mcp==X.Y.Z extension install`, or from a checkout
  `uv run --project <checkout> omniverse-mcp extension install`, and, for an extension from Kit's community
  registry, the version to install in Kit's Extensions window (`kit_extension.install_advice()`)
- Automatic reconnection on failure (1 retry, 2 total attempts)
- A 120-second timeout on each request; the bridge's capture calls answer within about 90 s, under it
  ([Viewport Capture](#viewport-capture))
- A Kit that stopped answering named in 5 s (#114): when a request's connected socket times out, `GET /health` on a
  connection of its own gets 5 s (`HEALTH_SECONDS`). Any answer, a refusal too, means Kit's loop runs, and the timeout
  stands as it is. No answer raises `KitSilentError` and marks the client, under its lock, so each later request asks
  `/health` first and fails the same way at once while Kit stays silent; the mark clears once `/health` answers. A
  connect that times out is a host that is down, and keeps its error. `tools/_bridge.py` adds what it may mean: a long
  script without an await, which holds `/health` back too, or Kit hung in NVIDIA's renderer, and when to restart it
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
- **Kit's community registry** is the other way in. Each release also attaches the extension's zip under the two
  names the registry's crawler reads (`tools/release.py archives`, which checks the layout: everything under
  `ovmcp.bridge/`). Kit downloads a listed version from its release into its own cache and links it into its
  registry folder, where `extension install`'s folder never reaches. Turning the extension on in a running Kit
  doesn't download it, the Extensions window's **Install** does; a start with `--enable` wasn't tried.
  `[package.target] kit` keeps it from Kit apps before 107.

### Key files

| File | Purpose |
|------|---------|
| `ovmcp/bridge/extension.py` | Kit lifecycle: makes the token, starts the core's HTTP server with the routes |
| `ovmcp/core/` | Kit-free core, unit-tested on usd-core and numpy without Kit, typed in strict mode; import-linter keeps `omni`, `carb`, `isaacsim` and `ovmcp.bridge` out of it: `http.py` (HTTP server, token and browser checks, routing), `token.py` (the token file), `protocol.py` (the handshake, and the Kit app's name, versions and OS), `formatter.py` (the prim-block text), `bounds.py` (world boxes and their outline on screen), `capture.py` (the capture path's waits, each bounded by time, a call's bookkeeping, the frame-size limit, 4096 a side, for start_recording, capture_viewport and inspect_prim, Path Tracing's settle frames, and segmentation's colours), `png.py` (the PNG writer), `logs.py` (Kit's log file read into the log ring, and its query), `force.py` (apply_force's request, its refusals and the point it pushes at; from the stage's joints, the articulation a body is a link of and the fixed joint that holds it to the world; for the push through PhysX's tensor API, which the handler takes while `/physics/suppressReadback` is on: the physics scene's step length, an impulse as one step's force, and the centre of mass from the tensor API's rows), `framing.py`, `isolation.py`, `lighting.py`, `collision.py` (set_physics_properties' collision: the shapes PhysX collides and the refusals for the rest, the rigid body a collider moves with, a moving Mesh's convex hull, and the echo), `material.py` (set_material's OmniPBR, named by its MDL source; set_physics_properties' physics material: its path, a child of the prim, and its refusals; the values a body has, and what the material it binds copies from the one it replaces; one walk of the stage's bindings, for the other prims a write changes and the older shared material it deletes once nothing binds it), `robot.py` (whether create_robot was given a file or a name, its prim's name; the articulation root whose joint states get_robot_info reads), `metrics.py` (a referenced file's up axis and units brought to the stage's, for create_robot and create_prim: the turn that stands a file of another up axis upright, and the scale and the converted values that bring a file of other units to the stage's), `usd_files.py` (where a USD file a tool is given loads from: a URL, a file on Kit's machine, Isaac Sim's asset library), `stage_open.py` (open_scene's checks before Kit closes the open stage, its sequence, its limits and its answer; new_scene's up axis and units, checked before Kit discards the open stage), `extensions.py` (whether an extension the bridge needs is on, can be turned on, or is absent), `debug_draw.py` (draw_debug's shapes as segments, its colours, and the book of drawings still due), `recording.py` (start_recording's request, the camera check, which updates take a frame and its number, and deleting a camera feed's render product from every layer), `exposure.py` (what the edit target held of a camera's exposure before RTX wrote onto it, for each camera a feed renders through, put back exactly when the last feed through it goes), `serial.py`, `layers.py` (the files the open stage has loaded, which flatten_usd and export_prim_as_file refuse to write, the layers Kit holds that they read again from disk, and the open stage without Kit's session layer, which they flatten), `xform.py` (every transform the bridge writes, into a prim's own xform ops, refused when it couldn't show, and a camera's aim, in the layer that holds its ops: Kit's session layer for Kit's own cameras), `deletion.py` (whether delete_prim can take a prim off the stage, from its composition arcs, and why not), `variants.py` (a prim's variant sets and the layer holding each selection; set_variant_selection's and compare_prims' switch in one layer, the session layer by default, refused whole before anything is written, and its snapshot, which puts that layer back field by field; the session layer's selections save_scene leaves out), `script.py` (a script compiled for /execute and a job, told awaiting or plain, and run as a function of its namespace), `output.py` (the router over sys.stdout and sys.stderr that sends a task's prints to its call's or its job's sink), `jobs.py` (the job board: one job at a time, its states, lines, cancel, wait and shutdown), `sweep.py` (capture_sweep's shots, read and checked before anything changes, a manifest's read back as the shots it rendered; a lens fitted to the image; a pose from a yaw and pitch on either up axis; the selections to write before a shot, each set it doesn't name back to its starting session value; the switch, a block included; the timeline's start; the manifest and the summary line), `usd.py` (typed forms of pxr calls the stubs get wrong) |
| `ovmcp/bridge/handlers/` | Handler package: split into focused modules (camera, scene, scene_open, simulation, recording, robot, debug_draw, misc, jobs, sweep, usd_advanced, logging) with shared utilities in `_utils.py` (among them `enable_extension` and the capture to a file, `capture_file_png`, with `capture_feed_png` on it), `variants.py` (the viewport's refresh after a variant switch: with Fabric Scene Delegate on before Kit 110, the switched prims made inactive in the session layer for some updates, and that layer put back in a `finally`), `camera_feed.py` (a camera rendered at a size in a texture of its own, for a recording or a capture, with a capture's segmentation and its release, and the capture feed kept between calls with the viewport lock, lent to a recording or a sweep at its size; what RTX writes onto its cameras put back with its render product) and `_mcp_bridge.py` |
| `config/extension.toml` | Extension metadata and default settings |

### HTTP Server

The extension runs an asyncio HTTP server on the application's event loop (same pattern as the built-in Jupyter extension). This is important - it shares the event loop with Kit, so handlers can use `await omni.kit.app.get_app().next_update_async()` to synchronise with the main thread.

### The bridge token

`/execute` and `/jobs/script` run any Python inside the app, so the bridge answers only a client that holds its token.

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
`protocol` and `extension_version` as well, for people, and the Kit app as `/sim/state` does: `kit_app_name`,
`kit_app_version`, `kit_version` and `kit_os`, read once when the extension starts. A route the extension lacks, such as an older one's for a new
tool, answers 404 `Unknown endpoint`, and `bridge_call` adds that the extension is older than this MCP server, with
the install command; a new route leaves `PROTOCOL` alone, so the other tools go on working.

### Request routing

`extension.py` maintains a routes dictionary mapping URL paths to handler functions:

```
/health              -> handle_health
/execute             -> handle_execute
/jobs/script         -> handle_job_script
/jobs/get            -> handle_job_get
/jobs/cancel         -> handle_job_cancel
/jobs/sweep          -> handle_sweep_start
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
/scene/attribute     -> handle_set_attribute
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
/sim/performance     -> handle_performance
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
- `format_scene_dump()` - get_scene_tree's dump, with properties or a filter: a scene subtree's blocks to max_depth,
  with the number of prims written
- `format_scene_tree()` - get_scene_tree's text: path, type and position down to max_depth, a prim there with its count
  of children
- `format_frame_state()` - Format a snapshot for recording

## Threading Model

1. The HTTP server runs on the Omniverse application's asyncio event loop
2. Handlers use `await omni.kit.app.get_app().next_update_async()` to sync with the main thread before accessing USD/PhysX state
3. A script, `execute_script`'s or a job's, runs on the main thread, on its handler's or its job's own task, since USD
   and Omniverse APIs are not thread-safe. `ovmcp/core/script.py` compiles it once with
   `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`, as the standard library's asyncio REPL does, and runs its code as a function of
   the script's namespace, awaited when the compiler made it a coroutine: a script that awaits, `await mcp.*` among
   them, gives Kit's loop back at each `await`. Its lines keep their numbers, and a multi-line string stays whole. A
   top-level `return`, which the compiler refuses there, still runs, inside a coroutine function built from the
   script's own syntax tree. Its prints go to its call's or its job's sink through `ovmcp/core/output.py`: one router
   over `sys.stdout` and `sys.stderr`, a context variable naming the sink of the task printing, so what another
   handler, call or job prints meanwhile stays out of it, and it reads as no terminal, so no library writes colour
   codes into it. A thread, or a task with no sink, prints to the stream beneath, Kit's console; a sink closes when
   its call ends, so a task a script left running prints there too. A script that replaces `sys.stdout` or
   `sys.stderr` gets the router back at its call's end, as the old swap put Kit's stream back
4. A capture waits for its feed's frames, then its file, and a settle for the viewport's frames, each wait bounded by time (`ovmcp/core/capture.py`): `asyncio.wait_for` and polls on the same loop, no thread, so a camera or a viewport that renders nothing fails the call rather than hanging it. A viewport frame wait observes Kit's `NEW_FRAME` event through omni.usd's `next_frame_async`, as an immediate observer, which Kit 110's own code says may fire on the renderer thread with async rendering. Isaac Sim's headless Python app renders synchronously (`asyncRendering = false`); its GUI renders asynchronously whenever the simulation is stopped or paused, since `isaacsim.core.throttling` (`enable_async = true` in `isaacsim.exp.full.kit`) turns async rendering on at startup and a few updates after each stop or pause, and off on play. On Isaac Sim 6.2 headless with async rendering turned on the same way, every `NEW_FRAME`, immediate or deferred, and every `DRAWABLE_CHANGED` came on the main thread (#57); the GUI itself, and other Kit apps such as USD Composer, are untested
5. The bridge hands Kit's logging no Python callback. Kit runs one on whichever thread logs, and a physics worker that
   logged waited for the GIL that the main thread held while it waited for the worker, so Kit hung
   ([#5](https://github.com/serionist/omniverse-mcp/issues/5)). `get_logs` reads Kit's log file on the main thread
   instead; `tests/test_logs.py` fails on any Python hook on Kit's logging in the extension
6. A camera feed (`handlers/camera_feed.py`), a recording's or a capture's, hears of each frame through a Python callback on its
   texture's drawable-changed event. On Kit 110 Kit calls it on the main thread in every timeline state (#25's
   E16); on Kit 107, whose event stream is another, nobody has measured. So it does no USD work and logs nothing, as
   #5 asks of a callback Kit may call from another thread: it only hands the frame to the captures waiting for it
7. What runs on every app update, a recording's tick, the drawings' watch, the watch over a dropped feed's render
   product and `get_performance`'s measurement, observes Kit's update event (`omni.kit.app.GLOBAL_EVENT_UPDATE`) through Events 2.0, by
   `handlers/_updates.py`'s `on_update`, as Kit's own `next_update_async` does in Kit 107 and Kit 110. Its order is 0,
   where the app's update stream ran its subscriptions: after USD's update and the physics step (-10), before Hydra's
   render (30), `next_update_async` (50) and the asyncio loop that runs the handlers (100), as Kit's `KitUpdateOrder.h`
   orders them. On Isaac Sim 6.2 headless every call came on the main thread, a texture's drawable-changed event before
   it in the same update, and Kit called an observer again after it raised (#122). The app's event streams log a
   deprecation, with a call stack, at each call; `tests/test_updates.py` fails on any in the extension
8. `get_performance` (`handlers/performance.py`) times the app updates it observes, at order 0, so a physics step's
   profile stats, which PhysX's benchmarks interface sends with the step at -10, come before the update's own call:
   the measurement counts the steps of the updates whose intervals it keeps. Their callback only adds numbers up, as
   point 5 asks of one Kit may call from another thread. It lifts Kit's frame-rate limiter
   (`/app/runLoops/main/rateLimitEnabled`) while it measures, when it is on, and puts it back in a `finally`, and
   holds the viewport lock with the kept capture feed released (`without_kept_feed`), since a kept feed renders every
   update; the call's 90 s count from the call, so a wait for that lock is said as such when it spends them

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

**Async detection**: the compiler's own flag (`inspect.CO_COROUTINE` on the code `ovmcp/core/script.py` compiles with
top-level `await` allowed) says whether a script awaits; one that does is awaited on the handler's task, so `await`
"just works" and the script's lines keep their numbers ([Threading Model](#threading-model)). A job's script gets the
same names.

## Jobs

A job is long work that runs on Kit's loop as a task of its own (`ovmcp/core/jobs.py`, `handlers/jobs.py`), so Kit
renders, physics steps and other requests are answered between its `await`s, and it outlives the request that
started it (#158). `run_script_job` starts a script as one; `capture_sweep` a capture sweep, another kind, through
the same board and routes ([Capture Sweep](#capture-sweep)).

- **Start:** `/jobs/script` takes `code` or `file`, a `.py` on Kit's machine read as bytes and compiled with its path,
  so its encoding follows Python's source rules and its tracebacks show its lines. A script that never awaits at
  its top level is refused before it starts: its loops would hold the main thread from its start to its end, whatever
  ran it, and a coroutine it only defines or schedules would run where no route reaches it. The job starts
  with `asyncio.ensure_future`, and the route answers its id, `j1` and on, at once. One job at a time: a second start
  is refused, naming the one running.
- **States,** as an MCP task's: `working`; `cancelling`, from a cancel until the job's own cleanup has returned, which
  holds the slot, so a sweep that puts the stage back finishes first; `completed`, `failed`, `cancelled`, with a
  status message. The last job is kept, for `/jobs/get`, until the next starts.
- **Lines:** what the job's task, and the tasks it starts, print is its progress (`ovmcp/core/output.py`): both
  streams in order, the last 200 kept with a count of all, a line redrawn with a carriage return as its latest
  state. Each `/jobs/get` gives the lines since the last read, and
  once the job ends, each stream's last 200 lines and the result in its kind's shape (a script's `return_value`), or
  the error and traceback.
- **`/jobs/get`'s `wait`,** up to 100 s, under the server's 120 s for a call, returns early only on the job's end or a
  change of its state: new lines alone don't end it.
- **Cancel:** `/jobs/cancel` calls `task.cancel(reason)`, so the job's code gets `CancelledError` with the reason at its
  next `await` and its cleanup can tell a user's cancel from a stage change. A second cancel cancels again, for code
  whose bare `except:` swallowed the first.
- **The stage,** for a job started with `watch_stage`: cancelled with the reason when the stage's id changes or the
  stage begins to close, read on each update as a recording's frames are, which also catches a stage opened from
  Kit's menu or a script. A script job doesn't watch: a bake may open stages itself.
- **What a job can't do:** a script that awaits once and then loops, or calls Isaac Sim's `world.step()`, holds the
  main thread as a blocking `/execute` does, and `/jobs/get` runs on the same loop, so nothing reads the job until it
  ends. Kit's restart ends a job.

## Capture Sweep

`capture_sweep` (#157) captures a list of shots as a job of kind `sweep` (`ovmcp/core/sweep.py`, `handlers/sweep.py`),
read and cancelled through `/jobs/get` and `/jobs/cancel`. Each shot is a pose (a position with a yaw and pitch about
the stage's up axis, a position and a target, or a `camera_path`), a lens, the variant selections it shows and a
timeline time. Kit writes the PNGs and `manifest.json` into `<output>/sweeps/<name>/`, as it writes a recording's
frames.

1. **Start:** `/jobs/sweep` takes the shots (a list, or a sweep's manifest, whose entries read back as the shots they
   rendered), the size, and the output root and the name apart, so the name is checked as one plain folder name
   before it is joined to anything. It checks every shot, each selection of a prim and set on the stage now
   (`variant_refusal`), that no camera is defined at `/OmniverseKit_Sweep` (RTX's over there, in the root layer
   until the kept feed's render product goes, blocks nothing) and that the folder holds no manifest, then starts the
   job with `watch_stage` and a teardown, and answers its id and folder.
2. **The job's start:** it reads the timeline's state and time and each named (prim, set)'s session-layer value,
   defines its camera, `/OmniverseKit_Sweep`, in the session layer with Isaac Sim's clipping range (0.01 m to 1e7 m in
   stage units), writes the manifest at once, and borrows the captures' feed (`lend`), as a recording does.
3. **Each shot,** holding the viewport lock for that shot alone, at most 30 s (`SHOT_SECONDS`), so a capture called
   meanwhile runs between shots: the selections that differ from those last written, each set a shot doesn't name
   going back to its starting value, absent, blocked or named, through #155's `switch` in the session layer, its
   snapshots kept, a block through the block helper; `refresh`; a wait of up to 20 s for the stage to finish loading
   (`get_stage_loading_status`); the shot's time (a playing timeline paused, a stopped one left stopped) or the
   start's state and time back; the sweep's camera aimed in the session layer and its lens and clipping range set, or
   a `camera_path` checked after the switch and rendered as it is, its world pose and lens recorded; 20 of the feed's
   frames, `_capture_frame`, and the PNG. A failed shot is recorded with why; a feed that rendered no frame in a shot's
   time ends the sweep. Every 25 shots a line and the manifest again.
4. **The end,** whatever ends it, each step on its own: the feed pointed at the viewport's camera, every snapshot
   restored, last first, in one change block, the timeline put back and the sweep's camera deleted, unless the stage
   changed or began to close, which took its layers with it; then the manifest and the summary line, the job's last;
   then the feed handed back (`hand_back`). What RTX wrote onto the cameras the feed rendered through comes back with
   its render product, as a capture's does (#177). At the extension's shutdown the teardown does the same at once,
   the feed let go (`let_go_now`).

## Recording System

A recording renders its camera at its size through a camera feed, so the user's viewport, its camera and its size
never change (#25):

1. **Start** checks the request (`core/recording.py`; a side up to 4096) and the camera: `camera_path`, or the active
   viewport's camera, must be a `UsdGeom.Camera`. It borrows a `CameraFeed` (`handlers/camera_feed.py`'s `lend`,
   [Viewport Capture](#viewport-capture)): the feed the captures keep when it is the recording's size, its camera
   set, so no new RTX view is set up (#141); else a new one, which leaves the kept one on its clock. A feed is a
   texture from Kit's public `omni.kit.hydra_texture.create_hydra_texture`, rendering every update, as Replicator
   makes its render products but with no annotator, so Replicator's orchestrator, its capture settings and the
   timeline are left alone. The start waits for the feed's first frame (`capture.FRAME_SECONDS`), then the 20 frames
   a capture waits after it sets the camera, and under Path Tracing the frames a capture waits for its samples
   (`capture.settle_frames`, none under RT 2.0), then observes the app's update event (Threading Model, point 7).
2. **Each update,** `FrameClock` moves the recording's own clock and decides whether to take a frame. The clock adds
   the simulation time the update advanced when the timeline's time moved forward, and the wall time since the update
   before otherwise (`time.monotonic`): stopped, paused, or a timeline that plays and doesn't move. It reads the time,
   not the timeline's state, so a `sim_control` step counts whole whichever side of Kit's timeline tick the update
   runs on. Frame k is due once it reaches k/`fps`; a due frame waits while the feed still awaits the last frame's
   render or four frames are still being written, and the next is due at the first period boundary after the clock,
   so late frames are dropped, not sent in a burst (#111). A frame gets its number, its `sim_time` and the tracked prims' state (appended to
   `state.txt`) at its tick, so numbers never repeat (#69) and the state matches the time. The clock's two totals are
   the stop answer's `simulation_seconds` and `idle_seconds`.
3. **A frame** is taken as the viewport's are: a `FileCapture` delegate queued on the feed is handed the feed's next
   drawable-changed frame (Events 2.0 since Kit 108.2, an event stream before), and `capture_feed_png` waits for the
   whole PNG (`capture.capture_png`). One that doesn't come in time is written as an empty file, keeping the numbers.
   Its image shows the simulation within one update of its tick.
4. **Frames stop** when the stage starts to close, another stage opens, or the camera goes: the feed would go on
   rendering something else (white for a deleted camera, the new stage's default camera after a new stage). Frames in
   flight end at once as empty files, and `stop_recording` and `get_sim_state` say why. The feed is torn down at once
   (`let_go_now`), as at Kit's Save: a capture may have left segmentation graphs on a borrowed one.
5. **Stop** drops the update observer, awaits the frames in flight, hands the feed back (`hand_back`), and writes
   `metadata.json`, each step on its own so one that fails leaves the rest done. The feed is kept for the next capture
   or recording when no other is kept, no frame failed and the stage is the one it started on; else released, its
   render product deleted. Kit writes a texture's render product into the root and session layers, whatever the edit
   target, and lists it in `/Render/OmniverseGlobalRenderSettings`'s `products`; both stay after the texture goes, so
   the release deletes them from every layer of the stage open then, or of the next one once it opens. A stop doesn't
   wait out a capture holding the viewport lock: it releases the feed instead; only a capture already queued as the
   lock frees goes first, and the stop waits for that one. After the extension's shutdown it keeps
   nothing.

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
2. While the book holds a drawing, one observer of the app's update event runs on the main thread (Threading Model,
   point 7): it drops drawings that expired or belong to another stage, then clears and draws the rest again, since
   `isaacsim.util.debug_draw`'s clear takes every line. `omni.debugdraw` forgets a line after a frame, so with it the
   book's lines are drawn on every update.
3. A clear waits for an update with the stage `OPENED`, never while it opens or closes, and the observer goes once
   nothing is left.

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
  (`core/usd_files.py` says from where), stands a file of another up axis upright with the turn Kit's metrics
  assembler writes, `xformOp:rotateX:unitsResolve`, and brings a file of other units to the stage's: Kit's scale,
  `xformOp:scale:unitsResolve`, and its values converted by the PhysX schema's table of units, which the handler
  imports (`pxr.PhysicsSchemaTools.units`) and the Kit-free core takes as an argument (`core/metrics.py`). Both are
  measured against the frame the robot lands in, which the `:unitsResolve` ops above it make; `create_prim` brings a
  `usd_path` file through the same core
- **`get_robot_info`** asks two routes. `/robot/info` traverses the USD hierarchy to find joints, reading types and
  limits from USD properties. `/robot/joint_states` then finds the first articulation root at or under the prim
  (`core/robot.py`) and reads it through Isaac Sim's `isaacsim.core.experimental.prims.Articulation`, a new one per
  call, while physics plays or is paused; it never loads physics itself, and its error, stopped or without Isaac Sim,
  is a line of the tool's answer
- **`set_joint_targets`** sets USD drive target attributes directly, which works without articulation initialisation

## Viewport Capture

`capture_viewport` and `inspect_prim` render their camera at the size asked for through a camera feed kept between
calls (`handlers/camera_feed.py`, as a recording's is, [Recording System](#recording-system)): a texture of the
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
- **The segmentation:** from the sensor turned on for the feed's render product by each call that asks
  (`enable_segmentation`), and off again as the call ends, coloured in one pass (`core/capture.py`'s
  `colour_instances`).
- **The viewport:** never touched. `inspect_prim`'s orbit moves the viewport's camera, as the user sees, and the feed
  renders that camera; `capture_viewport` with a `camera_path` renders that camera without switching the viewport to
  it. A request without a size takes the viewport's resolution.

**Fresh frames:** every capture waits 20 of its feed's frames after the call sets the feed's camera, a kept feed's
too, so a camera move, a drawing or a change made just before the call is in the image, with either debug drawing
extension (#51's E19), where a capture of the viewport took the next frame it delivered, rendered about 3 updates
before, and had to let frames pass first (#57). A kept feed has frames already, and the handler can't tell whether
the stage changed just before the call, so the wait is the same for every capture. Path Tracing renders
`settle_frames` more, until it has all its samples (none more with Isaac Sim's 64 a frame). After a camera move, each
`inspect_prim` angle waits 20 of the feed's frames: the move shows from the third.

**The kept feed (#114):** Kit 110 can hang for good during a new RTX view's first frames, its main thread looping
inside NVIDIA's renderer; a feed made for each call made a new view each call, and the hang came about once in 300 to
400 `inspect_prim` calls. So one feed is kept: `kept_feed` hands a call the kept feed, its `camera_path`, `width` and
`height` set in place on the texture and on the feed, or makes one; `put_back` hands it back at the call's end. Every
feed's render product is `ovmcp_feed_<id>`, whichever call made it.

- **Views:** a changed camera makes no new view (8,000 switches on one feed never hung); a changed size makes one, on
  the same render product. Any size is kept.
- **Recordings and sweeps (#141, #157):** `lend` takes the viewport lock and, when the kept feed is the recording's
  or the sweep's size, takes it off the slot with its camera set, so the stage's events, the timer and the saves leave it to the recording; at another
  size a recording gets a feed of its own and the kept one stays, since a resize would set up a view and the next
  capture at the old size another. `hand_back` at the stop keeps a healthy feed when none is kept and the stage is the
  one it started on, and releases it otherwise; when a capture holds the lock it releases rather than waits. A
  recording's frames stopping early, a start that fails and shutdown tear its feed down at once (`let_go_now`), the
  graphs a capture left freed first. A sweep borrows the feed for its length, aims it at each shot's camera, and
  hands it back at its end, or lets it go at shutdown, as a recording does.
- **Released:** 30 s after the last call (`IDLE_SECONDS`, a timer on Kit's loop whose release takes the viewport
  lock and checks a generation number, so one that fires as a call takes the feed does nothing); at once when a call
  leaves it in doubt (an error that escaped the capture, an angle's error, segmentation that raised or gave no data),
  so a stalled feed or a half-made sensor is never kept; by `release_kept()`, which the live tests call through
  `execute_script`.
- **The stage:** Kit's `CLOSING` stage event, observed on Events 2.0 (`stage_event_name` with `carb.eventdispatcher`,
  in Kit 107's `omni.usd` too), drops the feed and deletes its render product from the next open stage
  (`discard`, whose watch observes the app's update event until a stage is open: Threading Model, point 7);
  `omni.syntheticdata` resets its own graphs as the stage closes. A call also checks the stage is the one
  the feed was made on.
- **Saves:** Kit keeps a feed's render product in the root layer. `save_scene`, `flatten_usd` and
  `export_prim_as_file` take the viewport lock, release the kept feed in `release`'s order and hold the lock through
  their write (`without_kept_feed`). Kit's own Save sends `SAVING` synchronously before it writes, so the feed is torn
  down then in `release`'s order with no update between the steps, which a synchronous event can't wait for; measured
  quiet in #51's E16 windows (as it ran, 2 s after, a save, a new stage, a segmented capture after). A feed part way
  through `release`, already let go, waits in `_releasing` until its render product goes, so `SAVING` deletes that at
  once too: only the two updates were left. Two writes send no `SAVING` and write the render product while a feed is
  kept: a script that writes the root layer through USD itself, from `execute_script`, and Kit's File > Save
  Flattened As when it leaves the session layer out, which opens the root layer as a stage of its own and exports it
  (`omni.kit.window.file`'s `file_window.py`).
- **Segmentation:** on for the call that asks, off as it puts the feed back: left on, a kept 640x480 feed cost Kit
  110 updates a second while idle against 157 with it off and 183 with no feed. Its graphs stay until the feed goes.
- **Shutdown:** `forget` tears the feed down as at `SAVING`, its render product deleted while a stage is open, and marks
  the module shut down, so a recording's stop still under way keeps nothing.
- **Cost while kept,** idle, on headless Isaac Sim 6.2 and an RTX 5090: Kit's updates a second fell from 183 with no
  feed to 157 at 640x480, 153 at 1920x1080 and 69 at 4096x4096, its share of the GPU's 3D engine rose from 9 % to
  25 %, 28 % and 65 %, and it took about 0.3, 1.0 and 5.5 GB more video memory.
- **A call that meets a let-go feed:** a stage event or shutdown during a call drops the feed under it; its waits fail
  at once (`NoFrameError`), not after 30 s: a new feed's first frame, each next frame, and a capture already handed to
  the feed, whose result `CameraFeed.result_of` races against the feed being let go, since `drop` takes back the
  captures still waiting. `put_back` leaves the feed alone.

**Releasing a feed:** `omni.syntheticdata` keeps the graph it makes under the feed's render product in a registry,
and one left there when the render product goes makes Kit log `Invalid object in Py_Graph` on every update until the
next stage (#51's E16). So `release` runs, each step on its own so one that fails doesn't stop the rest: the sensor
off, the feed dropped, each registry graph under the render product popped and reset (`SyntheticData._nodeGraphs`
and `_reset_node_graph`, private, as Replicator's own render product teardown uses them) under the session layer, two
updates, then the render product deleted from every layer and from `/Render/OmniverseGlobalRenderSettings.products`,
now or, during a stage change, once a stage is open. A Kit whose `omni.syntheticdata` has no such registry gets no
segmentation, said in `segmentation_error`, rather than a leak. While a feed is kept its render product is in the
stage, and Kit marks the stage as edited, as it does when the viewport switches camera.

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
- **Outside a call:** `set_camera` and `viewport_light` give a settle or reset 30 s for all its frames, and answer as
  before, with a warning in Kit's log, when the frames don't come. A recording frame gets 30 s, then 10 s for its
  file, and is the empty marker when they run out.
- **Kit versions:** run live on Isaac Sim 6.2 (Kit 110) on Windows and Linux, and on Isaac Sim 5.1 (Kit 107) on
  Linux, where both live suites pass. 5.1 ran on NVIDIA's 580.178.04 driver; on 595.91.07 its RTX scene library
  crashed in its own start, before any extension loaded. 5.1 on Windows is untested.
- **Timers on Kit's loop:** they fire only while the loop runs, so a main thread blocked by a shader compile delays
  them.
- **In Kit's log:** a failed capture's step and seconds (a warning); a capture over 2 s, how long its frame and file
  took; each segmentation wait's updates and seconds; a feed release step that failed. `get_logs(search="capture")` and `search="segmentation"` find the
  bridge's lines; `channel="syntheticdata"` finds what `omni.syntheticdata` itself reported, whose lines rarely name
  it.

**Segmentation:** each capture turns the sensor on for its feed, whose first data comes a frame or two later, and
reads it after each app update for up to 5 s, counting data only at the feed's size. An answer without segmentation
says why in `segmentation_error`. After a wait that got nothing, the next capture of that camera at that size on that
stage waits 1 s, until a read gets data, so `capture_viewport` doesn't pay 5 s on every call.

## Extension Lifecycle

- **on_startup**: Creates the HTTP server, binds to configured host:port, registers all routes. It turns on no sensor of
  the viewport's: captures render through feeds of their own and turn instance segmentation on for each feed ([Viewport
  Capture](#viewport-capture)), so the viewport's own sensor, which copied its instance ids to the host every frame, is
  left off (#76)
- **on_shutdown**: Cancels a running job, drops its stage watch and calls its teardown, and refuses any start after it,
  so a start in flight during a reload can't leave a job no route reaches; takes the output router off `sys.stdout`
  and `sys.stderr`, so Kit's own restore at exit finds its interceptor and the next start installs a router of its
  own, not one over this; stops any active recording, cancelling its frames and dropping its camera feed, and drops the debug
  drawing observer and its book (deleting and clearing nothing: the stage may be tearing down; a recording's
  render product stays on a stage that outlives the extension); tears the kept capture feed down with no update
  between its steps, deleting its render product while a stage is open ([Viewport Capture](#viewport-capture)); clears
  caches, closes the HTTP server

The extension includes:
- **Content-Length validation**: Rejects request bodies over 100 MB
- **Connection limiting**: 20 handler slots, so at most 20 requests run at once
- **Health endpoint**: `GET /health` returns server status with error wrapping

The extension can be enabled/disabled from the application's extension manager (Window > Extensions). Disabling it stops the HTTP server; re-enabling restarts it.
