"""flatten_usd, export_prim_as_file and save_scene never write over a layer the open stage uses, save_scene's own root
layer apart, and read a layer again from its file only when the open stage doesn't use it and it has no unsaved edits
(#81, #85); the two flatten the open stage without Kit's session layer (#118); on usd-core."""

import gc
from pathlib import Path, PurePosixPath

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdLux

from ovmcp.core import layers
from ovmcp.core.layers import refresh, refresh_written, without_session, write_refusal

RIG = "/OmniKit_Viewport_LightRig"
SUN = "/World/Sun"


def _file(path: Path, prim: str, **arcs: str) -> Path:
    """A USD file holding one Xform, its default prim, with a reference or a payload to another file if given."""
    stage = Usd.Stage.CreateNew(str(path))
    xform = UsdGeom.Xform.Define(stage, prim).GetPrim()
    stage.SetDefaultPrim(xform)
    if "reference" in arcs:
        xform.GetReferences().AddReference(arcs["reference"])
    if "payload" in arcs:
        xform.GetPayloads().AddPayload(arcs["payload"])
    stage.GetRootLayer().Save()
    return path


def _rewrite(path: Path, prim: str) -> None:
    """Writes the file anew, holding prim alone, past any layer the registry holds for it."""
    layer = Sdf.Layer.CreateAnonymous(".usda")
    Sdf.CreatePrimInLayer(layer, prim)
    assert layer.Export(str(path))


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    """scene.usda: /World over the sublayer sub.usda, /World/R referencing ref.usda, /World/P paying in pay.usda. Beside
    it, other.usda, which nothing uses."""
    _file(tmp_path / "sub.usda", "/Sub")
    _file(tmp_path / "ref.usda", "/Ref")
    _file(tmp_path / "pay.usda", "/Pay")
    _file(tmp_path / "other.usda", "/Other")
    path = _file(tmp_path / "scene.usda", "/World")
    layer = Sdf.Layer.FindOrOpen(str(path))
    layer.subLayerPaths.append("./sub.usda")
    stage = Usd.Stage.Open(layer)
    stage.DefinePrim("/World/R").GetReferences().AddReference("./ref.usda")
    stage.DefinePrim("/World/P").GetPayloads().AddPayload("./pay.usda")
    layer.Save()
    return path


@pytest.fixture
def stage(scene: Path) -> Usd.Stage:
    """scene.usda as the open stage."""
    return Usd.Stage.Open(str(scene))


# ----- write_refusal -----


def test_the_open_stages_own_file_is_refused(stage: Usd.Stage, scene: Path):
    refusal = write_refusal(stage, str(scene))
    assert refusal is not None
    assert "the open stage's root layer" in refusal
    assert "another path" in refusal
    assert "save_scene" in refusal


def test_a_sublayer_is_refused(stage: Usd.Stage, scene: Path):
    refusal = write_refusal(stage, str(scene.parent / "sub.usda"))
    assert refusal is not None
    assert "a sublayer of the open stage" in refusal


@pytest.mark.parametrize("name", ["ref.usda", "pay.usda"])
def test_a_referenced_or_paid_in_file_is_refused(stage: Usd.Stage, scene: Path, name: str):
    refusal = write_refusal(stage, str(scene.parent / name))
    assert refusal is not None
    assert "a layer the open stage references or pays in" in refusal


def test_a_session_layer_with_a_file_is_refused(scene: Path):
    session = _file(scene.parent / "session.usda", "/Session")
    stage = Usd.Stage.Open(Sdf.Layer.FindOrOpen(str(scene)), Sdf.Layer.FindOrOpen(str(session)))
    refusal = write_refusal(stage, str(session))
    assert refusal is not None
    assert "the open stage's session layer" in refusal


@pytest.mark.parametrize("name", ["other.usda", "new.usdc"])
def test_a_file_nothing_uses_may_be_written(stage: Usd.Stage, scene: Path, name: str):
    assert write_refusal(stage, str(scene.parent / name)) is None


