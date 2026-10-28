# Omniverse MCP Bridge Extension (`ovmcp.bridge`)

An Omniverse Kit extension that provides an HTTP bridge for AI assistants to control Omniverse applications via the Model Context Protocol (MCP).

## What It Does

This extension runs an HTTP server (default port 8211) inside your Omniverse application that accepts JSON commands and executes them using the full Omniverse/USD API. It is the backend for the [Omniverse MCP](https://github.com/serionist/omniverse-mcp) server.

## Installation

The `omniverse-mcp` package carries this extension. `omniverse-mcp extension install` copies the copy of its own
release to your user data folder and prints the folder to add to Kit's extension search paths (**Window > Extensions**,
the menu, **Settings**), once; then turn on `ovmcp.bridge` with **Autoload**. Or start Kit with
`--ext-folder <that folder> --enable ovmcp.bridge`. `omniverse-mcp extension path` prints the folder again.

See the [main project README](https://github.com/serionist/omniverse-mcp) for the whole setup.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `exts."ovmcp.bridge".host` | `127.0.0.1` | HTTP server bind address |
| `exts."ovmcp.bridge".port` | `8211` | HTTP server port |
| `exts."ovmcp.bridge".token` | `""` | Empty: a new random token at every start, written to a file only this user can read. Set it only for a remote MCP server, which gets the same value in `OMNIVERSE_MCP_TOKEN` |

Every request needs the bridge token; requests from web pages are refused. See the main project's
[architecture notes](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md#the-bridge-token).

## Endpoints

The extension exposes 42 HTTP endpoints for scene manipulation, robot control, simulation management, viewport capture, physics, geometry analysis, USD operations, variant management, and more. See [docs/ARCHITECTURE.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md) for the complete endpoint list.
