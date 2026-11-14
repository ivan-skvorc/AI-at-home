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
_MUST_CHANGE = {
    "cutBlind": "removed no material: a positive distance cuts away from the part, so use a negative distance to cut into it, and check that the outline lies on the part",
    "cutThruAll": "removed no material: the outline is probably off the part",
    "hole": "removed no material: the point is probably off the part",
    "cboreHole": "removed no material: the point is probably off the part",
    "cskHole": "removed no material: the point is probably off the part",
    "cut": "removed no material: the two parts do not overlap",
    "intersect": "changed nothing: the other part contains this one",
    "shell": "changed nothing: the wall is probably thicker than the part allows",
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


def _volume(part) -> float | None:
    try:
        return part.findSolid().Volume()
    except Exception:
        return None  # no solid yet: an outline, or an empty workplane


def _check_effect(operation, before: float | None, made, cq) -> None:
    """Refuse an operation that emptied the part or, where it had to change it, changed nothing."""
    # A cut or an intersection that leaves nothing puts an empty compound on the stack, and
    # looking for the solid then walks back to the part as it was before the operation.
    if any(isinstance(item, (cq.Solid, cq.Compound)) and not item.Solids() for item in made.objects):
        raise BuildFailed(operation.line, operation.method, f"{operation.method}() left no solid: nothing remains of the part after this operation")
    effect = _MUST_CHANGE.get(operation.method)
    if effect is None or before is None:
        return
    after = _volume(made)
    if after is not None and abs(after - before) <= 1e-12 * max(before, 1.0):
        raise BuildFailed(operation.line, operation.method, f"{operation.method}() {effect}")


def run_program(program: Program, cq):
    """Return the Workplane the script's result names. *cq* is the imported cadquery module."""
    parts: list = []
    for operation in program.operations:
        arguments = {name: parts[value.slot] if isinstance(value, Ref) else value for name, value in operation.arguments}
        try:
            if operation.receiver is None:
                parts.append(cq.Workplane(**arguments))
            elif operation.method in table.METHODS:
                receiver = parts[operation.receiver]
                before = _volume(receiver) if operation.method in _MUST_CHANGE else None
                # The one attribute lookup driven by a script, and only for a name in the table.
                made = getattr(receiver, operation.method)(**arguments)
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
