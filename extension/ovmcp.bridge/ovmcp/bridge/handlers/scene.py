"""
Scene management handlers.

Handles scene tree, dump, prim CRUD, transforms, materials, cloning,
visibility, save/new, mesh stats, and face count tree.
"""

import math
import os
from typing import Any

import omni.kit.app
import omni.usd
from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

from ovmcp.core import layers
from ovmcp.core.bounds import world_bbox
from ovmcp.core.deletion import why_kept
from ovmcp.core.formatter import format_prim_block, format_scene_dump, format_scene_tree
from ovmcp.core.material import ensure_material, set_surface
from ovmcp.core.usd import prim_spec
from ovmcp.core.xform import Parts, check_transform, check_writable, layer_name, position_of, write_transform

from ._utils import (
    _compute_mesh_stats,
    _first_missing,
    _get_stage,
    _next_update,
    _serialize_value,
)

# ---------------------------------------------------------------------------
# /scene/tree
# ---------------------------------------------------------------------------


async def handle_scene_tree(body: dict) -> dict:
    root_path = body.get("root", "/")
    max_depth = body.get("max_depth", 8)
    include_properties = body.get("include_properties", False)
    fmt = body.get("format", "json")  # "json" or "text"

    stage = _get_stage()
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {root_path}"}

    if fmt == "text":
        # Lightweight prim-block text: path + type + position only (no full properties), down to max_depth
        text, prim_count = format_scene_tree(stage, root_path, max_depth, include_properties=include_properties)
        return {"status": "success", "result": {"text": text, "prim_count": prim_count}}

    def _build_tree(prim: Usd.Prim, depth: int) -> dict:
        node: dict[str, Any] = {
            "path": str(prim.GetPath()),
            "type": prim.GetTypeName() or "Xform",
        }

        if prim.IsA(UsdGeom.Xformable):
            xformable = UsdGeom.Xformable(prim)
            local_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            translate = local_xform.ExtractTranslation()
            node["world_position"] = [round(translate[0], 4), round(translate[1], 4), round(translate[2], 4)]

        if include_properties:
            props = {}
            for prop in prim.GetProperties():
                try:
                    props[prop.GetName()] = _serialize_value(prop.Get())
                except Exception:
                    props[prop.GetName()] = "<unreadable>"
            node["properties"] = props

        if depth < max_depth:
            children = []
            for child in prim.GetChildren():
                children.append(_build_tree(child, depth + 1))
            if children:
                node["children"] = children
        else:
            child_count = len(prim.GetChildren())
            if child_count > 0:
                node["children_count"] = child_count
                node["truncated"] = True

        return node

    tree = _build_tree(root_prim, 0)
    return {"status": "success", "result": tree}


# ---------------------------------------------------------------------------
# /scene/dump  (writes full scene to file, returns file path)
# ---------------------------------------------------------------------------


