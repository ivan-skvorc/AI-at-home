"""Subscription inference contracts through real serializers and offline HTTP."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables.config import var_child_runnable_config

from deerflow.models import subscription_providers as providers

TOOL = {"type": "function", "function": {"name": "lookup", "description": "Look up a value", "parameters": {"type": "object", "properties": {}}, "strict": False}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(requests=[], tokens=[], token="subscription-secret-one", failure=False)

    def token(provider):
        state.tokens.append(provider)
        return state.token

    monkeypatch.setattr(providers, "get_access_token", token)

    def response(request):
        body = json.loads(request.content)
        state.requests.append((request, body))
        assert body["stream"] is True
        if request.url.path == "/v1/responses":
            if state.failure:
                events = [{"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded", "message": "Plan usage limit reached"}}}]
            else:
                followup = any(item.get("type") == "function_call_output" for item in body["input"])
                output = (
                    [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done"}]}]
                    if followup
                    else [
                        {"type": "reasoning", "id": "rs-one", "encrypted_content": "opaque-reasoning", "summary": []},
                        {"type": "function_call", "namespace": "deerflow", "name": "lookup", "call_id": "call-one", "arguments": "{}"},
                    ]
                )
                events = [{"type": "response.completed", "response": {"model": body["model"], "output": output, "usage": None}}]
        else:
            if state.failure:
                return httpx.Response(429, request=request, json={"error": {"message": "Subscription usage exhausted", "type": "rate_limit_error"}})
            followup = body["messages"][-1]["role"] == "tool"
            deltas = (
                [{"role": "assistant", "content": "Done"}]
                if followup
                else [
                    {"role": "assistant", "reasoning_content": "Checking "},
                    {"reasoning_content": "the value."},
                    {"tool_calls": [{"index": 0, "type": "function", "id": "call-one", "function": {"name": "lookup", "arguments": "{}"}}]},
                ]
            )
            events = [{"id": "chat-one", "object": "chat.completion.chunk", "created": 1, "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
            events.append({"id": "chat-one", "object": "chat.completion.chunk", "created": 1, "model": body["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if followup else "tool_calls"}]})
        data = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=data.encode())

    def send(client, request, **kwargs):
        return response(request)

    async def asend(client, request, **kwargs):
        return response(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setattr(httpx.AsyncClient, "send", asend)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_chatgpt_public_endpoint_namespaces_history_and_refresh(wire, asynchronous):
    model = providers.ChatGPTSubscriptionChatModel(model="account-model", temperature=0.2, max_tokens=500, metadata={"private": "ignored"})
    bound = model.bind_tools([TOOL])
    history = [SystemMessage(content="Use tools"), HumanMessage(content="Find the value")]
    first = await bound.ainvoke(history) if asynchronous else bound.invoke(history)
    assert first.tool_calls == [{"name": "lookup", "args": {}, "id": "call-one", "type": "tool_call"}]
    wire.token = "subscription-secret-two"
    history.extend([first, ToolMessage(content="42", tool_call_id="call-one")])
    second = await bound.ainvoke(history) if asynchronous else bound.invoke(history)
    assert second.content == "Done"
    assert second.response_metadata["model_name"] == "subscription-chatgpt-account-model"
    assert wire.tokens == ["chatgpt", "chatgpt"]
    for index, (request, body) in enumerate(wire.requests):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == f"Bearer subscription-secret-{'one' if index == 0 else 'two'}"
        assert request.headers["user-agent"].startswith("DeerFlow/")
        assert "originator" not in request.headers
        assert "chatgpt-account-id" not in request.headers
        assert body["store"] is False
        assert set(body) <= {"model", "instructions", "input", "store", "stream", "reasoning", "tools", "include"}
        assert body["tools"] == [{"type": "namespace", "name": "deerflow", "description": "DeerFlow tools executed by this application.", "tools": [{"type": "function", **TOOL["function"]}]}]
    replay = wire.requests[1][1]["input"]
    assert next(item for item in replay if item.get("type") == "function_call")["namespace"] == "deerflow"
    assert {"type": "reasoning", "id": "rs-one", "encrypted_content": "opaque-reasoning", "summary": []} in replay
    serialized = json.dumps(model.to_json(), default=str)
    assert "subscription-secret" not in serialized


@pytest.mark.parametrize("event", ["quota", "interrupted"])
def test_chatgpt_requires_completion_and_never_retries_subscription_limits(wire, monkeypatch, event):
    wire.failure = True
    model = providers.ChatGPTSubscriptionChatModel(model="account-model")
    if event == "interrupted":

        def send(client, request, **kwargs):
            wire.requests.append((request, json.loads(request.content)))
            return httpx.Response(200, request=request, headers={"content-type": "text/event-stream"}, content=b'data: {"type":"response.output_text.delta","delta":"Partial"}\n\n')

        monkeypatch.setattr(httpx.Client, "send", send)
    with pytest.raises(RuntimeError, match="subscription_sharing_usage_limit_exceeded" if event == "quota" else "without response.completed"):
        model.invoke("Hello")
    assert len(wire.requests) == 1


@pytest.mark.parametrize("allow_none", [False, True])
def test_chatgpt_disables_reasoning_only_when_the_catalog_supports_none(wire, allow_none):
    model = providers.ChatGPTSubscriptionChatModel(model="account-model", reasoning_effort="none", allow_reasoning_none=allow_none)
    model.invoke("Hello")
    payload = wire.requests[0][1]
    assert payload.get("reasoning") == ({"effort": "none"} if allow_none else None)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,model_name,endpoint", [("grok", "grok-code", "https://cli-chat-proxy.grok.com/v1/chat/completions"), ("kimi", "kimi-for-coding", "https://api.kimi.ai/coding/v1/chat/completions")])
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
async def test_proxy_tools_always_stream_refresh_and_preserve_kimi_reasoning(wire, provider, model_name, endpoint, mode):
    cls = providers.GrokSubscriptionChatModel if provider == "grok" else providers.KimiSubscriptionChatModel
    model = cls(model=model_name, api_key="accidental-paid-key", base_url="https://wrong.invalid/v1")
    bound = model.bind_tools([TOOL])

    async def call(history):
        if mode == "invoke":
            return bound.invoke(history)
        if mode == "ainvoke":
            return await bound.ainvoke(history)
        chunks = [chunk async for chunk in bound.astream(history)] if mode == "astream" else list(bound.stream(history))
        result = chunks[0]
        for chunk in chunks[1:]:
            result += chunk
        return result

    history = [HumanMessage(content="Find the value")]
    first = await call(history)
    assert first.tool_calls[0]["name"] == "lookup"
    assert first.tool_calls[0]["args"] == {}
    wire.token = "subscription-secret-two"
    history.extend([first, ToolMessage(content="42", tool_call_id="call-one")])
    second = await call(history)
    assert second.content == "Done"
    assert second.response_metadata["model_name"].startswith(f"subscription-{provider}-")
    assert wire.tokens == [provider, provider]
    for index, (request, body) in enumerate(wire.requests):
        assert str(request.url) == endpoint
        assert request.headers["authorization"] == f"Bearer subscription-secret-{'one' if index == 0 else 'two'}"
        assert request.headers["user-agent"].startswith("DeerFlow/")
        assert "subscription_provider" not in body
        if provider == "grok":
            assert request.headers["x-xai-token-auth"] == "xai-grok-cli"
            assert request.headers["x-grok-model-override"] == model_name
    if provider == "kimi":
        assistant = next(message for message in wire.requests[1][1]["messages"] if message["role"] == "assistant")
        assert assistant["reasoning_content"] == "Checking the value."
        assert assistant["content"] == ""
    serialized = json.dumps(model.to_json(), default=str)
    assert "subscription-secret" not in serialized
    assert "accidental-paid-key" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["grok", "kimi"])
async def test_proxy_subscription_limit_is_reported_without_paid_fallback(wire, provider):
    wire.failure = True
    cls = providers.GrokSubscriptionChatModel if provider == "grok" else providers.KimiSubscriptionChatModel
    with pytest.raises(Exception, match="Subscription usage exhausted"):
        await cls(model="test", max_retries=9).ainvoke("Hello")
    assert len(wire.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
@pytest.mark.parametrize("config_source", ["inherited", "explicit", "explicit_context"])
async def test_kimi_blocks_unattended_context_before_auth(wire, mode, config_source):
    model = providers.KimiSubscriptionChatModel(model="kimi-for-coding")
    config = {"context" if config_source == "explicit_context" else "configurable": {"non_interactive": True}}
    marker = var_child_runnable_config.set(config if config_source == "inherited" else None)
    call_options = {} if config_source == "inherited" else {"config": config}
    try:
        with pytest.raises(ValueError, match="interactive"):
            if mode == "invoke":
                model.invoke("Hello", **call_options)
            elif mode == "ainvoke":
                await model.ainvoke("Hello", **call_options)
            elif mode == "stream":
                list(model.stream("Hello", **call_options))
            else:
                [chunk async for chunk in model.astream("Hello", **call_options)]
    finally:
        var_child_runnable_config.reset(marker)
    assert wire.tokens == []
    assert wire.requests == []


@pytest.mark.asyncio
async def test_async_token_refresh_runs_off_the_event_loop(wire, monkeypatch):
    event_loop_thread = __import__("threading").get_ident()
    refresh_threads = []

    def token(provider):
        refresh_threads.append(__import__("threading").get_ident())
        return "refresh-secret"

    monkeypatch.setattr(providers, "get_access_token", token)
    await providers.GrokSubscriptionChatModel(model="grok-code").ainvoke("Hello")
    assert refresh_threads and all(thread != event_loop_thread for thread in refresh_threads)


def test_subscription_factory_never_uses_paid_fallbacks_or_api_prices(wire):
    from app.gateway.routers.models import _price_response
    from deerflow.config.app_config import AppConfig
    from deerflow.models.factory import create_chat_model
    from deerflow.pricing import build_pricing_map

    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "test"},
            "models": [
                {"name": "subscription-chatgpt-account-model", "model": "account-model", "use": "deerflow.models.subscription_providers:ChatGPTSubscriptionChatModel", "subscription_provider": "chatgpt"},
                {"name": "paid", "model": "account-model", "use": "langchain_openai:ChatOpenAI", "api_key": "paid-key", "price": {"input": 1, "output": 2}},
            ],
            "model_fallback": {"enabled": True, "chain": ["paid"]},
        }
    )
    model = create_chat_model("subscription-chatgpt-account-model", app_config=config, attach_tracing=False)
    assert isinstance(model, providers.ChatGPTSubscriptionChatModel)
    assert _price_response(build_pricing_map(config.models), config.models[0]) is None
