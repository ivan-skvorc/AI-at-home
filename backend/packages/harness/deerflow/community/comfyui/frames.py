"""Stills and contact sheets — how a clip becomes something a model can judge.

``view_image`` accepts png/jpg/webp/gif only, capped at 20 MB: no MP4 ever
reaches a model. So a generated clip is judged from images, and the shape of
those images decides whether the critique is any good.

A single **contact sheet** beats a handful of separate stills for two reasons:
one ``view_image`` call instead of six (vision tokens are billed per image, and
a cloud lead pays them every round), and temporal faults — flicker, morphing,
identity drift — read far more clearly side by side than frame by frame. The
individual stills are written too, for when the agent wants to look closely at
one moment.
"""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Pillow is not a declared harness dependency: `uv lock` cannot currently be
# re-run in this repo (the `tenki` extra's `tenki-sandbox` 404s on PyPI), so a
# pyproject change would break every `uv run`. It arrives transitively via
# markitdown[all], the import is lazy, and a missing Pillow degrades the clip
# to "no contact sheet" with this message rather than failing the generation.
_PIL_HINT = "Pillow is required to build a video contact sheet; the clip itself was generated. Install it with: uv pip install pillow"


def select_indices(total: int, count: int) -> list[int]:
    """Evenly spaced frame indices across the whole clip, endpoints included.

    Endpoints matter: the first and last frames are where identity drift shows
    up, and a sheet sampled from the middle hides exactly the fault the critic
    is looking for.
    """
    if total <= 0 or count <= 0:
        return []
    if count >= total:
        return list(range(total))
    if count == 1:
        return [0]
    step = (total - 1) / (count - 1)
    indices = sorted({int(round(index * step)) for index in range(count)})
    return [min(index, total - 1) for index in indices]


def _require_pil() -> Any:
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415 - optional dependency, imported at use
    except ImportError as exc:  # pragma: no cover - depends on the install profile
        raise RuntimeError(_PIL_HINT) from exc
    return Image, ImageDraw


def build_contact_sheet(
    frames: list[bytes],
    *,
    columns: int = 3,
    tile_width: int = 480,
    labels: list[str] | None = None,
    background: tuple[int, int, int] = (18, 18, 18),
) -> bytes:
    """Tile frames into one labelled PNG.

    Labels are drawn on the tiles on purpose: a verdict that says "frame 4
    morphs" is actionable, one that says "somewhere in the middle" is not.
    """
    if not frames:
        raise ValueError("No frames to build a contact sheet from")
    image_mod, draw_mod = _require_pil()

    tiles = []
    for raw in frames:
        image = image_mod.open(io.BytesIO(raw))
        image = image.convert("RGB")
        ratio = tile_width / image.width
        tiles.append(image.resize((tile_width, max(1, int(round(image.height * ratio))))))

    columns = max(1, min(columns, len(tiles)))
    rows = (len(tiles) + columns - 1) // columns
    tile_height = max(tile.height for tile in tiles)
    padding = 8
    sheet_width = columns * tile_width + padding * (columns + 1)
    sheet_height = rows * tile_height + padding * (rows + 1)

    sheet = image_mod.new("RGB", (sheet_width, sheet_height), background)
    draw = draw_mod.Draw(sheet)
    for position, tile in enumerate(tiles):
        row, column = divmod(position, columns)
        x = padding + column * (tile_width + padding)
        y = padding + row * (tile_height + padding)
        sheet.paste(tile, (x, y))
        label = labels[position] if labels and position < len(labels) else str(position + 1)
        draw.text((x + 6, y + 4), label, fill=(255, 255, 255))
        draw.text((x + 5, y + 3), label, fill=(0, 0, 0))

    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()
