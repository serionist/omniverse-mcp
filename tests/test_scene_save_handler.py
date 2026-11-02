"""The save_scene handler against a usd-core stage (#85): a file_path that names another layer of the open stage is
refused with nothing written, the stage's own file is saved whatever names it, and a layer Kit holds for the path is
read again after the write. The kept capture feed is released first, and the lock held through the write (#114).

handlers/scene.py is loaded from its file with Kit's modules and the handlers' _utils faked in sys.modules, as
tests/test_recording_handler.py loads its handler.
"""

import asyncio
import contextlib
import importlib.util
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pxr import Sdf, Usd

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "scene.py"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _file(path: Path, prim: str) -> Path:
    layer = Sdf.Layer.CreateAnonymous(".usda")
    Sdf.CreatePrimInLayer(layer, prim)
    assert layer.Export(str(path))
    return path


class KeptFeed:
    """camera_feed.without_kept_feed as a route sees it: what the route did while it held the viewport lock with no
    capture feed kept, and whether its file was written by the time it let the lock go (#114)."""

    def __init__(self) -> None:
        self.log: list[Any] = []
        self.written: Callable[[], bool] = lambda: False

    @contextlib.asynccontextmanager
    async def without_kept_feed(self) -> AsyncIterator[None]:
        self.log.append("lock taken, feed released")
        yield
        self.log.append(("lock let go, file written", self.written()))


@pytest.fixture
def kept() -> KeptFeed:
    return KeptFeed()


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    """scene.usda: /World over the sublayer sub.usda. Beside it, other.usda, which the stage doesn't use."""
    _file(tmp_path / "sub.usda", "/Sub")
    _file(tmp_path / "other.usda", "/Other")
    path = _file(tmp_path / "scene.usda", "/World")
    layer = Sdf.Layer.FindOrOpen(str(path))
    layer.subLayerPaths.append("./sub.usda")
    layer.Save()
    return path


@pytest.fixture
def stage(scene: Path) -> Usd.Stage:
    """scene.usda as the open stage, with an edit it hasn't saved."""
    opened = Usd.Stage.Open(str(scene))
    opened.DefinePrim("/World/Unsaved")
    return opened


@pytest.fixture
def handler(stage: Usd.Stage, kept: KeptFeed, monkeypatch: pytest.MonkeyPatch) -> Any:
    async def next_update() -> None:
        await asyncio.sleep(0)

    kit_app = _module("omni.kit.app")
    omni_kit = _module("omni.kit", app=kit_app)
    usd = _module("omni.usd")
    fakes = {
        "omni": _module("omni", kit=omni_kit, usd=usd),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": usd,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            _compute_mesh_stats=None,
            _first_missing=None,
            _get_stage=lambda: stage,
            _next_update=next_update,
            _physics_exponents=None,
            _serialize_value=None,
        ),
        "handlers_under_test.camera_feed": _module(
            "handlers_under_test.camera_feed", without_kept_feed=kept.without_kept_feed
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.scene", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _save(handler: Any, file_path: str = "") -> dict[str, Any]:
    return asyncio.run(handler.handle_save_scene({"file_path": file_path} if file_path else {}))


def test_a_save_over_a_sublayer_is_refused_and_writes_nothing(handler, stage: Usd.Stage, scene: Path):
    sub = scene.parent / "sub.usda"
    before = sub.read_bytes()
    r = _save(handler, str(sub))
    assert r["status"] == "error", r
    assert "a sublayer of the open stage" in r["error"]
    assert sub.read_bytes() == before
    assert stage.GetPrimAtPath("/Sub")
    assert stage.GetRootLayer().dirty, "the open stage lost its unsaved edit"


def test_a_save_over_the_stages_own_file_by_another_spelling_writes_it(
    handler, stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch
):
    # Relative, so another spelling than the layer's on every system: forward slashes are the same one on Linux.
    monkeypatch.chdir(scene.parent)
    r = _save(handler, scene.name)
    assert r["status"] == "success", r
    assert r["result"]["action"] == "save_as"
    assert Sdf.Layer.OpenAsAnonymous(str(scene)).GetPrimAtPath("/World/Unsaved")
    assert stage.GetPrimAtPath("/World/Unsaved")


def test_a_layer_kit_holds_for_the_path_is_read_again_after_the_save(handler, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    r = _save(handler, str(other))
    assert r["status"] == "success", r
    assert held.GetPrimAtPath("/World/Unsaved"), "the held layer still has the file's content from before the save"
    assert not held.GetPrimAtPath("/Other")


def test_a_layer_kit_holds_for_the_path_with_unsaved_edits_is_refused(handler, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    Sdf.CreatePrimInLayer(held, "/Edit")
    before = other.read_bytes()
    r = _save(handler, str(other))
    assert r["status"] == "error", r
    assert "unsaved edits" in r["error"]
    assert other.read_bytes() == before
    assert held.GetPrimAtPath("/Edit")


def test_a_save_without_a_file_path_saves_the_stages_own_file(handler, stage: Usd.Stage, scene: Path):
    r = _save(handler)
    assert r["status"] == "success", r
    assert r["result"]["action"] == "save"
    assert Path(r["result"]["file_path"]).samefile(scene)
    assert not stage.GetRootLayer().dirty
    assert Sdf.Layer.OpenAsAnonymous(str(scene)).GetPrimAtPath("/World/Unsaved")


@pytest.mark.parametrize("as_new", [True, False], ids=["save-as", "save"])
def test_a_save_releases_the_kept_capture_feed_first_and_holds_the_lock_through_its_write(
    handler, kept: KeptFeed, scene: Path, as_new: bool
):
    # Kit keeps the feed's render product in the root layer, which a save writes; a capture between the release and
    # the write would make another.
    out = scene.parent / "saved.usda" if as_new else scene

    def written() -> bool:
        layer = Sdf.Layer.OpenAsAnonymous(str(out))  # held: a layer no one holds is gone before it is read
        return bool(layer and layer.GetPrimAtPath("/World/Unsaved"))

    kept.written = written
    r = _save(handler, str(out) if as_new else "")
    assert r["status"] == "success", r
    assert kept.log == ["lock taken, feed released", ("lock let go, file written", True)]


@pytest.mark.parametrize("as_new", [True, False], ids=["save-as", "save"])
def test_a_save_names_the_session_layers_variant_selections_it_leaves_out(
    handler, stage: Usd.Stage, scene: Path, as_new: bool
):
    # A selection switched for a check stays out of the file; an agent that meant to keep it learns at the save (#155).
    look = stage.GetPrimAtPath("/World").GetVariantSets().AddVariantSet("look")
    for name in ("red", "blue"):
        look.AddVariant(name)
    look.SetVariantSelection("red")
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        look.SetVariantSelection("blue")

    r = _save(handler, str(scene.parent / "saved.usda") if as_new else "")

    assert r["status"] == "success", r
    assert r["result"]["session_selections"] == ["/World look=blue"]


def test_a_save_with_no_session_selection_names_none(handler):
    r = _save(handler)

    assert r["status"] == "success", r
    assert r["result"]["session_selections"] == []
