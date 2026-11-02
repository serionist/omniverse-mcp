"""RTX's exposure writes put back (#177) on usd-core: a camera's mark, taken before RTX writes onto it at the edit
target, puts the layer back exactly, and the marks count the feeds through each camera."""

import gc

import pytest
from pxr import Sdf, Usd, UsdGeom

from ovmcp.core.exposure import ATTRIBUTES, SCHEMAS, Marks, bare, mark

CAMERA = "/World/Rig/ShotCam"
# What RTX wrote, measured on Isaac Sim 6.2 with Kit's default settings (#177).
RTX_VALUES = (5.0, 1.1026709, 0.02)


def rtx_writes(stage: Usd.Stage, path: str) -> None:
    """What Kit 110's RTX writes onto a bare camera it renders through, at the edit target."""
    spec = Sdf.CreatePrimInLayer(stage.GetEditTarget().GetLayer(), path)
    op = spec.GetInfo("apiSchemas") if spec.HasInfo("apiSchemas") else Sdf.TokenListOp()
    op.prependedItems = [*SCHEMAS, *op.prependedItems]
    spec.SetInfo("apiSchemas", op)
    for name, value in zip(ATTRIBUTES, RTX_VALUES, strict=True):
        attribute = spec.attributes.get(name) or Sdf.AttributeSpec(spec, name, Sdf.ValueTypeNames.Float)
        attribute.default = value


@pytest.fixture
def stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Camera.Define(stage, CAMERA)
    return stage


def _texts(stage: Usd.Stage) -> tuple[str, str]:
    return stage.GetRootLayer().ExportToString(), stage.GetSessionLayer().ExportToString()


def test_a_mark_puts_back_what_rtx_wrote_onto_a_camera_of_the_file(stage):
    texts = _texts(stage)
    noted = mark(stage.GetRootLayer(), CAMERA)

    rtx_writes(stage, CAMERA)
    assert not bare(stage.GetPrimAtPath(CAMERA))
    noted.restore()

    assert _texts(stage) == texts
    assert bare(stage.GetPrimAtPath(CAMERA))


def test_a_mark_removes_the_over_rtx_left_for_a_camera_of_the_session_layer(stage):
    # The sweep's own camera lives in the session layer; RTX wrote an over for it into the root layer (#157's run).
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        UsdGeom.Camera.Define(stage, "/OmniverseKit_Sweep")
    texts = _texts(stage)
    noted = mark(stage.GetRootLayer(), "/OmniverseKit_Sweep")

    rtx_writes(stage, "/OmniverseKit_Sweep")
    noted.restore()

    assert _texts(stage) == texts
    assert stage.GetRootLayer().GetPrimAtPath("/OmniverseKit_Sweep") is None


def test_a_spec_s_own_schemas_attributes_and_value_block_come_back(stage):
    spec = stage.GetRootLayer().GetPrimAtPath(CAMERA)
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.Create(prependedItems=["SomeAPI"], appendedItems=["OtherAPI"]))
    Sdf.AttributeSpec(spec, "exposure:time", Sdf.ValueTypeNames.Float)  # declared, no value
    Sdf.AttributeSpec(spec, "exposure:fStop", Sdf.ValueTypeNames.Float).default = Sdf.ValueBlock()
    texts = _texts(stage)
    noted = mark(stage.GetRootLayer(), CAMERA)

    rtx_writes(stage, CAMERA)
    noted.restore()

    assert _texts(stage) == texts


def test_only_rtx_s_schemas_go_where_the_spec_held_none(stage):
    noted = mark(stage.GetRootLayer(), CAMERA)
    rtx_writes(stage, CAMERA)
    stage.GetPrimAtPath(CAMERA).AddAppliedSchema("UserAddedAPI")  # added since, in the same list op

    noted.restore()

    op = stage.GetRootLayer().GetPrimAtPath(CAMERA).GetInfo("apiSchemas")
    assert list(op.prependedItems) + list(op.appendedItems) == ["UserAddedAPI"]


def test_an_explicit_schema_list_comes_back_as_it_was(stage):
    spec = stage.GetRootLayer().GetPrimAtPath(CAMERA)
    spec.SetInfo("apiSchemas", Sdf.TokenListOp.CreateExplicit(["SomeAPI"]))
    texts = _texts(stage)
    noted = mark(stage.GetRootLayer(), CAMERA)

    spec.SetInfo("apiSchemas", Sdf.TokenListOp.CreateExplicit(["SomeAPI", *SCHEMAS]))
    noted.restore()

    assert _texts(stage) == texts


def test_a_camera_with_everything_is_no_bare_camera(stage):
    prim = stage.GetPrimAtPath(CAMERA)
    for name in SCHEMAS:
        prim.AddAppliedSchema(name)
    assert bare(prim)
    for name in ATTRIBUTES:
        prim.CreateAttribute(name, Sdf.ValueTypeNames.Float).Set(1.0)
    assert not bare(prim)


