# Omniverse MCP

An [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server that gives AI assistants full control over NVIDIA Omniverse applications -- including **Isaac Sim 5.1+**, USD Composer, and any Omniverse Kit-based app. Inspect scenes, manipulate objects, control robots, run physics simulations, capture viewports, record sessions, and manage extensions.

```
AI Assistant  <--MCP/stdio-->  MCP Server  <--HTTP/REST-->  Omniverse Extension
(any MCP client)               (Python)                     (runs inside Kit app)
```

## What Can It Do?

**32 MCP tools** across 8 categories:

| Category | Tools | Description |
|----------|-------|-------------|
| **Scene** | `get_scene_tree`, `dump_scene`, `get_prim_properties`, `get_prim_bounds`, `set_prim_transform`, `create_prim`, `delete_prim`, `set_material`, `clone_prim`, `set_visibility`, `save_scene`, `new_scene` | Full scene graph control -- create, query, transform, and manage USD prims |
| **Robot** | `create_robot`, `get_robot_info`, `get_joint_states`, `set_joint_targets` | Spawn robots from the asset library (Franka, G1, Spot, etc.), query joints, drive positions |
| **Camera** | `set_camera`, `look_at_prim`, `inspect_prim`, `capture_viewport` | Position cameras, orbit-capture from multiple angles, take viewport screenshots |
| **Simulation** | `sim_control`, `get_sim_state` | Play/pause/stop/step simulation, query state (time, FPS, up axis) |
| **Recording** | `start_recording`, `stop_recording`, `get_recording_frame` | Capture simulation frames + prim state over time for analysis |
| **Physics** | `set_physics_properties`, `apply_force`, `raycast` | Set mass/friction/restitution, apply forces, cast rays for spatial queries |
| **Debug** | `draw_debug` | Draw lines, spheres, and points in the viewport for visualization |
| **Extensions** | `manage_extensions` | List, enable, and disable Omniverse extensions |

**Key capabilities:**
- **Spatial reasoning** -- bounding box queries + multi-angle inspection
- **Simulation recording** -- capture frames + prim state during physics, review any frame after
- **File-based output** -- large scene dumps in grep-friendly text format, images saved as PNGs
- **Arbitrary scripting** -- run any Python code inside the sim via `execute_script`; also serves as a fallback if any tool fails
- **10 built-in robots** -- franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal

## Setup

### 1. Clone the repo and install the MCP server

```bash
git clone https://github.com/serionist/omniverse-mcp.git
cd omniverse-mcp
```

Then install using one of these options:

<details>
<summary><b>Conda</b> (recommended)</summary>

```bash
conda create -n omniverse-mcp python=3.11 -y
conda activate omniverse-mcp
pip install .
```

**`.mcp.json`** for your project (step 3):
```json
{
  "mcpServers": {
    "omniverse": {
      "command": "<CONDA_PATH>/envs/omniverse-mcp/python",
      "args": ["-m", "isaac_sim_mcp"],
      "env": { "PYTHONPATH": "" }
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```
Replace `<CONDA_PATH>` with your conda path. Find it by running `conda env list` -- the path shown next to `omniverse-mcp` is `<CONDA_PATH>/envs/omniverse-mcp`.

</details>

<details>
<summary><b>venv</b></summary>

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install .
```

**`.mcp.json`** for your project (step 3):
```json
{
  "mcpServers": {
    "omniverse": {
      "command": "<VENV_PATH>/bin/python",
      "args": ["-m", "isaac_sim_mcp"],
      "env": {}
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```
Replace `<VENV_PATH>` with the full path to your venv. Find it by running `python -c "import sys; print(sys.prefix)"` with the venv activated. On Windows, use `<VENV_PATH>/Scripts/python.exe`.

</details>

<details>
<summary><b>Global</b></summary>

```bash
pip install .
```

**`.mcp.json`** for your project (step 3):
```json
{
  "mcpServers": {
    "omniverse": {
      "command": "omniverse-mcp",
      "env": {}
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

</details>

> **Updating:** `git pull && pip install .` (or `pip install -e .` for development -- edits take effect without reinstalling)

### 2. Add the extension to your Omniverse app

You only need to do this once -- after that the extension autoloads every time.

1. Open Isaac Sim (or any Kit app)
2. **Window > Extensions > Gear icon (⚙)**
3. Under **Extension Search Paths**, click **+** and add the full path to the `extension/` folder in the cloned repo
   - Example: `/home/you/omniverse-mcp/extension` or `C:\Users\you\omniverse-mcp\extension`
4. Search for **"MCP Bridge"**, toggle it **ON**, and check **Autoload**

You should see in the console:
```
[ext: isaacsim.mcp.bridge-1.0.0] startup
```

> **Updating the extension:** `git pull` in the repo. Changes take effect on next app restart.

### 3. Add the AI guide to your project

Copy [`docs/AI_GUIDE.md`](docs/AI_GUIDE.md) into your project's AI instruction file so the assistant knows the recommended workflow, available tools, and common pitfalls:

| Client | Where to paste |
|--------|----------------|
| Claude Code | `CLAUDE.md` in project root |
| Cursor | `.cursorrules` in project root |
| Windsurf | `.windsurfrules` in project root |
| Other | Check your client's docs |

### 4. Go

1. Make sure your Omniverse app is running (extension autoloads)
2. Open your AI client in a project with `.mcp.json`
3. Ask: *"What's in the scene right now?"*

## Why Context7?

AI models are not trained on Omniverse/Isaac Sim APIs and will hallucinate function names, parameters, and patterns. [Context7](https://github.com/upstash/context7) provides up-to-date API docs on demand so the AI can look up the correct API before writing `execute_script` code. This dramatically improves reliability. Requires Node.js.

## Examples

> "Create a table with a red cube on top of it, and point a spotlight at it."

> "Spawn a Franka arm at the origin, then move its joints to a pick-ready pose."

> "Start recording, play the sim for 3 seconds, then show me what happened to the robot."

> "Move the apple so it's sitting on top of the desk. Use bounding boxes to compute the correct position."

> "Inspect the G1 robot from all angles so I can see its current pose."

## Configuration

### MCP Server Flags

```
--isaac-host    Omniverse extension host (default: 127.0.0.1)
--isaac-port    Omniverse extension port (default: 8211)
--output-dir    Directory for file outputs (default: ./mcp_output/)
```

### Extension Settings

In `extension.toml`:
```toml
[settings]
exts."isaacsim.mcp.bridge".host = "127.0.0.1"
exts."isaacsim.mcp.bridge".port = 8211
```

## Troubleshooting

**"Cannot connect to Isaac Sim"** -- Is the app running with MCP Bridge enabled? Check console for `[ext: isaacsim.mcp.bridge-1.0.0] startup`. Make sure port 8211 is free.

**MCP server fails to start** -- If using conda, use the direct `python.exe` path (not `conda run`). Set `"PYTHONPATH": ""` in env if you get import errors.

**Viewport capture returns black** -- First capture after launch needs a warmup frame. Capture twice.

**Tools return errors** -- Check the Omniverse console for tracebacks. Some tools need the sim to have played once (`get_joint_states`, `raycast`). Robot tools require Isaac Sim specifically.

## Documentation

- [Tool Reference](docs/TOOLS.md) -- All 32 tools with parameters and examples
- [Architecture](docs/ARCHITECTURE.md) -- How the two-process bridge works
- [AI Assistant Guide](docs/AI_GUIDE.md) -- Template for your project's AI instructions
- [Contributing](CONTRIBUTING.md) -- How to contribute

## License

[MIT](LICENSE)
