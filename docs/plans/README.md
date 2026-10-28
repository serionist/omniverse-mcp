# Plans

A non-trivial change gets a plan here before any code: a new tool or capability, a change to a one-way door
(`AGENTS.md`), to the bridge's security or its protocol, work on the server and the extension together, a dependency
that changes behaviour. A fix a reviewer can follow from the PR alone needs none; its PR says `Trivial: <why>`.

- One file per plan: `YYYY-MM-DD-<slug>.md`, dated the day it was started.
- Written with `start-work`, reviewed with `review-plan` until approved, approved by the maintainer, and committed as
  the first commit of its branch. Someone outside the maintainers puts it up as a draft PR for that approval
  (`start-work`).
- A plan records what was decided and why at the time. It changes while its branch is open, when the work departs from
  it, and not after the merge.
- A plan that spans several PRs, such as `2026-10-28-modernization.md`, is the exception: each step's PR updates it,
  and after its first merge only its progress log, the decisions taken on the way and their answers change.
- Fill every section. "None" is an answer; a blank is not.

## Template

```markdown
---
title: <a plain imperative sentence, which can become the PR title>
issue: "#<n>"
status: draft
approved_by:
approved_at:
---

# <title>

## Goal

What is true when this is done, and why it matters. In scope; out of scope.

## Design

How it works: the tools, routes, handlers and modules it adds or changes, on the server and in the extension. The
alternatives considered and why this one.

## Compatibility

The one-way doors it touches (`AGENTS.md`), what breaks for users (their `.mcp.json`, tool calls, the extension's
settings, the Kit apps supported) and how they move over. Or "none".

## Steps

Ordered, each one buildable and testable on its own, each naming the test that proves it.

## Tests

The new and changed tests, and the suites that prove it: unit (CI), the live suites (`test_integration.py`,
`test_scenarios.py`, by hand on a Kit app), and what neither can show.

## Docs

The docs that change with it: `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, the READMEs, `CHANGELOG.md`, `AGENTS.md`.

## Risks

What could go wrong, and whether each risk is resolved or accepted.

## Plan review

Written by `review-plan`: each round's reviewer, date and verdict, the findings with their status, the owner calls
with their answers, and the improvements with theirs.
```

`issue` is quoted: a bare `#` starts a YAML comment.
