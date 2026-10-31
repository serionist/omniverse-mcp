# Omniverse MCP without the plugin

> **For MCP clients other than Claude Code with the plugin**: Cursor, VS Code, Codex, Claude Desktop, or Claude Code
> with the server added by hand. The plugin brings all of this as skills
> ([README](https://github.com/serionist/omniverse-mcp#install)).

## What your client already has

The server sends much the same context as the one below to every client as its MCP instructions, and most clients
pass them to the model. Paste the [Context](#context) section into your instruction file (`AGENTS.md`, or `.cursor/rules/` in Cursor)
only if your client ignores a server's instructions.

## The workflows

The plugin's skills hold the workflows and the traps of each kind of work. Each is a plain Markdown file: copy the ones
your work needs into your client's instructions, or, for Codex, into `.agents/skills/<name>/SKILL.md` in your
project. Their `allowed-tools` lines are Claude Code's, and other clients ignore them.

| Skill | When |
|---|---|
| [setup](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/setup/SKILL.md) | installing the Kit extension, connecting, a tool that cannot reach Kit |
| [scene](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/scene/SKILL.md) | looking at a stage, placing and checking prims, lighting and black captures |
| [geometry](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/geometry/SKILL.md) | face counts, comparing prims and variants, variant sets, flattening and exports |
| [simulate](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/simulate/SKILL.md) | physics, robots, forces, recording a run |
| [script](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/script/SKILL.md) | `execute_script`, and the traps of Kit's Python |

Every tool, with its parameters and hints, is in [TOOLS.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/TOOLS.md).

## Context

You are connected to a running NVIDIA Omniverse Kit app (Isaac Sim, USD Composer) through the Omniverse MCP server.
The scene is a USD stage: a hierarchy of prims with paths such as `/World/Robot/base`. Edits apply at once; things
move only while physics plays.

- **Call `get_sim_state` first:** the up axis (Y or Z), the stage's units, and whether physics is playing.
- **Look before you act, and after:** `get_scene_tree` for what is there, with `include_properties` for many prims'
  values, `capture_viewport` or `inspect_prim` for how it looks. Never assume a change worked.
- **Files, not inline data:** images and long answers are written under `mcp_output/` in the server's working folder,
  and the tool returns the path; open it with your file tool. `capture_viewport(include_image=True)` also returns the
  image inline, which costs context like any image. Text comes as prim blocks: a `[/prim/path]` header, then
  `key = value` lines.
- **Look Kit APIs up before scripting:** before writing `execute_script` code, use Context7 (library
  `isaac-sim/isaacsim`) or NVIDIA's documentation for the app's version. Models are not trained on these APIs.
- **When a tool fails,** `get_logs(min_level="warn")` shows what the Kit app reported.
