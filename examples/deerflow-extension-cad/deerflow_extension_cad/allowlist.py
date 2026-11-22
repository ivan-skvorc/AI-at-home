"""The operations a script may ask for, as data.

This table is the whole reach of a script into the kernel: the interpreter
calls a ``Workplane`` method only when its name is a key here, and passes an
argument only when the table names the parameter and the value fits its kind.
A parameter that takes a file path, a callable, a font or a raw kernel object
is absent on purpose and stays absent (README, "What a script may contain"):
``text`` is here without its ``font`` and ``fontPath``, because ``build.py``
passes the module's own font file. Besides ``cq.Workplane``, the one thing a
script may call on ``cq`` is ``cq.Wire.makeHelix`` (``HELIX``), whose wire only
``sweep`` takes.

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
SIDES = "sides"  # a whole number from three to MAX_SIDES
BOOL = "bool"
POINT = "point"  # two or three numbers
POINTS = "points"  # a list or tuple of points
CENTERED_2D = "centered2"  # a bool, or one bool per axis of an outline
CENTERED_3D = "centered3"  # a bool, or one bool per axis of a solid
PLANE = "plane"  # one of PLANE_NAMES
SELECTOR = "selector"  # a CadQuery selector string, see SELECTOR_PATTERN
TAG = "tag"  # a label, see TAG_PATTERN
WORKPLANE = "workplane"  # a part built earlier in the script
PATH = "path"  # an outline drawn earlier in the script (see OUTLINES), or a helix, to sweep along
TEXT = "text"  # lettering: printable ASCII, at most MAX_TEXT characters

PLANE_NAMES = ("XY", "YZ", "ZX", "XZ", "YX", "ZY", "front", "back", "left", "right", "top", "bottom")
#: mirror() knows the six axis planes only; the kernel fails obscurely on any other name.
MIRROR_PLANES = ("XY", "YX", "XZ", "ZX", "YZ", "ZY")
#: The methods that end with lines, arcs or curves on the stack: what a PATH must end with.
#: A path that ends with a solid, a point or a moved copy is not swept along: the kernel
#: answers it with an error that names no cause.
OUTLINES = frozenset(
    {
        "rect",
        "circle",
        "ellipse",
        "polygon",
        "slot2D",
        "polyline",
        "lineTo",
        "line",
        "hLine",
        "vLine",
        "hLineTo",
        "vLineTo",
        "threePointArc",
        "spline",
        "radiusArc",
        "sagittaArc",
        "tangentArcPoint",
        "polarLine",
        "polarLineTo",
        "close",
        "mirrorX",
        "mirrorY",
        "offset2D",
    }
)

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
#: slower than hole(): 100 circles cut in about 7 seconds on four cores, 225 in 30 to 60
#: seconds. The caps keep the ordinary idioms inside the worker's wall clock. They are
#: not a bound on every script: vertices() on construction geometry multiplies the
#: points on the stack, and what stops that is the parent's wall clock.
MAX_INSTANCES_PER_CALL = 100
MAX_INSTANCES_PER_SCRIPT = 200
#: Sides of one regular polygon: past this it is a circle, and each side is a point.
MAX_SIDES = 100
#: Elements one list or tuple may hold.
MAX_SEQUENCE_ITEMS = 400
#: Letters one text() call cuts or raises: a label, not a page. Each is read as work.
MAX_TEXT = 64
#: Turns of one helix: past any screw a home printer makes, and few enough that sweeping
#: a thread along it stays inside the build's wall clock.
MAX_HELIX_TURNS = 200

# --- Numbers ----------------------------------------------------------------
# What a script may compute with besides arithmetic. The reader computes each one
# with its own functions on numbers it has already checked; no name here is ever
# looked up on a module, and a script cannot assign any of them.

#: ``import math`` gives a script these two constants...
MATH_CONSTANTS = ("pi", "tau")
#: ...and these functions, each with the fewest and the most numbers it takes.
MATH_FUNCTIONS: dict[str, tuple[int, int]] = {
    "sin": (1, 1),
    "cos": (1, 1),
    "tan": (1, 1),
    "asin": (1, 1),
    "acos": (1, 1),
    "atan": (1, 1),
    "atan2": (2, 2),
    "sqrt": (1, 1),
    "hypot": (2, 3),
    "radians": (1, 1),
    "degrees": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
}
#: Built-in calls, on numbers and on lists the script states.
BUILTINS = ("abs", "min", "max", "round", "int", "float", "len")


@dataclass(frozen=True)
class Param:
    name: str
    kind: str | tuple[str, ...]
    required: bool = False
    nullable: bool = False
    #: Given by name only: the kernel has it further down its own order than the table can follow.
    keyword: bool = False


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


def _kw(name: str, kind: str | tuple[str, ...]) -> Param:
    return Param(name, kind, keyword=True)


_CLEAN = _opt("clean", BOOL)
_COMBINE = _opt("combine", BOOL)
_CONSTRUCTION = _opt("forConstruction", BOOL)
_BASE = 'cq.Workplane("XY")'

#: ``cq.Workplane(...)``: one of the two things a script may call on ``cq``; the other is ``HELIX``.
CONSTRUCTOR = Method(
    (_opt("inPlane", PLANE), _opt("origin", POINT)),
    "Start a part on a named plane.",
    'cq.Workplane("XY")',
)

#: ``cq.Wire.makeHelix(...)``: the one constructor on ``cq`` besides Workplane, for threads. The
#: reader keeps its numbers as data; build.py makes the wire, and only sweep's path takes it.
HELIX = Method(
    (_req("pitch", LENGTH), _req("height", LENGTH), _req("radius", LENGTH), _kw("lefthand", BOOL)),
    f"A helix to sweep a thread's outline along, at most {MAX_HELIX_TURNS} turns (height / pitch); the outline is drawn on a plane through the axis, at the radius.",
    "helix = cq.Wire.makeHelix(1.25, 10, 3.2)\nthread = cq.Workplane('XZ').polyline([(3.2, -0.5), (4, -0.08), (4, 0.08), (3.2, 0.5)]).close().sweep(helix, isFrenet=True)\nresult = cq.Workplane('XY').circle(3.25).extrude(10).union(thread)",
)

METHODS: dict[str, Method] = {
    # Primitives
    "box": Method(
        (_req("length", LENGTH), _req("width", LENGTH), _req("height", LENGTH), _opt("centered", CENTERED_3D), _COMBINE, _CLEAN), "A box, centred on the workplane origin unless centered says otherwise.", f"{_BASE}.box(60, 40, 6)"
    ),
    "cylinder": Method((_req("height", LENGTH), _req("radius", LENGTH), _opt("direct", POINT), _opt("angle", ANGLE), _opt("centered", CENTERED_3D), _COMBINE, _CLEAN), "A cylinder along the workplane normal.", f"{_BASE}.cylinder(20, 5)"),
    "sphere": Method((_req("radius", LENGTH),), "A sphere.", f"{_BASE}.sphere(10)"),
    "wedge": Method(
        (
            _req("dx", LENGTH),
            _req("dy", LENGTH),
            _req("dz", LENGTH),
            _req("xmin", NUMBER),
            _req("zmin", NUMBER),
            _req("xmax", NUMBER),
            _req("zmax", NUMBER),
            _opt("pnt", POINT),
            _opt("dir", POINT),
            _opt("centered", CENTERED_3D),
            _COMBINE,
            _CLEAN,
        ),
        "A wedge: a dx by dz base that narrows, dy higher, to the face from xmin to xmax and zmin to zmax.",
        f"{_BASE}.wedge(20, 10, 10, 5, 5, 15, 5)",
    ),
    # Two-dimensional outlines, to extrude or to cut
    "rect": Method((_req("xLen", LENGTH), _req("yLen", LENGTH), _opt("centered", CENTERED_2D), _CONSTRUCTION), "A rectangle on the workplane, one per point on the stack.", f"{_BASE}.rect(30, 20).extrude(5)"),
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
    "spline": Method(
        (_req("listOfXYTuple", POINTS), _opt("tangents", POINTS, nullable=True), _opt("periodic", BOOL)),
        "A smooth curve through the given points; tangents gives its direction at the start and the end.",
        f"{_BASE}.spline([(0, 0), (10, 8), (20, 0)]).close().extrude(5)",
    ),
    "radiusArc": Method((_req("endPoint", POINT), _req("radius", NUMBER), _CONSTRUCTION), "An arc of a radius to an end point; a negative radius bends it the other way.", f"{_BASE}.hLine(20).radiusArc((0, 0), -12).close().extrude(5)"),
    "sagittaArc": Method((_req("endPoint", POINT), _req("sag", NUMBER), _CONSTRUCTION), "An arc to an end point that bulges by sag from the straight line.", f"{_BASE}.hLine(20).sagittaArc((0, 0), 5).close().extrude(5)"),
    "tangentArcPoint": Method(
        (_req("endpoint", POINT), _CONSTRUCTION, _opt("relative", BOOL)),
        "An arc that carries on smoothly from the last line, to a point given from the pen unless relative=False.",
        f"{_BASE}.hLine(20).tangentArcPoint((0, 10)).hLineTo(0).close().extrude(5)",
    ),
    "polarLine": Method((_req("distance", NUMBER), _req("angle", ANGLE), _CONSTRUCTION), "A line by a distance at an angle in degrees from the x axis.", f"{_BASE}.polarLine(20, 30).hLineTo(0).close().extrude(5)"),
    "polarLineTo": Method((_req("distance", NUMBER), _req("angle", ANGLE), _CONSTRUCTION), "A line to the point at a distance and an angle from the origin.", f"{_BASE}.hLine(20).polarLineTo(20, 60).close().extrude(5)"),
    "close": Method((), "Close the outline back to its start.", f"{_BASE}.lineTo(30, 0).lineTo(30, 20).close().extrude(5)"),
    "center": Method((_req("x", NUMBER), _req("y", NUMBER)), "Shift the workplane origin.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().center(10, 0).hole(4)"),
    "offset2D": Method(
        (_req("d", NUMBER), _opt("kind", ("arc", "intersection")), _CONSTRUCTION),
        "Grow the outline by d, or shrink it by a negative d; kind 'arc' rounds the corners it grows.",
        f"{_BASE}.rect(20, 10).offset2D(2).extrude(5)",
    ),
    # Solids from outlines
    "extrude": Method((_req("until", NUMBER), _COMBINE, _CLEAN, _opt("both", BOOL), _opt("taper", ANGLE, nullable=True)), "Extrude the outline by a distance.", f"{_BASE}.rect(30, 20).extrude(5)"),
    "cutBlind": Method(
        (_req("until", NUMBER), _CLEAN, _opt("both", BOOL), _opt("taper", ANGLE, nullable=True)),
        "Cut the outline into the part by a distance; negative cuts into the face.",
        f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutBlind(-3)",
    ),
    "cutThruAll": Method((_CLEAN, _opt("taper", ANGLE)), "Cut the outline through the whole part.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().rect(20, 10).cutThruAll()"),
    "revolve": Method(
        (_opt("angleDegrees", ANGLE), _opt("axisStart", POINT, nullable=True), _opt("axisEnd", POINT, nullable=True), _COMBINE, _CLEAN),
        "Turn the outline about an axis through two points of the workplane, by an angle in degrees. The axis must not cross the outline.",
        f"{_BASE}.moveTo(12.5, 0).rect(5, 4).revolve(360, (0, 0, 0), (0, 1, 0))",
    ),
    "loft": Method(
        (_opt("ruled", BOOL), _COMBINE, _CLEAN),
        "A solid through the outlines drawn on successive workplanes, first to last; ruled=True joins them with straight lines.",
        f"{_BASE}.circle(10).workplane(offset=20).circle(5).loft()",
    ),
    "sweep": Method(
        (
            _req("path", PATH),
            _opt("multisection", BOOL),
            _opt("sweepAlongWires", BOOL, nullable=True),
            _opt("makeSolid", BOOL),
            _opt("isFrenet", BOOL),
            _COMBINE,
            _CLEAN,
            _opt("transition", ("right", "round", "transformed")),
        ),
        "Move the outline along a path drawn earlier; the path starts on the outline's plane. transition is how corners are joined.",
        "path = cq.Workplane('XZ').polyline([(0, 0), (0, 20), (20, 20)])\nresult = cq.Workplane('XY').rect(4, 4).sweep(path)",
    ),
    "text": Method(
        (_req("txt", TEXT), _req("fontsize", LENGTH), _req("distance", NUMBER), _COMBINE, _CLEAN, _kw("halign", ("center", "left", "right")), _kw("valign", ("center", "top", "bottom"))),
        "Lettering in the module's own font, fontsize millimetres tall. It is cut into the part for a negative distance; combine=True and a positive distance raise it.",
        f"{_BASE}.box(40, 15, 3).faces('>Z').workplane().text('HELLO', 8, -0.6)",
    ),
    "twistExtrude": Method((_req("distance", NUMBER), _req("angleDegrees", ANGLE), _COMBINE, _CLEAN), "Extrude the outline by a distance while turning it by an angle in degrees.", f"{_BASE}.rect(20, 10).twistExtrude(10, 45)"),
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
        (_req("xSpacing", LENGTH), _req("ySpacing", LENGTH), _req("xCount", COUNT), _req("yCount", COUNT), _opt("center", CENTERED_2D)),
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
    "transformed": Method(
        (_opt("rotate", POINT), _opt("offset", POINT)),
        "Turn the workplane by degrees about its x, y and z axes and move it by offset: for angled holes and features.",
        f"{_BASE}.box(40, 40, 10).faces('>Z').workplane().transformed(rotate=(30, 0, 0)).hole(5)",
    ),
    "tag": Method((_req("name", TAG),), "Name the current state, to return to it with workplaneFromTagged.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)"),
    "workplaneFromTagged": Method((_req("name", TAG),), "Return to a tagged workplane.", f"{_BASE}.box(60, 40, 6).faces('>Z').workplane().tag('top').hole(4).workplaneFromTagged('top').center(20, 0).hole(3)"),
    "end": Method((_opt("n", COUNT),), "Go back n steps, to what was selected before the last n calls.", f"{_BASE}.box(30, 20, 5).faces('>Z').edges('|X').end(2).edges('|Z').fillet(2)"),
    "first": Method((), "Keep the first of the selected items.", f"{_BASE}.box(30, 20, 5).edges('|Z').first().fillet(2)"),
    "last": Method((), "Keep the last of the selected items.", f"{_BASE}.box(30, 20, 5).edges('|Z').last().fillet(2)"),
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
    "split": Method(
        (_kw("keepTop", BOOL), _kw("keepBottom", BOOL)),
        "Cut the part in two at the workplane and keep the top, the bottom or both, as for a part too tall for the printer's bed.",
        f"{_BASE}.box(20, 20, 40).faces('>Z').workplane(-20).split(keepBottom=True)",
    ),
    # Combining parts held in variables
    "union": Method((_req("toUnion", WORKPLANE), _CLEAN), "Join another part to this one.", "base = cq.Workplane('XY').box(60, 40, 6)\nrib = cq.Workplane('XY').box(6, 40, 20).translate((0, 0, 13))\nresult = base.union(rib)"),
    "cut": Method((_req("toCut", WORKPLANE), _CLEAN), "Remove another part from this one.", "block = cq.Workplane('XY').box(40, 40, 20)\npocket = cq.Workplane('XY').box(20, 20, 10).translate((0, 0, 5))\nresult = block.cut(pocket)"),
    "intersect": Method((_req("toIntersect", WORKPLANE), _CLEAN), "Keep what this part shares with another.", "a = cq.Workplane('XY').box(40, 40, 20)\nb = cq.Workplane('XY').sphere(22)\nresult = a.intersect(b)"),
}


# --- The table as a page ----------------------------------------------------

_KIND_WORDS = {
    LENGTH: "millimetres, above 0",
    NUMBER: "a number",
    ANGLE: "degrees",
    COUNT: "a whole number, 1 or more",
    SIDES: f"a whole number, 3 to {MAX_SIDES}",
    BOOL: "True or False",
    POINT: "a point, (x, y) or (x, y, z)",
    POINTS: "a list of points",
    CENTERED_2D: "True, False, or one of them per axis: (True, False)",
    CENTERED_3D: "True, False, or one of them per axis: (True, True, False)",
    PLANE: "a plane name",
    SELECTOR: "a selector string",
    TAG: "a label of letters, digits and underscores",
    WORKPLANE: "a part built earlier in the script",
    PATH: "an outline drawn earlier in the script with lines, arcs, a spline or a circle, or a helix; not a solid",
    TEXT: f"lettering, at most {MAX_TEXT} plain ASCII characters",
}


def _signature(name: str, method: Method) -> str:
    def said(param: Param) -> str:
        if param.keyword:
            return f"[{param.name}=]"
        return param.name if param.required else f"[{param.name}]"

    return f"{name}({', '.join(map(said, method.params))})"


def _arguments(method: Method) -> str:
    """Each parameter with what it takes; parameters of one kind share a line."""
    by_kind: dict[str, list[str]] = {}
    for param in method.params:
        words = _KIND_WORDS[param.kind] if isinstance(param.kind, str) else "one of " + ", ".join(f'"{choice}"' for choice in param.kind)
        by_kind.setdefault(words + (", or None" if param.nullable else ""), []).append(param.name)
    return "\n".join(f"- `{'`, `'.join(names)}`: {words}" for words, names in by_kind.items())


def reference() -> str:
    """The table as the page a model reads: ``references/operations.md`` of the cad-modeling skill.

    Generated, so the page says no more and no less than the table. After a change to
    the table, run this file and write its output over that page (the package's AGENTS.md
    has the command); ``tests/skills/test_cad_modeling.py`` fails until the two agree.
    """
    lines = [
        "# Operations a script may use",
        "",
        "Generated from the CAD module's allow-list. Do not edit: change the table and regenerate.",
        "",
        "A part starts with `cq.Workplane(...)` and is shaped by the methods below, each called on a part.",
        "Arguments are in CadQuery's order and may be given by name; one in `[brackets]` is optional, and one written `[name=]` is given by name only.",
        "Any other method, and anything else on `cq` but `cq.Wire.makeHelix`, is refused.",
        "",
        f"- Plane names: {', '.join(f'`{name}`' for name in PLANE_NAMES)}.",
        '- Selector strings: CadQuery\'s own, such as `">Z"`, `"<X"`, `"|Z"`, `"#Z"`, `"%CIRCLE"`, `"|Z and >Y"`.',
        f"- Sizes and coordinates: at most {MAX_MAGNITUDE:g} mm; a length is at least {MIN_LENGTH:g} mm.",
        f"- Patterns (`pushPoints`, `rarray`, `polarArray`): at most {MAX_INSTANCES_PER_CALL} points in one call and {MAX_INSTANCES_PER_SCRIPT} in a script.",
        f"- Numbers: `import math` gives {', '.join(f'`math.{name}`' for name in MATH_CONSTANTS)} and {', '.join(f'`math.{name}()`' for name in MATH_FUNCTIONS)}.",
        f"  {', '.join(f'`{name}()`' for name in BUILTINS)} take numbers or a list of them. An index such as `p[0]` is a whole number.",
        "",
        f"## {_signature('cq.Workplane', CONSTRUCTOR)}",
        "",
        CONSTRUCTOR.summary,
        "",
        _arguments(CONSTRUCTOR),
        "",
        "```python",
        f"result = {CONSTRUCTOR.example}.box(10, 10, 10)",
        "```",
        "",
        f"## {_signature('cq.Wire.makeHelix', HELIX)}",
        "",
        HELIX.summary,
        "",
        _arguments(HELIX),
        "",
        "```python",
        HELIX.example,
        "```",
    ]
    for name, method in METHODS.items():
        example = method.example if "result = " in method.example else f"result = {method.example}"
        lines += ["", f"## {_signature(name, method)}", "", method.summary, ""]
        if method.params:
            lines += [_arguments(method), ""]
        lines += ["```python", example, "```"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(reference(), end="")
