---
title: Switch variants in the session layer by default, choose the layer an edit goes to, and list a prim's variant sets, a change to the tool contract
issue: "#155"
status: draft
approved_by:
approved_at:
---

# Switch variants in the session layer by default, choose the layer an edit goes to, and list a prim's variant sets, a change to the tool contract

## Goal

An agent steps through every switch of a scene, captures each, and leaves every file as it found it. Today
`set_variant_selection` writes the selection at the stage's edit target, the root layer, and its Fabric refresh
leaves an `active = true` opinion there too; `compare_prims` "puts the selection back" by writing the old one, so a
selection the file never held becomes one it holds; and no tool lists a prim's variant sets.

The case (#155 and its author, 2026-11-02): a 300 x 300 m construction site in Isaac Sim 6.2 with 128 switches, all
USD variant sets, on each area's root prim (a file `site.usd` payloads, `areas/<area>/<area>.usd`) and on assembly or
asset prims referenced inside those files, many instanceable, where a selection on an instance prim splits its
prototype. The switched prims are never in the root layer's own specs. Files are shared on Nucleus, one writer each:
a check never writes into a person's file, and always only looks, in the session layer. Selections that must persist
are written by the case's own tools. Fabric Scene Delegate may be on.

When this is done:

- `set_variant_selection(prim_path, variant_set, variant_name, layer="session")` writes the selection in Kit's session
  layer by default, or at the edit target with `layer="edit_target"`; `variant_name=""` clears that layer's selection,
  so the files' own shows again; the answer names the layer, what the files select beneath it, and that `save_scene`
  keeps a session selection out of the file;
- its Fabric refresh toggles `active` in the session layer and leaves no opinion behind, whichever layer the
  selection went to;
- `compare_prims` switches two variants in the session layer and puts the layer back exactly as it was;
- `set_prim_attribute(..., layer="auto")` takes the same choice: `auto` is #151's rule, `session` and `edit_target`
  force one;
- `get_prim_properties` lists a prim's variant sets: each set, its selection, its options in order and the layer
  holding the selection, `variant_sets = []` for none.

In scope: the two tools' `layer` parameter, the variant switch's default, `compare_prims`' restore, the variant sets
in the prim block and its JSON, docs, the `geometry` skill, tests.
Out of scope: switching many prims or shots in one call (#157, which builds on this); authoring variant sets
(`create_variant_structure` stays at the edit target: it builds content); a `layer` on the other editing tools
(transforms, visibility, materials), for a later issue once a case asks.

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | `set_prim_attribute` takes the same `layer` choice, added here; #151 merged as approved | yes (maintainer, 2026-11-02) |
| Q2 | A variant switch defaults to the session layer, a change of behaviour; `set_prim_attribute` keeps #151's own rule (`auto`) as its default | yes (maintainer, 2026-11-02, the recommendation taken) |
| Q3 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02) |

### Measured on usd-core 26.11

A prim referencing a file whose variant set selects `closed`: a selection of `open` written in the session layer
(`Usd.EditContext(stage, stage.GetSessionLayer())`) shows (`GetVariantSelection()` reads `open`, the variant's prims
compose), and the root layer's `ExportToString()` is the same before and after. Clearing it there gives `closed` back
and leaves an empty over in the session layer, which `Sdf.CleanupEnabler` removes, as #151's undo does.
`Stage.Flatten()` bakes a session selection, but `flatten_usd` and `export_prim_as_file` flatten the open stage
without Kit's session layer (`layers.without_session`, #118), so a check's switches never reach an export either.

### The extension

- **`ovmcp/core/variants.py`** (Kit-free):
  - `variant_sets(prim)`: for each set in order, its selection, its options in order, and the layer holding the
    selection (the strongest spec in `prim.GetPrimStack()` whose `variantSelections` holds it: `session`, `root` or
    the file's name), or none;
  - `variant_refusal(prim, set, name, layer)`: an instance proxy (a prim inside an instance) is refused, naming the
    instance prim to switch instead; an unknown set or option is refused listing those there, and an unknown set on a
    prim with an unloaded payload says so; `layer="edit_target"` where the session layer holds a selection for that
    set is refused, since it wouldn't show, naming the fix (`variant_name=""` with `layer="session"` first);
  - `select(prim, set, name, layer)`: writes or clears the selection in that layer under `Sdf.CleanupEnabler`, and
    returns what the answer needs, a note when the prim is an instance (its own selection gives it a prototype of its
    own while it differs from its siblings').
- **`ovmcp/core/layers.py`** gains `layer_named(stage, "session" | "edit_target")`, which `variants.py` and
  `attribute.py` share.
- **`handle_set_variant_selection`:** reads `layer` (absent: `edit_target`, today's behaviour, so an older server
  keeps it), refuses before anything is written, writes, then the Fabric refresh: `SetActive(False)` in the session
  layer, frames, then the session layer's `active` opinion put back exactly (cleared when it had none), frames. The
  answer adds `layer`, `files_select` (the selection beneath the written layer) and the instance note.
- **`handle_compare_prims`:** both switches in the session layer, and the session layer's selection for that set put
  back exactly afterwards, cleared when it had none.
- **`handle_set_attribute`:** reads `layer`; `auto` is `target_layer` (#151), the others `layer_named`; the write
  blocker and every refusal stay as they are.
- **The prim block** (`ovmcp/core/formatter.py`): `variant_sets = state: open [closed, open] (session); lod: high
  [high, low] (area_a.usd)`, `[]` for none, always present like `api_schemas`, so the server can tell an older
  extension; `/scene/prim`'s and `/scene/tree`'s JSON add `variant_sets` as a list of
  `{name, selection, options, layer}`.

### The server

- `set_variant_selection`: `layer: Literal["session", "edit_target"] = "session"`; `variant_name` may be `""` to
  clear. The answer: `Variant switched in the session layer: /World/Area state=open (the files select closed; save_scene
  leaves it out of the file)`, the instance note when there is one. An older extension, which answers no `layer`:
  `WARNING:` it wrote at the edit target, into the stage's file.
- `set_prim_attribute`: `layer: Literal["auto", "session", "edit_target"] = "auto"`; the answer names the layer as
  today.
- `get_prim_properties`: warns, as for `api_schemas` (#149), when the text has no `variant_sets` line.
- Descriptions: `set_variant_selection` says the session default and what it means for saving; `set_prim_attribute`
  says when to pick `session` (a check that must leave files as they are).

### Alternatives

- **`get_variants(prim_path)`, a new tool:** no; the prim block already holds a prim's schemas and attributes, and an
  agent reads it anyway; one tool fewer.
- **Default `edit_target`, `session` on request:** no (Q2); the safe default is the one that never writes a person's
  file, and the answer says how to keep a selection.
- **Undo a switch by writing the old selection:** what `compare_prims` does today, and the cause of the stray opinions.

## Compatibility

**One-way door: the tool contract.** `set_variant_selection` gains `layer` and changes its default behaviour (the
session layer, where it wrote the edit target), and takes `""` to clear; `set_prim_attribute` gains `layer`
(additive, `auto` is today's rule). Under `CHANGELOG.md`'s Breaking for the switch's default; `get_prim_properties`
adds a line. The maintainer agreed in #155's thread (posted from the maintainer's chat decisions, 2026-11-02, before
the PR).

- **An agent that switched a variant and saved it:** `layer="edit_target"` writes it into the file as before; the
  answer says where every switch went.
- **An older extension with this server:** both tools warn that the write went to the edit target.
- **An older server with this extension:** no `layer` sent, so the edit target, as before.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/variants.py` and `layers.layer_named`, tests first | `tests/test_variants.py` with usd-core: a referenced file's set switched in the session layer, the root layer's export unchanged, cleared exactly; `edit_target` refused under a session selection; an instance proxy refused; an unloaded payload named; the instance note; `variant_sets` with each layer named |
| 2 | The prim block's `variant_sets` line and the JSON | `tests/test_formatter.py`, `tests/test_scene_handler.py` |
| 3 | `handle_set_variant_selection`, its refresh in the session layer, `handle_compare_prims`, `handle_set_attribute`'s `layer` | handler tests with the Kit fakes: after a switch with the refresh, no `active` opinion in any layer; `compare_prims` leaves the session and root layers as they were |
| 4 | The client, both tools, `get_prim_properties`' warning; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 5 | Live: a file with a variant set, referenced; a switch by default leaves the root layer's export identical, `get_prim_bounds` and a capture show the new state, a clear brings the old back; `layer="edit_target"` writes it into the root layer; `compare_prims` leaves both layers as they were; the prim block's `variant_sets` names each layer; `set_prim_attribute(layer="session")` on a light leaves the root layer as it was | `tests/test_integration.py` on Isaac Sim 6.2 at 8212 |
| 6 | Docs, `test_project/scenarios.md` phase 20's expectations, `uv run tools/gate.py full`, the AI phase 20 run, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 4.
- Live: step 5, with the suites on a Z-up and a Y-up stage; whether Fabric Scene Delegate is on in this Isaac Sim is
  read and recorded, since the refresh differs.
- AI: phase 20 (`--phases 20`), whose 20.3 switches a variant: its answer now names the session layer.
- What neither shows: a payloaded area file on Nucleus, as the case has it (a local file stands in); Fabric Scene
  Delegate if it is off here.

## Docs

`docs/TOOLS.md` (`set_variant_selection`, `set_prim_attribute`, `compare_prims`, `get_prim_properties`' notes), the
`geometry` skill (switching for a check, clearing, the instance note) and the `scene` skill's line on
`set_prim_attribute`, `CHANGELOG.md` (Breaking: the switch's default; Added: `layer`, `variant_sets`; Fixed: the
refresh's and `compare_prims`' stray opinions), `test_project/scenarios.md` phase 20.

## Risks

- **A session selection outlives the check** and hides a later edit of the file's selection: accepted; the answer and
  the prim block name the session layer, and `variant_name=""` clears it; a new or opened stage starts with an empty
  session layer.
- **Fabric Scene Delegate's refresh in the session layer** may not rebuild what the edit target's did: the live run
  reads the switch's effect in a capture with the delegate's setting recorded; if it doesn't, the toggle stays in the
  session layer and adds frames.
- **An instance prim's own selection** builds a prototype per distinct selection: accepted; the answer says so, as the
  case measured.

## Plan review

None yet.
