"""set_variant_selection's and compare_prims' handlers against a usd-core stage (#155): a switch goes to the layer asked
for, its Fabric refresh leaves no active opinion in any layer, an error mid-refresh included, and compare_prims leaves
the session and root layers as they were.

handlers/usd_advanced.py is loaded from its file with the handlers' _utils, camera_feed and Kit's carb faked in
sys.modules, as tests/test_flatten_handler.py loads it; handlers/variants.py, the refresh, is the real one.
"""

import asyncio
import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Sdf, Usd

from .conftest import EXTENSION_ROOT
from .test_variants import AREA, write_files

HANDLERS = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers"


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


class Kit:
    """The stage and what the handlers see of Kit: Fabric Scene Delegate's setting, and each app update, which can look
    at the stage or fail."""

    def __init__(self, stage: Usd.Stage) -> None:
        self.stage = stage
        self.fabric = False
        self.updates = 0
        self.on_update: Callable[[int], None] = lambda _n: None

    async def next_update(self) -> None:
        self.updates += 1
        self.on_update(self.updates)
        await asyncio.sleep(0)


@pytest.fixture
def files(tmp_path: Path) -> Path:
    return write_files(tmp_path)


@pytest.fixture
def stage(files: Path) -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World")
    stage.DefinePrim("/World/Site").GetReferences().AddReference(str(files / "site.usda"), "/Site")
    return stage


@pytest.fixture
def kit(stage: Usd.Stage) -> Kit:
    return Kit(stage)


@pytest.fixture
def seen() -> list[list[str]]:
    """The children of each prim compare_prims measured, in order."""
    return []


@pytest.fixture
def handler(kit: Kit, seen: list[list[str]], monkeypatch: pytest.MonkeyPatch) -> Any:
    def stats(prim: Usd.Prim) -> dict[str, int]:
        names = [child.GetName() for child in prim.GetChildren()]
        seen.append(names)
        return {"total_faces": len(names), "total_vertices": 0, "total_triangles": 0, "mesh_count": len(names)}

    settings = SimpleNamespace(get_as_bool=lambda key: kit.fabric if key == "/app/useFabricSceneDelegate" else False)
    carb_settings = _module("carb.settings", get_settings=lambda: settings)
    fakes = {
        "carb": _module("carb", settings=carb_settings),
        "carb.settings": carb_settings,
        "handlers_under_test": _module("handlers_under_test", __path__=[str(HANDLERS)]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            _collect_materials=lambda _prim: [],
            _compute_mesh_stats=stats,
            _get_stage=lambda: kit.stage,
            _next_update=kit.next_update,
        ),
        "handlers_under_test.camera_feed": _module("handlers_under_test.camera_feed", without_kept_feed=None),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "handlers_under_test.variants", raising=False)
    spec = importlib.util.spec_from_file_location("handlers_under_test.usd_advanced", HANDLERS / "usd_advanced.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _switch(handler: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(handler.handle_set_variant_selection({"prim_path": AREA, "variant_set": "state", **body}))


def _texts(stage: Usd.Stage) -> tuple[str, str]:
    return stage.GetSessionLayer().ExportToString(), stage.GetRootLayer().ExportToString()


def _active_opinions(stage: Usd.Stage) -> list[str]:
    """Every active field the stage's own layers hold, by layer and path."""
    found: list[str] = []

    def walk(spec: Sdf.PrimSpec) -> None:
        if spec.HasActive():
            found.append(f"{spec.layer.identifier} {spec.path} active={spec.active}")
        for child in spec.nameChildren:
            walk(child)

    for layer in stage.GetLayerStack(includeSessionLayers=True):
        for root in layer.rootPrims:
            walk(root)
    return found


def _selection(stage: Usd.Stage) -> str:
    return stage.GetPrimAtPath(AREA).GetVariantSet("state").GetVariantSelection()


# ---- set_variant_selection ----


def test_a_switch_in_the_session_layer_leaves_the_root_layer_and_says_what_the_files_select(handler, kit):
    root = kit.stage.GetRootLayer().ExportToString()

    r = _switch(handler, variant_name="open", layer="session")

    assert r["status"] == "success", r
    assert r["result"] == {
        "prim_path": AREA,
        "variant_set": "state",
        "old_selection": "closed",
        "new_selection": "open",
        "available_variants": ["closed", "open"],
        "layer": "session",
        "written_to": "Kit's session layer",
        "files_select": "closed",
    }
    assert kit.stage.GetRootLayer().ExportToString() == root
    assert _selection(kit.stage) == "open"


def test_a_switch_without_a_layer_goes_to_the_edit_target_as_an_older_server_expects(handler, kit):
    session = kit.stage.GetSessionLayer().ExportToString()

    r = _switch(handler, variant_name="open")

    assert r["status"] == "success", r
    assert r["result"]["layer"] == "edit_target"
    assert r["result"]["written_to"] == "the stage's root layer"
    assert kit.stage.GetSessionLayer().ExportToString() == session
    assert kit.stage.GetRootLayer().GetPrimAtPath(AREA).variantSelections["state"] == "open"


def test_a_clear_in_the_session_layer_gives_the_files_selection_back(handler, kit):
    assert _switch(handler, variant_name="open", layer="session")["status"] == "success"

    r = _switch(handler, variant_name="", layer="session")

    assert r["status"] == "success", r
    assert (r["result"]["old_selection"], r["result"]["new_selection"]) == ("open", "closed")
    assert _selection(kit.stage) == "closed"


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"variant_name": "ajar", "layer": "session"}, "no variant 'ajar'"),
        ({"variant_name": "open", "layer": "file"}, "layer must be session or edit_target"),
        ({"layer": "session"}, "variant_name is required"),
    ],
)
def test_a_wrong_switch_is_refused_with_nothing_written(handler, kit, body, says):
    texts = _texts(kit.stage)

    r = _switch(handler, **body)

    assert r["status"] == "error", r
    assert says in r["error"]
    assert _texts(kit.stage) == texts


