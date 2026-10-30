"""Robot tools."""

from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS, tool
from ._bridge import bridge_call
from ._params import Position, Rotation

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

RobotRoot = Annotated[str, Field(description='The robot\'s root prim, e.g. "/World/G1"')]


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, EDITS)
    def create_robot(
        robot_type: Annotated[str, Field(description="A robot's name (franka, g1, spot, ...) or a USD file's path")],
        prim_path: Annotated[str, Field(description="Where to put it; made up from the name when empty")] = "",
        position: Position = None,
        rotation: Rotation = None,
    ) -> str:
        """Add a robot to the stage as a reference: one of Isaac Sim's asset library by name, or a robot's USD file.

        Names, which need Isaac Sim: franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal. A USD file as
        robot_type is a path on the Kit app's machine, a URL, or a path in Isaac Sim's asset library (/Isaac/...).
        Without prim_path, the prim is named after the robot or the file: /World/Franka, or /World/MyBot for MyBot.usd.
        A prim already at prim_path, or a file that can't be opened, is an error. For anything but a robot, use
        create_prim; get_robot_info then lists the robot's joints.
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

    @tool(mcp, READS)
    def get_robot_info(prim_path: RobotRoot) -> str:
        """Read a robot's structure from USD: whether it is an articulation, its link and DOF counts, and each joint's
        name, type, limits and drive.

        Use it before driving a robot, whatever the simulation's state; get_joint_states reads where the joints are now,
        from physics. Limits are as USD holds them: degrees for revolute joints, stage units for prismatic ones. The
        joints come in the order a list of set_joint_targets follows, fixed joints included; the DOF count leaves fixed
        joints out.
        """
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

    @tool(mcp, READS)
    def get_joint_states(prim_path: RobotRoot) -> str:
        """Get each joint's position and velocity from physics while the simulation plays or is paused; an error while
        it is stopped, which says to play or step first.

        Radians for revolute joints and stage units for prismatic ones, velocities per second (set_joint_targets takes
        degrees). Use it to see where a robot is now; get_robot_info reads names, limits and drives from USD at any
        time. prim_path is the robot's articulation root or a prim above it. Needs Isaac Sim.
        """
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

    @tool(mcp, EDITS)
    def set_joint_targets(
        prim_path: RobotRoot,
        targets: Annotated[
            dict[str, float] | list[float] | None,
            Field(
                description=(
                    "Required: {joint_name: value}, or [v0, v1, ...] in get_robot_info's joint order, fixed joints "
                    "included; degrees for revolute joints, stage units for prismatic ones"
                )
            ),
        ] = None,
    ) -> str:
        """Set the position targets of a robot's joint drives, which physics drives the joints toward while the
        simulation plays.

        A dict sets the joints it names and skips names it doesn't find; a list follows get_robot_info's joint order,
        not get_joint_states'. A joint without a drive gets one, with stiffness 1000 and damping 100. It writes USD, so
        it works stopped too, before physics has started. The answer counts the targets set; get_joint_states then
        reads where the joints are, in radians.
        """
        resp = bridge_call(client.set_joint_targets, prim_path, targets)
        r = resp["result"]
        lines = [f"Set {r['targets_set']} joint targets on {r['prim_path']}"]
        if r.get("failed"):
            lines.append(f"Failed: {r['failed']}")
        return "\n".join(lines)
