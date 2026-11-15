---
subject: "Name Context7's omni.physx library, and NVIDIA's Kit docs server for contributors (#204)"
base: main (e96adb3)
head: 0de23ba
date: 2026-11-15
round: 1
tier: "one fresh reviewer on Claude Opus, the lenses that fit a docs and config change. Three minors, so no second round"
verdict: clean
---

# Review: Context7's omni.physx library and NVIDIA's Kit server

Read from the branch's diff against `main` at `e96adb3` (10 files, 175 lines) by one fresh reviewer, read only, who
checked the setup against NVIDIA-Omniverse/kit-usd-agents through `gh api` and the library ID with Context7. No plan:
docs and contributor setup, no tool or extension behaviour. Three minors, fixed in the commit after `0de23ba`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `.mcp.json` | An `nvidia-kit` entry the example's `enabledMcpjsonServers` leaves out prompts every contributor about a Docker server most don't run, and shows a failed server to those who accept it | fixed: no `.mcp.json` entry; `CONTRIBUTING.md` says `claude mcp add --transport http nvidia-kit http://localhost:9902/mcp`, NVIDIA's own form |
| F2 | minor | `CONTRIBUTING.md` | The build steps leave out Git LFS, which the build needs, and Windows' `build-wheels.bat` | fixed: both named, PowerShell's form beside the command |
| F3 | minor | `CONTRIBUTING.md`; #204 | "lost to Context7 on this repo's questions (#204)" cites a trial the issue didn't hold, and the change departs from the issue's Next | fixed: the trial's table posted on #204, the departure said there |

**Refuted:** the Context7 ID (it resolves); the port, path and compose service (`docker-compose.ngc.yaml`, the
server's README); "neither covers Kit 107" (NVIDIA's index holds 109.0 to 110.1); AGENTS.md's cap (150 lines); the
writing rules; a test pinning the server's instructions; the CHANGELOG entry (users see the instructions and the
skill; the contributor setup is left out).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Write both library IDs in Context7's `/org/project` form | left: the repo, the server's instructions and the skills name `isaac-sim/isaacsim` without the slash throughout, which Context7 resolves; changing all of them is a change of its own |
| I2 | Split the `script` skill's step 2 into the libraries and the version | taken |
