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
  `<unreadable>`; one with no targets is left out of the text, as an unset attribute is. The issue asked for an empty
  list there; F8 is why not: every gprim's `proxyPrim` and every collider's `physics:simulationOwner` would add a
  line that says nothing. The JSON keeps them, empty, as it keeps an unset attribute as `null`.
- **The JSON form says the same:** `/scene/prim`'s result gains `api_schemas`, and a relationship's value in
  `properties` is its list of target paths, there and in `/scene/tree`'s JSON with properties.
- **The tool's description and `docs/TOOLS.md` say so,** where they now say relationships come without targets,
  and `get_scene_tree`'s with `include_properties`; with an extension older than this change, `get_prim_properties`
  says so and how to install the server's.

Why, from #149: O4 of the outcome scenarios ("the box falls through the floor: find out why") had every agent read the
prims' applied schemas with `execute_script`, and O1's judges couldn't confirm a material binding.

| In scope | Out of scope |
|---|---|
| `ovmcp/core/formatter.py`'s prim block; `/scene/prim`'s and `/scene/tree`'s JSON; the tool's description, `docs/TOOLS.md`, CHANGELOG | Forwarded targets (`GetForwardedTargets`) and a binding's strength or purpose beyond its relationship's name |
| The scene dump and a recording's `state.txt`, which print the same blocks | A schema's version or its multiple-apply instance names beyond what `GetAppliedSchemas` gives |
| The `scene` and `simulate` skills, which send agents to these blocks | Schema names authored but not registered in the running app (P1) |
| | `format_scene_tree`'s text with properties, which no tool reaches: `get_scene_tree` sends `include_properties` only for a dump |

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
| F7 | `Usd.Prim.GetAppliedSchemas()` returns the applied API schemas the running app has registered, multiple-apply ones as `Name:instance` (`['MaterialBindingAPI', 'PhysicsCollisionAPI', 'CollectionAPI:things']`), a type's built-in ones included (a `DistantLight` gives `LightAPI, CollectionAPI:lightLink, CollectionAPI:shadowLink`); an authored name the app hasn't registered is left out (`PhysxRigidBodyAPI` on usd-core), where `GetPrimTypeInfo().GetAppliedAPISchemas()` keeps it. `Usd.Relationship.GetTargets()` returns the authored targets as `Sdf.Path`s, an instance proxy's mapped to real paths | usd-core 26.11, run at `6a6982c` and by the round 1 reviewer |
| F8 | `GetProperties()` lists a schema's relationships with no targets too: every gprim's `proxyPrim`, a collider's `physics:simulationOwner`, a collection's `includes` and `excludes`; each prints `<unreadable>` today | usd-core 26.11 |

## Design

### The text

In `format_prim_block`, with `include_properties`:

- **`api_schemas`,** the first property line: `prim.GetAppliedSchemas()` joined by `, `, or `[]` when there are none,
  so a missing collider shows as absent rather than unsaid. It gives what the running app applies: the schemas it has
  registered, a type's built-in ones included (F7). A name the app doesn't know is left out, as physics ignores it
  too; on Isaac Sim, which registers PhysX's and Isaac's schemas, `PhysxRigidBodyAPI` and `IsaacRobotAPI` show. A `property_filter` treats it as a property named
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

### The older extension

An extension without this change gives blocks without `api_schemas`. `get_prim_properties` checks for the line in its
text: missing, it adds a `WARNING:` line that the extension is older than the server and how to install the server's
(`install_advice`), as `delete_prim` does with its `checked` flag, rather than leaving an agent to read
`<unreadable>` against a description that says targets come.

### Alternatives

| Alternative | Taken? | Why |
|---|---|---|
| A separate tool for schemas and relationships | No | Agents already read the prim block; another call is one more thing to find |
| `api_schemas` only with physics or material schemas | No | Any schema can matter (`PhysxRigidBodyAPI`, `IsaacRobotAPI`); the line is short |
| Leave the JSON as it is | No | Scripts read it through `mcp.prim_properties` (F5), and the two forms would disagree |

## Compatibility

