"""Keep Claude's preserved thinking valid when DeerFlow edits a conversation.

On models with preserved thinking, Anthropic binds each thinking block to its
prefix: ``system``, ``tools`` and every earlier message. A request that sends a
block back after that prefix changed fails the API's prefix check. Claude
Fable 5.2 answers with a 400 ("The block is bound to a different
conversation"); the other models may answer with a 400 or bill the stale
reasoning. DeerFlow changes the prefix between requests: the durable-context
message sits near the front and changes mid-run, compaction keeps recent turns
behind a new summary, and the date update can move into ``system``.

This module mirrors the check on the client. When Claude answers, the request
that produced the answer is fingerprinted, and the fingerprint is stored on the
answer's ``response_metadata``. Before a later request, every earlier assistant
turn whose prefix no longer matches its fingerprint loses its thinking blocks.
Thinking is left out of every fingerprint, because the API does not compare it
as content. The blocks that are sent must be one unbroken run, each with the
same previous block it had when Claude produced it, so the guard keeps the
newest such run and drops the rest. Leaving thinking out never causes an error;
it costs only the reasoning.

If a request is still rejected, it is retried once with
``prefix_mismatch_behavior: drop_block``, which is Anthropic's documented
recovery. The warning it logs means the mirror missed a change.

Docs: https://platform.claude.com/docs/en/build-with-claude/preserved-thinking/prefix-checks
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextvars import ContextVar
from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

logger = logging.getLogger(__name__)

RECORD_KEY = "deerflow_thinking_binding"
BINDING_BETA = "thinking-binding-controls-2026-08-01"
_BOUND_ERROR = "bound to a different conversation"
_THINKING_TYPES = frozenset({"thinking", "redacted_thinking"})

# The models Anthropic lists under preserved thinking, plus later minor
# versions of the same families. Add a new family here when Anthropic lists it.
_PRESERVED_THINKING_MODEL = re.compile(r"claude-(?:(?:fable|mythos)-5-[1-9]|(?:opus|sonnet|haiku)-5-[5-9])(?:-\d{8})?")

# Carries the record from the payload build to the answer of the same call.
_PENDING_RECORD: ContextVar[dict | None] = ContextVar("deerflow_pending_thinking_record", default=None)


def has_preserved_thinking(model: Any) -> bool:
    return isinstance(model, str) and _PRESERVED_THINKING_MODEL.fullmatch(model) is not None


def _is_thinking(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") in _THINKING_TYPES


def _thinking_id(block: dict) -> str:
    """A stable id for a thinking block: its signature, or a redacted block's data."""
    secret = block.get("signature") if block.get("type") == "thinking" else block.get("data")
    return hashlib.sha256(str(secret or "").encode()).hexdigest()[:32]


def _thinking_ids(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [_thinking_id(block) for block in content if _is_thinking(block)]


def _canonical(value: Any) -> Any:
    """Drop ``cache_control`` markers, which the prefix check ignores."""
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items() if key != "cache_control"}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump(mode="json"))
    return value


def _digest(previous: str, value: Any) -> str:
    text = json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{previous}\n{text}".encode()).hexdigest()


def _without_thinking(message: Any) -> Any:
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        return {**message, "content": [block for block in message["content"] if not _is_thinking(block)]}
    return message


def _prefix_fingerprints(payload: Mapping[str, Any]) -> list[str]:
    """Fingerprint ``i`` covers system, tools and ``messages[:i]``, thinking left out."""
    current = _digest("", {"system": payload.get("system"), "tools": payload.get("tools")})
    fingerprints = [current]
    for message in payload.get("messages") or []:
        current = _digest(current, _without_thinking(message))
        fingerprints.append(current)
    return fingerprints


def records_from_messages(messages: Sequence[BaseMessage]) -> dict[str, dict]:
    """Map the first thinking block of each recorded assistant turn to its record."""
    records: dict[str, dict] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        record = message.response_metadata.get(RECORD_KEY) if isinstance(message.response_metadata, dict) else None
        ids = _thinking_ids(message.content)
        if isinstance(record, dict) and ids:
            records[ids[0]] = record
    return records


def _kept_turns(messages: list, fingerprints: list[str], records: Mapping[str, dict]) -> set[int]:
    """The newest unbroken run of assistant turns whose thinking is still valid."""
    kept: list[int] = []
    last_kept: str | None = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        ids = _thinking_ids(message.get("content"))
        if not ids:
            continue
        record = records.get(ids[0])
        if record is None or record.get("prefix") != fingerprints[index]:
            # Changed, or never recorded: this turn's thinking goes, and the
            # next valid turn starts a new run.
            kept, last_kept = [], None
            continue
        if kept and record.get("previous") != last_kept:
            # Valid on its own, but produced after a different block: only a
            # run that starts here can include it.
            kept = []
        kept.append(index)
        last_kept = ids[-1]
    return set(kept)


