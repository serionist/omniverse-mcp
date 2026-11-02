---
subject: "List a prim's applied schemas and its relationships' targets in its prim block (#149)"
base: main (6a6982c)
head: 74ec145
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; one minor, so no second round"
verdict: clean
---

# Review: List a prim's applied schemas and its relationships' targets in its prim block

Read from the branch's diff against `main` at `6a6982c` (14 files, about 460 lines with the plan) by one fresh
reviewer, read only, with every lens, against the approved plan
`docs/plans/2026-11-02-prim-block-schemas-and-targets.md`. The code does what the plan says; one minor, fixed in
`a1b3c27`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `ovmcp/core/formatter.py`, `format_prim_block` | `api_schemas` went through `format_value`, which shortens a list longer than 8: an Isaac Sim joint or collider with ten schemas lost the one an agent looks for, against the plan's "joined by `, `" and the description's "lists the applied API schemas" | fixed: every name joined; `test_api_schemas_names_every_schema_however_many` fails with the old line |

**Refuted:**
- **The older-extension warning fires on a new extension:** `/scene/prim`'s text always asks for properties with no
  filter, so the line always follows `type`; the check reads the text before a long answer goes to a file; filters
  reach only the dump and recordings, which have no check.
- **The filter rule breaks a test that pins line order:** it is the same substring test the properties use;
  `test_07_03` and the property filter test hold.
- **The order of the schemas:** `GetAppliedSchemas()`'s, a type's built-ins first; the plan asks for no sorting, and
  tests pin both cases.
- **Instance proxies' targets:** mapped to real paths (the plan's F7).
- **Empty relationships out of the text, `[]` in the JSON:** the plan's Goal, with its reason.
- **The plugin skills:** `simulate` gains only `get_prim_properties`, a read-only tool; the frontmatter keeps its form.
- **A test that passes without its code:** each fails on the old code (the missing line, the import, `<unreadable>`,
  the warning, the contract rows); the live `test_08d` cleans up.
- **The tool contract:** untouched; the fixture holds no descriptions.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | The CHANGELOG says what the JSON gives: an `api_schemas` list, and `[]` for a relationship with no targets | taken |
| I2 | A test for the `<unreadable>` fallback when a relationship's targets can't be read | taken |
| I3 | No plan id in a test's comment that already gives its reason | taken |

**Not covered:** bridge-security and harness-integrity, which nothing here touches.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension:

- `test_08d_get_prim_properties_lists_applied_schemas_and_a_bindings_target` passed: `/World/IntTestSchemas:
  api_schemas = MaterialBindingAPI, PhysicsCollisionAPI`; a plain cube in Kit reads `api_schemas = []`, so Kit applies
  no schema of its own to a new prim.
- Both live suites: 205 passed on a Z-up stage, 205 on a Y-up stage.
- O4 (`--phases none --outcomes O4`, run `20261102-165516`): WARN as before, for one `execute_script`, the Collision
  API's apply, where three earlier runs made two (reading the schemas, then applying it). The judge read the floor's
  schemas with `get_prim_properties`. #150's `collision` parameter is O4's tool path.
