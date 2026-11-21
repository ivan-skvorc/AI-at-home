"""A picture of a built part: four views of the STL the worker wrote, drawn with numpy and Pillow.

The worker calls ``render_views`` after measuring, on the binary STL that
``build.export`` wrote, so the picture shows the file a printer gets. The
drawing is a z-buffer in numpy, with flat Lambert shading and the part's sharp
edges in dark lines. Nothing here imports OpenGL, VTK or matplotlib: VTK's
offscreen rendering needs EGL or OSMesa, which the Gateway image does not ship,
and matplotlib writes a cache under HOME.

The picture is not a check. It carries no dimension beyond the measured
bounding box in its footer, and it is the same for the same STL every time.
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont, features

from deerflow_extension_cad import printability

#: Above this many triangles the mesh is simplified before drawing; the picture is 960 pixels, not the file.
MAX_TRIANGLES = 200_000
#: The sheet's side in pixels: the labels need the smallest, and the largest is far past any chat preview.
MIN_SIZE, MAX_SIZE = 240, 2048
#: Two faces meeting at more than this angle draw their shared edge.
FEATURE_DEG = 30.0

BACKGROUND = (246, 247, 249)
RULE = (214, 218, 224)
INK = (36, 41, 47)
MUTED = (101, 109, 118)
PART = (104, 146, 196)
PART_FAILED = (196, 112, 84)
BANNER = (176, 38, 28)
BANNER_INK = (255, 255, 255)
AXIS_COLOURS = {"X": (200, 60, 50), "Y": (50, 140, 60), "Z": (50, 90, 200)}

#: Each view by name: the direction toward the viewer, and the world direction that is up on the screen.
VIEWS = (("iso", (1, -1, 1), (0, 0, 1)), ("top", (0, 0, 1), (0, 1, 0)), ("front", (0, -1, 0), (0, 0, 1)), ("right", (1, 0, 0), (0, 0, 1)))
#: Light comes from over the viewer's left shoulder, the same in every view.
_LIGHT = (-0.3, 0.45, 0.85)
_AMBIENT = 0.45
#: Nearer surfaces are drawn up to this much lighter, so a floor reads apart from the rim above it.
_DEPTH_CUE = 0.18
#: An edge is hidden only when a surface lies this many pixels in front of it.
_EDGE_TOLERANCE_PX = 2.0


@dataclass(frozen=True, eq=False)
class View:
    """One panel of the sheet: an orthographic projection at the sheet's common scale."""

    name: str
    toward: np.ndarray
    right: np.ndarray
    up: np.ndarray
    #: The drawing area in pixels: left, top, right, bottom (exclusive).
    rect: tuple[int, int, int, int]
    #: Pixels per millimetre, the same in every view.
    scale: float
    #: The model's (right, up) coordinates drawn at the middle of the rect.
    middle: tuple[float, float]
    #: The panel this view sits in, for its label: left, top, right, bottom.
    panel: tuple[int, int, int, int]

    def to_pixels(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Sheet pixel coordinates of model *points*; the pixel a point falls in is (int(x), int(y))."""
        left, top, right, bottom = self.rect
        x = (left + right) / 2 + (points @ self.right - self.middle[0]) * self.scale
        y = (top + bottom) / 2 - (points @ self.up - self.middle[1]) * self.scale
        return x, y


@dataclass(frozen=True)
class Sheet:
    size: int
    banner: int
    footer: int
    header: int
    views: tuple[View, ...]


def _unit(vector: Sequence[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    return array / np.linalg.norm(array)


def layout(triangles: np.ndarray, *, size: int, failed: bool) -> Sheet:
    """Where each view goes on a sheet of *size* pixels, at one scale that fits the part into every view."""
    unit = size / 960
    banner = round(34 * unit) if failed else 0
    footer, header, margin = round(34 * unit), round(38 * unit), round(12 * unit)
    panel_width, panel_height = size // 2, (size - banner - footer) // 2
    points = triangles.reshape(-1, 3)
    frames = []
    for index, (name, toward, up_hint) in enumerate(VIEWS):
        toward = _unit(toward)
        right = _unit(np.cross(up_hint, toward))
        up = np.cross(toward, right)
        across, along = points @ right, points @ up
        left, top = (index % 2) * panel_width, banner + (index // 2) * panel_height
        panel = (left, top, left + panel_width, top + panel_height)
        rect = (left + margin, top + header, left + panel_width - margin, top + panel_height - margin)
        frames.append((name, toward, right, up, (across.min(), across.max()), (along.min(), along.max()), rect, panel))
    tiny = 1e-9
    scale = min(min((rect[2] - rect[0]) / max(x[1] - x[0], tiny), (rect[3] - rect[1]) / max(y[1] - y[0], tiny)) for *_, x, y, rect, _ in frames)
    views = tuple(View(name, toward, right, up, rect, scale, ((x[0] + x[1]) / 2, (y[0] + y[1]) / 2), panel) for name, toward, right, up, x, y, rect, panel in frames)
    return Sheet(size, banner, footer, header, views)


def decimate(triangles: np.ndarray, limit: int) -> np.ndarray:
    """At most *limit* triangles, by joining the corners that share a cell of a grid; a mesh within it is returned as is."""
    if len(triangles) <= limit:
        return triangles
    points = triangles.reshape(-1, 3)
    low = points.min(axis=0)
    extent = float(np.ptp(points, axis=0).max()) or 1.0
    # A cell that leaves about limit / 2 corners on the surface, and so about limit triangles; coarser until it does.
    cell = max(math.sqrt(2 * float(printability.areas(triangles).sum()) / limit), extent / (1 << 20))
    while True:
        cells = np.floor((points - low) / cell).astype(np.int64)
        _, index = np.unique((cells[:, 0] << 42) | (cells[:, 1] << 21) | cells[:, 2], return_inverse=True)
        count = np.bincount(index)
        corners = np.stack([np.bincount(index, weights=points[:, axis]) for axis in range(3)], axis=1) / count[:, None]
        faces = index.reshape(-1, 3)
        kept = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 2] != faces[:, 0])]
        if len(kept) <= limit:
            return corners[kept]
        cell *= 1.5


def _counted(counts: np.ndarray) -> np.ndarray:
    """0, 1, ... count - 1 for each count, all in one array."""
    return np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts)


def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator != 0)


def _rasterize(x: np.ndarray, y: np.ndarray, z: np.ndarray, width: int, height: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The pixel centres each triangle covers, row by row: pixel index, triangle and depth for each.

    *x*, *y* and *z* hold each triangle's corners in pixels of a width by height
    area, z toward the viewer. Spans are found for every triangle at once, so the
    work grows with the pixels covered, not with a loop over triangles.
    """
    order = np.argsort(y, axis=1, kind="stable")
    xs, ys = np.take_along_axis(x, order, axis=1), np.take_along_axis(y, order, axis=1)
    # The depth plane of each triangle on the screen, from its two edges.
    ex1, ey1, ez1 = x[:, 1] - x[:, 0], y[:, 1] - y[:, 0], z[:, 1] - z[:, 0]
    ex2, ey2, ez2 = x[:, 2] - x[:, 0], y[:, 2] - y[:, 0], z[:, 2] - z[:, 0]
    normal_z = ex1 * ey2 - ey1 * ex2
    usable = np.abs(normal_z) > 1e-9  # a triangle seen edge-on covers nothing
    slope_x = _ratio(-(ey1 * ez2 - ez1 * ey2), np.where(usable, normal_z, 0))
    slope_y = _ratio(-(ez1 * ex2 - ex1 * ez2), np.where(usable, normal_z, 0))
    first = np.maximum(np.ceil(ys[:, 0] - 0.5), 0)
    last = np.minimum(np.floor(ys[:, 2] - 0.5), height - 1)
    rows = np.where(usable, np.maximum(last - first + 1, 0), 0).astype(np.int64)
    triangle = np.repeat(np.arange(len(x)), rows)
    row = np.repeat(first.astype(np.int64), rows) + _counted(rows)
    centre = row + 0.5
    (x0, x1, x2), (y0, y1, y2) = xs[triangle].T, ys[triangle].T
    long = x0 + (centre - y0) * _ratio(x2 - x0, y2 - y0)
    short = np.where(centre < y1, x0 + (centre - y0) * _ratio(x1 - x0, y1 - y0), x1 + (centre - y1) * _ratio(x2 - x1, y2 - y1))
    start = np.maximum(np.ceil(np.minimum(long, short) - 0.5), 0)
    end = np.minimum(np.floor(np.maximum(long, short) - 0.5), width - 1)
    columns = np.maximum(end - start + 1, 0).astype(np.int64)
    triangle, row = np.repeat(triangle, columns), np.repeat(row, columns)
    column = np.repeat(start.astype(np.int64), columns) + _counted(columns)
    depth = z[triangle, 0] + slope_x[triangle] * (column + 0.5 - x[triangle, 0]) + slope_y[triangle] * (row + 0.5 - y[triangle, 0])
    return row * width + column, triangle, depth


@dataclass(frozen=True, eq=False)
class _Mesh:
    triangles: np.ndarray
    normals: np.ndarray
    #: Both ends of each edge drawn in every view (sharp, open or shared by more than two triangles), as points.
    sharp: np.ndarray
    #: Both ends of each smooth edge between two triangles, and the two triangles, for silhouettes.
    smooth: np.ndarray
    smooth_faces: np.ndarray


def _mesh(triangles: np.ndarray) -> _Mesh:
    """The triangles with their normals, and their edges sorted into sharp ones and smooth ones."""
    normals = printability.unit_normals(triangles)
    points, count, one, other = printability.edges(triangles)
    pair = count == 2
    shaded = (np.abs(normals[one]).sum(axis=1) > 0) & (np.abs(normals[other]).sum(axis=1) > 0)
    bend = (normals[one] * normals[other]).sum(axis=1) < math.cos(math.radians(FEATURE_DEG))
    sharp = ~pair | (shaded & bend)
    smooth = pair & shaded & ~bend
    return _Mesh(triangles, normals, points[sharp], points[smooth], np.stack([one[smooth], other[smooth]], axis=1))


def _draw_view(canvas: np.ndarray, mesh: _Mesh, view: View, colour: Sequence[int]) -> None:
    left, top, right, bottom = view.rect
    width, height = right - left, bottom - top
    corners = mesh.triangles.reshape(-1, 3)
    x, y = view.to_pixels(corners)
    x, y = (x - left).reshape(-1, 3), (y - top).reshape(-1, 3)
    depth = (corners @ view.toward).reshape(-1, 3)
    pixel, triangle, z = _rasterize(x, y, depth, width, height)
    nearest = np.full(width * height, -np.inf)
    np.maximum.at(nearest, pixel, z)
    front = z >= nearest[pixel]
    owner = np.full(width * height, -1, dtype=np.int64)
    np.maximum.at(owner, pixel[front], triangle[front])  # a tie goes to the later triangle, the same every time
    covered = owner >= 0
    # Flat Lambert shading, lit from the viewer's side whichever way a face is wound.
    facing = mesh.normals @ view.toward
    light = _unit(_LIGHT[0] * view.right + _LIGHT[1] * view.up + _LIGHT[2] * view.toward)
    lambert = np.clip(np.where(facing < 0, -1.0, 1.0) * (mesh.normals @ light), 0.0, 1.0)
    shade = _AMBIENT + (1 - _AMBIENT) * lambert
    near, far = float(depth.max()), float(depth.min())
    cue = 1 - _DEPTH_CUE + _DEPTH_CUE * (nearest[covered] - far) / max(near - far, 1e-9)
    area = canvas[top:bottom, left:right].reshape(-1, 3).copy()  # a slice of the sheet is not contiguous: drawn apart, copied back
    area[covered] = np.clip(np.asarray(colour, dtype=float) * (shade[owner[covered]] * cue)[:, None], 0, 255).astype(np.uint8)
    # Sharp edges in every view, and the smooth edges where the surface turns away from the viewer.
    visible_side = facing > 1e-9
    outline = visible_side[mesh.smooth_faces[:, 0]] != visible_side[mesh.smooth_faces[:, 1]]
    edges = np.concatenate([mesh.sharp, mesh.smooth[outline]])
    if len(edges):
        _draw_edges(area, edges, nearest, view, width, height)
    canvas[top:bottom, left:right] = area.reshape(height, width, 3)


def _draw_edges(area: np.ndarray, edges: np.ndarray, nearest: np.ndarray, view: View, width: int, height: int) -> None:
    """Each edge as a one-pixel line, point by point, where no surface lies in front of it."""
    left, top = view.rect[:2]
    ex, ey = view.to_pixels(edges.reshape(-1, 3))
    ex, ey = (ex - left).reshape(-1, 2), (ey - top).reshape(-1, 2)
    ez = (edges.reshape(-1, 3) @ view.toward).reshape(-1, 2)
    steps = np.ceil(np.maximum(np.abs(ex[:, 1] - ex[:, 0]), np.abs(ey[:, 1] - ey[:, 0]))).astype(np.int64) + 1
    edge = np.repeat(np.arange(len(edges)), steps)
    share = _counted(steps) / np.maximum(steps[edge] - 1, 1)
    px = ex[edge, 0] + share * (ex[edge, 1] - ex[edge, 0])
    py = ey[edge, 0] + share * (ey[edge, 1] - ey[edge, 0])
    pz = ez[edge, 0] + share * (ez[edge, 1] - ez[edge, 0])
    column, row = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64)
    inside = (column >= 0) & (column < width) & (row >= 0) & (row < height)
    spot = row[inside] * width + column[inside]
    seen = pz[inside] >= nearest[spot] - _EDGE_TOLERANCE_PX / view.scale
    area[spot[seen]] = INK


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    # Pillow's own font: nothing is read from the system, so every host draws the same letters.
    return ImageFont.load_default(size=size) if features.check("freetype2") else ImageFont.load_default()


