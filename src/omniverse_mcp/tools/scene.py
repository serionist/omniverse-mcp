"""Scene management tools."""

from typing import Annotated

from pydantic import Field

from ._annotations import DESTROYS, EDITS, READS
from ._bridge import bridge_call
from ._params import Position, PrimPath, Rotation, Scale


def register(mcp, client, h):
    @mcp.tool(annotations=READS)
    def get_scene_tree(
        root: Annotated[str, Field(description="Prim path to start from")] = "/",
        max_depth: Annotated[int, Field(ge=1, le=15, description="How many levels below root")] = 5,
    ) -> str:
        """Get the USD scene hierarchy as grep-friendly prim-block text.

        Each prim shows: path, type, world position. For large scenes, use dump_scene
        which also includes properties and bounding boxes.
        """
        resp = bridge_call(client.scene_tree, root, max_depth, fmt="text")
        r = resp["result"]
        text = r["text"]
        return h.text_response(text, "scene_tree")

    @mcp.tool(annotations=READS)
    def dump_scene(
        root: Annotated[str, Field(description="Prim path to start from")] = "/",
        max_depth: Annotated[int, Field(ge=1, description="How many levels below root")] = 15,
        include_properties: Annotated[bool, Field(description="Include every USD property of each prim")] = True,
        filter_types: Annotated[
            list[str] | None, Field(description='Only prims of these types, e.g. ["Mesh", "Xform"]')
        ] = None,
        property_filter: Annotated[
            list[str] | None, Field(description='Only properties whose names contain one of these, e.g. ["joint"]')
        ] = None,
    ) -> str:
        """Dump the full scene graph to a text file in prim-block format.

        Writes ALL prims with properties, bounding boxes, and transforms to a grep-friendly file.
        Returns the file path. Use your Read tool to examine specific parts.
        """
        resp = bridge_call(
            client.scene_dump,
            h.output_dir,
            root,
            max_depth,
            include_properties,
            filter_types or [],
            property_filter=property_filter,
        )
        r = resp["result"]
        return f"Dumped {r['prim_count']} prims ({r['file_size_bytes']:,} bytes) -> {h.rel(r['file_path'])}"

    @mcp.tool(annotations=READS)
    def get_prim_properties(prim_path: PrimPath) -> str:
        """Get all properties of a specific prim in prim-block text format.

        Returns grep-friendly text with type, position, bounding box, and all USD properties.
        """
        resp = bridge_call(client.prim_properties, prim_path, fmt="text")
        text = resp["result"]["text"]
        return h.text_response(text, f"prim_{prim_path.replace('/', '_')}")

    @mcp.tool(annotations=READS)
    def get_prim_bounds(prim_path: PrimPath) -> str:
        """Get the bounding box of a prim (center, dimensions, min/max corners, diagonal).

        Use this for spatial reasoning -- understanding sizes, overlap, distances.
        """
        resp = bridge_call(client.prim_bounds, prim_path)
        r = resp["result"]
        return (
            f"[{r['prim_path']}]\n"
            f"center = {r['center'][0]:.4f}, {r['center'][1]:.4f}, {r['center'][2]:.4f}\n"
            f"dimensions = {r['dimensions'][0]:.4f}, {r['dimensions'][1]:.4f}, {r['dimensions'][2]:.4f}\n"
            f"min = {r['min'][0]:.4f}, {r['min'][1]:.4f}, {r['min'][2]:.4f}\n"
            f"max = {r['max'][0]:.4f}, {r['max'][1]:.4f}, {r['max'][2]:.4f}\n"
            f"diagonal = {r['diagonal']:.4f}"
        )

    @mcp.tool(annotations=EDITS)
    def set_prim_transform(
        prim_path: PrimPath,
        position: Position = None,
        rotation: Rotation = None,
        scale: Scale = None,
    ) -> str:
        """Set position/rotation/scale of a prim."""
        bridge_call(client.set_transform, prim_path, position, rotation, scale)
        return f"Transform updated for {prim_path}"

    @mcp.tool(annotations=EDITS)
    def create_prim(
        prim_path: Annotated[str, Field(description='Where to create it, e.g. "/World/MyCube"')],
        prim_type: Annotated[str, Field(description="USD type name, e.g. Cube, Sphere, Xform, DistantLight")] = "Xform",
        usd_path: Annotated[str | None, Field(description="A USD file to load as a reference instead")] = None,
        position: Position = None,
        rotation: Rotation = None,
        scale: Scale = None,
        enable_physics: Annotated[bool, Field(description="Add the RigidBody and Collision APIs")] = False,
    ) -> str:
        """Create a new prim in the scene.

        Types: Cube, Sphere, Cylinder, Cone, Capsule, Xform, Camera, DistantLight, SphereLight, etc.
        Or load a USD file via usd_path.
        """
        kwargs = {}
        if usd_path:
            kwargs["usd_path"] = usd_path
        if position is not None:
            kwargs["position"] = position
        if rotation is not None:
            kwargs["rotation"] = rotation
        if scale is not None:
            kwargs["scale"] = scale
        if enable_physics:
            kwargs["enable_physics"] = True

        resp = bridge_call(client.create_prim, prim_path, prim_type, **kwargs)
        r = resp["result"]
        return f"Created {r['type']} at {r['prim_path']}"

    @mcp.tool(annotations=DESTROYS)
    def delete_prim(prim_path: PrimPath) -> str:
        """Delete a prim and all its children."""
        bridge_call(client.delete_prim, prim_path)
        return f"Deleted {prim_path}"

    @mcp.tool(annotations=EDITS)
    def set_material(
        prim_path: PrimPath,
        color: Annotated[
            list[float],
            Field(description="[r, g, b] diffuse color: 0-1 floats (e.g. [1, 0, 0] for red) or 0-255 ints"),
        ],
        opacity: Annotated[float, Field(ge=0, le=1, description="0 transparent to 1 opaque")] = 1.0,
        roughness: Annotated[float, Field(ge=0, le=1, description="0 glossy (mirror) to 1 rough (matte)")] = 0.5,
        metallic: Annotated[float, Field(ge=0, le=1, description="0 plastic (dielectric) to 1 metal")] = 0.0,
        material_path: Annotated[
            str, Field(description="The material prim's path; made under /World/Looks/ when empty")
        ] = "",
    ) -> str:
        """Apply a PBR material (OmniPBR) to a prim with color and surface properties.

        Creates a material automatically and binds it to the target prim.
        Color values can be 0-1 floats or 0-255 ints (auto-detected).
        """
        resp = bridge_call(client.set_material, prim_path, color, opacity, roughness, metallic, material_path)
        r = resp["result"]
        parts = [f"color=[{r['color'][0]:.2f},{r['color'][1]:.2f},{r['color'][2]:.2f}]"]
        if r.get("opacity", 1.0) < 1.0:
            parts.append(f"opacity={r['opacity']}")
        parts.append(f"roughness={r['roughness']}")
        parts.append(f"metallic={r['metallic']}")
        return f"Material {r['material_path']} -> {r['prim_path']} ({', '.join(parts)})"

    @mcp.tool(annotations=EDITS)
    def clone_prim(
        source_path: Annotated[str, Field(description='The prim to clone, e.g. "/World/MyCube"')],
        target_path: Annotated[str, Field(description='Where the copy goes, e.g. "/World/MyCube_Copy"')],
        count: Annotated[int, Field(ge=1, description="How many copies; paths get _001, _002, ...")] = 1,
        offset: Annotated[
            list[float] | None, Field(description="[x, y, z] each copy moves from the one before")
        ] = None,
    ) -> str:
        """Deep-copy a prim (and all children) to a new path. Supports batch cloning."""
        resp = bridge_call(client.clone_prim, source_path, target_path, count, offset)
        r = resp["result"]
        clones = r["clones"]
        if len(clones) == 1:
            return f"Cloned {source_path} -> {clones[0]}"
        return f"Cloned {source_path} -> {len(clones)} copies:\n" + "\n".join(f"  {c}" for c in clones)

    @mcp.tool(annotations=EDITS)
    def set_visibility(
        prim_path: PrimPath,
        visible: Annotated[bool, Field(description="True to show, False to hide")] = True,
    ) -> str:
        """Show or hide a prim (and its descendants)."""
        resp = bridge_call(client.set_visibility, prim_path, visible)
        r = resp["result"]
        state = "visible" if r["visible"] else "hidden"
        return f"{r['prim_path']} is now {state}"

    @mcp.tool(annotations=DESTROYS)
    def save_scene(
        file_path: Annotated[
            str, Field(description="The USD file to write; empty overwrites the stage's own file")
        ] = "",
    ) -> str:
        """Save the current scene to a USD file."""
        resp = bridge_call(client.save_scene, file_path)
        r = resp["result"]
        return f"Scene saved ({r['action']}) -> {r['file_path']}"

    @mcp.tool(annotations=DESTROYS)
    def new_scene() -> str:
        """Create a fresh empty scene with a /World root prim and Y-up axis."""
        bridge_call(client.new_scene)
        return "New scene created with /World root prim (Y-up)"
