---
subject: wip/2026-03-08-camera-lighting (inspect_prim auto-fit and isolate, viewport_light modes)
base: main (ceb6dd9)
head: c54bc34 (fixes on 2-s1b-camera-lighting; reviewed at e1b352d)
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
| F1 | major | `_compute_autofit_distance` 162-201, `_capture_frame` 242 | Auto-fit takes the vertical FOV from `verticalAperture` and the margin from the requested width and height, but `_capture_frame` ignores both and captures at the viewport's own size; RTX derives the vertical FOV from `horizontalAperture` and the viewport's aspect. On a 16:9 viewport the fit is too close vertically: tall prims lose head and feet. | Fixed, needs Kit to confirm (`85853cd`). The maths is in `core/framing.py` (tested). Margins use the viewport's resolution from `syn.helpers.get_view_params`, the call `_compute_screen_bboxes` already makes; the requested size is the fallback, with a one-time warning. Context7 did not say which vertical field of view RTX uses, so the fit takes the narrower of `verticalAperture` and the horizontal aperture at the frame's aspect, and holds either way. |
| F2 | major | 199-201 | `d = r / tan(θ)` lets the bounding sphere spill past the frame; a sphere fits only when `d >= r / sin(θ)` (about 8% at θ = 22.8°). The docstring calls it exact. | Fixed (`85853cd`): `r / sin(θ)`, tested against the projected outline. |
| F3 | major | `_hide_other_prims` 204-228 | `isolate` hides every other `/World` child, lights included, so isolated captures can come back dark. | Fixed, needs Kit to confirm (`b9b9c61`): lights, cameras and prims that hold a light are never hidden; a light-holding prim's other children are hidden instead. Tested on usd-core; that RTX then lights the isolated prim needs Kit. |
| F4 | major | 216-220 | Isolation sees only direct children of `/World`: target `/World` hides everything; a nested target keeps its siblings; prims outside `/World` never hide. | Fixed (`b9b9c61`): `core/isolation.py` walks from the root to the target and hides the siblings at every level; `/World` hides only what is outside it, `/` hides nothing. Tested on usd-core. |
| F5 | major | 672-678, 231-239 | Prims are hidden before the `try`, so a failure while hiding or settling leaves them hidden. The restore's `attr.Clear()` drops any session-layer visibility opinion that was there before, not only ours. | Fixed (`b9b9c61`): hiding runs inside the `try`; each prim's session-layer opinion (none, a spec without a default, or a value) is recorded and put back exactly, and only the specs isolation created are removed. Tests compare the session layer byte for byte, including after a partial hide. |
| F6 | major | 877-907 | `set` and `set_camera_light` call `SetLightingMenuModeCommand` and ignore its result. Kit logs and returns `(False, None)` for a missing command rather than raising, so both report success when nothing changed. The old `set_camera_light` set `/rtx/useViewLightingMode` directly and needed no menubar extension. | Fixed, needs Kit to confirm (`bae962f`): the command's result is checked; for `"camera"` and `"stage"` a failure falls back to `/rtx/useViewLightingMode`; anything else that did not change returns an error. Checked with Kit mocked. The `(success, result)` return shape was not confirmed by Context7; the code also accepts a plain truthy return. |
| F7 | minor | `_get_current_lighting_mode` 136 | Reads only the menubar's setting through a private function and never `/rtx/useViewLightingMode`, so it misreports a camera light turned on elsewhere; `_get_available_lighting_modes` swallows a changed private API and drops the rig presets. | Fixed (`bae962f`): `/rtx/useViewLightingMode` is read first; both private-API lookups log once with `carb.log_warn` when they fail. |
| F8 | minor | `_mcp_bridge.py` 52 | `mcp.inspect(..., distance=...)` still sends `distance`, which the handler no longer reads. | Fixed (`c54bc34`): it takes `zoom_offset` and `isolate`; the execute_script docstring and TOOLS.md match. |
| F9 | minor | 193 | `width` or `height` of 20 or less: division by zero or a negative distance; `zoom_offset <= -1` puts the camera inside the prim. | Fixed (`85853cd`): both are refused with a clear error, in the handler and in `core/framing.py`. Tested. |
| F10 | minor | `README.md` 212 | Still tells users `viewport_light("set_camera_light", enabled=true)` and names the old `camera_light_on` field. | Fixed (`c54bc34`): README and TOOLS.md give `viewport_light(action="set", mode=...)`. |

