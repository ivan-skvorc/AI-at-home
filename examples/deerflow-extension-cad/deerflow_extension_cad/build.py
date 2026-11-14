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

#: The STL and GLB meshes: at most 0.1 mm off the surface and 0.3 rad between facets. The
#: angle decides size and time; at 0.1 rad a hundred-hole enclosure takes seconds and 860 MiB.
MESH_TOLERANCE_MM = 0.1
MESH_ANGULAR_TOLERANCE = 0.3

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


def run_program(program: Program, cq):
    """Return the Workplane the script's result names. *cq* is the imported cadquery module."""
    parts: list = []
    for operation in program.operations:
        arguments = {name: parts[value.slot] if isinstance(value, Ref) else value for name, value in operation.arguments}
        try:
            if operation.receiver is None:
                parts.append(cq.Workplane(**arguments))
            elif operation.method in table.METHODS:
                # The one attribute lookup driven by a script, and only for a name in the table.
                parts.append(getattr(parts[operation.receiver], operation.method)(**arguments))
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


def export(shape, cq, directory: Path) -> dict[str, str]:
    """Write STEP, STL and GLB of *shape* into *directory* and return their file names by kind."""
    names = {"step": "part.step", "stl": "part.stl", "glb": "part.glb"}
    cq.exporters.export(shape, str(directory / names["step"]))
    # exportStl with relative=False: exporters.export reads the tolerance as a fraction of each edge.
    shape.exportStl(str(directory / names["stl"]), tolerance=MESH_TOLERANCE_MM, angularTolerance=MESH_ANGULAR_TOLERANCE, ascii=False, relative=False)
    cq.Assembly(shape, name="part").export(str(directory / names["glb"]), tolerance=MESH_TOLERANCE_MM, angularTolerance=MESH_ANGULAR_TOLERANCE)
    return names
