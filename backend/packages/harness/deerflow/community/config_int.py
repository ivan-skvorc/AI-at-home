"""Shared integer coercion for community provider ``tools:`` entries.

Four providers carried the same function under three names
(``browser_automation._as_int``, ``browserless._as_int``,
``camoufox_fetch._coerce_int``, ``jina_ai._coerce_timeout``). A tool entry's
extra fields arrive from ``config.yaml`` untyped and a ``$NAME`` substitution is
always a string, so a decimal string is accepted. Bounds and units stay with the
provider that reads the value.
"""

from __future__ import annotations


def coerce_int(value: object, default: int) -> int:
    """Return ``value`` as an int, or ``default`` when it is not an int or a decimal string.

    Booleans fall back to ``default`` rather than reading as 0 or 1, because a
    YAML ``off`` would otherwise become a zero timeout. Floats also fall back,
    so a fractional value is never truncated silently.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default
