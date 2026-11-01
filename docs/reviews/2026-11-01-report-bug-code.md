---
subject: "Have the agent offer a bug report when a tool misbehaves (#109)"
base: main (3b2b0cf)
head: ab421c7
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only"
verdict: needs-fixes
---

# Review: Have the agent offer a bug report when a tool misbehaves

Read from the branch's diff against `main`: the server's instructions, the new plugin skill `report-bug`, the guide,
the READMEs, CHANGELOG, the tester's rules and the tests. The reviewer also read the bug form, `SECURITY.md`, the
tool contract and `tools/scenarios.py`, and ran one read-only `gh issue list`. Two minors, no second round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `plugin/skills/report-bug/SKILL.md` step 1, `src/omniverse_mcp/server.py` INSTRUCTIONS, `docs/AI_GUIDE.md` Context | Only the skill kept a security hole out of an issue, and only a way past the token. In Cursor, without the plugin, an agent that sees `export_prim_as_file` write outside its path, or a secret in Kit's log, follows the instructions; the user picks a, and the hole is posted publicly. `SECURITY.md` counts both, and `gh --body-file` never shows the bug form's note pointing at private reports | fixed in `4d9f7e2`: step 1 points at `SECURITY.md`'s What counts by its full URL; the instructions and the guide send a security hole to the private advisory, never to an issue. `test_a_security_hole_goes_to_a_private_advisory_never_an_issue` |
| F2 | minor | `plugin/skills/report-bug/SKILL.md` step 3 | "The client: Claude Code, with the version `claude --version` prints." The guide has other clients copy the skills, Codex into `.agents/skills/`, so a Codex agent fills the client field from `claude --version`: an error, or the wrong client | fixed in `4d9f7e2`: "The client and its version (Claude Code: `claude --version`)." Prose only; no test reads it |

Refuted, each from the code:
- **`allowed-tools` not read-only:** `get_sim_state` and `get_logs` have `readOnlyHint` true in the tool contract, and
  the `>-` block of `mcp__plugin_omniverse-mcp_omniverse__` names matches the other skills.
- **Fields that don't match the form:** all 9 labels match, in order, and the body is written as GitHub renders a
  filed form: `### Field`, a blank line, the value, `_No response_`, a `text` fence for `render: text`, `- [X]`.
- **`blank_issues_enabled: false` blocks `gh issue create --body-file`:** it governs only the web chooser; the API and
  `gh` take a body. Leaving out `--label` is right: the form's `labels: [bug]` isn't applied, and the maintainer adds
  it.
- **`gh` flags:** `--repo`, `--state` and `--search` together returned #70 on a live read; `view`, `comment`,
  `create --body-file` and `release list --limit 1` are valid, and every command has `--repo`.
- **The three choices against #109:** the skill asks first, gathers nothing before a or b, posts only on a yes to the
  text shown (shown again after any change), and c means no second ask; the instructions say the same in short.
- **The instructions in the tool contract:** `golden.py` records only tool schemas, annotations and resources.
- **Writing rules and length:** the instructions grew from 919 to 1,564 characters; no banned words or em dashes.
- **Testers could file issues:** they run with `--tools Read,Grep,Glob,Skill`, no Bash or Write. The tester's Never
  line is right and needed in `-p` mode, and the `test_scenario_runs.py` change follows from `skill_names()`.
- **The tests:** `_form_labels` takes only elements with an `id`; `.gitattributes` keeps the form LF; and
  `test_a_field_renamed_on_the_form_is_found` shows the comparison fails on a rename.
- **The README links the skill, not the guide:** the skill is plain Markdown any client reads, and the guide links it
  too.

Improvements:
- **I1, `tools/scenarios.py` leaves `report-bug` out of the testers' skills:** left. The maintainer keeps the prose
  rule: testers have no Bash or Write, so they can't post.
- **I2, step 8 says where the text goes,** a new issue or a comment on `#<n>`, and that a comment holds only what is
  new, not the whole form: taken in `4d9f7e2`.
- **I3, the test's regex widened to `gh (issue|release) \w+`,** so `gh release list` is held to `--repo` too: taken in
  `4d9f7e2`, in `test_the_instructions_the_skill_and_the_guide_send_reports_to_this_repository`.
- **I4, step 6 takes out host names and IP addresses too:** with Kit on another machine, the error text names it.
  Taken in `4d9f7e2`.
- **I5, the title's quoting:** in Git Bash and PowerShell a double-quoted title runs backticks and `$`. Taken in
  `4d9f7e2`: the title holds no backtick, `$` or `"`.
- **I6, `gh issue create` refused** (a fine-grained token's 403 on a repository the user doesn't own): taken in
  `4d9f7e2`: the skill says why, and goes on as b.

Outside this change, moved to #105 (R8): `get_sim_state` reports no Kit app or version, so the skill asks the user;
#105 switches it to read them from `get_sim_state`.

Not covered: the Kit main thread, the bridge's security, the tool contract and compatibility (no extension, route,
token or tool code changed). The reviewer didn't run the gate. No plan in `docs/plans/`: the design is #109's
description, which the maintainer chose on 2026-11-01.

## Checks

- `uv run tools/gate.py full` passed on `ab421c7` (1685 tests) and on `4d9f7e2` (1686 tests), the plugin validated by
  Claude Code both times.
- No live run: no tool, route or extension code changed.
