"""Parse-only syntax checks for files the agent writes.

Nothing here executes the content: Python goes through ``ast.parse``, JSON
through ``json.loads``, YAML through ``yaml.compose_all`` (node composition,
so unknown tags such as CloudFormation's ``!Ref`` are not errors) and TOML
through ``tomllib``. Two shapes that are valid in practice but fail a strict
parser are accepted on purpose: JSON with comments and trailing commas
(``tsconfig.json``, VS Code settings) and templated YAML (Helm charts, Jinja),
because a false "your file is broken" costs the model a turn of second-guessing
a correct file.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import PurePosixPath

import yaml

# Large generated files are not worth parsing on the write path.
MAX_CHECK_BYTES = 2 * 1024 * 1024

_CHECKED_SUFFIXES = frozenset({".py", ".pyi", ".json", ".yaml", ".yml", ".toml"})
_TEMPLATE_MARKERS = ("{{", "{%")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def is_checked_path(path: str) -> bool:
    """Return True when :func:`check_syntax` knows the file's format."""
    return PurePosixPath(path.replace("\\", "/")).suffix.lower() in _CHECKED_SUFFIXES


def _strip_json_comments(text: str) -> str:
    """Drop ``//`` and ``/* */`` comments outside strings, then trailing commas."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return _TRAILING_COMMA_RE.sub(r"\1", "".join(out))


def _check_json(content: str) -> str | None:
    try:
        json.loads(content)
        return None
    except json.JSONDecodeError as strict_error:
        try:
            json.loads(_strip_json_comments(content))
            return None  # JSON with comments: valid for the tools that read it.
        except json.JSONDecodeError:
            return f"Invalid JSON at line {strict_error.lineno}, column {strict_error.colno}: {strict_error.msg}"


def _check_yaml(content: str) -> str | None:
    if any(marker in content for marker in _TEMPLATE_MARKERS):
        return None  # A template is not YAML until it is rendered.
    try:
        for _ in yaml.compose_all(content, Loader=yaml.SafeLoader):
            pass
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        return f"Invalid YAML{where}: {e.problem or e}"
    except yaml.YAMLError as e:
        return f"Invalid YAML: {e}"
    return None


def check_syntax(path: str, content: str) -> str | None:
    """Return a one-line description of the first syntax error, or ``None``.

    ``None`` also means "not checked": an unknown suffix, empty content, a file
    over :data:`MAX_CHECK_BYTES`, or a parser that failed for a reason other
    than the content's syntax (recursion depth on pathological nesting).
    """
    if not path or not content or not content.strip():
        return None
    if len(content) > MAX_CHECK_BYTES:
        return None
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    try:
        if suffix in (".py", ".pyi"):
            try:
                ast.parse(content, filename=path)
            except SyntaxError as e:
                return f"Python syntax error at line {e.lineno}, column {e.offset}: {e.msg}"
            except ValueError as e:  # e.g. a NUL byte in the source
                return f"Python source error: {e}"
            return None
        if suffix == ".json":
            return _check_json(content)
        if suffix in (".yaml", ".yml"):
            return _check_yaml(content)
        if suffix == ".toml":
            try:
                tomllib.loads(content)
            except tomllib.TOMLDecodeError as e:
                return f"Invalid TOML: {e}"
            return None
    except (RecursionError, MemoryError):
        return None
    return None


def syntax_advisory(path: str, content: str) -> str | None:
    """The note a successful write appends when the written file does not parse."""
    error = check_syntax(path, content)
    if error is None:
        return None
    return f"Warning: {path} does not parse after this write. {error}. If you are still writing the file in parts, continue; otherwise fix it before running it."
