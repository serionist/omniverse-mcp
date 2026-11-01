"""The scene handlers against a fake Kit, on a usd-core stage (#82): each answer says what the stage now holds.

handlers/scene.py is loaded from its file with Kit's modules faked in sys.modules, and its _utils.py from its own file
beside it, as tests/test_camera_handler.py and tests/test_camera_feed.py load theirs. The Kit-free core is the real one.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

from ovmcp.core.usd import floats

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


# ---- set_prim_transform ----


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


# ---- create_prim ----


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


def test_create_prim_over_a_prim_that_was_there_keeps_no_reference_it_refused(scene, kit):
    # Only a prim the call made was taken away, so each retry stacked another reference.
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Bot").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)
    held.SetDefaultPrim(held.GetPrimAtPath("/Bot"))
    kit.stage.DefinePrim("/World/Bot", "Xform")
    body = {"prim_path": "/World/Bot", "usd_path": asset.identifier, "position": [5, 5, 5]}

    for _ in range(2):
        r = _run(scene, "handle_create_prim", **body)
        assert r["status"] == "error"
        assert r["error"].endswith(". The reference was not added")
        spec = kit.stage.GetRootLayer().GetPrimAtPath("/World/Bot")
        assert not spec.referenceList.GetAddedOrExplicitItems()


def test_create_prim_that_refuses_keeps_a_reference_the_prim_already_held(scene, kit):
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Bot").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)
    held.SetDefaultPrim(held.GetPrimAtPath("/Bot"))
    kit.stage.DefinePrim("/World/Bot", "Xform").GetReferences().AddReference(asset.identifier)

    r = _run(scene, "handle_create_prim", prim_path="/World/Bot", usd_path=asset.identifier, position=[5, 5, 5])

    assert r["status"] == "error"
    assert "reference was not added" not in r["error"]
    assert len(kit.stage.GetRootLayer().GetPrimAtPath("/World/Bot").referenceList.GetAddedOrExplicitItems()) == 1


def test_create_prim_without_a_transform_leaves_a_prim_without_one(scene, kit):
    # A material has no transform: nothing is checked when none is given.
    r = _run(scene, "handle_create_prim", prim_path="/World/Looks/Mat", prim_type="Material")
    assert r["status"] == "success", r


# ---- create_prim's usd_path brought to the stage's up axis and units (#119) ----

TURN, SCALE = "xformOp:rotateX:unitsResolve", "xformOp:scale:unitsResolve"


def _box_file(
    folder: Path, up_axis: str | None = None, meters: float | None = None, name: str = "box.usda", animated=False
) -> str:
    """A file whose default prim, /Box, holds a box 0.5 by 0.5 by 1, tall along the file's up axis, its base at the
    origin, with a contact offset of 0.02 and a density of 1000; its root's own translate animated if asked."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    layer = Sdf.Layer.CreateNew(str(path))
    held = Usd.Stage.Open(layer)
    if up_axis is not None:
        UsdGeom.SetStageUpAxis(held, up_axis)
    if meters is not None:
        UsdGeom.SetStageMetersPerUnit(held, meters)
    root = UsdGeom.Xform.Define(held, "/Box")
    if animated:
        root.AddTranslateOp().Set(Gf.Vec3d(0, 0, 1), 1.0)
    shape = UsdGeom.Cube.Define(held, "/Box/Shape")
    z = up_axis == "Z"
    shape.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0.5) if z else Gf.Vec3d(0, 0.5, 0))
    shape.AddScaleOp().Set(Gf.Vec3f(0.25, 0.25, 0.5) if z else Gf.Vec3f(0.25, 0.5, 0.25))
    shape.GetPrim().CreateAttribute("physxCollision:contactOffset", Sdf.ValueTypeNames.Float).Set(0.02)
    shape.GetPrim().CreateAttribute("physics:density", Sdf.ValueTypeNames.Float).Set(1000.0)
    held.SetDefaultPrim(root.GetPrim())
    layer.Save()
    return layer.realPath


