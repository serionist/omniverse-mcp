# Omniverse MCP Bridge (`ovmcp.bridge`)

The Kit extension behind [Omniverse MCP](https://github.com/serionist/omniverse-mcp): it lets an AI assistant work in
this Kit app through the `omniverse-mcp` MCP server.

## What it does

It runs an HTTP server inside the Kit app, on port 8211 by default, that takes JSON requests from the MCP server and
carries them out with Kit's and USD's APIs: reading and editing the stage, captures, physics, robots, recordings.

## The MCP server

This extension is the Kit half. The other half, the MCP server your AI client starts, comes from PyPI and must be this
release: `uvx omniverse-mcp==0.3.0` in your client's MCP config. The
[project's README](https://github.com/serionist/omniverse-mcp#install) says how, for each client.

## Installation

Two ways, one at a time: a second copy is a second version of this extension, and Kit's Autoload starts one.

- **From Kit's community registry,** in Kit's Extensions window: under **THIRD PARTY**, *Community - Unverified*,
  **INSTALL** (Kit warns first that NVIDIA hasn't verified it), then **ENABLED** and **AUTOLOAD**. Isaac Sim 5.1
  lists the registry; other Kit apps add it once under **Window > Extensions**, the menu button (three lines) at the
  top right, **Settings**, **Extension Registries**: `kit/community`,
  `https://dw290v42wisod.cloudfront.net/exts/kit/community`. Update it there too, with the server's pin.
- **With the server's own command:** `uvx omniverse-mcp==0.3.0 extension install` copies the extension of its release
  to your user data folder and prints the folder. Add that folder to Kit's extension search paths once (the same
  **Settings**, **Extension Search Paths**), then turn on **Omniverse MCP Bridge** with **AUTOLOAD**. A headless Kit
  takes `--ext-folder <that folder> --enable ovmcp.bridge` instead. `uvx omniverse-mcp extension path` prints the
  folder again.

It needs Kit 107 or later. The [project's README](https://github.com/serionist/omniverse-mcp#install) has the whole
setup, and the [changelog](https://github.com/serionist/omniverse-mcp/blob/main/CHANGELOG.md) what each release
changed.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `exts."ovmcp.bridge".host` | `127.0.0.1` | HTTP server bind address |
| `exts."ovmcp.bridge".port` | `8211` | HTTP server port |
| `exts."ovmcp.bridge".token` | `""` | Empty: a new random token at every start, written to a file only this user can read. Set it only for a remote MCP server, which gets the same value in `OMNIVERSE_MCP_TOKEN` |

Set them on Kit's command line, such as `--/exts/ovmcp.bridge/port=8212`. An edit to the installed `extension.toml`
is lost at the next install, which replaces the extension.

Every request needs the bridge token; requests from web pages are refused. See the main project's
[architecture notes](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md#the-bridge-token).

## Endpoints

The routes cover scene editing, robots, simulation, viewport capture, physics, geometry, USD files and variants. See
[docs/ARCHITECTURE.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md) for the list.
