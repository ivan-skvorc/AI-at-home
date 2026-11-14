"""The operations a script may ask for, as data.

This table is the whole reach of a script into the kernel: the interpreter
calls a ``Workplane`` method only when its name is a key here, and passes an
argument only when the table names the parameter and the value fits its kind.
A method that takes a file path, a callable, a font or a raw kernel object is
absent on purpose and stays absent (README, "What a script may contain").

The module imports nothing from CadQuery, so the table can be read, tested and
turned into documentation without the kernel installed.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Parameter kinds --------------------------------------------------------
# A kind names what a script may put in one argument. A tuple of strings is a
# closed vocabulary: the argument must be one of them.

LENGTH = "length"  # a number greater than zero, in millimetres
NUMBER = "number"  # any number within the magnitude cap
ANGLE = "angle"  # a number of degrees
COUNT = "count"  # a whole number of at least one
SIDES = "sides"  # a whole number of at least three
BOOL = "bool"
POINT = "point"  # two or three numbers
POINTS = "points"  # a list or tuple of points
CENTERED = "centered"  # a bool, or two or three bools
PLANE = "plane"  # one of PLANE_NAMES
SELECTOR = "selector"  # a CadQuery selector string, see SELECTOR_PATTERN
TAG = "tag"  # a label, see TAG_PATTERN
WORKPLANE = "workplane"  # a part built earlier in the script

PLANE_NAMES = ("XY", "YZ", "ZX", "XZ", "YX", "ZY", "front", "back", "left", "right", "top", "bottom")
#: mirror() knows the six axis planes only; the kernel fails obscurely on any other name.
MIRROR_PLANES = ("XY", "YX", "XZ", "ZX", "YZ", "ZY")

#: CadQuery's selector grammar: direction, type and index filters joined by
#: and/or/not/exc. Nothing here names a file, a module or an attribute.
SELECTOR_PATTERN = r"[A-Za-z0-9 <>|#%+\-\[\](),.]{1,80}"
TAG_PATTERN = r"[A-Za-z][A-Za-z0-9_]{0,31}"

# --- Limits -----------------------------------------------------------------

#: Largest coordinate or size a script may state, in millimetres (100 m), and the
#: smallest length. The kernel answers anything smaller with an empty error.
MAX_MAGNITUDE = 100_000.0
MIN_LENGTH = 0.0001
MAX_ANGLE = 3600.0
#: Points one pattern call may create, and all pattern calls of a script together.
#: Cost grows faster than the count, and the common idiom circle().cutThruAll() is far
#: slower than hole(): 100 circles cut in about 7 seconds on four cores, 225 in about a
#: minute. With these caps the worst accepted script still fits the worker's wall clock.
MAX_INSTANCES_PER_CALL = 100
MAX_INSTANCES_PER_SCRIPT = 200
#: Elements one list or tuple may hold.
MAX_SEQUENCE_ITEMS = 400


@dataclass(frozen=True)
class Param:
    name: str
    kind: str | tuple[str, ...]
    required: bool = False
    nullable: bool = False


@dataclass(frozen=True)
class Method:
    """One allow-listed call: its parameters in CadQuery's own positional order."""

    params: tuple[Param, ...]
    summary: str
    example: str
    #: Parameters whose product is the number of pattern points the call makes.
    instances: tuple[str, ...] = ()


def _req(name: str, kind: str | tuple[str, ...]) -> Param:
    return Param(name, kind, required=True)


def _opt(name: str, kind: str | tuple[str, ...], *, nullable: bool = False) -> Param:
    return Param(name, kind, nullable=nullable)


_CLEAN = _opt("clean", BOOL)
_COMBINE = _opt("combine", BOOL)
_CONSTRUCTION = _opt("forConstruction", BOOL)
_BASE = 'cq.Workplane("XY")'

#: ``cq.Workplane(...)``: the only thing a script may call on ``cq``.
CONSTRUCTOR = Method(
    (_opt("inPlane", PLANE), _opt("origin", POINT)),
    "Start a part on a named plane.",
    'cq.Workplane("XY")',
)

