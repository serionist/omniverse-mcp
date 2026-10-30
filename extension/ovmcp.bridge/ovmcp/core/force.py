"""apply_force's request, checked, whether PhysX can push the body, and the point it pushes at. No Kit.

The handler reads the facts from Kit and PhysX and passes them in, so the decisions here are unit-tested without it.
What holds a body, an articulation it is a link of or a fixed joint to the world, is read from the stage, which
usd-core gives the tests.
"""

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from pxr import Sdf, Usd, UsdPhysics

from .usd import has_api, is_a

Vec3 = tuple[float, float, float]

# What the answer's `at` says the point is: the one the caller gave, or the body's centre of mass, from PhysX.
AT_GIVEN = "given"
AT_CENTRE_OF_MASS = "centre of mass"


@dataclass(frozen=True)
class ForceArgs:
    prim_path: str
    force: Vec3
    position: Vec3 | None  # world space; None pushes at the centre of mass
    impulse: bool

    @property
    def mode(self) -> str:
        """IPhysxSimulation.apply_force_at_pos's mode: an impulse changes the velocity at once, a force acts for one
        physics step."""
        return "Impulse" if self.impulse else "Force"


def force_args(body: Mapping[str, Any]) -> ForceArgs:
    """apply_force's request body, checked; the ValueError says what is wrong with it."""
    prim_path = body.get("prim_path", "")
    if not isinstance(prim_path, str) or not prim_path:
        raise ValueError("No prim_path provided")
    if body.get("force") is None:
        raise ValueError("force [fx, fy, fz] is required")
    force = _vec3(body["force"], "force")
    position = None if body.get("position") is None else _vec3(body["position"], "position")
    impulse = body.get("impulse", False)
    if not isinstance(impulse, bool):
        raise ValueError(f"impulse must be true or false (got {impulse!r})")
    return ForceArgs(prim_path, force, position, impulse)


def refusal(
    prim_path: str, *, stopped: bool, direct_gpu: bool, enabled: bool, kinematic: bool, held: bool
) -> str | None:
    """Why PhysX won't move the body, or None when it will, as far as the cheap facts tell; `fixed_refusal` asks the
    stage's joints after.

    A stopped timeline first: PhysX holds no bodies then, so the others say nothing. Then PhysX's Direct GPU API,
    under which no push moves any body. Then what the prim says of itself, then whether PhysX holds it.
    """
    if stopped:
        return (
            "The simulation is stopped, so PhysX holds no bodies to push: play it first with sim_control('play'); "
            "paused works too"
        )
    if direct_gpu:
        # Measured on Isaac Sim 6.2 with GPU dynamics and suppressReadback: the push returns and moves nothing. A
        # stage opened after a GPU device can keep the setting on a CPU scene, where a push is unmeasured: refused too,
        # with how to turn the setting off.
        return (
            "PhysX's Direct GPU API is on (/physics/suppressReadback is true), and a push moves nothing under it "
            "(#68). To push bodies, stop the simulation, turn it off with execute_script: "
            "carb.settings.get_settings().set_bool('/physics/suppressReadback', False), and play again"
        )
    if not enabled:
        # PhysX makes such a body a static rigid, as NVIDIA's own rigid body tests count it, and nothing moves one.
        return (
            f"{prim_path}'s rigid body is disabled (physics:rigidBodyEnabled is false): PhysX holds it as a static "
            "body, which no force moves"
        )
    if kinematic:
        return (
            f"{prim_path} is kinematic (physics:kinematicEnabled is true): PhysX takes a force on it and moves it "
            "only by its transform"
        )
    if not held:
        return f"PhysX holds no rigid body at {prim_path}; get_logs(min_level='warn') may say why"
    return None


