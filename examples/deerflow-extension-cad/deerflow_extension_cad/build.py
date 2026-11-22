"""Perform a compiled program against the kernel and export the part.

This module is the only place a script's request turns into a kernel call, and
the call is always the same shape: a ``Workplane`` method whose name is a key
of ``allowlist.METHODS``, with keyword arguments the interpreter already
checked. Two arguments are the module's own and never the script's: the font
file of ``text`` (``INJECTED``) and the helix wire a thread is swept along,
made here from the numbers the interpreter kept. It runs in the worker process
only; the Gateway never imports it.
"""

from __future__ import annotations

import io
import json
import re
import struct
import zipfile
from pathlib import Path

from deerflow_extension_cad import allowlist as table
from deerflow_extension_cad.interpreter import Helix, Program, Ref

#: The lettering font, shipped in the package: the slim Gateway image has no system fonts,
#: and a script never names a font or a path (fonts/README.md).
FONT = Path(__file__).with_name("fonts") / "LiberationSans-Regular.ttf"
#: Arguments this module passes itself, by method: never in the table, never from a script.
INJECTED = {"text": ("fontPath",)}

#: The STL and GLB meshes, finest first: millimetres off the surface, radians between
#: facets. The angle decides size and time. A part dense with small fillets and holes
#: is meshed at the next step until its STL fits the target.
MESH_STEPS = ((0.1, 0.3), (0.2, 0.5), (0.4, 0.8))
#: The host stores 8 MiB per file by default; a mesh under this leaves room for it.
MESH_TARGET_BYTES = 6 * 1024 * 1024
#: Past this size the tolerance grows with the part: a tenth of a millimetre on a
#: part of several metres is millions of triangles nobody asked for.
MESH_FULL_DETAIL_MM = 1000.0

#: Operations whose whole point is to change the solid. One that changes nothing is a
#: script that missed the part, and with only a bounding box to meet it would pass.
#: A harmless repeat (the same hole drilled twice) is refused with it: the line is not
#: needed, and nothing here can tell the two apart.
_REDUNDANT = " Delete this line if the part is right without it."
#: The same for a line inside a loop, where the line is every pass and only this pass does nothing.
_REDUNDANT_PASS = " Leave this pass out if the part is right without it."
_OFF_THE_PART = "removed no material: it is off the part, or the material there is already gone." + _REDUNDANT
_INSIDE_THE_PART = "added no material: the new body lies inside the part, so check its position and direction." + _REDUNDANT
_MUST_CHANGE = {
    # One sentence for every way a blind cut removes nothing: the wrong way, beside the part, or twice.
    "cutBlind": (
        "removed no material: the cut ran away from the material, started beside it, or the material there is already gone. "
        "A blind cut runs against the workplane's normal for a negative distance (into the part from a face it was taken from) and along it for a positive one. "
        "Check the face it starts from: faces('>Z') is the highest face of the part as it is now, which a boss or a lip added earlier has moved." + _REDUNDANT
    ),
    "cutThruAll": _OFF_THE_PART,
    "hole": _OFF_THE_PART,
    "cboreHole": _OFF_THE_PART,
    "cskHole": _OFF_THE_PART,
    "cut": "removed no material: the two parts do not overlap." + _REDUNDANT,
    "intersect": "changed nothing: the other part contains this one." + _REDUNDANT,
    "shell": "changed nothing: the wall is probably thicker than the part allows.",
    "extrude": _INSIDE_THE_PART,
    "union": _INSIDE_THE_PART,
    "box": _INSIDE_THE_PART,
    "cylinder": _INSIDE_THE_PART,
    "sphere": _INSIDE_THE_PART,
    "wedge": _INSIDE_THE_PART,
    "revolve": _INSIDE_THE_PART,
    "loft": _INSIDE_THE_PART,
    "sweep": _INSIDE_THE_PART,
    "twistExtrude": _INSIDE_THE_PART,
    "text": (
        "changed nothing: lettering is cut into the part unless combine=True, and a cut needs a negative distance from a face of the part; "
        "raised lettering takes combine=True and a positive distance. Check that the workplane is on the face the lettering belongs to."
    ),
    "split": "removed no material: the workplane does not cross the part, so nothing was cut off. Place the workplane through the part first.",
}

