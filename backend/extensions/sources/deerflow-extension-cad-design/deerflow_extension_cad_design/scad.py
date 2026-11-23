"""Text-only helpers for OpenSCAD source. Nothing here evaluates the code."""

from __future__ import annotations

import difflib
import re
from typing import Any

#: ``name = <number|true|false>;`` with an optional Customizer comment, at the start of a line.
_ASSIGNMENT = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|true|false)\s*;")
MAX_PARAMS = 100


def _depth_changes(line: str, in_block: bool) -> tuple[int, bool]:
    """The bracket depth a line adds, skipping comments and strings, and whether a block comment stays open."""
    depth = 0
    index = 0
    in_string = False
    while index < len(line):
        pair = line[index : index + 2]
        char = line[index]
        if in_block:
            if pair == "*/":
                in_block = False
                index += 2
                continue
        elif in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif pair == "//":
            break
        elif pair == "/*":
            in_block = True
            index += 2
            continue
        elif char == '"':
            in_string = True
        elif char in "{([":
            depth += 1
        elif char in "})]":
            depth -= 1
        index += 1
    return depth, in_block


def parse_params(code: str) -> dict[str, Any]:
    """Top-level numeric and boolean assignments, in file order; the last one of a name wins."""
    params: dict[str, Any] = {}
    depth = 0
    in_block = False
    for line in code.splitlines():
        if depth == 0 and not in_block:
            match = _ASSIGNMENT.match(line)
            if match and (match.group(1) in params or len(params) < MAX_PARAMS):
                raw = match.group(2)
                value: Any = raw == "true" if raw in ("true", "false") else float(raw)
                if isinstance(value, float) and value.is_integer() and re.fullmatch(r"-?\d+", raw):
                    value = int(value)
                params[match.group(1)] = value
        change, in_block = _depth_changes(line, in_block)
        depth = max(0, depth + change)
    return params


def capped_diff(before: str, after: str, limit: int) -> tuple[str, bool]:
    """A unified diff of two files, cut at ``limit`` characters on a line boundary. Returns (text, complete)."""
    lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "model", "now", n=1, lineterm=""))
    text = ""
    for line in lines:
        if len(text) + len(line) + 1 > limit:
            return text, False
        text += line + "\n"
    return text, True
