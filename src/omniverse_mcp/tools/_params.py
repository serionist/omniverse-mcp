"""Parameter types several tools share: each a type with its description, as the client sees it in the schema."""

from typing import Annotated

from pydantic import Field

PrimPath = Annotated[str, Field(description='Full USD path of the prim, e.g. "/World/Robot"')]
Position = Annotated[
    list[float] | None,
    Field(description="[x, y, z] relative to the parent prim, in the stage's units (get_sim_state's meters_per_unit)"),
]
Rotation = Annotated[
    list[float] | None, Field(description="Euler angles [rx, ry, rz] in degrees, or a quaternion [w, x, y, z]")
]
Scale = Annotated[list[float] | float | None, Field(description="A uniform scale, or [sx, sy, sz]")]
