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

The `omniverse-mcp` package carries this extension. `uvx omniverse-mcp extension install` copies the extension of its
own release to your user data folder and prints the folder. Add that folder to Kit's extension search paths once
(**Window > Extensions**, the menu (☰) at the top right, **Settings**), then turn on **Omniverse MCP Bridge** with
**Autoload**. A headless Kit takes `--ext-folder <that folder> --enable ovmcp.bridge` instead.
`uvx omniverse-mcp extension path` prints the folder again.

The [project's README](https://github.com/serionist/omniverse-mcp#install) has the whole setup.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `exts."ovmcp.bridge".host` | `127.0.0.1` | HTTP server bind address |
| `exts."ovmcp.bridge".port` | `8211` | HTTP server port |
| `exts."ovmcp.bridge".token` | `""` | Empty: a new random token at every start, written to a file only this user can read. Set it only for a remote MCP server, which gets the same value in `OMNIVERSE_MCP_TOKEN` |

Set them on Kit's command line, such as `--/exts/ovmcp.bridge/port=8212`. An edit to this folder's `extension.toml`
is lost at the next `extension install`, which replaces the folder.

Every request needs the bridge token; requests from web pages are refused. See the main project's
[architecture notes](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md#the-bridge-token).

## Endpoints

The routes cover scene editing, robots, simulation, viewport capture, physics, geometry, USD files and variants. See
[docs/ARCHITECTURE.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md) for the list.
