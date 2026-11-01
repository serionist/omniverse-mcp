---
title: Leave the viewport's light rig out of viewport_light's scene lights
issue: "#117"
status: approved
approved_by: serionist
approved_at: 2026-11-01
---

# Leave the viewport's light rig out of viewport_light's scene lights

`viewport_light`'s get counts the viewport's light rig as the stage's lights: in a rig mode such as Default it says
"Scene has lights: yes" on a stage with none of its own, and lists the rig's `DomeLight` and `DistantLight`. The
captures' check, `_has_scene_lights` (#105), walks inside instances where the get doesn't. This plan gives both one
check, which finds the lights inside instances and leaves the rig out, and has the get say the rig apart.

## Goal

When this is done, with this release's Kit extension:

| What | True when done | Shown by |
|---|---|---|
| The get's `has_scene_lights` and `scene_lights` | The stage's own lights, inside instances too; never the rig's, in any mode. A stage without lights reads "no" in Default as in `stage` | `test_lighting.py`, `test_camera_handler.py`; live `test_12j` |
| The captures' `has_scene_lights` | The same check as the get's | `test_camera_handler.py` |
| The get's text in a rig mode | Says the rig lights the viewport, apart from the stage's lights (Q1) | `test_tools_camera.py` |
| The get's list | Bounded, now that instances can multiply it (Q2); a light inside an instance is marked read only | `test_tools_camera.py` |

Why: `viewport_light`'s description sends an agent to the get to ask whether the stage needs lights. In Default it
reads yes and adds none, then switches to `stage`, or saves the scene for another app, and gets black surfaces.

| In scope | Out of scope |
|---|---|
| The light check, the get's answer and text, the tool's description | `get_scene_tree` and `list_prims` showing `/OmniKit_Viewport_LightRig` and Kit's cameras |
| `test_12j` reading the get in a rig mode; scenarios 23.1 and 23.2 | `inspect_prim`'s isolate, which keeps the rig visible as it should: its lights light the capture |
| `docs/TOOLS.md`, the scene skill, `CHANGELOG.md` | Grey Studio's ground plane, which the rig brings beside its lights |
| | `flatten_usd` baking the session layer, the rig included, into its file: #118 (P2) |

## What Kit does

Read on disk, in `omni.kit.viewport.menubar.lighting` 107.3.4 (Isaac Sim 6.2) and 107.3.1 (Isaac Sim 5.1); K1 to K3
also rebuilt on usd-core, as step 1's test does, and seen live (The probe):

| # | What | Where |
|---|---|---|
| K1 | A rig mode authors an `over` at `/OmniKit_Viewport_LightRig` in the session layer, references the rig's file from it (`data/usd/Default.usda` and the others), and marks it `hide_in_stage_window` and `no_delete`. The path is a literal in Kit's code, twice, in both versions; nothing exports it | `actions.py:195`, `:205-224`, `:282` (107.3.4); `:185`, `:272` (107.3.1) |
| K2 | The rig file's prims `def` the lights, so the over composes a defined prim: `Traverse` and the walk inside instances both reach `/OmniKit_Viewport_LightRig/Lights/DomeLight` and `.../DistantLight` | `data/usd/Default.usda`; usd-core; the probe |
| K3 | Modes `stage`, `camera` and `off` clear the over's references and leave the over: an undefined prim, which neither walk visits | `actions.py:88-94`, `:230-232` |
| K4 | A rig mode, and modes `camera` and `off`, hide the stage's own lights, through visibility in the session layer; `stage` shows them again. A light inside an instance is hidden through its instance, and only when every child of the instance is a light, an `Xform` or a `Scope`: a lamp asset's bulb, beside its shade, stays lit, and Kit logs "Will not hide ..." | `actions.py:217-219`, `:235-241`; `utility.py`, `VisibilityEdit.__hide_prims` |
| K5 | NVIDIA's asset validator skips the same path, and the subtree under it, as a prim Kit makes | `omni.asset_validator.core-1.22.0`, `_compliance_checker.py:26-66` |
| K6 | An instance has no children of its own: its prototype holds them, `Usd.PrimRange(prototype)` walks them starting with the prototype itself, a nested instance in it is again an instance, and `GetPrimAtPath` of a path under an instance gives the instance proxy | OpenUSD's instancing docs (Context7, `/websites/openusd_release_api`); usd-core |

