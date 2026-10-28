---
subject: "S7c, test every tool against the mock bridge, and type the server strictly (PR #26)"
base: main (560cfdd)
head: eefeff5
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: S7c, test every tool against the mock bridge, and type the server strictly

Read from the pack (the scope diff), the bridge's handlers and core, the mock bridge and CI's results on the head
(all 14 checks passed, the coverage leg against floor 92). Two minors, so no round 2; fixed in `7cb8343`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_tools.py`, the `get_prim_properties`, `dump_scene` and `start_recording` cases | Three cases could pass with a broken tool. `get_prim_properties`' case didn't pin `"format": "text"`: drop `fmt="text"` from the tool and the case still passed, as the canned answer always holds `text`, while against Kit the bridge sends `text` only when asked (`fmt = body.get("format", "json")`) and the tool fails on a missing key. The other two never checked `output_dir`, the folder each tool exists to pass on. | Fixed: the `format` is pinned, and both `output_dir`s through an `OUTPUT` stand-in each test replaces with its own folder. |
| F2 | minor | the plan's progress log, the PR description | Two coverage figures for one change: 92.54% in the log, 92.50% in the PR. | Fixed: 92.50%, from `gate full` on Windows, in both. |

Refuted, each from the code:

- **The client refactor changes behaviour:** the stale-socket retry is unchanged (`reused = sock is not None`, the
  same `raise` condition, and a second attempt reconnects with a handshake); after `_disconnect()` inside
  `_read_response` it raises or reads no more; `close()` takes the lock `request()` holds; `_connect()`'s one caller
  is guarded by `if sock is None:`. The one path that differs, a 200 handshake with `Connection: close`, crashed with
  `AttributeError` before and raises `OSError` without a retry now; the bridge sends `close` only on refusals, 400 and
  413 (`core/http.py`).
- **`draw_debug`'s labels assume dicts:** every item the handler appends is a dict (`handlers/misc.py`), and the
  handshake pins protocol 1.
- **`body or {}` hides a missing body:** the mock records `{}` for an empty body; the `or` is gone anyway.
- **The `TYPE_CHECKING` imports make a cycle, or change what the SDK reads:** `server` is imported only for the
  checker; no `from __future__ import annotations` in `src/`, so the tools' annotations stay real objects, and the
  golden file is unchanged.
- **`py.typed` needs a CHANGELOG line:** the wheel ships it (`packages = ["src/omniverse_mcp"]`), and no user of
  the command notices it.
- **A CI leg could measure under 92:** CI's coverage leg passed on the head; the OS-specific lines are a handful.
  The margin is thin, now 92.82% on `7cb8343`.

Not covered: kit-main-thread and bridge-security found nothing to apply to (no extension code changed; `_build` and
`_refusal` changed only in types). The reviewer ran nothing; CI and the author's runs stand in.

Improvements:

- **Unit tests for the retry rule,** which the refactor kept but nothing pinned: taken,
  `test_a_dropped_kept_alive_connection_is_retried_once_with_a_new_handshake` and
  `test_a_reply_cut_short_is_not_sent_again` (`tests/test_client.py`), against a scripted socket bridge; the second
  keeps a connection ready, so a retry would succeed and show. With the "bytes came back" guard removed the second
  fails, and with retries removed the first.
- **`manage_extensions`' enable path:** taken, `test_manage_extensions_enables_one`.
- **`pyproject.toml`'s strict comment cited plan ids, not a reason:** taken.
- **`stop_recording`'s case checked `"State: "` only:** taken, the state file's path.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for this run, loading `ovmcp.bridge` from the branch's
`extension/`; the maintainer's own Isaac Sim on 8211 was not touched. On `eefeff5` (`7cb8343` changes only tests,
docs and a comment):

- **The live suites,** `-k "not test_10_ and not test_14_"` (#5), through the changed client: the first run after
  Kit started, 108 passed, with #6's `test_05_03` and `test_07_02`, #7's three `draw_debug` scenarios and
  `test_22_01_inspect_with_segmentation` failing; two more runs, 111 passed, only #7's three failing. `test_22_01`
  fails only on a first run after Kit starts (2 of 3 such runs across #24 and #26), whatever the client: #27.
- **The MCP tools through the in-memory client** (the S7b smoke script): 43 calls as expected; `draw_debug` fails
  as #7 says.

## Checks

`uv run tools/gate.py full` passed on `eefeff5` (606 tests, 92.50%) and on `7cb8343` (609 tests, 92.82%). The new
per-tool tests failed on two planted faults, a tool's text and a client body, and passed again once restored.
