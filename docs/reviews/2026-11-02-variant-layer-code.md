---
subject: "Switch variants in Kit's session layer by default, and give set_prim_attribute a layer, a change to the tool contract (#155)"
base: main (6df788e)
head: b071101
date: 2026-11-02
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split: the Kit-free core and the handlers; the server's tools, the contract, the docs and the live test. Minors only, so no second round"
verdict: clean
---

# Review: Switch variants in Kit's session layer

Read from the branch's diff against `main` at `6df788e` (31 files, about 2,450 lines with the plan) by two fresh
reviewers, read only, against the approved plan `docs/plans/2026-11-02-variant-layer.md` and the maintainer's
agreement on #155. One read `ovmcp/core/variants.py`, `layers.py`, `attribute.py`'s layer, the formatter's
`variant_sets`, `handlers/variants.py` and the handlers, settling each claim on usd-core 26.11 and against Isaac Sim's
own assembler; the other the server's tools, the contract, the docs, the skills and the live test. Four minors, no
blocker or major; all fixed in `2d47a9a` and `2f4a67c` (`bd5fa7f` and `1ffe36f` after the rebase onto `7d30015`). The
two reviewers numbered their findings apart: F for the first, G for the second.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_variant_handler.py`, `test_a_clear_of_nothing_writes_nothing_and_needs_no_refresh` | Its name promised no refresh, but nothing checked it: with the handler's `if switched.wrote:` guard gone the test still passed, while a clear of nothing would hide the prim for 40 updates and recompose a whole area | fixed in `2d47a9a`: the test asserts one update, the handler's own, where the refresh would add 40 |
| G1 | minor | `tools/usd_advanced.py` `set_variant_selection`, `docs/TOOLS.md`, the geometry skill | With `layer="edit_target"` the answer said `save_scene` writes the selection into the file, but where Kit's Layer window made a sublayer the edit target, `save_scene` (the root layer alone) never saves it, and nothing warned | fixed in `2d47a9a`: the answer says so only when the root layer took it, else names the layer and says `save_scene` writes the root alone; the description, `docs/TOOLS.md` and the skill say the same; a tool test |
| G2 | minor | `tools/usd_advanced.py` `set_variant_selection` | With an older extension a clear (`variant_name=""`), as the geometry skill asks, came back "variant_name is required", read as the caller's mistake, with no install advice | fixed in `2d47a9a`: that refusal gets the older-extension warning and how to install this server's; a tool test |
| G3 | minor | `tests/test_integration.py`, `TestVariantSwitchesKeepTheFiles` | The live test only asserted that the captures before and after a switch differed, which a stale frame likely passes too | fixed in `2f4a67c`: it reads the switched cube's width from each capture's segmentation and expects the open state about 3 times the closed one, and after a clear checks the prim block names the referenced file as the layer holding the selection |

**Refuted,** from the code and from measurements on usd-core 26.11:
- **Session sublayers ranked wrongly** (Isaac Sim's assembler adds one): the strength order reads the layer stack with
  its session layers, so they rank between the session layer and the root.
- **An instance proxy breaks the handler's reads before the refusal:** measured, the selection and `beneath()` read
  through a proxy, and `switch` then refuses it.
- **A blocked selection shown wrongly:** blocked in the session layer over `open` in the root, it composes to `""`,
  and the line reads `state: none [closed, open] (session)`, which is right.
- **`compare_prims`' second switch raising, a circular import, an edit target with a mapping, bare overs left by a
  clear at the edit target, the handler test leaking a module, the removed `BBoxCache(...).Clear()`:** each checked
  against the code; none is a defect.
- **An older server sending no `layer`:** the extension falls back to the edit target, and to `auto` for an attribute;
  the old fields are still answered.
- **The older-extension check, `save_scene` against an older extension, the `variant_sets` filter, the fixture, the
  live test's cleanup and units, scenario 20.7's "(root)", the CHANGELOG, the plugin skills, `AGENTS.md`'s cap and the
  writing rules:** each checked; none is a defect.

**The build's departures,** each judged sound: options listed sorted, as `GetVariantNames()` gives them and the old
answer did; a blocked selection put back through `BlockVariantSelection`; `edit_target` refused while any stronger
layer holds a selection; a clear that deletes only the key; Fabric Scene Delegate's setting read as `_utils.py` reads
settings; `written_to` and `session_selections` additive.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | `variants._rank` was a copy of `xform._rank`: take the one definition of the stage's strength order, which `_stronger_holder`, `beneath` and `write_blocker` must agree on | taken in `2d47a9a`: `xform.layer_ranks`, public, used by both |
| I2 | `get_scene_tree`'s description lists what its file holds without variant sets | taken in `2d47a9a`; `test_contract.py` pins it |
| I3 | The live test checks the third layer label, a referenced file's name, after the clear | taken in `2f4a67c` |

**Not covered:** the gate and CI, the PR's text, and two questions only Kit answers: whether a session-layer `active`
toggle refreshes Fabric Scene Delegate as the old root-layer toggle did, and Kit 107 (Isaac Sim 5.1). The live run
below answers the first; the second stays open.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, each suite run on a fresh Kit:

- **At `2f4a67c`,** with the review's fixes: both live suites 212 passed on a Z-up stage and 212 on a Y-up stage,
  `TestVariantSwitchesKeepTheFiles` among them. AI scenario phase 20 (run `20261102-201705`): every row PASS; 20.3's
  tester read the session-layer answer and `variant_sets = detail: low [high, low] (session)`.
- **After the rebase onto `7d30015`** (#159's Z-up `new_scene`, #156, #163): 215 passed on a Z-up stage and 215 on a
  Y-up stage.
- **The refresh, measured** in the viewport (`measure_refresh.py` in the session's scratch: a red 1 m cube switched to
  a blue 3 m cube in a referenced file, on a referenced root and an instance prim, Fabric Scene Delegate on): with
  the toggle, 0.33 to 0.39 s a call through the tool; through the core's switch alone, 0.03 s; both showed the blue
  cube and no red (about 212,800 blue pixels), and the red one back after a clear. So from Kit 110 the switch makes no
  toggle (`a6bada3`).
- **At `a6bada3`,** the toggle only before Kit 110: 215 passed on a Z-up stage; the measurement again, the tool now
  0.05 s a call with the blue cube and no red after it, the red back after its clear.

**What it couldn't show:** Kit 107 (Isaac Sim 5.1 fails in its own start-up on this machine), which keeps the
toggle; a bechtel-sized area's switch time.
