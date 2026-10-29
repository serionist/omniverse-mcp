# Setup in depth

The [README](../README.md#install) has the short path. This page has the rest: each MCP client's config, headless
Kit, ports, Kit on another machine, the output folder, updating, uninstalling and troubleshooting.

The names used here:

- **the Kit app:** Isaac Sim, or another app of Kit 107 or later;
- **the server:** `omniverse-mcp`, the MCP server your client starts;
- **the bridge:** the Kit extension `ovmcp.bridge`, listed in Kit as *Omniverse MCP Bridge*.

## MCP clients

Every client starts the server with `uvx omniverse-mcp` and an empty `PYTHONPATH`: Isaac Sim's environment can set
one, which would put Isaac Sim's Python packages into the server's Python. Restart the client after changing its
config.

| Client | Where |
|---|---|
| Claude Code | the plugin ([README](../README.md#claude-code-the-plugin)); or by hand, `claude mcp add --scope project -e PYTHONPATH= --transport stdio omniverse -- uvx omniverse-mcp`, which writes `.mcp.json` in the folder it runs in (`--scope user` for every project). Keep an option between `-e` and the name, or the name is read as another variable |
| Cursor | `.cursor/mcp.json` in the project, or `~/.cursor/mcp.json` for every project |
| VS Code | `.mcp.json` at the workspace root; older setups use `.vscode/mcp.json`, in VS Code's own form (below) |
| Claude Desktop | `claude_desktop_config.json`, from **Settings > Developer > Edit Config**: `%APPDATA%\Claude\` on Windows, `~/Library/Application Support/Claude/` on macOS. Quit it fully and start it again after an edit |
| Codex | `~/.codex/config.toml`, or `.codex/config.toml` in a trusted project (below) |
| Windsurf (now Devin Desktop) | its MCP config, opened from the app's MCP settings |

Most take the `mcpServers` form:

```json
{
  "mcpServers": {
    "omniverse": { "command": "uvx", "args": ["omniverse-mcp"], "env": { "PYTHONPATH": "" } }
  }
}
```

VS Code's `.vscode/mcp.json` names the list `servers`, and each server's `type`:

```json
{
  "servers": {
    "omniverse": { "type": "stdio", "command": "uvx", "args": ["omniverse-mcp"], "env": { "PYTHONPATH": "" } }
  }
}
```

Codex takes TOML:

```toml
[mcp_servers.omniverse]
command = "uvx"
args = ["omniverse-mcp"]

[mcp_servers.omniverse.env]
PYTHONPATH = ""
```

**The client needs to read files.** The tools write images and long answers to files and return their paths, and
the coding clients above read them with their file tools. Claude Desktop has none of its own, and starts servers in
no particular folder: give the server an absolute `--output-dir` ([The output folder](#the-output-folder)), and
Claude Desktop a filesystem MCP server for that folder. `capture_viewport(include_image=True)` returns its image
inline either way.

**Allowing tools without prompts in Claude Code:** the plugin's tools are `mcp__plugin_omniverse-mcp_omniverse__<tool>`,
and a server added by hand gives `mcp__omniverse__<tool>`. Add the read-only ones to `permissions.allow` in
`.claude/settings.json`; the [tool reference](TOOLS.md) lists which those are. Keep `execute_script` and
`manage_extensions` asking: they run code inside Kit.

## Headless Kit

A Kit app without its window takes the bridge on its command line:

```
--ext-folder <the folder extension install printed> --enable ovmcp.bridge
```

- **Isaac Sim** takes the same flags from its launcher script (`isaac-sim.sh`, `isaac-sim.bat`) and from the pip
  install's `isaacsim` command.
- **A standalone Python script** with `SimulationApp` passes them through its launch config:

  ```python
  from isaacsim import SimulationApp

  app = SimulationApp({"headless": True, "extra_args": ["--ext-folder", "<folder>", "--enable", "ovmcp.bridge"]})
  while app.is_running():
      app.update()
  ```

  The bridge runs on Kit's event loop, so it answers only while the script keeps calling `update()`. A script's own
  unknown command-line arguments reach Kit too, so `python.sh my_script.py --enable ovmcp.bridge` works as well.
- Isaac Sim asks for NVIDIA's licence on its first start; accepting it, or setting `OMNI_KIT_ACCEPT_EULA=YES`, is your
  decision.

## Ports and two Kit apps

The bridge listens on port 8211. To use another, set it on both sides:

- the Kit app: `--/exts/ovmcp.bridge/port=8212` on its command line;
- the server: `OMNIVERSE_MCP_PORT=8212` in its environment, or `"args": ["omniverse-mcp", "--port", "8212"]`.

Two Kit apps on one machine each need their own port, and each server the port of its Kit app. When the port is taken,
Kit logs `[MCP Bridge] Failed to start server` and the bridge doesn't answer.

## Kit on another machine

The bridge runs any Python the server sends, and the link is plain HTTP with a bearer token. Keep it off networks you
don't trust.

**The safer way, an SSH tunnel:** the bridge keeps listening on `127.0.0.1` on the Kit machine, and the tunnel
brings it to the server's machine.

1. On the Kit machine, give the bridge a fixed token, a long random value such as
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` prints:
   `--/exts/ovmcp.bridge/token=<the token>`.
2. On the server's machine: `ssh -N -L 8211:127.0.0.1:8211 <you>@<the Kit machine>`.
3. Give the server the same token: `"env": { "PYTHONPATH": "", "OMNIVERSE_MCP_TOKEN": "<the token>" }`.

**Over the network:** `--/exts/ovmcp.bridge/host=0.0.0.0` and the token on the Kit machine, and
`OMNIVERSE_MCP_HOST=<the Kit machine>` with `OMNIVERSE_MCP_TOKEN` on the server's. Kit warns at start that anyone on
the network who holds the token can run code in the app.

A container, or Kit running as another user, is the same case: the server can't read the token file, so set the
token on both sides. `OMNIVERSE_MCP_STATE_DIR`, set the same on both sides, moves the token file instead, when both
can reach one folder.

**Where files land:** captures and long answers come back over the link and are written on the server's machine.
`dump_scene` and recordings are written by Kit itself, so with a remote Kit they land on the Kit machine, under the
same path.

**A Kit machine without uv:** each [GitHub release](https://github.com/serionist/omniverse-mcp/releases) has the
bridge as `ovmcp.bridge-<version>.zip`. Take the one of your server's version, unzip it into a folder of its own,
which then holds `ovmcp.bridge/`, and add that folder to Kit's extension search paths.

## The output folder

The server makes `mcp_output/` in the folder the client starts it in, as soon as it starts, and returns paths
relative to that folder. Claude Code and VS Code start servers in the project, so the paths work as they are.

- Add `mcp_output/` to `.gitignore`.
- A client that starts servers elsewhere: give the server an absolute folder with `--output-dir` or
  `OMNIVERSE_MCP_OUTPUT_DIR`. The paths it returns are then relative to its working folder
  ([#41](https://github.com/serionist/omniverse-mcp/issues/41)).

## Updating

The server and the bridge come from one release; update both, then restart Kit and the client.

- **The plugin:** `claude plugin marketplace update omniverse-mcp`, `claude plugin update omniverse-mcp@omniverse-mcp`,
  restart Claude Code, then `/omniverse-mcp:setup`. Claude Code doesn't update plugins from other marketplaces by
  itself.
- **uvx:** `uvx omniverse-mcp@latest extension install` fetches the newest server and installs its bridge. On Windows,
  quit Kit first: a running Kit holds the bridge's folder.
- **Unpinned, uvx can move on its own:** uv rechecks PyPI every few minutes, so a new release can start without the
  bridge to match. The server then says so, in `get_sim_state`'s `note` or in the connection error, with the command
  that installs the matching bridge.
- **Pinned:** `"args": ["omniverse-mcp==0.2.0"]` stays on that release until you change the number, as the plugin
  does. Install the bridge with the same number: `uvx omniverse-mcp==<version> extension install`.

`get_sim_state` reports both versions, and a `note` when the bridge differs from the server's.

## Uninstalling

1. **In the Kit app:** turn **Omniverse MCP Bridge** off, and remove its folder from **Extension Search Paths**.
2. **The bridge's folders:** `omniverse-mcp extension path` prints the `exts` folder; delete the `omniverse-mcp`
   folder around it. On Linux the token files are in `~/.local/state/omniverse-mcp/` too.
3. **The client:** remove the `omniverse` server from its config; for the plugin,
   `claude plugin uninstall omniverse-mcp@omniverse-mcp` and `claude plugin marketplace remove omniverse-mcp`.
4. **uv's cache:** `uv cache clean omniverse-mcp`.
5. **Your projects:** delete `mcp_output/`.

## Troubleshooting

| What you see | Why, and what to do |
|---|---|
| "Missing or wrong bridge token" | The server can't read the bridge's token file: Kit runs as another user, in a container or on another machine. Set a token on both sides ([Kit on another machine](#kit-on-another-machine)). |
| "older than this MCP server", "speaks bridge protocol" | The server and the bridge come from different releases. Run the command the message names, then restart Kit. |
| "Kit app connection failed", refused | Kit isn't running, the bridge is off, or it listens on another port. `omniverse-mcp extension path` says whether the bridge is installed. |
| timed out | Kit is busy: on its first start Isaac Sim compiles shaders for minutes; a long physics step or script holds it too. Kit's console shows what it is doing. |
| Kit logs `[MCP Bridge] Failed to start server` | Another program holds the port ([Ports](#ports-and-two-kit-apps)). |
| The server doesn't start | `uvx` isn't on the PATH the client starts with: restart the client after installing uv. Claude Code's `/mcp` shows the error. |
| The server starts, then fails importing a package | A `PYTHONPATH` from Isaac Sim's environment reached it: set it empty in the client's config. |
| `get_sim_state` has a `note` | Kit runs another release's bridge: install the server's, as the note says, and restart Kit. |
| A black capture | Kit apps have no default light. `viewport_light(action="set", mode="Default")`, or `mode="camera"`. |
| `draw_debug` fails on Isaac Sim 6.2 | [#7](https://github.com/serionist/omniverse-mcp/issues/7). |
| Kit stops answering while a robot plays | [#5](https://github.com/serionist/omniverse-mcp/issues/5). |