def test_another_spelling_of_the_open_stages_file_is_refused(
    stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(scene.parent)
    for spelling in ("scene.usda", "./nowhere/../scene.usda", scene.as_posix(), str(scene)):
        assert write_refusal(stage, spelling) is not None, spelling


def test_a_layers_file_gone_from_disk_is_still_refused_by_another_spelling(
    stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch
):
    # The layer outlives its file, and writing the path would make the file again under it.
    (scene.parent / "sub.usda").unlink()
    monkeypatch.chdir(scene.parent)
    assert write_refusal(stage, "./sub.usda") is not None


def test_a_hard_link_to_the_open_stages_file_is_refused(stage: Usd.Stage, scene: Path):
    link = scene.parent / "linked" / "scene.usda"
    link.parent.mkdir()
    link.hardlink_to(scene)
    refusal = write_refusal(stage, str(link))
    assert refusal is not None
    assert "the open stage's root layer" in refusal


@pytest.mark.parametrize("name", ["latest.usda", "sub.usda"])
def test_a_symlink_to_a_file_of_the_open_stage_is_refused_whatever_its_name(stage: Usd.Stage, scene: Path, name: str):
    # Export writes through the link, onto the scene's file: the name a link has tells nothing.
    link = scene.parent / "links" / name
    link.parent.mkdir()
    try:
        link.symlink_to(scene.parent / "sub.usda")
    except OSError as e:  # Windows makes one only with the privilege or developer mode
        pytest.skip(f"this account can't make a symlink: {e}")
    refusal = write_refusal(stage, str(link))
    assert refusal is not None
    assert "a sublayer of the open stage" in refusal


def test_a_file_url_of_the_open_stages_file_is_refused(stage: Usd.Stage, scene: Path):
    # file:///C:/... from Python, file:/C:/... as Kit spells it.
    for url in (scene.as_uri(), f"file:{PurePosixPath('/', scene.as_posix())}"):
        assert write_refusal(stage, url) is not None, url


def test_a_url_nothing_uses_may_be_written(stage: Usd.Stage):
    assert write_refusal(stage, "omniverse://localhost/Projects/scene.usda") is None


def test_a_layer_whose_file_is_gone_doesnt_stop_the_check(stage: Usd.Stage, scene: Path):
    (scene.parent / "pay.usda").unlink()
    assert write_refusal(stage, str(scene.parent / "other.usda")) is None
    assert write_refusal(stage, str(scene)) is not None


def test_the_open_stages_file_by_another_case_is_refused_where_the_file_system_ignores_case(
    stage: Usd.Stage, scene: Path
):
    shouted = scene.with_name("SCENE.USDA")
    # Sdf's registry tells the two names apart; a file system that ignores case finds one file under both.
    refused = write_refusal(stage, str(shouted)) is not None
    assert refused == shouted.exists()


def test_an_unloaded_payloads_file_is_not_the_open_stages(stage: Usd.Stage, scene: Path):
    stage.Unload("/World/P")
    assert write_refusal(stage, str(scene.parent / "pay.usda")) is None


def test_a_layer_held_outside_the_open_stage_with_unsaved_edits_is_refused(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    assert write_refusal(stage, str(other)) is None
    Sdf.CreatePrimInLayer(held, "/Edit")
    refusal = write_refusal(stage, str(other))
    assert refusal is not None
    assert "unsaved edits" in refusal


# ----- write_refusal for save_scene, which writes the root layer -----


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("sub.usda", "a sublayer of the open stage"),
        ("ref.usda", "a layer the open stage references or pays in"),
        ("pay.usda", "a layer the open stage references or pays in"),
    ],
)
def test_saving_over_another_layer_of_the_open_stage_is_refused(stage: Usd.Stage, scene: Path, name: str, role: str):
    refusal = write_refusal(stage, str(scene.parent / name), saving=True)
    assert refusal is not None
    assert role in refusal
    assert "saving the root layer there" in refusal
    assert "save_scene without a file_path" in refusal


@pytest.mark.parametrize(("saving", "ending"), [(True, "Save to another path."), (False, "Write to another path.")])
def test_a_stage_never_saved_is_offered_no_save_to_its_own_file(scene: Path, saving: bool, ending: str):
    # new_scene's stage, then a prim referencing a file: save_scene without a file_path fails, with no file to save.
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World/Table").GetReferences().AddReference(str(scene.parent / "ref.usda"))
    refusal = write_refusal(stage, str(scene.parent / "ref.usda"), saving=saving)
    assert refusal is not None
    assert "a layer the open stage references or pays in" in refusal
    assert refusal.endswith(ending)
    assert "save_scene" not in refusal


