# Omniverse MCP - AI assistant guide

> **For MCP clients without the Claude Code plugin.** Copy this file into your project's instruction file
> (`AGENTS.md`, `.cursorrules`, or your client's equivalent). Claude Code users install the plugin instead, whose
> skills hold the same guidance ([README](https://github.com/serionist/omniverse-mcp#install)).

## Context

You are connected to a running NVIDIA Omniverse Kit app (Isaac Sim, USD Composer) through the Omniverse MCP server.
The scene is a USD stage: a hierarchy of prims with paths such as `/World/Robot/base`. Edits apply at once; things
move only while physics plays.

- **Call `get_sim_state` first:** the up axis (Y or Z), the stage's units, and whether physics is playing.
- **Look before you act, and after:** `get_scene_tree` or `dump_scene` for what is there, `capture_viewport` or
  `inspect_prim` for how it looks. Never assume a change worked.
- **Files, not inline data:** images and long answers are written under `mcp_output/` in the working folder, and the
  tool returns the path; open it with your file tool. `capture_viewport(include_image=True)` also returns the image
  inline, at about 50K tokens. Text comes as prim blocks: a `[/prim/path]` header, then `key = value` lines.
- **Look Kit APIs up before scripting:** before writing `execute_script` code, use Context7 (library
  `isaac-sim/isaacsim`) or NVIDIA's documentation for the app's version. Models are not trained on these APIs.
- **When a tool fails,** `get_logs(min_level="warn")` shows what the Kit app reported.

## Workflows

Each workflow is a skill of the Claude Code plugin, and each skill is a plain Markdown file: copy the ones your work
needs below this guide, or point your client at them.

| Skill | When |
|---|---|
| [setup](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/setup/SKILL.md) | installing the Kit extension, connecting, a tool that cannot reach Kit |
| [scene](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/scene/SKILL.md) | looking at a stage, placing and checking prims, lighting and black captures |
| [geometry](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/geometry/SKILL.md) | face counts, comparing prims and variants, variant sets, flattening and exports |
| [simulate](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/simulate/SKILL.md) | physics, robots, forces, recording a run |
| [script](https://github.com/serionist/omniverse-mcp/blob/main/plugin/skills/script/SKILL.md) | `execute_script`, and the traps of Kit's Python |

Every tool, with its parameters and hints, is in [TOOLS.md](https://github.com/serionist/omniverse-mcp/blob/main/docs/TOOLS.md).
