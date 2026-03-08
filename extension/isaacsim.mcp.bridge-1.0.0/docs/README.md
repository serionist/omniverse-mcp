# Omniverse MCP Bridge Extension

An Omniverse Kit extension that provides an HTTP bridge for AI assistants to control Omniverse applications via the Model Context Protocol (MCP).

## What It Does

This extension runs an HTTP server (default port 8211) inside your Omniverse application that accepts JSON commands and executes them using the full Omniverse/USD API. It is the backend for the [Omniverse MCP](https://github.com/serionist/omniverse-mcp) server.

## Installation

See the [main project README](https://github.com/serionist/omniverse-mcp) for installation instructions.

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `exts."isaacsim.mcp.bridge".host` | `127.0.0.1` | HTTP server bind address |
| `exts."isaacsim.mcp.bridge".port` | `8211` | HTTP server port |
| `exts."isaacsim.mcp.bridge".scene_tree_max_depth` | `8` | Default scene tree traversal depth |

## Endpoints

The extension exposes 42 HTTP endpoints for scene manipulation, robot control, simulation management, viewport capture, physics, geometry analysis, USD operations, variant management, and more. See [docs/ARCHITECTURE.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/ARCHITECTURE.md) for the complete endpoint list.
