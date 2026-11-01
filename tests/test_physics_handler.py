"""set_physics_properties' handler against a fake Kit, loaded as tests/test_force_handler.py loads
handlers/simulation.py, on a usd-core stage with the Kit-free core: the physics material it binds starts from the
body's own values, so a value left out stays as it is; /sim/state names the Kit app (#105)."""

import asyncio
from typing import Any

import pytest
from pxr import Sdf, Usd, UsdPhysics, UsdShade

from ovmcp.core import protocol

from .test_force_handler import BOX, FakeKit, load_simulation

OWN = "/World/PhysicsMaterials/Box_PhysMat"


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def simulation(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_simulation(kit, monkeypatch)


def _set(simulation: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(simulation.handle_set_physics_properties({"prim_path": BOX, **body}))


def _values(kit: FakeKit, path: str = OWN) -> dict[str, float]:
    prim = kit.stage.GetPrimAtPath(path)
    return {
        name: round(float(prim.GetAttribute(f"physics:{name}").Get()), 6)
        for name in ("staticFriction", "dynamicFriction", "restitution")
    }


def _bound(kit: FakeKit) -> str:
    material, _ = UsdShade.MaterialBindingAPI(kit.stage.GetPrimAtPath(BOX)).ComputeBoundMaterial("physics")
    return str(material.GetPath())


def _material(stage: Usd.Stage, path: str, **values: Any) -> Usd.Prim:
    prim = UsdShade.Material.Define(stage, path).GetPrim()
    UsdPhysics.MaterialAPI.Apply(prim)
    for name, value in values.items():
        kind = Sdf.ValueTypeNames.Token if isinstance(value, str) else Sdf.ValueTypeNames.Float
        prim.CreateAttribute(name, kind).Set(value)
    return prim


def _bind(kit: FakeKit, material: Usd.Prim) -> None:
    UsdShade.MaterialBindingAPI.Apply(kit.stage.GetPrimAtPath(BOX)).Bind(
        UsdShade.Material(material), UsdShade.Tokens.weakerThanDescendants, "physics"
    )


def test_restitution_alone_on_a_bare_body_keeps_physx_s_default_friction(simulation, kit):
    # Its friction was left unauthored, which PhysX reads as 0: the probe's box slid 5.9 where a bare one slid 1.4.
    r = _set(simulation, restitution=0.0)

    assert r["status"] == "success", r
    assert _bound(kit) == OWN
    assert _values(kit) == {"staticFriction": 0.5, "dynamicFriction": 0.5, "restitution": 0.0}


def test_restitution_on_a_body_with_a_material_keeps_everything_else_it_held(simulation, kit):
    # The probe's Rubber, friction 0.9, went to 0; and a density and PhysX's combine mode went with it.
    rubber = _material(
        kit.stage,
        "/World/Mats/Rubber",
        **{
            "physics:staticFriction": 0.9,
            "physics:dynamicFriction": 0.9,
            "physics:density": 1000.0,
            "physxMaterial:frictionCombineMode": "max",
        },
    )
    rubber.AddAppliedSchema("PhysxMaterialAPI")
    _bind(kit, rubber)

    _set(simulation, restitution=0.2)

    own = kit.stage.GetPrimAtPath(OWN)
    assert _bound(kit) == OWN
    assert _values(kit) == {"staticFriction": 0.9, "dynamicFriction": 0.9, "restitution": 0.2}
    assert own.GetAttribute("physics:density").Get() == pytest.approx(1000.0)
    assert own.GetAttribute("physxMaterial:frictionCombineMode").Get() == "max"
    assert "PhysxMaterialAPI" in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert _values(kit, "/World/Mats/Rubber")["restitution"] == 0.0, "the material it replaced isn't written"


def test_friction_alone_keeps_a_bound_material_s_restitution(simulation, kit):
    # The probe's Bouncy, restitution 0.8, stopped bouncing.
    _bind(kit, _material(kit.stage, "/World/Mats/Bouncy", **{"physics:restitution": 0.8}))

    _set(simulation, friction=0.5)

    assert _values(kit) == {"staticFriction": 0.5, "dynamicFriction": 0.5, "restitution": 0.8}


def test_a_second_call_keeps_what_the_first_set(simulation, kit):
    _set(simulation, friction=0.7)
    _set(simulation, restitution=0.1)

    assert _values(kit) == {"staticFriction": 0.7, "dynamicFriction": 0.7, "restitution": 0.1}


def test_the_scene_s_default_material_stands_in_for_none(simulation, kit):
    default = _material(
        kit.stage, "/World/Mats/Default", **{"physics:staticFriction": 0.6, "physics:dynamicFriction": 0.4}
    )
    UsdShade.MaterialBindingAPI.Apply(kit.scene).Bind(
        UsdShade.Material(default), UsdShade.Tokens.weakerThanDescendants, "physics"
    )

    _set(simulation, restitution=0.3)

    assert _values(kit) == {"staticFriction": 0.6, "dynamicFriction": 0.4, "restitution": 0.3}


def test_both_given_are_written_as_given_and_echoed(simulation, kit):
    r = _set(simulation, friction=0.8, restitution=0.3)

    assert _values(kit) == {"staticFriction": 0.8, "dynamicFriction": 0.8, "restitution": 0.3}
    # #108's server prints these: the values given, a value left out null.
    assert (r["result"]["friction"], r["result"]["restitution"]) == (0.8, 0.3)
    assert _set(simulation, restitution=0.2)["result"]["friction"] is None


# ---- /sim/state names the Kit app (#105) ----


def test_sim_state_answers_the_kit_app_the_extension_kept(simulation, kit, monkeypatch):
    facts = {
        "kit_app_name": "Isaac-Sim Python",
        "kit_app_version": "6.2.0",
        "kit_version": "110.4.0+feature.386251.187cf21b.gl",
        "kit_os": "Windows-11-10.0.26300-SP0",
    }
    monkeypatch.setattr(protocol, "_kit_app", facts)

    r = asyncio.run(simulation.handle_sim_state({}))

    assert r["status"] == "success", r
    assert {key: r["result"][key] for key in facts} == facts
    assert r["result"]["state"] == "playing"
