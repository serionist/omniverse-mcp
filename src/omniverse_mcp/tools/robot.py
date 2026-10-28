"""Robot tools."""

from ._bridge import bridge_call


def register(mcp, client, h):
    @mcp.tool()
    def create_robot(
        robot_type: str,
        prim_path: str = "",
        position: list[float] | None = None,
        rotation: list[float] | None = None,
    ) -> str:
        """Spawn a robot from Isaac Sim's asset library.

        Available: franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal.
        Or provide a full USD path as robot_type.

        Args:
            robot_type: Robot name or USD path
            prim_path: Scene path (auto-generated if empty)
            position: [x, y, z] spawn position
            rotation: Euler or quaternion
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

    @mcp.tool()
    def get_robot_info(prim_path: str) -> str:
        """Get robot joint info: names, types, limits, DOF count. Pure USD, no sim needed.

        Args:
            prim_path: Root prim of the robot (e.g., "/World/G1")
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

    @mcp.tool()
    def get_joint_states(prim_path: str) -> str:
        """Get current joint positions and velocities. Requires sim to have been played at least once.

        Args:
            prim_path: Root prim of the robot
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

    @mcp.tool()
    def set_joint_targets(
        prim_path: str,
        targets: dict[str, float] | list[float] | None = None,
    ) -> str:
        """Set joint drive position targets. Works without articulation initialization.

        Args:
            prim_path: Root prim of the robot
            targets: Joint targets as {joint_name: value} dict or [v0, v1, ...] list.
                     Values in degrees for revolute, meters for prismatic joints.
        """
        resp = bridge_call(client.set_joint_targets, prim_path, targets)
        r = resp["result"]
        lines = [f"Set {r['targets_set']} joint targets on {r['prim_path']}"]
        if r.get("failed"):
            lines.append(f"Failed: {r['failed']}")
        return "\n".join(lines)