_HINTS = {
    "fillet": "the radius is probably too large for the selected edges, or no edge is selected",
    "chamfer": "the length is probably too large for the selected edges, or no edge is selected",
    "shell": "the wall is probably thicker than the part allows, or the selected face cannot be removed",
    "extrude": "there is no closed outline to extrude: draw one first and close() it",
    "cutBlind": "there is no closed outline to cut: draw one first",
    "cutThruAll": "there is no closed outline to cut: draw one first",
    "hole": "there is no point to drill at or no solid to drill into",
    "twistExtrude": "there is no closed outline to extrude: draw one first and close() it",
    "loft": "loft needs two or more closed outlines on separate workplanes, such as circle(10).workplane(offset=20).circle(5)",
    "sweep": "sweep needs a closed outline drawn before it, and the path must start on the profile's plane",
    "revolve": "the axis must not cross the outline: draw the outline wholly on one side of it",
    "split": "keepTop or keepBottom must be True, and the workplane must cross a solid",
}


class BuildFailed(Exception):
    """The kernel could not perform one operation of the script."""

    def __init__(self, line: int | None, operation: str, message: str):
        super().__init__(message)
        self.line = line
        self.operation = operation
        self.message = message


#: Operations that make or reshape a solid: a branch of a script that holds one did work on the part.
_SHAPING = frozenset(_MUST_CHANGE) | {"fillet", "chamfer", "translate", "rotate", "mirror"}


def _failed(operation, message: str) -> BuildFailed:
    """A failure of one operation; inside a loop, with the pass it happened in, since the line alone names them all."""
    if not operation.where:
        return BuildFailed(operation.line, operation.method, message)
    return BuildFailed(operation.line, operation.method, f"{message.replace(_REDUNDANT, _REDUNDANT_PASS)} (in {operation.where})")


def _state(part) -> tuple[float, int] | None:
    """Volume and face count of the solid a workplane stands for."""
    try:
        solid = part.findSolid()
    except Exception:
        return None  # no solid yet: an outline, or an empty workplane
    return solid.Volume(), len(solid.Faces())


def _check_effect(operation, before: tuple[float, int] | None, made, cq) -> None:
    """Refuse an operation that emptied the part or, where it had to change it, changed nothing."""
    # A cut or an intersection that leaves nothing puts an empty compound on the stack, and
    # looking for the solid then walks back to the part as it was before the operation.
    if any(isinstance(item, (cq.Solid, cq.Compound)) and not item.Solids() for item in made.objects):
        raise _failed(operation, f"{operation.method}() left no solid: nothing remains of the part after this operation")
    effect = _MUST_CHANGE.get(operation.method)
    if effect is None or before is None or dict(operation.arguments).get("combine") is False:
        return  # combine=False makes a body of its own: it is not meant to change this one
    after = _state(made)
    # The faces as well as the volume: a real cut of a millimetre in a part of metres is
    # below any tolerance on the volume, and it still adds faces.
    if after is not None and after[1] == before[1] and abs(after[0] - before[0]) <= 1e-12 * max(before[0], 1.0):
        raise _failed(operation, f"{operation.method}() {effect}")


def _used_by_result(program: Program) -> set[int]:
    """The operations the result is made of. A trial cut the part never uses is not held to account."""
    used: set[int] = set()
    pending = [program.result]
    while pending:
        slot = pending.pop()
        if slot in used:
            continue
        used.add(slot)
        operation = program.operations[slot]
        if operation.receiver is not None:
            pending.append(operation.receiver)
        pending.extend(value.slot for _, value in operation.arguments if isinstance(value, Ref))
    return used


