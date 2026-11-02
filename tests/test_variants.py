"""A prim's variant sets, and a switch in one layer that the snapshot puts back exactly (#155), on usd-core.

The case: an area's file with variant sets, brought in by a site file the stage references, so the switched prim has
no spec in the root layer; a check switches in the session layer and must leave every file as it found it.
"""

from pathlib import Path

import pytest
from pxr import Sdf, Usd

from ovmcp.core import variants
from ovmcp.core.usd import select
from ovmcp.core.variants import Snapshot, deactivate, switch, variant_refusal, variant_sets

AREA = "/World/Site/Area"

_AREA_USDA = """#usda 1.0
(
    defaultPrim = "Area"
)

def Xform "Area" (
    variants = {
        string state = "closed"
    }
    prepend variantSets = ["state", "lod"]
)
{
    variantSet "state" = {
        "closed" {
            def Cube "Wall"
            {
            }
        }
        "open" {
            def Sphere "Door"
            {
            }
        }
    }
    variantSet "lod" = {
        "high" {
        }
        "low" {
        }
    }
}
"""


def _write(path: Path, text: str) -> Path:
    layer = Sdf.Layer.CreateAnonymous(".usda")
    layer.ImportFromString(text)
    assert layer.Export(str(path))
    return path


def write_files(folder: Path) -> Path:
    """area.usda, with the sets state (closed selected) and lod (none selected), and site.usda, whose /Site/Area
    references it, written to folder."""
    _write(folder / "area.usda", _AREA_USDA)
    _write(
        folder / "site.usda",
        '#usda 1.0\ndef Xform "Site"\n{\n    def "Area" (\n        prepend references = @./area.usda@\n    )\n    {\n'
        "    }\n}\n",
    )
    return folder


@pytest.fixture
def files(tmp_path: Path) -> Path:
    return write_files(tmp_path)


@pytest.fixture
def stage(files: Path) -> Usd.Stage:
    """A stage whose /World/Site references site.usda: the area's prim is in no spec of the root layer."""
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World")
    stage.DefinePrim("/World/Site").GetReferences().AddReference(str(files / "site.usda"), "/Site")
    return stage


def _selection(stage: Usd.Stage, path: str = AREA, name: str = "state") -> str:
    return stage.GetPrimAtPath(path).GetVariantSet(name).GetVariantSelection()


def _children(stage: Usd.Stage, path: str = AREA) -> list[str]:
    return [child.GetName() for child in stage.GetPrimAtPath(path).GetChildren()]


def _texts(stage: Usd.Stage) -> tuple[str, str]:
    return stage.GetSessionLayer().ExportToString(), stage.GetRootLayer().ExportToString()


# ---- the switch ----


def test_a_switch_in_the_session_layer_shows_and_leaves_the_root_layer_as_it_was(stage: Usd.Stage):
    root = stage.GetRootLayer().ExportToString()

    switch(stage, {Sdf.Path(AREA): {"state": "open"}}, stage.GetSessionLayer())

    assert _selection(stage) == "open"
    assert _children(stage) == ["Door"]
    assert stage.GetRootLayer().ExportToString() == root
    assert variants.selections_of(stage.GetSessionLayer(), AREA) == {"state": "open"}


def test_a_switch_at_the_edit_target_writes_the_root_layer(stage: Usd.Stage):
    session = stage.GetSessionLayer().ExportToString()

    switch(stage, {Sdf.Path(AREA): {"state": "open"}}, stage.GetRootLayer())

    assert _selection(stage) == "open"
    assert variants.selections_of(stage.GetRootLayer(), AREA) == {"state": "open"}
    assert stage.GetSessionLayer().ExportToString() == session


