---
subject: "Give a shape's computed extent where it authors none, in get_prim_properties (#163)"
base: main (6df788e)
head: 3154600
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; one minor, so no second round"
verdict: clean
---

# Review: Give a shape's computed extent where it authors none

Read from the branch's diff against `main` at `6df788e` (7 files, about 240 lines) by one fresh reviewer, read only,
with every lens, against issue #163; no plan, a fix a reviewer can follow from the PR. One minor, fixed in `23b31ab`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `ovmcp/core/attribute.py`, `set_attribute` | `set_prim_attribute` on a resized cube's unauthored `extent` answered `was (-1, -1, -1), (1, 1, 1)`, the fallback the prim block no longer shows, so the tool's answer and the block disagreed | fixed: `before` read through `attribute_value`; `test_an_unauthored_extent_written_gives_the_computed_box_as_before` |

**Refuted:**
- **A Mesh with no points:** the plugin gives `None`, so there is no line, as before.
- **A Mesh with `points = []`:** USD's empty box, marked as computed, valid in the JSON as a string; rare, no error.
- **A PointInstancer without `protoIndices`:** `None`, so no line; at most a log line, not seen in a run.
- **Time-sampled sizes:** the block, the size line and `world_bbox` all read the default time and agree.
- **Cost on a big mesh or the scene dump:** only for an unauthored extent, and `world_bbox` already does that pass.
- **Meshes and sized lights gain a line:** correct and marked; the docs now say so.
- **A stale authored extent shown as written:** `get_prim_bounds` reads the same authored value; a test pins it.
- **No `extent_authored` flag in the JSON:** a deliberate departure from the issue, so the properties map keeps its
  shape.
- **`test_08e` in place of the issue's `test_23c`:** the same coverage, and it checks first that the extent is
  unauthored.
- **A non-shape prim with an `extent` attribute:** excluded by `is_a(prim, UsdGeom.Boundable)`, tested.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | One `plugin_extent` in `ovmcp/core/usd.py`, beside the other pxr calls the stubs type wrongly, for the formatter and `attribute.py` | taken: `23b31ab` |
| I2 | The CHANGELOG names `state.txt`; the docs say meshes and sized lights gain the computed line | taken: `23b31ab` |
| I3 | Drop `_json_properties`' unreachable third branch | taken: `23b31ab` |

**Not covered:** bridge-security and harness-integrity, which nothing here touches; the gate and CI (the reviewer ran
neither; gate full passed on `23b31ab`).

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension at `3154600`, each suite on a
fresh Kit: both live suites, 209 passed on a Z-up stage and 209 on a Y-up stage, with
`test_08e_get_prim_properties_gives_a_resized_cubes_computed_extent` among them: `create_prim`'s Cube authors no
extent, resized to 0.5 its prim block reads `extent = [(-0.25, -0.25, -0.25), (0.25, 0.25, 0.25)] (computed: none
authored)`, and `get_prim_bounds` measures 0.5 m a side. The review's fixes after it touch the core only and are
unit-tested.
