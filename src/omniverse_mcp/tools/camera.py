"""Camera and viewport tools."""

import base64
import binascii
import json
import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ImageContent, TextContent
from pydantic import Field

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import install_command

from ._annotations import EDITS, READS, tool
from ._bridge import bridge_call
from ._params import PrimPath

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

Width = Annotated[
    int, Field(ge=1, description="Image width in pixels, up to 4096; the camera is rendered at this size")
]
Height = Annotated[
    int, Field(ge=1, description="Image height in pixels, up to 4096; the camera is rendered at this size")
]

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(image_base64: str) -> tuple[int, int] | None:
    """A base64 PNG's width and height, from the first 24 bytes: its signature and header chunk. None for anything
    else. The server's own: the extension's PNG module is Kit's side, which the server never imports."""
    try:
        head = base64.b64decode(image_base64[:32])[:24]
    except (binascii.Error, ValueError):
        return None
    if len(head) < 24 or not head.startswith(_PNG_SIGNATURE) or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def _sizes(r: dict[str, Any]) -> tuple[str, str | None]:
    """The image's size as `WxH`, from its own header when it has one, and a warning when the answer's size, which
    its boxes are in, isn't it: an extension from before #51 rendered the viewport's size and scaled the boxes to the
    size asked for."""
    told = (r.get("width"), r.get("height"))
    real = _png_size(r.get("image_base64") or "") or told
    shown = f"{real[0]}x{real[1]}"
    if None in told or tuple(told) == tuple(real):
        return shown, None
    return shown, (
        f"WARNING: The image is {shown} but its boxes are for {told[0]}x{told[1]}: the Kit extension is older than "
        f"this server. Install this server's, {install_command()}, then restart Kit."
    )


def _older_inspect_warning(r: dict[str, Any], width: int, height: int) -> list[str]:
    """For an inspect_prim answer without its size, from an extension before #51: a warning when its images aren't the
    size asked for, read from the first one's header, since that extension captured the viewport at its own size."""
    first = next((cap["image_base64"] for cap in r.get("captures", []) if cap.get("image_base64")), "")
    got = _png_size(first)
    if got is None or got == (width, height):
        return []
    return [
        f"  WARNING: The images are {got[0]}x{got[1]}, not the {width}x{height} asked for: the Kit extension is older "
        f"than this server. Install this server's, {install_command()}, then restart Kit."
    ]


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


