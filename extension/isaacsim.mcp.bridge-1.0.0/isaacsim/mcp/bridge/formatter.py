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

Used uniformly by dump_scene, recording state, and any large data output.
"""

from typing import Any

from pxr import Gf, Sdf, UsdGeom, UsdPhysics


def format_value(val) -> str:
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
        return f"{float(val[0]):.4f}, {float(val[1]):.4f}"
    if isinstance(val, (Gf.Vec3f, Gf.Vec3d)):
        return f"{float(val[0]):.4f}, {float(val[1]):.4f}, {float(val[2]):.4f}"
    if isinstance(val, (Gf.Vec4f, Gf.Vec4d)):
        return ", ".join(f"{float(val[i]):.4f}" for i in range(4))
    if isinstance(val, (Gf.Quatf, Gf.Quatd)):
        r = val.GetReal()
        im = val.GetImaginary()
        return f"{float(r):.4f}, {float(im[0]):.4f}, {float(im[1]):.4f}, {float(im[2]):.4f}"
    if isinstance(val, Gf.Matrix4d):
        rows = []
        for r in range(4):
            rows.append(", ".join(f"{float(val[r][c]):.4f}" for c in range(4)))
        return " | ".join(rows)
    if isinstance(val, Sdf.AssetPath):
        return str(val.resolvedPath or val.path)
    if isinstance(val, (list, tuple)):
        if len(val) == 0:
            return "[]"
        if len(val) <= 8:
            return ", ".join(format_value(v) for v in val)
        return ", ".join(format_value(v) for v in val[:8]) + f" ... ({len(val)} items)"
    try:
        return str(val)
    except Exception:
        return "<unreadable>"


def format_prim_block(prim, include_properties: bool = True,
                      include_transform: bool = True,
                      include_bounds: bool = False,
                      property_filter: list[str] | None = None) -> str:
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

    if include_transform and prim.IsA(UsdGeom.Xformable):
        xformable = UsdGeom.Xformable(prim)
        world_xform = xformable.ComputeLocalToWorldTransform(0)  # TimeCode.Default
        t = world_xform.ExtractTranslation()
        lines.append(f"pos = {float(t[0]):.4f}, {float(t[1]):.4f}, {float(t[2]):.4f}")

        rotation = world_xform.ExtractRotation()
        if rotation:
            quat = rotation.GetQuat()
            r = quat.GetReal()
            im = quat.GetImaginary()
            lines.append(f"rot = {float(r):.4f}, {float(im[0]):.4f}, {float(im[1]):.4f}, {float(im[2]):.4f}")

    if include_bounds:
        try:
            from .handlers import _compute_world_bbox
            center, dims, corners = _compute_world_bbox(prim)
            lines.append(f"bbox_center = {center[0]:.4f}, {center[1]:.4f}, {center[2]:.4f}")
            lines.append(f"bbox_size = {dims[0]:.4f}, {dims[1]:.4f}, {dims[2]:.4f}")
        except Exception:
            pass

    if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
        lines.append("articulation_root = true")

    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
        lines.append("rigid_body = true")

    if include_properties:
        for prop in prim.GetProperties():
            name = prop.GetName()
            if property_filter:
                if not any(f in name for f in property_filter):
                    continue
            try:
                val = prop.Get()
                if val is not None:
                    lines.append(f"{name} = {format_value(val)}")
            except Exception:
                lines.append(f"{name} = <unreadable>")

    return "\n".join(lines)


def format_scene_dump(stage, root_path: str = "/", max_depth: int = 15,
                      include_properties: bool = True,
                      include_bounds: bool = True,
                      filter_types: list[str] | None = None,
                      property_filter: list[str] | None = None) -> str:
    """Format an entire scene subtree as prim-block text."""
    from pxr import Usd

    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return f"# ERROR: Prim not found: {root_path}\n"

    prim_count = sum(1 for _ in Usd.PrimRange(root_prim))

    lines = [
        f"# Isaac Sim MCP Scene Dump",
        f"# format = isaacsim-mcp-v1",
        f"# root = {root_path}",
        f"# prim_count = {prim_count}",
        f"# up_axis = {UsdGeom.GetStageUpAxis(stage)}",
        f"# meters_per_unit = {UsdGeom.GetStageMetersPerUnit(stage)}",
        "",
        f"=== SCENE root={root_path} prims={prim_count} ===",
        "",
    ]

    def _walk(prim, depth):
        if depth > max_depth:
            return

        type_name = prim.GetTypeName() or "Xform"
        if filter_types and type_name not in filter_types:
            # Still walk children
            for child in prim.GetChildren():
                _walk(child, depth + 1)
            return

        block = format_prim_block(
            prim,
            include_properties=include_properties,
            include_transform=True,
            include_bounds=include_bounds,
            property_filter=property_filter,
        )
        lines.append(block)
        lines.append("")  # Blank line between blocks

        for child in prim.GetChildren():
            _walk(child, depth + 1)

    _walk(root_prim, 0)
    return "\n".join(lines)


def format_frame_state(prims, frame_index: int, sim_time: float,
                       include_properties: bool = False,
                       property_filter: list[str] | None = None) -> str:
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