def run_program(program: Program, cq):
    """Return the Workplane the script's result names. *cq* is the imported cadquery module."""
    return build_parts(program, cq)[program.result]


def build_parts(program: Program, cq) -> list:
    """Perform every operation of the script; the part each one made, by its position."""
    parts: list = []
    used = _used_by_result(program)
    for slot, operation in enumerate(program.operations):
        arguments = {name: _argument(value, parts, cq) for name, value in operation.arguments}
        try:
            if operation.method in INJECTED:
                arguments.update(_injected(operation))
            if operation.receiver is None:
                parts.append(cq.Workplane(**arguments))
            elif operation.method in table.METHODS:
                receiver = parts[operation.receiver]
                before = _state(receiver) if slot in used and operation.method in _MUST_CHANGE else None
                # The one attribute lookup driven by a script, and only for a name in the table.
                made = getattr(receiver, operation.method)(**arguments)
                if slot in used:
                    _check_effect(operation, before, made, cq)
                parts.append(made)
            else:
                raise _failed(operation, "this operation is not on the allow-list")
        except BuildFailed:
            raise
        except MemoryError:
            raise _failed(operation, "the kernel ran out of memory on this operation") from None
        except Exception as exc:
            detail = " ".join(str(exc).split())[:300] or type(exc).__name__
            hint = _HINTS.get(operation.method)
            raise _failed(operation, f"{operation.method}() failed: {detail}" + (f". Likely cause: {hint}." if hint else "")) from None
    return parts


def _argument(value, parts: list, cq):
    """An argument as the kernel takes it: a part by its position, a helix as its wire, plain data as it is."""
    if isinstance(value, Ref):
        return parts[value.slot]
    if isinstance(value, Helix):
        return cq.Wire.makeHelix(value.pitch, value.height, value.radius, lefthand=value.lefthand)
    return value


def _injected(operation) -> dict[str, str]:
    """The module's own arguments for *operation*: today the font of text()."""
    if not FONT.is_file():
        # The kernel would fall back to some system font, or to none, without saying so.
        raise _failed(operation, f"{operation.method}() cannot letter: the module's font file is missing. Reinstall the CAD module.")
    return {"fontPath": str(FONT)}


def _holds_solid(part) -> bool:
    """Whether a workplane stands for a solid. Looked up, not measured: measuring every spare body took seconds."""
    try:
        part.findSolid()
    except Exception:
        return False
    return True


