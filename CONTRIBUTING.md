# Contributing

Contributions to Omniverse MCP are welcome. This document explains how to get started.

## Development Setup

### Prerequisites

- NVIDIA Omniverse Kit-based application (Isaac Sim 5.1+, USD Composer, etc.)
- Python 3.10+ (conda recommended)
- Git

### Setting Up the Development Environment

1. Clone the repository:
   ```bash
   git clone https://github.com/serionist/omniverse-mcp.git
   cd omniverse-mcp
   ```

2. Create a conda environment:
   ```bash
   conda create -n omniverse-mcp python=3.11 -y
   conda activate omniverse-mcp
   ```

3. Install in editable mode:
   ```bash
   pip install -e .
   ```

4. Install the extension in your Omniverse application (symlink for development):

   **Linux:**
   ```bash
   ln -s /path/to/omniverse-mcp/extension \
       /path/to/omniverse-app/exts/isaacsim.mcp.bridge
   ```

   **Windows (PowerShell as Admin):**
   ```powershell
   New-Item -ItemType SymbolicLink `
       -Path "<OMNIVERSE_APP_PATH>\exts\isaacsim.mcp.bridge" `
       -Target "<REPO_PATH>\extension"
   ```

5. Enable the extension (Window > Extensions > search "MCP Bridge").

## Project Structure

```
isaac_sim_mcp/           # MCP server (standalone Python process)
  server.py              # Tool definitions -- add new tools here
  client.py              # HTTP client -- add new endpoint methods here

extension/               # Omniverse Kit extension (runs inside app)
  isaacsim/mcp/bridge/
    extension.py         # HTTP server + routing -- register new routes here
    handlers.py          # Handler implementations -- add new handlers here
    formatter.py         # Text format utilities
```

## Adding a New Tool

A new MCP tool requires changes in three places:

### 1. Add the handler (`extension/.../handlers.py`)

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

### 2. Register the route (`extension/.../extension.py`)

Add the endpoint to the `_routes` dict in the `Extension` class:

```python
self._routes = {
    # ... existing routes ...
    "/my/endpoint": handlers.handle_my_feature,
}
```

### 3. Add the HTTP client method (`isaac_sim_mcp/client.py`)

```python
def my_feature(self, param: str) -> dict:
    return self._post("/my/endpoint", {"param": param})
```

### 4. Add the MCP tool (`isaac_sim_mcp/server.py`)

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
python -m pytest tests/test_client.py -v
```

### Integration tests (requires running Omniverse app with extension enabled)

```bash
python -m pytest tests/test_integration.py -v
```

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
