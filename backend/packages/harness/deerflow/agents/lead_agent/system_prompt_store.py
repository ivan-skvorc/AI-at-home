"""Persistence for a user-authored lead-agent system prompt (fork feature).

The built-in prompt lives in :data:`deerflow.agents.lead_agent.prompt.SYSTEM_PROMPT_TEMPLATE`.
Operators can inspect it and replace it from **Settings → System Prompt** in the
web UI; the replacement is stored as a single Markdown file at
``{base_dir}/SYSTEM_PROMPT.md``, next to ``USER.md``.

Two rules shape this module:

* **A saved override may change a run, never break one.** Everything written
  through :func:`save_custom_system_prompt` is validated first, and
  :func:`resolve_system_prompt_template` still re-validates on read so a file
  hand-edited on disk (or written by an older version) degrades to the built-in
  template instead of raising inside the agent build.
* **The allowed placeholder set is derived, not duplicated.** Callers pass the
  built-in template's own field names as ``allowed``, so adding a placeholder to
  the template automatically permits it here with no second list to update.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from string import Formatter

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

# Filename of the override, stored alongside USER.md in the base directory.
SYSTEM_PROMPT_FILENAME = "SYSTEM_PROMPT.md"

# Upper bound on a stored template. The prompt is prepended to every run, so a
# runaway paste is a per-turn token cost; this is a sanity bound, not a budget.
MAX_TEMPLATE_CHARS = 200_000


class SystemPromptTemplateError(ValueError):
    """A system prompt template is malformed or uses an unknown placeholder."""


def custom_system_prompt_path() -> Path:
    """Path to the override file: ``{base_dir}/SYSTEM_PROMPT.md``."""
    return get_paths().base_dir / SYSTEM_PROMPT_FILENAME


def extract_placeholders(template: str) -> frozenset[str]:
    """Return the ``str.format`` field names used by *template*.

    Escaped braces (``{{`` / ``}}``) are literals and yield no field. A
    malformed template raises :class:`SystemPromptTemplateError` rather than the
    bare ``ValueError`` that :class:`string.Formatter` produces.
    """
    try:
        fields = [field for _, field, _, _ in Formatter().parse(template) if field is not None]
    except ValueError as exc:
        raise SystemPromptTemplateError(f"Malformed template: {exc}") from exc
    return frozenset(fields)


def validate_system_prompt_template(template: str, *, allowed: Iterable[str]) -> None:
    """Raise :class:`SystemPromptTemplateError` unless *template* is renderable.

    A template is accepted when it is non-empty, within
    :data:`MAX_TEMPLATE_CHARS`, parses as a format string, and uses only bare
    field names drawn from *allowed*. Using a *subset* is fine — dropping
    ``{skills_section}`` is a legitimate way to strip that block from the
    prompt — but an unknown name would raise ``KeyError`` at render time, and a
    positional or dotted field would raise ``IndexError`` / expose object
    internals, so all three are refused here.
    """
    if not template or not template.strip():
        raise SystemPromptTemplateError("The system prompt cannot be empty.")
    if len(template) > MAX_TEMPLATE_CHARS:
        raise SystemPromptTemplateError(f"The system prompt is too long ({len(template)} characters; the maximum is {MAX_TEMPLATE_CHARS}).")

    allowed_set = frozenset(allowed)
    for field in extract_placeholders(template):
        if field == "":
            raise SystemPromptTemplateError("Positional placeholders like `{}` are not supported. Use a named placeholder, or escape a literal brace as `{{`.")
        if not field.isidentifier():
            raise SystemPromptTemplateError(f"Unsupported placeholder `{{{field}}}`. Only bare names are allowed — attribute access, indexing, and positional fields are not.")
        if field not in allowed_set:
            available = ", ".join(sorted(allowed_set))
            raise SystemPromptTemplateError(f"Unknown placeholder `{{{field}}}`. Available placeholders: {available}. To write a literal brace, escape it as `{{{{`.")

    # Field names alone do not prove renderability: a nested format spec such as
    # `{agent_name:{width}}` parses to the allowed field `agent_name` yet still
    # raises KeyError on the inner `width`. Rendering once with placeholder
    # values settles it, so anything that saves is guaranteed to render — the
    # alternative is a save that appears to succeed while every run silently
    # falls back to the built-in prompt.
    try:
        template.format(**dict.fromkeys(allowed_set, ""))
    except Exception as exc:
        raise SystemPromptTemplateError(f"The template could not be rendered: {exc}") from exc


def load_custom_system_prompt() -> str | None:
    """Return the stored override, or ``None`` when there is none.

    A missing file, an unreadable file, and a blank file are all "no override".
    """
    path = custom_system_prompt_path()
    try:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read the custom system prompt at %s: %s", path, exc)
        return None
    return content if content.strip() else None


def save_custom_system_prompt(content: str, *, allowed: Iterable[str]) -> None:
    """Validate *content* and persist it atomically as the override.

    Raises :class:`SystemPromptTemplateError` before touching the filesystem, so
    a rejected edit never leaves a partial or invalid file behind.
    """
    validate_system_prompt_template(content, allowed=allowed)
    path = custom_system_prompt_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Never leave a stray .tmp beside the user's state; it would be carried
        # into the next `make backup` and read as a real file.
        tmp.unlink(missing_ok=True)
        raise
    logger.info("Saved a custom lead-agent system prompt to %s (%d characters)", path, len(content))


def clear_custom_system_prompt() -> bool:
    """Delete the override, reverting to the built-in template.

    Returns ``True`` when a file was removed and ``False`` when there was
    nothing to remove, so the caller can distinguish a reset from a no-op.
    """
    path = custom_system_prompt_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    logger.info("Removed the custom lead-agent system prompt at %s", path)
    return True


def resolve_system_prompt_template(default: str) -> str:
    """Return the template to render: the override when usable, else *default*.

    The override is re-validated against *default*'s own placeholders on every
    read. That covers the file being hand-edited on disk, restored from a
    backup, or written by a version whose template had a placeholder this one
    no longer provides — in each case the run continues on the built-in prompt
    with a warning rather than failing to build the agent.
    """
    content = load_custom_system_prompt()
    if content is None:
        return default
    try:
        validate_system_prompt_template(content, allowed=extract_placeholders(default))
    except SystemPromptTemplateError as exc:
        logger.warning("Ignoring the custom system prompt at %s: %s", custom_system_prompt_path(), exc)
        return default
    return content
