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
compose), and the root layer's `ExportToString()` is the same before and after. Clearing it there with
`ClearVariantSelection()` gives `closed` back but leaves `over "Area" {}` in the session layer, even inside
`Sdf.CleanupEnabler` (the fit's measurement); only the spec's own fields, written back as they were, leave the layer
exact. A blocked selection (`""`) is not the same as none. `Stage.Flatten()` bakes a session selection, but
`flatten_usd` and `export_prim_as_file` flatten the open stage without Kit's session layer (`layers.without_session`,
#118), so a check's switches never reach an export either.

Isaac Sim's own temporary session switch does the same bookkeeping: `isaacsim.robot_setup.assembler`'s
`robot_assembler.py:667` keeps the session spec's `variantSelections.get(set)` before it switches, and puts `None`
back with a clear and `""` with `BlockVariantSelection()` (`:707-711`).

### The extension

- **`ovmcp/core/variants.py`** (Kit-free):
  - `variant_sets(prim)`: for each set in order, its selection, its options in order, and the layer holding the
    selection (the strongest spec in `prim.GetPrimStack()` whose `variantSelections` holds it: `session`, `root` or
    the file's name), or none;
  - `variant_refusal(prim, set, name, layer)`: an instance proxy (a prim inside an instance) is refused, naming the
    instance prim to switch instead; an unknown set or option is refused listing those there, and an unknown set on a
    prim with an unloaded payload says so; `layer="edit_target"` where the session layer holds a selection for that
    set is refused, since it wouldn't show, naming the fix (`variant_name=""` with `layer="session"` first);
  - `Snapshot` (fit I1), built like `attribute._Undo`: for each prim and set a switch touches, whether the layer had
    the prim's spec, the selection in one of three states (absent, blocked `""`, a name), and the spec's `active`
    field; `restore()` writes each back through the Sdf spec, and removes a spec only when the switch created it;
  - `switch(stage, {prim: {set: name}}, layer) -> Snapshot` (fit I2): refuses every switch before it writes any,
    writes them all in one `Sdf.ChangeBlock` (`""` clears that layer's selection), and returns the snapshot of what
    it wrote over, with a note for each prim that is an instance (its own selection gives it a prototype of its own
    while it differs from its siblings'). One call serves one switch (the tool), two (`compare_prims`) or a shot's
    whole set of changes (#157, which merges the last shot's revert with the next shot's apply).
- **`ovmcp/core/layers.py`** gains `layer_named(stage, "session" | "edit_target")`, which `variants.py` and
  `attribute.py` share.
- **`handlers/variants.py`,** `refresh(stage, prims)` (fit I2): the Fabric refresh for a whole switch at once, one
  `SetActive(False)` over the top-most switched prims in the session layer, its updates, then their `active` fields put
  back from the snapshot in a `finally`, so a cancel or an error between the two never leaves a prim hidden; it runs
  only when Fabric Scene Delegate is on and step 5 finds the toggle still needed (fit I3).
- **`handle_set_variant_selection`:** reads `layer` (absent: `edit_target`, today's behaviour, so an older server
  keeps it), calls `switch`, then `refresh`. The answer adds `layer`, `files_select` (the selection beneath the written
  layer) and the instance note.
- **`handle_compare_prims`:** checks with `variant_refusal` before it switches, so a prim inside an instance gets the
  refusal, not `Tf.ErrorException` (fit I6); both switches through `switch` in the session layer, and the first's
  snapshot restored in a `finally`.
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
- `get_scene_tree(property_filter=["variant_sets"])` lists every switch of a scene in one call: the formatter's filter
  matches `variant_sets` as it matches `api_schemas` (fit I5).
- `save_scene`'s answer names the variant selections the session layer holds and the save leaves out of the file
  (fit I4), so an agent that switched expecting to keep it learns at the save, not many calls back.
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
| 1 | `ovmcp/core/variants.py` and `layers.layer_named`, tests first | `tests/test_variants.py` with usd-core: a referenced file's set switched in the session layer, the root layer's export unchanged; a snapshot restored leaves the session layer's export as before, for each of absent, blocked and named selections, a spec that existed and one the switch made, and an `active` field set; a batch refused whole when one switch is wrong; `edit_target` refused under a session selection; an instance proxy refused; an unloaded payload named; the instance note; `variant_sets` with each layer named |
| 2 | The prim block's `variant_sets` line, the filter matching it, and the JSON | `tests/test_formatter.py`, `tests/test_scene_handler.py` |
| 3 | `handlers/variants.py`'s `refresh`, `handle_set_variant_selection`, `handle_compare_prims`, `handle_set_attribute`'s `layer`, `save_scene`'s line | handler tests with the Kit fakes: after a switch with the refresh, no `active` opinion in any layer, and none after an error mid-refresh; `compare_prims` leaves the session and root layers as they were, and refuses an instance proxy; `save_scene` names the session selections |
| 4 | The client, both tools, `get_prim_properties`' warning; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 5 | Live: a file with a variant set, referenced; a switch by default leaves the root layer's export identical, `get_prim_bounds` and a capture show the new state, a clear brings the old back; `layer="edit_target"` writes it into the root layer; `compare_prims` leaves both layers as they were; the prim block's `variant_sets` names each layer; `set_prim_attribute(layer="session")` on a light leaves the root layer as it was. With Fabric Scene Delegate on (Isaac Sim 6.2's default, `isaacsim.exp.base.kit:203`), a switch captured with the refresh and without it, on a referenced root and on an instance prim, each timed: if nothing renders stale without it, the toggle goes; if it stays, whether a capture's own 20 frames cover its updates (fit I3) | `tests/test_integration.py` on Isaac Sim 6.2 at 8212; the measurements in the PR |
| 6 | Docs, `test_project/scenarios.md` phase 20's expectations, `uv run tools/gate.py full`, the AI phase 20 run, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 4.
- Live: step 5, with the suites on a Z-up and a Y-up stage; Fabric Scene Delegate's setting read and recorded.
- AI: phase 20 (`--phases 20`), whose 20.3 switches a variant: its answer now names the session layer.
- What neither shows: a payloaded area file on Nucleus, as the case has it (a local file stands in); a Kit app with
  Fabric Scene Delegate off, such as USD Composer's default.

## Docs

`docs/TOOLS.md` (`set_variant_selection`, `set_prim_attribute`, `compare_prims`, `save_scene`, `get_prim_properties`'
notes, `get_scene_tree` with `property_filter=["variant_sets"]` to list a scene's switches), the `geometry` skill
(finding the switches, switching for a check, clearing, the instance note) and the `scene` skill's line on
`set_prim_attribute`, `CHANGELOG.md` (Breaking: the switch's default; Added: `layer`, `variant_sets`; Fixed: the
refresh's and `compare_prims`' stray opinions), `test_project/scenarios.md` phase 20.

## Risks

- **A session selection outlives the check** and hides a later edit of the file's selection: accepted; the answer and
  the prim block name the session layer, and `variant_name=""` clears it; a new or opened stage starts with an empty
  session layer.
- **Fabric Scene Delegate's refresh:** the toggle works around old FSD bugs (OMPE-54434, OMPE-70769, OMPE-71336, from a
  Kit release not known), which neither Kit's `SelectVariantPrimCommand` nor Isaac Sim's assembler works around, and
  on an area root it recomposes the whole area each time; step 5 measures whether it is still needed and what it
  costs, since #157's sweep time depends on it. Resolved by the measurement, either way.
- **An instance prim's own selection** builds a prototype per distinct selection: accepted; the answer says so, as the
  case measured.

## Plan review

### Fit

The plan at `743e02e`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, with this repo's `fit-plan`
from `main`, measuring on usd-core 26.11. The change's own question: does the switch, its clear, its Fabric refresh and
its exact restore give #157 a primitive to call per shot, at a cost fit for hundreds of switches? Answers by the author,
2026-11-02, on the maintainer's delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | A `Snapshot` built like `attribute._Undo` that restores the session layer exactly (the spec, three selection states, `active`), as Isaac Sim's assembler does, called in a `finally` by `compare_prims` and #157 | taken: The extension, step 1 |
| I2 | One `switch(stage, {prim: {set: name}}, layer)` that refuses all before writing any, writes in one `Sdf.ChangeBlock`, and one refresh over the switched prims with `active` put back in a `finally`, so #157 merges a shot's revert and apply and a cancel never leaves a prim hidden | taken: The extension, step 3 |
| I3 | Isaac Sim 6.2 turns Fabric Scene Delegate on by default: measure live whether the toggle is still needed and what it costs, since Kit's own variant command and Isaac Sim's assembler don't toggle | taken: step 5, Risks |
| I4 | `save_scene`'s answer names the session layer's selections it leaves out | taken: The server, step 3 |
| I5 | `get_scene_tree(property_filter=["variant_sets"])` lists every switch, the filter matching it as it matches `api_schemas` | taken: The server, Docs |
| I6 | `compare_prims` checks with `variant_refusal` first, so a prim inside an instance gets a refusal, not `Tf.ErrorException` | taken |

Noticed on the way, for Round 1: `ClearVariantSelection()` leaves an empty over even under `Sdf.CleanupEnabler` (the
Measured section, now corrected); #155 has no agreement comment yet (Compatibility); neither put-back was in a
`finally` (The extension; I1 and I2 answer it).
