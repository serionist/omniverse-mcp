# The Omniverse MCP plugin for Claude Code

The plugin connects Claude Code to a running NVIDIA Omniverse Kit app (Isaac Sim, USD Composer) through the
`omniverse-mcp` MCP server and its Kit extension `ovmcp.bridge`: Claude can look at the stage, edit it, run physics,
drive robots and record what happens. Not affiliated with NVIDIA.

## Install

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), which runs the server, and a Kit app of
Kit 107 or later (Isaac Sim 5.x and up). In Claude Code:

```
/plugin marketplace add serionist/omniverse-mcp
/plugin install omniverse-mcp@omniverse-mcp
```

Then `/omniverse-mcp:setup` installs the Kit extension of the same release, walks you through turning it on in Kit,
and checks the connection.

## What it brings

| Part | What it does |
|---|---|
| the MCP server `omniverse` | `uvx omniverse-mcp==0.1.0`, the server of this plugin's release; its tools show as `mcp__plugin_omniverse-mcp_omniverse__<tool>` ([the tools](https://github.com/serionist/omniverse-mcp/blob/main/docs/TOOLS.md)). Images and long answers go to `mcp_output/` in your project |
| `/omniverse-mcp:setup` | installs the extension, has you point Kit at it, checks with `get_sim_state` |
| `/omniverse-mcp:scene` | look before acting: captures, bounds, placing and checking prims, lighting |
| `/omniverse-mcp:geometry` | face counts, comparing prims and variants, variant sets, flattening and exports |
| `/omniverse-mcp:simulate` | physics, robots, forces, recording a run |
| `/omniverse-mcp:script` | `execute_script`, with the API looked up first |

Claude uses the skills on its own when a request fits them. Each pre-approves only tools that read (the
`readOnlyHint` ones): every tool that edits the stage, writes a file or runs code still asks you.

## Settings

The server reads `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT` (8211 by default) and `OMNIVERSE_MCP_OUTPUT_DIR` from
the environment Claude Code starts in, and `OMNIVERSE_MCP_TOKEN` for a Kit app on another machine; see the
[README](https://github.com/serionist/omniverse-mcp#configuration).

## Updating

`claude plugin marketplace update omniverse-mcp` fetches the marketplace, and
`claude plugin update omniverse-mcp@omniverse-mcp` moves the plugin to its newest release; restart Claude Code. Then
run `/omniverse-mcp:setup` again, so the Kit extension matches the server, and restart Kit.
