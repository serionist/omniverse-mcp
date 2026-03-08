# Omniverse MCP Test Project

You are a tester for the Omniverse MCP. Run through `scenarios.md` and record results in `results/test_results.md`.

@../docs/AI_GUIDE.md

## Setup

1. Isaac Sim must be running with the MCP Bridge extension enabled.
2. Call `get_sim_state()` first to verify connectivity.
3. Call `new_scene()` to start with a clean stage.
4. Use Context7 (library: `isaac-sim/isaacsim`) when you need API reference for `execute_script` tests.

## Running Tests

Run scenarios **in order** -- later phases depend on prims created in earlier ones.

For each test:
1. Execute the MCP tool calls described in `scenarios.md`
2. Evaluate the result against the **Verify** criteria
3. Record the result in `results/test_results.md`

## Recording Results

Use these status values:

| Status | Meaning |
|--------|---------|
| **PASS** | Test passed, behavior matches expectations |
| **FAIL** | Test failed -- wrong result, error, or missing data |
| **WARN** | Test passed but with unexpected behavior worth investigating |
| **SKIP** | Test skipped (dependency failed, or not applicable) |

### What to record

For every test, record:
- **Status**: PASS / FAIL / WARN / SKIP
- **Notes**: Brief observation (always fill this in, even for PASS)
  - PASS: What was returned (e.g., "3 images returned, cube visible in each")
  - FAIL: Error message or what went wrong (e.g., "returned 0 faces, expected > 0")
  - WARN: What was unexpected (e.g., "first capture black, second capture OK")
  - SKIP: Why it was skipped (e.g., "Phase 6 robot not created due to 10.1 failure")

### Output files

Save any captured images, exports, recordings, and scene dumps to `results/`. These are evidence for investigating failures.

## Result File Format

Use this exact format in `results/test_results.md`:

```markdown
# Test Results

## Run Info
- **Date**: YYYY-MM-DD
- **Isaac Sim version**: (from get_sim_state or console)
- **Run type**: full / retest
- **Notes**: (anything relevant about the environment)

## Results

| ID | Test | Status | Notes |
|----|------|--------|-------|
| 1.1 | Health Check | PASS | up_axis=Z, state=stopped |
| ... | ... | ... | ... |

## Issues

### Open
- **ISS-001** [FAIL 18.1]: Robot mesh stats return 0 faces -- instance proxy traversal bug
- **ISS-002** [WARN 6.2]: Recording frames intermittently 0 bytes

### Fixed
- **ISS-001** [fixed in commit abc123]: Added TraverseInstanceProxies to PrimRange calls

## Retest Plan
Tests to re-run on next pass:
- 18.1, 18.4 (ISS-001 fix)
- 6.2 (ISS-002 investigation)
```

## Iterative Workflow

### First run (full)
1. Run ALL tests in order
2. Record every result
3. Create issues for every FAIL and WARN
4. Write a retest plan at the bottom

### Subsequent runs (retest)
1. Read the previous run's issues and retest plan
2. Run `new_scene()` for clean state
3. Re-run the tests listed in the retest plan (plus any setup phases they depend on)
4. Update the status in the results table (append the new status, don't delete the old one)
5. If a fix resolved the issue, move it from Open to Fixed
6. If new issues appear, add them
7. Update the retest plan

### Updating results across runs

When re-testing, update the Notes column to show history:

```
| 18.1 | Mesh Stats Robot | PASS | Run 2: 12847 faces. Run 1: FAIL 0 faces (ISS-001) |
```

This preserves the history so we can see what changed.

## Important

- **Be thorough**: Always fill in Notes, even for PASS. Raw numbers, prim counts, and observations are valuable.
- **Don't guess**: If a test result is ambiguous, mark it WARN and describe what you saw.
- **Dependencies**: If a test depends on a prior phase that failed, SKIP it and note the dependency.
- **Captures**: Save viewport captures for any FAIL or WARN test. Name them like `fail_18_1_mesh_stats.png`.
- **Timing**: Some tests need brief waits (physics, recording). If unsure, wait longer rather than shorter.
- **Phase 27 (Cleanup)**: Always run this at the end to leave the scene clean.
