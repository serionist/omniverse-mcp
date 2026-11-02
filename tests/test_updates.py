"""handlers/_updates.py against a fake Kit (#122): the bridge's one way to run code on every app update, an observer of
Kit's update event through Events 2.0; and the guard that keeps the app's deprecated event streams out of the
extension, which Kit logs with a call stack at each call.

The helper is loaded from its file with carb.eventdispatcher and omni.kit.app faked in sys.modules, as the handler
tests load it beside their handler.
"""

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from .conftest import EXTENSION_ROOT, HANDLERS, FakeUpdates, load_updates


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def kit() -> FakeUpdates:
    return FakeUpdates()


@pytest.fixture
def updates(kit: FakeUpdates, monkeypatch: pytest.MonkeyPatch) -> Any:
    dispatcher = _module("carb.eventdispatcher", get_eventdispatcher=lambda: kit)
    kit_app = _module("omni.kit.app", **FakeUpdates.APP)
    omni_kit = _module("omni.kit", app=kit_app)
    fakes = {
        "carb": _module("carb", eventdispatcher=dispatcher),
        "carb.eventdispatcher": dispatcher,
        "omni": _module("omni", kit=omni_kit),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    return load_updates()


def test_an_observer_of_kits_update_event_at_order_0_under_the_bridges_name(updates, kit):
    guard = updates.on_update("recording rec_1", lambda: None)
    (observer,) = kit.observers
    # Order 0: where the app's update stream ran its subscriptions, measured on Isaac Sim 6.2 (#122's P1).
    assert (observer.event_name, observer.order, observer.name) == ("update", 0, "ovmcp.bridge recording rec_1")
    assert guard is not None


def test_the_callback_runs_once_an_update_with_no_argument(updates, kit):
    calls = []
    _guard = updates.on_update("debug draw", lambda: calls.append("called"))
    for _ in range(3):
        kit.update()
    assert calls == ["called"] * 3


def test_a_guard_reset_or_dropped_ends_the_calls(updates, kit):
    calls = {"reset": 0, "dropped": 0, "kept": 0}

    def counter(name: str) -> Any:
        return lambda: calls.__setitem__(name, calls[name] + 1)

    reset = updates.on_update("reset", counter("reset"))
    dropped = updates.on_update("dropped", counter("dropped"))
    _kept = updates.on_update("kept", counter("kept"))
    kit.update()
    reset.reset()
    del dropped
    kit.update()
    kit.update()
    assert calls == {"reset": 1, "dropped": 1, "kept": 3}
    assert kit.names == ["ovmcp.bridge kept"]


def test_a_guard_dropped_inside_its_own_call_ends_the_calls(updates, kit):
    # As the drawings' watch and the render product watch drop theirs once nothing is left.
    held: dict[str, Any] = {"calls": 0}

    def once_twice() -> None:
        held["calls"] += 1
        if held["calls"] == 2:
            held["guard"] = None

    held["guard"] = updates.on_update("self-drop", once_twice)
    for _ in range(5):
        kit.update()
    assert held["calls"] == 2
    assert kit.observers == []


# ----- The guard -----

# The app's event stream getters Kit wraps in carb.deprecated("Use Events 2.0"), which logs a notice with a call stack
# at each call (Kit 110's and Kit 107's omni/kit/app/_impl/__init__.py), but the log stream's: tests/test_logs.py
# refuses that one already, as a Python hook on Kit's logging (#5).
DEPRECATED_STREAMS = (
    "get_pre_update_event_stream",
    "get_update_event_stream",
    "get_post_update_event_stream",
    "get_message_bus_event_stream",
    "get_startup_event_stream",
    "get_shutdown_event_stream",
)


def _streams(data: bytes) -> list[str]:
    """The DEPRECATED_STREAMS that data names."""
    return [name for name in DEPRECATED_STREAMS if name.encode() in data]


def _files(root: Path) -> list[Path]:
    """Every file under root but Python's caches: a .pyc left by a pull, or by Kit 107's Python, can still hold a name
    the code no longer has."""
    return [p for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]


@pytest.mark.parametrize("name", DEPRECATED_STREAMS)
def test_the_guard_finds_each_deprecated_stream(name):
    assert _streams(f"omni.kit.app.get_app().{name}().create_subscription_to_pop(fn)".encode()) == [name]


def test_the_guard_lets_kits_update_event_pass():
    sample = b"observe_event(order=0, event_name=omni.kit.app.GLOBAL_EVENT_UPDATE, on_event=fn, observer_name=n)"
    assert _streams(sample) == []


def test_the_guard_skips_pythons_caches(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "recording.cpython-311.pyc").write_bytes(b"get_update_event_stream")
    (tmp_path / "recording.py").write_bytes(b"on_update(name, callback)")
    assert _files(tmp_path) == [tmp_path / "recording.py"]


def test_the_bridge_uses_no_deprecated_app_event_stream():
    files = _files(EXTENSION_ROOT)
    assert HANDLERS / "_updates.py" in files  # the scan sees the bridge's code
    found = [
        f"{path.relative_to(EXTENSION_ROOT).as_posix()}: {name}"
        for path in files
        for name in _streams(path.read_bytes())
    ]
    assert not found, (
        "Kit logs each call of a deprecated app event stream with a call stack, which get_logs then returns (#122): "
        f"observe Kit's update event with handlers/_updates.py's on_update: {found}"
    )
