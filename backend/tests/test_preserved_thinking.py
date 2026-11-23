"""The preserved-thinking guard keeps Claude thinking blocks valid across prefix edits.

Each test drives the public model calls through an offline HTTP transport and
reads the request bodies DeerFlow sends, because the guard's whole job is what
reaches Anthropic.
"""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from deerflow.models.preserved_thinking import BINDING_BETA, RECORD_KEY, GuardedChatAnthropic, has_preserved_thinking

THINKING = {"type": "adaptive", "display": "summarized"}
BOUND_ERROR = 'messages.1.content.0: Invalid `signature` in `thinking` block. The block is bound to a different conversation. Remove the block, or set `thinking.block_binding.prefix_mismatch_behavior` to "drop_block".'


def _answer(signature: str, tool_id: str) -> dict:
    return {
        "id": f"msg_{signature}",
        "type": "message",
        "role": "assistant",
        "model": "claude-fable-5-2",
        "content": [
            {"type": "thinking", "thinking": f"plan {signature}", "signature": signature},
            {"type": "tool_use", "id": tool_id, "name": "lookup", "input": {}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


class _Anthropic:
    """An offline Anthropic endpoint that records every request."""

    def __init__(self, *responses: httpx.Response):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.betas: list[str | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.betas.append(request.headers.get("anthropic-beta"))
        return self.responses.pop(0)


def _model(endpoint: _Anthropic, model: str = "claude-fable-5-2") -> GuardedChatAnthropic:
    chat = GuardedChatAnthropic(model=model, anthropic_api_key="sk-ant-fake", max_tokens=2048, thinking=dict(THINKING))
    chat.__dict__["_client"] = chat._client.with_options(http_client=httpx.Client(transport=httpx.MockTransport(endpoint)), max_retries=0)
    return chat


def _ok(signature: str, tool_id: str) -> httpx.Response:
    return httpx.Response(200, json=_answer(signature, tool_id))


def _turn(context: str) -> list:
    # The second human message stands in for the durable-context message
    # DeerFlow inserts near the front and rewrites mid-run.
    return [SystemMessage("You are DeerFlow."), HumanMessage(context), HumanMessage("Look it up.")]


def _sent_thinking(body: dict) -> list[str]:
    return [block["signature"] for message in body["messages"] if message["role"] == "assistant" for block in message["content"] if block["type"] == "thinking"]


def test_an_unchanged_prefix_sends_the_thinking_back():
    endpoint = _Anthropic(_ok("sig1", "toolu_1"), _ok("sig2", "toolu_2"))
    model = _model(endpoint)

    first = model.invoke(_turn("context v1"))
    assert first.response_metadata[RECORD_KEY]["previous"] is None
    model.invoke([*_turn("context v1"), first, ToolMessage("42", tool_call_id="toolu_1")])

    assert _sent_thinking(endpoint.bodies[1]) == ["sig1"]


def test_a_changed_earlier_message_leaves_the_thinking_after_it_out():
    endpoint = _Anthropic(_ok("sig1", "toolu_1"), _ok("sig2", "toolu_2"))
    model = _model(endpoint)

    first = model.invoke(_turn("context v1"))
    model.invoke([*_turn("context v2"), first, ToolMessage("42", tool_call_id="toolu_1")])

    sent = endpoint.bodies[1]["messages"][1]
    assert _sent_thinking(endpoint.bodies[1]) == []
    assert [block["type"] for block in sent["content"]] == ["tool_use"]
    # The thread's own message keeps its thinking: only the request is trimmed.
    assert first.content[0]["type"] == "thinking"


def test_the_newest_valid_run_is_kept_after_a_change():
    endpoint = _Anthropic(_ok("sig1", "toolu_1"), _ok("sig2", "toolu_2"), _ok("sig3", "toolu_3"))
    model = _model(endpoint)

    first = model.invoke(_turn("context v1"))
    history = [first, ToolMessage("42", tool_call_id="toolu_1")]
    second = model.invoke([*_turn("context v2"), *history])
    model.invoke([*_turn("context v2"), *history, second, ToolMessage("43", tool_call_id="toolu_2")])

    # sig1 is still bound to "context v1"; sig2 was produced without it and stays valid.
    assert _sent_thinking(endpoint.bodies[2]) == ["sig2"]


def test_a_model_without_preserved_thinking_is_left_alone():
    endpoint = _Anthropic(_ok("sig1", "toolu_1"), _ok("sig2", "toolu_2"))
    model = _model(endpoint, model="claude-opus-5")

    first = model.invoke(_turn("context v1"))
    model.invoke([*_turn("context v2"), first, ToolMessage("42", tool_call_id="toolu_1")])

    assert _sent_thinking(endpoint.bodies[1]) == ["sig1"]


@pytest.mark.parametrize(
    ("model", "expected"),
    [("claude-fable-5-2", True), ("claude-fable-5-1", True), ("claude-opus-5-5", True), ("claude-haiku-5-5-20261007", True), ("claude-opus-5", False), ("claude-sonnet-5", False), ("claude-fable-5", False)],
)
def test_which_models_are_guarded(model, expected):
    assert has_preserved_thinking(model) is expected


@pytest.mark.asyncio
async def test_a_streamed_answer_carries_one_intact_record():
    events = [
        {"type": "message_start", "message": {**_answer("sig1", "toolu_1"), "content": [], "stop_reason": None}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "plan"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig1"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "done"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 2}},
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    model = GuardedChatAnthropic(model="claude-fable-5-2", anthropic_api_key="sk-ant-fake", max_tokens=2048, thinking=dict(THINKING))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode()))
    model.__dict__["_async_client"] = model._async_client.with_options(http_client=httpx.AsyncClient(transport=transport), max_retries=0)

    message = None
    async for chunk in model.astream(_turn("context v1")):
        message = chunk if message is None else message + chunk

    record = message.response_metadata[RECORD_KEY]
    assert set(record) == {"prefix", "previous"} and len(record["prefix"]) == 64


def test_a_rejected_request_is_retried_once_with_drop_block():
    endpoint = _Anthropic(_ok("sig1", "toolu_1"), httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": BOUND_ERROR}}), _ok("sig2", "toolu_2"))
    model = _model(endpoint)

    first = model.invoke(_turn("context v1"))
    # The endpoint refuses sig1 as if the guard had missed a change.
    model.invoke([*_turn("context v1"), first, ToolMessage("42", tool_call_id="toolu_1")])

    assert len(endpoint.bodies) == 3
    assert "block_binding" not in endpoint.bodies[1]["thinking"]
    assert endpoint.bodies[2]["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert BINDING_BETA in (endpoint.betas[2] or "")
    assert "block_binding" not in model.thinking


def test_another_bad_request_is_not_retried():
    endpoint = _Anthropic(httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: too large"}}))
    model = _model(endpoint)

    with pytest.raises(Exception, match="max_tokens"):
        model.invoke(_turn("context v1"))
    assert len(endpoint.bodies) == 1
