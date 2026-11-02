"""The exposure shield (#177) on usd-core: what RTX would write at the edit target is authored in the session layer
first, and lifted back exactly."""

import pytest
from pxr import Sdf, Usd, UsdGeom

from ovmcp.core.exposure import ATTRIBUTES, SCHEMAS, shield


def _applied(prim: Usd.Prim) -> set[str]:
    op = prim.GetMetadata("apiSchemas")
    return set(op.ApplyOperations([])) if op else set()


CAMERA = "/World/Rig/ShotCam"


@pytest.fixture
def stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Camera.Define(stage, CAMERA)
    return stage


def _texts(stage: Usd.Stage) -> tuple[str, str]:
    return stage.GetRootLayer().ExportToString(), stage.GetSessionLayer().ExportToString()


def test_a_bare_camera_gets_the_schemas_and_attributes_in_the_session_layer_only(stage):
    root = stage.GetRootLayer().ExportToString()

    made = shield(stage, CAMERA)

    assert made is not None
    prim = stage.GetPrimAtPath(CAMERA)
    assert set(SCHEMAS) <= _applied(prim)
    for name, value in ATTRIBUTES:
        assert prim.GetAttribute(name).Get() == pytest.approx(value)
        assert stage.GetSessionLayer().GetAttributeAtPath(f"{CAMERA}.{name}") is not None
    assert stage.GetRootLayer().ExportToString() == root  # the user's file untouched


def test_lift_puts_the_session_layer_back_exactly_with_the_specs_it_made(stage):
    texts = _texts(stage)

    made = shield(stage, CAMERA)
    assert made is not None
    assert made.created  # the session layer had no spec on the camera's path
    made.lift()

    assert _texts(stage) == texts
    assert stage.GetSessionLayer().GetPrimAtPath("/World") is None


def test_a_camera_that_has_them_is_left_alone(stage):
    prim = stage.GetPrimAtPath(CAMERA)
    for name in SCHEMAS:
        prim.AddAppliedSchema(name)
    for name, value in ATTRIBUTES:
        prim.CreateAttribute(name, Sdf.ValueTypeNames.Float).Set(value * 2)
    texts = _texts(stage)

    assert shield(stage, CAMERA) is None
    assert _texts(stage) == texts


def test_only_what_the_camera_lacks_is_authored_and_its_own_values_stand(stage):
    # With only the schemas there, RTX still wrote the attributes (#177's measurement); an attribute the camera has
    # keeps its value.
    prim = stage.GetPrimAtPath(CAMERA)
    for name in SCHEMAS:
        prim.AddAppliedSchema(name)
    prim.CreateAttribute("exposure:fStop", Sdf.ValueTypeNames.Float).Set(2.8)
    texts = _texts(stage)

    made = shield(stage, CAMERA)

    assert made is not None
    assert made.schemas == []
    assert made.attributes == ["exposure:responsivity", "exposure:time"]
    assert prim.GetAttribute("exposure:fStop").Get() == pytest.approx(2.8)
    made.lift()
    assert _texts(stage) == texts


def test_a_session_spec_with_its_own_schemas_and_an_empty_attribute_comes_back_as_it_was(stage):
    session = stage.GetSessionLayer()
    spec = Sdf.CreatePrimInLayer(session, CAMERA)
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["SomeAPI"], appendedItems=["OtherAPI"]))
    Sdf.AttributeSpec(spec, "exposure:time", Sdf.ValueTypeNames.Float)  # declared, no value
    texts = _texts(stage)

    made = shield(stage, CAMERA)

    assert made is not None
    assert {"SomeAPI", "OtherAPI", *SCHEMAS} <= _applied(stage.GetPrimAtPath(CAMERA))
    assert made.defaults == ["exposure:time"]
    assert made.created == []
    made.lift()
    assert _texts(stage) == texts


def test_an_explicit_schema_list_keeps_its_items(stage):
    spec = Sdf.CreatePrimInLayer(stage.GetSessionLayer(), CAMERA)
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.CreateExplicit(["SomeAPI"]))
    texts = _texts(stage)

    made = shield(stage, CAMERA)

    assert made is not None
    assert list(spec.GetInfo("apiSchemas").explicitItems) == ["SomeAPI", *SCHEMAS]
    made.lift()
    assert _texts(stage) == texts


@pytest.mark.parametrize("path", ["/World/Nothing", "/World/Rig/ShotCam/Child"])
def test_no_prim_no_shield(stage, path):
    texts = _texts(stage)

    assert shield(stage, path) is None
    assert _texts(stage) == texts


def test_a_camera_inside_an_instance_is_left_alone(stage, tmp_path):
    # A session spec under an instance proxy's path has no effect, so nothing is written for one.
    asset = tmp_path / "rig.usda"
    rig = Usd.Stage.CreateNew(str(asset))
    UsdGeom.Xform.Define(rig, "/Rig")
    UsdGeom.Camera.Define(rig, "/Rig/Cam")
    rig.SetDefaultPrim(rig.GetPrimAtPath("/Rig"))
    rig.Save()
    placed = stage.DefinePrim("/World/Placed")
    placed.GetReferences().AddReference(str(asset))
    placed.SetInstanceable(True)
    texts = _texts(stage)

    assert stage.GetPrimAtPath("/World/Placed/Cam").IsInstanceProxy()
    assert shield(stage, "/World/Placed/Cam") is None
    assert _texts(stage) == texts
