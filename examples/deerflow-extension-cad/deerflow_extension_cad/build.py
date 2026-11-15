"""Perform a compiled program against the kernel and export the part.

This module is the only place a script's request turns into a kernel call, and
the call is always the same shape: a ``Workplane`` method whose name is a key
of ``allowlist.METHODS``, with keyword arguments the interpreter already
checked. It runs in the worker process only; the Gateway never imports it.
"""

from __future__ import annotations

from pathlib import Path

from deerflow_extension_cad import allowlist as table
from deerflow_extension_cad.interpreter import Program, Ref

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
_OFF_THE_PART = "removed no material: it is off the part, or the material there is already gone." + _REDUNDANT
_INSIDE_THE_PART = "added no material: the new body lies inside the part, so check its position and direction." + _REDUNDANT
_MUST_CHANGE = {
    "cutBlind": "removed no material: a positive distance cuts away from the part, so use a negative distance to cut into it, and check that the outline lies on the part." + _REDUNDANT,
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
}

_HINTS = {
    "fillet": "the radius is probably too large for the selected edges, or no edge is selected",
    "chamfer": "the length is probably too large for the selected edges, or no edge is selected",
    "shell": "the wall is probably thicker than the part allows, or the selected face cannot be removed",
    "extrude": "there is no closed outline to extrude: draw one first and close() it",
    "cutBlind": "there is no closed outline to cut: draw one first",
    "cutThruAll": "there is no closed outline to cut: draw one first",
    "hole": "there is no point to drill at or no solid to drill into",
}


class BuildFailed(Exception):
    """The kernel could not perform one operation of the script."""

    def __init__(self, line: int | None, operation: str, message: str):
        super().__init__(message)
        self.line = line
        self.operation = operation
        self.message = message


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
        raise BuildFailed(operation.line, operation.method, f"{operation.method}() left no solid: nothing remains of the part after this operation")
    effect = _MUST_CHANGE.get(operation.method)
    if effect is None or before is None or dict(operation.arguments).get("combine") is False:
        return  # combine=False makes a body of its own: it is not meant to change this one
    after = _state(made)
    # The faces as well as the volume: a real cut of a millimetre in a part of metres is
    # below any tolerance on the volume, and it still adds faces.
    if after is not None and after[1] == before[1] and abs(after[0] - before[0]) <= 1e-12 * max(before[0], 1.0):
        raise BuildFailed(operation.line, operation.method, f"{operation.method}() {effect}")


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
    parts: list = []
    used = _used_by_result(program)
    for slot, operation in enumerate(program.operations):
        arguments = {name: parts[value.slot] if isinstance(value, Ref) else value for name, value in operation.arguments}
        try:
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
                raise BuildFailed(operation.line, operation.method, "this operation is not on the allow-list")
        except BuildFailed:
            raise
        except MemoryError:
            raise BuildFailed(operation.line, operation.method, "the kernel ran out of memory on this operation") from None
        except Exception as exc:
            detail = " ".join(str(exc).split())[:300] or type(exc).__name__
            hint = _HINTS.get(operation.method)
            raise BuildFailed(operation.line, operation.method, f"{operation.method}() failed: {detail}" + (f". Likely cause: {hint}." if hint else "")) from None
    return parts[program.result]


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


def export(shape, cq, directory: Path, max_bytes: int) -> tuple[dict[str, str], dict[str, float]]:
    """Write STEP, STL and GLB of *shape* into *directory*.

    Returns the file names by kind and the mesh tolerance that was used.
    """
    from OCP.BRepTools import BRepTools

    names = {"step": "part.step", "stl": "part.stl", "glb": "part.glb"}
    step, stl, glb = (directory / names[kind] for kind in ("step", "stl", "glb"))
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
    cq.Assembly(shape, name="part").export(str(glb), tolerance=linear, angularTolerance=angular)
    _fits(glb, "GLB", max_bytes)
    return names, {"tolerance_mm": linear, "angular_rad": angular}
