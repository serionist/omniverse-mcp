"""apply_force's request, checked, whether PhysX can push the body, and the point it pushes at. No Kit.

The handler reads the facts from Kit and PhysX and passes them in, so the decisions here are unit-tested without it.
"""

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

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


def refusal(prim_path: str, *, stopped: bool, kinematic: bool, held: bool) -> str | None:
    """Why PhysX won't move the body, or None when it will. A stopped timeline first: PhysX holds no bodies then, so
    the other two say nothing."""
    if stopped:
        return (
            "The simulation is stopped, so PhysX holds no bodies to push: play it first with sim_control('play'); "
            "paused works too"
        )
    if kinematic:
        return (
            f"{prim_path} is kinematic (physics:kinematicEnabled is true): PhysX takes a force on it and moves it "
            "only by its transform"
        )
    if not held:
        return f"PhysX holds no rigid body at {prim_path}; get_logs(min_level='warn') may say why"
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
