---
subject: "S8, extension install: omniverse-mcp extension install and extension path (PR #28)"
base: main (6e62ddc)
head: 8ccec6e
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: S8, extension install

Read from the pack (the scope diff), the touched files in full, `bridge_token.py`, the wheel settings in
`pyproject.toml` and the gate's `run` and `git` helpers, with CI's results on the head (every leg passed). Six minors,
so no round 2; fixed in `c5bb8eb`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `kit_extension.py`, `install()` | When the swap failed and putting the old copy back failed too, the restore's `OSError` escaped as a traceback and `finally` deleted the old copy, the only one left: `exts` ended with no extension. Two installs at once could also end in a traceback. | Fixed: the restore is tried only when the old copy is there, in its own `try`; when it fails the old copy is kept, and the message names its folder. `test_an_install_that_cannot_put_the_one_before_back_keeps_it_and_says_where`. |
| F2 | minor | `kit_extension.install_command()`, `client.py` `_check_handshake` | A checkout user who installed a copy was told `uvx omniverse-mcp==0.1.0 extension install`, a version not on PyPI, whose extension would be the release's and not the checkout's; the "git pull" beside it doesn't touch an installed copy. | Fixed: an editable install (the source is the checkout's `extension/`) is told `uv run --project <checkout> omniverse-mcp extension install`; the wheel keeps the uvx command. `test_the_install_command_fits_the_install`. |
| F3 | minor | `kit_extension.main()` | The `--ext-folder` path it printed was unquoted, so a profile folder with a space (`C:\Users\John Smith`) broke the pasted command. | Fixed: quoted for the platform's shell (double quotes on Windows, `shlex.quote` elsewhere); `test_a_checkout_installs_its_own_extension` checks it. |
| F4 | minor | `tests/test_kit_extension.py`, `_tracked()` | Three tests compared the install with git's index, while the install and the wheel copy the working tree: a new module not yet added, or a `.DS_Store`, failed them with the code right. | Fixed: they compare with the working tree's extension folder; no git call is left. |
| F5 | minor | `test_the_wheel_installs_the_extension_it_carries` | `uv build` resolves hatchling from the index, so the unit suite needed the network. | Fixed: `uv build --offline`, with hatchling in uv's cache from the editable install the tests run in. |
| F6 | minor | the PR description; `kit_extension.main()`'s last line | The PR didn't say what the live run could not show: Linux, where the rename succeeds under a running Kit that may hot-reload the extension, and Isaac Sim 5.x. The printed "loads the new extension when it restarts" was unverified there. | Fixed: the message says "Restart any Kit app that runs the extension", true whatever Kit does; the PR lists what the live run could not show. |

Refuted, each from the code:

- **A first rename refused by Windows loses or litters the old copy:** `not target.exists()` skips the restore, and
  `rmtree(old)` runs on a path that was never made; the live run left the installed copy whole with nothing beside it.
- **`finally` deletes the new install after a good swap:** after `staging.rename(target)` the staging path is gone.
- **`mkdtemp`'s 0700 mode makes the install private:** `copytree` ends with `copystat(src, dst)` on the root.
- **Concurrent installs end with no extension:** every interleaving leaves one whole copy; the traceback is F1.
- **The routing by first word:** `extension` alone is argparse's "required" error, `extension --help` prints its
  help, `extension install --port 1` is "unrecognized arguments"; the server's flags never take the route.
- **A one-way door broken:** nothing is released, and the plan's Names lists `extension install|path`.
- **The wheel test can't run on Windows or macOS:** every leg passed on `8ccec6e`.
- **`install_command()` raises `PackageNotFoundError` mid-handshake:** `create_server` already reads the version.
- **A non-dict `result` raises `AttributeError`:** only a server that isn't the bridge, answering `/bridge` with 200,
  gets there, and its calls fail either way.
- **The data folder and the token folder collide on Windows and macOS:** tokens are `bridge-<port>.token` at the
  top, the extension under `exts/`.
- **The wheel test patches `_PACKAGE`, so it proves nothing:** `_PACKAGE` is the module's only input, pointed where
  the wheel puts the module.

Not covered: kit-main-thread (no Kit-bound code changed). bridge-security found nothing (`client.py` changes message
text only). Kit's behaviour on Linux when the folder is swapped under it was not run (F6). The reviewer ran nothing;
CI and the author's runs stand in.

Improvements, all taken:

- **`install_command()` ran its metadata lookup on every handshake:** it runs in the refusal branches only.
- **The install folder as a one-way door:** Kit's search paths and users' `--ext-folder` scripts will hold it, and a
  move would strand every install without an error. Added to AGENTS.md's One-way doors.
- **`path`'s hint named `omniverse-mcp`, which a uvx user has no command for:** it names `install_command()`.
- **`mkdir` and `mkdtemp` sat outside the `try`:** a folder it cannot write is an `InstallError` with the path,
  `test_an_install_into_a_folder_it_cannot_write_says_so`.
- **Piped output on Windows is in the code page,** so a path outside it raised `UnicodeEncodeError`: the command's
  streams are UTF-8, as the gate's are.

Beyond the findings, the copy is now made in the data folder, outside `exts`, where Kit's search path never sees a
half-made extension or an old one set aside.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for this run; the maintainer's own Isaac Sim on 8211 was not
touched. The extension was installed with `omniverse-mcp extension install` into a scratch data folder
(`LOCALAPPDATA` pointed at it) and Kit started with its `exts` folder on the search path; Kit loaded
`ovmcp.bridge` from there.

- **The live suites,** `-k "not test_10_ and not test_14_"` (#5), on `8ccec6e`: the first run after Kit started, 108
  passed, with #6's two, #7's three `draw_debug` scenarios and #27's `test_22_01` failing; the second, 111 passed,
  only #7's three failing. As on `main`.
- **Installing again while Kit ran,** on `8ccec6e` and on the fixes: Windows refused the first rename (`WinError 5`),
  the command said to quit Kit and run it again, the installed copy stayed whole with nothing left beside it or in the
  data folder, and Kit kept answering (integration 28/28 after each). Once Kit had quit, the same command replaced
  the copy ("in place of 0.1.0").
- **Not shown:** Linux and macOS, where the rename succeeds under a running Kit, and what Kit's hot reload then does;
  Isaac Sim 5.x.

## Checks

`uv run tools/gate.py full` passed on `8ccec6e` (624 tests, 93.21%) and on the fixes (628 tests, 93.29%). Against
`8ccec6e`'s `kit_extension.py`, the new tests for F1, F2, F3 and two improvements failed (5 of 14), and all passed
with the fixes.
