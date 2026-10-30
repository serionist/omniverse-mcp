"""The open_scene handler against a fake Kit (#79): the Kit calls its StageKit makes for the core, and one open end to
end through them, the core and a real usd-core stage.

handlers/scene_open.py is loaded from its file with Kit's modules and the recording handler faked in sys.modules, as
tests/test_recording_handler.py loads its handler.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd, UsdGeom

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "scene_open.py"
STATES = SimpleNamespace(OPENED="state.OPENED", OPENING="state.OPENING", CLOSING="state.CLOSING", CLOSED="state.CLOSED")
ROOT = "https://assets.example.invalid/Assets/Isaac/6.2"


class FakeContext:
    """omni.usd's context as the handler calls it. `callback` says what open_stage_with_callback does with its
    callback: "now" calls it before returning, "later" leaves it to the test, "never" refuses without calling."""

    def __init__(self) -> None:
        self.state = STATES.OPENED
        self.current: Usd.Stage | None = Usd.Stage.CreateInMemory()
        self.callback = "now"
        self.answer = (True, "")
        self.started: list[str] = []
        self.pending: list[Any] = []
        self.writable = True

    def get_stage_state(self) -> str:
        return self.state

    def get_stage(self) -> Usd.Stage | None:
        return self.current

    def is_writable(self) -> bool:
        return self.writable

    def open_stage_with_callback(self, url: str, callback: Any) -> bool:
        self.started.append(url)
        if self.callback == "never":
            return False
        if self.answer[0]:
            self.current = Usd.Stage.Open(url)
        if self.callback == "now":
            callback(*self.answer)
        else:
            self.pending.append(callback)
        return self.answer[0] or self.callback != "now"


class FakeTimeline:
    def __init__(self) -> None:
        self.stopped = True
        self.stops = 0

    def is_stopped(self) -> bool:
        return self.stopped

    def stop(self) -> None:
        self.stops += 1
        self.stopped = True


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def context() -> FakeContext:
    return FakeContext()


@pytest.fixture
def timeline() -> FakeTimeline:
    return FakeTimeline()


@pytest.fixture
def stat_results() -> dict[str, str]:
    return {}


@pytest.fixture
def handler(context: FakeContext, timeline: FakeTimeline, stat_results: dict[str, str], monkeypatch) -> Any:
    async def next_update_async() -> None:
        await asyncio.sleep(0)

    async def stat_async(url: str) -> tuple[str, None]:
        return f"Result.{stat_results.get(url, 'OK')}", None

    async def get_assets_root_path_async() -> str:
        return ROOT

    kit_app = _module("omni.kit.app", get_app=lambda: SimpleNamespace(next_update_async=next_update_async))
    omni_kit = _module("omni.kit", app=kit_app)
    usd = _module("omni.usd", get_context=lambda: context, StageState=STATES)
    omni_timeline = _module("omni.timeline", get_timeline_interface=lambda: timeline)
    client = _module("omni.client", stat_async=stat_async)
    fakes = {
        "omni": _module("omni", kit=omni_kit, usd=usd, timeline=omni_timeline, client=client),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.timeline": omni_timeline,
        "omni.usd": usd,
        "omni.client": client,
        "isaacsim": _module("isaacsim", __path__=[]),
        "isaacsim.storage": _module("isaacsim.storage", __path__=[]),
        "isaacsim.storage.native": _module(
            "isaacsim.storage.native", get_assets_root_path_async=get_assets_root_path_async
        ),
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test.recording": _module("handlers_under_test.recording", recording_note=lambda: "a note"),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.scene_open", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scene(path: Path) -> str:
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdGeom.Xform.Define(stage, "/World")
    stage.GetRootLayer().Save()
    return str(path)


async def _started(handler: Any, url: str) -> tuple[Any, "asyncio.Future[tuple[bool, str]]"]:
    kit = handler._Kit()
    return kit, kit.start_open(url)


def test_the_open_starts_before_start_open_returns_and_takes_kit_s_answer_once(handler, context, tmp_path):
    context.callback = "later"
    url = _scene(tmp_path / "room.usda")

    async def run() -> tuple[bool, str]:
        _kit, future = await _started(handler, url)
        assert context.started == [url]
        assert not future.done()
        context.pending[0](True, "")
        context.pending[0](False, "a second answer")
        return await future

    assert asyncio.run(run()) == (True, "")


def test_a_busy_kit_s_answer_during_the_start_reaches_the_core(handler, context):
    context.answer = (False, "UsdContext busy")

    async def run() -> tuple[bool, str]:
        _kit, future = await _started(handler, "C:/Scenes/Room.usd")
        return await future

    assert asyncio.run(run()) == (False, "UsdContext busy")


def test_a_start_kit_refuses_without_an_answer_fails_at_once(handler, context):
    context.callback = "never"

    async def run() -> tuple[bool, str]:
        _kit, future = await _started(handler, "C:/Scenes/Room.usd")
        assert future.done()
        return await future

    assert asyncio.run(run()) == (False, "Kit didn't start the open")


def test_the_state_and_the_stat_are_named_as_the_core_reads_them(handler, context, stat_results):
    stat_results["https://example.invalid/missing.usd"] = "ERROR_NOT_FOUND"
    kit = handler._Kit()
    for state, name in ((STATES.OPENED, "OPENED"), (STATES.CLOSING, "CLOSING"), (STATES.CLOSED, "CLOSED")):
        context.state = state
        assert kit.state() == name
    assert asyncio.run(kit.stat("https://example.invalid/missing.usd")) == "ERROR_NOT_FOUND"
    assert asyncio.run(kit.stat("https://example.invalid/room.usd")) == "OK"


def test_the_asset_root_comes_from_isaac_sim_s_async_lookup(handler):
    assert asyncio.run(handler._Kit().assets_root()) == ROOT


def test_a_kit_app_without_isaac_sim_s_library_has_no_root(handler, monkeypatch):
    monkeypatch.setitem(sys.modules, "isaacsim.storage.native", None)
    assert asyncio.run(handler._Kit().assets_root()) is None


def test_stop_timeline_stops_it_and_says_whether_it_ran(handler, timeline):
    kit = handler._Kit()
    timeline.stopped = False
    assert kit.stop_timeline() is True
    assert kit.stop_timeline() is False
    assert timeline.stops == 2


def test_a_file_opens_end_to_end_through_kit_s_calls(handler, context, timeline, tmp_path):
    timeline.stopped = False
    url = _scene(tmp_path / "room.usda")
    r = asyncio.run(handler.handle_open_scene({"file_path": url}))
    assert r["status"] == "success", r
    result = r["result"]
    assert result["file_path"] == url
    assert context.started == [url]
    assert result["replaced"] == "an unsaved stage"
    assert result["up_axis"] == "Z"
    assert result["stopped"] is True
    assert result["writable"] is True
    assert result["recording_note"] == "a note"
