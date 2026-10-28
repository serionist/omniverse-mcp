---
subject: "D16, Dependabot merges its minor and patch updates (PR #14)"
base: main (1019117)
head: a292e48
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; a fresh refuter each for F1 and F3, the harness findings)
verdict: needs-fixes
---

# Review: D16, Dependabot merges its minor and patch updates

Read only: the reviewer and the refuters read the workflow, the docs it touches and the sources it relies on
(dependabot/fetch-metadata at `25dd0e3`, cli/cli's `pr merge`, GitHub's docs), and used gh GET calls on the ruleset,
the repo and PR #15. Fixed in `51a9d50` (F2, F3) and `8fb5f4d` (F1).

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `dependabot-auto-merge.yml`, `GH_TOKEN` | Auto-merge turned on with the workflow's `GITHUB_TOKEN` makes GitHub record the merge as `github-actions[bot]`, and "events triggered by the `GITHUB_TOKEN` will not create a new workflow run": CI and CodeQL never run on `main` after a Dependabot merge, and `ci.yml` and `codeql.yml` said "every push to main". The ruleset doesn't require up-to-date branches, so two groups that each passed CI against the same `main` can both merge into a tree nothing tested, and the break shows first on the maintainer's next PR. The reviewer rated it major; the refuter confirmed the mechanism (rmartz/envctl #137-#139: `merged_by: github-actions[bot]`, no push runs on their merge commits; the `closed` event is suppressed too) and rated it minor: the groups touch different files, the next PR's CI runs on its merge ref, and CodeQL runs weekly. A merge queue needs an organisation's repo; this one is a user's. | Fixed, with the maintainer's agreement on 2026-10-28 (REVIEW.md: a check that stops running): `ci.yml` also runs daily on `main` (`23 6 * * *`), so `main` is tested within a day of a Dependabot merge; the gap and the choice over a GitHub App token are in the headers of `ci.yml`, `codeql.yml` and `dependabot-auto-merge.yml`, and in D16. The concurrency group now keys on `pull_request`, as `codeql.yml`'s does, and the gate step's notice names a missing base. |
| F2 | minor | `AGENTS.md`, `pr-text.yml`, `dependabot.yml`, the plan | The docs said a Dependabot PR's squash message keeps "the bump line" and that "the maintainer merges it", while the workflow writes a line of its own; the `.github/` row in `AGENTS.md` left the workflow out. | Fixed: each says the message keeps the title and a line naming what moved, written by the workflow for a minor or patch and by the maintainer for a major; the row lists `dependabot-auto-merge.yml`; the plan's two bullets on the ruleset are one. |
| F3 | minor | `dependabot-auto-merge.yml`, `on` and `if` | Turning auto-merge off held an update only until Dependabot's next push (a conflict rebase, `@dependabot rebase`, the next Monday's run): the `synchronize` run turned it back on. The refuter confirmed it from Dependabot's options reference, and found the hold that already exists: "No one can merge the pull request until you mark the pull request as ready for review again." | Fixed: the job skips draft PRs, and runs on `ready_for_review` too, so marking a held PR ready turns auto-merge back on; fetch-metadata checks the PR's author and its first commit (`verified_commits.ts`), not the actor, so a maintainer's `ready_for_review` works. The header, `AGENTS.md` and D16 say how to hold one. |

Refuted by the reviewer, each from its source:

- **Something other than Dependabot reaching the write job:** nobody can register a `[bot]` login; a fork's PR is
  authored by the fork's owner and gets a read-only token whatever `permissions` asks; fetch-metadata also checks the
  first commit's author and its verified signature.
- **Shell injection:** the title, number and metadata reach the script through env, quoted; `run` has no `${{ }}`.
- **A grouped PR with a major in it:** `update-type` is the highest change in the PR, so the step is skipped.
- **`--subject` and `--body` with `--auto`:** gh sends them as `commitHeadline` and `commitBody` to
  `enablePullRequestAutoMerge`.
- **A merge before CI starts:** a required check that hasn't reported keeps the PR `BLOCKED`.
- **A skipped `PR text` blocking the merge:** PR #15 shows `PR text` skipped and the PR `CLEAN`.
- **`require_extra_approval_for_unattributed_changes` holding Dependabot's PRs:** PR #15 is `CLEAN` with no review
  decision.

Not covered: the tool-contract, Kit main thread, bridge security and compatibility lenses (no Python, Kit or bridge
code changed). Unsettled: whether `GITHUB_TOKEN` may merge a PR that changes `.github/workflows/`, as every `actions`
group PR does; GitHub's own example uses it. The first such auto-merge shows it.

Improvements:

- Name what moved in the squash line, from fetch-metadata's `updated-dependencies-json`, since a grouped PR's title
  only counts the updates: taken in `51a9d50`.
- Cite D16 in the PR as the maintainer's agreement to the job's write permissions: taken.
- PR #15, opened before the workflow, gets no event once it lands, so it won't merge itself: taken; it gets
  `@dependabot rebase` after the merge, which runs the job on it.

No round 2: F1's refuter rated it minor, and every finding is fixed; the main session checked the fixes.

## Checks

- **The squash line:** the step's `run` block, cut from the workflow and run under `bash -e` in Alpine with jq and a
  stub `gh` that prints its arguments: PR #15's three updates give "Bumps astral-sh/setup-uv 10.3.0 to 10.3.1,
  github/codeql-action/init 4.38.3 to 4.39.1, github/codeql-action/analyze 4.38.3 to 4.39.1, a minor update; the
  release notes are in #15."; a dependency without versions gives its name alone; `$(...)`, backticks and quotes in
  the title or a name stay text, and nothing ran. shellcheck is clean on it and on `ci.yml`'s gate step.
- **Gate:** `uv run tools/gate.py full` passed all 11 checks on `51a9d50` (pytest 388 passed, 124 skipped: the live
  suites, with no Kit running); the pre-push hook's quick lane passed on `51a9d50` and `8fb5f4d`.
- **Verdict at `8fb5f4d`:** clean.
