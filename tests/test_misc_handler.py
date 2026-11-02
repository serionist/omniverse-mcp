"""/health and /execute against a fake Kit: handlers/misc.py loaded from its file, as tests/test_force_handler.py loads
handlers/simulation.py, on a usd-core stage. /health reports the Kit app beside the protocol and the extension's
version, for people (#105). /execute runs a script, plain or awaiting, and gives its result, stdout and stderr, or its
error with the traceback (#158's P6: these held for the handler before its move onto ovmcp.core.script and output)."""

import asyncio
import importlib.util
import sys
from collections.abc import Iterator
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd

from ovmcp.core import protocol

from .conftest import EXTENSION_ROOT, reset_output

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "misc.py"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


class FakeMcp:
    """The `mcp` a script gets, with one handler: its answer, after a turn of the loop as a real handler awaits Kit."""

    async def sim_state(self) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"status": "success", "result": {"state": "stopped"}}


@pytest.fixture
def misc(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    stage = Usd.Stage.CreateInMemory()

    async def next_update() -> None:
        await asyncio.sleep(0)

    kit_app = _module("omni.kit.app", get_app=lambda: SimpleNamespace(get_extension_manager=lambda: None))
    omni_kit = _module("omni.kit", app=kit_app)
    fakes = {
        "carb": _module("carb"),
        "omni": _module("omni", kit=omni_kit),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils", _get_stage=lambda: stage, _next_update=next_update
        ),
        "handlers_under_test.recording": _module("handlers_under_test.recording", recording_active=lambda: False),
        "handlers_under_test._mcp_bridge": _module("handlers_under_test._mcp_bridge", mcp_bridge=FakeMcp()),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.misc", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    reset_output()


def test_health_reports_the_kit_app_beside_the_protocol(misc, monkeypatch):
    facts = {
        "kit_app_name": "Isaac-Sim Python",
        "kit_app_version": "6.2.0",
        "kit_version": "110.4.0+feature.386251.187cf21b.gl",
        "kit_os": "Windows-11-10.0.26300-SP0",
    }
    monkeypatch.setattr(protocol, "_kit_app", facts)

    r = asyncio.run(misc.handle_health({}))

    assert r["status"] == "success", r
    assert {key: r["result"][key] for key in facts} == facts
    assert r["result"]["protocol"] == protocol.PROTOCOL
    assert r["result"]["stage_path"] == "(unsaved)"


# ----- /execute -----


def _execute(misc: Any, code: str) -> dict[str, Any]:
    return asyncio.run(misc.handle_execute({"code": code}))


def test_a_plain_script_gives_its_result_and_stdout(misc):
    r = _execute(misc, "print('hi')\nresult = {'answer': 42}")

    assert r == {"status": "success", "result": {"stdout": "hi\n", "stderr": "", "return_value": {"answer": 42}}}


def test_stderr_comes_back_apart_from_stdout(misc):
    r = _execute(misc, "import sys\nprint('out')\nprint('err', file=sys.stderr)")

    assert (r["result"]["stdout"], r["result"]["stderr"]) == ("out\n", "err\n")


def test_an_awaiting_script_awaits_mcp_and_gives_its_result(misc):
    r = _execute(misc, "state = await mcp.sim_state()\nprint(state['result']['state'])\nresult = state['result']")

    assert r["status"] == "success", r
    assert r["result"]["return_value"] == {"state": "stopped"}
    assert r["result"]["stdout"] == "stopped\n"


def test_the_namespace_holds_kit_usd_and_mcp(misc):
    names = ("omni", "carb", "Usd", "UsdGeom", "UsdLux", "UsdPhysics", "Sdf", "Gf", "mcp")
    r = _execute(misc, f"result = [name for name in {names!r} if name in globals()]")

    assert r["result"]["return_value"] == list(names)


def test_a_result_json_cant_hold_comes_back_as_its_str(misc):
    r = _execute(misc, "result = {3}")

    assert r["result"]["return_value"] == "{3}"


def test_no_result_returns_none(misc):
    assert _execute(misc, "x = 1")["result"]["return_value"] is None


def test_a_top_level_return_still_runs_and_returns(misc):
    # The wrapper ran it, which PyCF_ALLOW_TOP_LEVEL_AWAIT refuses (#158's P2).
    r = _execute(misc, "print('before')\nreturn 7")

    assert r["status"] == "success", r
    assert (r["result"]["return_value"], r["result"]["stdout"]) == (7, "before\n")


def test_an_error_gives_its_message_its_traceback_line_and_the_output_before_it(misc):
    r = _execute(misc, "print('started')\nx = 1\nraise ValueError('the bake went wrong')")

    assert r["status"] == "error"
    assert r["error"] == "the bake went wrong"
    assert 'File "<string>", line 3, in <module>' in r["traceback"]
    assert r["stdout"] == "started\n"


def test_a_syntax_error_is_an_error_naming_its_line(misc):
    r = _execute(misc, "x = 1\nx = = 2")

    assert r["status"] == "error"
    assert "line 2" in r["error"]


def test_sys_exit_is_refused_as_an_error(misc):
    r = _execute(misc, "import sys\nsys.exit(3)")

    assert r["status"] == "error"
    assert r["error"] == "Script called sys.exit(3). This is not allowed."


@pytest.mark.parametrize("code", ["", "   \n"])
def test_no_code_is_an_error(misc, code):
    assert _execute(misc, code) == {"status": "error", "error": "No code provided"}


# ----- /execute on the shared compiler and the output router (#158) -----


def test_an_awaiting_script_s_traceback_names_its_own_line(misc):
    # The old wrapper's line came one after the script's.
    r = _execute(misc, "import asyncio\nawait asyncio.sleep(0)\nraise ValueError('late')")

    assert r["status"] == "error"
    assert 'File "<string>", line 3, in <module>' in r["traceback"]


def test_a_multi_line_string_in_an_awaiting_script_is_kept_whole(misc):
    # The old wrapper indented each of the script's lines, a string's own included.
    r = _execute(misc, 'await mcp.sim_state()\nresult = """first\nsecond"""')

    assert r["result"]["return_value"] == "first\nsecond"


def test_two_calls_at_once_each_get_their_own_output(misc):
    # The old swap of sys.stdout was global: what one call printed while the other awaited landed in either.
    code = "for i in range(3):\n    print('{name}', i)\n    await mcp.sim_state()\nresult = '{name}'"

    async def both() -> list[dict[str, Any]]:
        calls = [misc.handle_execute({"code": code.format(name=name)}) for name in ("first", "second")]
        return list(await asyncio.gather(*calls))

    first, second = asyncio.run(both())

    assert first["result"]["stdout"] == "first 0\nfirst 1\nfirst 2\n"
    assert second["result"]["stdout"] == "second 0\nsecond 1\nsecond 2\n"


@pytest.mark.parametrize("stream", ["io.StringIO()", "sys.__stdout__"])
def test_a_script_that_replaces_sys_stdout_leaves_the_router_in_place(misc, stream):
    # The old handler's finally put Kit's stream back. Left in place, the replacement took what Kit itself printed, and
    # the next call's router went over it rather than over Kit's stream.
    _execute(misc, "print('first')")
    routers = (sys.stdout, sys.stderr)
    _execute(misc, f"import io, sys\nsys.stdout = {stream}\nsys.stderr = {stream}\nprint('gone')")

    assert (sys.stdout, sys.stderr) == routers
    later = _execute(misc, "import sys\nprint('seen')\nprint('noted', file=sys.stderr)")
    assert (later["result"]["stdout"], later["result"]["stderr"]) == ("seen\n", "noted\n")
