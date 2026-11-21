"""How a part would print, read off the STL the worker wrote.

Pure numpy over the triangles of the binary STL that ``build.export`` wrote,
which is the file a slicer gets. Nothing here imports the kernel or reads
configuration: the printer's numbers are arguments, and the fixed thresholds of
the notes are the constants below. The block is reported and never checked:
pass or fail stays on the user's numbers alone.

Every result is a function of the triangles only, with no clock and no random
source, so the same STL gives the same block.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

#: A wall thinner than this many nozzle widths gets a note: the slicer may leave it out or lay one weak line.
WALL_NOZZLES = 2
#: Overhang past the printer's angle, in square millimetres, below which no note is written. Small holes
#: lying sideways overhang less than this and bridge without support.
OVERHANG_NOTE_MM2 = 25.0
#: Less than this on the bed is a point or a line, not a face to stand on.
MIN_BED_CONTACT_MM2 = 1.0
#: Rays the wall estimate casts at most. A large mesh gets fewer, so the work stays bounded (WALL_PAIR_BUDGET).
WALL_SAMPLES = 512
#: Ray and triangle pairs the wall estimate weighs before its exact test; the rays are cut to fit.
WALL_PAIR_BUDGET = 8_000_000
#: The six ways to lay a part down, by the side that goes on the bed. The order breaks a tie.
FACES = (("-Z", (0, 0, -1)), ("+Z", (0, 0, 1)), ("-X", (-1, 0, 0)), ("+X", (1, 0, 0)), ("-Y", (0, -1, 0)), ("+Y", (0, 1, 0)))

#: A face within this angle of straight down rests on the bed when it lies at the lowest height.
_BED_COS = math.cos(math.radians(1.0))
_RECORD = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
#: Rays per block in the wall estimate: the arrays of one block stay near a million numbers.
_PAIRS_PER_BLOCK = 1_000_000


def read_stl(data: bytes) -> np.ndarray:
    """The triangles of a binary STL as an (n, 3, 3) array of millimetres. Raises ValueError for anything else."""
    if len(data) < 84:
        raise ValueError("not a whole binary STL: the file is shorter than its header")
    count = int.from_bytes(data[80:84], "little")
    if 84 + 50 * count != len(data):
        raise ValueError(f"not a whole binary STL: the header says {count} triangles and the file holds {len(data)} bytes")
    if count == 0:
        raise ValueError("the STL holds no triangles")
    triangles = np.frombuffer(data, dtype=_RECORD, count=count, offset=84)["vertices"].astype(np.float64)
    if not np.isfinite(triangles).all():
        raise ValueError("the STL holds coordinates that are not finite numbers")
    return triangles


def _cross(triangles: np.ndarray) -> np.ndarray:
    return np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])


def areas(triangles: np.ndarray) -> np.ndarray:
    """The area of each triangle in square millimetres."""
    return 0.5 * np.linalg.norm(_cross(triangles), axis=1)


def unit_normals(triangles: np.ndarray) -> np.ndarray:
    """The outward unit normal of each triangle by its winding; zero for a triangle without area."""
    cross = _cross(triangles)
    length = np.linalg.norm(cross, axis=1, keepdims=True)
    return np.divide(cross, length, out=np.zeros_like(cross), where=length > 0)


def mesh_volume_mm3(triangles: np.ndarray) -> float:
    """The volume a closed, outward-wound mesh encloses."""
    return float(np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6.0)


def _extent(triangles: np.ndarray) -> float:
    return float(np.ptp(triangles.reshape(-1, 3), axis=0).max())


def _on_bed(heights: np.ndarray, normal_z: np.ndarray, extent: float) -> np.ndarray:
    """Faces facing straight down at the lowest height: what the slicer sets on the bed."""
    tolerance = 1e-4 + 1e-6 * extent  # the STL holds single-precision numbers
    return (normal_z < -_BED_COS) & (np.abs(heights - heights.min()) <= tolerance).all(axis=1)


def _hanging(heights: np.ndarray, normal_z: np.ndarray, overhang_deg: float, extent: float) -> np.ndarray:
    # A face leaning further from vertical than the printer's angle, facing down, and not on the bed.
    return (normal_z < -math.sin(math.radians(overhang_deg))) & ~_on_bed(heights, normal_z, extent)


def bed_contact_mm2(triangles: np.ndarray) -> float:
    """The area that rests flat on the bed when the part is printed as built."""
    return float(areas(triangles)[_on_bed(triangles[:, :, 2], unit_normals(triangles)[:, 2], _extent(triangles))].sum())


def overhang_mm2(triangles: np.ndarray, overhang_deg: float) -> float:
    """The area facing down further from vertical than *overhang_deg*, printed as built, the bed excluded."""
    hanging = _hanging(triangles[:, :, 2], unit_normals(triangles)[:, 2], overhang_deg, _extent(triangles))
    return float(areas(triangles)[hanging].sum())


def _laid(triangles: np.ndarray, normals: np.ndarray, down: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """Heights and normal heights with the side toward *down* on the bed: only the vertical matters here."""
    direction = np.asarray(down, dtype=float)
    return -(triangles @ direction), -(normals @ direction)


def better_face_down(triangles: np.ndarray, overhang_deg: float) -> dict | None:
    """The side to lay the part on, of the six axis sides, when it at least halves the overhang; else None.

    Ties go to the larger area on the bed, then to the order of FACES.
    """
    normals, extent, area = unit_normals(triangles), _extent(triangles), areas(triangles)
    scores = []
    for order, (name, down) in enumerate(FACES):
        heights, normal_z = _laid(triangles, normals, down)
        hanging = round(float(area[_hanging(heights, normal_z, overhang_deg, extent)].sum()), 1)
        resting = round(float(area[_on_bed(heights, normal_z, extent)].sum()), 1)
        scores.append((hanging, -resting, order, name))
    now = scores[0][0]
    best = min(scores)
    if now <= 0 or best[0] > now / 2:
        return None
    return {"face": best[3], "overhang_mm2": best[0]}


def weld(triangles: np.ndarray) -> np.ndarray:
    """The corners of each triangle as indices of shared vertices, joining points a millionth of the part apart."""
    points = triangles.reshape(-1, 3)
    low = points.min(axis=0)
    span = float(np.ptp(points, axis=0).max()) or 1.0
    cells = np.rint((points - low) * ((1 << 20) / span)).astype(np.int64)  # 21 bits an axis
    _, index = np.unique((cells[:, 0] << 42) | (cells[:, 1] << 21) | cells[:, 2], return_inverse=True)
    return index.reshape(-1, 3)


def edges(triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Each edge of the welded mesh once: its two end points, how many triangles use it, and the first two of them.

    The second triangle repeats the first for an edge only one triangle uses. The
    collapsed edge of a degenerate triangle joins nothing and is left out.
    """
    faces = weld(triangles)
    ends = np.stack([faces, np.roll(faces, -1, axis=1)], axis=-1).reshape(-1, 2)
    points = np.stack([triangles, np.roll(triangles, -1, axis=1)], axis=2).reshape(-1, 2, 3)
    owner = np.repeat(np.arange(len(triangles)), 3)
    proper = ends[:, 0] != ends[:, 1]
    ends, points, owner = ends[proper], points[proper], owner[proper]
    if not len(ends):
        return np.zeros((0, 2, 3)), np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    key = ends.min(axis=1) * (int(ends.max()) + 1) + ends.max(axis=1)
    order = np.argsort(key, kind="stable")
    key = key[order]
    start = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    count = np.diff(np.r_[start, len(key)])
    first, second = owner[order[start]], owner[order[np.minimum(start + 1, len(key) - 1)]]
    return points[order[start]], count, first, second


