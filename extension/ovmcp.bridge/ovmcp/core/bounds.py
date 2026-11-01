"""World bounding boxes, and the outline a box's corners make once projected to the screen."""

from collections.abc import Sequence

from pxr import Usd, UsdGeom

from .usd import Vec, floats, is_a


def world_bbox(prim: Usd.Prim) -> tuple[list[float], list[float], list[list[float]]]:
    """(center, dimensions, [min corner, max corner]) of the prim's world bounds.

    A prim with no extent gets its world position, or the origin when it has no transform, and a 0.1 cube, so callers
    that frame or compare it still have something to work with.
    """
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    box = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if box.IsEmpty():
        if is_a(prim, UsdGeom.Xformable):
            xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            center = floats(xf.ExtractTranslation())
        else:
            center = [0.0, 0.0, 0.0]
        return center, [0.1, 0.1, 0.1], [center, center]

    min_pt, max_pt = box.GetMin(), box.GetMax()
    center, dims = center_and_size(min_pt, max_pt)
    return center, dims, [floats(min_pt), floats(max_pt)]


def center_and_size(min_pt: Vec, max_pt: Vec) -> tuple[list[float], list[float]]:
    """The box's center and its size along each axis."""
    center = [(float(min_pt[i]) + float(max_pt[i])) / 2.0 for i in range(3)]
    dims = [float(max_pt[i]) - float(min_pt[i]) for i in range(3)]
    return center, dims


def box_corners(min_pt: Vec, max_pt: Vec) -> list[list[float]]:
    """The box's 8 corners. Bit 0 of a corner's index picks the max x, bit 1 the max y, bit 2 the max z."""
    return [
        [
            float(max_pt[0]) if i & 1 else float(min_pt[0]),
            float(max_pt[1]) if i & 2 else float(min_pt[1]),
            float(max_pt[2]) if i & 4 else float(min_pt[2]),
        ]
        for i in range(8)
    ]


# The box's 12 edges, as pairs of box_corners' indices one bit apart.
_EDGES = [(i, i | bit) for i in range(8) for bit in (1, 2, 4) if not i & bit]


def project_in_front(clip: Sequence[Sequence[float]], near: float) -> list[list[float]]:
    """A box's corners in clip space, as Kit's pinhole projection gives them (omni.syntheticdata's
    get_view_proj_mat), projected to fractions of the viewport [x, y], keeping only the part in front of the camera.

    Kit's w is the view-space z, and the camera looks down -z, so a corner is in front where w <= -near. Dividing a
    corner behind the camera by its w mirrors it onto the screen (#90), so those are left out, and each edge that
    crosses the near plane gives the point where it does, which bounds the part in front. Empty when nothing is.
    """
    # A clipping range from 0 puts the plane through the eye, where a corner's w is 0 and can't be divided by.
    near = max(near, 1e-6)
    ahead = [float(c[3]) <= -near for c in clip]
    points = [_projected(clip[i]) for i in range(len(clip)) if ahead[i]]
    for a, b in _EDGES:
        if ahead[a] != ahead[b]:
            wa, wb = float(clip[a][3]), float(clip[b][3])
            t = (-near - wa) / (wb - wa)
            points.append(
                _projected([float(clip[a][k]) + t * (float(clip[b][k]) - float(clip[a][k])) for k in range(4)])
            )
    return points


def _projected(c: Sequence[float]) -> list[float]:
    """A clip-space point divided by its w and mapped from -1..1 to 0..1, as omni.syntheticdata's project_pinhole
    does."""
    w = float(c[3])
    return [0.5 * (float(c[0]) / w + 1.0), 0.5 * (float(c[1]) / w + 1.0)]


def screen_box(points: Sequence[Vec], viewport: tuple[int, int], image: tuple[int, int]) -> list[float] | None:
    """Where the outline of points lies on the viewport, as [x0, y0, x1, y1] in the output image's pixels.

    Each point's x and y are fractions of the viewport (0 to 1; a corner off-screen falls outside). The outline is the
    points' convex hull, which for a pinhole camera's points (project_in_front) is the projection of the box's part in
    front of it. It is clipped to the viewport, and the clipped part's bounding rectangle scaled from the viewport's
    size to the image's and rounded to a tenth of a pixel. None when what lies on the viewport has no width or no
    height, or nothing does: a prim beside the view, whose corners' rectangle reaches a corner of the frame while its
    outline doesn't, had a box there (#105).
    """
    vp_w, vp_h = viewport
    img_w, img_h = image
    outline = _clipped(_hull([(float(p[0]) * vp_w, float(p[1]) * vp_h) for p in points]), float(vp_w), float(vp_h))
    if not outline:
        return None
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    if x1 <= x0 or y1 <= y0:
        return None
    x0 = max(0.0, x0) * img_w / vp_w
    y0 = max(0.0, y0) * img_h / vp_h
    x1 = min(float(vp_w), x1) * img_w / vp_w
    y1 = min(float(vp_h), y1) * img_h / vp_h
    return [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]


Point = tuple[float, float]


def _hull(points: list[Point]) -> list[Point]:
    """The convex hull of points, counter-clockwise, by Andrew's monotone chain; fewer than three points, or points on
    one line, give their ends."""
    unique = sorted(set(points))
    if len(unique) < 3:
        return unique

    def turn(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    upper: list[Point] = []
    for chain, ordered in ((lower, unique), (upper, list(reversed(unique)))):
        for point in ordered:
            while len(chain) >= 2 and turn(chain[-2], chain[-1], point) <= 0:
                chain.pop()
            chain.append(point)
    return lower[:-1] + upper[:-1]


def _clipped(polygon: list[Point], width: float, height: float) -> list[Point]:
    """polygon cut to 0 <= x <= width and 0 <= y <= height, one edge of the frame at a time (Sutherland-Hodgman); a
    point or a segment is cut as a polygon of one or two corners. Empty when nothing of it is inside."""
    edges = (
        (0, 0.0, True),  # x >= 0
        (0, width, False),  # x <= width
        (1, 0.0, True),  # y >= 0
        (1, height, False),  # y <= height
    )
    for axis, bound, above in edges:

        def inside(p: Point, axis: int = axis, bound: float = bound, above: bool = above) -> bool:
            return p[axis] >= bound if above else p[axis] <= bound

        def crossing(a: Point, b: Point, axis: int = axis, bound: float = bound) -> Point:
            t = (bound - a[axis]) / (b[axis] - a[axis])
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

        cut: list[Point] = []
        for i, current in enumerate(polygon):
            previous = polygon[i - 1]
            if inside(current):
                if not inside(previous):
                    cut.append(crossing(previous, current))
                cut.append(current)
            elif inside(previous):
                cut.append(crossing(previous, current))
        polygon = cut
        if not polygon:
            break
    return polygon
