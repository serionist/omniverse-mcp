# Code review lenses

`review-code` applies every lens below, to a change or to a path. `REVIEW.md` holds the severities, the questions and
the harness rule; the lenses say where to look. A lens whose "Applies when" names nothing in the scope returns no
findings at once, and an empty list is a good result.

**Not a bug hunt.** Report a problem only when it is real: it can be reproduced and causes an actual failure for a
user, their Kit app or the next change.

- It has: a title; a severity (blocker, major, minor; most are minor); the file and the function or line.
- **The scenario:** the input or state, what happens, why it matters. No scenario, no finding.
- What it is judged against: a rule in `AGENTS.md` or `REVIEW.md`, the plan, a library's documented behaviour, or
  "none".
- The evidence, and the fix. Style is ruff's, taste is the author's.

**Improvements too,** under any lens: a reuse it missed, a simpler approach, a clearer name, a step someone must
remember that a check could do. What, where, why it's better; no severity, never counted.

## plan-and-intent

Applies when: the change has a plan in `docs/plans/` or an issue.

Does it do what the plan and the issue say? A planned step missing, or behaviour nobody asked for that a user will
meet, is a finding; a small departure the PR explains is not.

## implementation

Real bugs a user would hit. The plan's lenses below are where this repo breaks most; this one catches the rest.

- Wrong logic; an edge case real input reaches (an empty stage, a missing prim, a path with spaces or non-ASCII, a
  very large scene or image).
- An exception swallowed or turned into text, so a failure looks like success to the agent calling the tool.
- A socket, file or Kit subscription not closed on an error path; a timeout missing on a wait or a request.
- Blocking work on an asyncio event loop: the server's, or Kit's (below).

## tool-contract

Applies when: the scope touches `src/omniverse_mcp/tools/`, `server.py`, `client.py`, or a handler a tool calls.

- Does a tool's name, parameters, defaults, annotations or result change? Named in the PR, with its heading in
  `docs/TOOLS.md` and a CHANGELOG line (under Breaking when it breaks callers)? A silent change is a one-way door
  broken: a blocker.
- Does a request or response change shape on one side only? The server and the extension move together, and the
  protocol number changes with the shape.
- Does a failure reach the agent as an error it can act on, saying what to do?

## kit-main-thread

Applies when: the scope touches `extension/ovmcp.bridge/ovmcp/bridge/` or anything that calls USD, Kit or Isaac Sim.

- USD and Kit called off Kit's main thread (`run_in_executor`, a thread) crash Kit: a blocker.
- A handler awaited inside the connection task breaks Kit's widgets: each runs as its own task.
- A long operation that never yields freezes Kit's UI; one that waits for frames needs a timeout.
- `AGENTS.md`, Traps, lists what broke before; a change that undoes a guard there is a finding.

## bridge-security

Applies when: the scope touches `ovmcp/core/http.py`, `ovmcp/core/token.py`, `client.py`, `bridge_token.py`, the
extension's settings, or adds a route.

Name the concrete attack and what it gains.

- A route reachable without the token, or a token compared other than in constant time.
- An `Origin` accepted, or on a loopback bind a foreign `Host`: a web page reaches `/execute`.
- A token in a log, an error, a doc, a test fixture that looks real, or a file other users can read.
- A refused request's body read and parsed anyway; a connection without the token holding a handler's slot.

A way past the checks is a blocker.

## tests

- Would each new test fail without the change? Is a fix pinned by a test that reproduced the bug?
- Do tests use invented data and tokens, run without Kit, a GPU or the network, and clean up what they create?
- The live suites (`test_integration.py`, `test_scenarios.py`) never run in CI. For a change to the extension, the
  client or a tool: does the PR say whether they ran, on which Kit app and version, and what they can't cover (another
  Kit, Isaac Sim 5.x when they ran on 6.x, a GPU, a stage with no lights)? Is a failure compared with `main`'s run on
  the same Kit before it is called the change's?
- Kit behaviour a unit test mocks (a Kit command's return value, a viewport's resolution): is the mock what Kit
  does, per Context7 or a live run?

A missing test for new behaviour is major; a missing edge-case test is minor.

## docs-freshness

- Did the docs that describe the scope move with it: `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `docs/AI_GUIDE.md`,
  the READMEs, `CHANGELOG.md` when users notice, `AGENTS.md` for a changed path, command or rule?
- Does anything cite a path, a command, a flag or a setting that no longer exists?
- A comment or doc outside `docs/plans/` and `docs/reviews/` that cites a plan or review id instead of the reason?

## simplicity

A second implementation of one thing, a layer with one caller, an option nobody asked for, dead code: an improvement,
written as what it drops ("X could become Y, which drops Z"). A finding only when it causes a real failure, with its
scenario (the two copies already disagree).

## compatibility

Applies when: the scope touches paths, files, processes, encodings, the extension, or the Python it needs.

- Kit and Isaac Sim: every Kit the repo supports (Kit 107+, Isaac Sim 5.x and up). An API from one release only, or
  an extension a headless app lacks, needs a fallback or a clear error.
- Windows and Linux: path separators, `\r\n`, text read and written as UTF-8 explicitly, file modes (no effect on
  Windows), a tool assumed on PATH.
- Python 3.11 for the server and the extension's core.

## harness-integrity

Applies when: the scope touches a harness file (`REVIEW.md`, The harness).

Anything that loosens a check: a gate step dropped or made a warning, a lint rule or a test skipped, an ignore or a
baseline entry added, a question or a lens removed, attribution let through, a permission widened. A blocker unless
the maintainer agrees in the PR.

## Refuting

- Every finding gets a refutation attempt before it is reported.
- Rule it not real when:
  - its scenario can't happen (read further: it is often handled elsewhere);
  - it causes no actual failure;
  - it is taste;
  - it rests on a misread of the code or the library.
- Settle it with evidence: quote the line that proves or kills it. On your own branch a refuter may reproduce it with
  a test or a short script, never the live suites or someone's running Kit.
- Someone else's PR is never run here.
- A refutation you couldn't check leaves it real. A refuted one stays in the record, with its reason.
