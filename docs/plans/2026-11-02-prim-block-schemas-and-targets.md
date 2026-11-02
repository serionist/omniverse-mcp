---
title: List a prim's applied schemas and its relationships' targets in its prim block
issue: "#149"
status: draft
approved_by:
approved_at:
---

# List a prim's applied schemas and its relationships' targets in its prim block

`get_prim_properties` names a prim's attributes but not the API schemas applied to it, and prints every relationship
as `<unreadable>`, a material binding included. This change adds an `api_schemas` line to a prim block and prints each
relationship with its target paths, in the text and in `/scene/prim`'s JSON, so an agent can tell whether a floor has
a collider or which material a cube is bound to without `execute_script`.

## Goal

When this is done:

- **A prim block lists its applied schemas:** `api_schemas = MaterialBindingAPI, PhysicsCollisionAPI`, or `[]` when
  none, in every block that lists properties.
- **A relationship gives its targets:** `material:binding = /World/Looks/RedCube_Mat`, where it read
  `<unreadable>`; one with no targets is left out, as an unset attribute is.
- **The JSON form says the same:** `/scene/prim`'s result gains `api_schemas`, and a relationship's value in
  `properties` is its list of target paths, there and in `/scene/tree`'s JSON with properties.
- **The tool's description and `docs/TOOLS.md` say so,** where they now say relationships come without targets.

Why, from #149: O4 of the outcome scenarios ("the box falls through the floor: find out why") had every agent read the
prims' applied schemas with `execute_script`, and O1's judges couldn't confirm a material binding.

| In scope | Out of scope |
|---|---|
| `ovmcp/core/formatter.py`'s prim block; `/scene/prim`'s and `/scene/tree`'s JSON; the tool's description, `docs/TOOLS.md`, CHANGELOG | Forwarded targets (`GetForwardedTargets`) and a binding's strength or purpose beyond its relationship's name |
| The scene dump and a recording's `state.txt`, which print the same blocks | A schema's version or its multiple-apply instance names beyond what `GetAppliedSchemas` gives |

## What the code says

Read at `6a6982c`.

