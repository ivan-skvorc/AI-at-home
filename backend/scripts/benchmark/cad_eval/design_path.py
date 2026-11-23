"""The design path: draft the part in OpenSCAD first, then port it to CadQuery.

The CAD design page (FORK.md §58) has the model draft in OpenSCAD and then, on
Finalize, port the draft to CadQuery for ``cad_build``. This band asks whether
that detour helps or hurts the measured part, on the same specs and the same
truth as the direct path. A sample is two turns in one thread:

1. the spec's request with the drafting rules the page's brief gives
   (``DRAFT_RULES``, kept equal to ``deerflow_extension_cad_design.notes.DRAFT_BRIEF``
   by ``tests/test_bench_cad_eval.py``), asking for the whole file in one
   ``openscad`` block and no CAD tool yet;
2. the draft sent back with the page's finalize instruction: port it to
   CadQuery with the same parameter names and values and build it with
   ``cad_build``.

It emulates the page's prompts, not the page. No browser renders the draft,
so the model gets no render result, no automatic repair turn, and no rendered
bounding box to hand ``cad_build``; the page's own tool and version note are
not in play, because they reach design runs only. What the band measures is
the language detour.

Stdlib only, like ``specs.py`` and ``score.py``, though nothing loads it by path.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

#: The paths a run can take; ``direct`` is the request alone, as before this band.
PATHS = ("direct", "design")
DEFAULT_PATH = "direct"

#: The page brief's drafting rules, word for word (notes.DRAFT_BRIEF).
DRAFT_RULES = (
    "- Millimetres, Z up, the part resting on z=0.",
    "- Every dimension is a top-level named parameter with a Customizer range, e.g. `width = 40; // [10:1:100]`; the user drags these as sliders.",
    "- No import(), include or use of files, and no text(): the browser has no fonts. Keep $fn at 64 or lower.",
)

DRAFT_INSTRUCTIONS = "\n".join(
    (
        "Draft this part in OpenSCAD first. Reply with the whole file in one ```openscad code block, and do not call any CAD tool yet.",
        *DRAFT_RULES,
    )
)

#: The page's finalize message and brief, in one user turn (actions.FINALIZE_MESSAGE, notes.FINALIZE_BRIEF).
FINALIZE_TEMPLATE = (
    "Finalize the draft: port this OpenSCAD file to a CadQuery script with the same parameter names and values, "
    "the same orientation (Z up) and real fillets and chamfers where the draft approximates them, "
    "and build it with cad_build. Do not draft again.\n\n```openscad\n{scad}\n```"
)

_FENCE = re.compile(r"```[ \t]*(?:openscad|scad)[^\n]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def draft_prompt(spec_prompt: str) -> str:
    """The first turn: the spec's own prompt (request and preamble), then the drafting rules."""
    return f"{spec_prompt}\n\n{DRAFT_INSTRUCTIONS}"


def finalize_prompt(scad: str) -> str:
    return FINALIZE_TEMPLATE.format(scad=scad.strip("\n"))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, Mapping) else part if isinstance(part, str) else "" for part in content)
    return ""


def extract_draft(messages: Iterable[Mapping[str, Any]]) -> str | None:
    """The last ``openscad`` block the model wrote in the draft turn, or None."""
    found = None
    for message in messages:
        if not isinstance(message, Mapping) or message.get("type", message.get("role")) not in ("ai", "assistant"):
            continue
        for block in _FENCE.findall(_text(message.get("content"))):
            if block.strip():
                found = block
    return found


def path_hash() -> str:
    """Twelve hex digits over the design path's prompts: rows compare only when it matches."""
    return hashlib.sha256((DRAFT_INSTRUCTIONS + "\0" + FINALIZE_TEMPLATE).encode("utf-8")).hexdigest()[:12]