def left_out(program: Program, parts: list) -> tuple[list[int], dict[int, int]]:
    """What a script built and left out of its result: whole bodies, and passes of a loop.

    Returns the line each left-out body starts on, one entry per body, and for each
    loop, by its line, how many of its passes did work on the part that did not reach
    the result. Both are the usual slips in a loop: each pass builds a body and the
    last one alone is the result, or each pass starts from the same part, so only the
    last pass's work is kept.

    Not counted, because nothing is missing from the part:
    - an outline or a selection, which is no work, and a branch off the result
      outside a loop, which is a trial;
    - a tool made ready for a pass that never came (a cutter moved on after its last
      cut): left over in the last pass, where the same call's outcome was used in
      every pass before;
    - a part put together again in every pass (result = body.union(lid) inside the
      loop): dropped in the earlier passes, where the same call's outcome in the
      last pass is in the result and stands on what that pass carried.
    """
    operations = program.operations
    used = _used_by_result(program)
    consumed = {operation.receiver for operation in operations if operation.receiver is not None}
    consumed.update(value.slot for operation in operations for _, value in operation.arguments if isinstance(value, Ref))
    #: The passes of each call, by the run of its innermost loop: {(call, passes around that loop): {pass number: operation}}.
    runs: dict[tuple, dict[int, int]] = {}
    for slot, operation in enumerate(operations):
        if operation.passes:
            runs.setdefault((operation.site, operation.passes[:-1], operation.loop), {})[operation.passes[-1][1]] = slot

    def same_call(slot: int) -> dict[int, int]:
        operation = operations[slot]
        return runs[(operation.site, operation.passes[:-1], operation.loop)]

    def made_ready(slot: int) -> bool:
        earlier = [other for number, other in same_call(slot).items() if number < operations[slot].passes[-1][1]]
        return operations[slot].last and bool(earlier) and all(other in used for other in earlier)

    def put_together_again(slot: int, ancestor: int) -> bool:
        final = max(same_call(slot).items())[1]
        return not operations[slot].last and final in used and operations[ancestor].passes == operations[slot].passes

    bodies: dict[int, int] = {}
    passes: dict[int, set[tuple]] = {}
    for slot, operation in enumerate(operations):
        if slot in used or slot in consumed:
            continue
        chain = [slot]
        ancestor = operation.receiver
        # A workplane the result also started from is not the part until it holds a solid.
        while ancestor is not None and not (ancestor in used and _holds_solid(parts[ancestor])):
            chain.append(ancestor)
            ancestor = operations[ancestor].receiver
        if ancestor is None:
            # A body of its own, however many selections were made on it: counted once, where it starts.
            start = next((index for index in reversed(chain) if index not in used), chain[-1])
            if start not in bodies and _holds_solid(parts[slot]) and not (operation.passes and made_ready(slot)):
                bodies[start] = operations[start].line
        elif operation.passes and not made_ready(slot) and not put_together_again(slot, ancestor):
            # Every pass the dropped chain did work in, not only the one it ends in.
            worked = {operations[index].passes for index in chain if operations[index].loop == operation.loop and operations[index].method in _SHAPING}
            if worked:
                passes.setdefault(operation.loop, set()).update(worked | {operation.passes})
    return sorted(bodies.values()), {loop: len(dropped) for loop, dropped in sorted(passes.items())}


def solid_of(part):
    """The solid a script's result stands for, even when its last call selected a face or drew an outline."""
    try:
        return part.findSolid()
    except Exception:
        raise BuildFailed(None, "result", "the script's result contains no solid: finish it with an operation that makes one, such as extrude()") from None


def unused_outline(part) -> bool:
    """True when the script drew an outline it never extruded or cut."""
    return bool(part.ctx.pendingWires or part.ctx.pendingEdges)


def whole_stl(path: Path) -> bool:
    """True when a binary STL holds as many triangles as its header says.

    The kernel's writer does not report a write the operating system cut short.
    """
    if not path.is_file() or path.stat().st_size < 84:
        return False
    with path.open("rb") as handle:
        triangles = int.from_bytes(handle.read(84)[80:], "little")
    return 84 + 50 * triangles == path.stat().st_size


def _fits(path: Path, kind: str, max_bytes: int) -> None:
    if not path.is_file() or path.stat().st_size > max_bytes:
        limit = f"{max_bytes // (1024 * 1024)} MiB" if max_bytes >= 1024 * 1024 else f"{max_bytes // 1024} KiB"
        raise BuildFailed(None, "export", f"the {kind} file is larger than {limit}. Simplify the part: fewer small fillets and holes.")


#: glTF lengths are metres and the kernel writes the GLB in millimetres: its scene is scaled by this.
GLB_SCALE = 0.001
_GLB_MAGIC, _GLB_JSON = 0x46546C67, 0x4E4F534A


