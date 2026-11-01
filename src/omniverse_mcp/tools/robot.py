"""Robot tools."""

from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS, tool
from ._bridge import bridge_answer, bridge_call
from ._params import Position, Rotation

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

RobotRoot = Annotated[str, Field(description='The robot\'s root prim, e.g. "/World/G1"')]


def _joint_line(j: dict[str, Any]) -> str:
    """One joint of /robot/info's answer: its name, type, limits and drive."""
    limits = ""
    if j.get("lower_limit") is not None and j.get("upper_limit") is not None:
        limits = f" [{j['lower_limit']:.1f}, {j['upper_limit']:.1f}]"
    drive = ""
    if j.get("drive_angular"):
        drive = " drive=angular"
    elif j.get("drive_linear"):
        drive = " drive=linear"
    return f"  {j['name']} ({j['type']}{limits}{drive})"


def _joint_states(resp: dict[str, Any]) -> list[str]:
    """/robot/joint_states' answer as lines: a header naming the units, then each degree of freedom's position and
    velocity; or one line with the route's error, such as a stopped simulation's."""
    if resp.get("status") == "error":
        return [f"Joint states: not read: {resp.get('error', 'the bridge reported an error')}"]
    r: dict[str, Any] = resp.get("result") or {}
    names: list[str] = r.get("names", [])
    positions: list[float] = r.get("positions", [])
    velocities: list[float] = r.get("velocities", [])
    lines = [
        f"Joint states ({r.get('dof_count', len(positions))} DOF, from physics: radians for revolute joints, stage "
        "units for prismatic ones, velocities per second; set_joint_targets takes degrees):"
    ]
    for i, pos in enumerate(positions):
        name = names[i] if i < len(names) else f"joint_{i}"
        vel = velocities[i] if i < len(velocities) else 0.0
        lines.append(f"  {name}: pos={pos:.4f} vel={vel:.4f}")
    return lines


def _turned_line(turn: dict[str, Any]) -> str:
    """The line for a robot create_robot stood upright: the turn this call added, and the op's value after it, which
    differ when the file's root held the op already (#105). Both are named, so the op read back matches the answer."""
    degrees, value = float(turn["degrees"]), float(turn["op"])
    op = turn.get("op_name", "xformOp:rotateX:unitsResolve")
    added = "went into" if degrees == value else "added to"
    return (
        f"Turned upright: the file is {turn['file']}-up and the stage {turn['stage']}-up, so {degrees:+g}° about X "
        f"{added} {op}, which now reads {value:g}, as Kit's metrics assembler turns a dropped file"
    )


