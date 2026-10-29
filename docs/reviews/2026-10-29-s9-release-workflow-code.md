---
subject: "S9, the release workflow, the release runbook and PyPI's README (PR #37, #36)"
base: main (017da47)
head: e3bbaf5
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: S9, the release machinery

Read from the pack (the scope diff), every touched file in full, the repo's `pypi` environment and its "release tags"
ruleset, the pinned actions at their SHAs, setup-uv's, upload-artifact's and download-artifact's defaults, and a real
build of the branch (twine, check-wheel-contents, `release.py`, `git archive`), with CI's results on the head (all 14
checks passed). Two minors; fixed in the commit this record follows, with three improvements taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `pyproject.toml`'s substitutions; `tools/release.py`, `_RELATIVE` | The check looked for exactly the forms the substitutions rewrite, so a README edit could break PyPI's page with CI green: a Markdown image became a github.com page (served as HTML, a broken image), a link with a title or a reference definition stayed relative unflagged, and a `mailto:` link was rewritten into a github.com path. Today's README is fine: its 16 rewritten lines are all absolute. | Fixed: an image substitution to raw URLs before the link one; `mailto:` left alone; `_RELATIVE` also flags a link with a title, a reference definition, and an image or `img` on a github.com page. `test_a_wheel_that_is_wrong_says_how` gains a case for each; `mailto:` passes. |
| F2 | minor | `docs/releasing.md`, When it fails | Every failure before the approval went to a new patch version, a CI flake included, while `release.yml` itself says to re-run: 0.2.0 would never publish, and the plugin on `main`, pinned to it, couldn't start until 0.2.1 (R10). And "a tag can't be moved" is this repo's rule, not a fact: the ruleset lets admins. | Fixed: a failure by chance is re-run (CI's failed jobs, then the release's); a failure for a reason gets the next patch version; the tag rule is stated as the repo's. |

Refuted, each from the repo, GitHub or a real run:

- **The trusted publisher's claims:** the file is `.github/workflows/release.yml`, the job's environment `pypi`,
  which exists with the maintainer as reviewer (self-review allowed, so the person who tags can approve) and
  deploys from `v*` tags only.
- **`gh run list`'s filters:** the job's exact query on `main`'s head found its push run; a merge the maintainer
  makes starts one (only the workflow token's, as in D16, don't, and a release PR is never merged that way).
- **`release.py` importing `gate` under `uv run --no-project`:** `sys.path[0]` is `tools/`; CI's package job runs it.
- **`git archive HEAD:extension/ovmcp.bridge`:** the zip holds the wheel's 30 extension files.
- **The sparse checkout for the notes:** `gate.py` reads no file at import; `notes` works on those three files.
- **`origin/main` in `verify`:** checkout with full history fetches every branch.
- **`release.py` against the real changelog:** with `## 0.2.0 (date)` under `## Unreleased`, the section and the check
  come out right; the changelog has no fences or stray headings.
- **The offline wheel test:** the editable build caches every build requirement first; it passed on all seven legs.
- **The W004 ignore loosens a check:** check-wheel-contents never ran before; W004 is its only warning, every hit under
  `_extension/ovmcp.bridge/`, and it has no per-path ignore.
- **Cache poisoning:** setup-uv's default caches nothing on a tag push.
- **`dist/.gitignore` uploaded:** upload-artifact leaves hidden files out by default.
- **A contributor's PR or a branch publishing:** only a `v*` tag starts the workflow, the ruleset lets only admins
  make one, the environment deploys from tags only and needs the reviewer, a fork gets no id-token, and the tag reaches
  scripts only as a quoted `$GITHUB_REF_NAME`.
- **The pins:** all five SHAs are the versions their comments name, and the publish action's container exists.
- **Permissions:** `contents: read` above, raised per job with a reason; no checkout keeps credentials.
- **A version the release PR could miss:** everything else naming 0.1.0 is tests' invented data or a form's example.
- **The pre-push hook and a tag:** a tag on `main` sends an empty range.
- **`hatch-fancy-pypi-readme` unpinned:** `uv.lock` holds no build requirement; it is pinned exactly in
  `[build-system]`; MIT, no advisories.

Not covered: tool-contract, kit-main-thread and bridge-security had nothing in scope; `release.yml` runs first on the
release PR's tag.

Improvements, all taken:

- **Check a release PR as its tag will be:** `release.py pr`, in CI's package job, runs the tag's check when
  `CHANGELOG.md` has a section for `pyproject.toml`'s version, and passes on any other change;
  `test_a_release_pr_is_checked_as_its_tag_will_be`.
- **Release notes with each paragraph on one line,** since GitHub breaks a release body at every newline:
  `release.py notes` unwraps; `test_the_notes_put_each_paragraph_on_one_line`.
- **The README's "before 0.2.0" lines would be frozen into PyPI's description:** for the release PR, and the runbook
  now says to check for such lines.

## Checks

`uv run tools/gate.py full` passed on `e3bbaf5` (684 tests, 93.34%) and on the fixes (690 tests, 93.30%); actionlint
finds nothing in either workflow; a fresh build passes `release.py wheel`, its README rewritten on 16 lines.
