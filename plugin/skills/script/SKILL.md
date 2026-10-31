---
name: script
description: >-
  Use when an Omniverse or Isaac Sim task needs Python run inside the Kit app with execute_script: something no tool
  does, a batch of tool calls in one go, a tool that failed and needs the same thing done by hand, or Kit and USD APIs
  to look up before writing that code.
allowed-tools: >-
  mcp__plugin_omniverse-mcp_omniverse__get_sim_state mcp__plugin_omniverse-mcp_omniverse__get_logs
  mcp__plugin_omniverse-mcp_omniverse__get_prim_properties
---

# Script inside Kit

`execute_script` runs any Python inside the Kit app, with the user's rights on their machine, so it always asks
first. Kit's and Isaac Sim's APIs change between releases and models are not trained on them: look an API up before
using it, never guess.

## Steps

1. **Prefer a tool.** A tool that does the job is checked, bounded and safer; script only what no tool covers.
2. **Look the API up** with Context7, library `isaac-sim/isaacsim`, for the app's version: ask the user, or in Isaac
   Sim run `from isaacsim.core.version import get_version; result = get_version()`. Without Context7, NVIDIA's
   documentation for that version.
3. **Write the script.** Already imported: `omni`, `carb`, `Usd`, `UsdGeom`, `UsdLux`, `UsdPhysics`, `Sdf`, `Gf` and
   `mcp`. Set `result = <value>` to return data. `await mcp.<handler>(...)` calls the tools' handlers from the
   script, so one script can capture, measure and move:

   ```python
   bounds = await mcp.prim_bounds("/World/Robot")
   await mcp.set_camera([bounds["result"]["center"][0] + 3, 3, 3])
   result = bounds["result"]
   ```

4. **Run it** with `execute_script`, then check the result, and `get_logs(min_level="warn")` when it fails: the
   error result carries the traceback's last lines, the log what Kit reported around it.

## Traps

| Trap | What to do |
|---|---|
| Backslashes in a Windows path | raw strings (`r"D:\3d\a.usda"`) or forward slashes |
| Moving Kit's viewport camera with `UsdGeom.Xformable` in the stage's edit layer | nothing moves: Kit keeps its own cameras' ops in the session layer, which outranks the edit layer, and the edit stays in the user's file. `await mcp.set_camera()` or `await mcp.look_at()`, or `ViewportCameraState` |
| Switching a variant in a script | the viewport keeps the old geometry: `set_variant_selection` |
| USD called from a thread | crashes Kit: stay on the script's own task |
| `stage.Flush()` | does not exist in OpenUSD; `stage.Reload()` reloads layers from disk |