_TABLE = {"physxCollision:contactOffset": (0, 1, 0, 0, 0), "physics:density": (1, -3, 0, 0, 0)}


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> None:
    """pxr.PhysicsSchemaTools.units, which only Kit's PhysX schema ships, faked with two of its entries."""
    units = _module("pxr.PhysicsSchemaTools.units", get_attribute_unit_exponents=lambda name, _prim: _TABLE.get(name))
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools", _module("pxr.PhysicsSchemaTools", units=units))
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools.units", units)


def _units(kit: FakeKit, up_axis: str, meters: float) -> None:
    UsdGeom.SetStageUpAxis(kit.stage, up_axis)
    UsdGeom.SetStageMetersPerUnit(kit.stage, meters)


def _size(kit: FakeKit, path: str) -> list[float]:
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(kit.stage.GetPrimAtPath(path))
    return [round(v, 6) for v in floats(box.ComputeAlignedRange().GetSize())]


def _offset(kit: FakeKit, path: str) -> float:
    return kit.stage.GetPrimAtPath(path).GetAttribute("physxCollision:contactOffset").Get()


def test_create_prim_brings_a_file_of_another_up_axis_and_units_to_the_stage(scene, kit, tmp_path, table):
    # A Z-up centimetre prop on a Y-up metre stage lay on its side, 100 times too large, its values in centimetres.
    _units(kit, "Y", 1.0)
    box = _box_file(tmp_path, "Z", 0.01)

    r = _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path=box, position=[1, 2, 3])

    assert r["status"] == "success", r
    assert _ops(kit.stage.GetPrimAtPath("/World/Box")) == ["xformOp:translate", TURN, SCALE]
    assert _size(kit, "/World/Box/Shape") == [0.005, 0.01, 0.005]
    assert _world(kit.stage.GetPrimAtPath("/World/Box")) == Gf.Vec3d(1, 2, 3)
    assert _offset(kit, "/World/Box/Shape") == pytest.approx(0.0002)
    assert kit.stage.GetPrimAtPath("/World/Box/Shape").GetAttribute("physics:density").Get() == pytest.approx(1e9)
    result = r["result"]
    assert result["up_axis_turn"] == {"file": "Z", "stage": "Y", "degrees": -90.0, "op": -90.0, "op_name": TURN}
    assert (result["units_scale"]["factor"], result["units_scale"]["converted"]) == (0.01, 2)
    assert (result["frame"], result["not_brought"]) == (None, None)


def test_create_prim_s_rotation_and_scale_stay_outside_the_units_ops(scene, kit, tmp_path):
    # rotation turns the standing file about the stage's Y, and scale=2 makes it twice its real size.
    _units(kit, "Y", 1.0)

    r = _run(
        scene,
        "handle_create_prim",
        prim_path="/World/Box",
        usd_path=_box_file(tmp_path, "Z", 1.0),
        rotation=[0, 90, 0],
        scale=2,
    )

    assert r["status"] == "success", r
    assert _ops(kit.stage.GetPrimAtPath("/World/Box"))[-1] == TURN
    assert _size(kit, "/World/Box/Shape") == [1.0, 2.0, 1.0]


@pytest.mark.parametrize(("up_axis", "meters"), [("Y", 1.0), (None, None)], ids=["the-stage-s", "unsaid"])
def test_create_prim_leaves_a_file_of_the_stage_s_axis_and_units_or_none_as_it_is(
    scene, kit, tmp_path, table, up_axis, meters
):
    _units(kit, "Y", 1.0)

    r = _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path=_box_file(tmp_path, up_axis, meters))

    assert r["status"] == "success", r
    assert _ops(kit.stage.GetPrimAtPath("/World/Box")) == []
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Box/Shape") is None
    assert [r["result"][k] for k in ("up_axis_turn", "units_scale", "frame", "not_brought")] == [None] * 4