So the rig is told by its path, the one Kit writes and NVIDIA's own validator skips. Telling it by the session layer
instead doesn't work: the rig's light specs are in the rig's file, reached through the session layer's reference,
and a walk would need each light's composition arcs to know; it would also drop any light a script put in the session
layer on purpose.

### The probe

`<scratchpad>/117/117-probe-rig.py`, run by the main session on its headless Isaac Sim 6.2 at port 8212, on the stage
it had open, which has no lights of its own. It switched to Default, then to
`stage`, and read each time; then it put back the mode it found, `stage`.

| Mode | The rig prim | Its session-layer spec | Root layer | `Traverse` and the walk inside instances | The walk with the rig pruned | The get today |
|---|---|---|---|---|---|---|
| Default | defined (`def`) | `over`, referencing Kit's `.../omni.kit.viewport.menubar.lighting-107.3.4+107.3.0/data/usd/Default.usda`, `hide_in_stage_window` true | no spec | `/OmniKit_Viewport_LightRig/Lights/DomeLight`, `.../DistantLight` | none | `has_scene_lights: true`, the rig's two lights |
| stage | undefined (`over`) | `over`, no references, `hide_in_stage_window` true | no spec | none | none | `has_scene_lights: false` |

K1 to K3 hold on Isaac Sim 6.2, and the get's answer differs between the two modes on one stage: the bug.

## Design

**Extension, `ovmcp/core/lighting.py`** (Kit-free, tested on usd-core):

- `LIGHT_RIG = Sdf.Path("/OmniKit_Viewport_LightRig")`, with K1 as its why.
- `scene_lights(stage) -> Iterator[Usd.Prim]`, lazy, so a yes or no stops at the first light:
  - walks `Usd.PrimRange.Stage(stage)`, pruning the subtree at `LIGHT_RIG`, and yields each prim
    `isolation.is_light` takes;
  - at an instance, yields the lights of its prototype as the instance's own proxies, at the instance's path plus
    each light's path in the prototype (K6). Each prototype is walked once, its lights' relative paths kept for the
    call, with a nested instance's added under its own (I1). `isolation._paths_holding_lights` keeps prototypes the
    same way.
  - The lights and their order are those of the walk inside every instance, `Usd.TraverseInstanceProxies()`; a
    usd-core check with nested instancing, an instance that is itself a light and an inactive light in a prototype
    gave the same list, walking each of three prototypes once.

**Extension, `handlers/camera.py`:**

- `_has_scene_lights()` is `next(scene_lights(stage), None) is not None`.
- The get lists `scene_lights(stage)` in place of its `stage.Traverse()` loop. The answer keeps its keys:
  `has_scene_lights`, `scene_lights` (path, type, intensity). A light inside an instance has its proxy's path and
  `in_instance: true`, since USD refuses edits to it there (I4).

**Server, `tools/camera.py`, the get:**

- A rig mode is any mode but `off`, `camera` and `stage`, and the server's `unknown` for an answer without one, read
  from the mode alone, so the line doesn't hang on Kit's list of rigs, which can fail with one warning (I3). In one, a
  line after "Scene has lights" says the rig apart (Q1, A):
  - no lights: `The light rig 'Default' lights the viewport with lights of its own, which aren't the stage's: in mode
    'stage', or in another app, the stage's surfaces render black. create_prim (DistantLight, DomeLight) lights the
    stage itself.`
  - lights: `The light rig 'Default' lights the viewport in place of the stage's lights, which Kit hides, all but a
    light inside an instance with other prims, until the mode is 'stage'.` (K4, P1)
