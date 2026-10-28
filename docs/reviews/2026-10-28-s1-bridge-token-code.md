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

Round 2 runs on the fixes (a round 1 major).