def test_create_prim_inside_an_asset_brought_to_the_stage_measures_against_its_frame(scene, kit, tmp_path, table):
    # Kit's own recursive test and the plan's N1 and N2: the same file under it needs no op of its own; a file of the
    # stage's axis is turned back, where Kit would leave it lying down.
    _units(kit, "Y", 0.01)
    box = _box_file(tmp_path, "Z", 1.0)
    assert _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path=box)["status"] == "success"

    same = _run(scene, "handle_create_prim", prim_path="/World/Box/Inner", usd_path=box)
    native = _run(
        scene, "handle_create_prim", prim_path="/World/Box/Native", usd_path=_box_file(tmp_path, "Y", 0.01, "y.usda")
    )

    assert same["status"] == "success", same
    assert _ops(kit.stage.GetPrimAtPath("/World/Box/Inner")) == []
    assert _size(kit, "/World/Box/Inner/Shape") == _size(kit, "/World/Box/Shape") == [50.0, 100.0, 50.0]
    assert _offset(kit, "/World/Box/Inner/Shape") == pytest.approx(2.0)
    assert same["result"]["frame"] == {"up_axis": "Z", "meters_per_unit": 1.0, "prims": ["/World/Box"]}
    assert native["result"]["up_axis_turn"]["degrees"] == 90.0
    assert native["result"]["up_axis_turn"]["frame"] == "Z"
    assert _size(kit, "/World/Box/Native/Shape") == [0.5, 1.0, 0.5]


def test_create_prim_on_a_prim_already_there_adds_the_file_as_it_is_and_says_so(scene, kit, tmp_path, table):
    # The prim may hold other content, which a turn or a scale would move too (Q1).
    _units(kit, "Y", 1.0)
    kit.stage.DefinePrim("/World/Shelf", "Xform")

    r = _run(scene, "handle_create_prim", prim_path="/World/Shelf", usd_path=_box_file(tmp_path, "Z", 0.01))

    assert r["status"] == "success", r
    assert _ops(kit.stage.GetPrimAtPath("/World/Shelf")) == []
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Shelf/Shape") is None
    assert r["result"]["up_axis_turn"] is None
    assert r["result"]["not_brought"] == {
        "prim_path": "/World/Shelf",
        "file": {"up_axis": "Z", "meters_per_unit": 0.01},
        "frame": {"up_axis": "Y", "meters_per_unit": 1.0},
    }


def test_create_prim_measures_a_file_added_to_a_brought_prim_against_the_frame_inside_it(scene, kit, tmp_path):
    # The plan's P1: a shelf brought in (-90, x0.01), then a Y-up metre file on it, which lies along -Z at 1/100.
    _units(kit, "Y", 1.0)
    brought = _run(scene, "handle_create_prim", prim_path="/World/Shelf", usd_path=_box_file(tmp_path, "Z", 0.01))
    assert brought["status"] == "success", brought

    r = _run(scene, "handle_create_prim", prim_path="/World/Shelf", usd_path=_box_file(tmp_path, "Y", 1.0, "y.usda"))

    assert r["result"]["not_brought"]["frame"] == {"up_axis": "Z", "meters_per_unit": 0.01}


def test_create_prim_called_again_on_its_file_moves_it_and_turns_it_once(scene, kit, tmp_path):
    _units(kit, "Y", 1.0)
    body = {"prim_path": "/World/Box", "usd_path": _box_file(tmp_path, "Z", 0.01)}
    assert _run(scene, "handle_create_prim", **body)["status"] == "success"

    r = _run(scene, "handle_create_prim", **body, position=[5, 0, 0])

    assert r["status"] == "success", r
    prim = kit.stage.GetPrimAtPath("/World/Box")
    assert _ops(prim) == ["xformOp:translate", TURN, SCALE]
    assert (prim.GetAttribute(TURN).Get(), prim.GetAttribute(SCALE).Get()) == (-90.0, Gf.Vec3d(0.01, 0.01, 0.01))
    assert _world(prim) == Gf.Vec3d(5, 0, 0)
    assert (r["result"]["up_axis_turn"], r["result"]["not_brought"]) == (None, None)


def test_create_prim_that_refuses_after_the_turn_leaves_no_prim_and_no_override(scene, kit, tmp_path):
    _units(kit, "Y", 1.0)
    box = _box_file(tmp_path, "Z", 0.01, animated=True)

    r = _run(scene, "handle_create_prim", prim_path="/World/Group/Box", usd_path=box, position=[1, 0, 0])

    assert r["status"] == "error"
    assert r["error"].endswith(". Nothing was created")
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Group") is None


