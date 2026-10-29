"""The draw_debug handler against a fake Kit: what it draws, clears and draws again on each update, and that it reads
each drawing interface at its use, so an extension turned off and on again is drawn with through the interface it
gives then, never one it released.

The handler is loaded from its file with Kit's modules faked in sys.modules for each test, as tests/test_mcp_bridge.py
loads its module: the handlers package imports all of Kit.
"""

import asyncio
import importlib.util
import re
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "debug_draw.py"
ISAAC, OMNI = "isaacsim.util.debug_draw", "omni.debugdraw"
OPENED, CLOSING = "OPENED", "CLOSING"
RED, GREEN = (1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)
WIDTH = 2.0


class FakeInterface:
    """A drawing interface that records what it is asked to do."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def draw_lines(self, *args: Any) -> None:
        self.calls.append(("draw_lines", *args))

    def clear_lines(self) -> None:
        self.calls.append(("clear_lines",))


class FakeKit:
    """What the handler reads of Kit: which extensions are on, the stage, the clock, the interface each extension
    gives now (a new one after it is turned off and on again), and how many update subscriptions were made."""

    def __init__(self) -> None:
        self.enabled = {ISAAC: True, OMNI: True}
        self.stage_state = OPENED
        self.stage_id = 1
        self.now = 0.0
        self.isaac = FakeInterface()
        self.omni: FakeInterface | None = FakeInterface()
        self.subscriptions = 0

    def subscribe(self, _callback: Any, name: str) -> SimpleNamespace:
        self.subscriptions += 1
        return SimpleNamespace(name=name)


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def handler(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    manager = SimpleNamespace(is_extension_enabled=lambda name: kit.enabled.get(name, False))
    stream = SimpleNamespace(create_subscription_to_pop=kit.subscribe)
    app = SimpleNamespace(get_extension_manager=lambda: manager, get_update_event_stream=lambda: stream)
    context = SimpleNamespace(get_stage_state=lambda: kit.stage_state, get_stage_id=lambda: kit.stage_id)
    kit_app = _module("omni.kit.app", get_app=lambda: app)
    omni_kit = _module("omni.kit", app=kit_app)
    usd = _module("omni.usd", get_context=lambda: context, StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING))
    simplex = _module("omni.debugdraw._debugDraw", SimplexPoint=SimpleNamespace)
    debugdraw = _module("omni.debugdraw", _debugDraw=simplex, get_debug_draw_interface=lambda: kit.omni)
    isaac = _module(ISAAC, _debug_draw=SimpleNamespace(acquire_debug_draw_interface=lambda: kit.isaac))
    util = _module("isaacsim.util", debug_draw=isaac)
    fakes = {
        "carb": _module("carb", Float3=lambda *v: tuple(v)),
        "omni": _module("omni", kit=omni_kit, usd=usd, debugdraw=debugdraw),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": usd,
        "omni.debugdraw": debugdraw,
        "omni.debugdraw._debugDraw": simplex,
        "isaacsim": _module("isaacsim", util=util),
        "isaacsim.util": util,
        ISAAC: isaac,
        # The handler's package, holding only what it imports from _utils.
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils", enable_extension=lambda name: kit.enabled.get(name, False)
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.debug_draw", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: kit.now))
    return module


def _draw(handler: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(handler.handle_draw_debug(body))


def _update(handler: Any) -> None:
    """One Kit update: the subscription's callback runs while the handler holds one."""
    if handler._drawings.sub is not None:
        handler._on_update(None)


LINE = {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}
SPHERE = {"type": "sphere", "center": [0, 0, 0], "radius": 1.0, "color": [0, 1, 0]}
SPHERE_STARTS = [(-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)]
SPHERE_ENDS = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]


def test_a_line_is_drawn_at_once_and_cleared_after_its_duration(handler, kit):
    r = _draw(handler, **LINE, duration=1.0)
    assert r == {
        "status": "success",
        "result": {
            "drawn": [{"type": "line", "start": [0.0, 0.0, 0.0], "end": [1.0, 0.0, 0.0]}],
            "backend": ISAAC,
            "duration": 1.0,
        },
    }
    assert kit.isaac.calls == [("draw_lines", [(0, 0, 0)], [(1, 0, 0)], [RED], [WIDTH])]
    kit.now = 0.9
    _update(handler)
    assert len(kit.isaac.calls) == 1
    kit.now = 1.0
    _update(handler)
    assert kit.isaac.calls[1:] == [("clear_lines",)]
    assert handler._drawings.sub is None


def test_when_one_drawing_goes_the_rest_are_drawn_again(handler, kit):
    _draw(handler, **LINE, duration=3.0)
    _draw(handler, **SPHERE, duration=1.0)
    assert kit.subscriptions == 1
    kit.now = 1.0
    _update(handler)
    # The clear takes all four lines; the line is drawn again in the same update.
    assert kit.isaac.calls[2:] == [("clear_lines",), ("draw_lines", [(0, 0, 0)], [(1, 0, 0)], [RED], [WIDTH])]
    kit.now = 3.0
    _update(handler)
    assert kit.isaac.calls[4:] == [("clear_lines",)]
    assert handler._drawings.sub is None


