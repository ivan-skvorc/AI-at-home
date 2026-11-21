"""Shared reasoning capture for providers that preserve a reasoning string.

``patched_mimo`` and ``patched_stepfun`` both wrap ``ChatOpenAI`` so a provider's
``reasoning_content`` survives multi-turn tool calls. They used to carry
identical copies of every mechanical step that job needs: attach a reasoning
string to a LangChain message without mutating the message the caller still
holds, read ``choices[index].message`` out of a response object that may not be
shaped like that at all (dict payloads, SDK objects, or a chunk with no
choices), look the field up on a dict, an SDK object or its ``model_extra``, and
copy it onto streamed chunks and non-streamed generations.

``ReasoningCaptureChatOpenAI`` owns those steps. Which fields a provider reads,
and in what order, is its dialect and stays on the provider as
``reasoning_fields``: MiMo reads ``reasoning_content``, StepFun reads
``reasoning_content`` and then ``reasoning``. ``patched_minimax`` merges streamed
deltas and ``patched_deepseek`` / ``vllm_provider`` read other spellings, so they
keep their own handling. A fix to any shared step lands once instead of per
provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from deerflow.models.openai_response import GuardedChatOpenAI

#: Returned by :func:`extract_reasoning` when no listed field holds a value. An
#: empty string is a value and is kept.
MISSING_REASONING = object()


def with_reasoning_content(message: AIMessage | AIMessageChunk, reasoning: str) -> AIMessage | AIMessageChunk:
    """Return a copy of ``message`` carrying ``reasoning`` in ``additional_kwargs``.

    The incoming message is never modified: LangChain hands the same object to
    callbacks, run journals and the caller's history, so an in-place write would
    leak reasoning into a message that was already emitted. A copy is returned
    whether or not the value changed, keeping the result's identity predictable
    for callers that replay messages through ``model_copy``.
    """
    additional_kwargs = dict(message.additional_kwargs)
    if additional_kwargs.get("reasoning_content") != reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def typed_choice_message(response: Any, index: int) -> Any:
    """Return ``response.choices[index].message`` when that shape exists, else ``None``.

    Non-streaming results arrive either as a dict payload (no attribute access)
    or as an SDK object whose choice list may be shorter than the index the
    caller is replaying. Neither case is an error for the callers here: they
    fall back to the payload they already have, so this reports "nothing typed"
    rather than raising.
    """
    choices = getattr(response, "choices", None)
    if choices is None:
        return None
    try:
        return choices[index].message
    except (AttributeError, IndexError, TypeError):
        return None


def extract_reasoning(value: Any, fields: tuple[str, ...]) -> str | object:
    """Return the first non-null field of ``fields`` from a dict or an SDK object.

    A mapping is read by key. An object is read by attribute and then through
    its pydantic ``model_extra``, where some SDK versions keep fields they do
    not model. ``None`` counts as absent; ``MISSING_REASONING`` reports that no
    field held a value.
    """
    if isinstance(value, Mapping):
        for field in fields:
            if field in value and value[field] is not None:
                return value[field]
        return MISSING_REASONING

    for field in fields:
        attr = getattr(value, field, MISSING_REASONING)
        if attr is not MISSING_REASONING and attr is not None:
            return attr

    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, Mapping):
        for field in fields:
            if field in model_extra and model_extra[field] is not None:
                return model_extra[field]

    return MISSING_REASONING


class ReasoningCaptureChatOpenAI(GuardedChatOpenAI):
    """``GuardedChatOpenAI`` that copies a provider's reasoning field onto its results.

    A subclass names the response fields it reads in ``reasoning_fields``, in
    priority order. Streaming deltas and non-streamed ``choices[].message``
    values are both captured into ``additional_kwargs["reasoning_content"]``.
    """

    reasoning_fields: ClassVar[tuple[str, ...]] = ("reasoning_content",)

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta") or {}
            reasoning = extract_reasoning(delta, self.reasoning_fields)
            if reasoning is not MISSING_REASONING and isinstance(generation_chunk.message, AIMessageChunk):
                generation_chunk = ChatGenerationChunk(
                    message=with_reasoning_content(generation_chunk.message, reasoning),
                    generation_info=generation_chunk.generation_info,
                )

        return generation_chunk

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            choice = choices[index] if index < len(choices) else {}
            choice_message = choice.get("message", {}) if isinstance(choice, Mapping) else {}
            reasoning = extract_reasoning(choice_message, self.reasoning_fields)
            if reasoning is MISSING_REASONING and not isinstance(response, dict):
                reasoning = extract_reasoning(typed_choice_message(response, index), self.reasoning_fields)

            message = generation.message
            if reasoning is not MISSING_REASONING and isinstance(message, AIMessage):
                if patched_generations is None:
                    patched_generations = list(result.generations)
                patched_generations[index] = ChatGeneration(
                    message=with_reasoning_content(message, reasoning),
                    generation_info=generation.generation_info,
                )

        return ChatResult(generations=patched_generations or result.generations, llm_output=result.llm_output)
