"""Inference using explicitly connected subscriptions, without API billing fallback.

Credentials are resolved for each request and remain outside serializable model
state. The ChatGPT transport uses the public Sign in with ChatGPT Responses API;
the legacy Codex CLI transport and its authentication remain separate.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from copy import deepcopy
from typing import Any, ClassVar

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel, agenerate_from_stream, generate_from_stream
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables.config import RunnableConfig, ensure_config
from langchain_openai import ChatOpenAI

from deerflow.agents.interaction_policy import resolve_run_interaction_policy
from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content
from deerflow.models.openai_codex_provider import CodexChatModel

USER_AGENT = "DeerFlow/subscription-models"
_TOOL_NAMESPACE = "deerflow"
_REASONING_ITEMS = "deerflow_subscription_reasoning"


def get_access_token(provider: str) -> str:
    # Keep model construction independent of credential storage initialization.
    from deerflow.models.subscriptions import get_access_token as resolve_token

    return resolve_token(provider)


class ChatGPTSubscriptionChatModel(CodexChatModel):
    """Public Responses API with the selected account's ChatGPT plan token."""

    retry_max_attempts: int = 1
    allow_reasoning_none: bool = False
    subscription_provider: ClassVar[str] = "chatgpt"

    @property
    def _llm_type(self) -> str:
        return "chatgpt-subscription-responses"

    @property
    def _responses_url(self) -> str:
        return "https://api.openai.com/v1/responses"

    def model_post_init(self, __context: Any) -> None:
        # Do not call CodexChatModel.model_post_init: that loads a CLI token and
        # selects a different, private endpoint. Subscription tokens stay local
        # to the request, including after this model has been serialized.
        self.retry_max_attempts = 1
        BaseChatModel.model_post_init(self, __context)

    def _convert_messages(self, messages: list[BaseMessage]) -> tuple[str, list[dict]]:
        instructions = []
        input_items = []
        for message in messages:
            if isinstance(message, SystemMessage):
                content = self._normalize_content(message.content)
                if content:
                    instructions.append(content)
                continue
            if isinstance(message, AIMessage):
                # With store=false the caller supplies reasoning items again on
                # tool follow-ups, including opaque encrypted reasoning state.
                for item in message.additional_kwargs.get(_REASONING_ITEMS, []):
                    if isinstance(item, dict) and item.get("type") == "reasoning":
                        input_items.append(deepcopy(item))
            _, items = super()._convert_messages([message])
            for item in items:
                if item.get("type") == "function_call":
                    item["namespace"] = _TOOL_NAMESPACE
            input_items.extend(items)
        return "\n\n".join(instructions) or "You are a helpful assistant.", input_items

    def _call_codex_api(self, messages: list[BaseMessage], tools: list[dict] | None = None, tool_choice: str | dict | bool | None = None) -> dict:
        instructions, input_items = self._convert_messages(messages)
        # Build an allowlisted payload: the subscription preview rejects many
        # ordinary Responses API controls, including output limits/temperature.
        # `tool_choice` is accepted because the base class now passes it
        # (upstream #6898) but stays off the wire: it is not on the allowlist,
        # and a named choice has no verified form for namespaced tools.
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
        }
        if self.reasoning_effort != "none" or self.allow_reasoning_none:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if tools:
            payload["tools"] = [{"type": "namespace", "name": _TOOL_NAMESPACE, "description": "DeerFlow tools executed by this application.", "tools": self._convert_tools(tools)}]
        headers = {
            "Authorization": f"Bearer {get_access_token('chatgpt')}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": USER_AGENT,
        }
        return self._stream_response(headers, payload)

    def _parse_response(self, response: dict) -> ChatResult:
        for item in response.get("output", []):
            if item.get("type") == "function_call" and item.get("namespace") not in (None, _TOOL_NAMESPACE):
                raise ValueError("ChatGPT returned a tool outside the DeerFlow namespace")
        result = super()._parse_response(response)
        result.generations[0].message.response_metadata["model"] = f"subscription-chatgpt-{self.model}"
        result.llm_output["model_name"] = f"subscription-chatgpt-{self.model}"
        reasoning = [deepcopy(item) for item in response.get("output", []) if item.get("type") == "reasoning"]
        if reasoning:
            result.generations[0].message.additional_kwargs[_REASONING_ITEMS] = reasoning
        return result


class _SubscriptionChatOpenAI(ChatOpenAI):
    """Shared OpenAI-compatible subscription transport with request-local auth."""

    subscription_provider: ClassVar[str]
    subscription_endpoint: ClassVar[str]
    subscription_responses_api: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        kwargs.pop("subscription_provider", None)
        kwargs.pop("openai_api_key", None)
        kwargs.pop("openai_api_base", None)
        # The fixed placeholder satisfies SDK construction. Actual auth is added
        # to each request after refresh, never saved on the model or SDK client.
        kwargs.update(api_key="deerflow-managed-subscription", base_url=self.subscription_endpoint, streaming=True, max_retries=0, use_responses_api=self.subscription_responses_api, default_headers={"User-Agent": USER_AGENT})
        if self.subscription_responses_api:
            # Nothing is stored provider-side, so reasoning survives a tool
            # follow-up only as the encrypted items replayed with the history.
            kwargs.update(store=False, include=["reasoning.encrypted_content"])
            kwargs.setdefault("output_version", "responses/v1")
        super().__init__(**kwargs)

    def _check_subscription_use(self) -> None:
        return None

    def _subscription_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}", "User-Agent": USER_AGENT}

    def _convert_chunk_to_generation_chunk(self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None) -> ChatGenerationChunk | None:
        from deerflow.models.subscriptions import subscription_model_name

        result = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if result is not None and result.generation_info and "model_name" in result.generation_info:
            # Keep subscription usage separate from separately billed API aliases.
            result.generation_info["model_name"] = subscription_model_name(self.subscription_provider, self.model_name)
        return result

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        self._check_subscription_use()
        headers = self._subscription_headers(get_access_token(self.subscription_provider))
        kwargs["extra_headers"] = {**(kwargs.get("extra_headers") or {}), **headers}
        yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        self._check_subscription_use()
        access_token = await asyncio.to_thread(get_access_token, self.subscription_provider)
        kwargs["extra_headers"] = {**(kwargs.get("extra_headers") or {}), **self._subscription_headers(access_token)}
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        # Grok requires streaming on the wire even for an ordinary invoke().
        return generate_from_stream(self._stream(messages, stop=stop, run_manager=run_manager, **kwargs))

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        return await agenerate_from_stream(self._astream(messages, stop=stop, run_manager=run_manager, **kwargs))