def _legend_beside(seg_path: str) -> str:
    """The legend file beside a segmentation image, from the path save_png gave: relative to the working folder, or
    absolute. Only the file's own suffix changes, whatever its folders are called."""
    seg = Path(seg_path)
    legend = seg.with_name(f"{seg.stem}_legend.txt")
    return str(legend if legend.is_absolute() else Path.cwd() / legend)


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, READS)
    def capture_viewport(
        width: Width = 640,
        height: Height = 480,
        camera_path: Annotated[
            str,
            Field(description="The camera prim to capture from, which must be a camera; the viewport's when empty"),
        ] = "",
        include_image: Annotated[
            bool, Field(description="Also return the image inline, besides the file (uses more context)")
        ] = False,
    ) -> str | list[TextContent | ImageContent]:
        """Render one frame from a camera at width x height and save 3 files to mcp_output/captures/:

        1. **Image** (PNG): what the camera sees.
        2. **Bounding boxes** (TXT): each visible prim under /World, with its box in pixels, world centre and size.
        3. **Instance segmentation** (PNG): each prim in a colour of its own, with a legend naming them.

        Use it to see the scene and tell which prim is where: the boxes for places, the segmentation for prims that
        overlap. It renders camera_path, or the viewport's camera when empty, in a render of its own, so the viewport
        the user sees keeps its camera and size. Aim first with set_camera or look_at_prim; for one prim from every
        side, use inspect_prim. include_image=True also returns the image inline, at a cost in context. An all-black
        image comes with a warning saying what to change with viewport_light. Without omni.syntheticdata the image
        and boxes still come, and the segmentation line says why it is missing.
        """
        resp = bridge_call(client.capture_viewport, width, height, camera_path)

        r = resp["result"]
        lines: list[str] = []
        size, mismatch = _sizes(r)

        # 1. Save viewport image. Its number names the boxes and the segmentation too, taken once: tools run several
        # at once, and the counter can move between two reads of it.
        capture_id = h.next_capture()
        filepath = h.save_png(r["image_base64"], "viewport", number=capture_id)
        lighting_mode = r.get("lighting_mode", "unknown")
        lines.append(f"Viewport: {size} (lighting: {lighting_mode}) -> {filepath}")
        if mismatch:
            lines.append(mismatch)
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
            text = [f"# Screen-space bounding boxes ({r.get('width')}x{r.get('height')})\n"]
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
                abs_legend = _legend_beside(seg_path)
                legend_lines = [f"{prim_path} = [{c[0]}, {c[1]}, {c[2]}]\n" for prim_path, c in legend.items()]
                h.write(
                    abs_legend,
                    "# Instance segmentation color legend\n# Format: prim_path = [R, G, B]\n\n" + "".join(legend_lines),
                )
                lines.append(f"Segmentation -> {seg_path}")
                lines.append(f"Color legend ({len(legend)} prims) -> {h.rel(abs_legend)}")
        elif r.get("segmentation_error"):
            lines.append(f"Segmentation: ERROR {r['segmentation_error']}")
        else:
            # An extension from before segmentation_error gives no reason.
            lines.append("Segmentation: not available (omni.syntheticdata may not be loaded)")

        if include_image and r.get("image_base64"):
            return [
                TextContent(type="text", text="\n".join(lines)),
                ImageContent(type="image", data=r["image_base64"], mime_type="image/png"),
            ]
        return "\n".join(lines)

    @tool(mcp, EDITS)
    def set_camera(
        position: Annotated[list[float], Field(description="[x, y, z] camera position in world space")],
        target: Annotated[
            list[float] | None, Field(description="[x, y, z] world point to look at; the origin when omitted")
        ] = None,
    ) -> str:
        """Move the viewport's camera to a world position and aim it at a target point, for a view from coordinates
        you choose.

        target defaults to the world origin. To frame a prim by its path, use look_at_prim; to capture from another
        camera without moving the viewport, capture_viewport's camera_path. It moves whichever camera the viewport
        looks through, a scene camera included, and the user sees the move. Aiming needs Isaac Sim
        (isaacsim.core.utils.viewports): other Kit apps only move the camera, without aiming it.
        """
        resp = bridge_call(client.camera_set, position, target)
        r = resp["result"]
        msg = f"Camera at {r['position']}"
        if r.get("target"):
            msg += f" looking at {r['target']}"
        return msg

    @tool(mcp, EDITS)
    def look_at_prim(
        prim_path: PrimPath,
        distance: Annotated[
            float | None,
            Field(gt=0, description="From the prim's centre, in stage units; 2.5 times its largest side when omitted"),
        ] = None,
        azimuth: Annotated[
            float,
            Field(
                description="Horizontal angle in degrees: 0 from the front (+Y on a Z-up stage, +Z on a Y-up one), "
                "90 from the right (+X), 180 the back, 270 the left"
            ),
        ] = 45.0,
        elevation: Annotated[float, Field(description="Vertical angle in degrees above the horizontal")] = 30.0,
    ) -> str:
        """Move the viewport's camera to frame a prim from an angle around it, aimed at the prim's centre, given only
        its path.

        Use it to see one prim: set_camera places the camera at coordinates, and inspect_prim captures a prim from up
        to 14 sides in one call; capture_viewport then takes the picture. It moves whichever camera the viewport looks
        through, and the user sees the move. Aiming needs Isaac Sim (isaacsim.core.utils.viewports): other Kit apps
        only move the camera, without aiming it. An error when the prim doesn't exist.
        """
        resp = bridge_call(client.camera_look_at, prim_path, distance, azimuth, elevation)
        r = resp["result"]
        return (
            f"Camera at {r['camera_position']} looking at {r['target']}\n"
            f"Distance: {r['distance']}m, Azimuth: {r['azimuth']}deg, Elevation: {r['elevation']}deg"
        )

    @tool(mcp, EDITS)
    def inspect_prim(
        prim_path: PrimPath,
        angles: Annotated[
            list[str] | None,
            Field(
                description=(
                    'Angle names, all 14 when omitted. Face centres: "front", "back", "right", "left", "top", '
                    '"bottom". Cube corners: "top_front_right", "top_front_left", "top_back_right", '
                    '"top_back_left", "bottom_front_right", "bottom_front_left", "bottom_back_right", '
                    '"bottom_back_left"'
                )
            ),
        ] = None,
        width: Width = 640,
        height: Height = 480,
        zoom_offset: Annotated[
            float,
            Field(
                gt=-1,
                description="Adjusts the fitted distance: negative closer, positive further (-0.3 is 30% closer)",
            ),
        ] = 0.0,
        isolate: Annotated[bool, Field(description="Hide everything else while capturing, then restore it")] = False,
        include_segmentation: Annotated[
            bool, Field(description="Also capture instance segmentation at each angle")
        ] = False,
    ) -> str:
        """Capture a prim from up to 14 angles around it, each framed so the prim fills the image, and save each as a
        PNG in mcp_output/captures/.

        Use it to see one object from every side; capture_viewport takes one picture from a camera as it stands. The
        angles are the 6 face centres and 8 corners of a cube around the prim, all 14 unless angles names some. The
        distance is fitted to the prim's size at width x height, then moved by zoom_offset. It moves the viewport's own
        camera, which stays at the last angle, and renders each angle in a render of its own at width x height. isolate
        hides everything but the prim and the lights while it captures, then shows them again. A call has about 80 s:
        an angle that fails says why, and the angles after it say Not captured. An orthographic camera is refused.
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
        # An extension from before #51 doesn't say the size, which was the viewport's whatever was asked.
        size_info = f", {r['width']}x{r['height']}" if r.get("width") and r.get("height") else ""
        lines = [f"Inspect {prim_path} (dist={r['distance']}m{size_info}{zoom_info}{isolate_info})"]
        if not size_info:
            lines.extend(_older_inspect_warning(r, width, height))
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
                        h.write(
                            _legend_beside(seg_path),
                            "".join(f"{pp} = [{c[0]}, {c[1]}, {c[2]}]\n" for pp, c in legend.items()),
                        )
                elif cap.get("segmentation_error"):
                    cap_line += f" | seg: ERROR {cap['segmentation_error']}"
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

    @tool(mcp, EDITS)
    def viewport_light(
        action: Annotated[
            Literal["get", "set", "set_camera_light"],
            Field(description='"get" the mode, "set" one, or the legacy "set_camera_light"'),
        ] = "get",
        mode: Annotated[
            str, Field(description='For "set": "off", "camera", "stage", or a light rig "get" lists, e.g. "Default"')
        ] = "",
        enabled: Annotated[bool, Field(description='For "set_camera_light": turn the camera light on or off')] = True,
    ) -> str:
        """Read or set the viewport's lighting mode, which decides how the viewport and its captures are lit, without
        changing the scene.

        Use it when a capture comes back black, then capture again. "get" (the default) answers the mode, the modes on
        offer, and the stage's lights with their intensity. "set" takes a mode "get" lists: "stage" (the stage's own
        lights), "camera" (a light that follows the camera), "off", or a light rig such as "Default", "Colored Lights"
        or "Grey Studio"; rigs need Kit's lighting menu, omni.kit.viewport.menubar.lighting, and a mode not on offer is
        an error. "set_camera_light" is the older switch, turning the camera light on or off with enabled. To add a
        light to the stage itself, use create_prim (DistantLight, DomeLight).
        """
        resp = bridge_call(client.viewport_light, action, enabled, mode=mode)

        r = resp["result"]
        lines: list[str] = []
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