| # | Finding | Where |
|---|---|---|
| F1 | `format_prim_block` prints `type`, the pose, the bounds, `articulation_root` and `rigid_body` flags, then, with `include_properties`, each property: a relationship as `<unreadable>`, by design ("its targets have never been listed here"), an attribute by `format_value`, an unset one left out | `ovmcp/core/formatter.py:68-147` |
| F2 | Three callers: `/scene/prim`'s text (`include_properties=True`, bounds), the scene dump (`include_properties` as asked, a `property_filter` too), and a recording's frame state (`include_properties or property_filter`, a filter applied by substring of the property's name) | `handlers/scene.py:163`; `formatter.py:179`, `:276` |
| F3 | `/scene/prim`'s JSON and `/scene/tree`'s JSON with properties call `prop.Get()` on every property; a relationship has none, so it lands in `except` as `<unreadable>` | `handlers/scene.py:66-75`, `:166-171` |
| F4 | `get_prim_properties` asks for the text; its description says "Relationships, such as a material binding, are named without their targets", and `docs/TOOLS.md` the same | `src/omniverse_mcp/tools/scene.py:105-116`; `docs/TOOLS.md:125` |
| F5 | The JSON form reaches scripts through the bridge's `mcp` helper (`prim_properties(prim_path)`), which `execute_script` documents | `src/omniverse_mcp/tools/misc.py:70`; `handlers/_mcp_bridge.py` |
| F6 | `test_a_relationship_is_unreadable_and_an_unset_attribute_is_left_out` pins the old line | `tests/test_formatter.py:163-167` |
| F7 | `Usd.Prim.GetAppliedSchemas()` returns the applied API schema names, multiple-apply ones as `Name:instance` (`['MaterialBindingAPI', 'PhysicsCollisionAPI', 'CollectionAPI:things']`); `Usd.Relationship.GetTargets()` returns the authored targets as `Sdf.Path`s | usd-core 26.11, run at `6a6982c` |
| F8 | `GetProperties()` lists a schema's relationships with no targets too: every gprim's `proxyPrim`, a collider's `physics:simulationOwner`, a collection's `includes` and `excludes`; each prints `<unreadable>` today | usd-core 26.11 |

## Design

### The text

In `format_prim_block`, with `include_properties`:

- **`api_schemas`,** the first property line: `prim.GetAppliedSchemas()` joined by `, `, or `[]` when there are none,
  so a missing collider shows as absent rather than unsaid. A `property_filter` treats it as a property named
  `api_schemas`: shown only when a filter substring is in that name, so a recording filtered to `physics:` keeps
  its lines as they were.
- **A relationship:** its targets, `str(path)` each, through `format_value`, so more than 8 read `a, b, ... (n
  items)` as any list does. One with no targets is left out, as an unset attribute is: every gprim's `proxyPrim` and a
  collider's `physics:simulationOwner` (F8) would otherwise add a line each that says nothing. A relationship whose
  targets can't be read stays `<unreadable>`.

`rigid_body` and `articulation_root` stay where they are: they come without properties too, and scripts and tests read
them.

### The JSON

`/scene/prim`'s result gains `api_schemas`, a list. In `properties`, here and in `/scene/tree`'s JSON with
properties, a relationship's value is its list of target paths, empty when it has none, as an unset attribute's is
`null` there. One helper in `ovmcp/core/formatter.py`,
`relationship_targets(prop) -> list[str] | None` (None for an attribute), serves both forms, so the core keeps the
rule and stays testable without Kit.

### Alternatives

| Alternative | Taken? | Why |
|---|---|---|
| A separate tool for schemas and relationships | No | Agents already read the prim block; another call is one more thing to find |
| `api_schemas` only with physics or material schemas | No | Any schema can matter (`PhysxRigidBodyAPI`, `IsaacRobotAPI`); the line is short |
| Leave the JSON as it is | No | Scripts read it through `mcp.prim_properties` (F5), and the two forms would disagree |

## Compatibility

No one-way door: the tool's name, parameters and hints stay; its answer and description change. A reader that
matched `material:binding = <unreadable>` gets the target instead, and the `<unreadable>` lines of relationships
without targets go; a dump or `state.txt` with properties gains an `api_schemas` line per block. The Kit extension changes, so users get it with `extension install` after the release;
an older extension gives the old blocks. CHANGELOG, under Changed.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | `relationship_targets` and the text's two changes in `format_prim_block` | `tests/test_formatter.py`: targets, more than 8, none left out (`proxyPrim`); `api_schemas` with none (`[]`), with `MaterialBindingAPI` and `PhysicsCollisionAPI`, a multiple-apply instance; a filter that excludes it and one that keeps it; a frame state; F6's test rewritten |
| 3 | The JSON forms | `tests/test_scene_handler.py`: `/scene/prim`'s JSON gives `api_schemas` and a binding's target; `/scene/tree`'s JSON with properties gives the target |
| 4 | The description, `docs/TOOLS.md`, CHANGELOG | `tests/test_contract.py` unchanged (no contract change); the docs read |
| 5 | A live check | `tests/test_integration.py`: a cube given `set_material` and a friction lists `MaterialBindingAPI` and `PhysicsCollisionAPI` and its binding's target, in the text and the JSON |
| 6 | `finish-work`: the gate in full, `review-code`, the live suites on Z-up and Y-up stages, and O4 in an outcome run | the review record; the PR |

## Tests

- **Unit (CI):** steps 2 and 3, on usd-core stages.
- **Live, by hand:** both suites on my headless Isaac Sim 6.2 at 8212, on Z-up and Y-up stages; step 5's new check.
  O4 in an outcome run (`uv run tools/scenarios.py run --phases none --outcomes O4`) shows whether its agent still
  reads schemas with code; the PR quotes it.
- **What neither shows:** whether agents use the new lines; the outcome run gives one sample.

## Docs

- `get_prim_properties`' description and `docs/TOOLS.md`'s section: applied schemas, and relationships with their
  targets.
- CHANGELOG, Unreleased, Changed, with the extension install line.

## Risks

| Risk | What then |
|---|---|
| A prim with many relationships or schemas makes blocks longer | Accepted: a line each, and 8 targets at most before `... (n items)` |
| A reader parses `<unreadable>` | Accepted: the tool's own description told readers it meant a relationship; the CHANGELOG names the change |
| `GetAppliedSchemas` reads a schema Kit's USD doesn't know (an unregistered name) | It returns the authored name, which is what an agent needs; no error |

## Plan review

Not reviewed yet.
