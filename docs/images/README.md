# Images

The README's images, and how each was made.

| File | What | How |
|---|---|---|
| `hero-viewport.jpg`, `hero-segmentation.png` | the README's hero | One `capture_viewport(width=1280, height=720)` in Isaac Sim 6.2.0, through the MCP tools: its frame and its instance segmentation, the same square crop of each, 640 pixels |
| `inspect-orbit.jpg` | "What can it do?" | One `inspect_prim(prim_path="/World/Workcell", angles=["top_front_right", "top_back_right", "top_back_left", "top_front_left"], width=800, height=600, isolate=True)`, each frame cropped square |
| `logo.svg` | the README's logo | Drawn: an isometric cube whose faces are three segmentation colours |
| `social-preview.png` | GitHub's social preview, 1280 by 640 | Drawn with the logo and the two hero captures. GitHub takes it only in the repo's settings (Settings, General, Social preview), by the maintainer |

The plugin's icon, `plugin/.claude-plugin/icon.png`, is the logo on a dark square, 1024 pixels, where `claude plugin
validate` looks for one: for a listing in Anthropic's plugin directory. Claude Code itself shows no icon.

**The scene**, built through the MCP tools:

- `new_scene`, then `execute_script` for a Z-up stage with a dome light (intensity 380) and a distant light (1700,
  rotated -40, 25, 30);
- `create_prim("/World/Workcell", "Xform")`, and under it:
  - `create_prim("/World/Workcell/Table", "Cube", position=[0.15, 0, 0.36], scale=[0.55, 0.42, 0.36])`;
  - `create_robot("franka", prim_path="/World/Workcell/Franka", position=[-0.25, 0, 0.72])`;
  - `RedBlock`, `GreenBlock` and `BlueBlock`, Cubes scaled 0.035, and `Ball`, a Sphere scaled 0.045, on the table;
- `create_prim("/World/Floor", "Cube", position=[0, 0, -0.01], scale=[4, 4, 0.01])`, outside the workcell, so
  `isolate=True` hides it;
- `set_material` on each, and `set_camera(position=[2.45, 1.5, 1.85], target=[0.03, 0, 1.08])`.

Every capture is the tool's own output, cropped and resized only.
