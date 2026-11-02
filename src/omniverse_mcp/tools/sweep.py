"""The capture sweep (#157): many shots, each with its own pose, lens, variant selections and time, in one call, as a
job Kit runs while it renders; get_job reads it."""

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, tool
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

# The most shots one sweep takes, as the Kit extension holds it.
MAX_SHOTS = 2000
# How many shot numbers a line names before it says how many more.
SHOWN = 10

Point = Annotated[list[float], Field(min_length=3, max_length=3)]


class Shot(BaseModel):
    """One picture of a sweep: a pose (position with yaw and pitch, position with target, or camera_path), a lens, the
    variant selections it shows and the timeline time it shows."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field("", max_length=100, description="Names its PNG and its manifest entry, e.g. dock_a_open")
    position: Point | None = Field(None, description="Where the camera is, [x, y, z] in the stage's world and units")
    yaw: float | None = Field(
        None, description="Degrees about the stage's up axis, counter-clockwise seen from above, 0 looking along +X"
    )
    pitch: float | None = Field(
        None, ge=-90, le=90, description="Degrees above the horizon, -90 straight down; 0 when left out"
    )
    target: Point | None = Field(None, description="A point to look at, [x, y, z], instead of yaw and pitch")
    camera_path: str | None = Field(
        None, description="A camera of the stage to render through as it is, instead of a position and a lens"
    )
    focal_length: float | None = Field(None, gt=0, description="Millimetres; Kit's own camera's 18.15 when left out")
    horizontal_aperture: float | None = Field(None, gt=0, description="Millimetres; 20.955 when left out")
    vertical_aperture: float | None = Field(
        None, gt=0, description="Millimetres; fitted to the image's shape when left out, refused when it doesn't fit"
    )
    clipping_range: list[float] | None = Field(
        None,
        min_length=2,
        max_length=2,
        description="[near, far] in the stage's units; Isaac Sim's 0.01 m to 10,000 km when left out",
    )
    selections: dict[str, dict[str, str]] | None = Field(
        None,
        description='The variants it shows, {prim: {set: variant}}, e.g. {"/World/Dock": {"door": "open"}}; a set it '
        "doesn't name shows what it showed before the sweep",
    )
    time: float | None = Field(
        None, description="The timeline's time to show, in seconds; the timeline as it was at the start when left out"
    )


def _read_shots_file(path: str) -> object:
    """A shots file's JSON: a list of shots, or a sweep's manifest, sent to Kit as it is, which checks each shot.
    ToolError when it can't be read or is neither."""
    try:
        data: object = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ToolError(f"Can't read shots_file {path}: {e}") from e
    if isinstance(data, list) or (isinstance(data, dict) and "shots" in data):
        return cast("object", data)
    raise ToolError(f"shots_file {path} holds neither a list of shots nor a sweep's manifest, with its shots")


def _numbers(found: list[int]) -> str:
    shown = ", ".join(str(i) for i in found[:SHOWN])
    more = f" and {len(found) - SHOWN} more" if len(found) > SHOWN else ""
    return f"{'shot' if len(found) == 1 else 'shots'} {shown}{more}"


def sweep_line(result: dict[str, Any], h: "Helpers") -> str:
    """A completed sweep as get_job gives it, in one line: `400 shots in mcp_output/sweeps/site_a/ (manifest.json); 2
    black: shots 12, 13; 1 failed: shot 300`."""
    asked, done = result.get("asked", 0), result.get("done", 0)
    count = f"{done} of {asked}" if done < asked else f"{done}"
    parts = [f"{count} {'shot' if asked == 1 else 'shots'} in {h.rel(result['folder'])}/ (manifest.json)"]
    for key, what in (("black", "black"), ("failed", "failed"), ("loading", "taken still loading")):
        found: list[int] = result.get(key) or []
        if found:
            parts.append(f"{len(found)} {what}: {_numbers(found)}")
    return "; ".join(parts)


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, EDITS)
    def capture_sweep(
        shots: Annotated[
            list[Shot] | None,
            Field(max_length=MAX_SHOTS, description="The shots, in order, up to 2,000; give this or shots_file"),
        ] = None,
        shots_file: Annotated[
            str,
            Field(
                description="A JSON file on this server's machine holding a list of shots, or a sweep's "
                "manifest.json to take its shots again; give this or shots"
            ),
        ] = "",
        width: Annotated[int, Field(ge=1, description="Every picture's width in pixels, up to 4096")] = 1280,
        height: Annotated[int, Field(ge=1, description="Every picture's height in pixels, up to 4096")] = 720,
        name: Annotated[
            str,
            Field(
                description="The sweep's folder in mcp_output/sweeps/: letters, digits, '.', '_', '-' and spaces; "
                "the time when empty. A folder that holds a sweep already is refused"
            ),
        ] = "",
    ) -> str:
        """Capture many shots in one call, each with its own camera pose, lens, variant selections and timeline time,
        as a job: for checking a scene's looks and switches from many viewpoints, where one capture_viewport a picture
        costs a turn each. Answers the job's id and folder at once.

        A shot is a position with yaw and pitch (yaw about the up axis, 0 along +X; pitch -90 looks straight down), a
        position with a target, or camera_path, a camera of the stage rendered as it is. Its lens is focal_length and
        the apertures in mm, the vertical one fitted to the image when left out; one that doesn't fit the image's
        shape is refused. selections switch variant sets for the shot alone, in the session layer, which no save
        writes; time sets the timeline. Every shot is checked before anything changes.

        Kit writes each shot's PNG and a manifest.json, each shot's pose, lens, selections, time and file, into
        mcp_output/sweeps/<name>/. Read it with get_job(id, wait=100): shot 37 of 400 as it goes, then one line naming
        the folder and the shots that came out black or failed. A sweep's manifest.json given as shots_file takes the
        same shots again, on this scene after a change or on another built from the same spec. Afterwards every
        layer, the timeline and the selections are as they were, after cancel_job too, which keeps the shots taken. A
        time repeats time-sampled animation; Replicator's walking agents move on each update whatever the time, so
        stop the timeline (sim_control) for shots of them that repeat. One size for all the shots; one job runs at a
        time.
        """
        if (shots is None) == (not shots_file.strip()):
            raise ToolError("Give the shots as shots or as shots_file, one of them")
        if shots is not None:
            sent: object = [shot.model_dump(exclude_none=True) for shot in shots]
        else:
            sent = _read_shots_file(shots_file.strip())
        folder_name = name.strip() or time.strftime("%Y%m%d-%H%M%S")
        root = str(Path(h.output_dir) / "sweeps")
        resp = bridge_call(client.job_sweep, sent, root, folder_name, width, height)
        r = resp["result"]
        return (
            f"Sweep {r['id']} started: {r['shots']} shots at {r['width']}x{r['height']} -> {h.rel(r['folder'])}/\n"
            f'Read it with get_job("{r["id"]}", wait=100); cancel_job("{r["id"]}") stops it and keeps the shots taken.'
        )
