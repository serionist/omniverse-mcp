"""viewport_light's decisions: the mode in effect, what the legacy camera-light switch does, and which lights are the
stage's own."""

from types import SimpleNamespace
from typing import ClassVar

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdLux

from ovmcp.core import lighting
from ovmcp.core.isolation import is_light
from ovmcp.core.lighting import LIGHT_RIG, camera_light_switch, current_mode, scene_lights


@pytest.mark.parametrize(
    ("flag", "menu", "mode"),
    [
        (True, None, "camera"),
        (True, "Default", "camera"),
        (True, "stage", "camera"),
        (False, "camera", "stage"),  # the menu's record is stale: the flag is off
        (False, None, "stage"),
        (False, "", "stage"),
        (False, "stage", "stage"),
        (False, "off", "off"),
        (False, "Default", "Default"),
        (False, "Grey Studio", "Grey Studio"),
    ],
)
def test_current_mode(flag, menu, mode):
    assert current_mode(flag, menu) == mode


@pytest.mark.parametrize(
    ("enabled", "current", "sets"),
    [
        (True, "stage", "camera"),
        (True, "Default", "camera"),
        (True, "camera", "camera"),
        (False, "camera", "stage"),
        (False, "Default", None),  # a rig stays; only the flag is cleared, as before
        (False, "stage", None),
        (False, "off", None),
    ],
)
def test_camera_light_switch(enabled, current, sets):
    assert camera_light_switch(enabled, current) == sets


# ---- the stage's own lights, never a light rig's (#117) ----

# Kit's Default rig, as omni.kit.viewport.menubar.lighting 107.3 ships it (data/usd/Default.usda), cut to its prims.
RIG_FILE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Y"
)

def Xform "World"
{
    def Xform "Lights"
    {
        def DomeLight "DomeLight"
        {
            float inputs:intensity = 1
        }

        def DistantLight "DistantLight"
        {
            float inputs:intensity = 1
        }
    }
}
"""
RIG_LIGHTS = [f"{LIGHT_RIG}/Lights/DomeLight", f"{LIGHT_RIG}/Lights/DistantLight"]


def _stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Box")
    return stage


def kit_rig(stage: Usd.Stage) -> Usd.Prim:
    """A rig mode's rig, as Kit's lighting menu authors it: an over in the session layer, referencing the rig's file
    (its actions.py, _set_lighting_mode)."""
    rig_file = Sdf.Layer.CreateAnonymous("Default.usda")
    rig_file.ImportFromString(RIG_FILE)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        rig = stage.OverridePrim(LIGHT_RIG)
        rig.GetReferences().SetReferences([Sdf.Reference(rig_file.identifier)])
    return rig


def _paths(prims) -> list[str]:
    return [str(prim.GetPath()) for prim in prims]


def _instance(stage: Usd.Stage, path: str, source: str) -> Usd.Prim:
    prim = stage.DefinePrim(path)
    prim.GetReferences().AddInternalReference(source)
    prim.SetInstanceable(True)
    return prim


def test_a_light_rig_is_not_the_stages():
    stage = _stage()
    kit_rig(stage)
    # What the get counted before: the rig's lights, reached by a plain walk (#105's live run).
    assert _paths(p for p in stage.Traverse() if is_light(p)) == RIG_LIGHTS

    assert list(scene_lights(stage)) == []

    UsdLux.DistantLight.Define(stage, "/World/Sun")
    assert _paths(scene_lights(stage)) == ["/World/Sun"]


def test_a_rig_kit_has_taken_away_adds_nothing():
    # Modes stage, camera and off clear the over's references and leave the over, which composes to nothing.
    stage = _stage()
    rig = kit_rig(stage)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        rig.GetReferences().SetReferences([])

    assert not stage.GetPrimAtPath(LIGHT_RIG).IsDefined()
    assert list(scene_lights(stage)) == []


def _lamps(stage: Usd.Stage) -> None:
    """Lamps as instanced assets: a lamp of a shade, a bulb and an inactive spare; a room of two lamps and a ceiling
    light, itself instanced twice; three lamps on their own; an instance that is itself a light; a light of the stage's
    own; and the rig."""
    stage.CreateClassPrim("/_Lamp")
    UsdGeom.Cube.Define(stage, "/_Lamp/Shade")
    UsdLux.SphereLight.Define(stage, "/_Lamp/Bulb")
    UsdLux.SphereLight.Define(stage, "/_Lamp/Spare").GetPrim().SetActive(False)
    stage.CreateClassPrim("/_Room")
    _instance(stage, "/_Room/LampA", "/_Lamp")
    _instance(stage, "/_Room/LampB", "/_Lamp")
    UsdLux.RectLight.Define(stage, "/_Room/Ceiling")
    _instance(stage, "/World/Room1", "/_Room")
    _instance(stage, "/World/Room2", "/_Room")
    for i in range(3):
        _instance(stage, f"/World/Lamp{i}", "/_Lamp")
    stage.CreateClassPrim("/_Sun")
    UsdLux.DistantLight.Define(stage, "/_Sun/Source")
    _instance(stage, "/World/Sun", "/_Sun/Source")
    UsdLux.DomeLight.Define(stage, "/World/Sky")
    kit_rig(stage)


class _CountingRange:
    """Usd.PrimRange, noting the prim each range starts at, for the walk's prototypes."""

    starts: ClassVar[list[str]] = []
    Stage = staticmethod(Usd.PrimRange.Stage)

    def __new__(cls, prim: Usd.Prim) -> Usd.PrimRange:
        cls.starts.append(str(prim.GetPath()))
        return Usd.PrimRange(prim)


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The prims the walk started a range at: the prototypes it walked."""
    _CountingRange.starts = []
    monkeypatch.setattr(lighting, "Usd", SimpleNamespace(PrimRange=_CountingRange, Prim=Usd.Prim))
    return _CountingRange.starts


def test_lights_inside_instances_are_the_walk_inside_every_instances(counted):
    stage = _stage()
    _lamps(stage)
    every_copy = [
        p
        for p in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())
        if is_light(p) and not p.GetPath().HasPrefix(LIGHT_RIG)
    ]

    found = list(scene_lights(stage))

    assert _paths(found) == _paths(every_copy)
    assert _paths(found) == [
        "/World/Room1/LampA/Bulb",
        "/World/Room1/LampB/Bulb",
        "/World/Room1/Ceiling",
        "/World/Room2/LampA/Bulb",
        "/World/Room2/LampB/Bulb",
        "/World/Room2/Ceiling",
        "/World/Lamp0/Bulb",
        "/World/Lamp1/Bulb",
        "/World/Lamp2/Bulb",
        "/World/Sun",
        "/World/Sky",
    ]
    assert all(prim.IsInstanceProxy() for prim in found if prim.GetName() in ("Bulb", "Ceiling"))
    # The room's, the lamp's and the sun's prototypes, each once, for 2 rooms, 7 lamps and a sun.
    assert sorted(counted) == sorted(str(p.GetPath()) for p in stage.GetPrototypes())


def test_a_yes_or_no_stops_at_the_first_light(counted):
    stage = _stage()
    UsdLux.DistantLight.Define(stage, "/World/A_Sun")
    _lamps(stage)

    assert next(scene_lights(stage)).GetPath() == Sdf.Path("/World/A_Sun")
    assert counted == []  # no prototype walked
