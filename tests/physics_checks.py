"""The live suites' physics checks, shared by the scenarios (phase 15) and the GPU module (#68): a mixin of the
helpers that build a body or an articulation in Kit and measure what a push did to it.

Every method runs against `self.c`, the BridgeClient of the class that inherits this one.
"""

import math
import time
import unittest

from omniverse_mcp.client import BridgeClient


def _along_up(up: int, value: float, x: float = 0.0) -> list[float]:
    """`value` along the up axis (index `up`), `x` along X, 0 on the third: a point at that height, or a turn about
    the up axis."""
    vector = [x, 0.0, 0.0]
    vector[up] = value
    return vector


def _turn_degrees(q0: list[float], q1: list[float]) -> float:
    """How far a body turned between two unit quaternions, in degrees, whatever their component order."""
    dot = abs(sum(a * b for a, b in zip(q0, q1, strict=True)))
    return math.degrees(2 * math.acos(min(1.0, dot)))


# The bodies' speed along X, from PATHS and FRAMES set before it: played for FRAMES of Kit's updates, then paused, so
# the window is counted in simulation steps whatever the machine's speed (Kit updates unthrottled here). The speed is
# their centre of mass's travel over the simulation time between, from PhysX's poses and mass information. With no
# contact, it changes by a push over the bodies' mass, whatever their joints do.
_SPEED_ALONG_X = """
import omni.kit.app
import omni.timeline
from omni.physx import get_physx_interface, get_physxunittests_interface

timeline = omni.timeline.get_timeline_interface()


def turned(q, v):
    # v turned by the unit quaternion q, in PhysX's order: x, y, z, w.
    x, y, z, w = q
    cx, cy, cz = y * v[2] - z * v[1], z * v[0] - x * v[2], x * v[1] - y * v[0]
    dx, dy, dz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return (v[0] + 2 * (w * cx + dx), v[1] + 2 * (w * cy + dy), v[2] + 2 * (w * cz + dz))


def centre_along_x():
    mass = moment = 0.0
    for path in PATHS:
        info = get_physxunittests_interface().get_mass_information(path)
        pose = get_physx_interface().get_rigidbody_transformation(path)
        mass += info["mass"]
        moment += info["mass"] * (pose["position"][0] + turned(pose["rotation"], info["com"])[0])
    return moment / mass, mass, timeline.get_current_time()


timeline.play()
await omni.kit.app.get_app().next_update_async()
x0, mass, t0 = centre_along_x()
for _ in range(FRAMES):
    await omni.kit.app.get_app().next_update_async()
x1, _, t1 = centre_along_x()
timeline.pause()
await omni.kit.app.get_app().next_update_async()
result = {"speed": (x1 - x0) / (t1 - t0), "mass": mass, "time": t1}
"""

# Plays for FRAMES of Kit's updates, then pauses: a window counted in simulation steps.
_RUN_FRAMES = """
import omni.kit.app
import omni.timeline

omni.timeline.get_timeline_interface().play()
for _ in range(FRAMES + 1):
    await omni.kit.app.get_app().next_update_async()
omni.timeline.get_timeline_interface().pause()
await omni.kit.app.get_app().next_update_async()
result = omni.timeline.get_timeline_interface().get_current_time()
"""


