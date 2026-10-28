"""Camera and viewport tools."""

import json
import os

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent

from ._bridge import bridge_call

# What to do about a black capture. Camera mode needs no other extension; a rig needs the viewport's lighting menu.
LIGHTING_ADVICE = (
    "Use viewport_light(action='set', mode='camera') for a light that follows the camera (always "
    "available), or a light rig such as mode='Default' if viewport_light('get') lists it."
)
# When the camera light is already on, more light is not the answer.
CAMERA_LIGHT_ON_ADVICE = (
    "The camera light is already on, so the camera may be inside or facing away from the "
    "geometry, or the renderer is still warming up: recapture, or move the camera with "
    "look_at_prim."
)


def register(mcp, client, h):
    @mcp.tool()
    def capture_viewport(
        width: int = 640,
        height: int = 480,
        camera_path: str = "",
        include_image: bool = False,
    ) -> str | list[TextContent | ImageContent]:
        """Capture the viewport and save 3 files for scene understanding:

        1. **Viewport image** (PNG) -- what the camera sees
        2. **Bounding boxes** (TXT) -- screen-space bounding boxes mapping each visible prim to pixel coordinates
        3. **Instance segmentation** (PNG) -- each prim rendered as a unique color, with a legend mapping colors to prim paths

        Use files 2 and 3 to understand which prim is where in the viewport image.
        Set include_image=True to return the viewport image inline (uses more context but lets you see the scene directly).

        Args:
            width: Image width (default 640)
            height: Image height (default 480)
            camera_path: Camera prim path (default: active viewport)
            include_image: Return viewport image inline instead of only saving to file
        """
        resp = bridge_call(client.capture_viewport, width, height, camera_path)

        r = resp["result"]
        lines = []

        # 1. Save viewport image. Its number names the boxes and the segmentation too, taken once: tools run several
        # at once, and the counter can move between two reads of it.
        capture_id = h.next_capture()
        filepath = h.save_png(r["image_base64"], "viewport", number=capture_id)
        lighting_mode = r.get("lighting_mode", "unknown")
        lines.append(f"Viewport: {r['width']}x{r['height']} (lighting: {lighting_mode}) -> {filepath}")
        if r.get("is_black"):
            has_lights = r.get("has_scene_lights", False)
            if lighting_mode == "camera":
                lines.append(f"WARNING: Image is all-black. {CAMERA_LIGHT_ON_ADVICE}")
            elif lighting_mode == "off":
                lines.append(f"WARNING: Image is all-black. Lighting mode is 'off'. {LIGHTING_ADVICE}")
            elif not has_lights and lighting_mode == "stage":
                lines.append(f"WARNING: Image is all-black. No scene lights and mode is 'stage'. {LIGHTING_ADVICE}")
            else:
                lines.append(
                    f"WARNING: Image is all-black (lighting: {lighting_mode}). The renderer may need warmup: "
                    f"try recapturing. If it stays black: {LIGHTING_ADVICE}"
                )

        # 2. Save screen-space bounding boxes
        bboxes = r.get("screen_bboxes", [])
        if bboxes:
            bbox_path = os.path.join(h.output_dir, "captures", f"viewport_{capture_id:04d}_bboxes.txt")
            text = [f"# Screen-space bounding boxes ({r['width']}x{r['height']})\n"]
            text.append("# Format: [x_min, y_min, x_max, y_max] in pixels\n\n")
            for b in bboxes:
                sb = b["screen_bbox"]
                text.append(f"[{b['prim_path']}]\n")
                text.append(f"type = {b['type']}\n")
                text.append(f"screen_bbox = [{sb[0]}, {sb[1]}, {sb[2]}, {sb[3]}]\n")
                text.append(f"world_center = {b['world_center']}\n")
                text.append(f"world_dimensions = {b['world_dimensions']}\n\n")
            h.write(bbox_path, "".join(text))
            lines.append(f"Bounding boxes ({len(bboxes)} prims) -> {h.rel(bbox_path)}")
        else:
            lines.append("Bounding boxes: none (no visible prims)")

        # 3. Save instance segmentation image + legend
        seg_b64 = r.get("segmentation_base64")
        legend = r.get("segmentation_legend", {})
        if seg_b64:
            # A segmentation image that won't decode costs only itself; the capture still stands.
            try:
                seg_path = h.save_png(seg_b64, f"viewport_{capture_id:04d}_segmentation")
            except ToolError as e:
                lines.append(f"Segmentation: ERROR: {e}")
            else:
                legend_path = seg_path.replace(".png", "_legend.txt")
                abs_legend = os.path.join(os.getcwd(), legend_path) if not os.path.isabs(legend_path) else legend_path
                legend_lines = [f"{prim_path} = [{c[0]}, {c[1]}, {c[2]}]\n" for prim_path, c in legend.items()]
                h.write(
                    abs_legend,
                    "# Instance segmentation color legend\n# Format: prim_path = [R, G, B]\n\n" + "".join(legend_lines),
                )
                lines.append(f"Segmentation -> {seg_path}")
                lines.append(f"Color legend ({len(legend)} prims) -> {h.rel(abs_legend)}")
        else:
            lines.append("Segmentation: not available (omni.syntheticdata may not be loaded)")

        if include_image and r.get("image_base64"):
            return [
                TextContent(type="text", text="\n".join(lines)),
                ImageContent(type="image", data=r["image_base64"], mime_type="image/png"),
            ]
        return "\n".join(lines)

    @mcp.tool()
    def set_camera(position: list[float], target: list[float] | None = None) -> str:
        """Set the viewport camera position and optionally aim it at a target point.

        Args:
            position: [x, y, z] camera position in world space
            target: [x, y, z] point to look at (optional)
        """
        resp = bridge_call(client.camera_set, position, target)
        r = resp["result"]
        msg = f"Camera at {r['position']}"
        if r.get("target"):
            msg += f" looking at {r['target']}"
        return msg

    @mcp.tool()
    def look_at_prim(
        prim_path: str,
        distance: float | None = None,
        azimuth: float = 45.0,
        elevation: float = 30.0,
    ) -> str:
        """Point the viewport camera at a prim from a given angle.

        Auto-computes distance from object size if not specified.
        Azimuth 0=front, 90=right, 180=back, 270=left.

        Args:
            prim_path: Target prim to look at
            distance: Camera distance (auto if omitted)
            azimuth: Horizontal angle in degrees (0=front)
            elevation: Vertical angle in degrees above horizontal
        """
        resp = bridge_call(client.camera_look_at, prim_path, distance, azimuth, elevation)
        r = resp["result"]
        return (
            f"Camera at {r['camera_position']} looking at {r['target']}\n"
            f"Distance: {r['distance']}m, Azimuth: {r['azimuth']}deg, Elevation: {r['elevation']}deg"
        )

    @mcp.tool()
    def inspect_prim(
        prim_path: str,
        angles: list[str] | None = None,
        width: int = 640,
        height: int = 480,
        zoom_offset: float = 0.0,
        isolate: bool = False,
        include_segmentation: bool = False,
    ) -> str:
        """Orbit-capture: take screenshots from 14 systematic angles around a prim (cube-based).

        Auto-fits camera distance so the prim fills the viewport with ~10px margin.
        Captures from all 6 face centers + 8 cube corners by default, giving full coverage.
        Saves each angle as a PNG file. Use Read tool to view images.

        Args:
            prim_path: Target prim
            angles: Angle names (default: all 14). Face centers: "front", "back", "right",
                    "left", "top", "bottom". Cube corners: "top_front_right",
                    "top_front_left", "top_back_right", "top_back_left",
                    "bottom_front_right", "bottom_front_left", "bottom_back_right",
                    "bottom_back_left". Pass a subset list to capture fewer angles.
            width: Image width per capture
            height: Image height per capture
            zoom_offset: Adjust auto-fit distance. 0=auto-fit (default), negative=closer,
                        positive=further. E.g., -0.3 = 30% closer, 0.5 = 50% further.
            isolate: Hide all other scene content during capture (restore after)
            include_segmentation: Also capture instance segmentation at each angle
        """
        resp = bridge_call(
            client.camera_inspect,
            prim_path,
            angles,
            width,
            height,
            zoom_offset=zoom_offset,
            isolate=isolate,
            include_segmentation=include_segmentation,
        )

        r = resp["result"]
        zoom_info = f", zoom_offset={r['zoom_offset']}" if r.get("zoom_offset", 0) != 0 else ""
        isolate_info = ", isolated" if r.get("isolate") else ""
        lines = [f"Inspect {prim_path} (dist={r['distance']}m{zoom_info}{isolate_info})"]
        for warning in r.get("isolate_warnings", []):
            lines.append(f"  WARNING (isolate): {warning}")
        warned = False
        for cap in r["captures"]:
            if "error" in cap:
                lines.append(f"  {cap['angle']}: ERROR {cap['error']}")
            else:
                filepath = h.save_png(cap["image_base64"], f"inspect_{cap['angle']}")
                cap_line = f"  {cap['angle']}: {filepath}"
                if cap.get("segmentation_base64"):
                    try:
                        seg_path = h.save_png(cap["segmentation_base64"], f"inspect_{cap['angle']}_seg")
                    except ToolError as e:
                        seg_path = ""
                        cap_line += f" | seg: ERROR: {e}"
                    else:
                        cap_line += f" | seg: {seg_path}"
                    legend = cap.get("segmentation_legend", {})
                    if legend and seg_path:
                        legend_path = seg_path.replace(".png", "_legend.txt")
                        abs_legend = (
                            os.path.join(os.getcwd(), legend_path) if not os.path.isabs(legend_path) else legend_path
                        )
                        h.write(abs_legend, "".join(f"{pp} = [{c[0]}, {c[1]}, {c[2]}]\n" for pp, c in legend.items()))
                if cap.get("is_black") and not warned:
                    advice = CAMERA_LIGHT_ON_ADVICE if r.get("lighting_mode") == "camera" else LIGHTING_ADVICE
                    warning = f"  WARNING: One or more captures are all-black. {advice}"
                    if r.get("isolate"):
                        warning += (
                            " isolate=True hid the other prims, though not the lights: if the scene is lit by"
                            " something it hid, such as emissive geometry, try again without isolate."
                        )
                    lines.append(warning)
                    warned = True
                lines.append(cap_line)
        return "\n".join(lines)

    @mcp.tool()
    def viewport_light(action: str = "get", mode: str = "", enabled: bool = True) -> str:
        """Query or control viewport lighting mode.

        Actions:
        - "get": Return current lighting mode, available modes, and scene lights
        - "set": Set lighting mode. Available modes: "off", "camera", "stage",
          "Default", "Colored Lights", "Grey Studio" (light rigs)
        - "set_camera_light": Legacy — enable/disable camera light

        When capture_viewport returns a black image, use this tool to check and change
        the lighting mode, then recapture.

        Args:
            action: "get", "set", or "set_camera_light"
            mode: Lighting mode to set (for "set" action)
            enabled: Whether to enable (true) or disable (false) camera light (for set_camera_light)
        """
        resp = bridge_call(client.viewport_light, action, enabled, mode=mode)

        r = resp["result"]
        lines = []
        if action == "get":
            lines.append(f"Lighting mode: {r.get('lighting_mode', 'unknown')}")
            available = r.get("available_modes", [])
            if available:
                lines.append(f"Available modes: {', '.join(available)}")
            lines.append(f"Scene has lights: {'yes' if r.get('has_scene_lights') else 'no'}")
            scene_lights = r.get("scene_lights", [])
            if scene_lights:
                lines.append(f"Scene lights ({len(scene_lights)}):")
                for lt in scene_lights:
                    lines.append(f"  {lt['path']} ({lt['type']}, intensity={lt.get('intensity', 'N/A')})")
        elif action in ("set", "set_camera_light"):
            lines.append(f"Lighting mode: {r.get('lighting_mode', 'unknown')}")
            if r.get("message"):
                lines.append(r["message"])
        else:
            lines.append(json.dumps(r, indent=2))
        return "\n".join(lines)