def test_a_clear_gives_the_files_selection_back_and_leaves_the_spec_the_snapshot_removes(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    before = session.ExportToString()
    switched = switch(stage, {Sdf.Path(AREA): {"state": "open"}}, session)

    switch(stage, {Sdf.Path(AREA): {"state": ""}}, session)

    assert _selection(stage) == "closed"
    assert variants.selections_of(session, AREA) == {}
    switched.restore()
    assert session.ExportToString() == before


def test_a_clear_of_nothing_at_the_edit_target_writes_nothing(stage: Usd.Stage):
    # Usd's ClearVariantSelection() writes an over for each prim on the way into the root layer, the user's file, and
    # clears nothing (round 1, P3).
    root = stage.GetRootLayer().ExportToString()

    snapshot = switch(stage, {Sdf.Path(AREA): {"state": ""}}, stage.GetRootLayer())

    assert stage.GetRootLayer().ExportToString() == root
    assert not snapshot.wrote
    assert _selection(stage) == "closed"


def test_a_switch_of_many_prims_and_sets_is_one_call(stage: Usd.Stage, files: Path):
    stage.DefinePrim("/World/Other").GetReferences().AddReference(str(files / "area.usda"))
    session = stage.GetSessionLayer()
    before = session.ExportToString()

    snapshot = switch(
        stage,
        {Sdf.Path(AREA): {"state": "open", "lod": "low"}, Sdf.Path("/World/Other"): {"state": "open"}},
        session,
    )

    found = (_selection(stage), _selection(stage, name="lod"), _selection(stage, "/World/Other"))
    assert found == ("open", "low", "open")
    snapshot.restore()
    assert session.ExportToString() == before


def test_a_batch_is_refused_whole_when_one_switch_is_wrong(stage: Usd.Stage, files: Path):
    stage.DefinePrim("/World/Other").GetReferences().AddReference(str(files / "area.usda"))
    texts = _texts(stage)

    with pytest.raises(ValueError, match="no variant 'ajar'"):
        switch(
            stage,
            {Sdf.Path(AREA): {"state": "open"}, Sdf.Path("/World/Other"): {"state": "ajar"}},
            stage.GetSessionLayer(),
        )

    assert _texts(stage) == texts
    assert _selection(stage) == "closed"


def test_a_switch_of_a_prim_not_there_is_refused(stage: Usd.Stage):
    with pytest.raises(ValueError, match="Prim not found: /World/Nothing"):
        switch(stage, {Sdf.Path("/World/Nothing"): {"state": "open"}}, stage.GetSessionLayer())


def test_a_switch_on_an_instance_notes_its_prototype_of_its_own(stage: Usd.Stage, files: Path):
    for name in ("A", "B"):
        instance = stage.DefinePrim(f"/World/{name}")
        instance.GetReferences().AddReference(str(files / "area.usda"))
        instance.SetInstanceable(True)
    assert len(stage.GetPrototypes()) == 1

    snapshot = switch(stage, {Sdf.Path("/World/A"): {"state": "open"}}, stage.GetSessionLayer())

    assert len(stage.GetPrototypes()) == 2
    assert len(snapshot.notes) == 1
    assert "/World/A is an instance" in snapshot.notes[0]
    assert "prototype of its own" in snapshot.notes[0]


# ---- what is refused ----


def test_an_unknown_set_is_refused_with_the_sets_there(stage: Usd.Stage):
    why = variant_refusal(stage.GetPrimAtPath(AREA), "colour", "red", stage.GetSessionLayer())

    assert why is not None
    assert "has no variant set 'colour'" in why
    assert "state, lod" in why


def test_an_unknown_variant_is_refused_with_the_variants_there(stage: Usd.Stage):
    why = variant_refusal(stage.GetPrimAtPath(AREA), "state", "ajar", stage.GetSessionLayer())

    assert why is not None
    assert "no variant 'ajar'" in why
    assert "closed, open" in why


def test_a_clear_takes_no_variant_name_but_still_a_known_set(stage: Usd.Stage):
    prim = stage.GetPrimAtPath(AREA)

    assert variant_refusal(prim, "state", "", stage.GetSessionLayer()) is None
    assert variant_refusal(prim, "colour", "", stage.GetSessionLayer()) is not None


def test_a_prim_inside_an_instance_is_refused_naming_the_instance(stage: Usd.Stage, files: Path):
    holder = stage.DefinePrim("/World/Holder")
    holder.GetReferences().AddReference(str(files / "site.usda"), "/Site")
    holder.SetInstanceable(True)
    proxy = stage.GetPrimAtPath("/World/Holder/Area")
    assert proxy.IsInstanceProxy()

    why = variant_refusal(proxy, "state", "open", stage.GetSessionLayer())

    assert why is not None
    assert "inside the instance /World/Holder" in why
    with pytest.raises(ValueError, match="inside the instance /World/Holder"):
        switch(stage, {proxy.GetPath(): {"state": "open"}}, stage.GetSessionLayer())


def test_an_unknown_set_on_a_prim_whose_payload_isnt_loaded_says_so(stage: Usd.Stage, files: Path):
    paid = stage.DefinePrim("/World/Paid")
    paid.GetPayloads().AddPayload(str(files / "area.usda"))
    stage.Unload("/World/Paid")

    why = variant_refusal(stage.GetPrimAtPath("/World/Paid"), "state", "open", stage.GetSessionLayer())

    assert why is not None
    assert "payload isn't loaded" in why


def test_the_edit_target_is_refused_under_a_session_selection(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    switch(stage, {Sdf.Path(AREA): {"state": "open"}}, session)
    root = stage.GetRootLayer().ExportToString()

    why = variant_refusal(stage.GetPrimAtPath(AREA), "state", "closed", stage.GetRootLayer())

    assert why is not None
    assert "Kit's session layer holds" in why
    assert 'variant_name=""' in why
    with pytest.raises(ValueError, match="Kit's session layer holds"):
        switch(stage, {Sdf.Path(AREA): {"state": "closed"}}, stage.GetRootLayer())
    assert stage.GetRootLayer().ExportToString() == root
    # Another set of the prim isn't held there, so it may go to the edit target.
    assert variant_refusal(stage.GetPrimAtPath(AREA), "lod", "low", stage.GetRootLayer()) is None


# ---- the snapshot ----


def _held(layer: Sdf.Layer, before: str) -> None:
    """What the session layer holds for the area before the switch: nothing, a bare over, a blocked selection, a
    selection of its own, or a selection and an active field."""
    if before == "nothing":
        return
    spec = Sdf.CreatePrimInLayer(layer, AREA)
    if before == "blocked":
        spec.BlockVariantSelection("state")
    elif before in ("named", "active"):
        select(spec, "state", "open")
    if before == "active":
        spec.active = True


@pytest.mark.parametrize("before", ["nothing", "bare over", "blocked", "named", "active"])
@pytest.mark.parametrize("name", ["open", "closed", ""])
def test_a_snapshot_puts_the_session_layer_back_exactly(stage: Usd.Stage, before: str, name: str):
    session = stage.GetSessionLayer()
    _held(session, before)
    text = session.ExportToString()
    held = variants.selections_of(session, AREA)

    snapshot = switch(stage, {Sdf.Path(AREA): {"state": name}}, session)
    snapshot.restore()

    assert session.ExportToString() == text
    assert variants.selections_of(session, AREA) == held


def test_a_snapshot_keeps_a_spec_another_edit_filled_meanwhile(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    snapshot = switch(stage, {Sdf.Path(AREA): {"state": "open"}}, session)
    Sdf.CreatePrimInLayer(session, "/World/Site/Area/Kept")

    snapshot.restore()

    assert session.GetPrimAtPath("/World/Site/Area/Kept")
    assert variants.selections_of(session, AREA) == {}


def test_deactivate_hides_the_prims_in_the_layer_and_its_snapshot_leaves_no_active_opinion(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    text = session.ExportToString()

    hidden = deactivate(session, [Sdf.Path(AREA)])

    assert not stage.GetPrimAtPath(AREA).IsActive()
    hidden.restore()
    assert stage.GetPrimAtPath(AREA).IsActive()
    assert session.ExportToString() == text


def test_deactivate_puts_back_an_active_field_that_was_there(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    Sdf.CreatePrimInLayer(session, AREA).active = True
    text = session.ExportToString()

    deactivate(session, [Sdf.Path(AREA)]).restore()

    assert session.ExportToString() == text


@pytest.mark.parametrize(
    ("kit_version", "needed"),
    [
        ("110.4.0+feature.386251.187cf21b.gl", False),  # Isaac Sim 6.2, measured: the switch shows without it
        ("111.0.0", False),
        ("107.3.1+release.2134.af0b2bba.gl", True),  # Isaac Sim 5.1, not measured
        ("unknown", True),
        ("", True),
    ],
)
def test_the_fabric_toggle_is_needed_before_kit_110_and_wherever_the_version_is_unknown(kit_version: str, needed: bool):
    assert variants.toggle_needed(kit_version) is needed


def test_top_most_leaves_out_a_prim_under_another(stage: Usd.Stage):
    paths = [Sdf.Path("/World/Site/Area"), Sdf.Path("/World/Site"), Sdf.Path("/World/Other"), Sdf.Path("/World/Site")]

    assert variants.top_most(paths) == [Sdf.Path("/World/Site"), Sdf.Path("/World/Other")]


def test_a_snapshot_of_nothing_restores_nothing():
    layer = Sdf.Layer.CreateAnonymous()
    Snapshot(layer).restore()
    assert layer.ExportToString() == Sdf.Layer.CreateAnonymous().ExportToString()


# ---- what the prim's sets say ----


def test_variant_sets_names_the_layer_holding_each_selection(stage: Usd.Stage):
    switch(stage, {Sdf.Path(AREA): {"lod": "low"}}, stage.GetSessionLayer())

    sets = variant_sets(stage.GetPrimAtPath(AREA))

    assert [(s.name, s.selection, s.options, s.layer) for s in sets] == [
        ("state", "closed", ("closed", "open"), "area.usda"),
        ("lod", "low", ("high", "low"), "session"),
    ]
    line = variants.format_variant_sets(sets)
    assert line == "state: closed [closed, open] (area.usda); lod: low [high, low] (session)"


def test_variant_sets_names_the_root_layer_none_and_a_blocked_selection(stage: Usd.Stage):
    switch(stage, {Sdf.Path(AREA): {"state": "open"}}, stage.GetRootLayer())
    Sdf.CreatePrimInLayer(stage.GetSessionLayer(), AREA).BlockVariantSelection("lod")

    sets = variant_sets(stage.GetPrimAtPath(AREA))

    assert variants.format_variant_sets(sets) == "state: open [closed, open] (root); lod: none [high, low] (session)"


def test_a_prim_without_sets_has_none(stage: Usd.Stage):
    sets = variant_sets(stage.GetPrimAtPath("/World"))

    assert sets == []
    assert variants.format_variant_sets(sets) == "[]"


def test_a_set_nothing_selects_has_no_layer(stage: Usd.Stage):
    lod = variant_sets(stage.GetPrimAtPath(AREA))[1]

    assert (lod.selection, lod.layer) == ("", None)
    assert variants.format_variant_sets([lod]) == "lod: none [high, low]"


def test_beneath_gives_what_the_files_select_under_the_layer_written(stage: Usd.Stage):
    session, root = stage.GetSessionLayer(), stage.GetRootLayer()
    prim = stage.GetPrimAtPath(AREA)
    switch(stage, {Sdf.Path(AREA): {"state": "open"}}, root)

    assert variants.beneath(prim, "state", session) == "open"
    assert variants.beneath(prim, "state", root) == "closed"
    assert variants.beneath(prim, "lod", session) is None


def test_session_selections_lists_what_a_save_leaves_out(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    switch(stage, {Sdf.Path(AREA): {"state": "open", "lod": "low"}}, session)
    Sdf.CreatePrimInLayer(session, "/World/Blocked").BlockVariantSelection("look")
    Sdf.CreatePrimInLayer(session, "/World/Bare")

    assert variants.session_selections(stage) == [
        "/World/Blocked look=none",
        "/World/Site/Area lod=low",
        "/World/Site/Area state=open",
    ]


def test_session_selections_of_an_empty_session_layer(stage: Usd.Stage):
    assert variants.session_selections(stage) == []
