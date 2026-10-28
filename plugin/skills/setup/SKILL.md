---
name: setup
description: >-
  Use when the user asks to set up, install, connect or update Omniverse MCP, when a tool says it cannot reach the
  Kit app or that the extension is older than the server, or when Isaac Sim or another Kit app should be driven from
  here for the first time. Installs the Kit extension of this plugin's release, has the user point Kit at it and turn
  it on, and checks the connection with get_sim_state.
allowed-tools: mcp__plugin_omniverse-mcp_omniverse__get_sim_state
---

# Set up Omniverse MCP

The plugin's MCP server talks to a Kit app (Isaac Sim, USD Composer) through the Kit extension `ovmcp.bridge`, which
must come from the same release. This skill installs that extension, has the user turn it on in Kit, and checks the
two can talk. Kit's settings are the user's: say what to click, never edit Kit's config files.

## Steps

1. **Check first.** Call `get_sim_state`.
   - It answers, with `extension_version` equal to `server_version`: the setup is done. Say so, with the up axis,
     units and prim count it reports, and stop.
   - It answers with another `extension_version` (a `note` line says so): Kit runs another release's extension, as
     after an update of the plugin. Go on with step 2.
   - It fails: its message says why; go on with the step it points at (step 4 lists them).
   - There is no such tool: the plugin's server didn't start. `/mcp` shows its error. Without `uv` the user installs
     it (https://docs.astral.sh/uv/getting-started/installation/) and restarts Claude Code; a version not found means
     this release isn't on PyPI yet.
2. **Install the extension** of this plugin's release, with the user's yes:

   ```
   uvx omniverse-mcp==0.1.0 extension install
   ```

   It copies `ovmcp.bridge` into the user's data folder, in place of an older one, and prints the folder Kit needs.
   On Windows, "Could not install ... quit it" means a Kit app has the extension loaded: ask the user to quit it,
   then run the command again. When the folder is already on Kit's search path (an update), skip step 3: restarting
   Kit loads the new extension.
3. **Point Kit at the folder, once,** by the user's hand, in the Kit app:
   - **Window > Extensions**, the menu (☰) at the top right, **Settings**;
   - under **Extension Search Paths**, the green **+**, then the folder the command printed;
   - search for `ovmcp`, under **THIRD PARTY**: turn **Omniverse MCP Bridge** on, and **Autoload**;
   - quit Kit with **File > Exit**, which is when Kit saves these settings, and start it again.

   A headless or scripted Kit takes `--ext-folder <the folder> --enable ovmcp.bridge` on its command line instead.
   A user who had the extension from a clone of the repo (`isaacsim.mcp.bridge` or the clone's `extension/` folder)
   turns that one off and removes its search path, so Kit loads one copy.
4. **Check again** with `get_sim_state`: `extension_version` equals `server_version`. The Kit console shows
   `[ext: ovmcp.bridge-0.1.0] startup` once the extension runs.
   - "Kit app connection failed": Kit isn't running, the extension is off, or it listens on another port than the
     server (`OMNIVERSE_MCP_PORT`, 8211 by default).
   - "Missing or wrong bridge token": Kit runs as another user or on another machine; the README's [bridge
     token](https://github.com/serionist/omniverse-mcp#the-bridge-token) section says how to set one by hand.
   - "older than this MCP server" or "speaks bridge protocol": the extension is from another release; run step 2
     again and restart Kit.
5. **Keep the outputs out of git.** The server writes captures and long answers to `mcp_output/` in the project.
   When the project is a git repository and `.gitignore` doesn't name it, offer to add the line `mcp_output/`.

## Done means

- `get_sim_state` answers from the user's Kit app, with `extension_version` equal to `server_version`.
- The user knows the extension autoloads, and that after updating the plugin this skill updates the extension.

## Never

- Edit Kit's `user.config.json` or other settings files: Kit rewrites them when it exits.
- Install the extension, or change `.gitignore`, without the user's yes.
- Set `OMNI_KIT_ACCEPT_EULA` or accept NVIDIA's licence for the user.
