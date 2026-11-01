"""The tool contract clients depend on: the server lists what tests/fixtures/mcp-tools.json holds (tools/golden.py
writes it), every tool says what it does to the Kit app, every parameter is described, docs/TOOLS.md has a heading
for each tool and none for a tool that is gone, and nothing an agent reads names a tool that is gone."""

import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any

import golden
import pytest
from mcp.types import Resource, ResourceTemplate, Tool

from omniverse_mcp.server import INSTRUCTIONS
from omniverse_mcp.tools._annotations import DESTROYS, EDITS, READS, RUNS

TOOLS_MD = golden.ROOT / "docs" / "TOOLS.md"
# What an agent reads beside the tools: the plugin's skills, and the guide for clients without the plugin.
AGENT_FILES = [*sorted((golden.ROOT / "plugin" / "skills").glob("*/SKILL.md")), golden.ROOT / "docs" / "AI_GUIDE.md"]
HINTS = [h.model_dump(by_alias=True, exclude_none=True) for h in (READS, EDITS, DESTROYS, RUNS)]
# docs/TOOLS.md's hints table, a row for each of HINTS in the same order.
HINT_ROWS = ("read-only", "not destructive", "destructive", "destructive, open world")
# Tools merged into another (#77). A call to one is an unknown tool, so a description, the server's instructions or a
# plugin skill that still names one sends an agent after a tool the server doesn't list.
REMOVED = frozenset({"look_at_prim", "get_joint_states", "get_prim_face_count_tree", "dump_scene"})


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


@pytest.mark.parametrize(
    ("tool", "says"),
    [
        # An agent reading these learns when to reach for viewport_light: not only for an all-black image (#105).
        ("capture_viewport", "lighting that lights nothing"),
        ("inspect_prim", "lighting that lights nothing"),
        ("viewport_light", "warns that the lighting lights nothing"),
        ("create_robot", "A file that authors no upAxis is left as it is"),
        ("create_prim", "one that authors none is left as it is"),
        # Each prim's own material, not one prims of a name share, and what copies and clones do with it (#113).
        ("set_physics_properties", "a child named PhysMat (/World/Cube/PhysMat for /World/Cube)"),
        ("set_physics_properties", "A copy made with clone_prim takes its own with it"),
        ("set_physics_properties", "follows the source's material until a call on the clone"),
        # An agent reading this knows a robot of other units comes in at its size, its physics converted (#112).
        ("create_robot", "A file whose metersPerUnit or kilogramsPerUnit isn't the stage's is brought to the stage's"),
    ],
)
def test_a_description_says_what_the_tool_now_does(listed, tool: str, says: str):
    tools, _, _ = listed
    (description,) = [" ".join((t.description or "").split()) for t in tools if t.name == tool]
    assert says in description


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


def _names(name: str, text: str) -> bool:
    """Whether text names the tool as a word of its own: `name(`, `name`, or a skill's allowed-tools entry ending
    `__name`, though not a longer name such as `name_2`."""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?!\w)", text) is not None


def _naming_removed(tools: list[Tool], files: list[Path]) -> list[str]:
    """Where what an agent reads names a removed tool: each tool's description and its parameters', which a client
    shows the model beside it, the server's instructions, and files, such as the plugin's skills."""
    texts = {"the server's INSTRUCTIONS": INSTRUCTIONS}
    for t in tools:
        texts[f"{t.name}'s description"] = t.description or ""
        for param, schema in t.input_schema.get("properties", {}).items():
            texts[f"{t.name}.{param}'s description"] = schema.get("description", "")
    for path in files:
        where = path.relative_to(golden.ROOT).as_posix() if path.is_relative_to(golden.ROOT) else str(path)
        texts[where] = path.read_text(encoding="utf-8")
    return sorted(f"{where}: {name}" for where, text in texts.items() for name in REMOVED if _names(name, text))


def test_a_removed_tool_is_neither_listed_nor_named(listed):
    tools, _, _ = listed
    assert sorted(REMOVED & {t.name for t in tools}) == [], "the server still lists these"
    named = _naming_removed(tools, AGENT_FILES)
    assert not named, f"these name a tool that is gone: {named}"


@pytest.mark.parametrize("where", ["a parameter", "a file"])
def test_a_removed_tool_named_in_a_parameter_or_a_file_is_found(where: str, listed, tmp_path: Path):
    # The check is only as good as what it reads: a name planted in either is caught.
    tools, _, _ = listed
    files = list(AGENT_FILES)
    if where == "a parameter":
        planted = next(t for t in tools if t.name == "get_scene_tree").model_copy(deep=True)
        planted.input_schema["properties"]["root"]["description"] = "the prim dump_scene started from"
        tools = [*tools, planted]
    else:
        guide = tmp_path / "AI_GUIDE.md"
        guide.write_text("Look with `look_at_prim` first.", encoding="utf-8")
        files.append(guide)
    assert len(_naming_removed(tools, files)) == 1


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("frame it with look_at_prim(path)", True),
        ("`look_at_prim`", True),
        ("mcp__plugin_omniverse-mcp_omniverse__look_at_prim mcp__plugin_omniverse-mcp_omniverse__get_logs", True),
        ("look_at_prim.", True),
        ("look_at_prim_2", False),
        ("relook_at_prim", False),
        ("mcp.look_at(path)", False),
    ],
)
def test_a_tool_is_named_as_a_word_of_its_own(text: str, names: bool):
    assert _names("look_at_prim", text) is names


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
