"""``scad_draft``: the model hands the page a whole OpenSCAD file. Nothing runs it here.

The tool is bound on every request by the host, and the middleware removes it
from every model call that is not a design run (middleware.py), so ordinary
conversations pay no tokens for it. The handler checks the same thing again:
filtering the schema does not stop a call the model makes anyway.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from .constants import ID
from .scad import parse_params
from .store import Conflict, NotFound, Store

# Measured in the host's short tool form by backend/tests/test_context_fit_critical.py;
# keep it at or under 150 tokens. The opening sentences stand on their own.
DESCRIPTION = (
    "Save the complete OpenSCAD file of the part on the user's design page as a new version; "
    "the page renders it in the browser. Only works in a design-page conversation. "
    "Send the whole file every time, never a fragment or a diff. note: one line on what changed."
)

INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"code": {"type": "string"}, "note": {"type": "string"}},
    "required": ["code"],
}

NEXT = "The page renders it in the browser; the result reaches you on your next turn."
NOT_A_DESIGN = "scad_draft only works in a conversation started from the Designs page. Answer in text instead."


def refusal(message: str) -> dict[str, Any]:
    return {"saved": False, "error": message}


def make_handler(store: Store, max_source_bytes: int):
    async def scad_draft(payload: Mapping[str, Any], context: Any) -> dict[str, Any]:
        options = context.run_options or {}
        design_id = options.get("design_id")
        phase = options.get("phase", "draft")
        if not isinstance(design_id, str) or not ID.fullmatch(design_id) or not context.thread_id:
            return refusal(NOT_A_DESIGN)
        if phase == "finalize":
            return refusal("This is the finalize run: build the part with cad_build instead of drafting.")
        code = payload.get("code")
        if not isinstance(code, str) or not code.strip():
            return refusal("code must be the whole OpenSCAD file.")
        if len(code.encode("utf-8")) > max_source_bytes:
            return refusal(f"The file is over {max_source_bytes:,} bytes; make it shorter.")
        owner = context.principal.user_id
        try:
            design = await asyncio.to_thread(store.get_design, owner, design_id)
            if design["thread_id"] != context.thread_id:
                return refusal(NOT_A_DESIGN)
            version = await asyncio.to_thread(
                store.add_version,
                owner,
                design_id,
                parent_id=design["head_version_id"],
                source="repair" if phase == "repair" else "model",
                scad=code,
                params=parse_params(code),
                run_id=context.run_id,
                thread_id=context.thread_id,
            )
        except NotFound:
            return refusal(NOT_A_DESIGN)
        except Conflict as exc:
            return refusal(str(exc))
        return {"version_id": version["id"], "seq": version["seq"], "next": NEXT}

    return scad_draft
