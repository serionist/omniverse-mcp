---
subject: "Warn when start_recording is given a camera or a size it ignores (#25, PR 3 of its plan)"
base: main (b818449)
head: bc241e8
date: 2026-10-29
round: 1
tier: light (one fresh reviewer on a server-only text change)
verdict: clean
---

# Review: the start_recording warning

Read from the diff, the tool, its tests and the recording handler. No blocker or major.

- **Accurate:** the handler records the active viewport and passes no size (`capture_viewport_png(viewport)`), so the
  warning is true; the tool's own answer never echoes the size or camera.
- **Contract:** names, parameters, defaults and hints unchanged; `tests/fixtures/mcp-tools.json` carries no
  descriptions.
- **Tests:** all three values, each alone, a camera with a height, and no warning for the defaults or `fps` alone;
  the values still reach the bridge as given.

Minors, left: a `camera_path` naming the active camera still gets the warning (true, if loud); an explicit 640x480
gets none (documented); the same "ignored for now (#25)" in the description, three parameters and TOOLS.md.

Improvements, taken in `40e0ec4`: the description's "while the simulation is playing" was stale (frames come every few
app updates, playing or not); TOOLS.md says `metadata.json` still lists the camera and size asked for.

Not covered: no bridge, route or Kit code changed, so the Kit lenses have nothing to read.

## Checks

`uv run tools/gate.py full` passed on `bc241e8` and on `40e0ec4`. No live run: only the server's text changed.
