# Images

The README's images, and how each was made.

| File | What | How |
|---|---|---|
| `hero-viewport.jpg`, `hero-segmentation.png` | the README's hero | One `capture_viewport(width=1280, height=720)` in Isaac Sim 6.2.0, through the MCP tools: its frame and its instance segmentation, the same square crop of each, 640 pixels |
| `inspect-orbit.jpg` | "What can it do?" | One `inspect_prim(prim_path="/World/Workcell", angles=["top_front_right", "top_back_right", "top_back_left", "top_front_left"], width=800, height=600, isolate=True)`, each frame cropped square |
| `logo.svg` | the README's logo | Drawn: an isometric cube whose faces are three segmentation colours |
| `social-preview.png` | GitHub's social preview, 1280 by 640 | Drawn with the logo and the two hero captures. GitHub takes it only in the repo's settings (Settings, General, Social preview), by the maintainer |

The plugin's icon, `plugin/.claude-plugin/icon.png`, is the logo on a dark square, 1024 pixels.

**The scene**, built through the MCP tools: `new_scene`, a Z-up stage with a dome light (380) and a distant light (1700,
rotated -40, 25, 30) made by `execute_script`; under `/World/Workcell`, a table (`create_prim` Cube at 0.15, 0, 0.36,
scaled 0.55, 0.42, 0.36), `create_robot("franka")` at -0.25, 0, 0.72, three cubes scaled 0.035 and a sphere scaled
0.045 on the table, each coloured by `set_material`; a floor Cube scaled 4, 4, 0.01; `set_camera` at 2.45, 1.5, 1.85
looking at 0.03, 0, 1.08.

Every capture is the tool's own output, cropped and resized only.