- A light inside an instance prints `inside an instance, read only` after its intensity (I4).
- The list prints the first 20 lights, then `... and N more` (Q2, B): the other tools' form, at 20.
- The description: the get answers "the stage's own lights, inside instances too, with their intensity; a light
  rig's lights are the viewport's, not the stage's, and aren't among them".

Alternatives: Q1 and Q2 hold them.

## Compatibility

No one-way door: no tool, parameter, hint or route changes, and `tests/fixtures/mcp-tools.json` holds no
descriptions. `scene_lights` changes in what it holds: no rig lights, and lights inside instances, each with the new
key `in_instance`.

A server of this release with an older Kit extension prints the rig line beside the old list, which still holds the
rig's lights. The CHANGELOG line says to run `uvx omniverse-mcp extension install`; 0.x doesn't keep older extensions
working.

## Steps

1. **Core:** `LIGHT_RIG` and `scene_lights` in `core/lighting.py`. `tests/test_lighting.py`:
   - a rig authored as K1 does, over a usd-core rig file with a DomeLight and a DistantLight, is left out;
   - the rig with its references cleared (K3) adds nothing; a stage light counts;
   - nested instancing, an instance that is itself a light and an inactive light in a prototype give the list of the
     walk inside every instance, and each prototype is walked once;
   - a stage with a light first stops the walk there.
2. **Handler:** `_has_scene_lights` and the get use it. `tests/test_camera_handler.py`: the get with the rig and an
   instanced lamp lists the lamp's light, with `in_instance`, and not the rig's, `has_scene_lights` true; with the rig
   alone, false; a capture in mode `stage` with the rig's over left (K3) and no light says false.
3. **Server:** the get's text (Q1, Q2, I3, I4) and the description. `tests/test_tools_camera.py`: a rig mode with and
   without lights; a rig mode `available_modes` doesn't list; mode `stage` unchanged; a light inside an instance;
   25 lights printing 20 and `... and 5 more`.
4. **Live test, scenarios and docs:**
   - `test_12j` reads the get in Default, when on offer, and again in each mode it captures in, and asserts the same
     list of light paths every time, none under `/OmniKit_Viewport_LightRig` (P3); the warnings follow that one
     answer. `e1a47f7` had it read the get after each switch, to work around this bug; that goes.
   - `test_project/scenarios.md` 23.1 and 23.2 (I2), and the docs below.
5. **finish-work:** `uv run tools/gate.py full`; both live suites whole on Isaac Sim 6.2, on a Z-up stage and on a
   Y-up one, and the AI scenarios' phase 23; then `review-code` until clean (P4).

## Tests

| Suite | What |
|---|---|
| Unit (CI) | Steps 1 to 3 |
| Live, by hand on Isaac Sim 6.2, Z-up and Y-up | `test_integration.py` and `test_scenarios.py` whole; `test_12j` and phase 23 (`test_23_01` to `test_23_06`) are the ones this changes |
| AI scenarios | Phase 23, whose 23.1 and 23.2 change |
| Neither | Isaac Sim 5.x (Kit 107), read on disk only (K1); USD Composer, not on this machine; Linux |

## Docs

- `docs/TOOLS.md`, `viewport_light`'s get (P5): the stage's own lights, inside instances too, each marked, never the
  rig's; the first 20, then `... and N more`; in a rig mode, the line naming the rig.
- `test_project/scenarios.md` (I2): 23.1, the list names no `/OmniKit_Viewport_LightRig` path; 23.2, after the
  switch, `viewport_light("get")` names the Default rig in its own line and still lists 18.2's `/World/DomeLight`,
  and no rig path.
- `plugin/skills/scene/SKILL.md`, Light and black captures: a rig's lights aren't the stage's.
- `CHANGELOG.md`, Fixed: the get no longer counts the rig, and finds lights inside instances; the fix is in the Kit
  extension and the server.

## Risks

