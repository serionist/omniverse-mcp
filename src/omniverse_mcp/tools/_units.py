"""The lines create_robot and create_prim print for a file the Kit extension brought to the stage's up axis and
units: the turn (#105), the scale and the converted values (#112)."""

from typing import Any


def turned_line(turn: dict[str, Any]) -> str:
    """The line for a robot create_robot stood upright: the turn this call added, and the op's value after it, which
    differ when the file's root held the op already (#105). Both are named, so the op read back matches the answer."""
    degrees, value = float(turn["degrees"]), float(turn["op"])
    op = turn.get("op_name", "xformOp:rotateX:unitsResolve")
    added = "went into" if degrees == value else "added to"
    return (
        f"Turned upright: the file is {turn['file']}-up and the stage {turn['stage']}-up, so {degrees:+g}° about X "
        f"{added} {op}, which now reads {value:g}, as Kit's metrics assembler turns a dropped file"
    )


def scaled_lines(units: dict[str, Any]) -> list[str]:
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
    # Without the PhysX schema's table only the cameras' two distances convert, by Kit's camera rules.
    table = units.get("table") is not False
    kinds = "masses, inertia, drives, limits, camera distances" if table else "camera distances"
    rules = "physics" if table else "camera"
    lines = [
        f"{line}; {units.get('converted', 0)} values ({kinds}) were converted to the stage's units, as Kit's metrics "
        f"assembler converts them with its {rules} rules"
    ]
    if units.get("left_count"):
        left: list[str] = units.get("left") or []
        more = units["left_count"] - len(left)
        lines.append(
            f"{units['left_count']} values stay in the file's units: inside instances, which USD lets no one "
            "override, animated by value clips or splines, or of a type that doesn't multiply: "
            f"{', '.join(left)}" + (f", and {more} more" if more > 0 else "")
        )
    if units.get("table") is False:
        lines.append(
            "This Kit app has no PhysX schema to read units from, so the robot's physics values stay in the file's "
            "units"
        )
    return lines
