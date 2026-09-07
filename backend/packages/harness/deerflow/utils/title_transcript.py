"""Extract the visible conversation opening a title can be written from.

The automatic rename (FORK.md §33) titles a thread from its first exchange
while the run is still in memory. The **manual** rename (FORK.md §38) has no
run: it reads a persisted checkpoint back and has to reconstruct what the user
actually saw, which is a narrower thing than what the graph stored.

Three kinds of message live in a thread's ``messages`` channel and only one of
them belongs in a title prompt:

* ``ToolMessage`` results — in an Ultra turn these carry the *whole* subagent
  conversation, tens of kilobytes of model-to-model deliberation the user never
  opened. Titling from those describes the debate rather than the answer, so
  they are dropped outright.
* AI messages with no text — tool-call scaffolding. Real in the transcript,
  invisible on screen.
* ``hide_from_ui`` messages — dynamic-context reminders, skill activations,
  goal bookkeeping, hidden human-input replies.

What is left is the pair the user reads: their prompt, and the final answer
that ended the turn.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from deerflow.utils.llm_text import strip_think_blocks
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, get_original_user_content_text

#: How many opening exchanges a title is written from. Two is enough to tell a
#: follow-up-shaped conversation ("and now in Rust") from a one-shot question,
#: and short enough that the prompt stays cheap on any model.
DEFAULT_EXCHANGE_LIMIT = 2

#: Control messages the UI filters out by ``name``. Kept in step with
#: ``frontend/src/core/messages/utils.ts::HIDDEN_CONTROL_MESSAGE_NAMES`` — a name
#: that drifts apart here shows up as a title written from a summary block.
HIDDEN_CONTROL_MESSAGE_NAMES = frozenset({"summary", "loop_warning", "todo_reminder", "todo_completion_reminder"})

_SLASH_SKILL_ACTIVATION_TAG = "<slash_skill_activation>"


@dataclass(frozen=True)
class VisibleExchange:
    """One prompt and the answer the user saw for it."""

    user_text: str
    assistant_text: str


def _attr(message: Any, key: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(key, default)
    return getattr(message, key, default)


def _additional_kwargs(message: Any) -> Mapping[str, Any]:
    kwargs = _attr(message, "additional_kwargs")
    return kwargs if isinstance(kwargs, Mapping) else {}


def _message_type(message: Any) -> str | None:
    message_type = _attr(message, "type")
    if message_type is None and isinstance(message, Mapping):
        message_type = message.get("role")
    if message_type == "user":
        return "human"
    if message_type == "assistant":
        return "ai"
    return message_type if isinstance(message_type, str) else None


def normalize_content(content: Any) -> str:
    """Flatten LangChain content (str / block list / dict) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [normalize_content(item) for item in content]
        return "\n".join(part for part in parts if part)
    if isinstance(content, Mapping):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value
        nested = content.get("content")
        if nested is not None:
            return normalize_content(nested)
    return ""


def _is_hidden(message: Any) -> bool:
    if _additional_kwargs(message).get("hide_from_ui") is True:
        return True
    name = _attr(message, "name")
    return isinstance(name, str) and name in HIDDEN_CONTROL_MESSAGE_NAMES


def _user_text(message: Any) -> str:
    """The user's own words, before any middleware rewrote them for the model."""
    additional_kwargs = _additional_kwargs(message)
    content = _attr(message, "content", "")
    if isinstance(additional_kwargs.get(ORIGINAL_USER_CONTENT_KEY), str):
        return get_original_user_content_text(content, additional_kwargs).strip()
    return normalize_content(content).strip()


def _is_visible_user_message(message: Any) -> bool:
    if _message_type(message) != "human" or _is_hidden(message):
        return False
    # A ``/skill``-only turn is a control message the composer sends on the
    # user's behalf; it carries no prompt of its own.
    text = _user_text(message)
    return not (_SLASH_SKILL_ACTIVATION_TAG in text and not text.replace(_SLASH_SKILL_ACTIVATION_TAG, "").strip())


def _visible_assistant_text(message: Any) -> str:
    """Text of an AI message the user saw, or ``""`` for anything else.

    Tool messages never reach this function — they are filtered by type before
    it, which is what keeps an Ultra turn's subagent transcript out of the
    prompt no matter how much of it the tool result carries.
    """
    if _message_type(message) != "ai" or _is_hidden(message):
        return ""
    return strip_think_blocks(normalize_content(_attr(message, "content", "")), truncate_unclosed=False).strip()


def extract_visible_exchanges(
    messages: Sequence[Any] | None,
    *,
    limit: int = DEFAULT_EXCHANGE_LIMIT,
) -> list[VisibleExchange]:
    """Return the first *limit* prompt/answer pairs a reader would recognize.

    The answer for a turn is the **last** AI message carrying text before the
    next visible user message: on a tool-using turn the earlier ones are
    scaffolding, and on an Ultra turn everything between them is subagent
    chatter that lives in tool results. An exchange with no answer yet (a run
    still in flight, or a cancelled one) is still returned, with an empty
    ``assistant_text`` — a conversation with one unanswered prompt is
    nameable, just from less.
    """
    if limit <= 0 or not messages:
        return []

    exchanges: list[VisibleExchange] = []
    pending_user: str | None = None
    pending_assistant = ""

    def flush() -> bool:
        """Close the open turn. Returns whether there is room for another."""
        nonlocal pending_user, pending_assistant
        if pending_user is not None:
            exchanges.append(VisibleExchange(user_text=pending_user, assistant_text=pending_assistant))
        pending_user = None
        pending_assistant = ""
        return len(exchanges) < limit

    for message in messages:
        if _is_visible_user_message(message):
            if not flush():
                return exchanges
            pending_user = _user_text(message)
            continue
        if pending_user is None:
            continue
        text = _visible_assistant_text(message)
        if text:
            # Last one wins: the final answer replaces the scaffolding before it.
            pending_assistant = text

    flush()
    return exchanges


def render_exchanges(exchanges: Sequence[VisibleExchange], *, max_chars_per_message: int = 500) -> str:
    """Render exchanges as the transcript block sent to the title model."""
    lines: list[str] = []
    for index, exchange in enumerate(exchanges, start=1):
        lines.append(f"### Exchange {index}")
        lines.append(f"User: {exchange.user_text[:max_chars_per_message]}")
        if exchange.assistant_text:
            lines.append(f"Assistant: {exchange.assistant_text[:max_chars_per_message]}")
        else:
            lines.append("Assistant: (no answer yet)")
    return "\n".join(lines)
