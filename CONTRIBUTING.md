# Contributing

Contributions to Omniverse MCP are welcome. This document explains how to get started.

## Development Setup

### Prerequisites

- NVIDIA Omniverse Kit-based application, Kit 107 or newer (Isaac Sim 5.x and up)
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Git

### Setting Up the Development Environment

1. Clone the repository and install the server with its dev tools:
   ```bash
   git clone https://github.com/serionist/omniverse-mcp.git
   cd omniverse-mcp
   uv sync
   ```
   `uv sync` makes `.venv/` with the server installed in editable mode, plus the test tools (`uv.lock` pins them).

2. Point your Kit app at the extension: **Window > Extensions > Settings > Extension Search Paths**, add the repo's
   `extension/` folder, then turn on **Omniverse MCP Bridge** (`ovmcp.bridge`) with autoload. Kit loads the files in
   place, so a restart picks up your edits.

## Project Structure

```
src/omniverse_mcp/           # MCP server (standalone Python process)
  server.py                  # FastMCP server, output helpers, resources
  client.py                  # HTTP client -- add new endpoint methods here
  tools/                     # MCP tools by area -- add new tools here

extension/ovmcp.bridge/      # Omniverse Kit extension (runs inside the app)
  config/extension.toml      # Extension id, version and settings
  ovmcp/bridge/              # Kit-bound: imports omni, carb, pxr
    extension.py             # Lifecycle; the route table -- register new routes here
    handlers/                # Handler implementations -- add new handlers here
    formatter.py             # Prim-block text format
  ovmcp/core/                # Kit-free: HTTP server, token, framing, isolation; unit-tested without Kit

tests/                       # pytest; test_integration.py and test_scenarios.py need a running Kit app
```

## Adding a New Tool

A new MCP tool requires changes in three places:

### 1. Add the handler (`extension/ovmcp.bridge/ovmcp/bridge/handlers/<area>.py`)

```python
async def handle_my_feature(data, send_response):
    """Handle /my/endpoint requests."""
    param = data.get("param", "default")

    # Access USD stage
    stage = _get_stage()
    if not stage:
        await send_response({"status": "error", "error": "No stage"})
        return

    # Do work...
    result = {"key": "value"}
    await send_response({"status": "success", "result": result})
```

### 2. Register the route (`extension/ovmcp.bridge/ovmcp/bridge/extension.py`)

Add the endpoint to the `_routes` dict in the `Extension` class:

```python
self._routes = {
    # ... existing routes ...
    "/my/endpoint": handlers.handle_my_feature,
}
```

### 3. Add the HTTP client method (`src/omniverse_mcp/client.py`)

```python
def my_feature(self, param: str) -> dict:
    return self._post("/my/endpoint", {"param": param})
```

### 4. Add the MCP tool (`src/omniverse_mcp/tools/<area>.py`)

```python
@mcp.tool()
def my_feature(param: str = "default") -> str:
    """Description for the AI assistant.

    Args:
        param: What this parameter does
    """
    resp = _client.my_feature(param)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Result: {r['key']}"
```

### 5. Update documentation

- Add the tool to `docs/TOOLS.md`
- Add the route to `docs/ARCHITECTURE.md`
- Update the tool count in `README.md` if applicable

## Running Tests

### Unit tests (no Isaac Sim needed)

```bash
uv run pytest
```

### Integration tests (requires running Omniverse app with extension enabled)

```bash
OMNIVERSE_MCP_SIM=1 uv run pytest tests/test_integration.py tests/test_scenarios.py
```

Without `OMNIVERSE_MCP_SIM=1` these skip when no Kit app answers; with it, they fail instead.

### AI-driven scenario tests

Open `test_project/` in an MCP-compatible AI client and run through the scenarios in `test_project/scenarios.md`.

## Code Style

- Follow existing patterns in the codebase
- Use type hints for function parameters
- Keep handler functions async
- Use the prim-block text format for scene/prim data (not JSON)
- Write docstrings for MCP tools -- they are shown to AI assistants

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run the tests
5. Submit a pull request

## Reporting Issues

Please include:
- Omniverse application and version (e.g., Isaac Sim 5.1)
- OS and Python version
- Steps to reproduce
- Error messages or tracebacks from the application console
- MCP client being used

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
