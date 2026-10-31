"""The scene handlers against a fake Kit, on a usd-core stage (#82): each answer says what the stage now holds.

handlers/scene.py is loaded from its file with Kit's modules faked in sys.modules, and its _utils.py from its own file
beside it, as tests/test_camera_handler.py and tests/test_camera_feed.py load theirs. The Kit-free core is the real one.
"""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from .conftest import EXTENSION_ROOT

HANDLERS = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


async def _nothing(*_args: Any, **_kwargs: Any) -> None:
    pass


class FakeKit:
    """The stage the handlers read through omni.usd."""

    def __init__(self) -> None:
        self.stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(self.stage, "/World")


def load_handler(name: str, kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    """handlers/<name>.py with Kit faked, its relative imports read from the handlers folder."""
    settings = SimpleNamespace(get=lambda _key: None, set=lambda *_a: None, set_bool=lambda *_a: None)
    context = SimpleNamespace(get_stage=lambda: kit.stage, get_stage_id=lambda: 1)
    kit_app = _module("omni.kit.app", get_app=lambda: SimpleNamespace(next_update_async=_nothing))
    omni_kit = _module("omni.kit", app=kit_app)
    usd = _module("omni.usd", get_context=lambda: context)
    fakes = {
        "carb": _module(
            "carb",
            log_warn=lambda _m: None,
            log_info=lambda _m: None,
            settings=SimpleNamespace(get_settings=lambda: settings),
        ),
        "omni": _module("omni", kit=omni_kit, usd=usd),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": usd,
        "handlers_under_test": _module("handlers_under_test", __path__=[str(HANDLERS)]),
    }
    for module_name, module in fakes.items():
        monkeypatch.setitem(sys.modules, module_name, module)
    # The handlers' _utils, loaded afresh for each test with the fakes above.
    monkeypatch.delitem(sys.modules, "handlers_under_test._utils", raising=False)
    spec = importlib.util.spec_from_file_location(f"handlers_under_test.{name}", HANDLERS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def scene(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler("scene", kit, monkeypatch)


def _run(handler: Any, name: str, **body: Any) -> dict[str, Any]:
    return asyncio.run(getattr(handler, name)(body))


def _ops(prim: Usd.Prim) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()]


def _world(prim: Usd.Prim) -> Gf.Vec3d:
    return UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()


def _pivoted(stage: Usd.Stage, path: str) -> Usd.Prim:
    xf = UsdGeom.Xform.Define(stage, path)
    common = UsdGeom.XformCommonAPI(xf)
    common.SetTranslate(Gf.Vec3d(1, 0, 0))
    common.SetPivot(Gf.Vec3f(0, 5, 0))
    common.SetRotate(Gf.Vec3f(0, 0, 90))
    return xf.GetPrim()


def _matrix_placed(stage: Usd.Stage, path: str) -> tuple[Usd.Prim, Gf.Matrix4d]:
    placed = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d.ZAxis(), 30)) * Gf.Matrix4d().SetTranslate(Gf.Vec3d(1, 2, 3))
    xf = UsdGeom.Xform.Define(stage, path)
    xf.AddTransformOp().Set(placed)
    return xf.GetPrim(), placed


# ---- set_prim_transform (R7) ----


def test_set_prim_transform_keeps_a_pivot_and_puts_the_position_in_the_translate_op(scene, kit):
    # 0.2.3 read the inverse pivot as the position and dropped the pivot.
    prim = _pivoted(kit.stage, "/World/P")
    before = _ops(prim)

    r = _run(scene, "handle_transform", prim_path="/World/P", position=[4, 0, 0])

    assert r["status"] == "success", r
    assert _ops(prim) == before
    assert prim.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(4, 0, 0)
    assert prim.GetAttribute("xformOp:translate:pivot").Get() == Gf.Vec3f(0, 5, 0)


def test_set_prim_transform_keeps_a_matrix_placed_prims_matrix(scene, kit):
    # 0.2.3 dropped the matrix op, and with it the prim's placement.
    prim, placed = _matrix_placed(kit.stage, "/World/M")

    r = _run(scene, "handle_transform", prim_path="/World/M", position=[5, 6, 7])

    assert r["status"] == "success", r
    assert _ops(prim) == ["xformOp:transform"]
    matrix = prim.GetAttribute("xformOp:transform").Get()
    assert matrix.ExtractTranslation() == Gf.Vec3d(5, 6, 7)
    assert Gf.IsClose(matrix.ExtractRotationMatrix(), placed.ExtractRotationMatrix(), 1e-9)


def test_set_prim_transform_keeps_reset_xform_stack(scene, kit):
    xf = UsdGeom.Xform.Define(kit.stage, "/World/R")
    xf.SetResetXformStack(True)

    r = _run(scene, "handle_transform", prim_path="/World/R", scale=2)

    assert r["status"] == "success", r
    assert xf.GetResetXformStack()


@pytest.mark.parametrize(
    ("body", "says"),
    [({"rotation": [0, 90]}, "rotation must be"), ({"position": [1, 2]}, "position must be")],
)
def test_set_prim_transform_refuses_what_it_cant_show(scene, kit, body, says):
    # 0.2.3 ignored a two-number rotation and answered "Transform updated".
    UsdGeom.Xform.Define(kit.stage, "/World/P")

    r = _run(scene, "handle_transform", prim_path="/World/P", **body)

    assert r["status"] == "error"
    assert says in r["error"]
    assert _ops(kit.stage.GetPrimAtPath("/World/P")) == []


