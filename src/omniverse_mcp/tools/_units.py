"""The lines create_robot and create_prim print for a file the Kit extension brought to the stage's up axis and
units: the turn (#105), the scale and the converted values (#112), the frame they were measured against, and what a
prim that was already there didn't get (#119). An older extension sends none of the fields, and nothing is printed."""

from typing import Any


def turned_line(turn: dict[str, Any]) -> str:
    """The line for a file stood upright: the turn this call added, and the op's value after it, which differ when the
    file's root held the op already (#105). Both are named, so the op read back matches the answer. Under a frame of
    its own, the turn is against that frame, and the line says so."""
    degrees, value = float(turn["degrees"]), float(turn["op"])
    op = turn.get("op_name", "xformOp:rotateX:unitsResolve")
    added = "went into" if degrees == value else "added to"
    target = f"the frame it lands in {turn['frame']}-up" if turn.get("frame") else f"the stage {turn['stage']}-up"
    return (
        f"Turned upright: the file is {turn['file']}-up and {target}, so {degrees:+g}° about X {added} {op}, which "
        f"now reads {value:g}, as Kit's metrics assembler turns a dropped file"
    )


def _meters(pair: dict[str, Any], scaled: bool) -> str:
    """The file's metersPerUnit beside what the scale was measured against: the frame's, when there is one, else the
    stage's; and the stage's too when only the values were converted."""
    file, stage, frame = float(pair["file"]), float(pair["stage"]), pair.get("frame")
    if frame is None:
        return f"metersPerUnit is {file:g} and the stage's {stage:g}"
    if scaled:
        return f"metersPerUnit is {file:g} and the frame's {float(frame):g}"
    return f"metersPerUnit is {file:g}, as the frame it lands in, and the stage's {stage:g}"


def scaled_lines(units: dict[str, Any], owner: str = "the robot's") -> list[str]:
    """The lines for a file brought to the stage's units (#112): the units that differ, the factor added and the op's
    value after, which differ when the file's root held the op, as #105's turned line names both; what was converted,
    and what stays in the file's units. Under a frame, the scale clause names the frame and the conversion clause the
    stage, which the values are converted to. owner names whose physics values a Kit app without the PhysX schema
    leaves."""
    scaled = units.get("op") is not None
    meters, kilograms = units.get("meters_per_unit"), units.get("kilograms_per_unit")
    framed = bool(meters and meters.get("frame") is not None)
    said = [_meters(meters, scaled)] if meters else []
    if kilograms:
        said.append(f"kilogramsPerUnit is {float(kilograms['file']):g} and the stage's {float(kilograms['stage']):g}")
    line = "the file's " + ", and its ".join(said)
    if scaled:
        factor, op = float(units["factor"]), [float(v) for v in units["op"]]
        name = units.get("op_name", "xformOp:scale:unitsResolve")
        added = "went into" if op == [factor] * 3 else "was multiplied into"
        reads = f"{op[0]:g}" if op[1:] == op[:-1] else "(" + ", ".join(f"{v:g}" for v in op) + ")"
        target = "the frame it lands in" if framed else "the stage's units"
        line = f"Scaled to {target}: {line}, so a factor of {factor:g} {added} {name}, which now reads {reads}"
    else:
        line = f"Converted to the stage's units: {line}"
    if units.get("converted") is None:
        # Only the frame differs: the file's values are in the stage's units already.
        return [f"{line}; its values are in the stage's units already"]
    # Without the PhysX schema's table only the cameras' two distances convert, by Kit's camera rules.
    table = units.get("table") is not False
    kinds = "masses, inertia, drives, limits, camera distances" if table else "camera distances"
    rules = "physics" if table else "camera"
    stage = f", metersPerUnit {float(meters['stage']):g}" if framed and meters else ""
    lines = [
        f"{line}; {units.get('converted', 0)} values ({kinds}) were converted to the stage's units{stage}, as Kit's "
        f"metrics assembler converts them with its {rules} rules"
    ]
    if units.get("left_count"):
        left: list[str] = units.get("left") or []
        more = units["left_count"] - len(left)
        lines.append(
            f"{units['left_count']} values stay in the file's units: inside instances, which USD lets no one "
            "override, animated by value clips or splines, or of a type that doesn't multiply: "
            f"{', '.join(left)}" + (f", and {more} more" if more > 0 else "")
        )
    if not table:
        lines.append(
            f"This Kit app has no PhysX schema to read units from, so {owner} physics values stay in the file's units"
        )
    return lines


def frame_line(frame: dict[str, Any]) -> str:
    """The line for a file measured against the frame it lands in, which its ancestors' :unitsResolve ops make
    (#119): a file inside an asset already brought to the stage isn't turned or scaled a second time."""
    prims: list[str] = frame.get("prims") or []
    owners = " and ".join(f"{prim}'s" for prim in prims) or "its ancestors'"
    return (
        f"Measured against the frame it lands in, not the stage's: {owners} :unitsResolve ops make it "
        f"{frame['up_axis']}-up, in metersPerUnit {float(frame['meters_per_unit']):g}"
    )


def _said(side: dict[str, Any]) -> str:
    axis, meters = side.get("up_axis"), side.get("meters_per_unit")
    parts = [f"{axis}-up" if axis else "turned so that neither Y nor Z is up"]
    if meters is not None:
        parts.append(f"in metersPerUnit {float(meters):g}")
    return " ".join(parts)


def _left_values(values: dict[str, Any]) -> str:
    said = [
        f"{name} {float(pair['file']):g} where the stage's is {float(pair['stage']):g}"
        for name, pair in (
            ("metersPerUnit", values.get("meters_per_unit")),
            ("kilogramsPerUnit", values.get("kilograms_per_unit")),
        )
        if pair
    ]
    return ", ".join(said)


def not_brought_line(missed: dict[str, Any]) -> str:
    """The line for a reference on a prim that was there before the call, as the file is (#119): what the file's
    content is beside the frame inside the prim, the physics values it leaves in the file's units, and that the
    reference stays there, with how to take it off and have the file brought at a new path, without touching the
    prim's other content."""
    path = missed["prim_path"]
    lacks: list[str] = []
    if missed.get("file") and missed.get("frame"):
        lacks.append(
            f"isn't turned or scaled to the stage (the file {_said(missed['file'])}, the frame inside {path} "
            f"{_said(missed['frame'])})"
        )
    if values := missed.get("values"):
        lacks.append(f"leaves its physics values in the file's units ({_left_values(values)})")
    reference = missed.get("reference")
    remove = (
        f"stage.GetPrimAtPath({path!r}).GetReferences().RemoveReference(Sdf.Reference({reference!r}))"
        if reference
        else f"RemoveReference on {path}'s references"
    )
    return (
        f"Left as the file is: {path} was there before this call, so the file's reference on it "
        f"{', and '.join(lacks)}. The reference stays on {path}: to have the file brought instead, take it off with "
        f"execute_script, {remove}, then create_prim at a new path, such as {path}/Item"
    )


def units_lines(result: dict[str, Any], owner: str) -> list[str]:
    """Every line the answer's units fields call for, in order: the turn, the frame, the scale and the values, and
    what a prim already there didn't get."""
    lines: list[str] = []
    if turn := result.get("up_axis_turn"):
        lines.append(turned_line(turn))
    if frame := result.get("frame"):
        lines.append(frame_line(frame))
    if units := result.get("units_scale"):
        lines.extend(scaled_lines(units, owner))
    if missed := result.get("not_brought"):
        lines.append(not_brought_line(missed))
    return lines
