# Plan review lenses

`review-plan` applies every lens below. `REVIEW.md` holds the severities, the questions and the harness rule; the
lenses say where to look in a plan. A lens that names nothing in the plan returns no findings at once, and an empty
list is a good result.

**Not a hunt.** A finding on a plan is a defect that would really hurt if the plan were followed as written: a step
that can't be built, a way past the bridge's checks, a one-way door changed silently, a test that can't prove what it
claims.

- It has: a title; a severity (blocker, major, minor; most are minor); the plan section.
- **The scenario:** what goes wrong when the plan is followed as written. No scenario, no finding.
- What it is judged against: a rule in `AGENTS.md` or `REVIEW.md`, the code, a library's documented behaviour.
- The evidence (quote the plan), and the proposed plan edit.

**Improvements too,** under any lens: what would make the plan, or the code it leads to, simpler, safer or cheaper
to change. No severity, never counted. Mechanical over manual: a step someone must remember, which a check could do.

## plan-and-intent

- Does the plan do what its issue asks, and nothing nobody asked for?
- Does it contradict a rule in `AGENTS.md` or `REVIEW.md`, or change a one-way door without naming it under
  Compatibility? Named openly, it is a choice for the maintainer; silent, it is a blocker.

## omissions

Read `REVIEW.md` and the code the plan changes, and list what they require that the plan leaves out and that would
really bite: the other end of a route (server, client, handler), a doc (`docs/TOOLS.md`, `docs/ARCHITECTURE.md`), a
CHANGELOG line users need, how existing users move over.

## bridge-security

Applies when: the plan touches the bridge's HTTP layer, the token, the client's connection, or adds a route.

Name the concrete attack and what it gains. Does every route still need the token? Are an `Origin` and, on loopback,
a foreign `Host` still refused? Does a token stay out of logs, errors and docs? Does the design fail closed? A way
for a web page or another local process to reach `/execute` is a blocker.

## kit-main-thread

Applies when: the plan touches handlers, the extension's lifecycle, or anything that calls USD or Kit.

Does USD and Kit work stay on Kit's main thread, never in `run_in_executor`? Does each handler run as its own task?
Does a long operation (a capture, a recording, physics steps) yield to Kit instead of freezing its UI? `AGENTS.md`,
Traps, lists what broke before.

## tool-contract

Applies when: the plan adds, removes or changes a tool, its parameters, its annotations or what it returns.

Is the change named, with its `docs/TOOLS.md` heading and a CHANGELOG line under Breaking when it breaks callers? Do
the server and the extension move together, with the protocol number changed when a request or response changes
shape?

## compatibility

Does it work on every Kit the repo supports (Kit 107+, Isaac Sim 5.x and up), on Windows and Linux, and on Python
3.11 for the server? An API taken from one Isaac Sim release without checking the others (Context7) is the usual way
this breaks.

## sequencing-and-tests

- Can each step be built, tested and committed on its own, in that order?
- Does each step name the test that proves it, one that fails without the change?
- Can it run in CI (no Kit, no GPU, no network)? What only Kit can show goes to the live suites: does the plan say
  which, and what they still cannot show?

## simplicity

A seam with no caller, a setting nobody asked for, a second way of doing one thing, scope beyond the issue: an
improvement, written as what it drops and who would notice. A finding only when following the plan as written causes
a real failure.

## harness-integrity

Applies when: the plan touches a harness file (`REVIEW.md`, The harness).

Does it loosen a check, a hook, the gate or the agent setup? A blocker unless the plan says so and the maintainer
agrees.

## premortem

Assume the plan shipped and a user's Kit app broke or their setup stopped working: what was the likeliest cause, and
what plan edit prevents it? Report it only when the plan's text makes the cause plausible.

## Refuting

- Every finding gets a refutation attempt before it is reported.
- Rule it not real when:
  - the plan covers it elsewhere (read the whole plan: this is the usual false positive);
  - it is deferred openly, under Later or Out of scope;
  - it is taste;
  - it rests on a misread rule or code.
- Quote the plan and the rule or code; a refutation without quoted text leaves it real.
- A refuted one stays in the record, with its reason; if the edit would still make the plan simpler, list it as an
  improvement too.