def guard_payload(payload: dict, records: Mapping[str, dict]) -> dict:
    """Drop thinking that would fail the prefix check, and return this request's record.

    The payload's message list and the changed messages are replaced, never
    edited in place, because they can share objects with the thread's state.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return {"prefix": _prefix_fingerprints(payload)[-1], "previous": None}

    if has_preserved_thinking(payload.get("model")):
        fingerprints = _prefix_fingerprints(payload)
        kept = _kept_turns(messages, fingerprints, records)
        guarded: list = []
        dropped = 0
        for index, message in enumerate(messages):
            if index not in kept and isinstance(message, dict) and message.get("role") == "assistant" and _thinking_ids(message.get("content")):
                stripped = _without_thinking(message)
                if stripped["content"]:
                    message = stripped
                    dropped += 1
                # A turn that held only thinking keeps it: an empty turn is
                # rejected outright, and the drop_block retry covers a mismatch.
            guarded.append(message)
        if dropped:
            logger.debug("Left out the thinking of %d earlier turn(s) whose prefix changed", dropped)
            payload["messages"] = guarded
            messages = guarded

    previous = None
    for message in messages:
        if isinstance(message, dict):
            ids = _thinking_ids(message.get("content"))
            if ids:
                previous = ids[-1]
    return {"prefix": _prefix_fingerprints(payload)[-1], "previous": previous}


def drop_block_retry_payload(payload: Mapping[str, Any], error: Exception) -> dict | None:
    """The payload to retry a prefix-check rejection with, or ``None`` to re-raise."""
    if _BOUND_ERROR not in str(error):
        return None
    thinking = payload.get("thinking")
    # Sending block_binding with thinking off is itself a 400.
    if not isinstance(thinking, Mapping) or thinking.get("type") not in ("adaptive", "enabled") or "block_binding" in thinking:
        return None
    retry = dict(payload)
    retry["thinking"] = {**thinking, "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
    betas = list(payload.get("betas") or [])
    if BINDING_BETA not in betas:
        betas.append(BINDING_BETA)
    retry["betas"] = betas
    return retry


def _attach(message: BaseMessage, holder: Mapping[str, Any]) -> None:
    record = holder.get("record")
    if record is not None:
        message.response_metadata[RECORD_KEY] = record


class PreservedThinkingMixin:
    """Records each answer's prefix and guards later requests. Put it before ``ChatAnthropic``.

    A subclass calls ``_guard_preserved_thinking`` as the last step of its
    ``_get_request_payload``, so the fingerprint covers the payload as sent.
    """

    def _guard_preserved_thinking(self, payload: dict, input_: Any) -> dict:
        messages = self._convert_input(input_).to_messages()  # type: ignore[attr-defined]
        record = guard_payload(payload, records_from_messages(messages))
        holder = _PENDING_RECORD.get()
        if holder is not None:
            holder["record"] = record
        return payload

    def _finish_drop_block_payload(self, payload: dict) -> dict:
        """Hook for a subclass that must adjust ``betas`` again (OAuth)."""
        return payload

    def _retry_payload(self, payload: dict, error: Exception) -> dict | None:
        retry = drop_block_retry_payload(payload, error)
        if retry is None:
            return None
        logger.warning("Anthropic rejected thinking blocks as bound to a different conversation; retrying once with drop_block. The preserved-thinking guard missed a prefix change.")
        return self._finish_drop_block_payload(retry)

    def _create(self, payload: dict) -> Any:
        try:
            return super()._create(payload)  # type: ignore[misc]
        except anthropic.BadRequestError as error:
            retry = self._retry_payload(payload, error)
            if retry is None:
                raise
            return super()._create(retry)  # type: ignore[misc]

    async def _acreate(self, payload: dict) -> Any:
        try:
            return await super()._acreate(payload)  # type: ignore[misc]
        except anthropic.BadRequestError as error:
            retry = self._retry_payload(payload, error)
            if retry is None:
                raise
            return await super()._acreate(retry)  # type: ignore[misc]

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        holder: dict = {}
        _PENDING_RECORD.set(holder)
        result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)  # type: ignore[misc]
        for generation in result.generations:
            _attach(generation.message, holder)
        return result

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        holder: dict = {}
        _PENDING_RECORD.set(holder)
        result = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)  # type: ignore[misc]
        for generation in result.generations:
            _attach(generation.message, holder)
        return result

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        holder: dict = {}
        _PENDING_RECORD.set(holder)
        first = True
        for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):  # type: ignore[misc]
            if first:
                # Only the first chunk carries it: merging two chunks that
                # both held the record would concatenate its strings.
                _attach(chunk.message, holder)
                first = False
            yield chunk

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        holder: dict = {}
        _PENDING_RECORD.set(holder)
        first = True
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):  # type: ignore[misc]
            if first:
                _attach(chunk.message, holder)
                first = False
            yield chunk


class GuardedChatAnthropic(PreservedThinkingMixin, ChatAnthropic):
    """``ChatAnthropic`` with the preserved-thinking guard.

    ``create_chat_model`` builds this class for ``use: langchain_anthropic:ChatAnthropic``.
    """

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        return self._guard_preserved_thinking(payload, input_)
