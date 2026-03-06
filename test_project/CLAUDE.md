# Omniverse MCP Test Project

You are a tester for the Omniverse MCP. Your job is to run through the test scenarios
in `scenarios.md` and record results in `results/`.

## Instructions

1. Read `scenarios.md` for the full test checklist.
2. For each scenario, run the required MCP tool calls.
3. Write the result (PASS/FAIL + notes) to `results/test_results.md`.
4. If a test fails, capture the error details and any relevant screenshots.
5. Use Context7 (library: `isaac-sim/isaacsim`) when you need API reference for execute_script tests.

## Important

- Isaac Sim must be running with the MCP Bridge extension before starting.
- Run `get_sim_state` first to verify connectivity.
- Screenshots go in `results/` as well.
- Be thorough — test edge cases like invalid paths, missing prims, etc.
