"""Which Grok API feature each xAI tool needs (fork feature).

A pure mapping with no I/O, so ``get_available_tools`` can filter on it while
assembling a run. Keyed by the tool's ``use:`` path rather than its configured
``name:``, because an operator may rename a tool entry but cannot make one
module path mean another tool.
"""

from __future__ import annotations

TOOL_FEATURES: dict[str, str] = {
    "deerflow.community.xai.tools:grok_generate_image_tool": "image",
    "deerflow.community.xai.tools:grok_edit_image_tool": "image",
    "deerflow.community.xai.tools:grok_generate_video_tool": "video",
    "deerflow.community.xai.tools:x_search_tool": "x_search",
}


def required_grok_feature(use: str) -> str | None:
    """The Grok feature a configured tool needs, or None for any other tool."""
    return TOOL_FEATURES.get(use)
