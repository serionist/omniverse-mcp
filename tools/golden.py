"""Write the tool contract: every tool's name, input and output schemas and annotations, and the resources, as the MCP
server lists them, without their prose. tests/test_contract.py fails when the server and the file part.

Usage: uv run tools/golden.py

Run it after a deliberate change to a tool, and say what changed under CHANGELOG.md's Unreleased: clients depend on
these (AGENTS.md, One-way doors). Unlike the gate and the hooks it imports the server, so it needs `uv sync`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.types import Resource, ResourceTemplate, Tool

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.server import create_server

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "fixtures" / "mcp-tools.json"

# Descriptions and titles are prose, free to change; names, types, bounds, defaults and hints are what clients rely on.
PROSE = frozenset({"description", "title"})
# Keys whose values map names to schemas: a parameter called "title" is not a title.
NAMED = frozenset({"properties", "$defs"})


def strip(node: Any, *, names: bool = False) -> Any:
    """The node without its prose, at any depth."""
    if isinstance(node, dict):
        return {k: strip(v, names=k in NAMED and not names) for k, v in node.items() if names or k not in PROSE}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


async def listing() -> tuple[list[Tool], list[Resource], list[ResourceTemplate]]:
    """What the server lists, prose included. Listing reaches no bridge: the client points at a port nothing dials,
    and its token, given, keeps it from reading this machine's token file."""
    bridge = BridgeClient(port=1, token="")
    try:
        async with Client(create_server("127.0.0.1", 1, str(ROOT), client=bridge)) as client:
            tools = (await client.list_tools()).tools
            resources = (await client.list_resources()).resources
            templates = (await client.list_resource_templates()).resource_templates
    finally:
        bridge.close()
    return tools, resources, templates


async def contract() -> dict[str, Any]:
    tools, resources, templates = await listing()
    return {
        "tools": {
            t.name: {
                "input": strip(t.input_schema),
                "output": strip(t.output_schema),
                "annotations": strip(t.annotations.model_dump(by_alias=True, exclude_none=True))
                if t.annotations
                else None,
            }
            for t in tools
        },
        "resources": {r.uri: {"name": r.name, "mimeType": r.mime_type} for r in resources},
        "resourceTemplates": {r.uri_template: {"name": r.name, "mimeType": r.mime_type} for r in templates},
    }


def render(found: dict[str, Any]) -> str:
    return json.dumps(found, indent=2, sort_keys=True) + "\n"


def main() -> int:
    found = asyncio.run(contract())
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(render(found), encoding="utf-8", newline="\n")
    print(f"{GOLDEN.relative_to(ROOT).as_posix()}: {len(found['tools'])} tools, {len(found['resources'])} resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