METHODS: dict[str, Method] = {
    # Primitives
    "box": Method((_req("length", LENGTH), _req("width", LENGTH), _req("height", LENGTH), _opt("centered", CENTERED), _COMBINE, _CLEAN), "A box, centred on the workplane origin unless centered says otherwise.", f"{_BASE}.box(60, 40, 6)"),
    "cylinder": Method((_req("height", LENGTH), _req("radius", LENGTH), _opt("direct", POINT), _opt("angle", ANGLE), _opt("centered", CENTERED), _COMBINE, _CLEAN), "A cylinder along the workplane normal.", f"{_BASE}.cylinder(20, 5)"),
    "sphere": Method((_req("radius", LENGTH),), "A sphere.", f"{_BASE}.sphere(10)"),
    # Two-dimensional outlines, to extrude or to cut
    "rect": Method((_req("xLen", LENGTH), _req("yLen", LENGTH), _opt("centered", CENTERED), _CONSTRUCTION), "A rectangle on the workplane, one per point on the stack.", f"{_BASE}.rect(30, 20).extrude(5)"),
    "circle": Method((_req("radius", LENGTH), _CONSTRUCTION), "A circle on the workplane, one per point on the stack.", f"{_BASE}.circle(10).extrude(5)"),
    "ellipse": Method((_req("x_radius", LENGTH), _req("y_radius", LENGTH), _opt("rotation_angle", ANGLE), _CONSTRUCTION), "An ellipse on the workplane.", f"{_BASE}.ellipse(20, 10).extrude(5)"),
    "polygon": Method((_req("nSides", SIDES), _req("diameter", LENGTH), _CONSTRUCTION, _opt("circumscribed", BOOL)), "A regular polygon.", f"{_BASE}.polygon(6, 20).extrude(5)"),
    "slot2D": Method((_req("length", LENGTH), _req("diameter", LENGTH), _opt("angle", ANGLE)), "A slot with rounded ends.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().slot2D(20, 6).cutThruAll()"),
    "polyline": Method(
        (_req("listOfXYTuple", POINTS), _CONSTRUCTION, _opt("includeCurrent", BOOL)),
        "Straight segments through the given points; close() finishes the outline.",
        f"{_BASE}.polyline([(0, 0), (40, 0), (40, 10), (10, 10), (10, 30), (0, 30)]).close().extrude(20)",
    ),
    "moveTo": Method((_opt("x", NUMBER), _opt("y", NUMBER)), "Move the pen to a point without drawing.", f"{_BASE}.moveTo(10, 0).lineTo(20, 0).lineTo(20, 10).close().extrude(5)"),
    "move": Method((_opt("xDist", NUMBER), _opt("yDist", NUMBER)), "Move the pen by a distance without drawing.", f"{_BASE}.move(10, 0).circle(3).extrude(5)"),
    "lineTo": Method((_req("x", NUMBER), _req("y", NUMBER), _CONSTRUCTION), "A line to a point.", f"{_BASE}.lineTo(30, 0).lineTo(30, 20).close().extrude(5)"),
    "line": Method((_req("xDist", NUMBER), _req("yDist", NUMBER), _CONSTRUCTION), "A line by a distance.", f"{_BASE}.line(30, 0).line(0, 20).close().extrude(5)"),
    "hLine": Method((_req("distance", NUMBER), _CONSTRUCTION), "A horizontal line by a distance.", f"{_BASE}.hLine(30).vLine(20).close().extrude(5)"),
    "vLine": Method((_req("distance", NUMBER), _CONSTRUCTION), "A vertical line by a distance.", f"{_BASE}.hLine(30).vLine(20).close().extrude(5)"),
    "hLineTo": Method((_req("xCoord", NUMBER), _CONSTRUCTION), "A horizontal line to an x coordinate.", f"{_BASE}.hLineTo(30).vLineTo(20).close().extrude(5)"),
    "vLineTo": Method((_req("yCoord", NUMBER), _CONSTRUCTION), "A vertical line to a y coordinate.", f"{_BASE}.hLineTo(30).vLineTo(20).close().extrude(5)"),
    "threePointArc": Method((_req("point1", POINT), _req("point2", POINT), _CONSTRUCTION), "An arc through a point to an end point.", f"{_BASE}.lineTo(20, 0).threePointArc((25, 5), (20, 10)).lineTo(0, 10).close().extrude(5)"),
    "close": Method((), "Close the outline back to its start.", f"{_BASE}.lineTo(30, 0).lineTo(30, 20).close().extrude(5)"),
    "center": Method((_req("x", NUMBER), _req("y", NUMBER)), "Shift the workplane origin.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().center(10, 0).hole(4)"),
    # Solids from outlines
    "extrude": Method((_req("until", NUMBER), _COMBINE, _CLEAN, _opt("both", BOOL), _opt("taper", ANGLE, nullable=True)), "Extrude the outline by a distance.", f"{_BASE}.rect(30, 20).extrude(5)"),
    "cutBlind": Method(
        (_req("until", NUMBER), _CLEAN, _opt("both", BOOL), _opt("taper", ANGLE, nullable=True)),
        "Cut the outline into the part by a distance; negative cuts into the face.",
        f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutBlind(-3)",
    ),
    "cutThruAll": Method((_CLEAN, _opt("taper", ANGLE)), "Cut the outline through the whole part.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutThruAll()"),
    # Holes: one per point on the stack
    "hole": Method((_req("diameter", LENGTH), _opt("depth", LENGTH, nullable=True), _CLEAN), "A hole; through the part unless depth is given.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)"),
    "cboreHole": Method(
        (_req("diameter", LENGTH), _req("cboreDiameter", LENGTH), _req("cboreDepth", LENGTH), _opt("depth", LENGTH, nullable=True), _CLEAN), "A counterbored hole.", f"{_BASE}.box(60, 40, 10).faces('>Z').workplane().cboreHole(4, 8, 3)"
    ),
    "cskHole": Method(
        (_req("diameter", LENGTH), _req("cskDiameter", LENGTH), _req("cskAngle", ANGLE), _opt("depth", LENGTH, nullable=True), _CLEAN), "A countersunk hole.", f"{_BASE}.box(60, 40, 10).faces('>Z').workplane().cskHole(4, 8, 82)"
    ),
    # Edges and walls
    "fillet": Method((_req("radius", LENGTH),), "Round the selected edges.", f"{_BASE}.box(60, 40, 6).edges('|Z').fillet(3)"),
    "chamfer": Method((_req("length", LENGTH), _opt("length2", LENGTH, nullable=True)), "Bevel the selected edges.", f"{_BASE}.box(60, 40, 6).edges('>Z').chamfer(1)"),
    "shell": Method((_req("thickness", NUMBER), _opt("kind", ("arc", "intersection"))), "Hollow the part, removing the selected faces; negative thickness shells inward.", f"{_BASE}.box(60, 40, 30).faces('>Z').shell(-2)"),
    # Points to repeat the next outline or hole on
    "pushPoints": Method((_req("pntList", POINTS),), "Put points on the stack.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)", instances=("pntList",)),
    "rarray": Method(
        (_req("xSpacing", LENGTH), _req("ySpacing", LENGTH), _req("xCount", COUNT), _req("yCount", COUNT), _opt("center", CENTERED)),
        "A rectangular grid of points.",
        f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rarray(20, 20, 2, 2).hole(4)",
        instances=("xCount", "yCount"),
    ),
    "polarArray": Method(
        (_req("radius", LENGTH), _req("startAngle", ANGLE), _req("angle", ANGLE), _req("count", COUNT), _opt("fill", BOOL), _opt("rotate", BOOL)),
        "Points on a circle.",
        f"{_BASE}.cylinder(6, 30).faces('>Z').workplane().polarArray(20, 0, 360, 6).hole(4)",
        instances=("count",),
    ),
    # Selecting where to work
    "faces": Method((_opt("selector", SELECTOR), _opt("tag", TAG)), "Select faces with a CadQuery selector string.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().hole(4)"),
    "edges": Method((_opt("selector", SELECTOR), _opt("tag", TAG)), "Select edges with a CadQuery selector string.", f"{_BASE}.box(60, 40, 6).edges('|Z').fillet(3)"),
    "vertices": Method((_opt("selector", SELECTOR), _opt("tag", TAG)), "Select vertices; with workplane() or as points for holes.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rect(50, 30, forConstruction=True).vertices().hole(3)"),
    "workplane": Method(
        (_opt("offset", NUMBER), _opt("invert", BOOL), _opt("centerOption", ("CenterOfMass", "ProjectedOrigin", "CenterOfBoundBox")), _opt("origin", POINT, nullable=True)),
        "A new workplane on the selected face.",
        f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().hole(4)",
    ),
    "tag": Method((_req("name", TAG),), "Name the current state, to return to it with workplaneFromTagged.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)"),
    "workplaneFromTagged": Method((_req("name", TAG),), "Return to a tagged workplane.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)"),
    # Moving and copying
    "translate": Method((_req("vec", POINT),), "Move the part.", f"{_BASE}.box(10, 10, 10).translate((20, 0, 0))"),
    "rotate": Method((_req("axisStartPoint", POINT), _req("axisEndPoint", POINT), _req("angleDegrees", ANGLE)), "Rotate the part about an axis through two points.", f"{_BASE}.box(30, 10, 10).rotate((0, 0, 0), (0, 0, 1), 45)"),
    "mirror": Method(
        (_opt("mirrorPlane", MIRROR_PLANES), _opt("basePointVector", POINT, nullable=True), _opt("union", BOOL)),
        "Mirror the part across a named plane; union=True keeps both halves as one solid.",
        f"{_BASE}.box(20, 10, 10, centered=False).mirror('YZ', union=True)",
    ),
    "mirrorX": Method((), "Mirror a half outline across the workplane's x axis, closing it.", f"{_BASE}.vLine(10).hLine(20).vLineTo(0).mirrorX().extrude(5)"),
    "mirrorY": Method((), "Mirror a half outline across the workplane's y axis, closing it.", f"{_BASE}.hLine(20).vLine(10).hLineTo(0).mirrorY().extrude(5)"),
    # Combining parts held in variables
    "union": Method((_req("toUnion", WORKPLANE), _CLEAN), "Join another part to this one.", "base = cq.Workplane('XY').box(60, 40, 6)\nrib = cq.Workplane('XY').box(6, 40, 20).translate((0, 0, 13))\nresult = base.union(rib)"),
    "cut": Method((_req("toCut", WORKPLANE), _CLEAN), "Remove another part from this one.", "block = cq.Workplane('XY').box(40, 40, 20)\npocket = cq.Workplane('XY').box(20, 20, 10).translate((0, 0, 5))\nresult = block.cut(pocket)"),
    "intersect": Method((_req("toIntersect", WORKPLANE), _CLEAN), "Keep what this part shares with another.", "a = cq.Workplane('XY').box(40, 40, 20)\nb = cq.Workplane('XY').sphere(22)\nresult = a.intersect(b)"),
}