def test_set_prim_transform_refuses_an_animated_op(scene, kit):
    xf = UsdGeom.Xform.Define(kit.stage, "/World/P")
    xf.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)

    r = _run(scene, "handle_transform", prim_path="/World/P", position=[5, 5, 5])

    assert r["status"] == "error"
    assert "animated" in r["error"]


# ---- create_prim (R7, round 1's P5) ----


def test_create_prim_with_a_malformed_rotation_makes_no_prim(scene, kit):
    r = _run(scene, "handle_create_prim", prim_path="/World/New/Cube", prim_type="Cube", rotation=[0, 90])

    assert r["status"] == "error"
    assert "rotation must be" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/New").IsValid()


def test_create_prim_places_a_new_prim(scene, kit):
    r = _run(scene, "handle_create_prim", prim_path="/World/Cube", prim_type="Cube", position=[1, 2, 3], scale=0.5)

    assert r["status"] == "success", r
    prim = kit.stage.GetPrimAtPath("/World/Cube")
    assert _ops(prim) == ["xformOp:translate", "xformOp:scale"]
    assert _world(prim) == Gf.Vec3d(1, 2, 3)


def test_create_prim_that_refuses_once_made_takes_away_what_it_made(scene, kit):
    # An animated root op in the referenced file is found only once the prim is there.
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Bot").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)
    held.SetDefaultPrim(held.GetPrimAtPath("/Bot"))

    r = _run(scene, "handle_create_prim", prim_path="/World/Group/Bot", usd_path=asset.identifier, position=[5, 5, 5])

    assert r["status"] == "error"
    assert "Nothing was created" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Group").IsValid()


def test_create_prim_without_a_transform_leaves_a_prim_without_one(scene, kit):
    # A material has no transform: nothing is checked when none is given.
    r = _run(scene, "handle_create_prim", prim_path="/World/Looks/Mat", prim_type="Material")
    assert r["status"] == "success", r


# ---- clone_prim (R8) ----


def test_clone_prim_offsets_a_matrix_placed_sources_copies_and_keeps_their_matrix(scene, kit):
    _prim, placed = _matrix_placed(kit.stage, "/World/M")

    r = _run(scene, "handle_clone_prim", source_path="/World/M", target_path="/World/Row", count=3, offset=[2, 0, 0])

    assert r["status"] == "success", r
    for n, path in enumerate(r["result"]["clones"]):
        copy = kit.stage.GetPrimAtPath(path)
        assert _ops(copy) == ["xformOp:transform"]
        assert _world(copy) == placed.ExtractTranslation() + Gf.Vec3d(2 * n, 0, 0)


def test_clone_prim_offsets_a_pivoted_sources_copies_from_its_position(scene, kit):
    # 0.2.3 counted from the first translate op, which can be a pivot.
    prim = _pivoted(kit.stage, "/World/P")
    start = _world(prim)

    r = _run(scene, "handle_clone_prim", source_path="/World/P", target_path="/World/Row", count=2, offset=[0, 0, 3])

    assert r["status"] == "success", r
    second = kit.stage.GetPrimAtPath("/World/Row_002")
    assert _ops(second) == _ops(prim)
    assert _world(second) == start + Gf.Vec3d(0, 0, 3)


def test_a_single_clone_with_an_offset_is_left_as_copied(scene, kit):
    # 0.2.3 moved it by zero, and rewrote its ops on the way.
    _prim, placed = _matrix_placed(kit.stage, "/World/M")

    r = _run(scene, "handle_clone_prim", source_path="/World/M", target_path="/World/One", offset=[2, 0, 0])

    assert r["status"] == "success", r
    copy = kit.stage.GetPrimAtPath("/World/One")
    assert _ops(copy) == ["xformOp:transform"]
    assert copy.GetAttribute("xformOp:transform").Get() == placed


def test_clone_prim_moves_its_copies_in_the_root_layer_with_a_sublayer_as_the_edit_target(scene, kit):
    # The copies are in the root layer; moving them in the sublayer would be refused as hidden (round 1's P6).
    UsdGeom.Xform.Define(kit.stage, "/World/A").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
    sub = Sdf.Layer.CreateAnonymous("sub.usda")
    kit.stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    kit.stage.SetEditTarget(Usd.EditTarget(sub))

    r = _run(scene, "handle_clone_prim", source_path="/World/A", target_path="/World/Row", count=2, offset=[0, 1, 0])

    assert r["status"] == "success", r
    assert _world(kit.stage.GetPrimAtPath("/World/Row_002")) == Gf.Vec3d(1, 1, 0)
    assert not sub.GetPrimAtPath("/World/Row_002")


def test_clone_prim_with_an_animated_source_copies_nothing(scene, kit):
    UsdGeom.Xform.Define(kit.stage, "/World/A").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)

    r = _run(scene, "handle_clone_prim", source_path="/World/A", target_path="/World/Row", count=2, offset=[0, 1, 0])

    assert r["status"] == "error"
    assert "Nothing was copied" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Row_001").IsValid()


def test_clone_prim_refuses_a_malformed_offset(scene, kit):
    UsdGeom.Xform.Define(kit.stage, "/World/A")
    r = _run(scene, "handle_clone_prim", source_path="/World/A", target_path="/World/Row", count=2, offset=[1, 2])
    assert r["status"] == "error"
    assert "offset must be" in r["error"]
