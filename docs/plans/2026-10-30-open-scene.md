---
title: Add an open_scene tool that opens a USD file as the stage
issue: "#79"
status: draft
approved_by:
approved_at:
---

# Add an open_scene tool that opens a USD file as the stage

Today an agent opens a file only through `execute_script`. `new_scene` starts an empty stage and `save_scene` writes
one, but nothing opens one. Glama's completeness mark (4/5) names the gap: "no explicit scene-open tool".

This plan adds `open_scene(file_path)`, a new tool, route and handler, after a live run on Isaac Sim 6.2 that settled
the issue's four questions:

- **Unsaved changes:** Kit's own flag for them, `has_pending_edit()`, reads true in every state measured: a fresh
  new stage, a file just opened, and a stage just saved (E3, E6). Nothing tells the user's edits from Kit's own, so
  the tool can't refuse on them. It discards them, as `new_scene` does, and says so (Q2).
- **Paths:** `create_robot`'s rule (#40): a file on the Kit app's machine, a relative one read from Kit's working
  folder; a URL as given; a path in Isaac Sim's asset library under its root (Q3).
- **Time:** an open runs on Kit's loop while Kit's updates go on (E3, E12, E13): 0.3 s for a small file, 1.3 s for
  100,000 prims, 2.4 s for Isaac Sim's `simple_room.usd` over HTTPS. The tool gives the open 80 s, after a 20 s check
  of the file, under the client's 120 s.
- **The answer:** the file, the up axis and metres per unit as `get_sim_state` reports them, the default prim and
  the prim count, with a note for a file that sets no axis or units, which USD reads as Y and centimetres (E4).

The run also found that a failed open loses the stage. Kit closes the open stage before it reads the file, so a
missing, broken or non-USD file leaves no stage open at all (E7). So `open_scene` checks the file before Kit closes
anything: it exists, Kit can reach it, USD opens its type, and no other open is under way.

## Goal

**When this is done:**

- `open_scene(file_path)` opens a USD file as the stage and answers with its file, up axis, metres per unit, default
  prim and prim count.
- The paths it takes:
  - a local file, whole or relative to Kit's working folder;
  - an `omniverse://`, `https://` or `file:///` URL;
  - a path in Isaac Sim's asset library (`/Isaac/...`).
- It refuses with the open stage kept:
  - a file that isn't there;
  - a URL Kit can't reach;
  - a type USD doesn't open;
  - a call made while Kit opens or closes a stage.
- The open stage goes without a prompt, its unsaved changes too. Opening the file the stage has open reloads it from
  disk (E5).
- It stops the simulation first, as Kit's own File > Open does. A recording's frames stop, and `draw_debug`'s
  drawings go, as on `new_scene` (E11).
- An older extension, which lacks the route, gets an error that names the command installing this release's.
- The tool contract gains the tool, `docs/TOOLS.md` its heading, `CHANGELOG.md` its line, and the live suites test
  it.

**In scope:**

- the server's tool, client method and the older-extension message;
- the bridge's route and handler;
- a Kit-free core for the open's checks, sequence and answer;
- `create_robot`'s path rule moved to a module of its own, so both tools share it, unchanged;
- the unit, contract and live tests, and the docs.

**Out of scope:**

