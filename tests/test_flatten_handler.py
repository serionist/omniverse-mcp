"""The flatten_usd and export_prim_as_file handlers against a usd-core stage in Kit's light mode Default (#118): the
file leaves out Kit's session layer, its light rig and its hiding of the stage's own light, keeps the open stage's
unsaved edits, and the open stage stays as it was.

handlers/usd_advanced.py is loaded from its file with the handlers' _utils faked in sys.modules, as
tests/test_scene_save_handler.py loads its handler.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdLux, UsdShade

from .conftest import EXTENSION_ROOT
from .test_layers import RIG, SUN, kits_default_mode

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "usd_advanced.py"
CAMERA = "/OmniverseKit_Persp"  # one of Kit's own cameras, which Kit defines in the session layer
UNSAVED = "/World/Unsaved"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    """scene.usda: /World with a light, /World/Sun, and a cube bound to /Looks/Mat, a material outside /World."""
    path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(path))
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/World").GetPrim())
    UsdLux.DistantLight.Define(stage, SUN)
    cube = UsdGeom.Cube.Define(stage, "/World/Box").GetPrim()
    material = UsdShade.Material.Define(stage, "/Looks/Mat")
    UsdShade.MaterialBindingAPI.Apply(cube).Bind(material)
    stage.GetRootLayer().Save()
    return path


@pytest.fixture
def stage(scene: Path) -> Usd.Stage:
    """scene.usda as the open stage in Kit's mode Default, with Kit's camera, and an edit it hasn't saved."""
    opened = Usd.Stage.Open(str(scene))
    kits_default_mode(opened, scene.parent / "Default.usda")
    with Usd.EditContext(opened, opened.GetSessionLayer()):
        UsdGeom.Camera.Define(opened, CAMERA)
    opened.DefinePrim(UNSAVED)
    return opened


@pytest.fixture
def handler(stage: Usd.Stage, monkeypatch: pytest.MonkeyPatch) -> Any:
    async def next_update() -> None:
        await asyncio.sleep(0)

    fakes = {
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            _collect_materials=None,
            _compute_mesh_stats=None,
            _get_stage=lambda: stage,
            _next_update=next_update,
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.usd_advanced", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as_it_is(stage: Usd.Stage) -> dict[str, Any]:
    """What a flatten must leave of the open stage: its session and root layers, their unsaved edits, the rig and the
    hidden light."""
    return {
        "session": stage.GetSessionLayer().ExportToString(),
        "root": stage.GetRootLayer().ExportToString(),
        "dirty": stage.GetRootLayer().dirty,
        "rig": bool(stage.GetPrimAtPath(f"{RIG}/Lights/DomeLight")),
        "sun": UsdGeom.Imageable(stage.GetPrimAtPath(SUN)).ComputeVisibility(),
    }


def _assert_without_session(path: Path, *, sun: str = SUN, unsaved: str = UNSAVED) -> Sdf.Layer:
    """The file at path has no rig, no Kit camera and no visibility on the stage's light; it has the unsaved edit."""
    layer = Sdf.Layer.OpenAsAnonymous(str(path))
    assert layer is not None, path
    text = layer.ExportToString()
    assert "OmniKit_Viewport_LightRig" not in text
    assert "OmniverseKit_Persp" not in text
    assert layer.GetPrimAtPath(sun), "the stage's own light is missing"
    assert not layer.GetPropertyAtPath(f"{sun}.visibility"), "Kit's hiding of the stage's light was written"
    assert layer.GetPrimAtPath(unsaved), "the open stage's unsaved edit is missing"
    return layer


def test_a_flatten_of_the_open_stage_leaves_out_kits_session_layer(handler, stage: Usd.Stage, scene: Path):
    before = _as_it_is(stage)
    out = scene.parent / "flat.usda"
    r = asyncio.run(handler.handle_flatten_usd({"output_path": str(out)}))
    assert r["status"] == "success", r
    assert Path(r["result"]["input_path"]).samefile(scene)
    _assert_without_session(out)
    assert _as_it_is(stage) == before


def test_a_flatten_of_the_open_stages_own_file_leaves_out_kits_session_layer(handler, stage: Usd.Stage, scene: Path):
    # An input is opened as a stage of its own, with an empty session layer: Kit's was never in it.
    before = _as_it_is(stage)
    out = scene.parent / "flat.usda"
    r = asyncio.run(handler.handle_flatten_usd({"output_path": str(out), "input_path": str(scene)}))
    assert r["status"] == "success", r
    _assert_without_session(out)
    assert _as_it_is(stage) == before


def test_an_export_leaves_out_kits_session_layer(handler, stage: Usd.Stage, scene: Path):
    before = _as_it_is(stage)
    out = scene.parent / "world.usda"
    r = asyncio.run(handler.handle_export_prim({"prim_path": "/World", "output_path": str(out)}))
    assert r["status"] == "success", r
    assert r["result"]["materials_included"] == 1
    layer = _assert_without_session(out)
    assert layer.GetPrimAtPath("/Looks/Mat")
    assert _as_it_is(stage) == before


@pytest.mark.parametrize("prim_path", [RIG, f"{RIG}/Lights/DomeLight", CAMERA])
def test_an_export_of_a_prim_from_kits_session_layer_is_refused(handler, stage: Usd.Stage, scene: Path, prim_path: str):
    out = scene.parent / "kit.usda"
    r = asyncio.run(handler.handle_export_prim({"prim_path": prim_path, "output_path": str(out)}))
    assert r["status"] == "error", r
    assert "comes from Kit's session layer" in r["error"]
    assert not out.exists()


def test_an_export_of_the_rigs_over_alone_is_refused(handler, stage: Usd.Stage, scene: Path):
    # Modes stage, camera and off clear the over's references and leave the over (#117's plan, K3): a prim, undefined.
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.GetPrimAtPath(RIG).GetReferences().ClearReferences()
    assert stage.GetPrimAtPath(RIG)
    assert not stage.GetPrimAtPath(RIG).IsDefined()
    r = asyncio.run(handler.handle_export_prim({"prim_path": RIG, "output_path": str(scene.parent / "kit.usda")}))
    assert r["status"] == "error", r
    assert "comes from Kit's session layer" in r["error"]