async def handle_scene_dump(body: dict) -> dict:
    output_dir = body.get("output_dir", "")
    root_path = body.get("root", "/")
    max_depth = body.get("max_depth", 15)
    include_properties = body.get("include_properties", True)
    filter_types = body.get("filter_types", [])  # e.g. ["Mesh", "Xform"]
    property_filter = body.get("property_filter", [])  # e.g. ["joint", "position"]

    if not output_dir:
        return {"status": "error", "error": "No output_dir provided"}

    os.makedirs(output_dir, exist_ok=True)

    stage = _get_stage()
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {root_path}"}

    # The count is the blocks written, where the answer counted the whole stage (#82).
    text, prim_count = format_scene_dump(
        stage,
        root_path,
        max_depth,
        include_properties=include_properties,
        include_bounds=True,
        filter_types=filter_types or None,
        property_filter=property_filter or None,
    )

    file_path = os.path.join(output_dir, "scene_dump.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    file_size = os.path.getsize(file_path)

    return {
        "status": "success",
        "result": {
            "file_path": file_path,
            "file_size_bytes": file_size,
            "prim_count": prim_count,
            "root": root_path,
        },
    }


# ---------------------------------------------------------------------------
# /scene/prim
# ---------------------------------------------------------------------------


async def handle_prim_properties(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    fmt = body.get("format", "json")  # "json" or "text"
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    if fmt == "text":
        text = format_prim_block(prim, include_properties=True, include_transform=True, include_bounds=True)
        return {"status": "success", "result": {"text": text, "prim_path": prim_path}}

    props = {}
    for prop in prim.GetProperties():
        try:
            props[prop.GetName()] = _serialize_value(prop.Get())
        except Exception:
            props[prop.GetName()] = "<unreadable>"

    result: dict[str, Any] = {
        "prim_path": prim_path,
        "type": prim.GetTypeName(),
        "is_active": prim.IsActive(),
        "properties": props,
    }

    if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
        result["is_articulation_root"] = True

    try:
        center, dims, corners = world_bbox(prim)
        result["bbox_center"] = center
        result["bbox_dimensions"] = dims
        result["bbox_min"] = corners[0]
        result["bbox_max"] = corners[1]
    except Exception:
        pass

    return {"status": "success", "result": result}


# ---------------------------------------------------------------------------
# /scene/bounds
# ---------------------------------------------------------------------------


async def handle_prim_bounds(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, corners = world_bbox(prim)
    max_dim = max(dims)
    diagonal = math.sqrt(sum(d * d for d in dims))

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "center": center,
            "dimensions": dims,
            "min": corners[0],
            "max": corners[1],
            "max_dimension": round(max_dim, 4),
            "diagonal": round(diagonal, 4),
        },
    }


# ---------------------------------------------------------------------------
# /scene/transform
# ---------------------------------------------------------------------------


async def handle_transform(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}
    if not prim.IsA(UsdGeom.Xformable):
        return {"status": "error", "error": f"Prim is not transformable: {prim_path}"}

    await _next_update()
    try:
        write_transform(prim, check_transform(body.get("position"), body.get("rotation"), body.get("scale")))
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    return {
        "status": "success",
        "result": {"prim_path": prim_path, "message": "Transform updated"},
    }


# ---------------------------------------------------------------------------
# /scene/create
# ---------------------------------------------------------------------------


async def handle_create_prim(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    prim_type = body.get("prim_type", "Xform")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}
    # Before the prim is made: a refusal after it would leave a prim the answer says wasn't created.
    try:
        parts = check_transform(body.get("position"), body.get("rotation"), body.get("scale"))
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    await _next_update()
    stage = _get_stage()

    usd_path = body.get("usd_path")
    # DefinePrim retypes a prim that is there: a create never turns one kind of prim into another.
    existing = stage.GetPrimAtPath(prim_path)
    if not usd_path and existing.IsValid() and existing.GetTypeName() not in ("", prim_type):
        return {
            "status": "error",
            "error": f"{prim_path} is already a {existing.GetTypeName()}: delete it first, or pick another path",
        }
    made = None if existing.IsValid() else _first_missing(stage, prim_path)
    added = None
    if usd_path:
        prim = stage.DefinePrim(prim_path)
        reference = Sdf.Reference(usd_path)
        spec = prim_spec(stage.GetEditTarget().GetLayer(), prim.GetPath())
        held = spec is not None and reference in spec.referenceList.GetAddedOrExplicitItems()
        prim.GetReferences().AddReference(usd_path)
        added = None if held else reference
    else:
        prim = stage.DefinePrim(prim_path, prim_type)

    if not prim.IsValid():
        return {"status": "error", "error": f"Failed to create prim at {prim_path}"}

    if parts != Parts():
        try:
            write_transform(prim, parts)
        except ValueError as e:
            # Found only once the prim exists, such as an animated op in a referenced file: what this call made goes.
            if made is not None:
                stage.RemovePrim(made)
            elif added is not None:
                # A prim that was there keeps nothing of this call, or each retry would stack another reference.
                prim.GetReferences().RemoveReference(added)
            after = (
                ". Nothing was created"
                if made is not None
                else ". The reference was not added"
                if added is not None
                else ""
            )
            return {"status": "error", "error": f"{e}{after}"}

    if body.get("enable_physics", False):
        UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdPhysics.CollisionAPI.Apply(prim)

    return {
        "status": "success",
        "result": {"prim_path": str(prim.GetPath()), "type": prim.GetTypeName()},
    }


# ---------------------------------------------------------------------------
# /scene/delete
# ---------------------------------------------------------------------------


async def handle_delete_prim(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    await _next_update()
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    # RemovePrim takes only the edit layer's specs: what another layer or an arc above defines would stay, with the
    # edit layer's overrides of it gone, so that is refused before anything changes.
    edit_layer = stage.GetEditTarget().GetLayer()
    why = why_kept(prim, edit_layer)
    if why:
        return {"status": "error", "error": why}
    where = layer_name(stage, edit_layer)
    if not stage.RemovePrim(prim_path):
        return {"status": "error", "error": f"{prim_path} is not deleted: {where}, where edits go, holds nothing there"}
    after = stage.GetPrimAtPath(prim_path)
    if after.IsValid() and after.IsDefined():
        # The check above should have said why; this answers the truth if it missed a case.
        return {"status": "error", "error": f"{prim_path} is still on the stage after what {where} held of it went"}
    return {
        "status": "success",
        # checked: this extension refuses a prim it can't remove, so the server needn't warn of one that stayed.
        "result": {"prim_path": prim_path, "message": "Prim deleted", "checked": True},
    }


# ---------------------------------------------------------------------------
# /scene/material
# ---------------------------------------------------------------------------


async def handle_set_material(body: dict) -> dict:
    """Apply a PBR material to a prim.

    Body params:
        prim_path: str          - target prim
        color: [r, g, b]        - diffuse color (0-1 floats or 0-255 ints)
        opacity: float           - 0.0 (transparent) to 1.0 (opaque), default 1.0
        roughness: float         - 0.0 (glossy) to 1.0 (rough), default 0.5
        metallic: float          - 0.0 (dielectric) to 1.0 (metal), default 0.0
        material_path: str       - custom material prim path (auto-generated if omitted)
    """
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    color = body.get("color")
    if not color or len(color) != 3:
        return {"status": "error", "error": "color must be [r, g, b] with 3 values"}

    # Normalize color to 0-1 range
    r, g, b = [float(c) for c in color]
    if max(r, g, b) > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0

    opacity = float(body.get("opacity", 1.0))
    roughness = float(body.get("roughness", 0.5))
    metallic = float(body.get("metallic", 0.0))

    await _next_update()
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    # Create material under /World/Looks/<PrimName>_Mat
    prim_name = prim_path.rstrip("/").split("/")[-1]
    mat_path = body.get("material_path", "")
    if not mat_path:
        mat_path = f"/World/Looks/{prim_name}_Mat"

    mat, shader = ensure_material(stage, mat_path)
    set_surface(shader, (r, g, b), opacity, roughness, metallic)

    # Bind material to the target prim
    UsdShade.MaterialBindingAPI.Apply(prim)
    UsdShade.MaterialBindingAPI(prim).Bind(mat)

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "material_path": mat_path,
            "color": [r, g, b],
            "opacity": opacity,
            "roughness": roughness,
            "metallic": metallic,
        },
    }


