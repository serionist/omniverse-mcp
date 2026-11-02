"""A prim made a collider, or its collision turned off, for set_physics_properties' `collision` (#150): which prims
PhysX can make a shape for, the rigid body a collider moves with, a moving Mesh's approximation, and the answer's
echo. Kit-free, as the rest of ovmcp.core."""

from typing import Any

from pxr import Usd, UsdGeom, UsdPhysics

from .deletion import instance_of
from .usd import has_api, is_a

# The gprims PhysX makes a collision shape for. usd-core counts curves and TetMesh as gprims too, which it doesn't.
COLLIDING: tuple[type, ...] = (
    UsdGeom.Cube,
    UsdGeom.Sphere,
    UsdGeom.Capsule,
    UsdGeom.Cylinder,
    UsdGeom.Cone,
    UsdGeom.Mesh,
    UsdGeom.Plane,
)
COLLIDING_NAMES = "Cube, Sphere, Capsule, Cylinder, Cone, Mesh and Plane"
# The prims under a refused one that its error names, so the next calls can take them one by one.
NAMED = 5


def collides(prim: Usd.Prim) -> bool:
    """Whether PhysX makes a shape for prim when it has the Collision API."""
    return any(is_a(prim, schema) for schema in COLLIDING)


def collision_refusal(prim: Usd.Prim) -> str | None:
    """Why prim can't be made a collider, or have its collision turned off, or None. Checked before anything is
    written, so the other values of the call aren't written either."""
    path = prim.GetPath()
    if not prim.IsActive():
        return f"{path} is inactive, so PhysX makes no shape for it: activate it first"
    if prim.IsInstanceProxy():
        instance = instance_of(prim)
        return (
            f"{path} is inside the instance {instance.GetPath()}, whose prims can't be changed one by one: its "
            "colliders belong in the asset the instance references, or the instance needs instanceable turned off"
        )
    if collides(prim):
        return None
    kind = prim.GetTypeName() or "typeless prim"
    # "an Xform", "a BasisCurves": the article as the type name is said.
    kind = f"{'an' if kind[:1] in 'AEIOUX' else 'a'} {kind}"
    shapes = [p for p in Usd.PrimRange(prim) if p != prim and collides(p)]
    if shapes:
        named = ", ".join(str(p.GetPath()) for p in shapes[:NAMED])
        more = f", of {len(shapes)} in all" if len(shapes) > NAMED else ""
        return (
            f"{path} is {kind}, which PhysX makes no shape for: only a {COLLIDING_NAMES} collide. Make the shapes "
            f"under it colliders one by one: {named}{more}"
        )
    inside = [p for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()) if p.IsInstanceProxy() and collides(p)]
    if inside:
        instance = instance_of(inside[0])
        return (
            f"{path} is {kind}, which PhysX makes no shape for: only a {COLLIDING_NAMES} collide. The shapes under "
            f"it lie inside the instance {instance.GetPath()}, whose prims can't be changed one by one: their "
            "colliders belong in the asset it references, or the instance needs instanceable turned off"
        )
    return (
        f"{path} is {kind}, which PhysX makes no shape for: only a {COLLIDING_NAMES} collide, and none lies under it"
    )


def rigid_body_of(prim: Usd.Prim) -> Usd.Prim | None:
    """The rigid body prim moves with as a collider: itself, or its nearest ancestor with RigidBodyAPI."""
    current = prim
    while current and current.IsValid() and not current.IsPseudoRoot():
        if has_api(current, UsdPhysics.RigidBodyAPI):
            return current
        current = current.GetParent()
    return None


def _kinematic(body: Usd.Prim) -> bool:
    return bool(UsdPhysics.RigidBodyAPI(body).GetKinematicEnabledAttr().Get())


def needs_hull(prim: Usd.Prim, body: Usd.Prim | None) -> bool:
    """Whether prim, made a collider, should get a convex hull: a Mesh moving with a body that isn't kinematic, whose
    approximation no one has authored. PhysX can't simulate a triangle mesh on a moving body, and falls back to a hull
    with a warning; on a kinematic body it keeps triangles."""
    if body is None or not is_a(prim, UsdGeom.Mesh) or _kinematic(body):
        return False
    authored = prim.GetAttribute("physics:approximation")
    return not (authored and authored.HasAuthoredValue())


def set_collision(prim: Usd.Prim, on: bool) -> dict[str, Any]:
    """Make prim a collider (on) or turn its collision off, after collision_refusal let it through. The echo: the APIs
    applied; `collision`, the composed physics:collisionEnabled read back, so a stronger layer's opinion shows as it
    stands; `collider` False when off met a prim without the Collision API; `approximation` when one was authored;
    `body` when prim moves with a rigid body."""
    applied: list[str] = []
    echo: dict[str, Any] = {}
    body = rigid_body_of(prim)
    if on:
        if not has_api(prim, UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(prim)
            applied.append("CollisionAPI")
        enabled = UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr()
        # Its fallback is true: only an authored false needs writing over.
        if enabled.Get() is False:
            enabled.Set(True)
        if needs_hull(prim, body):
            if not has_api(prim, UsdPhysics.MeshCollisionAPI):
                UsdPhysics.MeshCollisionAPI.Apply(prim)
                applied.append("MeshCollisionAPI")
            UsdPhysics.MeshCollisionAPI(prim).CreateApproximationAttr().Set(UsdPhysics.Tokens.convexHull)
            echo["approximation"] = str(UsdPhysics.Tokens.convexHull)
    elif has_api(prim, UsdPhysics.CollisionAPI):
        UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
    else:
        echo["collider"] = False
    if has_api(prim, UsdPhysics.CollisionAPI):
        echo["collision"] = bool(UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get())
    else:
        echo["collision"] = False
    if body is not None:
        echo["body"] = str(body.GetPath())
    echo["applied"] = applied
    return echo