| Risk | Status |
|---|---|
| A later Kit moves the rig (K1's path is private to Kit): the get counts its lights again, as today | Accepted: `test_12j` compares the list of light paths in Default with the list in each other mode, on any stage, and fails then (P3) |
| Lights inside instances cost a walk of every instance's copy, on Kit's main thread | Resolved: each prototype is walked once (I1); the yes or no stops at the first light |
| This repo's `flatten_usd` flattens the open stage with `Stage.Flatten()` (`handlers/usd_advanced.py:50`), which keeps the session layer: run in a rig mode, it bakes the rig's lights at `LIGHT_RIG` into the file, and Kit's hiding of the stage's own lights with them. Reopened, those lights light mode `stage`, yet the get leaves them out and a capture warns. Kit's Save Flattened As leaves the session layer out unless asked (`omni.kit.window.file`, `file_window.py:723-745`) | Accepted here: the bake is `flatten_usd`'s bug, already there for the hidden lights, and #118 has it flatten without the session layer. `export_prim` flattens the whole stage the same way (`usd_advanced.py:110`) (P2) |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, read only, 2026-11-01, on `86e7bf3`, with a usd-core check of its own.
**Verdict:** approved: no blocker or major, five minors; Q1 and Q2 answered by the maintainer since. **Now:** P1 to P5 fixed,
improvements 1 to 4 taken and the probe's results added (The probe), in the commit after `86e7bf3`.

Checked and holding: K1 to K5 on disk, the rig path at `actions.py:195` and `:282` in 107.3.4 and `:185` and `:272`
in 107.3.1, the rig files differing only in line endings; K2 and K3 on usd-core, where pruning at the rig path drops
the rig's lights and keeps an instanced lamp's, and the over left after the references are cleared is valid but not
defined. The main session's probe showed the same live (The probe).

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | K4 said a rig mode hides every light of the stage's own. Kit doesn't hide a light inside an instance that holds other prims too, the lamp case this plan starts counting: with instanced lamps in Default, the get would say Kit hides the lamps' lights until mode `stage`, while they light the viewport beside the rig (`VisibilityEdit.__hide_prims`: "Will not hide ..., it contains at least one child with a type not being requested to hide") | fixed: K4 says which lights Kit hides, and the "lights" line reads "which Kit hides, all but a light inside an instance with other prims, until the mode is 'stage'" (Design) |
| P2 | minor | Risks row 3's premise, "only a flattened export that took it along", misses this repo's `flatten_usd`: it calls `Flatten()` on the open stage, which keeps the session layer; on usd-core both `Flatten()` and `Export()` hold `/OmniKit_Viewport_LightRig/Lights/DomeLight`. An agent flattens in Default and reopens the file: mode `stage` is lit by the baked rig's lights, yet the get says no lights and the capture warns that the surfaces render black. The same flatten bakes Kit's hiding of the user's own lights, a bug already there | fixed: the row names `flatten_usd`, Kit's Save Flattened As and `export_prim`; the bake is #118's (Risks; Out of scope) |
| P3 | minor | `test_12j`'s guard against a moved rig compared only yes or no. The suite runs on whatever stage Kit has open (`test_integration.py:349-361` opens none), and on a stage with lights of its own Default and `stage` both read yes, so a moved rig would pass | fixed: `test_12j` asserts the same list of light paths in Default and in each mode it captures in (step 4; Risks) |
| P4 | minor | The steps ended at 4, with no finish-work step (gate full, both live suites on Z-up and Y-up, `review-code`); review-plan's approval needs the plan to end with `review-code` | fixed: step 5; the Tests table names both suites whole and phase 23 of the AI scenarios |
| P5 | minor | Docs: `docs/TOOLS.md:798` says the get returns "a list of all scene light prims"; the plan's line left out the cut at 20 and the rig line, both of which users see | fixed: the Docs line names both, and the mark on a light inside an instance |

**Refuted:**

- Some rig lights escape the skip: every rig mode goes through one `_set_lighting_mode` at the literal path, Default,
  Colored Lights' `/OmniKit_Viewport_LightRig/DistantLight*`, Grey Studio and any folder the rigs setting names.
  Kit's "Import Current Lighting Rig" copies the rig to `/Environment/<name>` and shows it (`actions.py:282-371`):
  real stage lights, rightly counted.
- The camera light needs skipping: it has no prim; it is the renderer's flag `/rtx/useViewLightingMode`
  (`actions.py:264-265`).
- A user's own light under the rig path skipped wrongly: only a script or a flattened file puts one there (P2); Kit's
  Stage window hides the path, and NVIDIA's asset validator skips it (`_compliance_checker.py:26-66`).
- The walk inside instances costing too much: Risks row 2 accepted it openly, and the yes or no became lazy, so
  captures pay less than today. Improvement 1 resolves it.
- The tool contract or a one-way door: `golden.py` strips descriptions and titles; the answer's keys stay; no route
  or schema changes.
- An older extension's contradictory text: in Compatibility; 0.x doesn't keep older extensions working.
- `test_12j` failing on an up axis or a mode: `is_light` ignores visibility, and Kit's hiding is session-layer
  visibility; on Z-up the over's `xformOp:transform` sits on an undefined prim; the same answer in `off`, `stage`,
  `camera` and Default on both axes.
- The writing rules: clean.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | What the get says of the rig's lights: A, left out, the server naming the rig from the mode; B, a new `rig_lights` key, listed apart; C, left out, nothing said | A. The reviewer agrees: it hides nothing an agent needs, the "Lighting mode" line stays, and rig paths aren't for an agent to edit; B hands it Kit's prims, C leaves "lit viewport, no lights" unexplained. A needs P1's wording (done) | A (serionist, 2026-11-01) |
| Q2 | The list's length: A, every light; B, the first 20, then `... and N more`; C, the whole answer through `text_response` | B. The reviewer agrees: the other tools' form, though `manage_extensions` cuts at 50 and `create_robot` at 10 (taken into Q2) | B (serionist, 2026-11-01) |

**Improvements:**

1. Walk each instance's prototype once, not every instance's copy: far less time on Kit's main thread on a stage of
   many instanced assets: taken (Design; K6, checked on Context7's OpenUSD docs and usd-core; step 1).
2. `test_project/scenarios.md` 23.1 and 23.2 check that in Default the list names no `/OmniKit_Viewport_LightRig`
   path and the rig line shows: taken (Docs; step 4).
3. Tell a rig from the mode alone, any mode but `off`, `camera` and `stage`, so the rig line doesn't hang on Kit's
   list of rigs, which can fail with one warning: taken (Design; step 3).
4. Mark lights inside instances in the list, since USD refuses edits to a prim inside an instance: taken, as
   `in_instance` and `inside an instance, read only` (Design; steps 2 and 3).

### Owner calls

**Q1. What the get says of the rig's lights.**

| Option | What | For | Against |
|---|---|---|---|
| A | The bridge leaves them out; the server names the rig from the mode, with what it means for `stage` (Design) | One answer to "does the stage have lights"; no rig paths for an agent to edit, where a write would leave an `over` under `/OmniKit_Viewport_LightRig` in the user's own file | The server reads the rig from the mode, not from the stage |
| B | The bridge sends them as `rig_lights`; the server lists them under their own heading | Shows exactly what lights the viewport | A new answer key; puts Kit's prims in front of an agent as if they were editable |
| C | The bridge leaves them out; the server says nothing more | Extension alone, no plan needed | In Default the viewport looks lit while the get says no lights, with no word why |

Recommendation: A. **Answer:** A (serionist, 2026-11-01).

**Q2. The list's length, now that instances can multiply it.** A warehouse with 300 instanced lamps lists 300 lights.

| Option | What |
|---|---|
| A | Every light, as the get does today for lights outside instances |
| B | The first 20, then `... and N more`: the other tools' form, at 20 (`manage_extensions` cuts at 50, `create_robot` at 10) |
| C | The whole answer through `text_response`: inline up to 1000 characters, else to a file, and "Scene has lights" with it |

Recommendation: B. "Scene has lights" and the count stay inline, where C can move them into a file, and 20 lights
are enough to see what lights the stage. **Answer:** B (serionist, 2026-11-01).
