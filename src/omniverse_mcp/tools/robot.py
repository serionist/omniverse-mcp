"""Robot tools."""

from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS
from ._bridge import bridge_call
from ._params import Position, Rotation

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

RobotRoot = Annotated[str, Field(description='The robot\'s root prim, e.g. "/World/G1"')]


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=EDITS)
    def create_robot(
        robot_type: Annotated[str, Field(description="A robot's name (franka, g1, spot, ...) or a USD file's path")],
        prim_path: Annotated[str, Field(description="Where to put it; made up from the name when empty")] = "",
        position: Position = None,
        rotation: Rotation = None,
    ) -> str:
        """Spawn a robot from Isaac Sim's asset library.

        Available: franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal. Or a USD file as robot_type: a path
        on the Kit app's machine, a URL, or a path in Isaac Sim's asset library (/Isaac/...). Without prim_path,
        the prim is named after the file.
        """
        resp = bridge_call(client.create_robot, robot_type, prim_path, position, rotation)
        r = resp["result"]
        parts = [f"Robot '{r['robot_type']}' created at {r['prim_path']}"]
        parts.append(f"USD: {r['usd_path']}")
        if r.get("joints"):
            parts.append(f"Joints: {len(r['joints'])}")
            for j in r["joints"][:10]:
                parts.append(f"  {j['path']} ({j['type']})")
            if len(r["joints"]) > 10:
                parts.append(f"  ... and {len(r['joints']) - 10} more")
        return "\n".join(parts)

    @mcp.tool(annotations=READS)
    def get_robot_info(prim_path: RobotRoot) -> str:
        """Get robot joint info: names, types, limits, DOF count. Pure USD, no sim needed."""
        resp = bridge_call(client.get_robot_info, prim_path)
        r = resp["result"]
        lines = [
            f"Robot: {r['prim_path']}",
            f"Articulation: {r['is_articulation']}",
            f"DOF: {r['dof_count']}",
            f"Links: {r['link_count']}",
            f"Joints ({len(r['joints'])}):",
        ]
        for j in r["joints"]:
            limits = ""
            if j.get("lower_limit") is not None and j.get("upper_limit") is not None:
                limits = f" [{j['lower_limit']:.1f}, {j['upper_limit']:.1f}]"
            drive = ""
            drive_angular = j.get("drive_angular")
            drive_linear = j.get("drive_linear")
            if drive_angular:
                drive = " drive=angular"
            elif drive_linear:
                drive = " drive=linear"
            lines.append(f"  {j['name']} ({j['type']}{limits}{drive})")
        text = "\n".join(lines)
        return h.text_response(text, "robot_info")

    @mcp.tool(annotations=READS)
    def get_joint_states(prim_path: RobotRoot) -> str:
        """Get current joint positions and velocities. Requires sim to have been played at least once."""
        resp = bridge_call(client.get_joint_states, prim_path)
        r = resp["result"]
        lines = [f"Joint states for {r['prim_path']} ({r['dof_count']} DOF):"]
        names = r.get("names", [])
        positions = r.get("positions", [])
        velocities = r.get("velocities", [])
        for i in range(len(positions)):
            name = names[i] if i < len(names) else f"joint_{i}"
            pos = positions[i]
            vel = velocities[i] if i < len(velocities) else 0.0
            lines.append(f"  {name}: pos={pos:.4f} vel={vel:.4f}")
        text = "\n".join(lines)
        return h.text_response(text, "joint_states")

    @mcp.tool(annotations=EDITS)
    def set_joint_targets(
        prim_path: RobotRoot,
        targets: Annotated[
            dict[str, float] | list[float] | None,
            Field(
                description=(
                    "{joint_name: value} or [v0, v1, ...] in joint order: degrees for revolute joints, metres for "
                    "prismatic ones"
                )
            ),
        ] = None,
    ) -> str:
        """Set joint drive position targets. Works without articulation initialisation."""
        resp = bridge_call(client.set_joint_targets, prim_path, targets)
        r = resp["result"]
        lines = [f"Set {r['targets_set']} joint targets on {r['prim_path']}"]
        if r.get("failed"):
            lines.append(f"Failed: {r['failed']}")
        return "\n".join(lines)
