"""Robot tools."""

from typing import TYPE_CHECKING, Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS, tool
from ._bridge import bridge_answer, bridge_call
from ._params import Position, Rotation
from ._units import units_lines

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


# What a joint state line's numbers are in, said once above the lines (#199).
JOINT_UNITS = (
    "from physics: radians or stage units, per second for velocities, kp and kd per radian or unit as "
    "set_joint_drives takes; set_joint_targets takes degrees"
)
# PhysX's "no limit": infinite, or float32's largest, for a continuous joint's limits or a drive with no maxForce.
UNLIMITED = 1e30


def _value(v: float | None, places: int = 4) -> str:
    """A joint state's number, `unlimited` past UNLIMITED in magnitude, `none` where there is none."""
    if v is None:
        return "none"
    if abs(v) >= UNLIMITED:
        return "unlimited"
    return f"{v:.{places}f}"


def joint_state_lines(r: dict[str, Any]) -> list[tuple[str, str]]:
    """Each degree of freedom of /robot/joint_states' answer as (name, its values): position and velocity, and, from an
    extension with #199, its target, tracking error, limits, stiffness, damping and force limit."""
    names: list[str] = r.get("names", [])
    positions: list[float] = r.get("positions", [])
    velocities: list[float] = r.get("velocities", [])
    lines: list[tuple[str, str]] = []
    for i, pos in enumerate(positions):
        name = names[i] if i < len(names) else f"joint_{i}"
        vel = velocities[i] if i < len(velocities) else 0.0
        parts = [f"pos {pos:.4f}", f"vel {vel:.4f}"]
        if "targets" in r:
            limits = f"[{_value(r['lower_limits'][i])}, {_value(r['upper_limits'][i])}]"
            parts += [
                f"target {_value(r['targets'][i])}",
                f"tracking_error {_value(r['tracking_errors'][i])}",
                f"limits {limits}",
                f"kp {_value(r['stiffnesses'][i], 1)}",
                f"kd {_value(r['dampings'][i], 1)}",
                f"max_force {_value(r['max_forces'][i], 1)}",
            ]
        lines.append((name, ", ".join(parts)))
    return lines


_DriveValue = Annotated[float, Field(ge=0, allow_inf_nan=False)] | None


class DriveValues(BaseModel):
    """One joint's drive for set_joint_drives, any of its three values, in get_robot_info's joint state units."""

    model_config = ConfigDict(extra="forbid")

    stiffness: _DriveValue = None
    damping: _DriveValue = None
    max_force: _DriveValue = None


def _drive_lines(r: dict[str, Any]) -> list[str]:
    """/robot/joint_drives' answer: per joint, what went to USD and what physics drives with after it."""
    written: dict[str, Any] = r.get("written") or {}
    lines = [f"Set the drives of {len(written)} joints on {r['prim_path']}"]
    held: dict[str, Any] = r.get("in_simulation") or {}
    for name, w in written.items():
        usd = ", ".join(f"{key} {value:.6g}" for key, value in w["usd"].items())
        per = "per degree" if w["kind"] == "angular" else "per stage unit"
        line = f"  {name}: USD {usd} ({w['kind']} drive, gains {per})"
        physics = held.get(name)
        if physics is None:
            pass
        elif "none" in physics:
            line += f"; in the simulation: none ({physics['none']})"
        else:
            line += "; in the simulation: " + ", ".join(
                f"{key} {_value(physics[key], 1)}" for key in ("stiffness", "damping", "max_force")
            )
        lines.append(line)
    if r.get("through_view"):
        lines.append("note = physics didn't take the USD write, so the drives were also set through the view")
    if r.get("in_simulation_note"):
        lines.append(f"note = {r['in_simulation_note']}")
    not_written: dict[str, str] = r.get("not_written") or {}
    for name, why in not_written.items():
        lines.append(f"  {name}: not written: {why}")
    return lines


def _joint_states(resp: dict[str, Any]) -> list[str]:
    """/robot/joint_states' answer as lines: a header naming the units, then each degree of freedom's values; or one
    line with the route's error, such as a stopped simulation's."""
    if resp.get("status") == "error":
        return [f"Joint states: not read: {resp.get('error', 'the bridge reported an error')}"]
    r: dict[str, Any] = resp.get("result") or {}
    lines = [f"Joint states ({r.get('dof_count', len(r.get('positions', [])))} DOF, {JOINT_UNITS}):"]
    lines += [f"  {name}: {values}" for name, values in joint_state_lines(r)]
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
        parts.extend(units_lines(r, "the robot's"))
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
        name, type, limits and drive; from physics, while the simulation plays or is paused, each joint's position,
        velocity, target, tracking error (target minus position, `none` where no position drive acts), limits,
        stiffness (kp), damping (kd) and force limit, as PhysX drives with them.

        Use it before driving a robot, to see where its joints are now, and to tune a drive: read the tracking error,
        change kp or kd with set_joint_drives, step, read again. The Joints list's limits are as USD holds them:
        degrees for revolute joints, stage units for prismatic ones. Joint states are in radians for revolute joints
        and stage units for prismatic ones, velocities per second, kp per radian or per stage unit, the units
        set_joint_drives takes; set_joint_targets takes degrees. `unlimited` is a limit or force PhysX doesn't cap. The
        Joints list comes in the
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

    @tool(mcp, EDITS)
    def set_joint_drives(
        prim_path: RobotRoot,
        drives: Annotated[
            dict[str, DriveValues],
            Field(
                min_length=1,
                description="{joint_name: {stiffness, damping, max_force}}, any of the three, in get_robot_info's "
                "joint state units: kp and kd per radian for revolute joints, per stage unit for prismatic ones",
            ),
        ],
    ) -> str:
        """Set the stiffness, damping and force limit of a robot's joint drives, and read back what the simulation
        drives with.

        Values are in the units get_robot_info's joint states give, so a kp read there can be written back changed;
        the answer also gives what was written to USD, which holds an angular drive's gains per degree. A max_force of
        1e30 or more means no limit, which get_robot_info reads as `unlimited`. It writes USD, so it works stopped too,
        and the next play takes it; while the simulation plays or is paused, it reads the drives back from physics
        after one update, and where physics didn't take the USD write it sets them through Isaac Sim's articulation
        view and says so. A joint with no drive isn't written: set_joint_targets gives it one. Use it to tune a drive:
        read the tracking error with get_robot_info, change kp or kd, step with sim_control, read again.
        """
        asked = {name: values.model_dump(exclude_none=True) for name, values in drives.items()}
        # A value JSON can't carry, NaN or infinity, arrives as null, so a joint given only that has none left.
        empty = [name for name, values in asked.items() if not values]
        if empty:
            raise ToolError(f"Give each joint any of stiffness, damping, max_force, finite and 0 or more: {empty}")
        r = bridge_call(client.set_joint_drives, prim_path, asked)["result"]
        return "\n".join(_drive_lines(r))
