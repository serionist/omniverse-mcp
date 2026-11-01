"""set_physics_properties' handler against a fake Kit, loaded as tests/test_force_handler.py loads
handlers/simulation.py, on a usd-core stage with the Kit-free core: the physics material it binds starts from the
body's own values, so a value left out stays as it is; /sim/state names the Kit app (#105). Each prim's material is
its own, the answer names it and the other prims a write reaches, and the older shared material goes once no prim
binds it (#113)."""

import asyncio
from typing import Any

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

from ovmcp.core import protocol

from .test_force_handler import BOX, FakeKit, load_simulation

OWN = "/World/Box/PhysMat"
# What an extension of 0.3.0 or older bound to every prim named Box.
OLD = "/World/PhysicsMaterials/Box_PhysMat"


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def simulation(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_simulation(kit, monkeypatch)


def _set(simulation: Any, path: str = BOX, **body: Any) -> dict[str, Any]:
    return asyncio.run(simulation.handle_set_physics_properties({"prim_path": path, **body}))


def _values(kit: FakeKit, path: str = OWN) -> dict[str, float]:
    prim = kit.stage.GetPrimAtPath(path)
    return {
        name: round(float(prim.GetAttribute(f"physics:{name}").Get()), 6)
        for name in ("staticFriction", "dynamicFriction", "restitution")
    }


def _bound(kit: FakeKit, path: str = BOX) -> str:
    material, _ = UsdShade.MaterialBindingAPI(kit.stage.GetPrimAtPath(path)).ComputeBoundMaterial("physics")
    return str(material.GetPath())


def _material(stage: Usd.Stage, path: str, **values: Any) -> Usd.Prim:
    prim = UsdShade.Material.Define(stage, path).GetPrim()
    UsdPhysics.MaterialAPI.Apply(prim)
    for name, value in values.items():
        kind = Sdf.ValueTypeNames.Token if isinstance(value, str) else Sdf.ValueTypeNames.Float
        prim.CreateAttribute(name, kind).Set(value)
    return prim


def _bind(kit: FakeKit, material: Usd.Prim, path: str = BOX) -> None:
    UsdShade.MaterialBindingAPI.Apply(kit.stage.GetPrimAtPath(path)).Bind(
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


# ---- each prim's own material (#113) ----


def test_the_answer_names_the_material_it_bound(simulation, kit):
    r = _set(simulation, friction=0.8)

    assert r["result"]["material"] == OWN
    assert _bound(kit) == OWN
    assert "also_changes" not in r["result"]
    assert "old_material" not in r["result"]


def test_mass_alone_binds_no_material_and_names_none(simulation, kit):
    r = _set(simulation, mass=2.0)

    assert r["status"] == "success", r
    assert "material" not in r["result"]
    assert not kit.stage.GetPrimAtPath(OWN)


def test_two_prims_of_one_name_keep_their_own_values(simulation, kit):
    # The issue's case: both fingers bound panda_leftfinger_PhysMat, so the second call wrote PhysX's 0.5 over 1.0.
    fingers = [f"/World/Franka_{n}/panda_leftfinger" for n in (1, 2)]
    for finger in fingers:
        kit.add_body(finger)

    _set(simulation, fingers[0], friction=1.0)
    _set(simulation, fingers[1], restitution=0.2)

    assert _values(kit, f"{fingers[0]}/PhysMat") == {"staticFriction": 1.0, "dynamicFriction": 1.0, "restitution": 0.0}
    assert _values(kit, f"{fingers[1]}/PhysMat") == {"staticFriction": 0.5, "dynamicFriction": 0.5, "restitution": 0.2}
    assert [_bound(kit, f) for f in fingers] == [f"{f}/PhysMat" for f in fingers]


def test_a_prim_on_an_older_shared_material_moves_off_it_and_the_last_one_deletes_it(simulation, kit):
    # An extension of 0.3.0 or older bound both boxes to one material, named for their last name.
    kit.add_body("/World/Shelf/Box")
    shared = _material(kit.stage, OLD, **{"physics:staticFriction": 0.7, "physics:dynamicFriction": 0.6})
    _bind(kit, shared)
    _bind(kit, shared, "/World/Shelf/Box")

    first = _set(simulation, restitution=0.2)

    assert _values(kit) == {"staticFriction": 0.7, "dynamicFriction": 0.6, "restitution": 0.2}
    assert _values(kit, OLD) == {"staticFriction": 0.7, "dynamicFriction": 0.6, "restitution": 0.0}
    assert _bound(kit, "/World/Shelf/Box") == OLD
    assert first["result"]["old_material"] == {"path": OLD, "kept": "1 prim still binds it: /World/Shelf/Box"}

    last = _set(simulation, "/World/Shelf/Box", friction=0.4)

    assert last["result"]["old_material"] == {"path": OLD, "deleted": [OLD, "/World/PhysicsMaterials"]}
    assert not kit.stage.GetPrimAtPath("/World/PhysicsMaterials")
    assert _values(kit, "/World/Shelf/Box/PhysMat") == {
        "staticFriction": 0.4,
        "dynamicFriction": 0.4,
        "restitution": 0.0,
    }


def test_a_copy_keeps_its_values_when_the_original_is_called(simulation, kit):
    _set(simulation, friction=0.9)
    layer = kit.stage.GetRootLayer()
    Sdf.CopySpec(layer, BOX, layer, "/World/Box_01")  # as clone_prim copies

    r = _set(simulation, friction=0.1)

    assert _values(kit, "/World/Box_01/PhysMat")["staticFriction"] == 0.9
    assert _bound(kit, "/World/Box_01") == "/World/Box_01/PhysMat"
    assert "also_changes" not in r["result"]


def test_a_call_on_a_source_names_the_clones_that_inherit_its_material(simulation, kit):
    # Isaac Sim's cloner with copy_from_source=False: env_1 on inherit from env_0.
    link = "/World/envs/env_0/Robot/link"
    kit.add_body(link)
    spec = Sdf.CreatePrimInLayer(kit.stage.GetRootLayer(), "/World/envs/env_1")
    spec.specifier = Sdf.SpecifierDef
    spec.inheritPathList.Prepend("/World/envs/env_0")

    r = _set(simulation, link, friction=0.9)

    assert r["result"]["also_changes"] == {"count": 1, "prims": ["/World/envs/env_1/Robot/link"]}
    clone = _set(simulation, "/World/envs/env_1/Robot/link", restitution=0.3)
    assert "also_changes" not in clone["result"]
    assert _values(kit, f"{link}/PhysMat") == {"staticFriction": 0.9, "dynamicFriction": 0.9, "restitution": 0.0}
    assert "also_changes" not in _set(simulation, link, friction=0.8)["result"]


def test_the_answer_names_five_of_the_clones_and_counts_the_rest(simulation, kit):
    # Isaac Lab's 4096 environments would send 4096 paths, which the server printed whole (review S2).
    link = "/World/envs/env_0/Robot/link"
    kit.add_body(link)
    for e in range(1, 8):
        spec = Sdf.CreatePrimInLayer(kit.stage.GetRootLayer(), f"/World/envs/env_{e}")
        spec.specifier = Sdf.SpecifierDef
        spec.inheritPathList.Prepend("/World/envs/env_0")

    r = _set(simulation, link, friction=0.9)

    assert r["result"]["also_changes"] == {
        "count": 7,
        "prims": [f"/World/envs/env_{e}/Robot/link" for e in range(1, 6)],
    }


def test_an_inactive_prim_is_refused_and_not_even_its_mass_is_written(simulation, kit):
    # It raised "Failed to define UsdPrim" after the Collision API and the mass were written (review E3).
    kit.stage.GetPrimAtPath(BOX).SetActive(False)
    before = kit.stage.GetRootLayer().ExportToString()

    r = _set(simulation, mass=3.0, friction=0.5)

    assert r["status"] == "error"
    assert r["error"].startswith(f"{BOX} is inactive")
    assert kit.stage.GetRootLayer().ExportToString() == before


def test_an_instance_is_refused_and_not_even_its_mass_is_written(simulation, kit):
    UsdGeom.Cube.Define(kit.stage, "/Props/Crate/Box")
    crate = kit.stage.DefinePrim("/World/Shelf/Crate", "Xform")
    crate.GetReferences().AddInternalReference("/Props/Crate")
    crate.SetInstanceable(True)
    before = kit.stage.GetRootLayer().ExportToString()

    r = _set(simulation, "/World/Shelf/Crate", mass=3.0, friction=0.5)

    assert r["status"] == "error"
    assert r["error"].startswith("/World/Shelf/Crate is an instance")
    assert kit.stage.GetRootLayer().ExportToString() == before


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
