"""The prim-block text of dump_scene, get_prim_properties (text) and recording frames, on usd-core."""

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.formatter import (
    format_frame_state,
    format_prim_block,
    format_scene_dump,
    format_scene_tree,
    format_value,
)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (7, "7"),
        (0.1 + 0.2, "0.3"),
        (1.25e-9, "1.25e-09"),
        ("a label", "a label"),
        (Gf.Vec2f(1.5, -2), "1.5000, -2.0000"),
        (Gf.Vec3d(1, 2, 3), "1.0000, 2.0000, 3.0000"),
        (Gf.Vec4d(1, 2, 3, 4), "1.0000, 2.0000, 3.0000, 4.0000"),
        (Gf.Quatf(0.5, 0.1, 0.2, 0.3), "0.5000, 0.1000, 0.2000, 0.3000"),
        (Gf.Matrix4d(2.0), " | ".join(", ".join("2.0000" if r == c else "0.0000" for c in range(4)) for r in range(4))),
        (Sdf.AssetPath("./tex.png"), "./tex.png"),
        ([], "[]"),
        ([1, 2.5, "x"], "1, 2.5, x"),
        (tuple(range(12)), "0, 1, 2, 3, 4, 5, 6, 7 ... (12 items)"),
        (Gf.Vec3i(1, 2, 3), "(1, 2, 3)"),
    ],
)
def test_values(value, text):
    assert format_value(value) == text


@pytest.fixture
def stage():
    st = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(st, "/World")
    cube = UsdGeom.Cube.Define(st, "/World/Cube")
    cube.CreateSizeAttr(2.0)
    UsdGeom.Xformable(cube).AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
    ball = UsdGeom.Sphere.Define(st, "/World/Group/Ball")
    UsdGeom.Xformable(ball).AddTranslateOp().Set(Gf.Vec3d(-4, 0, 0))
    ball.GetPrim().CreateRelationship("material:binding").AddTarget("/World/Looks/M")
    ball.GetPrim().CreateAttribute("unset", Sdf.ValueTypeNames.Float)
    st.DefinePrim("/World/Off").SetActive(False)
    return st


def test_a_block_has_the_path_type_transform_and_properties(stage):
    text = format_prim_block(stage.GetPrimAtPath("/World/Cube"), include_bounds=True)
    lines = text.splitlines()

    assert lines[:4] == [
        "[/World/Cube]",
        "type = Cube",
        "pos = 1.0000, 2.0000, 3.0000",
        "rot = 1.0000, 0.0000, 0.0000, 0.0000",
    ]
    assert "bbox_center = 1.0000, 2.0000, 3.0000" in lines
    assert "bbox_size = 2.0000, 2.0000, 2.0000" in lines
    assert "size = 2" in lines
    assert "rigid_body = true" not in lines


def test_a_rigid_body_takes_its_position_from_its_bounds(stage):
    prim = stage.GetPrimAtPath("/World/Cube")
    # An extent off-center: the bounds' center is not the transform's translation.
    UsdGeom.Cube(prim).CreateExtentAttr([Gf.Vec3f(0, 0, 0), Gf.Vec3f(2, 2, 2)])
    UsdPhysics.RigidBodyAPI.Apply(prim)
    UsdPhysics.ArticulationRootAPI.Apply(prim)

    lines = format_prim_block(prim, include_properties=False).splitlines()

    assert lines[2] == "pos = 2.0000, 3.0000, 4.0000"
    assert lines[-2:] == ["articulation_root = true", "rigid_body = true"]


def test_a_relationship_is_unreadable_and_an_unset_attribute_is_left_out(stage):
    lines = format_prim_block(stage.GetPrimAtPath("/World/Group/Ball")).splitlines()

    assert "material:binding = <unreadable>" in lines
    assert not any(line.startswith("unset") for line in lines)


def test_a_property_filter_keeps_matching_names(stage):
    lines = format_prim_block(stage.GetPrimAtPath("/World/Cube"), property_filter=["size", "xformOp"]).splitlines()

    assert [line.split(" = ")[0] for line in lines[4:]] == ["size", "xformOp:translate", "xformOpOrder"]


def test_a_prim_without_a_transform_has_no_pose(stage):
    prim = stage.DefinePrim("/World/Typeless")

    assert format_prim_block(prim, include_bounds=True) == (
        "[/World/Typeless]\ntype = Xform\nbbox_center = 0.0000, 0.0000, 0.0000\nbbox_size = 0.1000, 0.1000, 0.1000"
    )