# ---------------------------------------------------------------------------
# /scene/clone
# ---------------------------------------------------------------------------


async def handle_clone_prim(body: dict) -> dict:
    """Clone a prim (deep copy). Optionally create multiple copies with offset."""
    source_path = body.get("source_path", "")
    target_path = body.get("target_path", "")
    count = body.get("count", 1)
    offset = body.get("offset")  # [x, y, z] per-copy offset

    if not source_path:
        return {"status": "error", "error": "No source_path provided"}
    if not target_path:
        return {"status": "error", "error": "No target_path provided"}

    try:
        step = check_transform(position=offset).position if offset is not None else None
    except ValueError:
        return {"status": "error", "error": f"offset must be [x, y, z], 3 numbers, got {offset!r}"}

    await _next_update()
    stage = _get_stage()
    source_prim = stage.GetPrimAtPath(source_path)
    if not source_prim.IsValid():
        return {"status": "error", "error": f"Source prim not found: {source_path}"}

    dest_paths = [target_path if count == 1 else f"{target_path}_{i + 1:03d}" for i in range(count)]
    # CopySpec replaces whatever is at the destination, children included: a clone never takes a path in use.
    taken = [p for p in dest_paths if stage.GetPrimAtPath(p).IsValid()]
    if taken:
        return {
            "status": "error",
            "error": f"Already a prim at {', '.join(taken)}: delete it first, or pick another target_path",
        }

    # The copies are written into the root layer, so they move there: with a sublayer as the edit target, a move there
    # would be refused as hidden, after the copies were made.
    src_layer = stage.GetRootLayer()
    moves = step is not None and count > 1 and source_prim.IsA(UsdGeom.Xformable)
    if moves:
        try:
            check_writable(source_prim, Parts(position=position_of(source_prim)), src_layer)
        except ValueError as e:
            return {"status": "error", "error": f"{e}. Nothing was copied"}
    created = []
    for i, dest_path in enumerate(dest_paths):
        if not Sdf.CopySpec(src_layer, source_path, src_layer, dest_path):
            return {"status": "error", "error": f"Failed to clone to {dest_path}"}
        created.append(dest_path)
        # Copy n moves n offsets from the source, through its own ops; the first copy, and a single one, stay as copied.
        dest_prim = stage.GetPrimAtPath(dest_path)
        if moves and step is not None and i > 0 and dest_prim.IsA(UsdGeom.Xformable):
            try:
                write_transform(dest_prim, Parts(position=position_of(dest_prim) + step * i), src_layer)
            except ValueError as e:
                # A copy composes apart from its source, so one may refuse what the source took: none stays.
                with Usd.EditContext(stage, Usd.EditTarget(src_layer)):
                    for path in created:
                        stage.RemovePrim(path)
                return {"status": "error", "error": f"{e}. Nothing was copied"}

    return {
        "status": "success",
        "result": {"source": source_path, "clones": created, "count": len(created)},
    }


