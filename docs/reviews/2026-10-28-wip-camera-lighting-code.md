---
subject: wip/2026-03-08-camera-lighting (inspect_prim auto-fit and isolate, viewport_light modes)
base: main (ceb6dd9)
head: e1b352d
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: needs-fixes
---

# Review: the March camera and lighting work

Read only; nothing ran. "Confirmed" means the main session read the code path and agrees; "needs Kit" means the
finding rests on Kit or RTX behaviour that only a live Isaac Sim settles.

| # | Sev | Where (`handlers/camera.py`) | Finding | Status |
|---|---|---|---|---|
| F1 | major | `_compute_autofit_distance` 162-201, `_capture_frame` 242 | Auto-fit takes the vertical FOV from `verticalAperture` and the margin from the requested width and height, but `_capture_frame` ignores both and captures at the viewport's own size; RTX derives the vertical FOV from `horizontalAperture` and the viewport's aspect. On a 16:9 viewport the fit is too close vertically: tall prims lose head and feet. | Confirmed that width and height are unused; the RTX aperture rule needs Kit |
| F2 | major | 199-201 | `d = r / tan(θ)` lets the bounding sphere spill past the frame; a sphere fits only when `d >= r / sin(θ)` (about 8% at θ = 22.8°). The docstring calls it exact. | Confirmed (maths) |
| F3 | major | `_hide_other_prims` 204-228 | `isolate` hides every other `/World` child, lights included, so isolated captures can come back dark. | Confirmed that lights are hidden; their effect needs Kit |
| F4 | major | 216-220 | Isolation sees only direct children of `/World`: target `/World` hides everything; a nested target keeps its siblings; prims outside `/World` never hide. | Confirmed |
| F5 | major | 672-678, 231-239 | Prims are hidden before the `try`, so a failure while hiding or settling leaves them hidden. The restore's `attr.Clear()` drops any session-layer visibility opinion that was there before, not only ours. | Confirmed |
| F6 | major | 877-907 | `set` and `set_camera_light` call `SetLightingMenuModeCommand` and ignore its result. Kit logs and returns `(False, None)` for a missing command rather than raising, so both report success when nothing changed. The old `set_camera_light` set `/rtx/useViewLightingMode` directly and needed no menubar extension. | Needs Kit (headless apps without `omni.kit.viewport.menubar.lighting`) |
| F7 | minor | `_get_current_lighting_mode` 136 | Reads only the menubar's setting through a private function and never `/rtx/useViewLightingMode`, so it misreports a camera light turned on elsewhere; `_get_available_lighting_modes` swallows a changed private API and drops the rig presets. | Confirmed by reading |
| F8 | minor | `_mcp_bridge.py` 52 | `mcp.inspect(..., distance=...)` still sends `distance`, which the handler no longer reads. | Confirmed |
| F9 | minor | 193 | `width` or `height` of 20 or less: division by zero or a negative distance; `zoom_offset <= -1` puts the camera inside the prim. | Confirmed (maths) |
| F10 | minor | `README.md` 212 | Still tells users `viewport_light("set_camera_light", enabled=true)` and names the old `camera_light_on` field. | Confirmed |

Improvements (no severity): `set_camera_light` duplicates `set` and could map `enabled` to a mode; the light-type list
is written out three times (`_has_scene_lights`, the `get` action, `_compute_screen_bboxes`).

## Outcome

Pending the maintainer (plan D13): keep and fix, cut to the parts that hold, or drop.
