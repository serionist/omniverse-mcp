"""Scene management tools."""

from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import DESTROYS, EDITS, READS, tool
from ._bridge import bridge_call
from ._params import Position, PrimPath, Rotation, Scale

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def _open_notes(r: dict[str, Any]) -> list[str]:
    """What the model should know of a stage open_scene opened, beyond its numbers."""
    notes: list[str] = []
    if r.get("up_axis_authored") is False:
        notes.append(f"the file sets no upAxis: USD reads it as {r['up_axis']}")
    if r.get("meters_per_unit_authored") is False:
        notes.append(f"the file sets no metersPerUnit: USD reads it as {r['meters_per_unit']} (centimetres)")
    if r.get("package"):
        # Kit calls a .usdz's stage writable, but USD can't save one back.
        notes.append(
            "a .usdz package can't be saved back: flatten_usd, or save_scene with a file_path ending .usd or .usda, "
            "keeps changes"
        )
    elif r.get("writable") is False:
        notes.append("the stage is read-only here: save_scene needs a file_path to keep changes")
    if r.get("stopped"):
        notes.append("the simulation was playing or paused: it is stopped now")
    return notes


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, READS)
    def get_scene_tree(
        root: Annotated[str, Field(description="Prim path to start from")] = "/",
        max_depth: Annotated[
            int,
            Field(
                ge=0,
                le=15,
                description="How many levels below root to list; a prim on the last says how many children it has",
            ),
        ] = 5,
    ) -> str:
        """List the stage's prims under root as prim blocks: each one's path, type and world position.

        Use it to find prim paths before acting on them: it is the lightest look at a scene. A prim at max_depth that
        has children says how many, as children = N (truncated), and nothing below it is listed. The prims inside an
        instanceable prim are not listed
        (get_prim_face_count_tree looks inside). For properties, use get_prim_properties on one prim, or dump_scene for
        many at once, written to a file to grep.
        """
        resp = bridge_call(client.scene_tree, root, max_depth, fmt="text")
        r = resp["result"]
        text = r["text"]
        return h.text_response(text, "scene_tree")

    @tool(mcp, READS)
    def dump_scene(
        root: Annotated[str, Field(description="Prim path to start from")] = "/",
        max_depth: Annotated[int, Field(ge=0, description="How many levels below root; 0 for root alone")] = 15,
        include_properties: Annotated[bool, Field(description="Include every USD property of each prim")] = True,
        filter_types: Annotated[
            list[str] | None, Field(description='Only prims of these types, e.g. ["Mesh", "Xform"]')
        ] = None,
        property_filter: Annotated[
            list[str] | None, Field(description='Only properties whose names contain one of these, e.g. ["joint"]')
        ] = None,
    ) -> str:
        """Write the prims under root, with their properties, to mcp_output/scene_dump.txt as prim blocks; returns the
        file's path, to grep or read in parts, and how many prims it wrote.

        Each block holds the prim's type, world position, rotation and bounding box, and every attribute's value unless
        include_properties is False. Use it for many prims' values at once, or for depths beyond get_scene_tree's 15;
        get_prim_properties reads one prim inline. filter_types keeps the blocks of those types and
        still walks the others' children. Each call replaces the last dump. Kit writes the file itself, so with Kit on
        another machine it lands there. Like get_scene_tree, it doesn't list the prims inside an instanceable prim.
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

    @tool(mcp, READS)
    def get_prim_properties(prim_path: PrimPath) -> str:
        """Get one prim as a prim block: its type, world position and rotation, world bounding box, physics flags, and
        every attribute's value.

        Use it to read one prim; get_prim_bounds when only its size and place matter, dump_scene for many prims at
        once, get_scene_tree to find paths. Relationships, such as a material binding, are named without their targets.
        """
        resp = bridge_call(client.prim_properties, prim_path, fmt="text")
        text = resp["result"]["text"]
        return h.text_response(text, f"prim_{prim_path.replace('/', '_')}")

    @tool(mcp, READS)
    def get_prim_bounds(prim_path: PrimPath) -> str:
        """Get a prim's world-space, axis-aligned bounding box, its descendants included: centre, dimensions, min and
        max corners, and diagonal, in the stage's units.

        Use it to place things and measure: what rests on what (a bottom on a top along the up axis), gaps, sizes.
        get_prim_properties gives the same box among a prim's other values. A prim with no geometry, such as an empty
        Xform, gets a 0.1 box at its position rather than an error.
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

    @tool(mcp, EDITS)
    def set_prim_transform(
        prim_path: PrimPath,
        position: Position = None,
        rotation: Rotation = None,
        scale: Scale = None,
    ) -> str:
        """Set a prim's position, rotation or scale relative to its parent; any of the three left out keeps its value.

        Use it to move, turn or size a prim; to aim the viewport camera, use set_camera or look_at_prim, and to push a
        rigid body while physics runs, apply_force. Values are in the parent's space, not world space:
        get_prim_properties gives a prim's world position. It rewrites the prim's xform ops as translate, rotateXYZ
        (orient for a quaternion) and scale, and drops any other op, so a prim placed by a matrix (xformOp:transform),
        as imported assets often are, loses that placement. An error when the prim doesn't exist or can't be
        transformed.
        """
        bridge_call(client.set_transform, prim_path, position, rotation, scale)
        return f"Transform updated for {prim_path}"

    @tool(mcp, EDITS)
    def create_prim(
        prim_path: Annotated[str, Field(description='Where to create it, e.g. "/World/MyCube"')],
        prim_type: Annotated[str, Field(description="USD type name, e.g. Cube, Sphere, Xform, DistantLight")] = "Xform",
        usd_path: Annotated[
            str | None,
            Field(description="A USD file to reference instead of a type: an absolute path on Kit's machine, or a URL"),
        ] = None,
        position: Position = None,
        rotation: Rotation = None,
        scale: Scale = None,
        enable_physics: Annotated[bool, Field(description="Add the RigidBody and Collision APIs")] = False,
    ) -> str:
        """Create a prim at prim_path: a shape, an Xform, a camera, a light or any USD type, or a reference to a file.

        prim_type is a USD type name: Cube, Sphere, Cylinder, Cone, Capsule, Xform, Camera, DistantLight, DomeLight,
        SphereLight and the rest. Missing parents are made as typeless prims. A prim already at prim_path keeps its
        type: one of another type is refused, one of the same type takes the new transform. usd_path adds its reference
        to a prim already there. enable_physics puts the RigidBody and Collision APIs on the prim itself, so a shape
        falls and collides while the simulation plays; the meshes under an Xform or a referenced file's root get no
        Collision API of their own. To copy a prim, use clone_prim; for a robot, create_robot.
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

    @tool(mcp, DESTROYS)
    def delete_prim(prim_path: PrimPath) -> str:
        """Delete a prim and everything under it, by removing what the stage's edit layer holds at that path.

        A prim another layer defines too, or one a reference or payload on a prim above brings, such as a part of a
        referenced asset, can't be deleted this way: the call is refused, saying why, and nothing changes;
        set_visibility hides such a prim, or its instance for a prim inside one. To hide a prim and keep it, use
        set_visibility. Kit's undo doesn't record the delete, and the file on disk keeps the prim until save_scene. An
        error when no prim is there.
        """
        resp = bridge_call(client.delete_prim, prim_path)
        if resp["result"].get("checked"):
            return f"Deleted {prim_path}"
        # An extension from before the check answers "deleted" for a prim another layer keeps, and the plugin updates
        # the server ahead of the extension.
        return (
            f"Deleted {prim_path}\nThis Kit extension, older than the server, answers deleted for a prim another layer "
            "keeps: check with get_scene_tree"
        )

    @tool(mcp, EDITS)
    def set_material(
        prim_path: PrimPath,
        color: Annotated[
            list[float],
            Field(description="[r, g, b] diffuse colour: 0-1 floats (e.g. [1, 0, 0] for red) or 0-255 ints"),
        ],
        opacity: Annotated[float, Field(ge=0, le=1, description="0 transparent to 1 opaque")] = 1.0,
        roughness: Annotated[float, Field(ge=0, le=1, description="0 glossy (mirror) to 1 rough (matte)")] = 0.5,
        metallic: Annotated[float, Field(ge=0, le=1, description="0 plastic (dielectric) to 1 metal")] = 0.0,
        material_path: Annotated[
            str, Field(description="The material prim's path; made under /World/Looks/ when empty")
        ] = "",
    ) -> str:
        """Colour a prim with an OmniPBR material: make the material, or update the one at its path, set its colour and
        surface values, and bind it to the prim in place of its binding.

        Without material_path the material is /World/Looks/<prim name>_Mat, so prims of the same name share one and
        colouring one recolours the rest: give material_path to keep them apart, or to share one on purpose. The binding
        reaches the prim's children unless they have bindings of their own. For friction and bounce, use
        set_physics_properties; to repoint bindings after materials move, update_material_paths.
        """
        resp = bridge_call(client.set_material, prim_path, color, opacity, roughness, metallic, material_path)
        r = resp["result"]
        parts = [f"color=[{r['color'][0]:.2f},{r['color'][1]:.2f},{r['color'][2]:.2f}]"]
        if r.get("opacity", 1.0) < 1.0:
            parts.append(f"opacity={r['opacity']}")
        parts.append(f"roughness={r['roughness']}")
        parts.append(f"metallic={r['metallic']}")
        return f"Material {r['material_path']} -> {r['prim_path']} ({', '.join(parts)})"

    @tool(mcp, EDITS)
    def clone_prim(
        source_path: Annotated[str, Field(description='The prim to clone, e.g. "/World/MyCube"')],
        target_path: Annotated[str, Field(description='Where the copy goes, e.g. "/World/MyCube_Copy"')],
        count: Annotated[
            int, Field(ge=1, description="How many copies: one goes to target_path, more to target_path_001, _002, ...")
        ] = 1,
        offset: Annotated[
            list[float] | None,
            Field(description="[x, y, z] in the parent's space: each copy after the first sits this far from the last"),
        ] = None,
    ) -> str:
        """Copy a prim with everything under it to a new path, once or as a row of count copies.

        The first copy sits on the source and each next one moves by offset from the one before, so a single copy is
        never moved: move it with set_prim_transform. With offset, the copies it places, and a single copy, get their
        xform ops rewritten as set_prim_transform does, counted from the source's translate (the origin without one):
        copies of a prim placed by a matrix lose that placement. It copies what the stage's root layer holds at
        source_path, its references included, so a prim from a sublayer, or from inside a referenced asset, can't be
        copied whole. A target path that already holds a prim is refused before anything is copied. For a new prim,
        use create_prim.
        """
        resp = bridge_call(client.clone_prim, source_path, target_path, count, offset)
        r = resp["result"]
        clones = r["clones"]
        if len(clones) == 1:
            return f"Cloned {source_path} -> {clones[0]}"
        return f"Cloned {source_path} -> {len(clones)} copies:\n" + "\n".join(f"  {c}" for c in clones)

    @tool(mcp, EDITS)
    def set_visibility(
        prim_path: PrimPath,
        visible: Annotated[bool, Field(description="True to show, False to hide")] = True,
    ) -> str:
        """Show or hide a prim and everything under it, in the viewport and in captures; the prim stays in the stage.

        Use it to see inside or behind something, then show it again; delete_prim removes a prim, and inspect_prim's
        isolate hides all but one prim for its captures. Showing a prim under a hidden parent shows the parent and hides
        the parent's other children, as USD's MakeVisible does. An error for a prim that has no visibility, such as a
        material.
        """
        resp = bridge_call(client.set_visibility, prim_path, visible)
        r = resp["result"]
        state = "visible" if r["visible"] else "hidden"
        return f"{r['prim_path']} is now {state}"

    @tool(mcp, DESTROYS)
    def save_scene(
        file_path: Annotated[
            str, Field(description="The USD file to write, on Kit's machine; empty overwrites the stage's own file")
        ] = "",
    ) -> str:
        """Write the open stage's root layer to a USD file: back to the stage's own file when file_path is empty, or as
        a copy at file_path.

        Without file_path it overwrites the file the stage was opened from, and fails for a stage never saved, such as
        new_scene's. With file_path it overwrites any file there, and the stage stays tied to its own file, or to none.
        Only the root layer is written: sublayers and referenced files stay as they are, still referenced. For one
        self-contained file, use flatten_usd; for one prim's subtree, export_prim_as_file.
        """
        resp = bridge_call(client.save_scene, file_path)
        r = resp["result"]
        return f"Scene saved ({r['action']}) -> {r['file_path']}"

    @tool(mcp, DESTROYS)
    def open_scene(
        file_path: Annotated[
            str,
            Field(
                description="The USD file: a path on Kit's machine, a relative one read from the folder Kit was "
                "started in; a URL (omniverse://, https://, file:///); or a path in Isaac Sim's asset library "
                "(/Isaac/...)"
            ),
        ],
    ) -> str:
        """Open a USD file as the stage, in place of the open one, which goes with its unsaved changes.

        Use it to work on a scene from a file; new_scene starts an empty stage instead, and save_scene writes the open
        one, so call save_scene first to keep it. Opening the stage's own file reloads it from disk. It stops the
        simulation first; a recording that runs stops taking frames, and draw_debug's drawings go. Refused, with the
        open stage kept, for a file that isn't there or can't be reached, a type USD doesn't open, a local file that
        holds no USD (a Git LFS pointer, say), or while Kit opens or closes a stage. A file that passes those checks
        and still fails to load leaves no stage open, and the error says so; an open that takes over 80 s goes on in
        Kit after the error. Answers the path opened, the stage it replaced, and the stage's up axis, meters_per_unit,
        default prim and prim count, with a note for an axis or units the file leaves to USD's fallbacks.
        """
        resp = bridge_call(client.open_scene, file_path)
        r = resp["result"]
        lines = [f"Opened {r['file_path']}"]
        if r.get("replaced"):
            lines.append(f"replaced = {r['replaced']}")
        lines += [
            f"up_axis = {r['up_axis']}",
            f"meters_per_unit = {r['meters_per_unit']}",
            f"default_prim = {r.get('default_prim') or 'none'}",
            f"prim_count = {r['prim_count']}",
        ]
        lines += [f"note = {note}" for note in _open_notes(r)]
        if r.get("recording_note"):
            lines.append(f"recording_note = {r['recording_note']}")
        return "\n".join(lines)

    @tool(mcp, DESTROYS)
    def new_scene() -> str:
        """Discard the open stage, unsaved changes included, and open an empty one: Y-up, with a /World Xform as its
        default prim.

        Call save_scene first to keep the old one. Isaac Sim's robots and stages are Z-up: for robot work, open a Z-up
        stage with open_scene, or set the axis with execute_script (UsdGeom.SetStageUpAxis) before adding anything.
        The new stage has no file, so save_scene needs a file_path for it. A recording that runs stops taking frames,
        and draw_debug's drawings go.
        """
        bridge_call(client.new_scene)
        return "New scene created with /World root prim (Y-up)"