def in_metres(glb: bytes) -> bytes:
    """The GLB with each root node of its scenes scaled from millimetres to metres.

    The vertices stay as the kernel wrote them; only the scene's root transform changes, so a
    viewer, Blender or a phone's AR view opens a 40 mm part at 40 mm instead of 40 m. The JSON
    chunk is padded back to four bytes, as the format requires.
    """
    magic, version, _ = struct.unpack_from("<III", glb, 0)
    length, kind = struct.unpack_from("<II", glb, 12)
    if magic != _GLB_MAGIC or kind != _GLB_JSON:
        raise ValueError("not a binary glTF file")
    document = json.loads(glb[20 : 20 + length])
    roots = {index for scene in document.get("scenes", []) for index in scene.get("nodes", [])}
    for index in sorted(roots):
        node = document["nodes"][index]
        if "matrix" in node:
            # Column-major: scaling the result scales the first three rows of every column, translation included.
            node["matrix"] = [value * GLB_SCALE if position % 4 != 3 else value for position, value in enumerate(node["matrix"])]
            continue
        node["scale"] = [value * GLB_SCALE for value in node.get("scale", [1.0, 1.0, 1.0])]
        if "translation" in node:
            node["translation"] = [value * GLB_SCALE for value in node["translation"]]
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    body = struct.pack("<II", len(text), _GLB_JSON) + text + glb[20 + length :]
    return struct.pack("<III", magic, version, 12 + len(body)) + body