def test_create_prim_that_fails_converting_names_the_step_and_leaves_nothing(scene, kit, tmp_path, monkeypatch):
    def broken(name: str, _prim: Usd.Prim) -> tuple[int, ...]:
        raise KeyError(name)

    units = _module("pxr.PhysicsSchemaTools.units", get_attribute_unit_exponents=broken)
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools", _module("pxr.PhysicsSchemaTools", units=units))
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools.units", units)
    _units(kit, "Y", 1.0)

    r = _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path=_box_file(tmp_path, "Y", 0.01))

    assert r["status"] == "error"
    assert r["error"].startswith("Converting the file's values to the stage's units failed: KeyError: ")
    assert r["error"].endswith(". Nothing was created")
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Box") is None


def test_create_prim_with_a_file_that_can_t_be_opened_makes_nothing(scene, kit, tmp_path):
    # It made an empty prim, answered as created (Q3).
    missing = str(tmp_path / "No Such Box.usda")

    r = _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path=missing)

    assert r["status"] == "error"
    assert r["error"].startswith(f"Could not open {missing}")
    assert not kit.stage.GetPrimAtPath("/World/Box").IsValid()


def test_create_prim_reads_a_relative_usd_path_beside_the_stage_s_file(scene, kit, tmp_path, monkeypatch):
    # The reference reads it there, whatever folder Kit was started in (U1).
    (tmp_path / "scene").mkdir()
    kit.stage = Usd.Stage.CreateNew(str(tmp_path / "scene" / "stage.usda"))
    UsdGeom.Xform.Define(kit.stage, "/World")
    _units(kit, "Y", 1.0)
    _box_file(tmp_path / "scene" / "props", "Z", 1.0)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    r = _run(scene, "handle_create_prim", prim_path="/World/Box", usd_path="props/box.usda")

    assert r["status"] == "success", r
    assert r["result"]["up_axis_turn"]["degrees"] == -90.0


# ---- clone_prim ----


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
    # The copies are in the root layer; moving them in the sublayer would be refused as hidden.
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


# ---- delete_prim ----


@pytest.fixture
def asset() -> Sdf.Layer:
    """A robot's file, held for the test: an anonymous layer goes when its last handle does."""
    layer = Sdf.Layer.CreateAnonymous("bot.usda")
    held = Usd.Stage.Open(layer)
    UsdGeom.Xform.Define(held, "/Bot")
    UsdGeom.Cube.Define(held, "/Bot/Link")
    return layer


def test_delete_prim_refuses_a_part_of_a_referenced_file_and_keeps_its_override(scene, kit, asset):
    # 0.2.3 removed the root layer's over and answered "Prim deleted"; the part stayed, its override gone.
    kit.stage.DefinePrim("/World/Ref").GetReferences().AddReference(asset.identifier, "/Bot")
    kit.stage.OverridePrim("/World/Ref/Link").CreateAttribute("note", Sdf.ValueTypeNames.String).Set("mine")

    r = _run(scene, "handle_delete_prim", prim_path="/World/Ref/Link")

    assert r["status"] == "error"
    assert "comes through a reference on /World/Ref" in r["error"]
    assert kit.stage.GetPrimAtPath("/World/Ref/Link").GetAttribute("note").Get() == "mine"


def test_delete_prim_refuses_a_prim_a_sublayer_defines(scene, kit):
    sub = Sdf.Layer.CreateAnonymous("props.usda")
    kit.stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    with Usd.EditContext(kit.stage, sub):
        UsdGeom.Sphere.Define(kit.stage, "/World/FromSub")

    r = _run(scene, "handle_delete_prim", prim_path="/World/FromSub")

    assert r["status"] == "error"
    assert "props.usda defines it too" in r["error"]
    assert kit.stage.GetPrimAtPath("/World/FromSub").IsDefined()


