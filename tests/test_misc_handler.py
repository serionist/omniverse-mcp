"""/health against a fake Kit: handlers/misc.py loaded from its file, as tests/test_force_handler.py loads
handlers/simulation.py, on a usd-core stage. It reports the Kit app beside the protocol and the extension's version,
for people (#105)."""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd

from ovmcp.core import protocol

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "misc.py"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def misc(monkeypatch: pytest.MonkeyPatch) -> Any:
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
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.misc", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
