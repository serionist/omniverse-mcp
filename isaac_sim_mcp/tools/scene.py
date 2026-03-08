"""Scene management tools."""


def register(mcp, client, h):
    def _call(fn, *args, **kwargs):
        """Call client method with connection error handling."""
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "error": f"Isaac Sim connection failed: {e}"}
        return resp

    def _check_error(resp):
        """Check response for errors, including traceback."""
        if resp["status"] == "error":
            msg = f"ERROR: {resp['error']}"
            tb = resp.get("traceback", "")
            if tb:
                # Include first 5 lines of traceback for diagnosis
                tb_lines = tb.strip().split("\n")
                msg += "\n" + "\n".join(tb_lines[-5:])
            return msg
        return None

    @mcp.tool()
    def get_scene_tree(root: str = "/", max_depth: int = 5) -> str:
        """Get the USD scene hierarchy as grep-friendly prim-block text.

        Each prim shows: path, type, world position. For large scenes, use dump_scene
        which also includes properties and bounding boxes.

        Args:
            root: Starting prim path (default "/")
            max_depth: Traversal depth (default 5, max 15)
        """
        resp = _call(client.scene_tree, root, min(max_depth, 15), fmt="text")
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        text = r["text"]
        return h.text_response(text, "scene_tree")

    @mcp.tool()
    def dump_scene(
        root: str = "/",
        max_depth: int = 15,
        include_properties: bool = True,
        filter_types: list[str] | None = None,
        property_filter: list[str] | None = None,
    ) -> str:
        """Dump the full scene graph to a text file in prim-block format.

        Writes ALL prims with properties, bounding boxes, and transforms to a grep-friendly file.
        Returns the file path. Use your Read tool to examine specific parts.

        Args:
            root: Starting prim path
            max_depth: Max traversal depth (default 15)
            include_properties: Include all USD properties per prim
            filter_types: Only include prims of these types (e.g., ["Mesh", "Xform"])
            property_filter: Only include properties containing these substrings (e.g., ["joint", "pos"])
        """
        resp = _call(
            client.scene_dump,
            h.output_dir, root, max_depth, include_properties,
            filter_types or [], property_filter=property_filter,
        )
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"Dumped {r['prim_count']} prims ({r['file_size_bytes']:,} bytes) -> {h.rel(r['file_path'])}"

    @mcp.tool()
    def get_prim_properties(prim_path: str) -> str:
        """Get all properties of a specific prim in prim-block text format.

        Returns grep-friendly text with type, position, bounding box, and all USD properties.

        Args:
            prim_path: Full USD path (e.g., "/World/Robot")
        """
        resp = _call(client.prim_properties, prim_path, fmt="text")
        err = _check_error(resp)
        if err:
            return err
        text = resp["result"]["text"]
        return h.text_response(text, f"prim_{prim_path.replace('/', '_')}")

    @mcp.tool()
    def get_prim_bounds(prim_path: str) -> str:
        """Get the bounding box of a prim (center, dimensions, min/max corners, diagonal).

        Use this for spatial reasoning -- understanding sizes, overlap, distances.

        Args:
            prim_path: Full USD path
        """
        resp = _call(client.prim_bounds, prim_path)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return (
            f"[{r['prim_path']}]\n"
            f"center = {r['center'][0]:.4f}, {r['center'][1]:.4f}, {r['center'][2]:.4f}\n"
            f"dimensions = {r['dimensions'][0]:.4f}, {r['dimensions'][1]:.4f}, {r['dimensions'][2]:.4f}\n"
            f"min = {r['min'][0]:.4f}, {r['min'][1]:.4f}, {r['min'][2]:.4f}\n"
            f"max = {r['max'][0]:.4f}, {r['max'][1]:.4f}, {r['max'][2]:.4f}\n"
            f"diagonal = {r['diagonal']:.4f}"
        )

    @mcp.tool()
    def set_prim_transform(
        prim_path: str,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | float | None = None,
    ) -> str:
        """Set position/rotation/scale of a prim.

        Args:
            prim_path: Full USD path
            position: [x, y, z] in meters
            rotation: Euler [rx, ry, rz] degrees or quaternion [w, x, y, z]
            scale: Uniform (float) or [sx, sy, sz]
        """
        resp = _call(client.set_transform, prim_path, position, rotation, scale)
        err = _check_error(resp)
        if err:
            return err
        return f"Transform updated for {prim_path}"

    @mcp.tool()
    def create_prim(
        prim_path: str,
        prim_type: str = "Xform",
        usd_path: str | None = None,
        position: list[float] | None = None,
        rotation: list[float] | None = None,
        scale: list[float] | float | None = None,
        enable_physics: bool = False,
    ) -> str:
        """Create a new prim in the scene.

        Types: Cube, Sphere, Cylinder, Cone, Capsule, Xform, Camera, DistantLight, SphereLight, etc.
        Or load a USD file via usd_path.

        Args:
            prim_path: Where to create (e.g., "/World/MyCube")
            prim_type: USD type name
            usd_path: Optional USD file to load as reference
            position: Optional [x, y, z]
            rotation: Optional euler or quaternion
            scale: Optional scale
            enable_physics: Add RigidBody + Collision APIs
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

        resp = _call(client.create_prim, prim_path, prim_type, **kwargs)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"Created {r['type']} at {r['prim_path']}"

    @mcp.tool()
    def delete_prim(prim_path: str) -> str:
        """Delete a prim and all its children.

        Args:
            prim_path: Full USD path to delete
        """
        resp = _call(client.delete_prim, prim_path)
        err = _check_error(resp)
        if err:
            return err
        return f"Deleted {prim_path}"

    @mcp.tool()
    def set_material(
        prim_path: str,
        color: list[float],
        opacity: float = 1.0,
        roughness: float = 0.5,
        metallic: float = 0.0,
        material_path: str = "",
    ) -> str:
        """Apply a PBR material (OmniPBR) to a prim with color and surface properties.

        Creates a material automatically and binds it to the target prim.
        Color values can be 0-1 floats or 0-255 ints (auto-detected).

        Args:
            prim_path: Target prim to apply material to
            color: [r, g, b] diffuse color. Use 0-1 floats (e.g., [1,0,0] for red) or 0-255 ints
            opacity: 0.0 (transparent) to 1.0 (opaque), default 1.0
            roughness: 0.0 (glossy/mirror) to 1.0 (rough/matte), default 0.5
            metallic: 0.0 (plastic/dielectric) to 1.0 (metal), default 0.0
            material_path: Custom material prim path (auto-generated under /World/Looks/ if omitted)
        """
        resp = _call(client.set_material, prim_path, color, opacity, roughness, metallic, material_path)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        parts = [f"color=[{r['color'][0]:.2f},{r['color'][1]:.2f},{r['color'][2]:.2f}]"]
        if r.get('opacity', 1.0) < 1.0:
            parts.append(f"opacity={r['opacity']}")
        parts.append(f"roughness={r['roughness']}")
        parts.append(f"metallic={r['metallic']}")
        return f"Material {r['material_path']} -> {r['prim_path']} ({', '.join(parts)})"

    @mcp.tool()
    def clone_prim(
        source_path: str,
        target_path: str,
        count: int = 1,
        offset: list[float] | None = None,
    ) -> str:
        """Deep-copy a prim (and all children) to a new path. Supports batch cloning.

        Args:
            source_path: Prim to clone (e.g., "/World/MyCube")
            target_path: Destination path (e.g., "/World/MyCube_Copy")
            count: Number of copies (default 1). Paths auto-suffixed: _001, _002, ...
            offset: [x, y, z] per-copy offset. Each clone shifts by this amount from the previous.
        """
        resp = _call(client.clone_prim, source_path, target_path, count, offset)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        clones = r["clones"]
        if len(clones) == 1:
            return f"Cloned {source_path} -> {clones[0]}"
        return f"Cloned {source_path} -> {len(clones)} copies:\n" + "\n".join(f"  {c}" for c in clones)

    @mcp.tool()
    def set_visibility(prim_path: str, visible: bool = True) -> str:
        """Show or hide a prim (and its descendants).

        Args:
            prim_path: Target prim
            visible: True to show, False to hide
        """
        resp = _call(client.set_visibility, prim_path, visible)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        state = "visible" if r["visible"] else "hidden"
        return f"{r['prim_path']} is now {state}"

    @mcp.tool()
    def save_scene(file_path: str = "") -> str:
        """Save the current scene to a USD file.

        Args:
            file_path: Destination file path. If empty, saves to current file (overwrite).
        """
        resp = _call(client.save_scene, file_path)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"Scene saved ({r['action']}) -> {r['file_path']}"

    @mcp.tool()
    def new_scene() -> str:
        """Create a fresh empty scene with a /World root prim and Y-up axis."""
        resp = _call(client.new_scene)
        err = _check_error(resp)
        if err:
            return err
        return "New scene created with /World root prim (Y-up)"
