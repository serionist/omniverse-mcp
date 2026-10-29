---
subject: "List the server in the official MCP registry, and put the install lines on each release (PR #65)"
base: main (885051f)
head: 9baa8e7
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; outside facts checked against the registry's source at v1.8.1 and on main)
verdict: clean
---

# Review: the MCP registry

Read from the diff and each touched file in full, with the registry's source (`modelcontextprotocol/registry`) for
each outside fact. Three minors, all fixed in `954de0e`; three improvements taken, one left.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `server.json`, PYTHONPATH | `"value": ""` never reaches the registry: its model has `value,omitempty`, and `mcp-publisher publish` re-serialises the file. A client installing from the registry would get PYTHONPATH as an input without a value, prompt for it or leave it unset, and pass Isaac Sim's Python path to uvx's Python | fixed: no value; the description says to set it empty |
| F2 | minor | `docs/releasing.md` (Once), `release.yml` (header) | Said the registry trusts `release.yml`'s token, "in the same way" as PyPI. It grants `io.github.<owner>/*` to an OIDC token from any workflow of any repository the owner has, with no environment | fixed: said so, and that only the `registry` job here asks for one |
| F3 | minor | `release.yml`, `verify` | The comment listing what `release.py check` holds to the tag left out `server.json` | fixed |

Refuted, each from the code:

- **CI's validate fails while PyPI's README lacks the marker:** `/v0/validate` runs only the schema and semantic
  rules; the ownership check is in the publish path.
- **v1.8.1 lacks `validate` or `login github-oidc`:** both are at the v1.8.1 tag. CI ran `validate` on this PR:
  `Verified OK`, then `server.json is valid`.
- **The namespace doesn't match the login:** the grant is `io.github.<repository owner>/*`, here `serionist`.
- **The login lasts long enough for five tries:** it lasts 5 minutes, so each try logs in again, as the job does.
- **A re-run republishes:** a version the registry has is refused (`already exists`), as `docs/releasing.md` says.
- **The marker check disagrees with the registry:** it is stricter than the registry's boundary rule, and the README
  passes both.
- **The registry job's token could publish to PyPI:** the trusted publisher names the `pypi` environment, which the
  job doesn't have.
- **`set -e` stops the retry loop:** a command in an `if` condition doesn't trigger it.
- **The new tests pass without the change:** each fails without it; the server's version case matches before the
  package's, and the messages differ.

Improvements:

- **The gate holds `server.json`'s name and package,** which AGENTS.md calls one-way doors: taken, `registry_problems`
  in `tools/gate.py`, with three test cases.
- **`ci.yml` says `validate` asks the live registry,** so an outage there fails the step: taken.
- **The sdist carries `server.json`,** which its tests read: taken.
- **`mcp-publisher` installed in one place** (a composite action), not in `ci.yml` and `release.yml` both: left:
  each copy's comment names the other, the registry's guide bumps the pin by hand, and a composite action would need
  its own Dependabot entry and checkout path.

Not covered: the tool-contract, Kit main-thread and bridge-security lenses, with no code in their scope. The
`registry` job runs only on a tag: 0.2.2's release is its first run.

## Checks

`uv run tools/gate.py full` passed on `9baa8e7` (967 tests) and on `954de0e` (970 tests, 95.41%). CI passed on
`9baa8e7`, with `mcp-publisher validate` in `Package (Linux)`.
