---
name: start-work
description: >-
  Use when someone wants to work on something in omniverse-mcp ("let's do #12", "pick up the capture issue", "add a
  tool for X", "fix Y"), before any code or docs change. Finds or creates the issue, reads the code and the APIs it
  touches, decides whether it needs a plan, writes the plan and reviews it with review-plan until it is approved,
  then starts the branch from origin/main with the plan as its first commit.
---

# Start a change

Every change reaches `main` through a PR (`AGENTS.md`, How a change lands). This skill gets a change to where code can
start: an issue, a plan when it needs one, the plan approved, and a branch. `finish-work` closes it.

## Steps

1. **Find the issue.**
   - A number: `gh issue view <n> --comments`, read in full. Closed? Ask before going on.
   - A sentence: look for an open one first, `gh issue list --search "<words>"`. None fits: write the body to
     `.local/issue-body.md` (what and why, no tool attribution) and run
     `gh issue create --title "<title>" --body-file .local/issue-body.md`. Every change gets an issue, a typo or comment fix too: its PR names it, and `PR text` checks that.
2. **Read before planning,** never from memory:
   - the code of every folder the change touches, and its tests;
   - both ends of what it changes: for a tool, the tool in `src/omniverse_mcp/tools/`, the client method in
     `client.py`, the route in `extension.py` and its handler in `ovmcp/bridge/handlers/`;
   - the docs that describe it (`docs/ARCHITECTURE.md`, `docs/TOOLS.md`, the READMEs) and `REVIEW.md`;
   - every Kit, Isaac Sim, USD or MCP SDK API it will call, through Context7 (`AGENTS.md`, Look up APIs before coding
     against them).
3. **Decide whether it needs a plan,** by the rule in `docs/plans/README.md`. Unsure: ask, and recommend one for
   anything that touches a one-way door, the bridge's security, or the server and the extension together.
4. **Write the plan** at `docs/plans/<today>-<slug>.md` from the template in `docs/plans/README.md`, with `issue` set.
   Fill every section; "none" is an answer, a blank is not. A one-way door it changes is named under Compatibility.
5. **Review it** with `review-plan` until its verdict is `approved`.
6. **Get it approved** by the maintainer: give the plan's path and the review's verdict, and ask. No code before the
   yes. Then set `status: approved`, `approved_by` (their GitHub login) and `approved_at` in the frontmatter.
   - Someone outside the maintainers: do steps 7 and 8 first, push the branch to your fork, and open a draft PR titled
     `Plan: <title>` that links the issue. The maintainer approves it there, and the code lands on the same branch.
7. **Start the branch** `<n>-<slug>` from `origin/main`, after `git fetch origin`. Ask where, as one question with a
   recommendation:
   - a new branch here, `git switch -c <n>-<slug> origin/main`, when the checkout is clean and nothing else runs in
     it;
   - a new worktree, `git worktree add .claude/worktrees/<n>-<slug> -b <n>-<slug> origin/main`, when other work is
     in flight; then move the session there.
   - `post-checkout:` lines name AI setup files that changed on the way: re-read the ones you already read, this
     skill among them.
8. **Commit the plan** as the branch's first commit: subject `Plan: <title>`, body `Refs #<n>`.
9. **Ask how to build:** directly in this session, or in forked agents for independent steps, each brief naming the
   plan's path, its step and the folders it may touch. This session stays the plan's anchor either way.

## Done means

- The issue exists.
- A change that needs a plan has one, reviewed, approved, and committed first on its branch.
- The branch exists from `origin/main`, and how to build is chosen.

## Never

- Write code before the plan is approved, or on `main`.
- Plan from memory of the code or of an API instead of reading it.
- Keep a plan only in the session, an issue comment or a PR body: the plan is a file.
- Post an issue or a comment with tool attribution in it.
