---
title: Leave the viewport's light rig out of viewport_light's scene lights
issue: "#117"
status: draft
approved_by:
approved_at:
---

# Leave the viewport's light rig out of viewport_light's scene lights

`viewport_light`'s get counts the viewport's light rig as the stage's lights: in a rig mode such as Default it says
"Scene has lights: yes" on a stage with none of its own, and lists the rig's `DomeLight` and `DistantLight`. The
captures' check, `_has_scene_lights` (#105), walks inside instances where the get doesn't. This plan gives both one
check, which walks inside instances and leaves the rig out, and has the get say the rig apart.

## Goal

When this is done, with this release's Kit extension:

| What | True when done | Shown by |
|---|---|---|
| The get's `has_scene_lights` and `scene_lights` | The stage's own lights, inside instances too; never the rig's, in any mode. A stage without lights reads "no" in Default as in `stage` | `test_lighting.py`, `test_camera_handler.py`; live `test_12j` |
| The captures' `has_scene_lights` | The same check as the get's | `test_camera_handler.py` |
| The get's text in a rig mode | Says the rig lights the viewport, apart from the stage's lights (Q1) | `test_tools_camera.py` |
| The get's list | Bounded, now that instances can multiply it (Q2) | `test_tools_camera.py` |

Why: `viewport_light`'s description sends an agent to the get to ask whether the stage needs lights. In Default it
reads yes and adds none, then switches to `stage`, or saves the scene for another app, and gets black surfaces.

| In scope | Out of scope |
|---|---|
| The light check, the get's answer and text, the tool's description | `get_scene_tree` and `list_prims` showing `/OmniKit_Viewport_LightRig` and Kit's cameras |
| `test_12j` reading the get in a rig mode | `inspect_prim`'s isolate, which keeps the rig visible as it should: its lights light the capture |
| `docs/TOOLS.md`, the scene skill, `CHANGELOG.md` | Grey Studio's ground plane, which the rig brings beside its lights |

## What Kit does

Read on disk, in `omni.kit.viewport.menubar.lighting` 107.3.4 (Isaac Sim 6.2) and 107.3.1 (Isaac Sim 5.1); K1 to K3
also rebuilt on usd-core, as step 1's test does:

| # | What | Where |
|---|---|---|
| K1 | A rig mode authors an `over` at `/OmniKit_Viewport_LightRig` in the session layer, references the rig's file from it (`data/usd/Default.usda` and the others), and marks it `hide_in_stage_window` and `no_delete`. The path is a literal in Kit's code, twice, in both versions; nothing exports it | `actions.py:195`, `:205-224` (107.3.4); `:185` (107.3.1) |
| K2 | The rig file's prims `def` the lights, so the over composes a defined prim: `Traverse` and the walk inside instances both reach `/OmniKit_Viewport_LightRig/Lights/DomeLight` and `.../DistantLight` (#105's probe saw the same on Isaac Sim 6.2) | `data/usd/Default.usda`; usd-core |
| K3 | Modes `stage`, `camera` and `off` clear the over's references and leave the over: an undefined prim, which neither walk visits | `actions.py:88-94`, `:230-232` |
| K4 | A rig mode also hides every light of the stage's own, through visibility in the session layer; `stage` shows them again | `actions.py:217-219`, `utility.py` `VisibilityEdit` |
| K5 | NVIDIA's asset validator skips the same path, and the subtree under it, as a prim Kit makes | `omni.asset_validator.core-1.22.0`, `_compliance_checker.py:26-66` |

So the rig is told by its path, the one Kit writes and NVIDIA's own validator skips. Telling it by the session layer
instead doesn't work: the rig's light specs are in the rig's file, reached through the session layer's reference,
and a walk would need each light's composition arcs to know; it would also drop any light a script put in the session
layer on purpose.

## Design

**Extension, `ovmcp/core/lighting.py`** (Kit-free, tested on usd-core):

- `LIGHT_RIG = Sdf.Path("/OmniKit_Viewport_LightRig")`, with K1 as its why.
- `scene_lights(stage) -> Iterator[Usd.Prim]`: `Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())`, pruning
  the subtree at `LIGHT_RIG`, yielding each prim `isolation.is_light` takes. Lazy, so a yes/no stops at the first.

**Extension, `handlers/camera.py`:**

- `_has_scene_lights()` is `next(scene_lights(stage), None) is not None`.
- The get lists `scene_lights(stage)` in place of its `stage.Traverse()` loop. The answer keeps its keys:
  `has_scene_lights`, `scene_lights` (path, type, intensity). A light inside an instance has its proxy's path.

**Server, `tools/camera.py`, the get:**

- A rig mode is a mode the get lists in `available_modes` that isn't `off`, `camera` or `stage`. In one, a line after
  "Scene has lights" says the rig apart (Q1, A):
  - no lights: `The light rig 'Default' lights the viewport with lights of its own, which aren't the stage's: in mode
    'stage', or in another app, the stage's surfaces render black. create_prim (DistantLight, DomeLight) lights the
    stage itself.`
  - lights: `The light rig 'Default' lights the viewport in place of the stage's lights, which Kit hides until the
    mode is 'stage'.` (K4)