def test_the_edit_target_is_refused_under_a_session_selection(handler, kit):
    assert _switch(handler, variant_name="open", layer="session")["status"] == "success"
    root = kit.stage.GetRootLayer().ExportToString()

    r = _switch(handler, variant_name="closed", layer="edit_target")

    assert r["status"] == "error", r
    assert "Kit's session layer holds" in r["error"]
    assert kit.stage.GetRootLayer().ExportToString() == root


def test_a_switch_on_an_instance_notes_its_prototype(handler, kit, files):
    for name in ("A", "B"):
        instance = kit.stage.DefinePrim(f"/World/{name}")
        instance.GetReferences().AddReference(str(files / "area.usda"))
        instance.SetInstanceable(True)

    r = asyncio.run(
        handler.handle_set_variant_selection(
            {"prim_path": "/World/A", "variant_set": "state", "variant_name": "open", "layer": "session"}
        )
    )

    assert r["status"] == "success", r
    assert "prototype of its own" in r["result"]["note"]


@pytest.mark.parametrize("layer", ["session", "edit_target"])
def test_the_fabric_refresh_hides_the_prim_in_the_session_layer_and_leaves_no_active_opinion(handler, kit, layer):
    # The refresh wrote active = false then true at the edit target, the user's file, and left the true there (#155).
    kit.fabric = True
    hidden: list[bool] = []
    kit.on_update = lambda _n: hidden.append(not kit.stage.GetPrimAtPath(AREA).IsActive())

    r = _switch(handler, variant_name="open", layer=layer)

    assert r["status"] == "success", r
    assert any(hidden), "the refresh never hid the prim"
    assert hidden[-1] is False
    assert _active_opinions(kit.stage) == []
    assert kit.stage.GetPrimAtPath(AREA).IsActive()