def fixed_refusal(prim_path: str, fixed_base: str, articulation: str | None) -> str:
    """Why no force moves a body a fixed joint holds: `fixed_base` is the body that joint holds, prim_path itself or
    the one it is welded to (`Joints.held_to_world`). `articulation` names the root of the articulation the body is a
    link of."""
    if fixed_base == prim_path:
        # Measured on Isaac Sim 6.2: the Franka's base takes the push and moves less than 1e-8.
        base = f", as the base of the articulation at {articulation}" if articulation else ""
        return f"{prim_path} is held to the world by a fixed joint{base}: no force moves it"
    within = f", in the articulation at {articulation}" if articulation else ""
    return (
        f"{prim_path} is welded to its fixed base {fixed_base}, which a fixed joint holds to the world{within}: "
        "no force moves it"
    )


class Joints:
    """The stage's joints, read in one traversal, for what holds a body: the articulation it is a link of, and a fixed
    joint that holds it to the world.

    A joint's end is a body's path, or nothing for the world, a static prim or a disabled body, which PhysX holds as
    static (`_body_of`).
    """

    def __init__(self, stage: Usd.Stage) -> None:
        self._stage = stage
        self._neighbours: dict[str, set[str]] = {}
        self._joints_at: dict[str, list[Usd.Prim]] = {}
        # Bodies an enabled fixed joint joins to each other, and those it holds to the world.
        self._welded: dict[str, set[str]] = {}
        self._anchored: set[str] = set()
        for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
            if not is_a(prim, UsdPhysics.Joint):
                continue
            joint = UsdPhysics.Joint(prim)
            ends: list[str] = []
            for rel in (joint.GetBody0Rel(), joint.GetBody1Rel()):
                targets: list[Sdf.Path] = rel.GetTargets()
                # No target holds that end to the world; a target in no body anchors it to a static prim.
                end = _body_of(stage, targets[0]) if targets else None
                if end is not None:
                    ends.append(end)
            for end in ends:
                self._joints_at.setdefault(end, []).append(prim)
            two = len(ends) == 2 and ends[0] != ends[1]
            if two:
                _link(self._neighbours, ends[0], ends[1])
            # A disabled joint holds nothing; an excluded one still holds, outside the articulation's own joints.
            if is_a(prim, UsdPhysics.FixedJoint) and joint.GetJointEnabledAttr().Get() is not False:
                # A kinematic body moves only by its transform, so what it holds no force moves either: ground, as
                # the world is. Only here: it still joins an articulation as the parser reads one.
                movable = [end for end in ends if not _kinematic(stage, end)]
                if len(movable) == 2 and movable[0] != movable[1]:
                    _link(self._welded, movable[0], movable[1])
                elif len(movable) == 1:
                    self._anchored.add(movable[0])

    def articulation_holding(self, body_path: str) -> str | None:
        """The prim whose ArticulationRootAPI makes body_path one of its articulation's links, or None for a body
        PhysX holds on its own.

        Read as UsdPhysics's own parser reads an articulation: every body joined to the root's through joints belongs
        to it, wherever it sits in the hierarchy (the G1's links are its pelvis's siblings, the root on the pelvis),
        and the root may be on one of those bodies, on one of those joints, or on a prim above either (a robot's
        Xform). A joint excluded from articulations still joins, as the parser counts it. An end that is no body
        joins nothing: two things fixed to one wall are not one articulation.
        """
        joined = _reach(self._neighbours, body_path)
        for path in sorted(joined):
            for prim in (self._stage.GetPrimAtPath(path), *self._joints_at.get(path, [])):
                root = _root_at_or_above(prim)
                if root is not None:
                    return root
        return None

    def held_to_world(self, body_path: str) -> str | None:
        """The body an enabled fixed joint holds to the world, when body_path is that body or is welded to it through
        more enabled fixed joints; None when nothing holds it so.

        No force moves such a body: PhysX makes a fixed joint to the world an articulation's fixed base, and holds a
        lone body with it. Its other end is the world, a static prim, a disabled body or a kinematic one. A joint
        excluded from articulations counts too.
        """
        if body_path in self._anchored:
            return body_path
        return next((path for path in sorted(_reach(self._welded, body_path)) if path in self._anchored), None)