No one-way door: the tool's name, parameters and hints stay; its answer and description change. `PROTOCOL` stays 1:
the server reads only the text, and a bump would refuse every tool on an older extension. A reader that
matched `material:binding = <unreadable>` gets the target instead, and the `<unreadable>` lines of relationships
without targets go; a dump or `state.txt` with properties gains an `api_schemas` line per block. The Kit extension changes, so users get it with `extension install` after the release;
an older extension gives the old blocks. CHANGELOG, under Changed.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | `relationship_targets` and the text's two changes in `format_prim_block` | `tests/test_formatter.py`: targets, more than 8, none left out (`proxyPrim`); `api_schemas` with none (`[]`), with `MaterialBindingAPI` and `PhysicsCollisionAPI`, a multiple-apply instance, a light's built-in ones, and an authored name usd-core doesn't register left out (F7); a filter that excludes it and one that keeps it; a frame state; F6's test rewritten, and `test_a_prim_without_a_transform_has_no_pose`, which pins a whole block, given its `api_schemas = []` line |
| 3 | The JSON forms | `tests/test_scene_handler.py`: `/scene/prim`'s JSON gives `api_schemas` and a binding's target; `/scene/tree`'s JSON with properties gives the target |
| 4 | The descriptions (`get_prim_properties`, `get_scene_tree`'s `include_properties`), the older extension's warning, `docs/TOOLS.md`, the `scene` and `simulate` skills (`write-skill`), the judging rules, CHANGELOG | `tests/test_contract.py`'s `test_a_description_says_what_the_tool_now_does` gains rows ("applied API schemas", "with their targets"); `tests/test_tools.py`: a text without `api_schemas` gives the warning |
| 5 | A live check | `tests/test_integration.py`: a cube given `set_material` and a friction lists `MaterialBindingAPI` and `PhysicsCollisionAPI` and its binding's target, in the text and the JSON; a plain cube's `api_schemas`, which shows any schema Kit applies on its own |
| 6 | `finish-work`: the gate in full, `review-code`, the live suites on Z-up and Y-up stages, and O4 in an outcome run | the review record; the PR |

## Tests

- **Unit (CI):** steps 2 and 3, on usd-core stages.
- **Live, by hand:** both suites on my headless Isaac Sim 6.2 at 8212, on Z-up and Y-up stages; step 5's new check.
  O4 in an outcome run (`uv run tools/scenarios.py run --phases none --outcomes O4`) shows whether its agent still
  reads schemas with code; the PR quotes it.
- **What neither shows:** whether agents use the new lines; the outcome run gives one sample.

## Docs

- `get_prim_properties`' description and `docs/TOOLS.md`'s section: applied schemas, and relationships with their
  targets; with an older extension, the warning. `get_scene_tree`'s description, its `include_properties` parameter
  and `docs/TOOLS.md:100-101`: the same for a dump's blocks.
- `plugin/skills/scene/SKILL.md` (its `get_prim_properties` line) and `plugin/skills/simulate/SKILL.md` (step 2: check
  a collider by `api_schemas`, and `get_prim_properties` in its `allowed-tools`), through `write-skill`.
- `test_project/AGENTS.md`'s judging section: read a binding or a schema with `get_prim_properties`.
- CHANGELOG, Unreleased, Changed, with the extension install line.

## Risks

| Risk | What then |
|---|---|
| A prim with many relationships or schemas makes blocks longer | Accepted: a line each, and 8 targets at most before `... (n items)` |
| A reader parses `<unreadable>` | Accepted: the tool's own description told readers it meant a relationship; the CHANGELOG names the change |
| An authored schema the app hasn't registered | Left out, as physics ignores it too (F7); Isaac Sim registers PhysX's and Isaac's schemas, so they show there; a test pins the rule |
| A schema Kit applies on its own, such as to every new prim | Step 5's plain cube shows it; the line then says what Kit applied, which is true |

## Plan review

### Round 1

**How:** one fresh reviewer on Claude Opus 5.5, every lens, 2026-11-02, at `5ead132`, with two usd-core checks of its
own. **Verdict:** approved once P1 to P5 are applied, which this round does; no blocker, major or owner call, so no
second round.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | `GetAppliedSchemas` leaves out an authored name the app hasn't registered and adds a type's built-in schemas; the plan's F7 and Risks row said it returned the authored names, and a test built on `PhysxRigidBodyAPI` would fail on usd-core | fixed: F7, Design and Risks say what it gives; step 2 pins both |
| P2 | minor | `test_a_prim_without_a_transform_has_no_pose` pins a whole block and would fail on the new line, unnamed in step 2 | fixed: named |
| P3 | minor | Docs missed `get_scene_tree`'s description and parameter and an older extension, where a new server would promise targets and an old extension print `<unreadable>` | fixed: those docs, and a warning in the answer (Design, The older extension) |
| P4 | minor | The `scene` and `simulate` skills don't send an agent to the new lines, and O4's agents pick tools through them | fixed: both skills, through `write-skill` |
| P5 | minor | The plan leaves empty relationships out of the text where the issue asked for an empty list, without saying so | fixed: Goal says so, with F8's reason |

**Refuted:** the JSON's empty relationships contradicting the text (each form is consistent with itself, as unset
attributes are); tests that pin line order (`test_07_03` and the property filter test survive, the line showing only
when a filter matches); instance proxies' targets (mapped to real paths); the Kit-free core (`formatter.py` already
imports pxr alone); a protocol bump (the server reads only the text); the contract (descriptions are stripped from
the fixture); `state.txt`'s growth (a recording passes only a filter, and empty relationships' `<unreadable>` lines
go); block counts (tests count lines starting with `[`).

**Owner calls:** none. Optional, answered by the reviewer's recommendation: authored but unregistered schema names stay
out.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Rows in `test_contract.py`'s description test, not "the docs read" | taken |
| I2 | `get_prim_properties` warns when `api_schemas` is missing: an older extension | taken |
| I3 | Compatibility says why `PROTOCOL` stays 1 | taken |
| I4 | `format_scene_tree`'s text with properties named out of scope | taken |
| I5 | The judging rules read bindings and schemas with `get_prim_properties` | taken |
| I6 | Step 5 checks a plain cube's `api_schemas` in Kit | taken |