def test_an_error_mid_refresh_leaves_the_prim_active_and_no_active_opinion(handler, kit):
    kit.fabric = True

    def fail(n: int) -> None:
        if n == 4:
            raise RuntimeError("Kit stopped")

    kit.on_update = fail

    with pytest.raises(RuntimeError, match="Kit stopped"):
        _switch(handler, variant_name="open", layer="session")

    assert _active_opinions(kit.stage) == []
    assert kit.stage.GetPrimAtPath(AREA).IsActive()


def test_without_fabric_the_switch_only_waits(handler, kit):
    hidden: list[bool] = []
    kit.on_update = lambda _n: hidden.append(not kit.stage.GetPrimAtPath(AREA).IsActive())

    assert _switch(handler, variant_name="open", layer="session")["status"] == "success"

    assert hidden
    assert not any(hidden)


def test_a_clear_of_nothing_writes_nothing_and_needs_no_refresh(handler, kit):
    kit.fabric = True
    texts = _texts(kit.stage)

    r = _switch(handler, variant_name="", layer="edit_target")

    assert r["status"] == "success", r
    assert _texts(kit.stage) == texts


# ---- compare_prims ----


def _compare(handler: Any, a: str = "closed", b: str = "open", path: str = AREA) -> dict[str, Any]:
    return asyncio.run(
        handler.handle_compare_prims({"prim_path": path, "variant_set": "state", "variant_a": a, "variant_b": b})
    )


@pytest.mark.parametrize("held", [None, "open", ""], ids=["nothing", "a selection", "a blocked one"])
def test_compare_prims_measures_each_variant_and_leaves_both_layers_as_they_were(handler, kit, seen, held):
    if held is not None:
        Sdf.CreatePrimInLayer(kit.stage.GetSessionLayer(), "/World/Elsewhere")  # a spec the restore must keep
        spec = Sdf.CreatePrimInLayer(kit.stage.GetSessionLayer(), AREA)
        if held:
            spec.variantSelections["state"] = held
        else:
            spec.BlockVariantSelection("state")
    texts = _texts(kit.stage)

    r = _compare(handler)

    assert r["status"] == "success", r
    assert seen == [["Wall"], ["Door"]]
    assert r["result"]["a"]["label"] == f"{AREA} [state=closed]"
    assert _texts(kit.stage) == texts


@pytest.mark.parametrize(("a", "b", "says"), [("closed", "ajar", "no variant 'ajar'"), ("x", "open", "no variant 'x'")])
def test_compare_prims_refuses_an_unknown_variant_with_nothing_switched(handler, kit, seen, a, b, says):
    # An unknown name measured the prim with none of the set's variants (#155).
    texts = _texts(kit.stage)

    r = _compare(handler, a, b)

    assert r["status"] == "error", r
    assert says in r["error"]
    assert seen == []
    assert _texts(kit.stage) == texts


def test_compare_prims_refuses_a_prim_inside_an_instance(handler, kit, seen, files):
    holder = kit.stage.DefinePrim("/World/Holder")
    holder.GetReferences().AddReference(str(files / "site.usda"), "/Site")
    holder.SetInstanceable(True)

    r = _compare(handler, path="/World/Holder/Area")

    assert r["status"] == "error", r
    assert "inside the instance /World/Holder" in r["error"]
    assert seen == []


def test_compare_prims_puts_the_layers_back_when_a_measure_fails(handler, kit, monkeypatch):
    texts = _texts(kit.stage)

    def broken(_prim: Usd.Prim) -> dict[str, int]:
        raise RuntimeError("a broken mesh")

    monkeypatch.setattr(handler, "_compute_mesh_stats", broken)

    with pytest.raises(RuntimeError, match="a broken mesh"):
        _compare(handler)
    assert _texts(kit.stage) == texts


def test_compare_prims_writes_its_switches_in_the_session_layer_only(handler, kit):
    root = kit.stage.GetRootLayer().ExportToString()
    during: list[str] = []
    kit.on_update = lambda _n: during.append(kit.stage.GetRootLayer().ExportToString())

    assert _compare(handler)["status"] == "success"

    assert set(during) == {root}