- The list prints the first 20 lights, then `... and N more` (Q2, B), as `manage_extensions` and `create_robot`
  cut theirs.
- The description: the get answers "the stage's own lights, inside instances too, with their intensity; a light
  rig's lights are the viewport's, not the stage's, and aren't among them".

Alternatives: Q1 and Q2 hold them.

## Compatibility

No one-way door: no tool, parameter, hint, route or key changes, and `tests/fixtures/mcp-tools.json` holds no
descriptions. `scene_lights` changes in what it holds: no rig lights, and lights inside instances.

A server of this release with an older Kit extension prints the rig line beside the old list, which still holds the
rig's lights. The CHANGELOG line says to run `uvx omniverse-mcp extension install`; 0.x doesn't keep older extensions
working.

## Steps

1. **Core:** `LIGHT_RIG` and `scene_lights` in `core/lighting.py`. `tests/test_lighting.py`: a rig authored as K1
   does, over a usd-core rig file with a DomeLight and a DistantLight, is left out; a light inside an instance counts;
   a stage light counts; the rig with its references cleared (K3) adds nothing.
2. **Handler:** `_has_scene_lights` and the get use it. `tests/test_camera_handler.py`: the get with the rig and an
   instanced lamp lists the lamp's light and not the rig's, `has_scene_lights` true; with the rig alone, false; a
   capture in mode `stage` with the rig's over left (K3) and no light says false.
3. **Server:** the get's text (Q1, Q2) and the description. `tests/test_tools_camera.py`: a rig mode with and without
   lights, mode `stage` unchanged, 25 lights printing 20 and `... and 5 more`.
4. **Live test and docs:** `test_12j` reads the get in Default, when on offer, and again in each mode it captures in,
   asserting the same `has_scene_lights` every time and no path under `/OmniKit_Viewport_LightRig`, and the
   warnings follow that one answer. `e1a47f7` had it read the get after each switch, to work around this bug; that
   goes. The docs below.

## Tests

| Suite | What |
|---|---|
| Unit (CI) | Steps 1 to 3 |
| Live, by hand on Isaac Sim 6.2, Z-up and Y-up | `test_integration.py::test_12j`; `test_scenarios.py`'s phase 23, `test_23_01` to `test_23_06` |
| Neither | Isaac Sim 5.x (Kit 107), read on disk only (K1); USD Composer, not on this machine; Linux |

## Docs

- `docs/TOOLS.md`, `viewport_light`'s get: the stage's own lights, inside instances, not the rig's.
- `plugin/skills/scene/SKILL.md`, Light and black captures: a rig's lights aren't the stage's.
- `CHANGELOG.md`, Fixed: the get no longer counts the rig; the fix is in the Kit extension and the server.

## Risks

| Risk | Status |
|---|---|
| A later Kit moves the rig (K1's path is private to Kit): the get counts its lights again, as today | Accepted: `test_12j` reads Default against `stage` and fails then |
| The walk inside instances is slower than `Traverse` on a stage with many instances, on Kit's main thread, at each get | Accepted: the captures' check in mode `stage` already walks it (#105); the get is rare |
| A stage saved flattened with its session layer, from a rig mode, holds the rig's lights at `LIGHT_RIG` in its own layer, which then light mode `stage`; the get leaves them out | Accepted: Kit's Save writes no session layer; only a flattened export that took it along would |

## Plan review

Not yet reviewed.

### Owner calls

**Q1. What the get says of the rig's lights.**

| Option | What | For | Against |
|---|---|---|---|
| A | The bridge leaves them out; the server names the rig from the mode, with what it means for `stage` (Design) | One answer to "does the stage have lights"; no rig paths for an agent to edit, where a write would leave an `over` under `/OmniKit_Viewport_LightRig` in the user's own file | The server reads the rig from the mode, not from the stage |
| B | The bridge sends them as `rig_lights`; the server lists them under their own heading | Shows exactly what lights the viewport | A new answer key; puts Kit's prims in front of an agent as if they were editable |
| C | The bridge leaves them out; the server says nothing more | Extension alone, no plan needed | In Default the viewport looks lit while the get says no lights, with no word why |

Recommendation: A.

**Q2. The list's length, now that instances can multiply it.** A warehouse with 300 instanced lamps lists 300 lights.

| Option | What |
|---|---|
| A | Every light, as the get does today for lights outside instances |
| B | The first 20, then `... and N more`, as `manage_extensions` and `create_robot` cut theirs |
| C | The whole answer through `text_response`: inline up to 1000 characters, else to a file, and "Scene has lights" with it |

Recommendation: B. "Scene has lights" and the count stay inline, where C can move them into a file, and 20 lights
are enough to see what lights the stage.
