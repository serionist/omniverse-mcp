"""Recording tools."""

import os
from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import install_command

from ._annotations import EDITS, READS
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

# start_recording's size when none is given. An extension of 0.2.2 or older ignores the size, so for one of those a
# size other than this one, or any camera_path, gets a warning: the tool can't tell 640 given from 640 by default.
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480


def _ignored_warning(camera_path: str, width: int, height: int) -> str | None:
    """The WARNING line for the recording parameters an older Kit extension ignores (#25), or None when none was
    given."""
    ignored = [f"camera_path {camera_path}"] if camera_path else []
    if width != DEFAULT_WIDTH:
        ignored.append(f"width {width}")
    if height != DEFAULT_HEIGHT:
        ignored.append(f"height {height}")
    if not ignored:
        return None
    named = ignored[0] if len(ignored) == 1 else f"{', '.join(ignored[:-1])} and {ignored[-1]}"
    return (
        f"WARNING: this Kit extension records the active viewport, from its camera at its own size: {named} "
        f"{'is' if len(ignored) == 1 else 'are'} ignored. Install the extension of this server's release, "
        f"{install_command()}, then restart Kit, to record from a camera at a size."
    )


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=EDITS)
    def start_recording(
        fps: Annotated[int, Field(ge=1, description="Frames a second: 5 captures one every 0.2 s")] = 5,
        width: Annotated[int, Field(ge=1, description="Frame width in pixels, up to 4096")] = DEFAULT_WIDTH,
        height: Annotated[int, Field(ge=1, description="Frame height in pixels, up to 4096")] = DEFAULT_HEIGHT,
        camera_path: Annotated[
            str,
            Field(description="The camera to record, e.g. /World/RecCam; the active viewport's camera when empty"),
        ] = "",
        track_prims: Annotated[
            list[str] | None, Field(description='Prims whose state to record, descendants included, e.g. ["/World/G1"]')
        ] = None,
        property_filter: Annotated[
            list[str] | None,
            Field(description='Only properties whose names contain one of these, e.g. ["joint", "pos", "vel"]'),
        ] = None,
    ) -> str:
        """Start recording simulation frames to disk.

        Records camera_path, or the active viewport's camera when empty, at width x height (up to 4096 a side),
        through a render of its own: the viewport, its camera and its size stay as they are. The extra render runs
        while the recording does, and slows the app's updates, the more the larger the frames.

        Captures a frame every few app updates, about 1/fps seconds, whether or not the simulation plays: play it to
        record motion. Frames stop if the stage changes or the camera is deleted; stop_recording says so. Frames are
        saved as PNGs in mcp_output/recordings/, by Kit itself. One recording runs at a time: another start is refused
        until stop_recording. Use stop_recording when done, then get_recording_frame to review any frame.

        Optionally tracks prim state (transforms, properties) alongside video frames.
        State is written to a grep-friendly state.txt in prim-block format.
        """
        rec_dir = os.path.join(h.output_dir, "recordings")
        resp = bridge_call(
            client.recording_start,
            rec_dir,
            fps,
            width,
            height,
            camera_path,
            track_prims=track_prims,
            property_filter=property_filter,
        )
        r = resp["result"]
        # Only an extension that records from the camera at the size names the render product it renders into.
        from_camera = "render_product" in r
        size = f", {r['resolution'][0]}x{r['resolution'][1]} from {r['camera_path']}" if from_camera else ""
        msg = f"Recording {r['session_id']} at {r['fps']}fps{size} -> {h.rel(r['output_dir'])}"
        if from_camera:
            msg += f"\nRenders into {r['render_product']}, deleted at stop"
        if r.get("track_prims"):
            tp: list[str] | int = r["track_prims"]
            count = len(tp) if isinstance(tp, list) else tp
            msg += f"\nTracking {count} prims"
        warning = None if from_camera else _ignored_warning(camera_path, width, height)
        if warning:
            msg += f"\n{warning}"
        msg += "\nCall sim_control('play') to start."
        return msg

    @mcp.tool(annotations=EDITS)
    def stop_recording() -> str:
        """Stop the running recording: wait for the frames still being written, write metadata.json with each frame's
        simulation time, and delete the recording's render product.

        Returns the frame count, the duration, the session folder and the state file, with a note when frames stopped
        early or the cleanup failed in part. An error when no recording runs. Use get_recording_frame to review frames.
        """
        resp = bridge_call(client.recording_stop)
        r = resp["result"]
        msg = f"Stopped. {r['frame_count']} frames, {r['duration_seconds']}s -> {h.rel(r['output_dir'])}"
        if r.get("state_file"):
            msg += f"\nState: {h.rel(r['state_file'])}"
        if r.get("note"):
            msg += f"\nNote: {r['note']}"
        return msg

    @mcp.tool(annotations=READS)
    def get_recording_frame(
        frame_index: Annotated[int, Field(ge=0, description="The frame's number, from 0")] = 0,
        session_dir: Annotated[
            str,
            Field(
                description="The session folder start_recording named, on Kit's machine; the last recording when empty"
            ),
        ] = "",
    ) -> str:
        """Copy one recorded frame to a new PNG in mcp_output/captures/, and return its path and, once the recording
        has stopped, the frame's simulation time.

        Frames come from start_recording, which Kit writes itself as frame_00000.png and on in the session folder: with
        Kit on this machine you can also open them there, and with Kit on another this brings one here. Without
        session_dir it reads the last recording started since the Kit extension started, the running one included. A
        frame Kit failed to capture comes back as an empty file; a frame number past the last is an error. For a
        picture of the scene now, use capture_viewport.
        """
        resp = bridge_call(client.recording_frame, session_dir, frame_index)

        r = resp["result"]
        filepath = h.save_png(r["image_base64"], f"frame_{r['frame_index']:04d}")

        meta = f"Frame {r['frame_index']}"
        if "sim_time" in r:
            meta += f" t={r['sim_time']:.3f}s"
        return f"{meta} -> {filepath}"