#: Bodies laid out to print apart stand on the bed side by side along x, this far from each other.
PARTS_GAP_MM = 5.0
#: Per-body STL files written when the laid-out 3MF cannot be: a kit, not a pile.
MAX_BODY_FILES = 8
_MESH_OBJECT = re.compile(r'<object id="(\d+)"[^>]*>\s*<mesh>(.*?)</mesh>\s*</object>', re.S)
_COMPONENTS_OBJECT = re.compile(r'<object id="\d+"[^>]*>\s*<components>.*?</components>\s*</object>', re.S)
_VERTEX = re.compile(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"')
_BUILD = re.compile(r"<build>.*?</build>", re.S)


def lay_out(threemf: bytes, gap_mm: float = PARTS_GAP_MM) -> bytes:
    """The kernel's 3MF with each body as its own build item, dropped to z = 0 and set beside the one before.

    The kernel writes one item made of all bodies, which is right for printing them in place. For a
    kit printed apart, each body's mesh becomes an item of its own, moved (never turned) so its lowest
    point is on the bed and its box starts *gap_mm* past the box before it along x.
    """
    with zipfile.ZipFile(io.BytesIO(threemf)) as package:
        entries = [(info, package.read(info)) for info in package.infolist()]
    (model,) = [content.decode("utf-8") for info, content in entries if info.filename == "3D/3dmodel.model"]
    meshes = _MESH_OBJECT.findall(model)
    if len(meshes) < 2:
        raise ValueError(f"the 3MF holds {len(meshes)} body meshes; laying out needs two or more")
    items, cursor = [], 0.0
    for identifier, mesh in meshes:
        points = [tuple(map(float, found)) for found in _VERTEX.findall(mesh)]
        if not points:
            raise ValueError(f"body mesh {identifier} has no vertices")
        low = [min(point[k] for point in points) for k in range(3)]
        high = [max(point[k] for point in points) for k in range(3)]
        # Rounded, and + 0.0 so that no "-0.000000" reaches a slicer.
        move = " ".join(f"{round(value, 6) + 0.0:.6f}" for value in (cursor - low[0], -low[1], -low[2]))
        items.append(f'<item objectid="{identifier}" transform="1 0 0 0 1 0 0 0 1 {move}" />')
        cursor += high[0] - low[0] + gap_mm
    model, assemblies = _COMPONENTS_OBJECT.subn("", model)
    model, builds = _BUILD.subn("<build>" + "".join(items) + "</build>", model)
    if builds != 1:
        raise ValueError("the 3MF has no single build element to rewrite")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for info, content in entries:
            package.writestr(info.filename, model.encode("utf-8") if info.filename == "3D/3dmodel.model" else content)
    return out.getvalue()


def _bodies_apart(shape, threemf: Path, directory: Path, names: dict[str, str], linear: float, angular: float, max_bytes: int) -> None:
    """Write part.parts.3mf for printing the bodies apart; failing that, one STL per body, at most MAX_BODY_FILES.

    Neither is the checked part, so neither can fail the build: when both fail, no laid-out file is
    named, and the worker says so.
    """
    parts = directory / "part.parts.3mf"
    try:
        parts.write_bytes(lay_out(threemf.read_bytes()))
        _fits(parts, "laid-out 3MF", max_bytes)
    except (ValueError, OSError, zipfile.BadZipFile, BuildFailed):
        parts.unlink(missing_ok=True)
    else:
        names["parts.3mf"] = parts.name
        return
    bodies = {}
    for number, solid in enumerate(shape.Solids()[:MAX_BODY_FILES], 1):
        body = directory / f"part.body-{number}.stl"
        try:
            written = solid.exportStl(str(body), tolerance=linear, angularTolerance=angular, ascii=False, relative=False)
        except Exception:
            written = False
        if not (written and whole_stl(body) and body.stat().st_size <= max_bytes):
            for name in [*bodies.values(), body.name]:
                (directory / name).unlink(missing_ok=True)
            return
        bodies[f"body-{number}.stl"] = body.name
    names.update(bodies)


def export(shape, cq, directory: Path, max_bytes: int) -> tuple[dict[str, str], dict[str, float]]:
    """Write STEP, STL, 3MF and GLB of *shape* into *directory*.

    Returns the file names by kind and the mesh tolerance that was used. STEP, STL and 3MF are
    in millimetres; the GLB is in metres, the unit of glTF. A shape of several bodies also gets
    ``part.parts.3mf``, the bodies laid out to print apart (or one STL per body), and a GLB with
    one node per body.
    """
    from OCP.BRepTools import BRepTools

    names = {"step": "part.step", "stl": "part.stl", "3mf": "part.3mf", "glb": "part.glb"}
    step, stl, threemf, glb = (directory / names[kind] for kind in ("step", "stl", "3mf", "glb"))
    cq.exporters.export(shape, str(step))
    _fits(step, "STEP", max_bytes)
    scale = max(1.0, shape.BoundingBox().DiagonalLength / MESH_FULL_DETAIL_MM)
    for step_linear, angular in MESH_STEPS:
        linear = round(step_linear * scale, 4)
        # The kernel keeps a mesh on the shape and would reuse the finer one.
        BRepTools.Clean_s(shape.wrapped)
        # exportStl with relative=False: exporters.export reads the tolerance as a fraction of each edge.
        written = shape.exportStl(str(stl), tolerance=linear, angularTolerance=angular, ascii=False, relative=False)
        if written and whole_stl(stl) and stl.stat().st_size <= MESH_TARGET_BYTES:
            break
    if not whole_stl(stl):
        raise BuildFailed(None, "export", "the STL mesh could not be written in full, even at the coarsest tolerance. Simplify the part: fewer small fillets and holes.")
    _fits(stl, "STL", max_bytes)
    # The slicer's file: in millimetres, from the mesh the STL was just written with (the kernel keeps it on the shape).
    cq.exporters.export(shape, str(threemf), tolerance=linear, angularTolerance=angular)
    _fits(threemf, "3MF", max_bytes)
    solids = shape.Solids()
    if len(solids) > 1:
        _bodies_apart(shape, threemf, directory, names, linear, angular, max_bytes)
        # One node per body, so a viewer can show and pick them apart.
        assembly = cq.Assembly(name="part")
        for number, solid in enumerate(solids, 1):
            assembly.add(solid, name=f"body-{number}")
    else:
        assembly = cq.Assembly(shape, name="part")
    assembly.export(str(glb), tolerance=linear, angularTolerance=angular)
    _fits(glb, "GLB", max_bytes)
    glb.write_bytes(in_metres(glb.read_bytes()))
    _fits(glb, "GLB", max_bytes)
    return names, {"tolerance_mm": linear, "angular_rad": angular}
