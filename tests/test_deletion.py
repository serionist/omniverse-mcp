"""Whether delete_prim can take a prim off the stage (#82), on usd-core: refused, naming why, when another of the
stage's layers defines it or an arc on a prim above brings it; let through when the edit layer's removal takes it."""

import pytest
from pxr import Sdf, Usd, UsdGeom

from ovmcp.core.deletion import why_kept


@pytest.fixture
def stage() -> Usd.Stage:
    st = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(st, "/World")
    return st


def _asset() -> Sdf.Layer:
    """A robot's file: /Bot with a link, and a hand holding nothing of the stage's."""
    layer = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(layer)
    UsdGeom.Xform.Define(held, "/Bot")
    UsdGeom.Cube.Define(held, "/Bot/Link")
    UsdGeom.Xform.Define(held, "/Bot/Hand")
    return layer


# Held for the module: an anonymous layer goes when its last handle does, and a reference to it then resolves nothing.
ASSET = _asset()


def _sublayer(stage: Usd.Stage, tag: str = "sub.usda") -> Sdf.Layer:
    layer = Sdf.Layer.CreateAnonymous(tag)
    stage.GetRootLayer().subLayerPaths.append(layer.identifier)
    return layer


def _kept(stage: Usd.Stage, path: str) -> str | None:
    return why_kept(stage.GetPrimAtPath(path), stage.GetEditTarget().GetLayer())


def test_a_prim_the_root_layer_alone_defines_goes(stage):
    UsdGeom.Cube.Define(stage, "/World/Cube")
    assert _kept(stage, "/World/Cube") is None


def test_a_prim_that_references_a_file_goes_with_its_reference(stage):
    stage.DefinePrim("/World/Robot").GetReferences().AddReference(ASSET.identifier, "/Bot")
    assert _kept(stage, "/World/Robot") is None


def test_a_part_of_a_referenced_file_stays_though_the_root_layer_overrides_it(stage):
    # set_prim_transform on it leaves an over in the root layer, which RemovePrim would take while the part stays.
    stage.DefinePrim("/World/Robot").GetReferences().AddReference(ASSET.identifier, "/Bot")
    stage.OverridePrim("/World/Robot/Link").CreateAttribute("note", Sdf.ValueTypeNames.String).Set("mine")

    why = _kept(stage, "/World/Robot/Link")

    assert why == (
        "/World/Robot/Link is not deleted: it comes through a reference on /World/Robot (asset.usda). "
        "set_visibility hides it"
    )


def test_a_prim_a_sublayer_defines_stays(stage):
    sub = _sublayer(stage)
    with Usd.EditContext(stage, sub):
        UsdGeom.Sphere.Define(stage, "/World/FromSub")

    assert (
        _kept(stage, "/World/FromSub")
        == "/World/FromSub is not deleted: sub.usda defines it too. set_visibility hides it"
    )


def test_a_prim_the_session_layer_defines_is_named_as_kits(stage):
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        UsdGeom.Camera.Define(stage, "/World/Cam")

    assert "Kit's session layer defines it too" in (_kept(stage, "/World/Cam") or "")


def test_a_prim_a_variant_above_defines_stays(stage):
    holder = stage.DefinePrim("/World/V")
    variants = holder.GetVariantSets().AddVariantSet("look")
    variants.AddVariant("a")
    variants.SetVariantSelection("a")
    with variants.GetVariantEditContext():
        UsdGeom.Cube.Define(stage, "/World/V/Child")

    assert "comes through a variant on /World/V" in (_kept(stage, "/World/V/Child") or "")


def test_a_reference_a_sublayer_gives_the_prim_keeps_it(stage):
    UsdGeom.Xform.Define(stage, "/World/R")
    sub = _sublayer(stage, "props.usda")
    with Usd.EditContext(stage, sub):
        stage.OverridePrim("/World/R").GetReferences().AddReference(ASSET.identifier, "/Bot")

    assert (_kept(stage, "/World/R") or "").startswith("/World/R is not deleted: props.usda gives it a reference")


def test_a_prim_inside_an_instance_names_the_instance(stage):
    instance = stage.DefinePrim("/World/Bot")
    instance.GetReferences().AddReference(ASSET.identifier, "/Bot")
    instance.SetInstanceable(True)

    why = _kept(stage, "/World/Bot/Link") or ""

    assert "inside the instance /World/Bot" in why
    assert "set_visibility hides /World/Bot whole" in why


def test_a_prim_the_root_layer_defines_under_a_referenced_one_goes(stage):
    # A camera added to a robot's hand: the reference brings the hand, not the camera (round 1's P10).
    stage.DefinePrim("/World/Franka").GetReferences().AddReference(ASSET.identifier, "/Bot")
    UsdGeom.Camera.Define(stage, "/World/Franka/Hand/Cam")

    assert _kept(stage, "/World/Franka/Hand/Cam") is None


def test_a_prim_the_root_layer_defines_and_a_sublayer_overrides_goes(stage):
    UsdGeom.Cube.Define(stage, "/World/A")
    sub = _sublayer(stage)
    with Usd.EditContext(stage, sub):
        stage.OverridePrim("/World/A").CreateAttribute("note", Sdf.ValueTypeNames.String).Set("theirs")

    assert _kept(stage, "/World/A") is None
