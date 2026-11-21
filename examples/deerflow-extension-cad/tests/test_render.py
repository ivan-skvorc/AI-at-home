"""The picture of a build: four views of the STL the tool wrote, with its measured size.

The renderer is numpy and Pillow over the STL bytes: no kernel, no OpenGL. The
parts that need real tessellation are built with the kernel and meshed the way
``build.export`` meshes them; those cases skip without it.
"""

from __future__ import annotations

import ast
import io
import json
import math
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from deerflow_extension_cad import printability, render


def box(low, high) -> np.ndarray:
    """Twelve triangles of an axis-aligned box, wound outward."""
    (x0, y0, z0), (x1, y1, z1) = low, high
    corners = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], dtype=float)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return np.array([corners[[a, b, c]] for a, b, c, d in quads] + [corners[[a, c, d]] for a, b, c, d in quads])


def stl(triangles: np.ndarray) -> bytes:
    records = np.zeros(len(triangles), dtype=[("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    records["vertices"] = triangles
    return b"\0" * 80 + struct.pack("<I", len(triangles)) + records.tobytes()


def kernel_stl(make, tmp_path: Path) -> bytes:
    """Build with the kernel and mesh the way export() does: the bytes the worker hands the renderer."""
    cq = pytest.importorskip("cadquery", reason="the CAD kernel is not installed")
    from deerflow_extension_cad import build

    path = tmp_path / "part.stl"
    tolerance, angular = build.MESH_STEPS[0]
    assert make(cq).findSolid().exportStl(str(path), tolerance=tolerance, angularTolerance=angular, ascii=False, relative=False)
    return path.read_bytes()


HOLES = [(x * 6 - 27, y * 6 - 27) for x in range(10) for y in range(10)]


def enclosure(cq):
    # 100 holes of 3 mm through the 2 mm floor of a shelled box, open at the top.
    return cq.Workplane("XY").box(70, 70, 20).edges("|Z").fillet(4).faces(">Z").shell(-2).faces("<Z").workplane(origin=(0, 0, 0)).pushPoints(HOLES).hole(3)


def plate_one_hole(cq):
    # The plate of test_build.py with one hole where two were asked for: a part that built and failed its checks.
    return cq.Workplane("XY").box(60, 40, 6).faces(">Z").workplane().pushPoints([(-15, 0)]).hole(4)


def decoded(png: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    assert image.width <= 960 and image.height <= 960
    assert len(png) <= 400 * 1024
    return np.asarray(image.convert("RGB"))


def is_background(pixels: np.ndarray) -> np.ndarray:
    return np.all(pixels == render.BACKGROUND, axis=-1)


def test_a_box_gives_a_small_png_of_four_views():
    png = render.render_views(stl(box((0, 0, 0), (60, 40, 6))), [60, 40, 6])
    pixels = decoded(png)
    assert pixels.shape == (960, 960, 3)
    sheet = render.layout(printability.read_stl(stl(box((0, 0, 0), (60, 40, 6)))), size=960, failed=False)
    assert [view.name for view in sheet.views] == ["iso", "top", "front", "right"]
    for view in sheet.views:
        left, top, right, bottom = view.rect
        assert not is_background(pixels[top:bottom, left:right]).all(), view.name  # every view shows the part


def test_the_enclosure_and_a_failed_build_give_small_pngs(tmp_path):
    for make, failed in ((enclosure, None), (plate_one_hole, ["holes"])):
        decoded(render.render_views(kernel_stl(make, tmp_path), [70, 70, 20], failed_checks=failed))


def test_the_silhouette_lies_within_two_pixels_of_the_projected_bounding_box(tmp_path):
    data = kernel_stl(enclosure, tmp_path)
    pixels = decoded(render.render_views(data, [70, 70, 20]))
    triangles = printability.read_stl(data)
    corners = np.array([(x, y, z) for x in (-35, 35) for y in (-35, 35) for z in (-10, 10)], dtype=float)
    assert np.ptp(triangles.reshape(-1, 3), axis=0) == pytest.approx([70, 70, 20], abs=1e-3)
    for view in render.layout(triangles, size=960, failed=False).views:
        left, top, right, bottom = view.rect
        rows, columns = np.nonzero(~is_background(pixels[top:bottom, left:right]))
        drawn = np.array([columns.min() + left, rows.min() + top, columns.max() + left + 1, rows.max() + top + 1])
        # The mesh's own outline in every view; in the views along an axis that is the bounding box itself,
        # while in the iso view the rounded corners lie inside the box's corners.
        for points in [triangles.reshape(-1, 3)] + ([corners] if view.name != "iso" else []):
            x, y = view.to_pixels(points)
            expected = np.array([x.min(), y.min(), x.max(), y.max()])
            assert np.abs(drawn - expected).max() <= 2, (view.name, drawn, expected)


def test_a_through_hole_shows_the_background_in_the_top_view(tmp_path):
    data = kernel_stl(enclosure, tmp_path)
    pixels = decoded(render.render_views(data, [70, 70, 20]))
    [top] = [view for view in render.layout(printability.read_stl(data), size=960, failed=False).views if view.name == "top"]
    x, y = top.to_pixels(np.array([(hx, hy, 10) for hx, hy in HOLES], dtype=float))
    assert is_background(pixels[y.astype(int), x.astype(int)]).all()
    # Between the holes the floor is drawn, so the test above is not passing on an empty view.
    x, y = top.to_pixels(np.array([(hx + 3, hy + 3, 10) for hx, hy in HOLES[:-11]], dtype=float))
    assert not is_background(pixels[y.astype(int), x.astype(int)]).any()


def test_a_failed_build_carries_a_banner_and_a_passed_one_does_not():
    data = stl(box((0, 0, 0), (60, 40, 6)))
    passed = decoded(render.render_views(data, [60, 40, 6]))
    failed = decoded(render.render_views(data, [60, 40, 6], failed_checks=["holes", "volume"]))
    banner = np.all(failed == render.BANNER, axis=-1)
    sheet = render.layout(printability.read_stl(data), size=960, failed=True)
    assert sheet.banner > 0 and banner[: sheet.banner].mean() > 0.8  # the rest is its text
    assert not banner[sheet.banner :].any()
    assert not np.all(passed == render.BANNER, axis=-1).any()
    assert render.banner_text(["holes", "volume"]) == "did not pass: holes, volume"


def test_the_footer_states_the_measured_size():
    assert render.footer_text([60, 40, 6]) == "60 x 40 x 6 mm (W x D x H, measured)"
    assert render.footer_text([59.99996, 12.345, 0.5]) == "60 x 12.35 x 0.5 mm (W x D x H, measured)"


def test_a_smaller_sheet_is_drawn_at_the_size_asked_for():
    pixels = decoded(render.render_views(stl(box((0, 0, 0), (10, 10, 10))), [10, 10, 10], size=480))
    assert pixels.shape == (480, 480, 3)


def test_the_picture_is_the_same_every_time(tmp_path):
    data = kernel_stl(enclosure, tmp_path)
    assert render.render_views(data, [70, 70, 20]) == render.render_views(bytes(data), [70, 70, 20])


def test_the_enclosure_renders_well_within_its_budget(tmp_path):
    # Budget: under 1.5 s (roadmap item 53). It measures 0.17 s here (median of 7, slowest 0.20 s), so a runner
    # about seven times slower still passes.
    data = kernel_stl(enclosure, tmp_path)
    assert int.from_bytes(data[80:84], "little") > 15_000
    started = time.perf_counter()
    render.render_views(data, [70, 70, 20])
    elapsed = time.perf_counter() - started
    assert elapsed < 1.5, elapsed


def sphere(segments: int) -> np.ndarray:
    """A closed UV sphere of radius 50 with 4 * segments * (segments - 1) triangles."""
    theta = np.linspace(0, math.pi, segments + 1)
    phi = np.linspace(0, 2 * math.pi, 2 * segments + 1)
    grid = np.stack(np.meshgrid(theta, phi, indexing="ij"), axis=-1)
    points = 50 * np.stack([np.sin(grid[..., 0]) * np.cos(grid[..., 1]), np.sin(grid[..., 0]) * np.sin(grid[..., 1]), np.cos(grid[..., 0])], axis=-1)
    a, b, c, d = points[:-1, :-1], points[1:, :-1], points[1:, 1:], points[:-1, 1:]
    upper = np.stack([a, b, c], axis=2)[:-1].reshape(-1, 3, 3)  # the last row's b and c are both the south pole
    lower = np.stack([a, c, d], axis=2)[1:].reshape(-1, 3, 3)  # the first row's a and d are both the north pole
    return np.concatenate([upper, lower])


def test_a_mesh_over_200k_triangles_is_decimated_before_drawing():
    triangles = sphere(230)
    assert len(triangles) > render.MAX_TRIANGLES
    fewer = render.decimate(triangles, render.MAX_TRIANGLES)
    assert 0 < len(fewer) <= render.MAX_TRIANGLES
    assert np.ptp(fewer.reshape(-1, 3), axis=0) == pytest.approx([100, 100, 100], rel=0.02)
    started = time.perf_counter()
    pixels = decoded(render.render_views(stl(triangles), [100, 100, 100]))
    assert time.perf_counter() - started < 5  # 0.84 s here: about a sixfold margin
    [top] = [view for view in render.layout(fewer, size=960, failed=False).views if view.name == "top"]
    x, y = top.to_pixels(np.zeros((1, 3)))
    assert not is_background(pixels[int(y[0]), int(x[0])])
    assert render.decimate(box((0, 0, 0), (1, 1, 1)), render.MAX_TRIANGLES).shape == (12, 3, 3)


@pytest.mark.parametrize("bbox", [[60, 40], [60, 40, math.inf], [60, 40, -1]], ids=["two numbers", "infinite", "negative"])
def test_a_bounding_box_that_is_not_three_sizes_is_refused(bbox):
    with pytest.raises(ValueError, match="bounding box"):
        render.render_views(stl(box((0, 0, 0), (1, 1, 1))), bbox)


@pytest.mark.parametrize("size", [render.MIN_SIZE - 1, render.MAX_SIZE + 1])
def test_a_sheet_too_small_for_its_labels_or_too_large_to_send_is_refused(size):
    with pytest.raises(ValueError, match="pixels square"):
        render.render_views(stl(box((0, 0, 0), (1, 1, 1))), [1, 1, 1], size=size)


def test_rendering_loads_no_plotting_library_no_gl_and_not_the_kernel(tmp_path):
    data = tmp_path / "box.stl"
    data.write_bytes(stl(box((0, 0, 0), (60, 40, 6))))
    code = (
        "import json, sys\n"
        "from deerflow_extension_cad import printability, render\n"
        f"data = open({str(data)!r}, 'rb').read()\n"
        "render.render_views(data, [60, 40, 6], failed_checks=['holes'])\n"
        "printability.assess(printability.read_stl(data), overhang_deg=45, build_volume_mm=[256, 256, 256], density_g_cm3=1.24)\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in {'matplotlib', 'vtk', 'vtkmodules', 'OpenGL', 'cadquery', 'OCP'})))\n"
    )
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=120, check=True)
    assert json.loads(done.stdout) == []
    tree = ast.parse(Path(render.__file__).read_text(encoding="utf-8"))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    modules = {(alias.name if isinstance(node, ast.Import) else node.module).split(".")[0] for node in imports for alias in node.names}
    assert modules <= {"__future__", "collections", "dataclasses", "io", "math", "numpy", "PIL", "deerflow_extension_cad"}, modules
    own = {alias.name for node in imports if isinstance(node, ast.ImportFrom) and node.module.startswith("deerflow_extension_cad") for alias in node.names}
    assert own == {"printability"}
