"""How a part would print, read off the STL the tool wrote.

The checks are pure functions over the mesh: no kernel, no configuration. The
printer's numbers are arguments, so a test states the printer it assumes. The
parts that need real tessellation are built with the kernel and meshed the way
``build.export`` meshes them; those cases skip without it.
"""

from __future__ import annotations

import ast
import math
import struct
import time
from pathlib import Path

import numpy as np
import pytest

from deerflow_extension_cad import printability

PRINTER = {"overhang_deg": 45.0, "build_volume_mm": None, "density_g_cm3": 1.24}


def box(low, high) -> np.ndarray:
    """Twelve triangles of an axis-aligned box, wound outward."""
    (x0, y0, z0), (x1, y1, z1) = low, high
    corners = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)
    # (a, b, c, d) counter-clockwise seen from outside, by corner index x*4 + y*2 + z.
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([corners[[a, b, c]] for a, b, c, d in quads] + [corners[[a, c, d]] for a, b, c, d in quads])


def stl(triangles: np.ndarray) -> bytes:
    """A binary STL of *triangles*, as the kernel writes one."""
    records = np.zeros(len(triangles), dtype=[("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    records["vertices"] = triangles
    return b"\0" * 80 + struct.pack("<I", len(triangles)) + records.tobytes()


def kernel_triangles(make, tmp_path: Path) -> np.ndarray:
    """Build with the kernel, mesh the way export() does, and read the STL back."""
    cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")
    from deerflow_extension_cad import build

    path = tmp_path / "part.stl"
    tolerance, angular = build.MESH_STEPS[0]
    assert make(cq).findSolid().exportStl(str(path), tolerance=tolerance, angularTolerance=angular, ascii=False, relative=False)
    return printability.read_stl(path.read_bytes())


def tee(cq):
    # A 10 x 10 stem 20 tall standing on the bed, under a 40 x 10 cap: 300 mm2 of cap hangs in the air.
    return cq.Workplane("XY").box(10, 10, 20, centered=(True, True, False)).faces(">Z").workplane().rect(40, 10).extrude(4)


def shell(cq):
    # An open box with 1 mm walls and rounded corners: the wall is 1 mm everywhere, round the corners too.
    return cq.Workplane("XY").box(60, 40, 30).edges("|Z").fillet(3).faces(">Z").shell(-1)


HOLES = [(x * 6 - 27, y * 6 - 27) for x in range(10) for y in range(10)]


def enclosure(cq):
    # 100 holes through the floor of a shelled box: the dense part the timing budget is set on.
    return cq.Workplane("XY").box(70, 70, 20).edges("|Z").fillet(4).faces(">Z").shell(-2).faces("<Z").workplane(origin=(0, 0, 0)).pushPoints(HOLES).hole(3)


def plate_on_edge(cq):
    # A 60 x 40 x 6 plate with two 4 mm holes, built standing on a long edge: the holes lie sideways.
    return cq.Workplane("XZ").box(60, 40, 6).faces("<Y").workplane().pushPoints([(-15, 0), (15, 0)]).hole(4)


def test_the_stl_is_read_as_the_kernel_wrote_it():
    triangles = box((0, 0, 0), (10, 20, 30))
    read = printability.read_stl(stl(triangles))
    assert read.shape == (12, 3, 3) and read.dtype == np.float64
    assert np.array_equal(read, triangles)
    assert printability.mesh_volume_mm3(read) == pytest.approx(6000)


@pytest.mark.parametrize(
    "data, reason",
    [
        (b"", "binary STL"),
        (stl(box((0, 0, 0), (1, 1, 1)))[:-1], "binary STL"),
        (b"solid part\nfacet normal 0 0 1\n" + b" " * 80 + b"endsolid part\n", "binary STL"),
        (stl(np.zeros((0, 3, 3))), "no triangles"),
        (stl(box((0, 0, 0), (1, 1, math.nan))), "finite"),
    ],
    ids=["empty", "cut short", "ascii", "no triangles", "not a number"],
)
def test_a_file_that_is_not_a_whole_binary_stl_is_refused(data, reason):
    with pytest.raises(ValueError, match=reason):
        printability.read_stl(data)


def test_a_box_lies_flat_holds_water_overhangs_nothing_and_weighs_its_volume():
    triangles = box((0, 0, 5), (10, 10, 15))  # floating 5 mm up: the slicer drops it onto the bed
    assert printability.bed_contact_mm2(triangles) == pytest.approx(100)
    assert printability.overhang_mm2(triangles, 45) == 0
    assert printability.open_edges(triangles) == 0
    block = printability.assess(triangles, **PRINTER)
    assert block["watertight"] is True and block["grams"] == pytest.approx(1.24)  # 1 cm3 of PLA
    assert "fits_build_volume" not in block and "better_face_down" not in block
    assert printability.notes(block, nozzle_mm=0.4) == []


def test_a_mesh_with_a_missing_triangle_is_not_watertight_and_says_so():
    triangles = box((0, 0, 0), (10, 10, 10))[:-1]
    assert printability.open_edges(triangles) == 3
    block = printability.assess(triangles, **PRINTER)
    assert block["watertight"] is False and block["open_edges"] == 3
    assert any("not watertight" in note and "3 edges" in note for note in printability.notes(block, nozzle_mm=0.4))


def facing(direction, at=(0, 0, 0), leg=math.sqrt(20)) -> np.ndarray:
    """One triangle of 10 mm2 whose outward normal is *direction*, with a corner at *at*."""
    normal = np.array(direction, dtype=float)
    across = np.roll(np.abs(normal), 1) if np.count_nonzero(normal) == 1 else np.cross(normal, (0, 0, 1))
    across /= np.linalg.norm(across)
    corner = np.array(at, dtype=float)
    return np.array([corner, corner + leg * across, corner + leg * np.cross(normal / np.linalg.norm(normal), across)])


def test_the_overhang_angle_is_the_printers():
    # A roof leaning 50 degrees from vertical, over a floor on the bed: past 45 degrees, within 60.
    slope = math.radians(50)
    roof = facing((math.cos(slope), 0, -math.sin(slope)), at=(0, 0, 10))
    floor = facing((0, 0, -1))
    triangles = np.array([floor, roof])
    assert printability.unit_normals(triangles)[1] == pytest.approx([math.cos(slope), 0, -math.sin(slope)])
    assert printability.bed_contact_mm2(triangles) == pytest.approx(10)
    assert printability.overhang_mm2(triangles, 45) == pytest.approx(10)
    assert printability.overhang_mm2(triangles, 60) == 0


def test_a_tee_overhangs_its_cap_and_stands_on_its_stem(tmp_path):
    triangles = kernel_triangles(tee, tmp_path)
    assert printability.overhang_mm2(triangles, 45) == pytest.approx(300, abs=1)
    assert printability.bed_contact_mm2(triangles) == pytest.approx(100, abs=1)
    block = printability.assess(triangles, **PRINTER)
    assert block["overhang_mm2"] == pytest.approx(300, abs=1) and block["bed_contact_mm2"] == pytest.approx(100, abs=1)
    assert block["watertight"] is True
    # Upside down it stands on its cap and overhangs nothing.
    assert block["better_face_down"] == {"face": "+Z", "overhang_mm2": 0.0}
    [note] = printability.notes(block, nozzle_mm=0.4)
    assert "300" in note and "support" in note and "+Z" in note


def test_a_one_millimetre_shell_reads_one_millimetre(tmp_path):
    triangles = kernel_triangles(shell, tmp_path)
    assert printability.thinnest_wall_mm(triangles) == pytest.approx(1.0, abs=0.05)
    block = printability.assess(triangles, **PRINTER)
    assert block["thinnest_wall_mm"] == pytest.approx(1.0, abs=0.05) and block["watertight"] is True
    # Two nozzle widths of 0.4 mm is 0.8 mm: the wall is fine. With a 0.6 mm nozzle it is not.
    assert not any("wall" in note for note in printability.notes(block, nozzle_mm=0.4))
    assert any("wall" in note and "1.2 mm" in note for note in printability.notes(block, nozzle_mm=0.6))


def test_the_wall_estimate_holds_far_from_the_origin_and_on_a_part_of_metres():
    # The rays are weighed against the triangles in single precision; the margin must keep every true hit.
    plate = box((0, 0, 0), (40, 30, 1.5))
    assert printability.thinnest_wall_mm(plate) == pytest.approx(1.5, abs=1e-6)
    assert printability.thinnest_wall_mm(plate + 5000.0) == pytest.approx(1.5, abs=1e-4)
    assert printability.thinnest_wall_mm(box((0, 0, 0), (2000, 1500, 3))) == pytest.approx(3, abs=1e-3)


def test_a_wall_given_by_the_caller_is_used_instead_of_sampling():
    block = printability.assess(box((0, 0, 0), (10, 10, 10)), **PRINTER, wall_mm=0.5)
    assert block["thinnest_wall_mm"] == 0.5
    assert any("0.5 mm" in note and "0.8 mm" in note for note in printability.notes(block, nozzle_mm=0.4))


def test_a_part_larger_than_the_bed_gets_the_fit_note():
    triangles = box((0, 0, 0), (300, 20, 10))
    block = printability.assess(triangles, **{**PRINTER, "build_volume_mm": [256, 256, 256]})
    assert block["fits_build_volume"] is False and block["too_large_axes"] == ["X"]
    [note] = printability.notes(block, nozzle_mm=0.4)
    assert "larger than the build volume" in note and "256 × 256 × 256 mm" in note and "X" in note
    # The same part fits a bed it can be turned on, and a bed it fits is not mentioned.
    turned = printability.assess(box((0, 0, 0), (250, 300, 10)), **{**PRINTER, "build_volume_mm": [256, 320, 100]})
    assert turned["fits_build_volume"] is True and printability.notes(turned, nozzle_mm=0.4) == []
    assert printability.fit([300, 250, 10], [256, 320, 100]) == {"fits_build_volume": False, "too_large_axes": ["X"], "fits_turned": True}


def test_bodies_printed_apart_are_each_judged_standing_on_the_bed():
    # A 40 mm part split into two 20 mm halves for a 30 mm bed. As one mesh it is too tall, its halves'
    # shared corners are edges of four triangles and the upper half's underside hangs: three notes the
    # split was meant to answer. Laid apart (part.parts.3mf), each half is closed, fits and stands flat.
    bed = {**PRINTER, "build_volume_mm": [100, 100, 30]}
    lower, upper = box((0, 0, 0), (20, 20, 20)), box((0, 0, 20), (20, 20, 40))
    together = printability.assess(np.concatenate([lower, upper]), **bed)
    assert (together["fits_build_volume"], together["watertight"], together["overhang_mm2"]) == (False, False, 400.0)
    apart = printability.assess_apart([lower, upper], **bed, volume_mm3=16000.0)
    assert apart["printed_apart"] is True and apart["fits_build_volume"] is True and apart["watertight"] is True
    assert (apart["overhang_mm2"], apart["bed_contact_mm2"], apart["grams"], apart["thinnest_wall_mm"]) == (0.0, 800.0, 19.84, 20.0)
    assert [body["fits_build_volume"] for body in apart["bodies"]] == [True, True]
    # Too tall together and not apart: said once, in words that do not send the model to split it again.
    (note,) = printability.notes(apart, nozzle_mm=0.4)
    assert note == "as modelled the bodies do not fit the build volume together (100 × 100 × 30 mm) in Z; printed apart, as the .parts.3mf lays them out, each one does"
    assert "larger than the build volume" not in note
    # A body that does not fit on its own is named with its number; the bodies together are not said again.
    tall = printability.assess_apart([lower, box((40, 0, 0), (60, 20, 50))], **bed)
    assert tall["fits_build_volume"] is False and tall["too_large_axes"] == ["Z"] and tall["fits_turned"] is False
    assert printability.notes(tall, nozzle_mm=0.4) == ["body 2: larger than the build volume (100 × 100 × 30 mm) in Z"]
    # The same sentence for several bodies is one note that names them all.
    posts = [box((x, 0, 0), (x + 10, 10, 50)) for x in (0, 20, 40)]
    assert printability.notes(printability.assess_apart(posts, **bed), nozzle_mm=0.4) == ["bodies 1, 2 and 3: larger than the build volume (100 × 100 × 30 mm) in Z"]
    assert printability.notes(printability.assess_apart(posts[:2], **bed), nozzle_mm=0.4)[0].startswith("bodies 1 and 2: ")


def test_a_mesh_given_as_vertices_and_triangles_is_read_as_triangles():
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    triangles = printability.mesh_triangles(vertices, [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])
    assert triangles.shape == (4, 3, 3) and printability.open_edges(triangles) == 0
    for bad in ([(0, 1, 4)], [], [(0, 1)]):
        with pytest.raises(ValueError):
            printability.mesh_triangles(vertices, bad)
    with pytest.raises(ValueError):
        printability.mesh_triangles([(0, 0, float("nan")), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)])


def test_a_plate_built_standing_on_edge_is_told_to_lie_flat(tmp_path):
    triangles = kernel_triangles(plate_on_edge, tmp_path)
    sizes = np.ptp(triangles.reshape(-1, 3), axis=0)
    assert sizes == pytest.approx([60, 6, 40], abs=1e-3)  # standing: 6 mm deep, 40 mm tall
    block = printability.assess(triangles, **PRINTER)
    assert block["overhang_mm2"] > printability.OVERHANG_NOTE_MM2  # the tops of the sideways holes
    assert block["better_face_down"]["face"] in ("-Y", "+Y") and block["better_face_down"]["overhang_mm2"] == 0.0
    [note] = printability.notes(block, nozzle_mm=0.4)
    assert block["better_face_down"]["face"] in note


def test_a_better_face_down_is_named_only_when_it_halves_the_overhang():
    # One 10 mm2 face toward each of the six directions, held off the bed by corners whose faces never overhang:
    # whichever side goes down, one face hangs, so no side is better.
    axes = [(0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0)]
    corners = [facing((x, y, z), at=(50 * x, 50 * y, 50 * z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    sides = [facing(axis, at=np.multiply(axis, 5)) for axis in axes]
    triangles = np.array(corners + sides)
    assert printability.overhang_mm2(triangles, 45) == pytest.approx(10)
    assert printability.better_face_down(triangles, 45) is None
    # Without the face toward +Z, turning the part over leaves nothing hanging.
    triangles = np.array(corners + sides[:1] + sides[2:])
    assert printability.better_face_down(triangles, 45) == {"face": "+Z", "overhang_mm2": 0.0}
    assert printability.better_face_down(box((0, 0, 0), (10, 10, 10)), 45) is None


def test_a_part_with_nothing_flat_on_the_bed_says_so():
    # An octahedron balanced on its tip.
    tip = [(0, 0, 0)]
    ring = [(5, 0, 5), (0, 5, 5), (-5, 0, 5), (0, -5, 5)]
    top = [(0, 0, 10)]
    faces = [(tip[0], ring[(i + 1) % 4], ring[i]) for i in range(4)] + [(top[0], ring[i], ring[(i + 1) % 4]) for i in range(4)]
    triangles = np.array(faces, dtype=float)
    assert printability.open_edges(triangles) == 0 and printability.mesh_volume_mm3(triangles) > 0
    block = printability.assess(triangles, **PRINTER)
    assert block["bed_contact_mm2"] == 0
    assert any("flat" in note and "bed" in note for note in printability.notes(block, nozzle_mm=0.4))


def test_the_print_block_is_the_same_every_time(tmp_path):
    triangles = kernel_triangles(tee, tmp_path)
    assert printability.assess(triangles, **PRINTER) == printability.assess(triangles.copy(), **PRINTER)


def test_the_enclosure_is_checked_well_within_its_budget(tmp_path):
    # Budget: under 1 s (roadmap item 54). It measures 0.12 s here (median of 7, slowest 0.13 s) and about
    # 0.2 s with other builds loading the machine, so a runner five times slower than that still passes.
    triangles = kernel_triangles(enclosure, tmp_path)
    assert len(triangles) > 15_000
    started = time.perf_counter()
    block = printability.assess(triangles, **{**PRINTER, "build_volume_mm": [256, 256, 256]})
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, elapsed
    assert block["watertight"] is True and block["fits_build_volume"] is True
    assert block["thinnest_wall_mm"] == pytest.approx(2.0, abs=0.1)


def test_the_module_reads_no_configuration_and_imports_neither_tool_nor_worker():
    tree = ast.parse(Path(printability.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    modules = {(alias.name if isinstance(node, ast.Import) else node.module).split(".")[0] for node in imports for alias in node.names}
    assert modules <= {"__future__", "collections", "math", "numpy"}, modules