def test_a_scene_dump_walks_the_tree(stage):
    text, _count = format_scene_dump(stage, "/World", include_properties=False, include_bounds=False)

    assert text.splitlines()[:8] == [
        "# Omniverse MCP Scene Dump",
        "# format = omniverse-mcp-v1",
        "# root = /World",
        "# prim_count = 4",
        "# up_axis = Y",
        "# meters_per_unit = 0.01",
        "",
        "=== SCENE root=/World prims=4 ===",
    ]
    blocks = [line for line in text.splitlines() if line.startswith("[")]
    assert blocks == ["[/World]", "[/World/Cube]", "[/World/Group]", "[/World/Group/Ball]"]


def test_a_type_filter_still_walks_below_what_it_leaves_out(stage):
    text, _count = format_scene_dump(stage, "/", filter_types=["Sphere"], include_properties=False)

    assert [line for line in text.splitlines() if line.startswith("[")] == ["[/World/Group/Ball]"]


def test_max_depth_stops_the_walk(stage):
    text, _count = format_scene_dump(stage, "/World", max_depth=1, include_properties=False, include_bounds=False)

    assert [line for line in text.splitlines() if line.startswith("[")] == [
        "[/World]",
        "[/World/Cube]",
        "[/World/Group]",
    ]


def test_a_missing_root_says_so(stage):
    assert format_scene_dump(stage, "/Nowhere") == ("# ERROR: Prim not found: /Nowhere\n", 0)


@pytest.mark.parametrize(
    ("args", "count"),
    [({}, 4), ({"max_depth": 1}, 3), ({"max_depth": 0}, 1), ({"filter_types": ["Sphere"]}, 1)],
)
def test_a_scene_dump_counts_the_prims_it_wrote(stage, args, count):
    # The answer counted the whole stage and the header the whole subtree, past max_depth and filter_types (#82).
    text, written = format_scene_dump(stage, "/World", include_properties=False, include_bounds=False, **args)

    assert written == count
    assert sum(line.startswith("[") for line in text.splitlines()) == count
    assert f"# prim_count = {count}" in text.splitlines()
    assert f"=== SCENE root=/World prims={count} ===" in text.splitlines()


def test_a_scene_tree_at_depth_0_says_how_many_children_the_root_has(stage):
    text, listed = format_scene_tree(stage, "/World", 0)

    assert listed == 1
    assert [line for line in text.splitlines() if line.startswith("[")] == ["[/World]"]
    assert "children = 2 (truncated)" in text.splitlines()  # the cube and the group; the inactive prim isn't listed


def test_a_scene_tree_lists_every_prim_down_to_its_depth_and_counts_what_lies_below(stage):
    # The text listed the next level's prims that had children and left out the rest (#82).
    text, listed = format_scene_tree(stage, "/World", 1)

    assert listed == 3
    blocks = text.split("\n\n")
    assert [b.splitlines()[0] for b in blocks if b.startswith("[")] == ["[/World]", "[/World/Cube]", "[/World/Group]"]
    group = next(b for b in blocks if b.startswith("[/World/Group]"))
    cube = next(b for b in blocks if b.startswith("[/World/Cube]"))
    assert "children = 1 (truncated)" in group
    assert "children" not in cube
    assert "pos = 1.0000, 2.0000, 3.0000" in cube


def test_a_scene_tree_with_properties_gives_each_attributes_value(stage):
    text, _listed = format_scene_tree(stage, "/World/Cube", 0, include_properties=True)
    assert "size = 2" in text.splitlines()


def test_a_scene_tree_of_a_missing_root_lists_nothing(stage):
    text, listed = format_scene_tree(stage, "/Nowhere", 3)
    assert listed == 0
    assert not [line for line in text.splitlines() if line.startswith("[")]


def test_a_frame_has_its_marker_and_skips_prims_that_are_gone(stage):
    prims = [stage.GetPrimAtPath(p) for p in ("/World/Cube", "/World/Gone")]

    text = format_frame_state(prims, frame_index=3, sim_time=0.125)

    assert text.splitlines()[:5] == [
        "=== FRAME t=0.125 step=3 ===",
        "",
        "[/World/Cube]",
        "type = Cube",
        "pos = 1.0000, 2.0000, 3.0000",
    ]
    assert "[/World/Gone]" not in text
    assert "size = 2" not in text  # no properties unless asked
    assert "size = 2" in format_frame_state(prims, 3, 0.125, property_filter=["size"])
