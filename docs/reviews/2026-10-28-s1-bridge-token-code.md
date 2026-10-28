---
subject: S1, lock the bridge to a token (PR #3)
base: main (ceb6dd9)
head: ad8858f
date: 2026-10-28
round: 1
tier: high (one fresh reviewer; findings checked against the code by the main session)
verdict: needs-fixes
---

# Review: S1, the bridge token

Read only. Every finding was checked against the code; fixes landed in the commit after `ad8858f`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `extension.py` `on_startup` | The token file was written before the port was bound. A second Kit app on the same port replaced the running instance's token, failed to bind, and deleted the file on shutdown, so the running instance could not be reached. | Fixed: written in `_start_server` once `start()` succeeds; removed only if this instance wrote it. Checked with Kit mocked (two instances on one port). |
| F2 | major | `client.py` `request` | After a Kit restart, a request with a large body met the 401 as a TCP reset (the refusal closes with the body unread), so the client never re-read the token and reported "cannot connect". | Fixed: every new connection starts with `GET /bridge`, which has no body, so the 401 arrives cleanly. Test: a 2 MB body after a restart. |
| F3 | major | `core/http.py` `_handle_connection` | A connection took a slot of the 20 before any token check, with no read timeout: a local process without the token could hold every slot and lock the client out. | Fixed: slots are taken only by authenticated requests; idle connections close after 5 minutes, slow headers after 10 seconds. Tests for both. |
| F4 | minor | `client.py` `request` | The protocol check rode on `/health`, which fails with no stage open: the check was skipped and every request paid an extra `/health`. | Fixed: `GET /bridge`, answered by the core whatever Kit's state. |
| F5 | minor | `client.py` `_exchange` | A reconnect inside `_exchange` resent the request without the protocol check. | Fixed: the handshake runs on every new connection, retries included. Test: one handshake per connection. |
| F6 | minor | `tests/test_bridge_token.py` | `tomllib` broke collection on Python 3.10. | Fixed: a regex reads the version. |
| F7 | minor | `client.py` `_refusal` | The 401 advice ignored where the token came from (environment, constructor). | Fixed: the message names the source. Tests for each. |
| F8 | minor | `core/token.py` `write_token` | A leftover `.tmp` kept its old mode while the token was written into it. On Windows, file modes do nothing. | Fixed: the leftover is removed and the file is created with `O_EXCL` and 0600; ARCHITECTURE.md says an override folder on Windows must be private. Test (POSIX). |
| F9 | minor | extension `docs/README.md` | The new paragraph split the settings table. | Fixed. |

Improvement taken: the `state` fixture moved to `tests/conftest.py`.

## Round 2

- **Where:** PR #3 at `a418868`, medium tier, one fresh reviewer.
- **Verdict:** needs-fixes. Fixes are in `7199b96`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| R1 | major | `core/http.py` `close` | `close()` stopped listening but left kept-alive connections serving: a client already connected could still run `/execute` after the extension was turned off. | Fixed: `close()` drops every open connection. Test. |
| R2 | major | `client.py` `_exchange` | Any `OSError`, a timeout included, resent the request: a script slower than the client timeout ran twice. | Fixed: a resend happens only on a reused connection that came back empty, which is what a connection the bridge closed while idle looks like. Tests for both cases. |
| R3 | major | `core/http.py` | Moving the slots to handlers left connections without the token unlimited, each up to 300 s, and blank lines reset the wait. | Fixed: at most 32 wait without the token, a newer one pushes the oldest out, and they get 10 s in all, blank lines included. Tests. |
| R4 | minor | `extension.py` `_start_server` | A shutdown while the port was being bound left a listener and a token file behind. | Fixed: `start()` returns False and closes the listener when `close()` came first; no token is written then. Test. |
| R5 | minor | `extension.py` | The token file was named after the configured port, not the bound one (port 0). | Fixed: the bound port. |
| R6 | minor | `extension.py` | The token setting was used as is: whitespace or an unquoted number broke every request. | Fixed: stripped and made a string. |
| R7 | minor | `core/http.py` | An empty token would accept `Bearer ` with nothing after it. | Fixed: the constructor refuses an empty token. Test. |
| R8 | minor | `client.py` `_connect` | IPv6 hosts could not be reached (`AF_INET` only). | Fixed: `socket.create_connection`. |
| R9 | improvement | `core/http.py` `info` | `info()` was optional only for a test. | Taken: always a dict. The test plays an old extension with the mock bridge, which answers 404 to `/bridge`. |
| R10 | improvement | `bridge_token.py` | The token path code is mirrored in the server and the extension. | Left: the two run in different Pythons and neither can import the other; a test keeps them equal. |

No round 3: round 2's majors were fixed with a test each, and the live run decides the rest.

## Live run

On Isaac Sim 6.2.0 (pip, Python 3.12, headless, RTX 5090), at `7199b96`, with `OMNIVERSE_MCP_SIM=1`.

**Baseline:** the same scenario suite against `main`'s server and extension (`ceb6dd9`), on the same Isaac Sim.

**What ran:**

| Suite | This branch | `main` |
|---|---|---|
| `test_integration.py` | 10 passed | - |
| `test_scenarios.py`, all of it | 51 passed, 32 failed, 1 error | 52 passed, 31 failed, 1 error |
| `test_scenarios.py` without the G1 phases (10, 14) | 71 passed, 5 failed | - |

**Lifecycle:**
- The token file is written when Kit starts the extension, and is gone after a clean shutdown.
- A second instance on the same port, checked with Kit mocked, leaves the first one's token alone.

**Why the scenario failures are not this branch's:**
- **The G1 hang.** On both branches Kit stops responding during the G1 robot's physics (its last log line is convex-mesh cooking of `torso_link`), and every later test times out. The 28 failures after it are that hang.
- **The two gravity tests** (`05_03`, `07_02`) expect Y to change, but this stage is Z-up. They fail on `main` too.
- **The three `draw_debug` tests** (`16_03`-`16_05`) get an error from the handler, which this branch does not touch. On `main` they were hidden behind the hang.
- **The one difference, `03_05` (inspect):**
  - It was the first capture after Kit started. A renderer reset took it past the scenario client's 10-second timeout.
  - It passes in 0.5 s on a warm Kit.
  - `main` passed it only by sending the request a second time, which is R2.

These are Isaac Sim 6.2 problems with the tools, outside S1.
