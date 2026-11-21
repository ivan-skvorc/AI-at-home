"""Shared boolean coercion for community provider ``tools:`` entries.

Seven providers (``browser_automation``, ``browserless``, ``crawl4ai``, ``exa``,
``fastcrw``, ``firecrawl``, ``jina_ai``) carried byte-identical copies of this
function. A tool entry's extra fields arrive from ``config.yaml`` untyped, and a
``$NAME`` substitution is always a string, so ``"false"`` must read as false
rather than as a non-empty string; ``bool("false")`` is true.
"""

from __future__ import annotations

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off"})


def coerce_bool(value: object, default: bool) -> bool:
    """Return ``value`` as a bool, or ``default`` when it is neither a bool nor a known string.

    Strings are compared case-insensitively after trimming. Any other type,
    including integers, falls back to ``default``, so a typo never flips a
    safety setting such as ``network_isolation_confirmed``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True
        if normalized in _FALSE_STRINGS:
            return False
    return default