- **Opening with payloads unloaded** (Kit's `LOAD_NONE`), sublayers, or a session layer: a parameter could add one
  later without breaking a call.
- **Reporting the open stage's file in `get_sim_state`.**
- **`new_scene` stopping the simulation** as `open_scene` does: unchanged.
- **What Kit writes into an opened root layer** (R4).
- **Isaac Sim 5.x live:** it crashes in its own start on this machine (#59). 5.1 is read from its source on GitHub.

## What the code and the sources say

Read from this repo at `a724ca9`, from Isaac Sim 6.2.0 under `D:\isaac\venv` (Kit 110.4, `omni.usd` 1.19.11,
`omni.kit.window.file` 2.0.17), and from Isaac Sim 5.1's source on GitHub (`v5.1.0`, Kit 107). Isaac Sim's docs
were read through Context7. #80 (`584d6e9`) landed on main after `a724ca9`. Of the files this plan changes, it
touched `_utils.py`, `AGENTS.md`, the docs, `test_project/scenarios.md` and the live suites, where this plan only
adds; and it keys segmentation waits by stage id, camera and size.

| # | Fact | Source |
|---|---|---|
| F1 | `new_scene` calls `ctx.new_stage_async()`, waits two updates, defines `/World` and sets Y up; it neither asks about unsaved changes nor stops the timeline. `save_scene(file_path)` hands the path to `GetRootLayer().Export` as given, and with none calls `Save()` | `handlers/scene.py` lines 512-549 |
| F2 | `create_robot` reads a USD file through `robot_usd_url(path, assets_root, is_file, whole)`. A URL goes as given; a file on Kit's machine is made whole with `os.path.abspath`; a path starting `/Isaac/` goes under `get_assets_root_path()`; anything else is `None`, an error naming the path | `core/robot.py` lines 34-52; `handlers/robot.py` lines 38-75 |
| F3 | A recording's frames stop when the stage state isn't `OPENED` or its id changes. `draw_debug`'s book drops drawings of another stage id and draws nothing while the stage isn't `OPENED`. Segmentation waits are kept per stage id and render product; since #80, per stage id, camera and size | `handlers/recording.py` lines 210-224; `handlers/debug_draw.py` lines 115-201; `handlers/camera.py` line 424, and `_segmentation_key` at `584d6e9` |
| F4 | `UsdContext.open_stage_async(url, load_set, session_layer_url)` wraps `open_stage_with_callback`, returning `(result, error)`. Its callback sets the future only while it isn't done, so a wait cut short by `asyncio.wait_for` is safe | `omni/usd/_impl/api.py` lines 21-26, 142-167 |
| F5 | `has_pending_edit()`: "Whether it has unsaved edits or not". `can_open_stage()`, `get_stage_state()` (`CLOSED`, `OPENING`, `OPENED`, `CLOSING`), `get_stage_url()`, `is_writable()` and `get_stage_loading_status()` are on the same context | `omni/usd/_usd.pyi` lines 489-527, 546, 651, 668, 680, 707-727 |
| F6 | Kit's File > Open stops the timeline, then `omni.client.stat_async(path)`; only an `OK` goes on to `open_stage_async`, anything else is a warning and an error dialog. It counts an open as failed unless the result is true and the state is `OPENED`. It asks to save first when `has_pending_edit()` | `omni/kit/window/file/file_window.py` lines 226-238, 324-402, 887-925 |
| F7 | Isaac Sim 6.2's `open_stage_async` refuses a path that fails `Usd.Stage.IsSupportedFile` ("a shallow check on the path only"), then calls `omni.usd.get_context().open_stage_async(usd_path)` between `disable_save_to_recent_files()` and `enable_save_to_recent_files()` | `isaacsim.core.experimental.utils/.../impl/stage.py` lines 360-387 |
| F8 | Isaac Sim 5.1 (Kit 107) does the same: `IsSupportedFile`, then `omni.usd.get_context().open_stage_async(usd_path)` returning `(result, error)`. It checks a URL with `omni.client.stat_async` under `asyncio.wait_for` | GitHub `v5.1.0`: `isaacsim.core.utils/python/impl/stage.py` lines 452-483; `isaacsim.storage.native/isaacsim/storage/native/nucleus.py` line 228 |
| F9 | A route the extension lacks answers 404 `Unknown endpoint: <path>`. The client returns it, and `bridge_call` raises it as the tool's error as it stands. `PROTOCOL` changes only when the two sides stop understanding each other's requests | `core/http.py` line 222; `client.py` lines 62-70; `tools/_bridge.py`; `core/protocol.py`; modernization plan Q2 |
| F10 | The client times out after 120 s. The capture calls stay under it with 80 s plus 10 s, and a unit test holds that sum under it | `client.py` line 31; `core/capture.py` lines 28-31; `docs/ARCHITECTURE.md`, Viewport Capture |

## Findings

On Isaac Sim 6.2.0 (Kit 110.4.0) headless, with main's bridge on port 8212, on a fresh Kit. The main session ran
`e79_open.py`, kept outside the repo, on 2026-10-30. Every step ran, and Kit was still up after the last.

| # | What | Measured | Means |
|---|---|---|---|
| E1 | Kit's working folder | The folder Kit was started from (here the scratchpad); `omni.client.stat_async("e79-relative-missing.usda")`: `ERROR_NOT_FOUND` | a relative path is read from wherever Kit was started, which an agent can't see: the answer and the error give the whole path |
| E2 | `Usd.Stage.IsSupportedFile` in Kit | True: `.usd`, `.usda`, `.usdc`, `.usdz`, `.obj`, `.gltf`, `.glb`, `.fbx`, `.abc`, `SCENE.USD`, `https://.../scene.usd`, `omniverse://.../scene.usd`. False: `.txt`, `.stl`, `.ply`, `.urdf`, `.mjcf`, `.xml`, `.vdb`, `.mdl`, no extension | the shallow check NVIDIA's own code makes (F7, F8); Kit's plugins add formats, so it is asked in Kit, not listed by us |
| E3 | A new stage, then `open_stage_async` of a saved `.usda` | `(True, "")` in 0.31 s, with 89 app updates during it. Events `CLOSING`, `CLOSED`, `OPENING`, `OPENED`; stage id 9223003 to 9223004. URL and identifier `C:/Users/.../scene.usda`, real path with backslashes. `has_pending_edit()` and the root layer's `dirty` true at once and after 2, 10 and 30 updates; true on the new stage too, after 0, 10 and 30. Kit had written `/Render` (the viewport's render product and render settings) into the opened root layer | Kit's loop runs during an open. The flag can't tell a user's edit from Kit's own |
| E4 | A file with no `upAxis` or `metersPerUnit` | Up axis `Y`, metres per unit `0.01`, neither authored; no default prim | USD's fallbacks, which a reader takes for metres and Z: the answer notes them |
| E5 | An unsaved edit, then opening the file the stage has open | The edit is gone, the stage id changes, the file on disk is unchanged | opening the open file reloads it from disk |
| E6 | An edit, then the root layer's `Save()`, as `save_scene` does | The root layer clean, `has_pending_edit()` still true, after 10 updates too. The saved file holds Kit's `def "Render"`, the viewport's `RenderProduct`, `RenderSettings` and `RenderVar` | not even a save clears the flag. A save in place carries Kit's render prims into the file (R4) |
| E7 | Opening a missing `.usda`, a broken `.usda`, a `.txt`, and a `file:` URL to a missing file | Each `(False, "Failed to open: <path>")` within 0.08 s. Events `CLOSING`, `CLOSED`, `OPENING`, `OPEN_FAILED`; then state `CLOSED`, stage id -1, no stage, after 10 updates too | Kit closes the open stage before it reads the file: a failed open leaves no stage at all |
| E8 | A `.usdz` | Opens in 0.08 s; `is_writable()` true | nothing to note for `.usdz` |
| E9 | `omni.client.stat_async` | `OK` for a file's path and its `file:` URL, and for `simple_room.usd` over HTTPS. `ERROR_NOT_FOUND` for a missing path, a missing `file:` URL, a missing relative path and a missing HTTPS URL. A `file:` URL opens with the identifier `file:/C:/...` | one call checks a path or a URL before Kit closes anything, as Kit's File > Open does (F6) |
| E10 | Playing, then an open | `playing` before, `stopped` at time 0 after | Isaac Sim stops the timeline on an open; the tool stops it first anyway, as Kit's File > Open does in any Kit app that has it (F6) |
| E11 | The bridge's recording and a 30 s debug line, then an open | `get_sim_state` and `stop_recording`: `frames stopped after 28, at 0.00 s of simulation: the stage began to close`. The recording's render product neither on the opened stage nor in its root layer. Debug lines 1 before, 0 after | the stage-change handling (F3) covers an opened file as it covers `new_scene` |
| E12 | Isaac Sim's asset library over HTTPS | Root `https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/6.2`. `simple_room.usd` opened in 2.44 s, 3,046 updates during it; no file loading at the callback. `is_writable()` false; default prim `/Root`, 170 prims, Z, 1.0 | an open over the network takes seconds on the loop, and nothing is left loading; a URL's stage is read-only, so `save_scene` needs a path |
| E13 | 100,000 Xforms in a `.usdc` | 1.34 s, 759 updates during it; `get_stage()` `None` from `CLOSING` until `OPENED`; up axis and units unauthored | during an open, other requests run and find no stage |
| E14 | A second `open_stage_with_callback` while one runs | During the first: state `CLOSING`, `can_open_stage()` false, no stage. The second returned false, and its callback gave `(False, "UsdContext busy")`; the first opened its file | Kit refuses a second open itself, and its failure doesn't mean the stage is gone |

## Design

### The tool

```python
@mcp.tool(annotations=DESTROYS)
def open_scene(
    file_path: Annotated[
        str,
        Field(
            description="The USD file: a path on the Kit app's machine (a relative one is read from Kit's working "
            "folder), a URL (omniverse://, https://, file:///), or a path in Isaac Sim's asset library (/Isaac/...)"
        ),
    ],
) -> str:
    """Open a USD file as the stage, in place of the open one: the counterpart of save_scene, where new_scene starts
    an empty stage. The open stage goes without a prompt, its unsaved changes too (save_scene first to keep them);
    opening the file the stage has open reloads it from disk. The simulation is stopped, a recording's frames stop,
    and draw_debug's drawings go.

    Refused, with the open stage kept, for a file that isn't there or Kit can't reach, a type USD can't open, or while
    Kit opens or closes a stage. A file that still fails to load leaves no stage open, and the error says so. Answers
    the file, its up axis, meters_per_unit, default prim and prim count, as get_sim_state reports them."""
```

- **Name:** `open_scene`, beside `new_scene` and `save_scene`, in #77's verb-noun pattern.
- **Parameter:** `file_path`, as `save_scene` names its own, required. There is no `minLength`: no path parameter
  has one, and the bridge refuses an empty path.
- **Hints:** `DESTROYS`, as `new_scene`, since it replaces the stage. Open world was considered for URLs, and left:
  `create_robot` reads URLs without it, and here it marks `RUNS`, where anything can happen.
- **The description** follows #78: what it does, which sibling to use instead, its side effects, and how it fails.
- **The text:** the client gets key = value lines, as `get_sim_state` gives:

  ```
  Opened C:/scenes/warehouse.usda
  up_axis = Z
  meters_per_unit = 1.0
  default_prim = /World
  prim_count = 1234
  ```

- **`note =` lines, each only when it applies:**
  - the file sets no `upAxis`: USD reads it as Y;
  - the file sets no `metersPerUnit`: USD reads it as 0.01, centimetres;
  - the stage is read-only here, as a URL's is (E12): `save_scene` needs a `file_path` to keep changes;
  - the simulation was playing or paused, and is stopped now.
- **`recording_note =`:** the bridge's note, as `get_sim_state` gives it, when a recording's frames stopped.
- **The client:** `BridgeClient.open_scene(file_path)` posts `{"file_path": ...}` to `/scene/open`.

### An older extension

`bridge_call` adds one sentence to an `Unknown endpoint` error. It says the Kit extension is older than this server,
and gives the command, `install_command()`, then "restart Kit". It is the one place every tool's error passes, and
the next new route gets it too. Without it, a server updated past its extension says only
`Unknown endpoint: /scene/open` (F9).

`PROTOCOL` stays 1. Raising it would refuse every tool on an older extension for the sake of one new route; the
handshake keeps refusing on protocol alone (modernization plan Q2).

### The paths

`robot_usd_url` moves from `core/robot.py` to a new `core/usd_files.py` as `usd_file_url`, with `LIBRARY_PREFIX`,
`USD_SUFFIXES` and `is_usd_file`, unchanged. `create_robot` and `open_scene` then share one rule (F2):

- **a URL** (`scheme://...`, `file:///` included): as given. Kit's own spelling of a file URL, `file:/C:/...` (E9),
  has no `//`, so it reads as a local path, and the stat refuses it when no such file is there;
- **a file on Kit's machine:** made whole with `os.path.abspath` in Kit, so a relative path is read from Kit's
  working folder (E1). `save_scene` and `flatten_usd` hand a relative path to Kit as it is, so it names the same
  file for them;
- **`/Isaac/...`:** under Isaac Sim's asset root when Kit has one. `_assets_root` moves from `handlers/robot.py` to
  `_utils.py` for both handlers. Elsewhere the path stays as given, and the stat refuses it;
- **anything else:** none, and the error names the whole path Kit looked at and says what Kit reads a relative one
  against.

### The open, Kit-free

A new `core/stage_open.py`, unit-tested with plain asyncio as `core/capture.py` is. The handler passes Kit in as a
small protocol (`StageKit`):

- the stage state;
- `is_file`, `whole` and the asset root;
- `stat(url)`, the result's name;
- `stop_timeline()`, which says whether it was playing or paused;
- `open(url)`;
- two updates;
- the stage, whether it is writable, and the recording's note.

`open_stage(file_path, kit)` returns the handler's answer, in order:

1. **Refusals that change nothing.** Each is an error, before anything stops or closes:
   - an empty or non-string `file_path`;
   - no URL from the path rule;
   - `Usd.Stage.IsSupportedFile(url)` false (E2);
   - the state `OPENING` or `CLOSING` (E14);
   - `stat(url)` not `OK`, its result named (`ERROR_NOT_FOUND`: not found), or no answer within `STAT_SECONDS`,
     20 s (E9, F6, F8).
2. **Stop the timeline,** as Kit's File > Open does (F6, E10).
3. **Open,** within `OPEN_SECONDS`, 80 s. When the time runs out, the error says Kit goes on opening the file in the
   background, and that tools reading the stage fail until it has (E13). The wait can't cancel Kit's open; its late
   callback finds the future done (F4).
4. **A failed open** is `(False, error)`, or a state other than `OPENED` (F6). The error gives Kit's message and
   what is open now:
   - with no stage (E7): "Kit closed the stage that was open before the file failed to load, so no stage is open:
     open_scene another file, or new_scene";
   - with one, as when Kit was busy (E14): its file.
5. **Two updates,** as `new_scene` waits, so the recording's and the drawings' update handlers have seen the new
   stage. No wait for asset loading: nothing was left loading at `OPENED` (E12). Materials still compile on first
   render, which the scene skill already notes.
6. **The answer**, `describe(stage)`, pure pxr, so usd-core tests it:
   - `file_path`: the root layer's identifier, as Kit reports it (E3, E9);
   - `up_axis` and `meters_per_unit`, through `UsdGeom` as `/sim/state` reads them, each with whether the file
     authors it;
   - `default_prim`, or none;
   - `prim_count`, through `Traverse()` as `/sim/state` counts, Kit's own prims included;
   - with `writable`, `stopped` and `recording_note` from Kit.

Both limits are read when the call runs, as `capture.py`'s are, so a live test could shorten one. A unit test holds
`STAT_SECONDS + OPEN_SECONDS` 20 s under the client's 120 s, room for the updates, the traversal and the reply.

### The bridge

`handle_open_scene(body)` in `handlers/scene.py` builds the `StageKit` from Kit's calls and awaits
`stage_open.open_stage`. The calls:

- `omni.usd.get_context()`'s `get_stage_state`, `open_stage_async`, `get_stage` and `is_writable`;
- `omni.client.stat_async`;
- `omni.timeline.get_timeline_interface()`'s `is_stopped` and `stop`;
- `os.path.isfile` and `os.path.abspath`;
- `recording_note()` from `handlers/recording.py`.

`/scene/open` joins the routes in `extension.py` and `handlers/__init__.py`.

- **Threading:** all of it runs on Kit's loop, as a handler task of its own, awaiting Kit's own async calls. Nothing
  uses `run_in_executor` (AGENTS.md, Traps).
- **Requests during an open:** Kit's updates go on (E3, E12, E13), so a request from another client meanwhile runs,
  and finds no stage. The server's own client sends one request at a time, so its other tools wait for the answer.

### Alternatives

- **Refuse when the stage has unsaved changes, or take a `discard_unsaved` flag.** `has_pending_edit()` reads true
  after every new stage, open and save (E3, E6), so the refusal would refuse every call, and the flag would be
  needed on every call (Q2).
- **Open the file with `Usd.Stage.Open` first, then attach it,** keeping the old stage when the file fails. It parses
  the file on the main thread with Kit's loop stopped, where Kit's open lets the loop run (E13). It also skips the
  context's own open: its session layer, its load rules, its events.
- **Parse the root layer before the open** (`Sdf.Layer.FindOrOpen`), to catch a broken file. It also blocks the loop,
  for a download over the network too, and catches only the root layer. The stat and the type check catch the
  common failures; a broken file is R1.
- **Refuse relative paths.** `create_robot` takes them, and `save_scene` writes them, against Kit's working folder.
  The whole path in the answer and the error shows where that is (Q3).
- **Leave the timeline alone.** Isaac Sim stops it on an open (E10), but Kit's File > Open stops it first in any app
  that has it (F6), and other Kit apps are unmeasured. The one call costs nothing.
- **Turn off Kit's recent files around the open,** as NVIDIA's scripts do (F7). Kit has no getter to restore a
  setting the app chose, and an agent's open in File > Open Recent is no harm.
- **Raise `PROTOCOL`.** It would refuse every tool on an older extension for one new route.

## Compatibility

Two one-way doors gain an entry; neither changes an existing one.

| Door | Effect |
|---|---|
| Tool names, schemas and annotations | Adds `open_scene`: `file_path`, a required string, and the destructive hint. Additive: no tool's name, parameters or hints change. `tests/fixtures/mcp-tools.json` is rewritten by `uv run tools/golden.py`, and CHANGELOG lists it under Added, not Breaking |
| The wire protocol | Adds the path `/scene/open`. No path, body or header changes, and `PROTOCOL` stays 1 (Design, An older extension) |
| The extension's id and settings, the token, the output folder, the install folder | Unchanged |

What users notice:

- **A new tool.** Nothing they call today changes.
- **Mixed releases:** a server of this release on an older extension: every tool works as before, and `open_scene`
  errors with the install command. An older server never calls the route.
- **Kit apps:**
  - Kit 110 measured (E1 to E14).
  - Kit 107 through Isaac Sim 5.1's own calls: `open_stage_async` returning `(result, error)`, and `stat_async`
    under `wait_for` (F8). `StageState` the bridge already reads on both.
  - Kit apps without Isaac Sim's asset root, such as USD Composer: a `/Isaac/...` path stays as given, and the stat
    refuses it.

## Steps

| # | What | Proved by |
|---|---|---|
| 0 | The live run, E1 to E14 | the Findings |
| 1 | This plan, the branch's first commit; then the branch rebased on main, for #80 | `review-plan`, then the maintainer |
| 2 | `core/usd_files.py`: `usd_file_url` and its names moved from `core/robot.py`. `robot.py` and the robot handler import them; `_assets_root` to `_utils.py` | `tests/test_usd_files.py`: the path tests moved from `tests/test_robot.py`, renamed and otherwise unchanged; `test_integration.py`'s `test_27` to `test_30` unchanged |
| 3 | `core/stage_open.py`: the checks, the sequence, the limits and `describe` | `tests/test_stage_open.py` (Tests) |
| 4 | The handler, its `StageKit`, the route | the live tests of step 7 |
| 5 | The server: `client.open_scene`, the tool, `bridge_call`'s older-extension sentence. The golden file through `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 6 | The docs (Docs) | `tests/test_contract.py` finds the `### open_scene` heading; the gate's AGENTS.md and plugin checks |
| 7 | The live tests in `test_integration.py` and `test_scenarios.py`, and `test_project/scenarios.md`'s 17.7 | run on Isaac Sim 6.2 at 8212 |
| 8 | `uv run tools/gate.py full`, then `review-code` | the gate; the review record |

## Tests

**Unit (CI), new:**

`tests/test_stage_open.py`, with a fake `StageKit` that records its calls, and real usd-core stages:

- **Each refusal changes nothing:**
  - an empty path, a missing local file, a type USD can't open, an `OPENING` and a `CLOSING` state, a stat of
    `ERROR_NOT_FOUND`, and a stat that doesn't answer within a shortened `STAT_SECONDS`;
  - for each, no timeline stop and no open in the fake's calls;
  - the missing file's error names the whole path.
- **The path reaches the open as the rule makes it:** a URL as given, a library path under the root, a relative path
  made whole.
- **The timeline:** stopped before the open; `stopped` in the answer only when it was playing or paused.
- **A failed open:** `(False, "Failed to open: x")` with no stage after says no stage is open; with a stage after (Kit
  busy) it names that stage's file.
- **An open past a shortened `OPEN_SECONDS`:** the error says Kit goes on opening the file.
- **`describe`:**
  - on a usd-core stage from a file with `upAxis = "Z"`, `metersPerUnit = 1` and a default prim: identifier, axis,
    units, both authored, the default prim, the prim count;
  - on one with neither authored: Y and 0.01, both flagged unauthored, no default prim.
- **Kit's values pass through:** `writable` false, and the recording's note.
- **The limits:** `STAT_SECONDS + OPEN_SECONDS` stays 20 s under the client's timeout.

**Unit (CI), elsewhere:**

- `tests/test_usd_files.py`: `test_robot.py`'s path tests, moved.
- `tests/test_tools.py`:
  - a `Case` for `open_scene`: its route, `file_path` sent, and `Opened`, `up_axis = Z`, `meters_per_unit = 1.0` in
    the text;
  - a test for each `note =` line and `recording_note`;
  - a test that the mock's `404 Unknown endpoint: /scene/open` reaches the client as an error naming the install
    command.
- `tests/test_client.py`: `open_scene` posts `file_path` to `/scene/open`.
- `tests/test_contract.py`, unchanged: the golden file, the hints and the `### open_scene` heading.

**Live, `test_integration.py`, a new section "Opening a scene (#79)":**

- `test_31`, save, new, open:
  - a cube at `/World/IntTestOpen`, then `save_scene` to a `.usda` in a temp folder (`.usda`, which Windows doesn't
    hold locked);
  - `new_scene`: the cube is gone;
  - `open_scene` of the file: the answer's `file_path` is the file, `up_axis` and `meters_per_unit` are what
    `/sim/state` read before the save, and the cube is back.

  So the stage the suite found comes back, from its copy.
- `test_32`, a missing file: refused, naming the path, and the cube is still there. Without the stat, E7 says the
  stage would be gone, so this fails without the change.
- `test_33`, a `.txt`: refused, and the cube is still there.
- `test_34`, a `file:` URL to a missing file: refused by the stat, and the cube is still there.
- `test_35`, a relative path that doesn't exist: the error names it joined to Kit's working folder, read through
  `execute_script`'s `os.getcwd()`. Nothing is written into that folder.
- `test_36`, Isaac Sim's asset library, `/Isaac/Environments/Simple_Room/simple_room.usd`:
  - `/Root`, Z, 1.0, and the read-only note;
  - then `test_31`'s file opened again, so the suite's later tests find their stage.

  It needs the network, as the scenarios' robots do.

**Live, `test_scenarios.py`:**

- `test_17_07`, an opened file stops a recording and drops the drawings, as 17.3 and 17.5 do with `new_scene`
  (#80 took 17.6):
  - the stage saved to a temp file, a recording started, a 30 s line drawn, then `open_scene` of the file;
  - no frames after it, `stop_recording`'s note names the stage, the recording's render product isn't on the opened
    stage, and the line count is back where it started (E11).
- `test_project/scenarios.md`'s phase 17 gains it as 17.7.

**What neither shows:**

- an open that runs out of its 80 s, which needs a file that slow (the unit test covers the error);
- a broken file after the checks (R1);
- Nucleus `omniverse://`, with no Nucleus server here (the stat and the open are Kit's, as for `https://`);
- Kit 107 live.

## Docs

| File | Change |
|---|---|
| `docs/TOOLS.md` | `### open_scene` between `save_scene` and `new_scene`: the parameter, the paths, the answer and its notes, the refusals, a failed open leaving no stage, reloading the open file, the time limit. The Find a tool row "open a USD file as the stage, or start an empty one"; the destructive hints row; Scene Tools (12 tools); the recording's "When frames stop", draw_debug's "Drawings belong to their stage" and `new_scene`'s "open a Z-up stage" name `open_scene` |
| `README.md` | The tools table's Scene row: `open_scene`, and "save, open a file, or start an empty scene" |
| `docs/ARCHITECTURE.md` | `/scene/open -> handle_open_scene` in the routes; the scene tools module's row; the core's key files gain `usd_files.py` and `stage_open.py`, `robot.py`'s shrinks; a short "Opening a stage" section: the checks, the 20 s and 80 s under the client's 120 s, no stage during an open, a failed open leaving none |
| `plugin/skills/scene/SKILL.md` | Step 1 or a line before it: start from a file with `open_scene`, `save_scene` first to keep the open one. The Traps table: a file with no units is read as centimetres (the answer's note). `allowed-tools` unchanged: the tool isn't read-only |
| `CHANGELOG.md` | Unreleased, a new `### Added`: `open_scene` opens a USD file as the stage (paths, what goes, the answer); the extension needs `uvx omniverse-mcp extension install` and a Kit restart (#79) |
| `AGENTS.md` | The core's list in "Where things are" gains "USD file paths" and "opening a stage", in the same line |
| `test_project/scenarios.md` | Phase 17.7 (Tests) |

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | A file that passes the checks and still fails to load leaves no stage. Kit closes the old one first (E7): a broken file, a server that fails between the stat and the open | Accepted, as Kit's File > Open does it (F6). The error says no stage is open and what to do; TOOLS.md says it too (Q4) |
| R2 | An open past 80 s errors while Kit goes on; tools reading the stage fail until it has (E13) | Accepted. The error and TOOLS.md say so, and `get_sim_state` answers once it has. 80 s is more than 30 times E12's network open |
| R3 | Unsaved changes go without a prompt | Accepted, as `new_scene` does: Kit's flag can't tell them (E3, E6). The description, TOOLS.md and the skill say `save_scene` first; the destructive hint lets a client ask (Q2) |
| R4 | Kit writes its `/Render` prims into an opened file's root layer, and `save_scene` without a path writes them into the file (E6) | Not ours: Kit's own Save does the same, and any stage opened in the GUI has it today. Out of scope |
| R5 | `get_assets_root_path()` checks the server synchronously on the main thread, for a `/Isaac/` path | Accepted, as `create_robot` does today |
| R6 | A stat can refuse a URL Kit could open, from a server that answers no stat | Accepted: Kit's File > Open refuses it the same way (F6) |
| R7 | Kit 107 untested live | Accepted: F8's calls are Isaac Sim 5.1's own |
| R8 | `test_31` leaves Kit's stage tied to a temp file its cleanup deletes; a save there writes it again | Accepted: the live suites run on a test Kit, and the stage's content is the suite's own |

## Questions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | The tool: `open_scene(file_path)`, required, destructive hint, the answer above | Yes: it sits beside `new_scene` and `save_scene`, and takes `save_scene`'s parameter name |
| Q2 | Unsaved changes: refuse, take a flag, or discard as `new_scene` does | Discard, and say so in the description and the docs: `has_pending_edit()` is true after every new stage, open and save (E3, E6), so a refusal or a flag would fire on every call |
| Q3 | Paths: `create_robot`'s rule, a relative path read from Kit's working folder, URLs, `/Isaac/...` | Yes: one rule for both tools, and `save_scene` writes a relative path to the same place |
| Q4 | A file that passes the checks and fails to load: leave no stage, as Kit does, or open an empty one | Leave none and say so: an empty stage the agent didn't ask for would hide the failure, and `new_scene` is one call away |

## Plan review

None yet: `review-plan` runs next.
