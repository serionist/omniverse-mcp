# Releasing

A release is one pull request that dates the changelog and bumps every version, then a tag `vX.Y.Z` on its merge
commit. The tag starts `.github/workflows/release.yml`, which checks, waits for CI, publishes to PyPI once the
maintainer approves, makes the GitHub release and publishes `server.json` to the official MCP registry. The
plan's S9, S10 and D7 say why it works this way.

## Once

| What | Where | Done |
|---|---|---|
| A trusted publisher: project `omniverse-mcp`, owner `serionist`, repository `omniverse-mcp`, workflow `release.yml`, environment `pypi` | PyPI, your account, Publishing (pending until the first upload) | 2026-10-29 |
| The environment `pypi`, with the maintainer as required reviewer, deploying from `v*` tags only | GitHub, Settings, Environments | 2026-10-28 |
| The ruleset "release tags": only admins create, move or delete a `v*` tag | GitHub, Settings, Rules | 2026-10-28 |
| Nothing for the MCP registry: it takes a GitHub Actions OIDC token from any repository `serionist` owns for `io.github.serionist/*`, and the README on PyPI for the package; here only `release.yml`'s `registry` job asks for one | none | |

## Each release

1. **The release PR,** from an issue, on a branch `<issue>-release-X.Y.Z`:
   - `CHANGELOG.md`: `## Unreleased` becomes `## X.Y.Z (YYYY-MM-DD)`, with a new empty `## Unreleased` above it. The
     section is the release's notes;
   - the version, X.Y.Z, in `pyproject.toml`, `extension/ovmcp.bridge/config/extension.toml`,
     `plugin/.claude-plugin/plugin.json`, `server.json` (twice: the server's and its package's), and every
     `omniverse-mcp==` and `ovmcp.bridge-` under `plugin/`. The gate's `plugin` check names each one that differs;
   - `uv lock`, which records the project's own version;
   - `uv run --no-project tools/release.py check vX.Y.Z` passes; CI's `Package (Linux)` runs the same check on the PR;
   - the README says nothing that is true only before this release: PyPI keeps the description it is given.
2. **Try its wheel before it merges.** CI's `Package (Linux)` job keeps it as the `dist` artifact:
   `gh run download <run id> -n dist -D <folder>`. Then, against a Kit app of your own:
   - `uvx --from <folder>/omniverse_mcp-X.Y.Z-py3-none-any.whl omniverse-mcp extension install`, and Kit started with
     the folder it prints on its extension search path;
   - the live suites (`AGENTS.md`, Build and test) against that Kit app;
   - the AI scenario suite, every phase, against the same Kit app (`run-scenarios`), compared with the last release's
     run (`uv run tools/scenarios.py compare --against v<last>`): each regression fixed, or explained in the PR;
   - the plugin, a copy of `plugin/` whose `.mcp.json` runs `uvx --from <the wheel> omniverse-mcp`, loaded with
     `claude --plugin-dir`: `/omniverse-mcp:setup` reports the extension equal to the server.
3. **Merge it, then tag its merge commit at once:** `git tag vX.Y.Z <merge commit>` and `git push origin vX.Y.Z`.
   The marketplace serves `main`, so from the merge until PyPI has the version, a plugin user's server can't start
   (plan R10): keep that window short.
4. **Approve the deployment.** The run waits at `Publish to PyPI` for the `pypi` environment's reviewer, after its
   checks and a green `ci.yml` run on the tagged commit.
5. **Check it:** `uvx omniverse-mcp==X.Y.Z --help` runs, PyPI's page shows the README's images and its in-page links
   land on their headings, the GitHub release has the wheel, the sdist and `ovmcp.bridge-X.Y.Z.zip`, with the
   changelog section and the install lines as its notes, and the registry lists X.Y.Z:
   `curl "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.serionist/omniverse-mcp"`.

## When it fails

Nothing is published before the approval. Then:

- **By chance** (a CI leg or the build fails on a runner or the network, or CI isn't done within 40 minutes): re-run
  the failed jobs of `ci.yml`'s run on the tagged commit, then the release run's failed jobs. Its checked files stay in
  the run.
- **For a reason** (`release.py check`, a content check, a test): fix it on `main` in a pull request, and release the
  next patch version. A released tag is never moved, by this repo's rule (the ruleset lets only admins move one), and a
  version is never published twice.
- **The publish step:** re-run the job. It passes over a file PyPI already has (`skip-existing`), so a partial upload
  finishes.
- **After the publish:** fix forward with the next patch version. A release on PyPI can be yanked, never replaced.
- **The MCP registry job:** it tries five times over five minutes, for PyPI to show the upload. Re-run it while
  the registry lacks the version; a version it has is refused, so a re-run after a success changes nothing. A
  refusal of `server.json` itself is fixed in the next patch version, since `ci.yml` checks it on every PR.