class PhysicsChecks(unittest.TestCase):
    """Helpers for a live test of a force: a body of its own, its pose, its speed, the step."""

    c: BridgeClient

    def _up_axis(self) -> int:
        """The stage's up axis as the bridge reads it now: 1 for Y, 2 for Z. Never assumed: Isaac Sim opens a Z-up
        stage, and 17.2's new_scene leaves a Y-up one to the next run, so a first run and a later one differ (#6)."""
        r = self.c.sim_state()
        self.assertEqual(r["status"], "success", r)
        up = r["result"]["up_axis"]
        self.assertIn(up, ("Y", "Z"))
        return 2 if up == "Z" else 1

    def _force_body(
        self,
        name: str,
        *,
        enabled: bool = True,
        kinematic: bool = False,
        centre_of_mass: list[float] | None = None,
    ) -> str:
        """A 5 kg cube of its own for a force test, with the simulation stopped. Gravity is off, so only the push
        moves it, and it sits away from the scene, so it touches nothing. Deleted after, the simulation stopped
        first."""
        path = f"/World/{name}"
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.addCleanup(self.c.delete_prim, path)
        self.addCleanup(self.c.sim_control, "stop")
        r = self.c.create_prim(path, "Cube", position=_along_up(self._up_axis(), 5, x=-30), scale=[0.3, 0.3, 0.3])
        self.assertEqual(r["status"], "success", r)
        com = "None" if centre_of_mass is None else "Gf.Vec3f({}, {}, {})".format(*centre_of_mass)
        r = self.c.execute(
            "from pxr import PhysxSchema\n"
            f"prim = omni.usd.get_context().get_stage().GetPrimAtPath({path!r})\n"
            "body = UsdPhysics.RigidBodyAPI.Apply(prim)\n"
            f"body.CreateRigidBodyEnabledAttr().Set({enabled})\n"
            f"body.CreateKinematicEnabledAttr().Set({kinematic})\n"
            "UsdPhysics.CollisionAPI.Apply(prim)\n"
            "mass = UsdPhysics.MassAPI.Apply(prim)\n"
            "mass.CreateMassAttr().Set(5.0)\n"
            f"com = {com}\n"
            "if com is not None:\n"
            "    mass.CreateCenterOfMassAttr().Set(com)\n"
            "PhysxSchema.PhysxRigidBodyAPI.Apply(prim).CreateDisableGravityAttr().Set(True)\n"
            "result = 'ok'"
        )
        self.assertEqual(r["status"], "success", r)
        return path

    def _physx_pose(self, path: str) -> dict:
        """PhysX's pose of a rigid body now, and the simulation's time with it: `position`, `rotation` (x, y, z, w)
        and `time` in seconds."""
        r = self.c.execute(
            "import omni.timeline\n"
            "from omni.physx import get_physx_interface\n"
            f"pose = get_physx_interface().get_rigidbody_transformation({path!r})\n"
            "result = {'held': bool(pose['ret_val']), 'position': [float(v) for v in pose.get('position', (0, 0, 0))], "
            "'rotation': [float(v) for v in pose.get('rotation', (0, 0, 0, 1))], "
            "'time': omni.timeline.get_timeline_interface().get_current_time()}"
        )
        self.assertEqual(r["status"], "success", r)
        pose = r["result"]["return_value"]
        self.assertTrue(pose["held"], f"PhysX holds no rigid body at {path}")
        return pose

    def _speed_along_x(self, path: str) -> float:
        """The body's speed along X from PhysX's pose over half a second of simulation, once a push has landed."""
        time.sleep(0.2)
        a = self._physx_pose(path)
        time.sleep(0.5)
        b = self._physx_pose(path)
        self.assertGreater(b["time"], a["time"], "the simulation must play while the speed is measured")
        return (b["position"][0] - a["position"][0]) / (b["time"] - a["time"])

    def _physics_step(self) -> float:
        """The physics scene's step in seconds: 1 / timeStepsPerSecond, 60 unless the scene says otherwise."""
        r = self.c.execute(
            "from pxr import PhysxSchema\n"
            "steps = 60.0\n"
            "for prim in omni.usd.get_context().get_stage().Traverse():\n"
            "    if prim.IsA(UsdPhysics.Scene):\n"
            "        if prim.HasAPI(PhysxSchema.PhysxSceneAPI):\n"
            "            steps = float(PhysxSchema.PhysxSceneAPI(prim).GetTimeStepsPerSecondAttr().Get() or 60.0)\n"
            "        break\n"
            "result = 1.0 / steps"
        )
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _start_physics(self) -> None:
        """Plays, then pauses: physics is loaded and the bodies wait, so a push lands at the next step's start."""
        self.assertEqual(self.c.sim_control("play")["status"], "success")
        self.assertEqual(self.c.sim_control("pause")["status"], "success")

    def _speed_along_x_in_kit(self, paths: list[str], frames: int) -> dict:
        """The bodies' speed along X over `frames` simulation steps, from a pause to a pause (_SPEED_ALONG_X):
        `speed`, their `mass`, and the simulation `time` of the last sample."""
        r = self.c.execute(f"PATHS, FRAMES = {paths!r}, {frames}\n" + _SPEED_ALONG_X)
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _run_frames(self, frames: int) -> None:
        """Plays for `frames` simulation steps, from a pause to a pause."""
        r = self.c.execute(f"FRAMES = {frames}\n" + _RUN_FRAMES)
        self.assertEqual(r["status"], "success", r)

    def _rigid_bodies_under(self, root: str) -> list[str]:
        r = self.c.execute(
            f"root = omni.usd.get_context().get_stage().GetPrimAtPath({root!r})\n"
            "result = [str(p.GetPath()) for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies()) "
            "if p.HasAPI(UsdPhysics.RigidBodyAPI)]"
        )
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _force_pair(self, name: str, *, fixed: bool = False) -> tuple[str, str]:
        """Two 5 kg cubes of their own on a revolute joint about the up axis, an articulation rooted on their Xform,
        with the simulation stopped; with `fixed`, a fixed joint holds the first to the world. Gravity is off and they
        sit away from the scene, so only a push moves them. Deleted after, the simulation stopped first."""
        root = f"/World/{name}"
        first, second = f"{root}/First", f"{root}/Second"
        up = self._up_axis()
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.addCleanup(self.c.delete_prim, root)
        self.addCleanup(self.c.sim_control, "stop")
        r = self.c.execute(
            "from pxr import PhysxSchema\n"
            "stage = omni.usd.get_context().get_stage()\n"
            f"root = UsdGeom.Xform.Define(stage, {root!r})\n"
            f"x, y, z = {_along_up(up, 5, x=-40)!r}\n"
            f"for path, dx in (({first!r}, 0.0), ({second!r}, 0.4)):\n"
            "    cube = UsdGeom.Cube.Define(stage, path)\n"
            "    cube.CreateSizeAttr(0.3)\n"
            "    UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(x + dx, y, z))\n"
            "    UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())\n"
            "    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())\n"
            "    UsdPhysics.MassAPI.Apply(cube.GetPrim()).CreateMassAttr(5.0)\n"
            "    PhysxSchema.PhysxRigidBodyAPI.Apply(cube.GetPrim()).CreateDisableGravityAttr(True)\n"
            f"hinge = UsdPhysics.RevoluteJoint.Define(stage, {root + '/Hinge'!r})\n"
            f"hinge.CreateBody0Rel().SetTargets([Sdf.Path({first!r})])\n"
            f"hinge.CreateBody1Rel().SetTargets([Sdf.Path({second!r})])\n"
            "hinge.CreateLocalPos0Attr(Gf.Vec3f(0.2, 0, 0))\n"
            "hinge.CreateLocalPos1Attr(Gf.Vec3f(-0.2, 0, 0))\n"
            f"hinge.CreateAxisAttr({'XYZ'[up]!r})\n"
            f"if {fixed}:\n"
            # The world's end sits where the first cube does, so the joint holds it there.
            f"    bolt = UsdPhysics.FixedJoint.Define(stage, {root + '/Bolt'!r})\n"
            f"    bolt.CreateBody1Rel().SetTargets([Sdf.Path({first!r})])\n"
            "    bolt.CreateLocalPos0Attr(Gf.Vec3f(x, y, z))\n"
            "UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim())\n"
            "PhysxSchema.PhysxArticulationAPI.Apply(root.GetPrim()).CreateEnabledSelfCollisionsAttr(False)\n"
            "result = 'ok'"
        )
        self.assertEqual(r["status"], "success", r)
        return first, second
