"""
AI-friendly prim-block text format.

Format spec:
- Each prim is a [/path/to/prim] block header
- Properties are key = value lines (one per line)
- Blocks separated by blank lines
- Frame markers: === FRAME t=0.000 step=0 ===
- Scene dump headers: === SCENE root=/World prims=42 ===
- Comments start with #
- Values are plain text: numbers, comma-separated vectors, strings
- Grep-friendly: grep '/World/G1' finds block headers, grep 'joint_angle' finds properties

Used uniformly by get_scene_tree's dump, recording state, and any large data output.
"""

from collections.abc import Iterable, Sequence
from typing import cast

from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from .bounds import center_and_size, world_bbox
from .usd import Vec, children, has_api, is_a


def _join(v: Vec, n: int) -> str:
    return ", ".join(f"{float(v[i]):.4f}" for i in range(n))


def format_value(val: object) -> str:
    """Format a USD property value as a human-readable string."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        if isinstance(val, float):
            return f"{val:.6g}"
        return str(val)
    if isinstance(val, str):
        return val
    if isinstance(val, (Gf.Vec2f, Gf.Vec2d)):
        return _join(val, 2)
    if isinstance(val, (Gf.Vec3f, Gf.Vec3d)):
        return _join(val, 3)
    if isinstance(val, (Gf.Vec4f, Gf.Vec4d)):
        return _join(val, 4)
    if isinstance(val, (Gf.Quatf, Gf.Quatd)):
        return f"{float(val.GetReal()):.4f}, {_join(val.GetImaginary(), 3)}"
    if isinstance(val, Gf.Matrix4d):
        return " | ".join(_join(val[r], 4) for r in range(4))
    if isinstance(val, Sdf.AssetPath):
        # The stubs leave out an asset path's two fields.
        return str(getattr(val, "resolvedPath", "") or getattr(val, "path", ""))
    if isinstance(val, (list, tuple)):
        items = cast("Sequence[object]", val)
        if len(items) == 0:
            return "[]"
        if len(items) <= 8:
            return ", ".join(format_value(v) for v in items)
        return ", ".join(format_value(v) for v in items[:8]) + f" ... ({len(items)} items)"
    try:
        return str(val)
    except Exception:
        return "<unreadable>"


def format_prim_block(
    prim: Usd.Prim,
    include_properties: bool = True,
    include_transform: bool = True,
    include_bounds: bool = False,
    property_filter: list[str] | None = None,
) -> str:
    """Format a single prim as a text block.

    Args:
        prim: USD prim
        include_properties: Include all USD properties
        include_transform: Include world-space transform
        include_bounds: Include bounding box
        property_filter: If set, only include properties containing these substrings
    """
    lines = [f"[{prim.GetPath()}]"]
    lines.append(f"type = {prim.GetTypeName() or 'Xform'}")

    if include_transform and is_a(prim, UsdGeom.Xformable):
        # Use BBoxCache to get physics-accurate world position.
        # ComputeLocalToWorldTransform reads authored USD transforms which
        # don't reflect PhysX runtime state during simulation.  BBoxCache
        # reads through Fabric and returns the real physics position.
        pos_from_bbox = False
        if has_api(prim, UsdPhysics.RigidBodyAPI):
            try:
                bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
                box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
                if not box.IsEmpty():
                    center, _ = center_and_size(box.GetMin(), box.GetMax())
                    lines.append(f"pos = {_join(center, 3)}")
                    pos_from_bbox = True
            except Exception:
                pass

        xformable = UsdGeom.Xformable(prim)
        if not pos_from_bbox:
            world_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            lines.append(f"pos = {_join(world_xform.ExtractTranslation(), 3)}")

        world_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        rotation = world_xform.ExtractRotation()
        if rotation:
            quat = rotation.GetQuat()
            lines.append(f"rot = {float(quat.GetReal()):.4f}, {_join(quat.GetImaginary(), 3)}")

    if include_bounds:
        try:
            center, dims, _ = world_bbox(prim)
            lines.append(f"bbox_center = {center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f}")
            lines.append(f"bbox_size = {dims[0]:.4f}, {dims[1]:.4f}, {dims[2]:.4f}")
        except Exception:
            lines.append("bbox = <unavailable>")

    if has_api(prim, UsdPhysics.ArticulationRootAPI):
        lines.append("articulation_root = true")

    if has_api(prim, UsdPhysics.RigidBodyAPI):
        lines.append("rigid_body = true")

    if include_properties:
        for prop in prim.GetProperties():
            name = prop.GetName()
            if property_filter and not any(f in name for f in property_filter):
                continue
            if not isinstance(prop, Usd.Attribute):
                # A relationship has no value to read; its targets have never been listed here.
                lines.append(f"{name} = <unreadable>")
                continue
            try:
                val = prop.Get()
                if val is not None:
                    lines.append(f"{name} = {format_value(val)}")
            except Exception:
                lines.append(f"{name} = <unreadable>")

    return "\n".join(lines)


def format_scene_dump(
    stage: Usd.Stage,
    root_path: str = "/",
    max_depth: int = 15,
    include_properties: bool = True,
    include_bounds: bool = True,
    filter_types: list[str] | None = None,
    property_filter: list[str] | None = None,
) -> tuple[str, int]:
    """Format a scene subtree as prim-block text, with the number of prims written: the count, in the header too, is
    the blocks the file holds, where it counted the whole subtree, past max_depth and filter_types (#82)."""
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return f"# ERROR: Prim not found: {root_path}\n", 0

    blocks: list[str] = []

    def _walk(prim: Usd.Prim, depth: int) -> None:
        if depth > max_depth:
            return

        type_name = prim.GetTypeName() or "Xform"
        if filter_types and type_name not in filter_types:
            # Still walk children
            for child in children(prim):
                _walk(child, depth + 1)
            return

        blocks.append(
            format_prim_block(
                prim,
                include_properties=include_properties,
                include_transform=True,
                include_bounds=include_bounds,
                property_filter=property_filter,
            )
        )
        for child in children(prim):
            _walk(child, depth + 1)

    _walk(root_prim, 0)
    prim_count = len(blocks)
    lines = [
        "# Omniverse MCP Scene Dump",
        "# format = omniverse-mcp-v1",
        f"# root = {root_path}",
        f"# prim_count = {prim_count}",
        f"# up_axis = {UsdGeom.GetStageUpAxis(stage)}",
        f"# meters_per_unit = {UsdGeom.GetStageMetersPerUnit(stage)}",
        "",
        f"=== SCENE root={root_path} prims={prim_count} ===",
        "",
    ]
    for block in blocks:
        lines.append(block)
        lines.append("")  # Blank line between blocks
    return "\n".join(lines), prim_count


def format_scene_tree(
    stage: Usd.Stage, root_path: str, max_depth: int, include_properties: bool = False
) -> tuple[str, int]:
    """get_scene_tree's text: a block for each prim from root down to max_depth, with its type and world position, and
    the number of blocks. A prim at max_depth that has children says how many, as `children = N (truncated)`, and
    nothing below it is listed, as the JSON mode has it; the text used to list the next level's prims that had
    children and leave out the rest, so a childless one there looked absent (#82)."""
    lines = [f"# scene_tree root={root_path} up_axis={UsdGeom.GetStageUpAxis(stage)}", ""]
    count = 0

    def _walk(prim: Usd.Prim, depth: int) -> None:
        nonlocal count
        count += 1
        block = [f"[{prim.GetPath()}]", f"type = {prim.GetTypeName() or 'Xform'}"]
        if is_a(prim, UsdGeom.Xformable):
            world = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            block.append(f"pos = {_join(world.ExtractTranslation(), 3)}")
        if include_properties:
            for prop in prim.GetProperties():
                if not isinstance(prop, Usd.Attribute):
                    continue
                try:
                    val = prop.Get()
                    if val is not None:
                        block.append(f"{prop.GetName()} = {format_value(val)}")
                except Exception:
                    pass
        below = children(prim)
        if depth >= max_depth and below:
            block.append(f"children = {len(below)} (truncated)")
        lines.append("\n".join(block))
        lines.append("")
        if depth < max_depth:
            for child in below:
                _walk(child, depth + 1)

    root_prim = stage.GetPrimAtPath(root_path)
    if root_prim.IsValid():
        _walk(root_prim, 0)
    return "\n".join(lines), count


def format_frame_state(
    prims: Iterable[Usd.Prim],
    frame_index: int,
    sim_time: float,
    include_properties: bool = False,
    property_filter: list[str] | None = None,
) -> str:
    """Format prim states for a single recording frame.

    Args:
        prims: List of USD prims to capture state for
        frame_index: Frame number
        sim_time: Simulation time in seconds
        include_properties: Include all properties (can be very verbose)
        property_filter: Only include properties matching these substrings
    """
    lines = [
        f"=== FRAME t={sim_time:.3f} step={frame_index} ===",
        "",
    ]

    for prim in prims:
        if not prim.IsValid():
            continue

        block = format_prim_block(
            prim,
            include_properties=include_properties or (property_filter is not None),
            include_transform=True,
            include_bounds=False,
            property_filter=property_filter,
        )
        lines.append(block)
        lines.append("")

    return "\n".join(lines)
