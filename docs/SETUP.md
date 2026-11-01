# Setup in depth

The [README](../README.md#install) has the short path. This page has the rest: each MCP client's config, the bridge
from Kit's community registry, headless Kit, ports, Kit on another machine, the output folder, updating, uninstalling
and troubleshooting.

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

## From Kit's community registry

The bridge is listed in Kit's community extension registry too, so a Kit app can install it from its Extensions
window instead of `extension install`. NVIDIA doesn't review that registry: Kit marks the bridge *Community -
Unverified* and asks before it installs it. The server still comes from PyPI, and must be the bridge's release.

1. **The registry, once.** Isaac Sim 5.1 lists it already. In Isaac Sim 6.2 and other Kit apps: **Window >
   Extensions**, the menu (☰) at the top right, **Settings**, then under **Extension Registries** the green **+**,
   with the name `kit/community` and the URL `https://dw290v42wisod.cloudfront.net/exts/kit/community`.
2. **The bridge:** search for `ovmcp` under **THIRD PARTY**, open **Omniverse MCP Bridge**, **Install**, and accept
   Kit's warning. Then turn it on, with **Autoload**. Kit offers it to Kit 107 and later.
3. **The server, at the bridge's version:** Kit shows the version beside the bridge's name, and its Overview names the
   server, `uvx omniverse-mcp==<that version>`. Pin it in your client's config, `"args": ["omniverse-mcp==<version>"]`,
   so uvx doesn't move to another release on its own.

- **One source at a time.** A bridge from the registry and one from `extension install` are two copies of one
  extension, and Autoload starts one version of it. Keep one: uninstall the registry's in the Extensions window, or
  remove the other's folder from **Extension Search Paths**.
- **After a release,** the registry lists it the next day, where PyPI has it at once. A server ahead of the bridge
  says so in `get_sim_state`'s `note`: keep the server pinned, and update the bridge once Kit lists the release.
- **Headless Kit** takes the bridge from `extension install` ([Headless Kit](#headless-kit)): turning an extension
  on doesn't download it from a registry, and only the window's **Install** does.
- **With the plugin,** use its setup: it installs the bridge of the plugin's own release, at once.

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
  unknown command-line arguments reach Kit too, so `python.sh my_script.py --ext-folder <folder> --enable
  ovmcp.bridge` works as well.
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

First install the bridge of the server's release on the Kit machine, `uvx omniverse-mcp==<version> extension
install` there (or the release's zip, below), and pin the server to the same `omniverse-mcp==<version>`: unpinned,
two machines can each fetch a different release.

**The safer way, an SSH tunnel:** the bridge keeps listening on `127.0.0.1` on the Kit machine, and the tunnel
brings it to the server's machine.

1. On the Kit machine, give the bridge a fixed token, a long random value such as
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` prints:
   `--/exts/ovmcp.bridge/token=<the token>`.
2. On the server's machine: `ssh -N -L 8211:127.0.0.1:8211 <you>@<the Kit machine>`.
3. Give the server the same token: `"env": { "PYTHONPATH": "", "OMNIVERSE_MCP_TOKEN": "<the token>" }`.

Kit's command line, the token in it, is visible to every user of the Kit machine (`ps` on Linux): there, a token is
only as private as the machine.

**Over the network:** `--/exts/ovmcp.bridge/host=0.0.0.0` and the token on the Kit machine, and
`OMNIVERSE_MCP_HOST=<the Kit machine>` with `OMNIVERSE_MCP_TOKEN` on the server's. Kit warns at start that anyone on
the network who holds the token can run code in the app.

A container, or Kit running as another user, is the same case: the server can't read the token file, so set the
token on both sides. Only for the same user, such as a container running as your user with a folder of yours
mounted, can `OMNIVERSE_MCP_STATE_DIR`, set the same on both sides, move the token file there instead; that folder
must be one only you can read.

**Where files land:** captures and long answers come back over the link and are written on the server's machine.
`get_scene_tree`'s dump and recordings are written by Kit itself, so with a remote Kit they land on the Kit machine,
under the same path.

**A Kit machine without uv:** each [GitHub release](https://github.com/serionist/omniverse-mcp/releases) has the
bridge as `ovmcp.bridge-<version>.zip`, and the same zip under the two names Kit's community registry reads. Take the
one of your server's version, unzip it into a folder of its own, which then holds `ovmcp.bridge/`, and add that folder
to Kit's extension search paths. Or install the bridge in Kit from the registry
([From Kit's community registry](#from-kits-community-registry)).

## The output folder

The server writes to `mcp_output/` in the folder the client starts it in, made with the first file. It gives a file
under that folder by its relative path, such as `mcp_output/captures/viewport_0001.png`, and any other by its
absolute path. Claude Code and VS Code start servers in the project, so the short paths work as they are.

- Add `mcp_output/` to `.gitignore`.
- A client that starts servers elsewhere: give the server an absolute folder with `--output-dir` or
  `OMNIVERSE_MCP_OUTPUT_DIR`, and the tools give absolute paths into it.

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
- **Pinned:** `"args": ["omniverse-mcp==0.3.0"]` stays on that release until you change the number, as the plugin
  does. Install the bridge with the same number: `uvx omniverse-mcp==<version> extension install`.
- **The bridge from Kit's community registry:** update it in Kit's Extensions window, once Kit lists the release, and
  the server's pin to the same number.

`get_sim_state` reports both versions, and a `note` when the bridge differs from the server's.

## Uninstalling

1. **In the Kit app:** turn **Omniverse MCP Bridge** off, and remove its folder from **Extension Search Paths**; one
   from Kit's community registry, uninstall in the Extensions window.
2. **The bridge's folders:** `uvx omniverse-mcp extension path` prints the `exts` folder; delete the `omniverse-mcp`
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
| "Kit app connection failed", refused | Kit isn't running, the bridge is off, or it listens on another port. `uvx omniverse-mcp extension path` says whether the bridge is installed. |
| timed out | Kit is busy: on its first start Isaac Sim compiles shaders for minutes; a long physics step or script holds it too. Kit's console shows what it is doing. |
| Kit logs `[MCP Bridge] Failed to start server` | Another program holds the port ([Ports](#ports-and-two-kit-apps)). |
| The server doesn't start | `uvx` isn't on the PATH the client starts with: restart the client after installing uv. Claude Code's `/mcp` shows the error. |
| The server starts, then fails importing a package | A `PYTHONPATH` from Isaac Sim's environment reached it: set it empty in the client's config. |
| `get_sim_state` has a `note` | Kit runs another release's bridge: install the server's, as the note says, and restart Kit. With the bridge from Kit's community registry, install the server's version in the Extensions window; a copy from `extension install` beside it is a second copy ([From Kit's community registry](#from-kits-community-registry)). |
| Isaac Sim 5.1 crashes as it starts, in `rtx.scenedb.plugin` | A fault of 5.1's renderer on NVIDIA's 595 drivers, seen on Linux: run 5.1 on a 580 driver, or use Isaac Sim 6.2. |
| A black capture | Kit apps have no default light. `viewport_light(action="set", mode="Default")`, or `mode="camera"`. |
| Kit stops answering the first time physics plays with a robot | 0.2.0's bridge hung Kit while Isaac Sim cooked the robot's collision meshes: update to 0.2.1 or later, and install its bridge ([#5](https://github.com/serionist/omniverse-mcp/issues/5)). |