# ---------------------------------------------------------------------------
# /scene/visibility
# ---------------------------------------------------------------------------


async def handle_set_visibility(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    visible = body.get("visible", True)

    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    imageable = UsdGeom.Imageable(prim)
    if not imageable:
        return {"status": "error", "error": f"Prim is not imageable: {prim_path}"}

    if visible:
        imageable.MakeVisible()
    else:
        imageable.MakeInvisible()

    return {"status": "success", "result": {"prim_path": prim_path, "visible": visible}}


# ---------------------------------------------------------------------------
# /scene/save
# ---------------------------------------------------------------------------


async def handle_save_scene(body: dict) -> dict:
    file_path = body.get("file_path", "")

    await _next_update()
    stage = _get_stage()

    if file_path:
        # Export overwrites whatever file is there, another layer of the open stage too, under the layer Kit holds for
        # it (#85).
        refusal = layers.write_refusal(stage, file_path, saving=True)
        if refusal:
            return {"status": "error", "error": refusal}
        if not stage.GetRootLayer().Export(file_path):
            return {"status": "error", "error": f"Failed to save the stage to: {file_path}"}
        layers.refresh_written(stage, file_path)
        return {"status": "success", "result": {"file_path": file_path, "action": "save_as"}}

    current_path = stage.GetRootLayer().realPath
    if not current_path:
        return {"status": "error", "error": "No file path set. Provide file_path for save-as."}
    stage.GetRootLayer().Save()
    return {"status": "success", "result": {"file_path": current_path, "action": "save"}}


# ---------------------------------------------------------------------------
# /scene/new
# ---------------------------------------------------------------------------


async def handle_new_scene(_body: dict) -> dict:
    await _next_update()
    ctx = omni.usd.get_context()
    result, error = await ctx.new_stage_async()
    if not result:
        return {"status": "error", "error": f"Failed to create new scene: {error}"}

    await _next_update()
    await _next_update()

    stage = _get_stage()
    world = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(world)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    return {"status": "success", "result": {"message": "New scene created", "default_prim": "/World"}}


# ---------------------------------------------------------------------------
# /scene/mesh_stats
# ---------------------------------------------------------------------------


async def handle_mesh_stats(body: dict) -> dict:
    """Get face/vertex/triangle counts for a mesh or subtree."""
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()

    stats = _compute_mesh_stats(prim)
    stats["prim_path"] = prim_path
    return {"status": "success", "result": stats}


# ---------------------------------------------------------------------------
# /scene/face_count_tree
# ---------------------------------------------------------------------------


async def handle_face_count_tree(body: dict) -> dict:
    """Scene tree with face counts per mesh and subtree totals."""
    root_path = body.get("root", "/World")
    max_depth = body.get("max_depth", 10)

    stage = _get_stage()
    root = stage.GetPrimAtPath(root_path)
    if not root.IsValid():
        return {"status": "error", "error": f"Prim not found: {root_path}"}

    # Pre-compute per-mesh face counts (O(n))
    mesh_faces: dict[str, int] = {}
    for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        if p.IsA(UsdGeom.Mesh):
            fc = UsdGeom.Mesh(p).GetFaceVertexCountsAttr().Get()
            mesh_faces[str(p.GetPath())] = len(fc) if fc else 0

    # Bottom-up subtree sums via path-based aggregation.
    # prim.GetChildren() misses instance proxies, so instead we walk UP
    # from each mesh in mesh_faces to the root, accumulating face counts
    # at every ancestor.  This is O(m * d) where m = meshes, d = depth.
    subtree_sums: dict[str, int] = {}
    root_sdf = Sdf.Path(root_path)

    for mesh_path_str, n_faces in mesh_faces.items():
        if n_faces == 0:
            continue
        path = Sdf.Path(mesh_path_str)
        while path != Sdf.Path.emptyPath:
            ps = str(path)
            subtree_sums[ps] = subtree_sums.get(ps, 0) + n_faces
            if path == root_sdf:
                break
            path = path.GetParentPath()

    # Walk tree and produce text
    lines = [f"# face_count_tree root={root_path}", ""]
    total_faces = 0
    total_meshes = 0

    def _depth_of(path_str: str) -> int:
        """Number of path components relative to root."""
        return path_str.count("/") - root_path.rstrip("/").count("/")

    for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        path_str = str(p.GetPath())
        depth = _depth_of(path_str)
        if depth > max_depth:
            continue

        block = [f"[{p.GetPath()}]"]
        type_name = p.GetTypeName() or "Xform"
        block.append(f"type = {type_name}")

        if p.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(p)
            face_counts = mesh.GetFaceVertexCountsAttr().Get()
            points = mesh.GetPointsAttr().Get()
            n_faces = len(face_counts) if face_counts else 0
            n_vertices = len(points) if points else 0
            n_triangles = sum(max(0, c - 2) for c in face_counts) if face_counts else 0
            block.append(f"faces = {n_faces}")
            block.append(f"vertices = {n_vertices}")
            block.append(f"triangles = {n_triangles}")
            total_faces += n_faces
            total_meshes += 1
        elif subtree_sums.get(path_str, 0) > 0:
            block.append(f"subtree_faces = {subtree_sums[path_str]}")

        lines.append("\n".join(block))
        lines.append("")
    lines.append(f"# total: {total_faces} faces in {total_meshes} meshes")

    text = "\n".join(lines)
    return {"status": "success", "result": {"text": text, "total_faces": total_faces, "mesh_count": total_meshes}}
