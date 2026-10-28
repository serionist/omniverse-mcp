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
  command (or `uv run --project <clone> omniverse-mcp`; the README shows both).
- **The Kit extension is `ovmcp.bridge`, in `extension/ovmcp.bridge/`.** It was `isaacsim.mcp.bridge`, in a folder
  named with its version. To move over:
  1. In Kit's Extension Manager, turn `isaacsim.mcp.bridge` off and its autoload off.
  2. Remove its search path if it pointed inside `extension/isaacsim.mcp.bridge-1.0.0`; the repo's `extension/` folder
     stays the search path.
  3. Turn on `ovmcp.bridge` with autoload.
  4. Move a custom port or token from `exts."isaacsim.mcp.bridge"` to `exts."ovmcp.bridge"`. The
     `scene_tree_max_depth` setting is gone; nothing read it.
- **The server's flags are `--host` and `--port`,** in place of `--isaac-host` and `--isaac-port`. They and
  `--output-dir` default to `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT` and `OMNIVERSE_MCP_OUTPUT_DIR`.
- **The MCP resources are `omniverse://scene/tree` and `omniverse://sim/state`,** and the server calls itself
  `omniverse`. Scene dumps and recording state files start with `# Omniverse MCP`, and their `# format` line
  reads `omniverse-mcp-v1`.
- **Python 3.11 or newer** for the server.

### Changed

- **A black capture is no longer relit behind your back.** The bridge used to turn the camera light on and capture
  again; now the capture comes back as it is, with a warning that says how to light the scene (`viewport_light`).
- **`inspect_prim` refuses what it cannot do instead of guessing:** an unknown angle name (it used to be skipped),
  a non-numeric `width`, `height` or `zoom_offset`, and an orthographic viewport camera, where distance frames
  nothing.

### Added

- **`inspect_prim` frames the prim for you.** The camera stands where the prim's bounding sphere fills the captured
  frame with a small margin; `zoom_offset` moves it closer (`-0.3`) or further (`0.5`). `isolate=True` hides everything
  but the prim while it captures, keeps the scene's lights on, and puts every prim's visibility back exactly as it was;
  what it cannot hide (inside an instance, or with time-sampled visibility) it names in `isolate_warnings`.
- **`viewport_light(action="set", mode=...)` switches the lighting mode:** `"off"`, `"camera"`, `"stage"`, or a light
  rig such as `"Default"`, the quickest fix for black captures. It returns an error when the mode did not change, for
  example a light rig in a Kit app without the viewport's lighting menu.