def open_edges(triangles: np.ndarray) -> int:
    """Edges not shared by exactly two triangles. Zero for a watertight mesh."""
    return int((edges(triangles)[1] != 2).sum())


def fit(size_mm: Sequence[float], build_volume_mm: Sequence[float] | None) -> dict | None:
    """Whether a part of *size_mm* fits the build volume as built, and if not, turned a quarter on the bed."""
    if build_volume_mm is None:
        return None

    def within(size: float, room: float) -> bool:
        return size <= room * (1 + 1e-9) + 1e-6

    over = [axis for axis, size, room in zip("XYZ", size_mm, build_volume_mm) if not within(size, room)]
    if not over:
        return {"fits_build_volume": True}
    turned = within(size_mm[1], build_volume_mm[0]) and within(size_mm[0], build_volume_mm[1]) and within(size_mm[2], build_volume_mm[2])
    return {"fits_build_volume": False, "too_large_axes": over, "fits_turned": turned}


def thinnest_wall_mm(triangles: np.ndarray, *, samples: int = WALL_SAMPLES) -> float | None:
    """An estimate of the thinnest wall: rays from points spread over the surface, straight in, to where they leave.

    The points are spread by area, evenly and without a random source, so the same
    mesh gives the same answer. A wall smaller than the spacing of the points can
    be missed: this is a sample, not a proof. None when no ray leaves the part.
    """
    area = areas(triangles)
    faces = np.flatnonzero(area > 0)
    if not len(faces):
        return None
    count = int(min(samples, max(64, WALL_PAIR_BUDGET // len(triangles))))
    centre = triangles.reshape(-1, 3).mean(axis=0)
    mesh = triangles - centre  # smaller numbers keep the distances below exact
    cumulative = np.cumsum(area[faces])
    positions = (np.arange(count) + 0.5) / count * cumulative[-1]
    pick = np.minimum(np.searchsorted(cumulative, positions, side="right"), len(faces) - 1)
    source = faces[pick]
    # Where in its triangle each point falls: the share of its area slot, and a golden-ratio step across.
    along = np.clip((positions - (cumulative[pick] - area[source])) / area[source], 0.0, 1.0)
    spread = np.sqrt(0.1 + 0.8 * along)
    across = 0.1 + 0.8 * ((np.arange(count) * 0.6180339887498949) % 1.0)
    corners = mesh[source]
    points = (1 - spread)[:, None] * corners[:, 0] + (spread * (1 - across))[:, None] * corners[:, 1] + (spread * across)[:, None] * corners[:, 2]
    directions = -unit_normals(mesh)[source]
    nudge = 1e-6 * max(_extent(triangles), 1.0)
    origins = points + directions * nudge
    nearest = _first_hits(mesh, origins, directions, source, nudge)
    found = nearest[np.isfinite(nearest)]
    return float(found.min() + nudge) if len(found) else None


def _first_hits(mesh: np.ndarray, origins: np.ndarray, directions: np.ndarray, source: np.ndarray, nudge: float) -> np.ndarray:
    """The distance along each ray to the first triangle it meets, other than its own; inf for none."""
    centres = mesh.mean(axis=1)
    reach = np.sqrt(((mesh - centres[:, None]) ** 2).sum(axis=2).max(axis=1)) + nudge
    behind, reach_square = -reach[:, None], (reach**2)[:, None]
    centre_square = (centres**2).sum(axis=1)[:, None]
    nearest = np.full(len(origins), np.inf)
    block = max(1, _PAIRS_PER_BLOCK // len(mesh))
    for start in range(0, len(origins), block):
        rays = slice(start, start + block)
        origin, direction = origins[rays], directions[rays]
        # A triangle can meet a ray only if its bounding sphere does: weighed for all pairs with matrix
        # products, in place, since these arrays are the whole cost.
        ahead = centres @ direction.T
        ahead -= (origin * direction).sum(axis=1)
        apart = centres @ origin.T
        apart *= -2
        apart += centre_square
        apart += (origin**2).sum(axis=1)
        apart -= np.square(ahead)
        near = apart <= reach_square
        near &= ahead >= behind
        triangle, ray = np.nonzero(near)
        ray_global = ray + start
        keep = triangle != source[ray_global]
        triangle, ray, ray_global = triangle[keep], ray[keep], ray_global[keep]
        distance = _intersect(mesh[triangle], origin[ray], direction[ray])
        hit = np.isfinite(distance) & (distance > nudge)
        np.minimum.at(nearest, ray_global[hit], distance[hit])
    return nearest


def _intersect(triangles: np.ndarray, origins: np.ndarray, directions: np.ndarray) -> np.ndarray:
    """Moller and Trumbore's ray and triangle test, pair by pair: the distance along the ray, or inf."""
    corner = triangles[:, 0]
    edge1, edge2 = triangles[:, 1] - corner, triangles[:, 2] - corner
    p = np.cross(directions, edge2)
    determinant = (edge1 * p).sum(axis=1)
    usable = np.abs(determinant) > 1e-12 * np.linalg.norm(edge1, axis=1) * np.linalg.norm(edge2, axis=1)
    inverse = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=usable)
    offset = origins - corner
    u = (offset * p).sum(axis=1) * inverse
    q = np.cross(offset, edge1)
    v = (directions * q).sum(axis=1) * inverse
    distance = (edge2 * q).sum(axis=1) * inverse
    inside = usable & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
    return np.where(inside, distance, np.inf)


def assess(
    triangles: np.ndarray,
    *,
    overhang_deg: float,
    build_volume_mm: Sequence[float] | None,
    density_g_cm3: float,
    volume_mm3: float | None = None,
    wall_mm: float | None = None,
) -> dict:
    """The print block: what the part would do on the bed, printed as built.

    *volume_mm3* is the measured volume (the mesh's own when None); *wall_mm* a
    thinnest wall measured elsewhere, used instead of this module's sampled one.
    """
    normals, extent, area = unit_normals(triangles), _extent(triangles), areas(triangles)
    heights = triangles[:, :, 2]
    volume = abs(mesh_volume_mm3(triangles)) if volume_mm3 is None else float(volume_mm3)
    wall = thinnest_wall_mm(triangles) if wall_mm is None else float(wall_mm)
    unshared = open_edges(triangles)
    block: dict = {
        "bed_contact_mm2": round(float(area[_on_bed(heights, normals[:, 2], extent)].sum()), 1),
        "overhang_mm2": round(float(area[_hanging(heights, normals[:, 2], overhang_deg, extent)].sum()), 1),
        "overhang_deg": float(overhang_deg),
        "thinnest_wall_mm": None if wall is None else round(wall, 2),
        "watertight": unshared == 0,
        "grams": round(volume / 1000.0 * density_g_cm3, 2),
    }
    if unshared:
        block["open_edges"] = unshared
    better = better_face_down(triangles, overhang_deg)
    if better is not None:
        block["better_face_down"] = better
    fitting = fit(np.ptp(triangles.reshape(-1, 3), axis=0).tolist(), build_volume_mm)
    if fitting is not None:
        block["build_volume_mm"] = [float(size) for size in build_volume_mm]
        block.update(fitting)
    return block


def _number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def notes(block: dict, *, nozzle_mm: float) -> list[str]:
    """The sentences an answer carries: only what is past a fixed threshold, so a plain part says nothing."""
    said: list[str] = []
    wall, least = block.get("thinnest_wall_mm"), WALL_NOZZLES * nozzle_mm
    if wall is not None and wall < least:
        said.append(f"thinnest wall about {_number(wall)} mm (sampled), under two nozzle widths ({_number(least)} mm): it may print weak or with gaps")
    if block["overhang_mm2"] >= OVERHANG_NOTE_MM2:
        sentence = f"{_number(block['overhang_mm2'])} mm² overhangs past {_number(block['overhang_deg'])}° and needs support"
        better = block.get("better_face_down")
        if better:
            sentence += f"; with its {better['face']} side on the bed it would be {_number(better['overhang_mm2'])} mm²"
        said.append(sentence)
    if block["bed_contact_mm2"] < MIN_BED_CONTACT_MM2:
        said.append("nothing flat rests on the bed: give it a flat face at the lowest z, or it needs a brim or support")
    if block.get("fits_build_volume") is False:
        room = " × ".join(_number(size) for size in block["build_volume_mm"])
        sentence = f"larger than the build volume ({room} mm) in {', '.join(block['too_large_axes'])}"
        said.append(sentence + ("; it fits turned 90° on the bed" if block.get("fits_turned") else ""))
    if not block["watertight"]:
        said.append(f"the mesh is not watertight: {block['open_edges']} edges are not shared by exactly two triangles, so a slicer may repair it or print it wrong")
    return said