def test_delete_prim_deletes_a_prim_that_references_a_file_and_says_it_checked(scene, kit, asset):
    kit.stage.DefinePrim("/World/Ref").GetReferences().AddReference(asset.identifier, "/Bot")

    r = _run(scene, "handle_delete_prim", prim_path="/World/Ref")

    assert r["status"] == "success", r
    assert r["result"]["checked"] is True
    assert not kit.stage.GetPrimAtPath("/World/Ref").IsValid()


# ---- /scene/dump and /scene/tree's text ----


def _tree(stage: Usd.Stage) -> None:
    """/World/Table with a leg, a top and a cup on the top; a lamp beside the table."""
    for path in ("/World/Table/Leg", "/World/Table/Top", "/World/Table/Top/Cup", "/World/Lamp"):
        UsdGeom.Xform.Define(stage, path)


def test_dump_scene_counts_the_prims_it_wrote(scene, kit, tmp_path):
    # "Dumped N prims" counted the whole stage (#82).
    _tree(kit.stage)

    r = _run(scene, "handle_scene_dump", output_dir=str(tmp_path), root="/World/Table", max_depth=1)

    assert r["status"] == "success", r
    assert r["result"]["prim_count"] == 3  # the table, its leg and its top; the cup is past max_depth
    assert len(list(kit.stage.Traverse())) == 6


def test_the_scene_trees_text_stops_at_max_depth_with_each_prims_count_of_children(scene, kit):
    # The text listed the next level's prims that had children and left out the childless ones (#82).
    _tree(kit.stage)

    r = _run(scene, "handle_scene_tree", root="/World", max_depth=1, format="text")

    assert r["status"] == "success", r
    blocks = [b for b in r["result"]["text"].split("\n\n") if b.startswith("[")]
    assert [b.splitlines()[0] for b in blocks] == ["[/World]", "[/World/Table]", "[/World/Lamp]"]
    assert "children = 2 (truncated)" in blocks[1]
    assert "children" not in blocks[2]
    assert r["result"]["prim_count"] == 3


# ---- set_material ----


def test_set_material_with_an_opacity_of_1_makes_a_see_through_material_opaque(scene, kit):
    # 0.2.3 wrote the opacity only below 1, so an opaque material stayed see-through.
    UsdGeom.Cube.Define(kit.stage, "/World/Cube")
    shader_path = "/World/Looks/Cube_Mat/Shader"

    assert (
        _run(scene, "handle_set_material", prim_path="/World/Cube", color=[1, 0, 0], opacity=0.5)["status"] == "success"
    )
    r = _run(scene, "handle_set_material", prim_path="/World/Cube", color=[1, 0, 0])

    assert r["status"] == "success", r
    shader = UsdShade.Shader(kit.stage.GetPrimAtPath(shader_path))
    assert shader.GetInput("enable_opacity").Get() is False
    assert shader.GetInput("opacity_constant").Get() == 1.0


def test_clone_prim_whose_later_copy_refuses_leaves_none_of_its_copies(scene, kit, monkeypatch):
    # No stage on usd-core makes a copy refuse what its source took: CopySpec carries the root layer's
    # opinions and any other layer's at the copy's path would make that path taken. So the refusal is faked, on the
    # third copy, after two are there.
    UsdGeom.Xform.Define(kit.stage, "/World/A").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
    real = scene.write_transform
    moved: list[str] = []

    def refuse_the_third(prim: Usd.Prim, parts: Any, layer: Any = None) -> None:
        moved.append(str(prim.GetPath()))
        if len(moved) == 2:
            raise ValueError("held by Kit's session layer")
        real(prim, parts, layer)

    monkeypatch.setattr(scene, "write_transform", refuse_the_third)

    r = _run(scene, "handle_clone_prim", source_path="/World/A", target_path="/World/Row", count=3, offset=[0, 1, 0])

    assert r["status"] == "error"
    assert r["error"] == "held by Kit's session layer. Nothing was copied"
    assert moved == ["/World/Row_002", "/World/Row_003"]
    for n in (1, 2, 3):
        assert not kit.stage.GetPrimAtPath(f"/World/Row_00{n}").IsValid()
