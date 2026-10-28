"""inspect_prim's isolate: what gets hidden, and that the session layer comes back exactly. Runs on usd-core."""

import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom, UsdLux  # noqa: E402

from isaacsim.mcp.bridge.core.isolation import Hidden, is_light, prims_to_hide  # noqa: E402


@pytest.fixture
def stage():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Xform.Define(stage, "/World/Robot")
    UsdGeom.Cube.Define(stage, "/World/Robot/Base")
    UsdGeom.Cube.Define(stage, "/World/Robot/Arm")
    UsdGeom.Cube.Define(stage, "/World/Table")
    UsdGeom.Xform.Define(stage, "/World/Lights")
    UsdLux.SphereLight.Define(stage, "/World/Lights/Key")
    UsdGeom.Cube.Define(stage, "/World/Lights/Softbox")
    UsdGeom.Cube.Define(stage, "/World/Hidden").MakeInvisible()
    UsdGeom.Xform.Define(stage, "/Environment")
    UsdGeom.Cube.Define(stage, "/Environment/Ground")
    UsdLux.DomeLight.Define(stage, "/Environment/Sky")
    stage.DefinePrim("/Untyped")
    UsdGeom.Cube.Define(stage, "/Untyped/Crate")
    UsdGeom.Camera.Define(stage, "/Camera")
    return stage


def _strs(paths):
    return sorted(str(p) for p in paths)


def test_a_nested_target_hides_its_siblings_at_every_level(stage):
    assert _strs(prims_to_hide(stage, "/World/Robot/Arm")) == [
        "/Environment/Ground",
        "/Untyped/Crate",
        "/World/Lights/Softbox",
        "/World/Robot/Base",
        "/World/Table",
    ]


def test_world_as_target_hides_nothing_under_it(stage):
    assert _strs(prims_to_hide(stage, "/World")) == ["/Environment/Ground", "/Untyped/Crate"]


def test_the_root_as_target_hides_nothing(stage):
    assert prims_to_hide(stage, "/") == []


def test_lights_and_cameras_are_never_hidden(stage):
    hidden = _strs(prims_to_hide(stage, "/World/Table"))
    assert "/World/Lights/Key" not in hidden
    assert "/World/Lights" not in hidden
    assert "/Environment/Sky" not in hidden
    assert "/Camera" not in hidden


def test_is_light():
    stage = Usd.Stage.CreateInMemory()
    assert is_light(UsdLux.DistantLight.Define(stage, "/L").GetPrim())
    assert not is_light(UsdGeom.Cube.Define(stage, "/C").GetPrim())


def test_hiding_makes_them_invisible_and_restore_puts_the_session_layer_back_exactly(stage):
    layer = stage.GetSessionLayer()
    before = layer.ExportToString()
    hidden = Hidden(layer)
    hidden.hide(prims_to_hide(stage, "/World/Robot/Arm"))
    assert len(hidden) == 5
    vis = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Table")).ComputeVisibility()
    assert vis == UsdGeom.Tokens.invisible
    arm = UsdGeom.Imageable(stage.GetPrimAtPath("/World/Robot/Arm")).ComputeVisibility()
    assert arm == UsdGeom.Tokens.inherited

    hidden.restore()
    assert layer.ExportToString() == before
    assert len(hidden) == 0


def test_an_opinion_the_session_layer_already_had_comes_back(stage):
    # The root layer hides the table; the session layer shows it. Isolation must not lose that.
    UsdGeom.Imageable(stage.GetPrimAtPath("/World/Table")).MakeInvisible()
    layer = stage.GetSessionLayer()
    with Usd.EditContext(stage, layer):
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Table")).GetVisibilityAttr().Set(UsdGeom.Tokens.inherited)
    before = layer.ExportToString()

    hidden = Hidden(layer)
    hidden.hide(prims_to_hide(stage, "/World/Robot"))
    hidden.restore()

    assert layer.ExportToString() == before
    assert UsdGeom.Imageable(stage.GetPrimAtPath("/World/Table")).ComputeVisibility() == UsdGeom.Tokens.inherited


def test_a_visibility_spec_without_a_default_comes_back_without_one(stage):
    layer = stage.GetSessionLayer()
    spec = Sdf.CreatePrimInLayer(layer, "/World/Table")
    Sdf.AttributeSpec(spec, UsdGeom.Tokens.visibility, Sdf.ValueTypeNames.Token)
    before = layer.ExportToString()

    hidden = Hidden(layer)
    hidden.hide([Sdf.Path("/World/Table")])
    hidden.restore()

    assert layer.ExportToString() == before


def test_restore_after_a_partial_hide_undoes_what_was_done(stage):
    layer = stage.GetSessionLayer()
    before = layer.ExportToString()
    hidden = Hidden(layer)
    with pytest.raises(Exception):
        hidden.hide([Sdf.Path("/World/Table"), Sdf.Path("not a prim path")])
    hidden.restore()
    assert layer.ExportToString() == before
