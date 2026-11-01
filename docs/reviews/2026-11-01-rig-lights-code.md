---
subject: "Leave the viewport's light rig out of viewport_light's scene lights (#117)"
base: main (f5a27ed)
head: df9f9b7
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only, with a usd-core check; its report came back early for a machine restart"
verdict: clean
---

# Review: Leave the viewport's light rig out of viewport_light's scene lights

Read from the branch's diff against `main`: `ovmcp/core/lighting.py` (`LIGHT_RIG`, `scene_lights`),
`handlers/camera.py` (`_has_scene_lights`, `_scene_lights_for`, the get), `src/omniverse_mcp/tools/camera.py` (the rig
line, the 20 cut, `in_instance`), the tests, `docs/TOOLS.md`, the scene skill, `test_project/scenarios.md` 23.1 and
23.2, and CHANGELOG, against the approved plan `docs/plans/2026-11-01-rig-lights.md` (Q1 A, Q2 B). The reviewer
also read Kit's lighting menu on disk (`omni.kit.viewport.menubar.lighting` 107.3.1) and ran one usd-core script
against the branch's `ovmcp.core.lighting`. No finding.

What was checked and held:
- **`scene_lights`' prototype walk** against the walk inside every instance, on 400 random stages: 0 mismatches in
  paths or order over 2,301 lights, 1,417 of them instance proxies. The stages held nested instances, an instance
  whose source root is a light, inactive prims inside sources, prototypes with no light, and a rig holding an instance
  of its own. Unloaded payloads give the same list both ways.
- **The rig prune:** a rig root that is itself a light is pruned; `/OmniKit_Viewport_LightRig2/Dome` and
  `/World/OmniKit_Viewport_LightRig/Dome` are kept: only the literal root is pruned.
- **Cost on Kit's main thread:** 20,000 instanced lamps take about 0.22 s for the whole list; the yes or no comes back
  at the first light, and with no light anywhere takes 0.17 s, against 0.19 s for the old walk.
  `test_a_yes_or_no_stops_at_the_first_light` fails on an eager version.
- **Kit's facts in 107.3.1:** the literal rig path (`actions.py:185`); every rig light sits under the rig root; modes
  `stage`, `camera` and `off` clear its references; `VisibilityEdit` writes only `visibility` in the session layer,
  which `is_light` ignores, so the list is the same in every mode; the mode setting holds `""`, `off`, `camera` or a
  rig's name, never an int.
- **The rig line** is told from the mode alone, in both wordings; a rig `available_modes` doesn't list still gets it;
  no mode gives `unknown` and no rig line.
- **The 20 cut and `in_instance`:** `in_instance` comes from `IsInstanceProxy()`, so a light that is itself an instance
  root, whose properties can be edited, isn't marked; the server prints 20, then `... and N more` (tested at 20 and 25).
- **`test_12j`** fails on an older extension that counts the rig, and if Kit moved the rig; neither the up axis nor
  Kit's hiding changes the list. **`test_23_02`** fails on the old extension, whose Default list holds the rig's paths.
- **The tool contract:** `golden.py` drops descriptions and titles, `tests/fixtures/mcp-tools.json` isn't in the diff,
  and the answer gains only the optional `in_instance`, so the protocol stays 1. No one-way door.
- **Docs and CHANGELOG** match the code; no em dashes or banned words. The walk runs in the handler, with no executor.

Refuted:
- **An older extension with the new server** prints the rig line beside the old list, which then names the rig's two
  lights: misleading, but the plan's Compatibility section says so, CHANGELOG gives the install line, and 0.x doesn't
  design for older extensions.
- **No rig line when Kit's lighting menu can't be read:** `_get_current_lighting_mode` falls back to `stage`; an
  unlikely state that predates this change.
- **Tests that pass without the change:** `test_a_rig_kit_has_taken_away_adds_nothing` and
  `test_a_capture_in_mode_stage_with_the_rigs_over_left_says_no_lights` pin Kit's behaviour (K3); the other new tests
  fail on the old code.
- **Black-image warnings in a rig mode:** `has_scene_lights` now reads false there, but the server's black-image
  branch reads it only in mode `stage`, so no warning text changes.

Improvements:
- `test_23_02` also asserts `/World/DomeLight` is listed, as scenario 23.2 says. left: the pytest suite's phase 18 to
  23 twins make no dome light (only the AI scenario's 18.2 does), and `test_12j` already checks the stage's own lights
  stay listed in every mode.
- The bridge sends every light, about 2 MB of JSON for 20,000 instanced lamps, where the server shows 20. left: it
  would change the answer's shape, for stages that aren't common yet.

Not covered: the gate and CI (run by the main session and the PR), REVIEW.md's PR questions, USD Composer and Kit
107.3.4 on disk, `bridge-security` and `harness-integrity`, which don't apply.

## Live run

Run by the session on its own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows, RTX 5090, at port 8212, with the
branch's extension from `df9f9b7`; `105-stage.py` set the stage's up axis before each step.

| Step | Stage | What ran | Result |
|---|---|---|---|
| 1 | Z-up | the changed tests, `-k "test_12j or test_23_"` | 7 passed, 3 subtests; 1 failed: `test_integration.py`'s `test_23_mesh_stats`, which the filter caught by accident and which needs an earlier test's prim (it passes in the suites) |
| 2 | Z-up | both live suites whole | 193 passed |
| 3 | Y-up | step 1's tests | the same as step 1 |
| 4 | Y-up | both live suites whole | 193 passed |
| AI | Y-up | `scenarios.py run --phases 23`, run `20261101-184259` | 8 PASS (18.2's setup, 23.1 to 23.6, the cleanup) |

What it couldn't show: Isaac Sim 5.x (Kit 107.3.1's rig was read on disk only), Linux, USD Composer, and a stage of
many instanced lamps live (the unit tests cover the walk).
