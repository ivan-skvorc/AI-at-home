"""What the model is told about the design on each call of a design run.

The brief and the version note ride the system message only on design runs
(middleware.py), so ordinary conversations pay nothing for them. Both are
bounded: the note names the head version, its last render, a finalize result
that needs attention, and a capped diff of the user's own edits since the
model's last version.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .scad import capped_diff

#: The hand-edit diff the note carries, in characters. A longer one is cut and the
#: run's first message carries the whole current file instead (actions.py).
DIFF_CHARS = 1200
#: Render error lines the note repeats.
ERROR_CHARS = 400
MODEL_SOURCES = ("model", "repair")

DRAFT_BRIEF = """## Design page
You are drafting one part on the user's design page. Write OpenSCAD and save it with the drafting tool (name contains `scad_draft`), sending the whole file every time; the page renders it in the browser.
Draft only: do not build the part with cad_build, follow the cad-modeling skill, or write or present files for it. The user's Finalize button builds the CadQuery part.
- Millimetres, Z up, the part resting on z=0.
- Every dimension is a top-level named parameter with a Customizer range, e.g. `width = 40; // [10:1:100]`; the user drags these as sliders.
- No import(), include or use of files, and no text(): the browser has no fonts. Keep $fn at 64 or lower.
After saving, say in one or two sentences what changed and end your turn: the render result reaches you on your next turn. The user finalizes the part as CadQuery later."""

FINALIZE_BRIEF = """## Design page: finalize
Port draft v{seq} (the OpenSCAD file in the latest message) to a CadQuery script with the same parameter names and values,
the same orientation (Z up) and real fillets and chamfers where the draft approximates them. Build it with the CAD tool (name contains `cad_build`)
passing bbox_xyz_mm = {bbox}, the draft's rendered size. The draft is faceted, so the page accepts a size within 0.5 mm or 2 % per axis:
when only cad_build's bounding box check fails, and by less than that, the size is right, but cad_build exports the part only when every check passes:
build once more with the same script passing the measured size as bbox_xyz_mm. Do not change the script for it, and do not draft again. Report the result in two sentences."""


def chain(versions: list[dict[str, Any]], head_id: str | None) -> list[dict[str, Any]]:
    """The head and its ancestors, head first."""
    by_id = {version["id"]: version for version in versions}
    found = []
    current = by_id.get(head_id) if head_id else None
    while current is not None and len(found) <= len(versions):
        found.append(current)
        current = by_id.get(current["parent_id"]) if current["parent_id"] else None
    return found


def hand_edits(versions: list[dict[str, Any]], head_id: str | None, limit: int = DIFF_CHARS) -> tuple[dict[str, Any] | None, str, bool]:
    """(the model's last version, the diff of the user's edits since, whether the diff is whole)."""
    lineage = chain(versions, head_id)
    if not lineage or lineage[0]["source"] in MODEL_SOURCES:
        return None, "", True
    base = next((version for version in lineage[1:] if version["source"] in MODEL_SOURCES), None)
    if base is None:
        return None, "", True
    text, whole = capped_diff(base["scad"], lineage[0]["scad"], limit)
    return base, text, whole


def _size(values: Any) -> str:
    return " x ".join(f"{float(value):g}" for value in values) if isinstance(values, list) else "unknown"


def render_line(render: dict[str, Any] | None) -> str:
    if not render:
        return "Last render: not reported yet."
    if not render.get("ok"):
        lines = render.get("error_lines") or []
        where = f" (lines {', '.join(str(line) for line in lines[:8])})" if lines else ""
        error = str(render.get("error") or "unknown error")[:ERROR_CHARS]
        return f"Last render: FAILED{where}: {error}"
    parts = [f"bbox {_size(render.get('bbox_mm'))} mm"]
    if isinstance(render.get("volume_mm3"), int | float):
        parts.append(f"volume {render['volume_mm3']:,.0f} mm3")
    if isinstance(render.get("manifold"), bool):
        parts.append("manifold" if render["manifold"] else "NOT manifold")
    return "Last render: ok, " + ", ".join(parts) + "."


def final_line(final: dict[str, Any] | None) -> str:
    if not final or final.get("status") not in ("failed", "mismatch", "built"):
        return ""
    if final["status"] == "built":
        return "Finalized: built and within the draft's size."
    if final["status"] == "mismatch":
        return f"Finalize: the CadQuery part measured {_size(final.get('bbox_mm'))} mm against the draft's {_size(final.get('draft_bbox_mm'))} mm. {final.get('message') or ''}".strip()
    return f"Finalize: the build failed. {str(final.get('message') or '')[:ERROR_CHARS]}".strip()


def version_note(versions: list[dict[str, Any]], head_id: str | None, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    head = next((version for version in versions if version["id"] == head_id), None)
    if head is None:
        return f"## Design versions ({stamp})\nNo version yet: start the file."
    lines = [f"## Design versions ({stamp})", f"Head: v{head['seq']} ({head['source']}). {render_line(head.get('render'))}"]
    final = final_line(head.get("final"))
    if final:
        lines.append(final)
    base, diff, whole = hand_edits(versions, head_id)
    if base is not None and diff:
        lines.append(f"The user edited your v{base['seq']} by hand or with sliders; build on the current file:")
        lines.append("```diff\n" + diff + ("...(cut; the whole current file is in the user's message)\n" if not whole else "") + "```")
    return "\n".join(lines)