def test_saving_over_the_open_stages_own_file_is_a_save_by_any_spelling(
    stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch
):
    # Unsaved edits, as a save has: they are the open stage's, not a layer held outside it.
    stage.DefinePrim("/World/Unsaved")
    link = scene.parent / "linked" / "scene.usda"
    link.parent.mkdir()
    link.hardlink_to(scene)
    monkeypatch.chdir(scene.parent)
    spellings = ["scene.usda", "./nowhere/../scene.usda", scene.as_posix(), str(scene), scene.as_uri(), str(link)]
    shouted = scene.with_name("SCENE.USDA")
    if shouted.exists():
        spellings.append(str(shouted))
    for spelling in spellings:
        assert write_refusal(stage, spelling, saving=True) is None, spelling


def test_saving_onto_a_layer_held_outside_the_open_stage_with_unsaved_edits_is_refused(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    assert write_refusal(stage, str(other), saving=True) is None
    Sdf.CreatePrimInLayer(held, "/Edit")
    refusal = write_refusal(stage, str(other), saving=True)
    assert refusal is not None
    assert "unsaved edits" in refusal


def test_saving_over_the_open_stages_file_is_refused_when_kit_holds_it_apart_with_unsaved_edits(
    stage: Usd.Stage, scene: Path
):
    # The same file opened with arguments is a layer of its own, outside the open stage: its edits aren't the save's.
    apart = Sdf.Layer.FindOrOpen(str(scene), {"ovmcp": "apart"})
    assert apart is not None
    assert apart != stage.GetRootLayer()
    Sdf.CreatePrimInLayer(apart, "/Apart")
    refusal = write_refusal(stage, str(scene), saving=True)
    assert refusal is not None
    assert "unsaved edits" in refusal


# ----- open_to_flatten -----


def open_to_flatten(stage: Usd.Stage, path: str) -> Usd.Stage:
    opened = layers.open_to_flatten(stage, path)
    assert opened is not None, path
    return opened


def test_flattening_the_open_stages_own_file_leaves_the_open_stage_as_it_was(stage: Usd.Stage, scene: Path):
    stage.DefinePrim("/World/Unsaved")
    # The file changes on disk under the open stage: it must still not be read again.
    _rewrite(scene, "/Elsewhere")
    opened = open_to_flatten(stage, str(scene))
    for path in ("/World/Unsaved", "/World/R", "/World/P", "/Sub"):
        assert stage.GetPrimAtPath(path), path
    assert not stage.GetPrimAtPath("/Elsewhere")
    assert stage.GetRootLayer().dirty
    flat = opened.Flatten()
    # Flattened as Kit holds it, unsaved edits too, as with no input.
    for path in ("/World/Unsaved", "/World/R", "/World/P", "/Sub"):
        assert flat.GetPrimAtPath(path), path


def test_a_layer_of_the_open_stage_an_input_uses_is_not_read_again(stage: Usd.Stage, scene: Path):
    wrapper = _file(scene.parent / "wrapper.usda", "/Wrapper", reference="./sub.usda")
    _rewrite(scene.parent / "sub.usda", "/Changed")
    opened = open_to_flatten(stage, str(wrapper))
    assert stage.GetPrimAtPath("/Sub")
    assert not stage.GetPrimAtPath("/Changed")
    assert opened.GetPrimAtPath("/Wrapper")


def test_a_held_layer_the_open_stage_doesnt_use_is_read_again(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    _rewrite(other, "/New")
    assert held.GetPrimAtPath("/Other")  # stale until read again
    opened = open_to_flatten(stage, str(other))
    assert opened.GetPrimAtPath("/New")
    assert not opened.GetPrimAtPath("/Other")


def test_a_held_layers_unsaved_edits_are_flattened_not_dropped(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    Sdf.CreatePrimInLayer(held, "/Edit")
    opened = open_to_flatten(stage, str(other))
    assert opened.GetPrimAtPath("/Edit")
    assert held.dirty


def test_a_file_nothing_held_is_read_from_disk(stage: Usd.Stage, scene: Path):
    _rewrite(scene.parent / "other.usda", "/Fresh")
    assert open_to_flatten(stage, str(scene.parent / "other.usda")).GetPrimAtPath("/Fresh")


def test_an_input_usd_cant_open_gives_no_stage(stage: Usd.Stage, scene: Path):
    garbled = scene.parent / "garbled.usda"
    garbled.write_bytes(b"not a USD file\n")
    assert layers.open_to_flatten(stage, str(scene.parent / "missing.usda")) is None
    assert layers.open_to_flatten(stage, str(garbled)) is None
    assert stage.GetPrimAtPath("/World/R")


# ----- without_session -----


def kits_default_mode(stage: Usd.Stage, rig: Path) -> None:
    """Viewport light mode Default as Kit sets it (#117's plan, K1 and K4): a rig file with a DomeLight and a
    DistantLight, as Kit's Default.usda has, referenced from an over in the session layer, and the stage's own light,
    SUN, made invisible there."""
    rig_stage = Usd.Stage.CreateNew(str(rig))
    rig_stage.SetDefaultPrim(UsdGeom.Xform.Define(rig_stage, "/World").GetPrim())
    UsdLux.DomeLight.Define(rig_stage, "/World/Lights/DomeLight")
    UsdLux.DistantLight.Define(rig_stage, "/World/Lights/DistantLight")
    rig_stage.GetRootLayer().Save()
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.OverridePrim(RIG).GetReferences().AddReference(str(rig))
        UsdGeom.Imageable(stage.GetPrimAtPath(SUN)).MakeInvisible()


@pytest.fixture
def lit(scene: Path) -> Usd.Stage:
    """scene.usda with a light of its own, /World/Sun, saved, open in mode Default, and an edit it hasn't saved."""
    stage = Usd.Stage.Open(str(scene))
    UsdLux.DistantLight.Define(stage, SUN)
    stage.GetRootLayer().Save()
    kits_default_mode(stage, scene.parent / "Default.usda")
    stage.DefinePrim("/World/Unsaved")
    assert stage.GetPrimAtPath(f"{RIG}/Lights/DomeLight")
    assert UsdGeom.Imageable(stage.GetPrimAtPath(SUN)).ComputeVisibility() == UsdGeom.Tokens.invisible
    return stage


def _visibility(stage: Usd.Stage, path: str) -> str:
    return UsdGeom.Imageable(stage.GetPrimAtPath(path)).ComputeVisibility()


def test_without_session_leaves_out_the_rig_and_kits_hiding_of_the_stages_lights(lit: Usd.Stage):
    source = without_session(lit)
    assert not source.GetPrimAtPath(RIG)
    assert _visibility(source, SUN) == UsdGeom.Tokens.inherited
    flat = source.Flatten()
    assert not flat.GetPrimAtPath(RIG)
    assert "OmniKit_Viewport_LightRig" not in flat.ExportToString()
    assert not flat.GetPropertyAtPath(f"{SUN}.visibility")


def test_without_session_keeps_the_open_stages_layers_and_their_unsaved_edits(lit: Usd.Stage):
    source = without_session(lit)
    assert source.GetRootLayer() == lit.GetRootLayer()
    for path in ("/World/Unsaved", SUN, "/World/R", "/World/P", "/Sub"):
        assert source.GetPrimAtPath(path), path
    assert source.GetSessionLayer() != lit.GetSessionLayer()
    assert source.GetSessionLayer().anonymous
    assert source.GetSessionLayer().empty


def test_without_session_changes_nothing_of_the_open_stage(lit: Usd.Stage):
    lit.Unload("/World/P")
    before = {
        "session": lit.GetSessionLayer().ExportToString(),
        "root": lit.GetRootLayer().ExportToString(),
        "load_rules": lit.GetLoadRules(),
        "muted": lit.GetMutedLayers(),
        "session_layer": lit.GetSessionLayer(),
    }
    source = without_session(lit)
    source.Flatten()
    del source
    gc.collect()
    after = {
        "session": lit.GetSessionLayer().ExportToString(),
        "root": lit.GetRootLayer().ExportToString(),
        "load_rules": lit.GetLoadRules(),
        "muted": lit.GetMutedLayers(),
        "session_layer": lit.GetSessionLayer(),
    }
    assert after == before
    assert lit.GetRootLayer().dirty
    assert lit.GetPrimAtPath(f"{RIG}/Lights/DomeLight")
    assert _visibility(lit, SUN) == UsdGeom.Tokens.invisible


def test_without_session_carries_the_muted_layers_load_rules_mask_and_resolver_context(scene: Path):
    # Each leaves out a prim of its own: the mask /World/R, the muted sublayer /Sub, the unloaded payload its content.
    stage = Usd.Stage.OpenMasked(str(scene), Usd.StagePopulationMask(["/World/P", "/Sub"]))
    (sub,) = (layer for layer in stage.GetLayerStack() if layer.realPath.endswith("sub.usda"))
    stage.MuteLayer(sub.identifier)
    stage.Unload("/World/P")
    source = without_session(stage)
    assert source.GetPopulationMask() == stage.GetPopulationMask()
    assert not source.GetPrimAtPath("/World/R")
    assert source.GetMutedLayers() == stage.GetMutedLayers()
    assert not source.GetPrimAtPath("/Sub")
    assert source.GetLoadRules() == stage.GetLoadRules()
    assert not source.GetPrimAtPath("/World/P").IsLoaded()
    assert source.GetPathResolverContext() == stage.GetPathResolverContext()


def test_without_session_of_a_stage_never_saved(tmp_path: Path):
    # new_scene's stage has an anonymous root layer: no file, but the same layer, so its prims are there.
    stage = Usd.Stage.CreateInMemory()
    UsdLux.DistantLight.Define(stage, SUN)
    kits_default_mode(stage, tmp_path / "Default.usda")
    source = without_session(stage)
    assert source.GetRootLayer() == stage.GetRootLayer()
    assert source.GetPrimAtPath(SUN)
    assert _visibility(source, SUN) == UsdGeom.Tokens.inherited
    assert not source.GetPrimAtPath(RIG)


# ----- refresh_written and refresh -----


def test_a_held_layer_is_read_again_after_its_file_is_written(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    _rewrite(other, "/Written")
    assert refresh_written(stage, other.as_posix()) == [held]
    assert held.GetPrimAtPath("/Written")


def test_a_held_layer_whose_file_is_gone_is_kept(stage: Usd.Stage, scene: Path):
    other = scene.parent / "other.usda"
    held = Sdf.Layer.FindOrOpen(str(other))
    other.unlink()
    assert refresh(stage, [held]) == []
    assert held.GetPrimAtPath("/Other")


def test_nothing_held_nothing_read(stage: Usd.Stage, scene: Path):
    assert refresh_written(stage, str(scene.parent / "new.usdc")) == []


def test_refresh_leaves_the_open_stages_layers_and_anonymous_ones(stage: Usd.Stage, scene: Path):
    stage.DefinePrim("/World/Unsaved")
    # Opened from a file but with no file of its own, so with no unsaved edits: reading it again would empty it.
    anonymous = Sdf.Layer.OpenAsAnonymous(str(scene.parent / "other.usda"))
    assert not anonymous.dirty
    assert refresh(stage, [*stage.GetUsedLayers(), anonymous]) == []
    assert stage.GetPrimAtPath("/World/Unsaved")
    assert anonymous.GetPrimAtPath("/Other")


# ----- layers gone while they are walked -----


def _gone(path: Path) -> list[Sdf.Layer]:
    """The handles GetLoadedLayers gave for a stage opened from path, once the stage has gone: weak, so they expire with
    it, as a stage Python's garbage collector frees during a walk takes its layers with it (CI's Python 3.14, #85)."""
    opened = Usd.Stage.Open(str(path))
    used = opened.GetUsedLayers()
    handles = [layer for layer in Sdf.Layer.GetLoadedLayers() if layer in used]
    del opened, used
    gc.collect()
    assert handles
    assert not any(handles), "a layer outlived its stage"
    return handles


def test_a_layer_gone_while_kits_layers_are_walked_is_passed_over(
    stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch
):
    other = scene.parent / "other.usda"
    gone = _gone(other)
    loaded = Sdf.Layer.GetLoadedLayers
    monkeypatch.setattr(Sdf.Layer, "GetLoadedLayers", staticmethod(lambda: [*gone, *loaded()]))
    for saving in (False, True):
        assert write_refusal(stage, str(other), saving=saving) is None
    assert refresh_written(stage, str(other)) == []
    assert refresh(stage, gone) == []
    # The walk goes on past them.
    held = Sdf.Layer.FindOrOpen(str(other))
    Sdf.CreatePrimInLayer(held, "/Edit")
    refusal = write_refusal(stage, str(other))
    assert refusal is not None
    assert "unsaved edits" in refusal


def test_a_layer_gone_after_it_is_named_is_passed_over(stage: Usd.Stage, scene: Path, monkeypatch: pytest.MonkeyPatch):
    other = scene.parent / "other.usda"
    gone = _gone(other)
    # Handles the name check gives back from Kit's layers (any_name is for the open stage's own), then gone before
    # their edits are read or they are read again.
    named = layers._layers_at

    def then_gone(path: str, found: list[Sdf.Layer], *, any_name: bool = False) -> list[Sdf.Layer]:
        return named(path, found, any_name=any_name) + ([] if any_name else gone)

    monkeypatch.setattr(layers, "_layers_at", then_gone)
    for saving in (False, True):
        assert write_refusal(stage, str(other), saving=saving) is None
    assert refresh_written(stage, str(other)) == []