Improvements (no severity): `set_camera_light` duplicates `set` and could map `enabled` to a mode; the light-type list
is written out three times (`_has_scene_lights`, the `get` action, `_compute_screen_bboxes`). Both taken: the alias
maps `enabled` to a mode and shares the `set` path (`bae962f`); one `LIGHT_TYPES` tuple and `is_light()` serve all
three places (`b9b9c61`).

## Outcome

Kept (D13) and fixed on `2-s1b-camera-lighting`: all ten findings and both improvements.

## Live run

Isaac Sim 6.2.0, headless, after the rebase onto S1. Integration: 27/27 with `OMNIVERSE_MCP_SIM=1`, including
auto-fit, zoom offset, isolate and the three lighting actions.

The three findings that rest on Kit, checked from the images:

| # | What was checked | What it showed |
|---|---|---|
| F1 | A 0.5 x 0.5 x 4 m prim, front and right | It fills the viewport's real 1280 x 720 frame top to bottom with 19 px left at each edge, nothing cut off; the capture size is the viewport's, not the 640 x 480 asked for. |
| F3 | The top face, lit by a DistantLight pointing down, with and without isolate | Full brightness both ways, so isolated captures are not dark on 6.2. Hiding the light by hand also left it at full brightness, so whether RTX stops lighting with a hidden light could not be shown here; the old isolate's harm is not reproduced either. The side faces get darker under isolate because the box whose bounce lit them is hidden, as it should be. |
| F6 | `set` to stage, camera, Default, stage, then `get` | Each mode took and `get` reported it. |

