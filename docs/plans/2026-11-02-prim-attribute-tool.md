---
title: Add set_prim_attribute, which sets one attribute of a prim, such as a light's intensity
issue: "#151"
status: draft
approved_by:
approved_at:
---

# Add set_prim_attribute, which sets one attribute of a prim, such as a light's intensity

A new tool, `set_prim_attribute(prim_path, name, value)`, sets one attribute a prim already has: a schema's, such as
a light's `inputs:intensity` or a camera's `focalLength`, or one already authored. The extension converts the JSON
value to the attribute's type itself, checks a token against its allowed tokens, and refuses what wouldn't show or
belongs to another tool. The answer gives the value before and after, and the layer written.

## Goal

When this is done:

- **An agent sets an attribute without code:** a light's intensity or colour, a camera's focal length or projection, a
  sphere's radius, a display colour; `execute_script` is no longer the only way.
- **A write that couldn't show is refused, saying why:** a stronger layer's value, time samples, an instance proxy.
- **O1 can pass:** the outcome scenario that asks for a lit picture gets a light's intensity set with a tool (#146's
  O1, WARN in all three runs for that one `execute_script`).

Why, from #151: in O1 every agent made a `DistantLight` with `create_prim`, got UsdLux's fallback intensity of 50,000
(F1), an overexposed picture, and turned it down with `execute_script`.

| In scope | Out of scope |
|---|---|
| The tool, its route, client method, handler and a Kit-free core module; their tests; docs; the `scene` skill's lighting section | Creating a new, custom attribute (Q2) |
| Converting JSON to the attribute types USD's lights, cameras, shapes and primvars use (Q3) | Relationships (material bindings: `set_material`; a joint's bodies), matrices |
| Refusing attributes another tool owns: xform ops, `visibility` (Q3) | Setting time samples (Q4); several attributes in one call (Q1) |
| A scripted scenario and the O1 outcome run | Kit's undo: like the other edit tools, the write isn't recorded (F9) |

## What the code says

Read at `6a6982c`.

| # | Finding | Where |
|---|---|---|
| F1 | UsdLux's `DistantLight` has a fallback `inputs:intensity` of 50,000; `DomeLight` and `SphereLight` 1.0. So a `DistantLight` from `create_prim` is 50,000 on any USD, not only Isaac Sim | usd-core 26.11, measured: `stage.DefinePrim("/L", "DistantLight").GetAttribute("inputs:intensity").Get()` |
| F2 | No tool writes an arbitrary attribute. `create_prim` takes a type, transform, `usd_path` and `enable_physics`; `set_visibility`, `set_material`, `set_physics_properties` and `set_prim_transform` each write their own | `src/omniverse_mcp/tools/scene.py:139-199`, `:220-297`; `tools/simulation.py:141` |
| F3 | `get_prim_properties` reads every attribute's value as a prim block, `format_value` writing each; its JSON form uses `_serialize_value` | `tools/scene.py:105-116`; `ovmcp/core/formatter.py:30-65`; `handlers/_utils.py:276-300` |
| F4 | `Usd.Attribute.Set` takes an int for a float, `True` for a double (as 1.0), a disallowed token (`projection = "fisheye"`), NaN, and a string for an asset; it raises `Tf.ErrorException` "Type mismatch" for a Python list on `color3f` or `float2`. So the bridge converts and checks values itself | usd-core 26.11, measured |
| F5 | An attribute's `GetTypeName()` gives `scalarType`, `isArray`, `role` (`Color` for `color3f`) and `type.pythonClass`: `Gf.Vec3f` for `color3f`, `Vt.Vec3fArray` for `color3f[]`, `None` for `float`, `double`, `token`, `asset`. `GetMetadata("allowedTokens")` gives a token's choices from its schema (`Camera.projection`: perspective, orthographic) | usd-core 26.11, measured |
| F6 | A schema's attributes are valid on a typed prim before anything authors them (`DistantLight`'s `inputs:intensity`, `Cube`'s `size`); a name the prim lacks gives an invalid attribute | usd-core 26.11, measured |
| F7 | `write_transform` writes into the edit target's layer, refusing first, through `_blocker`, a write that couldn't show: a stronger layer holding the value ("nothing would change"), time samples in the written layer or a stronger one, or samples in a weaker one it would freeze | `ovmcp/core/xform.py:130-166`, `:407-437` |
| F8 | An instance proxy or an inactive prim is refused elsewhere with a reason naming the instance: `material_refusal`, `why_kept` | `ovmcp/core/material.py:179-204`; `ovmcp/core/deletion.py:33-52` |
| F9 | The edit tools write USD directly, outside Kit's undo; `delete_prim`'s description says its delete isn't recorded | `tools/scene.py:207` |
| F10 | The routes table; an older extension answers `Unknown endpoint`, which the server turns into "the Kit extension is older than this MCP server and lacks this tool" | `bridge/extension.py:105-147`; `tools/_bridge.py:13-14`, `:49` |
| F11 | The contract test wants every tool annotated and described, every parameter described, the golden file as `tools/golden.py` writes it, and a `docs/TOOLS.md` heading per tool | `tests/test_contract.py:40-109` |
| F12 | The `scene` skill tells an agent to add a light with `create_prim` when a viewport rig doesn't suit; it says nothing of intensity | `plugin/skills/scene/SKILL.md:46-53` |