def _size(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def footer_text(bbox: Sequence[float]) -> str:
    """The measured size as the footer says it. A plain x: Pillow's own fonts have no multiplication sign."""
    return " x ".join(_size(value) for value in bbox) + " mm (W x D x H, measured)"


def banner_text(failed_checks: Sequence[str]) -> str:
    return "did not pass" + (": " + ", ".join(failed_checks) if failed_checks else "")


def _fitted(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def _triad(draw: ImageDraw.ImageDraw, view: View, origin: tuple[float, float], arm: float, font) -> None:
    """The model's axes as this view shows them. An axis along the line of sight is a ring, dotted when it
    points at the viewer and crossed when it points away, labelled on its left, where no arm goes."""
    ox, oy = origin
    width = max(1, round(arm / 7))
    for axis, direction in zip("XYZ", np.eye(3)):
        dx, dy = float(direction @ view.right) * arm, -float(direction @ view.up) * arm
        colour = AXIS_COLOURS[axis]
        length = math.hypot(dx, dy)
        if length < 0.2 * arm:
            ring = arm * 0.3
            draw.ellipse((ox - ring, oy - ring, ox + ring, oy + ring), outline=colour, width=width)
            if float(direction @ view.toward) > 0:
                dot = max(1.0, ring * 0.35)
                draw.ellipse((ox - dot, oy - dot, ox + dot, oy + dot), fill=colour)
            else:
                cross = ring * 0.7
                draw.line((ox - cross, oy - cross, ox + cross, oy + cross), fill=colour, width=width)
                draw.line((ox - cross, oy + cross, ox + cross, oy - cross), fill=colour, width=width)
            draw.text((ox - ring - 3, oy), axis, font=font, fill=colour, anchor="rm")
            continue
        draw.line((ox, oy, ox + dx, oy + dy), fill=colour, width=width)
        draw.text((ox + dx * (1 + 6 / length), oy + dy * (1 + 6 / length)), axis, font=font, fill=colour, anchor="mm")


def _annotate(image: Image.Image, sheet: Sheet, bbox: Sequence[float], failed_checks: Sequence[str] | None) -> None:
    draw = ImageDraw.Draw(image)
    unit = sheet.size / 960
    label, small = _font(round(15 * unit)), _font(round(12 * unit))
    margin = round(12 * unit)
    for view in sheet.views:
        left, top, right, bottom = view.panel
        draw.rectangle((left, top, right - 1, bottom - 1), outline=RULE)
        draw.text((left + margin, top + sheet.header / 2), view.name, font=label, fill=MUTED, anchor="lm")
        arm = sheet.header * 0.28
        _triad(draw, view, (right - margin - arm * 2, top + sheet.header * 0.56), arm, small)
    footer_top = sheet.size - sheet.footer
    draw.line((0, footer_top, sheet.size, footer_top), fill=RULE)
    draw.text((margin, footer_top + sheet.footer / 2), _fitted(draw, footer_text(bbox), label, sheet.size - 2 * margin), font=label, fill=INK, anchor="lm")
    if failed_checks is not None:
        draw.rectangle((0, 0, sheet.size - 1, sheet.banner - 1), fill=BANNER)
        draw.text((margin, sheet.banner / 2), _fitted(draw, banner_text(failed_checks), label, sheet.size - 2 * margin), font=label, fill=BANNER_INK, anchor="lm")


def render_views(stl_bytes: bytes, bbox: Sequence[float], *, size: int = 960, failed_checks: Sequence[str] | None = None) -> bytes:
    """A PNG of the part in the STL: iso, top, front and right views on one sheet of *size* pixels square.

    *bbox* is the measured width, depth and height in millimetres, printed in the
    footer. *failed_checks* names the checks a failed build did not pass; a list,
    even an empty one, marks the picture as failed with a banner.

    Raises ValueError for a file that is not a whole binary STL or a bounding box
    that is not three sizes, and for a *size* outside MIN_SIZE to MAX_SIZE.
    """
    sizes = [float(value) for value in bbox]
    if len(sizes) != 3 or not all(math.isfinite(value) and value >= 0 for value in sizes):
        raise ValueError("the bounding box must be three sizes in millimetres")
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ValueError(f"the picture must be {MIN_SIZE} to {MAX_SIZE} pixels square")
    triangles = decimate(printability.read_stl(stl_bytes), MAX_TRIANGLES)
    sheet = layout(triangles, size=size, failed=failed_checks is not None)
    canvas = np.empty((size, size, 3), dtype=np.uint8)
    canvas[:] = BACKGROUND
    mesh = _mesh(triangles)
    for view in sheet.views:
        _draw_view(canvas, mesh, view, PART if failed_checks is None else PART_FAILED)
    image = Image.fromarray(canvas)
    _annotate(image, sheet, sizes, failed_checks)
    out = io.BytesIO()
    image.save(out, format="PNG", compress_level=6)
    return out.getvalue()