After isolate every prim's visibility is back to `inherited`. Not run here: Isaac Sim 5.1, and a headless app without
the lighting menu extension (F6's fallback). Seen while fixing, not in scope:
`capture_viewport` reports the requested width and height and scales its bounding boxes to them, while the image comes
out at the viewport's resolution.

## Review-code round 1 (PR #4)

High tier, one fresh reviewer, on the rebased branch after the live run. Fixed on `2-s1b-camera-lighting`; each fix
has a test that runs without Kit, except where the row says otherwise.

| # | Sev | Finding | Status |
|---|---|---|---|
| R1 | major | `viewport_light(action, mode, enabled)`: `mode` took `enabled`'s positional place, so the old `viewport_light("set_camera_light", False)` sent `mode=False` and turned the camera light on | Fixed (`8618c6b`): `enabled` back in its place, `mode` keyword-only. Test: the old call sends `enabled=false` |
| R2 | major | `camera_inspect` and `mcp.inspect`: `zoom_offset` sat where `distance` was, so an old fifth positional distance became a zoom | Fixed (`8618c6b`): `zoom_offset`, `isolate`, `include_segmentation` keyword-only. Tests: an old fifth positional raises `TypeError` on both |
| R3 | minor | The current mode trusted the lighting menu's stale "camera" with the camera-light flag off | Fixed (`dec8c3d`): `core/lighting.py` `current_mode()`, the flag first, tested as a table; every mode that takes sets the flag to match |
| R4 | major | Legacy `set_camera_light(enabled=False)` set "stage" and tore down a light rig | Fixed (`dec8c3d`): `camera_light_switch()`: off sets "stage" only from camera mode, otherwise only clears the flag; the resulting mode is reported. Tested as a table; the handler checked with Kit mocked |
| R5 | minor | Under an instance `GetChildren()` returns nothing and proxies can't be authored, so isolate silently left instances visible | Fixed (`9471460`): an instance the walk would enter is left whole and named in `isolate_warnings`, which the result carries and the tool prints. Tests on usd-core: an instance holding a light, one holding the target |
| R6 | minor | `capture_viewport`'s black-capture warnings sent the AI to the Default rig, which needs the lighting menu | Fixed (`84ff38c`): `mode="camera"` first (always available), a rig such as Default "if `viewport_light('get')` lists it". Tests |
| R7 | minor | `inspect_prim`'s black warning still said "enable camera light"; `test_project/scenarios.md` still described isolate as hiding the other `/World` children | Fixed (`84ff38c`): the same advice as R6, plus what isolate hid when it was on; scenarios.md describes the new isolate. Tests |
| R8 | minor | `Hidden.hide()` authors a default, which a prim's time-sampled session-layer visibility outranks | Fixed (`9471460`): such prims are skipped and named in `isolate_warnings`; their samples are untouched. Test on usd-core |
| R9 | improvement | `look_at` keeps the old 2.5x size guess for its distance, and repeats the orbit maths `inspect_prim` has | Later: a follow-up issue (fit `look_at` with `core/framing.py`, share the orbit position code) |
| R10 | minor | The handler refused a requested size of 20 px or less while the capture and the fit use the viewport's resolution; identical "set" / "set_camera_light" output branches in the tool | Fixed (`d72907b`): the pre-check goes and `fit_distance`'s error on the resolved size is the handler's error (zoom_offset <= -1 still refused), checked with Kit mocked; the branches are one. Test for the output |

Still to run against Kit: R4's handler on a rig, and R5 on an instanced asset, with the sim suite.

### Live run of round 1's fixes

On Isaac Sim 6.2.0, headless, at `b16328e`.

| Check | Result |
|---|---|
| `test_integration.py` with `OMNIVERSE_MCP_SIM=1` | 27/27 |
| `set` to camera, stage, Default, camera, then `get` | each took |
| R4: `set_camera_light(False)` under the Default rig | rig kept, mode `Default` |
| R4: `set_camera_light(False)` from camera, then `True` | `stage`, then `camera` |
| R5: `inspect_prim("/World/Inst/A", isolate=True)` on an instanceable prim | success, with the warning "/World/Inst is an instance that holds the target; children of an instance can't be hidden, so all of it stays visible" |

## Review-code round 2 (PR #4)

High tier, one fresh reviewer, at `4404717`. Fixed on `2-s1b-camera-lighting`; each fix with a test that runs without
Kit unless the row says otherwise.

| # | Sev | Finding | Status |
|---|---|---|---|
| R1 | major | Handlers interleave on Kit's loop at every await, so another request saw isolate's hidden prims and inspect's moved camera; two isolated inspects of siblings hid each other's target | Fixed (`a25bd69`): one asyncio lock, made on first use in the running loop (`core/serial.py`), held for the whole of inspect, capture, set_camera and look_at. No locked handler calls another (inspect captures through `_capture_frame`); scripts using the `mcp` object wait their turn. Tests with plain asyncio: two locked coroutines never overlap, a second waits, an unlocked one still runs |
| R2 | minor | The March work dropped `_capture_frame`'s "turn the camera light on and capture again" fallback without saying so | Kept as designed (lighting modes replace silent relighting); CHANGELOG says so under Changed (`e490248`) |
| R3 | minor | A non-numeric `zoom_offset`, `width` or `height`, or a malformed `[azimuth, elevation]` pair, raised a TypeError (a 500 with a traceback, the pair only mid-capture after isolate had hidden prims); unknown angle names were skipped silently | Fixed (`c729901`): `inspect_args` in `core/framing.py` checks the body first and the handler answers its ValueError as an error; unknown names are refused too (CHANGELOG). Tests |
| R4 | minor | With an orthographic active camera (such as `/OmniverseKit_Top`) the fitted distance frames nothing | Fixed (`c729901`): the fit refuses it and names `/OmniverseKit_Persp`. Test for the check; the handler checked with Kit mocked |
| R5 | minor | `_set_lighting_mode` sets the camera-light flag on every mode that takes | Left as is: checked live on Isaac Sim 6.2 for camera, stage and Default. Mode "off" is to be checked live by the main session |
| R6 | minor | With the camera light already on, both black-capture warnings said to set mode "camera" | Fixed (`e490248`): they say the camera may be inside or facing away from the geometry, or the renderer is warming up: recapture, or move it with look_at_prim. inspect_prim's result carries `lighting_mode`. Tests |
| R7 | improvement | `handle_viewport_light`'s local `current_mode` shadowed the imported core function | Fixed (`e80a133`): renamed `mode_now` |
| R8 | minor | The execute_script docstring's `mcp.inspect(..., zoom_offset=, isolate=)` is not valid Python | Fixed (`e80a133`): `zoom_offset=0.0, isolate=False`, in TOOLS.md too |
| R9 | improvement | isolate's light search walked every instance proxy, so N instances of one asset cost N walks of it | Fixed (`bbfc434`): no proxies; each prototype walked once and cached, nested instances included; same results. Test on usd-core with 30 instances of one lamp |

Still to run against Kit: R1 with two overlapping requests, R4 on `/OmniverseKit_Top`, and R5's mode "off".
