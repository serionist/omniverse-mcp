"""The tool contract clients depend on: the server lists what tests/fixtures/mcp-tools.json holds (tools/golden.py
writes it), every tool says what it does to the Kit app, every parameter is described, and docs/TOOLS.md has a heading
for each tool and none for a tool that is gone."""

import asyncio
import inspect
import json
import re
from typing import Any

import golden
import pytest
from mcp.types import Resource, ResourceTemplate, Tool

from omniverse_mcp.tools._annotations import DESTROYS, EDITS, READS, RUNS

TOOLS_MD = golden.ROOT / "docs" / "TOOLS.md"
HINTS = [h.model_dump(by_alias=True, exclude_none=True) for h in (READS, EDITS, DESTROYS, RUNS)]
# docs/TOOLS.md's hints table, a row for each of HINTS in the same order.
HINT_ROWS = ("read-only", "not destructive", "destructive", "destructive, open world")


@pytest.fixture(scope="module")
def listed() -> tuple[list[Tool], list[Resource], list[ResourceTemplate]]:
    return asyncio.run(golden.listing())


@pytest.fixture(scope="module")
def found() -> dict[str, Any]:
    return asyncio.run(golden.contract())


def test_the_server_lists_the_golden_contract(found):
    expected = json.loads(golden.GOLDEN.read_text(encoding="utf-8"))
    assert found == expected, (
        "The tool contract changed. If you meant it, run `uv run tools/golden.py` and say what changed under "
        "CHANGELOG.md's Unreleased."
    )


def test_the_golden_file_is_as_golden_writes_it(found):
    # A hand edit that parses the same still shows up in a diff as noise.
    assert golden.GOLDEN.read_text(encoding="utf-8") == golden.render(found)


def test_every_tool_says_what_it_does_to_the_kit_app(listed):
    tools, _, _ = listed
    loose = sorted(
        t.name
        for t in tools
        if not t.annotations or t.annotations.model_dump(by_alias=True, exclude_none=True) not in HINTS
    )
    assert not loose, f"annotate these with READS, EDITS, DESTROYS or RUNS (tools/_annotations.py): {loose}"


def test_every_tool_and_parameter_is_described(listed):
    tools, _, _ = listed
    bare = [t.name for t in tools if not (t.description or "").strip()]
    bare += [
        f"{t.name}.{name}"
        for t in tools
        for name, schema in t.input_schema.get("properties", {}).items()
        if not schema.get("description", "").strip()
    ]
    assert not bare, f"describe these: {bare}"


def test_no_description_carries_its_source_indentation(listed):
    # The SDK sends a docstring as it is, and Python before 3.13 keeps its source indentation in __doc__. A line
    # indented within the text, such as a code example's, is the description's own.
    tools, _, _ = listed
    indented = sorted(t.name for t in tools if (t.description or "") != inspect.cleandoc(t.description or ""))
    assert not indented, f"these descriptions carry their source's indentation: {indented}"


def test_the_tool_reference_has_a_heading_per_tool(found):
    headings = re.findall(r"^### `(\w+)`$", TOOLS_MD.read_text(encoding="utf-8"), re.MULTILINE)
    tools = set(found["tools"])
    assert sorted(tools - set(headings)) == [], "docs/TOOLS.md has no heading for these tools"
    assert sorted(set(headings) - tools) == [], "docs/TOOLS.md has headings for tools the server doesn't list"
    assert len(headings) == len(set(headings)), "docs/TOOLS.md has a tool's heading twice"


def test_the_tool_reference_lists_each_tool_under_its_hints(listed):
    tools, _, _ = listed
    text = TOOLS_MD.read_text(encoding="utf-8")
    under: list[tuple[str, dict[str, Any]]] = []
    for label, hints in zip(HINT_ROWS, HINTS, strict=True):
        row = re.search(rf"^\| {re.escape(label)} \| [^|]+ \| (.+) \|$", text, re.MULTILINE)
        assert row, f"docs/TOOLS.md has no hints row {label!r}"
        under += [(name, hints) for name in re.findall(r"`(\w+)`", row.group(1))]
    names = [name for name, _ in under]
    assert len(names) == len(set(names)), "docs/TOOLS.md lists a tool under two hints"
    documented = dict(under)
    wrong = sorted(
        t.name
        for t in tools
        if not t.annotations or documented.get(t.name) != t.annotations.model_dump(by_alias=True, exclude_none=True)
    )
    assert not wrong, f"docs/TOOLS.md's hints table puts these under the wrong row, or none: {wrong}"


def test_the_tool_reference_lists_each_resource(found):
    text = TOOLS_MD.read_text(encoding="utf-8")
    missing = [uri for uri in found["resources"] if f"`{uri}`" not in text]
    assert not missing, f"docs/TOOLS.md's MCP Resources table lacks: {missing}"


def test_prose_goes_and_a_parameter_named_like_it_stays():
    schema = {
        "title": "set_titleArguments",
        "description": "Prose.",
        "properties": {"title": {"type": "string", "title": "Title", "description": "The title."}},
        "$defs": {"description": {"type": "object", "title": "Description"}},
        "required": ["title"],
    }
    assert golden.strip(schema) == {
        "properties": {"title": {"type": "string"}},
        "$defs": {"description": {"type": "object"}},
        "required": ["title"],
    }