class GrokSubscriptionChatModel(_SubscriptionChatOpenAI):
    """Grok CLI's documented subscription-backed OpenAI-compatible proxy."""

    subscription_provider: ClassVar[str] = "grok"
    subscription_endpoint: ClassVar[str] = "https://cli-chat-proxy.grok.com/v1"

    def _subscription_headers(self, access_token: str) -> dict[str, str]:
        return {**super()._subscription_headers(access_token), "X-XAI-Token-Auth": "xai-grok-cli", "x-grok-model-override": self.model_name}


class GrokResponsesSubscriptionChatModel(_SubscriptionChatOpenAI):
    """Grok models xAI serves only through its public Responses API, on the same grant.

    Listed only after the reach probe showed this grant is accepted by
    ``api.x.ai``. The CLI proxy's routing headers do not apply here: the
    public API takes the model from the request body.
    """

    subscription_provider: ClassVar[str] = "grok"
    subscription_endpoint: ClassVar[str] = "https://api.x.ai/v1"
    subscription_responses_api: ClassVar[bool] = True

    def _subscription_chunk(self, chunk: ChatGenerationChunk) -> ChatGenerationChunk:
        from deerflow.models.subscriptions import subscription_model_name

        # The Responses stream bypasses the chat-completions chunk converter,
        # so the usage identity is renamed here: plan usage must never be
        # priced under the same model ID's paid API alias.
        name = subscription_model_name(self.subscription_provider, self.model_name)
        if "model_name" in chunk.message.response_metadata:
            chunk.message.response_metadata["model_name"] = name
        if chunk.generation_info and "model_name" in chunk.generation_info:
            chunk.generation_info["model_name"] = name
        return chunk

    def _stream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        for chunk in super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield self._subscription_chunk(chunk)

    async def _astream(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield self._subscription_chunk(chunk)


class KimiSubscriptionChatModel(_SubscriptionChatOpenAI):
    """Kimi Code subscription inference with interactive-use admission."""

    subscription_provider: ClassVar[str] = "kimi"
    subscription_endpoint: ClassVar[str] = "https://api.kimi.ai/coding/v1"

    def _check_subscription_use(self, config: RunnableConfig | None = None) -> None:
        policy_config = dict(ensure_config(config))
        if config is not None and "context" in config:
            # Runtime context is a DeerFlow extension to RunnableConfig; retain
            # its shape rather than ensure_config moving it under configurable.
            policy_config["context"] = config["context"]
        if not resolve_run_interaction_policy(policy_config).allows_clarification:
            raise ValueError("Kimi Code subscriptions require an interactive user session; choose an API-backed model for unattended runs")

    def invoke(self, input: LanguageModelInput, config: RunnableConfig | None = None, *, stop: list[str] | None = None, **kwargs: Any) -> AIMessage:
        # BaseChatModel consumes explicit config without binding it as child
        # context. Check before it disappears; the stream hooks still check
        # inherited context for calls made directly by graph internals.
        self._check_subscription_use(config)
        return super().invoke(input, config=config, stop=stop, **kwargs)

    async def ainvoke(self, input: LanguageModelInput, config: RunnableConfig | None = None, *, stop: list[str] | None = None, **kwargs: Any) -> AIMessage:
        self._check_subscription_use(config)
        return await super().ainvoke(input, config=config, stop=stop, **kwargs)

    def stream(self, input: LanguageModelInput, config: RunnableConfig | None = None, *, stop: list[str] | None = None, **kwargs: Any) -> Iterator[AIMessageChunk]:
        self._check_subscription_use(config)
        yield from super().stream(input, config=config, stop=stop, **kwargs)

    async def astream(self, input: LanguageModelInput, config: RunnableConfig | None = None, *, stop: list[str] | None = None, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:
        self._check_subscription_use(config)
        async for chunk in super().astream(input, config=config, stop=stop, **kwargs):
            yield chunk

    def _get_request_payload(self, input_: LanguageModelInput, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(messages, stop=stop, **kwargs)

        def restore(message: dict, original: AIMessage) -> None:
            restore_reasoning_content(message, original)
            if message.get("tool_calls") and message.get("content") is None:
                message["content"] = ""

        restore_assistant_payloads(payload.get("messages", []), messages, restore)
        return payload

    def _convert_chunk_to_generation_chunk(self, chunk: dict, default_chunk_class: type, base_generation_info: dict | None) -> ChatGenerationChunk | None:
        result = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        choices = chunk.get("choices") or []
        if result is not None and choices:
            reasoning = (choices[0].get("delta") or {}).get("reasoning_content")
            if reasoning is not None:
                result.message.additional_kwargs["reasoning_content"] = reasoning
        return result