def test_the_last_feed_through_a_camera_puts_it_back_and_not_before(stage):
    marks = Marks()
    texts = _texts(stage)
    layers = list(stage.GetLayerStack(includeSessionLayers=True))

    first = marks.take(stage, CAMERA)
    rtx_writes(stage, CAMERA)
    second = marks.take(stage, CAMERA)  # not bare any more, but a feed already holds its mark
    assert first is not None
    assert second == first
    assert marks.feeds(first) == 2

    marks.let_go(first, layers)
    assert _texts(stage) != texts  # another feed still renders through it
    marks.let_go(first, layers)  # the second feed's, the same key

    assert _texts(stage) == texts
    assert marks.feeds(first) == 0


def test_a_mark_on_a_layer_the_stage_no_longer_holds_is_dropped_unwritten(stage):
    marks = Marks()
    key = marks.take(stage, CAMERA)
    assert key is not None
    rtx_writes(stage, CAMERA)
    written = _texts(stage)

    marks.let_go(key, [])  # a new stage: the layer went with what RTX wrote into it

    assert _texts(stage) == written
    assert marks.feeds(key) == 0


def test_a_mark_is_taken_on_the_edit_target(stage, tmp_path):
    sub = Sdf.Layer.CreateNew(str(tmp_path / "edits.usda"))
    stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    stage.SetEditTarget(Usd.EditTarget(sub))
    marks = Marks()

    key = marks.take(stage, CAMERA)
    assert key is not None
    rtx_writes(stage, CAMERA)
    marks.let_go(key, list(stage.GetLayerStack(includeSessionLayers=True)))

    assert key[0] == sub.identifier
    assert sub.GetPrimAtPath(CAMERA) is None


def test_no_prim_no_mark(stage):
    assert Marks().take(stage, "/World/Nothing") is None


def test_a_camera_that_has_everything_or_sits_in_an_instance_gets_no_mark(stage, tmp_path):
    prim = stage.GetPrimAtPath(CAMERA)
    for name in SCHEMAS:
        prim.AddAppliedSchema(name)
    for name in ATTRIBUTES:
        prim.CreateAttribute(name, Sdf.ValueTypeNames.Float).Set(1.0)
    asset = tmp_path / "rig.usda"
    rig = Usd.Stage.CreateNew(str(asset))
    UsdGeom.Camera.Define(rig, "/Rig/Cam")
    rig.SetDefaultPrim(rig.GetPrimAtPath("/Rig"))
    rig.Save()
    placed = stage.DefinePrim("/World/Placed")
    placed.GetReferences().AddReference(str(asset))
    placed.SetInstanceable(True)
    marks = Marks()

    assert marks.take(stage, CAMERA) is None
    assert stage.GetPrimAtPath("/World/Placed/Cam").IsInstanceProxy()
    assert marks.take(stage, "/World/Placed/Cam") is None


def test_forget_drops_every_mark_unwritten(stage):
    marks = Marks()
    key = marks.take(stage, CAMERA)
    assert key is not None
    rtx_writes(stage, CAMERA)
    written = _texts(stage)

    marks.forget()
    marks.let_go(key, list(stage.GetLayerStack(includeSessionLayers=True)))

    assert _texts(stage) == written


@pytest.mark.parametrize("first", ["left", "right"])
def test_a_parent_two_marked_cameras_share_goes_whichever_is_put_back_last(first):
    # A stereo pair under a head the root layer has no spec for: RTX's over for the head stayed when the cameras were
    # put back in one order (code review round 2, M2).
    asset = Usd.Stage.CreateInMemory()
    UsdGeom.Camera.Define(asset, "/Robot/Head/cam_left")
    UsdGeom.Camera.Define(asset, "/Robot/Head/cam_right")
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World/Robot").GetReferences().AddReference(asset.GetRootLayer().identifier, "/Robot")
    texts = _texts(stage)
    layers = list(stage.GetLayerStack(includeSessionLayers=True))
    marks = Marks()

    left = marks.take(stage, "/World/Robot/Head/cam_left")
    rtx_writes(stage, "/World/Robot/Head/cam_left")
    right = marks.take(stage, "/World/Robot/Head/cam_right")
    rtx_writes(stage, "/World/Robot/Head/cam_right")
    assert left is not None
    assert right is not None
    for key in (left, right) if first == "left" else (right, left):
        marks.let_go(key, layers)

    assert _texts(stage) == texts


def test_a_mark_on_a_file_opened_again_is_dropped_without_an_error(tmp_path):
    # open_scene of the same file within the kept render's 30 s: the old root layer is freed and the new one has its
    # identifier, so a match by name put the mark back through a dead handle, which raised (code review round 2, M1).
    path = tmp_path / "scene.usda"
    made = Usd.Stage.CreateNew(str(path))
    UsdGeom.Camera.Define(made, CAMERA)
    made.Save()
    del made
    marks = Marks()
    stage = Usd.Stage.Open(str(path))
    key = marks.take(stage, CAMERA)
    assert key is not None
    rtx_writes(stage, CAMERA)
    del stage
    gc.collect()
    reopened = Usd.Stage.Open(str(path))
    assert reopened.GetRootLayer().identifier == key[0]
    texts = _texts(reopened)

    marks.let_go(key, list(reopened.GetLayerStack(includeSessionLayers=True)))

    assert marks.feeds(key) == 0
    assert _texts(reopened) == texts
