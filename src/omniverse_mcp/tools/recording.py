"""Recording tools."""

import os
from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

# start_recording's size when none is given. The bridge ignores the size, so a size other than this one, or any
# camera_path, gets a warning: the tool can't tell 640 given from 640 by default.
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480


def _ignored_warning(camera_path: str, width: int, height: int) -> str | None:
    """The WARNING line for the recording parameters the Kit extension ignores (#25), or None when none was given."""
    ignored = [f"camera_path {camera_path}"] if camera_path else []
    if width != DEFAULT_WIDTH:
        ignored.append(f"width {width}")
    if height != DEFAULT_HEIGHT:
        ignored.append(f"height {height}")
    if not ignored:
        return None
    named = ignored[0] if len(ignored) == 1 else f"{', '.join(ignored[:-1])} and {ignored[-1]}"
    return (
        f"WARNING: frames come from the active viewport, from its camera at its own size: {named} "
        f"{'is' if len(ignored) == 1 else 'are'} ignored for now (#25). Aim the viewport with set_camera or "
        "look_at_prim before playing."
    )


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=EDITS)
    def start_recording(
        fps: Annotated[int, Field(ge=1, description="Frames a second: 5 captures one every 0.2 s")] = 5,
        width: Annotated[
            int, Field(ge=1, description="Ignored for now: frames come at the active viewport's size (#25)")
        ] = DEFAULT_WIDTH,
        height: Annotated[
            int, Field(ge=1, description="Ignored for now: frames come at the active viewport's size (#25)")
        ] = DEFAULT_HEIGHT,
        camera_path: Annotated[
            str, Field(description="Ignored for now: frames come from the active viewport's camera (#25)")
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

        Records the active viewport, from its camera at its own size: aim it with set_camera or look_at_prim first.
        camera_path, width and height are ignored for now (#25); the answer warns when given a camera_path, or a size
        other than 640x480.

        Captures a screenshot every 1/fps seconds while the simulation is playing.
        Frames are saved as PNGs in mcp_output/recordings/. Use stop_recording when done,
        then get_recording_frame to review any frame.

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
        msg = f"Recording {r['session_id']} at {r['fps']}fps -> {h.rel(r['output_dir'])}"
        if r.get("track_prims"):
            tp: list[str] | int = r["track_prims"]
            count = len(tp) if isinstance(tp, list) else tp
            msg += f"\nTracking {count} prims"
        warning = _ignored_warning(camera_path, width, height)
        if warning:
            msg += f"\n{warning}"
        msg += "\nCall sim_control('play') to start."
        return msg

    @mcp.tool(annotations=EDITS)
    def stop_recording() -> str:
        """Stop the active recording session.

        Returns session info and frame count. Use get_recording_frame to review frames.
        """
        resp = bridge_call(client.recording_stop)
        r = resp["result"]
        msg = f"Stopped. {r['frame_count']} frames, {r['duration_seconds']}s -> {h.rel(r['output_dir'])}"
        if r.get("state_file"):
            msg += f"\nState: {h.rel(r['state_file'])}"
        return msg

    @mcp.tool(annotations=READS)
    def get_recording_frame(
        frame_index: Annotated[int, Field(ge=0, description="The frame's number, from 0")] = 0,
        session_dir: Annotated[str, Field(description="The session's folder; the last recording when empty")] = "",
    ) -> str:
        """Get a specific frame from a recording session. Saves as PNG file."""
        resp = bridge_call(client.recording_frame, session_dir, frame_index)

        r = resp["result"]
        filepath = h.save_png(r["image_base64"], f"frame_{r['frame_index']:04d}")

        meta = f"Frame {r['frame_index']}"
        if "sim_time" in r:
            meta += f" t={r['sim_time']:.3f}s"
        return f"{meta} -> {filepath}"
