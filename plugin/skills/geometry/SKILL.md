---
name: geometry
description: >-
  Use when analysing or preparing USD assets in an Omniverse or Isaac Sim stage: face and vertex counts, where the
  geometry budget goes, comparing two prims or two variants, building variant sets (a full and a simplified shell),
  flattening references, exporting a prim as its own file, or fixing material paths after a copy.
allowed-tools: >-
  mcp__plugin_omniverse-mcp_omniverse__get_sim_state mcp__plugin_omniverse-mcp_omniverse__get_mesh_stats
  mcp__plugin_omniverse-mcp_omniverse__get_prim_face_count_tree mcp__plugin_omniverse-mcp_omniverse__get_prim_bounds
  mcp__plugin_omniverse-mcp_omniverse__get_prim_properties mcp__plugin_omniverse-mcp_omniverse__capture_viewport
---

# Analyse and prepare geometry

Counting is read-only; variants, flattening and exports change the stage or write files, so say what they will do
before calling them.

## Steps

1. **Where the faces are.** `get_prim_face_count_tree` from the root down shows which subtrees cost most;
   `get_mesh_stats` breaks one down per mesh (faces, vertices, triangles). Implicit shapes (`Cube`, `Sphere`) count
   0: only `UsdGeom.Mesh` has faces.
2. **Compare.** `compare_prims` with two paths compares geometry, bounds and materials; with one path, a variant set
   and two variant names, it compares the variants, switching and restoring the selection itself.
3. **Variants.** `create_variant_structure` makes a set with named variants; fill each, then
   `set_variant_selection` to switch. Always switch with the tool: it detects Fabric Scene Delegate and refreshes the
   viewport, where a switch from `execute_script` leaves stale geometry on screen.
4. **Asset preparation.**
   - `flatten_usd` resolves every reference into one file; `export_prim_as_file` writes a subtree as a self-contained
     file. Both overwrite the output path: confirm it with the user. Both refuse a file the open stage has loaded, its
     own included: write elsewhere, or `save_scene` to save the open stage itself.
   - After copying assets to a new folder, `update_material_paths(old_prefix, new_prefix)` rebinds materials.
5. **Check** with `capture_viewport` at one camera position for each state you compare: capture both variants
   before moving the camera, never all of one and then all of the other.

## Traps

| Trap | What to do |
|---|---|
| Stale bounds after a variant switch | `compare_prims` and `set_variant_selection` clear the bounds cache; a script must do it too |
| Edits inside a variant land on the root layer | Usd-level APIs ignore the variant edit context: a script uses the `Sdf` layer API |
| A layer Kit already holds for a path | never `Clear()` it: if the open stage uses it, the scene empties. A script writes a file from an in-memory layer with `Export`, and `Reload()`s a held layer only when `stage.GetUsedLayers()` lacks it and `layer.dirty` is false; the tools refuse to write a file the open stage has loaded |
| `prim.SetActive()` in a script moves the camera | Kit may frame the prim again: avoid it in scripts |
| `stage.Flush()` | does not exist in OpenUSD |