def test_an_extension_turned_off_and_on_again_is_drawn_with_through_its_new_interface(handler, kit):
    _draw(handler, **LINE, duration=10.0)
    released = kit.isaac
    kit.isaac = FakeInterface()  # off and on again through manage_extensions: the old interface released
    _draw(handler, **SPHERE, duration=1.0)
    kit.now = 1.0
    _update(handler)
    assert kit.isaac.calls == [
        ("draw_lines", SPHERE_STARTS, SPHERE_ENDS, [GREEN] * 3, [WIDTH] * 3),
        ("clear_lines",),
        ("draw_lines", [(0, 0, 0)], [(1, 0, 0)], [RED], [WIDTH]),
    ]
    assert len(released.calls) == 1  # only the first line, before it was released


def test_while_the_extension_is_off_nothing_is_drawn_or_cleared(handler, kit):
    _draw(handler, **LINE, duration=1.0)
    kit.enabled[ISAAC] = False
    kit.now = 2.0
    _update(handler)
    assert len(kit.isaac.calls) == 1
    assert handler._drawings.sub is None
    assert handler._drawings.backend is None
    # Turned on again, the next call chooses it again and draws through what it gives now.
    kit.enabled[ISAAC] = True
    kit.isaac = FakeInterface()
    assert _draw(handler, **LINE, duration=1.0)["result"]["backend"] == ISAAC
    assert kit.isaac.calls == [("draw_lines", [(0, 0, 0)], [(1, 0, 0)], [RED], [WIDTH])]


def test_omni_debugdraw_draws_every_update_through_the_interface_it_holds_now(handler, kit):
    kit.enabled[ISAAC] = False
    assert _draw(handler, **LINE, duration=1.0)["result"]["backend"] == OMNI
    _update(handler)
    _update(handler)
    assert [call[0] for call in kit.omni.calls] == ["draw_lines", "draw_lines"]
    points = kit.omni.calls[0][1]
    assert [(p.position, p.color, p.width) for p in points] == [
        ((0.0, 0.0, 0.0), 0xFFFF0000, WIDTH),
        ((1.0, 0.0, 0.0), 0xFFFF0000, WIDTH),
    ]
    kit.omni = None  # none held for a moment: nothing drawn, nothing raised
    _update(handler)
    kit.omni = FakeInterface()  # off and on again: the new one draws
    _update(handler)
    assert [call[0] for call in kit.omni.calls] == ["draw_lines"]
    kit.now = 1.0
    _update(handler)
    assert len(kit.omni.calls) == 1
    assert handler._drawings.sub is None


def test_no_drawing_while_the_stage_opens_or_closes(handler, kit):
    kit.stage_state = CLOSING
    r = _draw(handler, **LINE, duration=1.0)
    assert r["status"] == "error"
    assert "No stage is open" in r["error"]
    assert kit.isaac.calls == []
    assert kit.subscriptions == 0


def test_a_clear_owed_while_the_stage_closes_waits_until_it_is_open(handler, kit):
    _draw(handler, **LINE, duration=1.0)
    kit.stage_state = CLOSING
    kit.now = 2.0
    _update(handler)
    assert len(kit.isaac.calls) == 1  # no clear while the stage tears down
    assert handler._drawings.sub is not None
    kit.stage_state = OPENED
    _update(handler)
    assert kit.isaac.calls[1:] == [("clear_lines",)]
    assert handler._drawings.sub is None


def test_a_new_stage_never_gets_the_old_ones_drawing_back(handler, kit):
    _draw(handler, **LINE, duration=30.0)
    kit.stage_id = 2  # new_scene
    _update(handler)
    assert kit.isaac.calls[1:] == [("clear_lines",)]  # cleared, and nothing drawn again
    assert handler._drawings.sub is None


def test_stopping_clears_nothing(handler, kit):
    _draw(handler, **LINE, duration=30.0)
    handler.stop_drawing()
    assert len(kit.isaac.calls) == 1
    assert handler._drawings.sub is None
    assert handler._drawings.backend is None
    assert handler._drawings.book.idle


def test_a_change_of_backend_clears_ours_and_empties_the_book(handler, kit):
    _draw(handler, **LINE, duration=30.0)
    assert handler.choose_backend((OMNI,)) == OMNI
    assert kit.isaac.calls[1:] == [("clear_lines",)]
    assert handler._drawings.book.empty
    assert handler.choose_backend() == ISAAC  # the default back, with nothing of ours to clear
    assert kit.isaac.calls[1:] == [("clear_lines",)]


def test_choose_backend_names_what_it_tried(handler, kit):
    with pytest.raises(ValueError, match=re.escape("Not a drawing backend: omni.invented")):
        handler.choose_backend(("omni.invented",))
    kit.enabled = {}
    with pytest.raises(RuntimeError, match=re.escape(f"none of {ISAAC}, {OMNI}")):
        handler.choose_backend()
    r = _draw(handler, **LINE, duration=1.0)
    assert r["status"] == "error"
    assert ISAAC in r["error"]
    assert OMNI in r["error"]


def test_a_wrong_shape_is_an_error_and_draws_nothing(handler, kit):
    r = _draw(handler, type="box", duration=1.0)
    assert r == {"status": "error", "error": "Unknown shape 'box': one of line, lines, sphere or points"}
    assert kit.isaac.calls == []