## Design

### The tool

```python
@tool(mcp, EDITS)
def set_prim_attribute(
    prim_path: PrimPath,
    name: Annotated[str, Field(description='The attribute, as get_prim_properties names it, e.g. "inputs:intensity"')],
    value: Annotated[
        bool | int | float | str | list[Any],
        Field(description="Its new value in JSON: a number, true or false, a string or token, or a list for a vector, "
              "colour or array, e.g. [1, 0, 0]"),
    ],
) -> str:
```

In `tools/scene.py`, beside `set_visibility`; route `/scene/attribute`, client `set_attribute(prim_path, name, value)`,
handler `handle_set_attribute` in `handlers/scene.py`. The answer, one prim block:

```
[/World/SunLight]
inputs:intensity = 3000 (float; was 50000)
written to the stage's root layer
```

The description says: use it for an attribute no other tool sets (a light's intensity or colour, a camera's focal
length, a shape's size or radius, a display colour); `set_prim_transform`, `set_visibility`, `set_material` and
`set_physics_properties` for theirs; the attribute must exist on the prim (`get_prim_properties` lists them, a
schema's included); the value is converted to its type, a token must be one of its allowed ones; refused, with
nothing written: a relationship, an xform op, `visibility`, an animated attribute, one a stronger layer holds, a prim
inside an instance, an inactive prim. A `DistantLight` comes at 50,000 (UsdLux's sunlight); a few thousand suits a
viewport capture.

### The core, `ovmcp/core/attribute.py`

Kit-free, tested on usd-core:

- **`attribute_refusal(prim, name) -> str | None`:** the prim inactive, or an instance proxy (naming the instance, as
  F8's do); the name a relationship ("set_material binds materials"); an xform op or `xformOpOrder`
  ("set_prim_transform"); `visibility` ("set_visibility"); no such attribute (naming up to 12 of the prim's attribute
  names, so the agent can pick).
- **`convert(attr, value) -> object`:** by the type name's scalar type and `isArray` (F5); `ValueError` with the type
  and the value when it doesn't fit:

| USD type | JSON value | Refused |
|---|---|---|
| `bool` | `true`, `false` | a number |
| `int`, `uint`, `int64`, `uint64`, `uchar` | a whole number in the type's range | `true`/`false`, a fraction |
| `half`, `float`, `double`, `timecode` | a number | `true`/`false`, NaN, infinity |
| `string` | a string | |
| `token` | a string, one of its allowed tokens when it has them | another string, naming the allowed ones |
| `asset` | a string: a path or URL, written as given | |
| `float2/3/4`, `double2/3/4`, `half2/3/4`, `int2/3/4`, colours, points, normals, vectors, texture coordinates | a list of 2, 3 or 4 numbers, as the type needs | a list of another length |
| `quatf`, `quatd`, `quath` | `[w, x, y, z]` | |
| any of the above as an array (`color3f[]`, `float[]`) | a list of the element's values; `[]` empties it | |
| matrices, `opaque`, `dictionary`, path expressions | | every value: no tool sets them (Q3) |

- **`set_attribute(prim, name, value, layer=None) -> Written`:** the refusal, the conversion, then F7's check, shared
  with `write_transform` (made public as `write_blocker` in `core/xform.py`); writes the default value in the layer
  (the edit target's when None) inside `Usd.EditContext`; reads it back, so the answer shows what USD stored (a float
  rounds); `Written(name, type_name, before, after, layer)`.

### The handler

`handle_set_attribute(body)`: the prim found, `await _next_update()` as `handle_transform` does, `set_attribute` on
Kit's main thread; a refusal or `ValueError` answers `{"status": "error"}` with nothing written; success answers the
`Written` fields, values through `_serialize_value`, the layer through `layer_name`.

### Alternatives

| Alternative | Taken? | Why |
|---|---|---|
| An `attributes` parameter on `create_prim` | No | Only at creation: "make the light dimmer" on an existing light would still need code, and `create_prim`'s contract grows a second job |
| A light tool, `set_light(intensity, color, ...)` | No | One tool per kind of prim; a camera's focal length or a sphere's radius would each need another |
| Several attributes in one call (`attributes: {name: value}`) | No (Q1) | A failed third leaves the first two written, or needs a rollback; one call each keeps the answer and the error plain |
| Kit's `ChangeProperty` command, for undo | No | The other edit tools write USD directly (F9); one undoable tool among them would mislead |

### Decisions for the maintainer

| # | Question | Recommendation |
|---|---|---|
| Q1 | The name and shape: `set_prim_attribute(prim_path, name, value)`, one attribute a call; or several a call? | One a call, that name: an agent calls twice for intensity and colour, and a refusal never leaves half a change |
| Q2 | An attribute the prim lacks: refuse, or create a custom one (with a type the caller names)? | Refuse, listing the prim's attributes: a typo would otherwise make a new attribute nothing reads |
| Q3 | Which types and names: the table above, refusing relationships, matrices, xform ops and `visibility`? | As the table: the owned names go to their tools, matrices to `set_prim_transform` |
| Q4 | An animated attribute: refuse, as `set_prim_transform` does, or write the default anyway? | Refuse, through the same check, naming the layer with the samples |
| Q5 | The layer: the edit target, refusing a write a stronger layer would hide? | Yes, as every edit tool writes |
| Q6 | An instance proxy or inactive prim: refuse, naming the instance or saying to activate it? | Refuse; the instance root itself may be set |

## Compatibility

- **One-way door, the tool contract:** a new tool, `set_prim_attribute`, with `EDITS` hints and three parameters,
  added to `tests/fixtures/mcp-tools.json` by `uv run tools/golden.py`. Nothing existing changes, so no client
  breaks; the PR names it in its title, and CHANGELOG has it under Added. The maintainer agrees in #151.
- **The wire protocol:** a new route, `/scene/attribute`, behind the same token, `Origin` and `Host` checks. A server
  with an older extension gets F10's "install the server's" answer.
- **Kit apps:** the core uses USD alone (Kit 107+).

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | `write_blocker` made public in `core/xform.py`, `write_transform` unchanged | `tests/test_xform.py` as it is |
| 3 | `core/attribute.py`: `attribute_refusal`, `convert`, `set_attribute` | `tests/test_attribute.py` on usd-core: each row of the type table, both ways; each refusal; a stronger layer and time samples refused; the value read back; nothing written on a refusal |
| 4 | The handler, the route, the client method, the tool | `tests/test_scene_handler.py` (the fake Kit's usd-core stage), `tests/test_client.py`, `tests/test_tools.py` (the route, the body, the answer), `tests/test_contract.py` after `golden.py` |
| 5 | Docs and the skill | the contract test's heading check; the gate |
| 6 | Live: a case in `tests/test_integration.py` (a `DistantLight`'s intensity set and read back with `get_prim_properties`, a token refused, an xform op refused); both live suites on Z-up and Y-up stages; a scripted scenario in Phase 23 and its twin in `tests/test_scenarios.py`; the O1 outcome, `uv run tools/scenarios.py run --phases none --outcomes O1`, twice | the PR quotes them |
| 7 | `finish-work`: the gate in full, `review-code` | the review record |

## Tests

- **Unit (CI):** `tests/test_attribute.py` (new), `tests/test_scene_handler.py`, `tests/test_client.py`,
  `tests/test_tools.py`, `tests/test_contract.py`, `tests/test_xform.py` unchanged.
- **Live suites, by hand:** `test_integration.py`'s new case and `test_scenarios.py`'s Phase 23 twin, on a headless
  Isaac Sim 6.2 at 8212, Z-up and Y-up.
- **AI scenarios:** the new Phase 23 scenario, and O1 twice: its agent should light the stage without `execute_script`.
  `outcomes.md`'s header, which says no tool sets a light's intensity, changes with it.
- **What neither shows:** every attribute type of every schema Kit apps carry; the table covers the ones lights,
  cameras, shapes and primvars use, and the rest are refused by name.

## Docs

- `docs/TOOLS.md`: a `set_prim_attribute` heading in Scene Tools; a row in "Find a tool" ("set a light's intensity or
  another attribute"); the not-destructive hints row.
- `docs/ARCHITECTURE.md`: `/scene/attribute -> handle_set_attribute`.
- `CHANGELOG.md`: Added, with the extension install line.
- `plugin/skills/scene/SKILL.md`: the lighting section sets a new light's intensity; `docs/AI_GUIDE.md` if it lists
  the tools.
- `test_project/outcomes.md`: O1's expected path names the tool.

## Risks

| Risk | What then |
|---|---|
| A value Kit's renderer or PhysX can't take, such as a negative radius or an absurd intensity | Accepted: USD takes it as it takes any author's value, and the answer shows it; finite numbers only, so NaN and infinity never reach Kit |
| A write in a layer a stronger one outranks changes nothing | Refused before writing, by F7's check, naming both layers |
| A physics attribute set while the simulation plays may not reach PhysX until it stops | Named in the description; the answer shows the authored value |
| A very large array in one call | Accepted: the bridge's request size limit already bounds it |
| An attribute another tool owns, written here, leaves that tool's state behind (a material input bypassing `set_material`'s defaults) | Accepted for shader inputs, which `set_material` doesn't own whole; refused for xform ops and `visibility`, which have rules of their own |

## Plan review

Not reviewed yet.