def _link(graph: dict[str, set[str]], a: str, b: str) -> None:
    graph.setdefault(a, set()).add(b)
    graph.setdefault(b, set()).add(a)


def _reach(graph: dict[str, set[str]], start: str) -> set[str]:
    """start and every node joined to it through graph's edges."""
    joined, queue = {start}, [start]
    while queue:
        for other in graph.get(queue.pop(), set()):
            if other not in joined:
                joined.add(other)
                queue.append(other)
    return joined


def _body_of(stage: Usd.Stage, path: Sdf.Path) -> str | None:
    """The rigid body a joint's target belongs to: the target, or the nearest prim above it with RigidBodyAPI, as a
    joint may name a body's child. None when none is, a static anchor as UsdPhysics reads it, and None for a disabled
    body, which PhysX holds as static and UsdPhysics's parser reads so."""
    prim = stage.GetPrimAtPath(path)
    while prim.IsValid() and not prim.IsPseudoRoot():
        if has_api(prim, UsdPhysics.RigidBodyAPI):
            if UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get() is False:
                return None
            return str(prim.GetPath())
        prim = prim.GetParent()
    return None


def _kinematic(stage: Usd.Stage, body_path: str) -> bool:
    return UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath(body_path)).GetKinematicEnabledAttr().Get() is True


def _root_at_or_above(prim: Usd.Prim) -> str | None:
    while prim.IsValid() and not prim.IsPseudoRoot():
        if has_api(prim, UsdPhysics.ArticulationRootAPI):
            return str(prim.GetPath())
        prim = prim.GetParent()
    return None


def centre_of_mass(info: Mapping[str, Any], prim_path: str) -> Vec3:
    """The body's centre of mass in its own frame, from PhysX's mass information. A mass of 0 means PhysX has none for
    it, as NVIDIA's own debug view reads it, and so does a missing `com`: both are a ValueError."""
    mass = info.get("mass")
    com = info.get("com")
    if not _is_number(mass) or float(cast("float", mass)) <= 0 or com is None:
        raise ValueError(f"PhysX has no mass for {prim_path}, so no centre of mass to push at: give a position")
    return _vec3(com, "com")


def world_point(position: object, rotation_xyzw: object, local: object) -> Vec3:
    """A point in a body's frame, in world space: turned by the body's rotation, a quaternion in PhysX's x, y, z, w
    order, then moved to its position. The pose is what PhysX's get_rigidbody_transformation reports."""
    px, py, pz = _vec3(position, "position")
    x, y, z, w = _vector(rotation_xyzw, 4, "rotation")
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0:
        raise ValueError("rotation must be a quaternion, not four zeros")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    vx, vy, vz = _vec3(local, "local")
    # v + 2w (u x v) + 2 u x (u x v), with u = (x, y, z): v turned by the unit quaternion.
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    dx, dy, dz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return px + vx + 2 * (w * cx + dx), py + vy + 2 * (w * cy + dy), pz + vz + 2 * (w * cz + dz)


def _vec3(value: object, name: str) -> Vec3:
    x, y, z = _vector(value, 3, name)
    return x, y, z


def _vector(value: object, size: int, name: str) -> list[float]:
    """`size` finite numbers from a list, a tuple or a sequence of Kit's (carb.Float3 iterates); a ValueError
    otherwise."""
    items: list[object] = []
    if not isinstance(value, (str, bytes, Mapping)):
        try:
            items = list(cast("Iterable[object]", value))
        except TypeError:
            items = []
    if len(items) != size or not all(_is_number(v) for v in items):
        raise ValueError(f"{name} must be {size} finite numbers (got {value!r})")
    return [float(cast("float", v)) for v in items]


def _is_number(value: object) -> bool:
    # A bool is an int to Python, never a coordinate; numbers.Real takes numpy's floats too.
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return math.isfinite(float(value))
