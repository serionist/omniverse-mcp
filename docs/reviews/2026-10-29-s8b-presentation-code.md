---
subject: "S8b, the presentation: the README's hero, the logo, the plugin icon and the social preview (PR #34)"
base: main (d2fdea5)
head: 9d85a32
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: S8b, the presentation

Read from the pack (the scope diff without the images), the touched files in full, each image, the gate's plugin check
and its tests, and Claude Code's plugin docs, with CI's results on the head (every leg passed). One minor, partly
refuted and fixed in the commit this record follows.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `plugin/.claude-plugin/icon.png`, `tools/gate.py` `PLUGIN_FILES`, the PR | The icon has no effect in Claude Code, which reads only `plugin.json` from `.claude-plugin/`; Anthropic's directory reads `plugin.json`'s `icon` field. The PR called it one of "the images GitHub and Claude Code show". | Partly refuted, and fixed: `claude plugin validate` itself looks for an icon "at .claude-plugin/icon.png or .svg ... or a similar path", for a listing in Anthropic's plugin directory, and reported ICON_MISSING until this PR; the path passes strict validation on Claude Code 2.1.285 (CI) and 2.1.312, where a new `icon` key might not on the pinned one. Kept there; the PR, AGENTS.md and `docs/images/README.md` now say it is for a directory listing, and that Claude Code shows no icon. |

Refuted, each from the code:

- **The binary breaks the gate, its tests or the hooks:** the pin and link scans read `.json` and `.md` only, the test
  tree copies bytes, the hooks match path names; CI's checks with Claude Code required passed.
- **The allowlist entry loosens a check:** nothing reads a file there to run it, and no key left in `plugin.json` or
  `.mcp.json` can point at it; an unlisted file still fails (`[a hooks file]`).
- **The captions claim what the tools don't do:** `capture_viewport` writes the boxes and the colour legend;
  `inspect_prim` takes `angles` with those corner names, `width`, `height` and `isolate`; the orbit's frames are in the
  angles' order, and the floor is gone from them, as `isolate` hides it.
- **The alt texts:** each matches its image; the logo's is empty, as the heading beside it names the project.
- **Light and dark:** the captures are opaque; the logo's faces read on both backgrounds.
- **The sdist and the wheel:** the sdist carries `docs/` and `plugin/`, so the README's images resolve in it; the wheel
  needs none.
- **Sizes and metadata:** 36, 4 and 43 KB captures, a 162 KB social preview (1280 by 640, under GitHub's 1 MB), a 39 KB
  icon; no metadata in the files.
- **The writing rules:** no dashes, curly quotes or banned words in the added lines; British spelling.

Not covered: tool-contract, kit-main-thread and bridge-security had nothing in scope.

Improvements, both taken:

- **The scene's tool calls named no prim paths,** so a literal re-run put the arm at `/World/Franka`, outside the
  workcell `isolate` keeps: `docs/images/README.md` gives each call with its path.
- **PyPI breaks the README's relative images and links,** noted only in the dated progress log: #36, for S9.

The PR's own gate line named `quick`; `uv run tools/gate.py full` passed on `9d85a32` and on the fixes.
