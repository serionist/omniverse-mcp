"""apply_force's request, checked, whether PhysX can push the body, and the point it pushes at. No Kit.

The handler reads the facts from Kit and PhysX and passes them in, so the decisions here are unit-tested without it;
whether a body is an articulation's link is read from the stage, which usd-core gives the tests.
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
    prim_path: str, *, stopped: bool, enabled: bool, kinematic: bool, held: bool, articulation: str | None
) -> str | None:
    """Why PhysX won't move the body, or None when it will. A stopped timeline first: PhysX holds no bodies then, so
    the others say nothing. Then what the prim says of itself, then whether PhysX holds it, then whether it is a link
    of the articulation `articulation` names."""
    if stopped:
        return (
            "The simulation is stopped, so PhysX holds no bodies to push: play it first with sim_control('play'); "
            "paused works too"
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
    if articulation is not None:
        # Measured on Isaac Sim 6.2: apply_force_at_pos on the G1's pelvis returns as on any body and moves nothing.
        return (
            f"{prim_path} is a link of the articulation at {articulation}: PhysX's push doesn't reach a robot's links "
            "yet (#58)"
        )
    return None


def articulation_holding(stage: Usd.Stage, body_path: str) -> str | None:
    """The prim whose ArticulationRootAPI makes body_path one of its articulation's links, or None for a body PhysX
    holds on its own.

    Read as UsdPhysics's own parser reads an articulation: every body joined to the root's through joints belongs to
    it, wherever it sits in the hierarchy (the G1's links are its pelvis's siblings, the root on the pelvis), and the
    root may be on one of those bodies, on one of those joints, or on a prim above either (a robot's Xform). A joint
    excluded from articulations still joins, as the parser counts it.
    """
    neighbours: dict[str, set[str]] = {}
    joints_at: dict[str, list[Usd.Prim]] = {}
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if not is_a(prim, UsdPhysics.Joint):
            continue
        joint = UsdPhysics.Joint(prim)
        ends: list[str] = []
        for rel in (joint.GetBody0Rel(), joint.GetBody1Rel()):
            targets: list[Sdf.Path] = rel.GetTargets()
            if targets:  # none: the joint holds that end to the world
                ends.append(_body_of(stage, targets[0]))
        for end in ends:
            joints_at.setdefault(end, []).append(prim)
        if len(ends) == 2 and ends[0] != ends[1]:
            neighbours.setdefault(ends[0], set()).add(ends[1])
            neighbours.setdefault(ends[1], set()).add(ends[0])

    joined, queue = {body_path}, [body_path]
    while queue:
        for other in neighbours.get(queue.pop(), set()):
            if other not in joined:
                joined.add(other)
                queue.append(other)
    for path in sorted(joined):
        for prim in (stage.GetPrimAtPath(path), *joints_at.get(path, [])):
            root = _root_at_or_above(prim)
            if root is not None:
                return root
    return None


def _body_of(stage: Usd.Stage, path: Sdf.Path) -> str:
    """The rigid body a joint's target belongs to: the target, or the nearest prim above it with RigidBodyAPI, as a
    joint may name a body's child. The target itself when none is."""
    prim = stage.GetPrimAtPath(path)
    while prim.IsValid() and not prim.IsPseudoRoot():
        if has_api(prim, UsdPhysics.RigidBodyAPI):
            return str(prim.GetPath())
        prim = prim.GetParent()
    return str(path)


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
