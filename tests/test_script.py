"""ovmcp.core.script, Kit-free (#158): a script compiled once, told awaiting or plain by the compiler's own flag, and
run as a function of its namespace, awaited when it awaits; a top-level return still run as the old wrapper ran it;
a file read as bytes and compiled with its path."""

import asyncio
import traceback
from pathlib import Path
from typing import Any

import pytest

from ovmcp.core import script


def _run(code: str | bytes, filename: str = script.FILENAME, **names: Any) -> dict[str, Any]:
    namespace: dict[str, Any] = {"asyncio": asyncio, **names}
    asyncio.run(script.run(script.compile_script(code, filename), namespace))
    return namespace


def _traceback(code: str | bytes, filename: str = script.FILENAME) -> str:
    with pytest.raises(ValueError, match="boom") as raised:
        _run(code, filename)
    return "".join(traceback.format_exception(raised.value))


# ----- awaiting or plain -----


@pytest.mark.parametrize(
    ("code", "awaits"),
    [
        ("x = 1\nresult = x", False),
        ("await asyncio.sleep(0)", True),
        ("for i in range(3):\n    await asyncio.sleep(0)", True),
        ("async with lock:\n    pass", True),
        ("async for x in stream:\n    pass", True),
        ("result = [await asyncio.sleep(0, i) for i in range(3)]", True),
        # A coroutine function the script only defines awaits nothing of the script's own.
        ("async def later():\n    await asyncio.sleep(0)\n", False),
        ("import asyncio\nasyncio.ensure_future(asyncio.sleep(1))", False),
    ],
)
def test_awaiting_and_plain_code_are_told_apart(code: str, awaits: bool):
    assert script.compile_script(code).awaits is awaits


@pytest.mark.parametrize(
    ("code", "awaits"),
    [("return 7", False), ("await asyncio.sleep(0)\nreturn 7", True), ("if True:\n    return 7", False)],
)
def test_a_top_level_return_is_told_apart_too(code: str, awaits: bool):
    compiled = script.compile_script(code)
    assert (compiled.returns, compiled.awaits) == (True, awaits)


# ----- running -----


def test_a_plain_script_runs_in_its_namespace():
    namespace = _run("x = 20\nresult = x + 22")
    assert (namespace["result"], namespace["x"]) == (42, 20)


def test_an_awaiting_script_is_awaited():
    namespace = _run("await asyncio.sleep(0)\nresult = 'after'")
    assert namespace["result"] == "after"


def test_a_class_and_a_function_see_the_namespace():
    namespace = _run("K = 3\nclass Box:\n    side = K\ndef area():\n    return Box.side * K\nresult = area()")
    assert namespace["result"] == 9


def test_a_multi_line_string_in_an_awaiting_script_is_kept_whole():
    # The old wrapper indented every line of the script, a string's own lines included.
    namespace = _run('await asyncio.sleep(0)\nresult = """first\nsecond\n  third"""')
    assert namespace["result"] == "first\nsecond\n  third"


@pytest.mark.parametrize(
    "code",
    [
        "x = 1\ny = 2\nraise ValueError('boom')",
        "await asyncio.sleep(0)\ny = 2\nraise ValueError('boom')",
        "x = 1\nif x:\n    raise ValueError('boom')\nreturn x",
    ],
    ids=["plain", "awaiting", "returning"],
)
def test_a_traceback_names_the_script_s_own_line(code: str):
    # The old wrapper's line came one after the script's, for an awaiting script.
    assert f'File "{script.FILENAME}", line 3, in ' in _traceback(code)


def test_a_top_level_return_gives_the_result():
    namespace = _run("print_me = 1\nreturn {'value': 7}")
    assert namespace["result"] == {"value": 7}


def test_a_top_level_return_ends_the_script_there():
    namespace = _run("result = 1\nif result:\n    return 2\nresult = 3")
    assert namespace["result"] == 2


def test_a_returning_script_that_awaits_is_awaited():
    namespace = _run("await asyncio.sleep(0)\nreturn 'late'")
    assert namespace["result"] == "late"


@pytest.mark.parametrize("code", ["x = = 1", "def f(:\n    return 1", "class A:\n    return 1"])
def test_a_real_syntax_error_is_raised(code: str):
    with pytest.raises(SyntaxError):
        script.compile_script(code)


# ----- a file -----


def test_a_file_is_read_as_bytes_and_named_by_its_path(tmp_path: Path):
    path = tmp_path / "bake.py"
    path.write_bytes(b"x = 1\ny = 2\nraise ValueError('boom')\n")

    source, filename = script.read_file(str(path))

    assert source == path.read_bytes()
    assert Path(filename) == path.resolve()
    text = _traceback(source, filename)
    # Its own path and line, and the line itself, read from the file.
    assert f'File "{filename}", line 3, in <module>' in text
    assert "raise ValueError('boom')" in text


def test_a_file_s_encoding_follows_python_s_source_rules(tmp_path: Path):
    path = tmp_path / "latin.py"
    path.write_bytes("# -*- coding: latin-1 -*-\nresult = 'Tübingen'\n".encode("latin-1"))
    source, filename = script.read_file(str(path))
    assert _run(source, filename)["result"] == "Tübingen"


def test_a_file_with_a_bom_reads_as_utf_8(tmp_path: Path):
    path = tmp_path / "bom.py"
    path.write_bytes("\ufeffresult = 'Ω'\n".encode())
    source, filename = script.read_file(str(path))
    assert _run(source, filename)["result"] == "Ω"


def test_a_returning_file_is_read_by_the_same_rules(tmp_path: Path):
    path = tmp_path / "latin_return.py"
    path.write_bytes("# coding: latin-1\nreturn 'Köln'\n".encode("latin-1"))
    source, filename = script.read_file(str(path))
    assert _run(source, filename)["result"] == "Köln"


def test_a_missing_file_is_an_os_error(tmp_path: Path):
    with pytest.raises(OSError):
        script.read_file(str(tmp_path / "nowhere.py"))


# ----- the result -----


@pytest.mark.parametrize(
    ("value", "sent"),
    [(None, None), (3, 3), ({"a": [1, 2]}, {"a": [1, 2]}), ({3}, "{3}")],
    ids=["none", "int", "dict", "set"],
)
def test_a_result_json_cant_hold_is_sent_as_its_str(value: Any, sent: Any):
    assert script.jsonable(value) == sent
