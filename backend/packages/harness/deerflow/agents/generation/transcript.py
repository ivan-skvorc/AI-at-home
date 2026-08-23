"""Turn stored run events and scheduled tasks into compact analysis transcripts.

Pure functions only: no IO, no config lookups, no LLM calls. The gateway route
fetches rows and passes them here, which keeps the size/shape decisions — the
part most likely to regress a prompt — unit-testable without a store.

Why digest at all: a single thread in this product can carry hundreds of turns
and multi-megabyte tool payloads (a ``bash`` transcript, a ``write_file`` body).
The analysis needs to know *what kind of work* a conversation was, not to replay
it, so each source is reduced to recent human/assistant turns plus the names of
the tools the assistant reached for, then capped twice — per message and per
source — before anything is concatenated into one prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from deerflow.utils.messages import message_to_text

# Appended wherever content was dropped, so the model can tell a short
# conversation apart from a long one it is only seeing the tail of.
TRUNCATION_MARKER = " …[truncated]"
OMITTED_PREFIX_MARKER = "…[earlier messages omitted]"

# Event types persisted with category="message". Tool results are deliberately
# excluded: their bodies are the bulk of a transcript's bytes and the assistant
# turn that called the tool already names it.
HUMAN_EVENT_TYPES = frozenset({"llm.human.input"})
AI_EVENT_TYPES = frozenset({"llm.ai.response"})


# Every block tag this module wraps model-bound content in. A tag listed here is
# escaped out of the content itself, so a transcript or a user-typed goal cannot
# forge the structure the prompt uses to separate framework text from quoted
# input. Adding a block tag to a prompt means adding it here, and classifying it
# in ``tests/test_input_sanitization_middleware.py``'s anti-drift guard.
BLOCK_TAG_NAMES: tuple[str, ...] = ("source", "goal", "draft")

# Matches an opening or closing delimiter for any of the tags above, with the
# same tolerance for whitespace and attributes that the production blocked-tag
# pattern uses — so a spaced or attributed forgery cannot slip past.
_BLOCK_DELIMITER_RE = re.compile(r"<\s*/?\s*(?:" + "|".join(BLOCK_TAG_NAMES) + r")\b[^>]*>?", re.IGNORECASE)


def neutralize_block_delimiters(text: str) -> str:
    """Render any prompt block delimiter in ``text`` inert.

    Escapes only the delimiter shapes in :data:`BLOCK_TAG_NAMES` rather than every
    angle bracket: transcripts and goals routinely contain code and markup, and
    mangling all of it would cost the analysis the very signal it is reading for.
    """
    return _BLOCK_DELIMITER_RE.sub(lambda match: match.group(0).replace("<", "&lt;").replace(">", "&gt;"), text)


def escape_block_attribute(value: str) -> str:
    """Make a value safe to interpolate into a double-quoted block attribute."""
    return neutralize_block_delimiters(value).replace('"', "&quot;")


@dataclass(frozen=True)
class SourceTranscript:
    """One digested conversation or scheduled task, ready to embed in a prompt."""

    kind: str
    source_id: str
    title: str
    body: str

    def render(self) -> str:
        """Render as a labelled block for the analysis prompt.

        Every interpolated value is neutralized first. The body is the user's own
        conversation text, so without this a message containing ``</source>``
        would close the block early and whatever followed would read to the model
        as prompt structure rather than as quoted history. This one-shot analysis
        call does not pass through ``InputSanitizationMiddleware`` (which only
        rewrites the lead agent's ``ModelRequest``), so the escaping has to happen
        here, where the delimiter is introduced. The same escaping covers the
        user-typed goal and a draft carried back in for revision.
        """
        header = f'<source kind="{escape_block_attribute(self.kind)}" id="{escape_block_attribute(self.source_id)}" title="{escape_block_attribute(self.title)}">'
        return f"{header}\n{neutralize_block_delimiters(self.body)}\n</source>"


def truncate(text: str, limit: int, *, marker: str = TRUNCATION_MARKER) -> str:
    """Clip ``text`` to ``limit`` characters, flagging that content was dropped.

    The marker is appended *after* clipping rather than budgeted into ``limit``,
    so a caller's per-message cap stays the cap on real content and two messages
    clipped at the same limit produce the same amount of signal.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + marker


def _tool_call_names(content: Any) -> list[str]:
    """Names of the tools an assistant turn called, in order, without duplicates."""
    if not isinstance(content, Mapping):
        return []
    raw = content.get("tool_calls")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    names: list[str] = []
    for call in raw:
        name = call.get("name") if isinstance(call, Mapping) else None
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name.strip())
    return names


def _row_line(row: Mapping[str, Any], *, max_chars_per_message: int) -> str | None:
    """Render one persisted message row as a single ``Role: text`` line."""
    event_type = row.get("event_type")
    content = row.get("content")

    if event_type in HUMAN_EVENT_TYPES:
        text = message_to_text(content).strip()
        if not text:
            return None
        return f"User: {truncate(text, max_chars_per_message)}"

    if event_type in AI_EVENT_TYPES:
        text = message_to_text(content).strip()
        tools = _tool_call_names(content)
        parts: list[str] = []
        if text:
            parts.append(truncate(text, max_chars_per_message))
        if tools:
            parts.append(f"[called tools: {', '.join(tools)}]")
        if not parts:
            return None
        return "Assistant: " + " ".join(parts)

    return None


def format_message_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_messages: int,
    max_chars_per_message: int,
    max_chars_per_source: int,
) -> str:
    """Digest persisted message rows into a plain-text transcript.

    ``rows`` arrive oldest-first (the store's documented ordering). The most
    recent ``max_messages`` renderable turns are kept, because how a
    conversation *ended up* being worked is more diagnostic of the user's
    recurring need than how it opened.
    """
    lines: list[str] = []
    for row in rows:
        line = _row_line(row, max_chars_per_message=max_chars_per_message)
        if line is not None:
            lines.append(line)

    omitted = len(lines) > max_messages
    if omitted:
        lines = lines[-max_messages:]
    if omitted:
        lines.insert(0, OMITTED_PREFIX_MARKER)

    return truncate("\n".join(lines).strip(), max_chars_per_source)


def format_scheduled_task(
    task: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    *,
    max_runs: int,
    max_chars_per_source: int,
) -> str:
    """Digest a scheduled task and its recent runs into a plain-text summary.

    A scheduled task is already a distilled statement of recurring intent — its
    prompt *is* the repeated instruction — so unlike a conversation it is
    rendered in full (subject to the source cap) and the runs contribute only
    their outcome, which is what tells the analysis whether the task is working.
    """
    lines: list[str] = []
    prompt = str(task.get("prompt") or "").strip()
    if prompt:
        lines.append(f"Recurring instruction: {prompt}")

    schedule_type = str(task.get("schedule_type") or "").strip()
    if schedule_type:
        spec = task.get("schedule_spec")
        spec_text = f" {spec}" if spec else ""
        lines.append(f"Schedule: {schedule_type}{spec_text}")

    status = str(task.get("status") or "").strip()
    if status:
        lines.append(f"Status: {status}")

    recent = list(runs)[:max_runs]
    if recent:
        lines.append(f"Recent runs ({len(recent)}):")
        for run in recent:
            run_status = str(run.get("status") or "unknown").strip()
            started = str(run.get("started_at") or run.get("created_at") or "").strip()
            error = str(run.get("error") or "").strip()
            suffix = f" — {truncate(error, 200)}" if error else ""
            lines.append(f"- {started or 'unknown time'}: {run_status}{suffix}")

    return truncate("\n".join(lines).strip(), max_chars_per_source)
