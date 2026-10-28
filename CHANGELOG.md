# Changelog

What changed for people who use omniverse-mcp, newest first. A change users notice adds its line under Unreleased in
the same PR. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Security

- **The bridge answers only the MCP server that holds its token.** Before this, any program on the machine, and any
  web page open in a browser, could send `/execute` to the extension and run Python inside the Kit app. The extension
  now writes a new random token to a file only your user can read, every request must carry it, and requests from web
  pages are refused.

### Breaking changes

- **Update the MCP server and the Kit extension together.** A new server refuses an old extension, and an old server
  gets 401 from a new one. `git pull` in your checkout updates both; then restart Kit and your MCP client.
- **A remote Kit app needs the token by hand:** set the extension's `token` setting and the server's
  `OMNIVERSE_MCP_TOKEN` to the same value.
- **`inspect_prim` no longer takes `distance`.** It fits the distance itself; use `zoom_offset` to move closer or
  further.
- **`viewport_light("get")` reports `lighting_mode`** and the available modes, in place of `camera_light_on`.
- **The Python package is `omniverse_mcp`.** In `.mcp.json`, `python -m isaac_sim_mcp` becomes the `omniverse-mcp`
  command (or `uv run --no-sync --project <clone> omniverse-mcp`; the README shows both). An install from before
  the rename still points `omniverse-mcp` at the deleted `isaac_sim_mcp`: reinstall it with
  `pip uninstall omniverse-mcp` then `pip install .` (or `pip install -e .`), or switch to `uv sync`.
- **The Kit extension is `ovmcp.bridge`, in `extension/ovmcp.bridge/`.** It was `isaacsim.mcp.bridge`, in a folder
  named with its version. To move over:
  1. In Kit's Extension Manager, turn `isaacsim.mcp.bridge` off and its autoload off.
  2. Remove its search path if it pointed inside `extension/isaacsim.mcp.bridge-1.0.0`; the repo's `extension/` folder
     stays the search path.
  3. Turn on `ovmcp.bridge` with autoload.
  4. Move a custom port or token from `exts."isaacsim.mcp.bridge"` to `exts."ovmcp.bridge"`. The
     `scene_tree_max_depth` setting is gone; nothing read it.
- **The server's flags are `--host` and `--port`,** in place of `--isaac-host` and `--isaac-port`, which now stop
  the server with a message naming the new flag; any other unknown flag is an error too. `--host`, `--port` and
  `--output-dir` default to `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT` and `OMNIVERSE_MCP_OUTPUT_DIR`; an empty
  variable counts as unset.
- **The MCP resources are `omniverse://scene/tree` and `omniverse://sim/state`,** and the server calls itself
  `omniverse`. Scene dumps and recording state files start with `# Omniverse MCP`, and their `# format` line
  reads `omniverse-mcp-v1`.
- **Python 3.11 or newer** for the server.
- **A tool that fails returns an error result, not `ERROR:` text.** The MCP result has `isError` set, with the
  bridge's message and the last lines of its traceback, or why the Kit app couldn't be reached; its text no
  longer starts `ERROR:`. A script that looked for `ERROR:` in a tool's text reads `isError` instead, or it
  takes every failure for a success. A failed resource read is a resource error.
- **A tool refuses a value out of its range, or not one of its choices,** before it reaches Kit: a width, height,
  count or `fps` below 1; a negative `max_depth`, `frame_index`, mass, density or friction; a distance, duration,
  radius or point size not above 0; a `zoom_offset` of -1 or less; an opacity, roughness, metallic or restitution
  outside 0 to 1; a `max_depth` above 15 in `get_scene_tree`, which used to cut it to 15 quietly. `sim_control`,
  `viewport_light`, `manage_extensions` and `draw_debug` take only their listed actions and shapes, in lower case
  (`"Play"` used to work), and `get_logs` only `verbose`, `info`, `warn`, `error`, `fatal` or `""` as `min_level`,
  where an unknown level used to filter nothing.
- **`clone_prim` refuses a target path that already holds a prim,** and `create_prim` one that holds a prim of
  another type. Both used to overwrite it: a clone replaced the prim there and its children, and a create turned a
  Cube into an Xform.

### Fixed

- **`draw_debug`'s `size` defaults to 0.05, what it draws,** where its schema said 5.0; asking for 5.0 drew 0.05.
- **`get_logs` names Kit's log levels right, and `min_level` keeps the right ones.** A warning was labelled
  `verbose` and an error `info`, and `min_level="warn"` kept only fatal messages.

### Changed

- **The server runs on MCP SDK v2** (`mcp` 2.3.0), and its tools reach Kit one request at a time.
- **A black capture is no longer relit behind your back.** The bridge used to turn the camera light on and capture
  again; now the capture comes back as it is, with a warning that says how to light the scene (`viewport_light`).
- **`inspect_prim` refuses what it cannot do instead of guessing:** an unknown angle name (it used to be skipped),
  a non-numeric `width`, `height` or `zoom_offset`, and an orthographic viewport camera, where distance frames
  nothing.

### Added

- **`omniverse-mcp extension install`** copies the Kit extension of the server's own release to your user data
  folder, in place of an older one, and prints the folder Kit's extension search paths need; `omniverse-mcp extension
  path` prints it again. When the server and the extension speak different bridge protocols, the server's message
  names the command for its release, `uvx omniverse-mcp==X.Y.Z extension install`, and says which side is older.
- **Each tool says what it does to the Kit app,** as MCP annotations a client may use to ask before it runs one:
  read-only (queries and captures), not destructive (edits), destructive (deletes and overwrites, prims or files), or
  destructive and open world (`execute_script`, `manage_extensions`). `docs/TOOLS.md` lists them. They are hints,
  never security.
- **Every parameter is described in the tool's schema,** with its range or choices, so a client shows them without
  the docs.
- **`inspect_prim` frames the prim for you.** The camera stands where the prim's bounding sphere fills the captured
  frame with a small margin; `zoom_offset` moves it closer (`-0.3`) or further (`0.5`). `isolate=True` hides everything
  but the prim while it captures, keeps the scene's lights on, and puts every prim's visibility back exactly as it was;
  what it cannot hide (inside an instance, or with time-sampled visibility) it names in `isolate_warnings`.
- **`viewport_light(action="set", mode=...)` switches the lighting mode:** `"off"`, `"camera"`, `"stage"`, or a light
  rig such as `"Default"`, the quickest fix for black captures. It returns an error when the mode did not change, for
  example a light rig in a Kit app without the viewport's lighting menu.