def _scaled_lines(units: dict[str, Any]) -> list[str]:
    """The lines for a robot create_robot brought to the stage's units (#112): the units that differ, the factor added
    and the op's value after, which differ when the file's root held the op, as #105's turned line names both; what
    was converted, and what stays in the file's units."""
    said = [
        f"{name} is {float(pair['file']):g} and the stage's {float(pair['stage']):g}"
        for name, pair in (
            ("metersPerUnit", units.get("meters_per_unit")),
            ("kilogramsPerUnit", units.get("kilograms_per_unit")),
        )
        if pair
    ]
    line = "the file's " + ", and its ".join(said)
    if units.get("op") is not None:
        factor, op = float(units["factor"]), [float(v) for v in units["op"]]
        name = units.get("op_name", "xformOp:scale:unitsResolve")
        added = "went into" if op == [factor] * 3 else "was multiplied into"
        reads = f"{op[0]:g}" if op[1:] == op[:-1] else "(" + ", ".join(f"{v:g}" for v in op) + ")"
        line = f"Scaled to the stage's units: {line}, so a factor of {factor:g} {added} {name}, which now reads {reads}"
    else:
        line = f"Converted to the stage's units: {line}"
    lines = [
        f"{line}; {units.get('converted', 0)} values (masses, inertia, drives, limits, camera distances) were "
        "converted to the stage's units, as Kit's metrics assembler converts them with its physics rules"
    ]
    if units.get("left_count"):
        left: list[str] = units.get("left") or []
        more = units["left_count"] - len(left)
        lines.append(
            f"{units['left_count']} values stay in the file's units, inside instances, which USD lets no one override, "
            f"or animated by value clips: {', '.join(left)}" + (f", and {more} more" if more > 0 else "")
        )
    if units.get("table") is False:
        lines.append(
            "This Kit app has no PhysX schema to read units from, so the robot's physics values stay in the file's "
            "units"
        )
    return lines


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
        A prim already at prim_path, or a file that can't be opened, is an error. A file whose upAxis isn't the
        stage's is stood upright on it, as Kit stands a dropped file, and the answer says so: Isaac Sim's robots are
        Z-up, so each is turned on a Y-up stage. A file that authors no upAxis is left as it is. A file whose
        metersPerUnit or kilogramsPerUnit isn't the stage's is brought to the stage's units, as Kit's metrics
        assembler brings a dropped file with its physics rules: scaled, its physics values converted, and the answer
        says so; one that authors neither is left as it is. position and rotation stay in the stage's frame. For
        anything but a robot, use create_prim; get_robot_info then lists the robot's joints.
        """
        resp = bridge_call(client.create_robot, robot_type, prim_path, position, rotation)
        r = resp["result"]
        parts = [f"Robot '{r['robot_type']}' created at {r['prim_path']}"]
        parts.append(f"USD: {r['usd_path']}")
        if turn := r.get("up_axis_turn"):
            parts.append(_turned_line(turn))
        if units := r.get("units_scale"):
            parts.extend(_scaled_lines(units))
        if r.get("joints"):
            parts.append(f"Joints: {len(r['joints'])}")
            for j in r["joints"][:10]:
                parts.append(f"  {j['path']} ({j['type']})")
            if len(r["joints"]) > 10:
                parts.append(f"  ... and {len(r['joints']) - 10} more")
        return "\n".join(parts)

    @tool(mcp, READS)
    def get_robot_info(prim_path: RobotRoot) -> str:
        """Read a robot: from USD, at any time, whether it is an articulation, its link and DOF counts, and each joint's
        name, type, limits and drive; from physics, while the simulation plays or is paused, each joint's position and
        velocity.

        Use it before driving a robot, and to see where its joints are now. Limits are as USD holds them: degrees for
        revolute joints, stage units for prismatic ones. Joint states are in radians for revolute joints and stage
        units for prismatic ones, velocities per second; set_joint_targets takes degrees. The Joints list comes in the
        order a list of set_joint_targets follows, fixed joints included, and the DOF count leaves fixed joints out;
        the joint states come in physics' own order of degrees of freedom. Stopped, or in a Kit app without Isaac Sim,
        the answer gives the structure and a line saying why there are no joint states. prim_path is the robot's root:
        the joint states are the first articulation's at or under it. An answer too long to give inline keeps the
        counts, and the joint states where they fit, and writes the Joints list to a file, its path in the answer.
        """
        r = bridge_call(client.get_robot_info, prim_path)["result"]
        header = [
            f"Robot: {r['prim_path']}",
            f"Articulation: {r['is_articulation']}",
            f"DOF: {r['dof_count']}",
            f"Links: {r['link_count']}",
        ]
        joints = [f"Joints ({len(r['joints'])}):", *(_joint_line(j) for j in r["joints"])]
        # Asked every call: the structure needs no physics, and a reason there are no joint states is part of the
        # answer, not a failure of it. Only a Kit that can't be reached fails the call.
        states = _joint_states(bridge_answer(client.get_joint_states, prim_path))
        whole = "\n".join(header + joints + states)
        if h.fits(whole):
            return whole
        # Too long: the header and the joint states, what a caller came for, stay inline where they fit, and the
        # Joints list goes to a file, with the joint states after it when they don't.
        if h.fits("\n".join(header + states)):
            wrote = h.write_response("\n".join(joints), "robot_info", f"the {len(r['joints'])} joints")
            return "\n".join([*header, wrote, *states])
        wrote = h.write_response(
            "\n".join(joints + states), "robot_info", f"the {len(r['joints'])} joints, then the joint states"
        )
        return "\n".join([*header, wrote])

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

        A dict sets the joints it names and skips names it doesn't find; a list follows the order of get_robot_info's
        Joints list, not of its joint states. A joint without a drive gets one, with stiffness 1000 and damping 100. It
        writes USD, so it works stopped too, before physics has started. The answer counts the targets set;
        get_robot_info then reads where the joints are, in radians, while the simulation plays or is paused.
        """
        resp = bridge_call(client.set_joint_targets, prim_path, targets)
        r = resp["result"]
        lines = [f"Set {r['targets_set']} joint targets on {r['prim_path']}"]
        if r.get("failed"):
            lines.append(f"Failed: {r['failed']}")
        return "\n".join(lines)
