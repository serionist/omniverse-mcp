---
subject: "List / in get_mesh_stats' face count tree at max_depth 0 (#145)"
base: main (4576d87)
head: a39702f
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; one minor, so no second round"
verdict: clean
---

# Review: List / in get_mesh_stats' face count tree at max_depth 0

Read from the branch's diff against `main` at `4576d87` (4 files, 50 lines added) by one fresh reviewer, read only,
with every lens. There is no plan: the PR is `Trivial`, a one-line depth rule with its tests. The code and both tests
were found right; one minor in the CHANGELOG, fixed after `a39702f`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `CHANGELOG.md`, Unreleased, Fixed | The entry didn't say the fix is in the Kit extension, where every other extension fix does: a user who updates the server and keeps 0.4.1's extension still gets nothing for `/` at depth 0, with no hint to reinstall | fixed: the entry ends with the extension install line, as #141's does |

**Refuted,** each from the code:
- **Another spelling of the root, such as a trailing slash:** depth now comes from the canonical paths on both sides,
  `root.GetPath().pathElementCount` and `p.GetPath().pathElementCount`; a spelling `GetPrimAtPath` refuses fails at
  `if not root.IsValid()`, as before.
- **An instance proxy as the root:** `Usd.PrimRange(root, Usd.TraverseInstanceProxies())` yields its descendants under
  the same proxy path, so the subtraction holds.
- **`subtree_sums` and the depth rule disagree for `/`:** the upward walk stops at `path == root_sdf`, so `/` collects
  the whole sum, and the test checks `subtree_faces = 7` on `/`'s block.
- **The unit test passes without the fix:** the old rule gives `/` a depth of 1, so the `("/", 0, ["/"])` case lists
  nothing and fails; the other three cases guard the rest.
- **The live check parses the answer wrongly:** the totals block is joined by single newlines, so the first blank line
  splits it from the tree, and at depth 0 the answer is about 170 characters, inline.
- **"From `max_depth` 1 on it listed what it should" overstates:** the old rule put `/` and its children both at depth
  1 and every deeper prim at its right depth, so the listings match from 1 on.

**Improvements:** none.

**Not covered:** the gate and CI, the live suites and the PR's text, which the reviewer could not run or read; the PR
gives them.
