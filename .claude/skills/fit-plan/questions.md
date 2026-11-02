# Fit questions

`fit-plan` asks these of a written plan, and the plan's author asks them too, while writing it (`start-work`). Each
answer is an improvement that clears `REVIEW.md`'s bar (Improvements), or nothing: "none" is a good answer. Not here:
defects in the plan as written, which are `review-plan`'s findings.

| Question | Ask | For example, from this repo's plans |
|---|---|---|
| Fit | Does it fit the issue, `AGENTS.md` (the rules, the one-way doors), `REVIEW.md`, the design as it stands (`README.md`, `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `plugin/README.md`, the tool contract in `tests/fixtures/mcp-tools.json`) and the maintainer's calls (the issue's comments, the plans it or the plan names)? Who uses it, and does it serve them: people who drive a Kit app through an AI client, with the plugin or without (`docs/AI_GUIDE.md`); the agents that read the tools' descriptions, their answers and the plugin's skills; the repo's contributors, people and agents? | #160: copy simready-forge's port word for word, so the three repos' text doesn't drift |
| Mechanical over manual | A step someone must remember, a rule only a review keeps: could the server, the bridge, the gate, a test, a hook or `tools/` do it? A manual step the plan keeps says why none can | #77: a contract test that no tool description, `INSTRUCTIONS` or plugin skill names a removed tool |
| Reuse | Does something the server, the extension's `ovmcp/core`, a tool, the plugin, `tools/` or the skills already have do this, or most of it? | #141: a recording borrows the kept capture feed at its size, so it sets up no new RTX view |
| Cut or simplify | What can go; what belongs in another issue; a rare corner it designs for; a new tool where a parameter on an old one would do, or the reverse | #146: `at most <n>` calls had no outcome using it, so `Calls:` is `any` or `no execute_script` |
| Prior art | How Kit and Isaac Sim do it themselves (their own APIs and extensions), OpenUSD practice, PhysX, the MCP specification and Python SDK (tool shape, annotations, long work), and Claude Code's skills and plugins; where the plan differs, and why | #160: why not Claude Code's `context: fork`, which the gate and Codex don't take |
| The change's own | The concern its issue, an issue it must stay open to, or the maintainer names, asked as a question of its own | #160: where it departs from simready-forge's port, and whether this repo needs each departure |

## Prior art

Looked up, never recalled (`AGENTS.md`, Look up APIs before coding against them):

- Context7, where it is on (`.mcp.json`, turned on by `.claude/settings.local.json.example`);
- the MCP SDK and `pxr` (usd-core) as installed under `.venv`, the versions `uv.lock` pins;
- the repo: the bridge's `ovmcp/core` and handlers, for the Kit calls it already makes; the server's tools, the
  plugin's skills, `tools/`;
- Kit's and Isaac Sim's extension sources, where a Kit app is installed.

The fit says what it could not look up.

## The change's own question

The session that starts the fit adds one when the issue, an issue the change must stay open to, or the maintainer
names a concern of its own, and the brief carries it. On #160 it was where the port departs from
simready-forge's, and it produced an improvement of its own. Without one, the five stand alone.

## What an improvement holds

As `review-plan`'s `lenses.md` says what a finding holds:

- an id, `I1`, `I2`, ..., and the question it answers;
- the plan section;
- what to change;
- why it is better, and who notices;
- the line it rests on, quoted with its `file:line`.

"None" for a question with nothing to offer. At the end, one line for the defects noticed on the way, when there are
any, each with its plan section: they go to `review-plan`'s Round 1, never fixed by the fit.
