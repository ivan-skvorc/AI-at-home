"""Grok Imagine and X search tools over offline HTTP (FORK.md §43).

Pinned: the token goes only to api.x.ai and never into a written file; source
images leave as data URIs and are recorded by path; a plan-quota refusal is
reported without a retry; generated files are fetched only from pinned hosts;
and a video job's terminal states are reported as themselves.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from _comfyui_helpers import PNG_1PX

from deerflow.community import url_safety
from deerflow.community.xai import client as client_module
from deerflow.community.xai import tools

TOKEN = "grok-secret-token"


@pytest.fixture
def xai(monkeypatch):
    state = SimpleNamespace(requests=[], handler=None, listed=["grok-imagine-image"], extra={})

    async def access(feature):
        state.feature = feature
        return TOKEN, state.listed

    def transport(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        return state.handler(request)

    original = httpx.AsyncClient
    monkeypatch.setattr(client_module, "resolve_access", access)
    monkeypatch.setattr(tools, "resolve_access", access)
    monkeypatch.setattr(client_module.httpx, "AsyncClient", lambda **kwargs: original(**{**kwargs, "transport": httpx.MockTransport(transport)}))
    monkeypatch.setattr(url_safety, "validate_public_http_url", lambda url, **kwargs: None)
    monkeypatch.setattr(tools, "_tool_extra", lambda name: dict(state.extra))
    return state


def _runtime(tmp_path):
    dirs = {name: tmp_path / name for name in ("workspace", "uploads", "outputs")}
    for path in dirs.values():
        path.mkdir()
    thread_data = {f"{name}_path": str(path) for name, path in dirs.items()}
    return SimpleNamespace(context={"thread_id": "thread-1"}, state={"thread_data": thread_data}), dirs


def _message(command):
    return command.update["messages"][0].content


def _image_response(request):
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG_1PX).decode(), "mime_type": "image/png"}]})


@pytest.mark.asyncio
async def test_generate_image_writes_outputs_and_keeps_the_token_off_disk(xai, tmp_path):
    xai.handler = _image_response
    runtime, dirs = _runtime(tmp_path)
    command = await tools.grok_generate_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="a lighthouse at dusk", aspect_ratio="16:9")
    payload = json.loads(_message(command))
    assert command.update["artifacts"] == payload["images"]
    assert payload["images"][0].startswith("/mnt/user-data/outputs/") and payload["images"][0].endswith(".png")
    request = xai.requests[0]
    assert str(request.url) == "https://api.x.ai/v1/images/generations"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {"model": "grok-imagine-image", "prompt": "a lighthouse at dusk", "n": 1, "response_format": "b64_json", "aspect_ratio": "16:9"}
    written = {path.name: path.read_bytes() for path in dirs["outputs"].iterdir()}
    assert PNG_1PX in written.values()
    record = next(content for name, content in written.items() if name.endswith(".request.json"))
    assert TOKEN.encode() not in record
    assert json.loads(record)["request"]["prompt"] == "a lighthouse at dusk"


@pytest.mark.asyncio
async def test_edit_sends_thread_images_as_data_and_records_them_by_path(xai, tmp_path):
    xai.handler = _image_response
    runtime, dirs = _runtime(tmp_path)
    (dirs["uploads"] / "photo.png").write_bytes(PNG_1PX)
    command = await tools.grok_edit_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="make the sky purple", images=["/mnt/user-data/uploads/photo.png"])
    assert "images" in json.loads(_message(command))
    body = json.loads(xai.requests[0].content)
    assert body["image"] == {"url": f"data:image/png;base64,{base64.b64encode(PNG_1PX).decode()}", "type": "image_url"}
    record = next(path for path in dirs["outputs"].iterdir() if path.name.endswith(".request.json")).read_text(encoding="utf-8")
    assert "base64" not in record and "/mnt/user-data/uploads/photo.png" in record


@pytest.mark.asyncio
async def test_edit_refuses_files_outside_the_thread_before_contacting_xai(xai, tmp_path):
    runtime, _ = _runtime(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG_1PX)
    command = await tools.grok_edit_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="edit", images=[str(outside)])
    assert _message(command).startswith("Error:")
    command = await tools.grok_edit_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="edit", images=["/mnt/user-data/uploads/../../secret.png"])
    assert _message(command).startswith("Error:")
    assert xai.requests == []


@pytest.mark.asyncio
async def test_plan_quota_is_reported_once_without_retry(xai, tmp_path):
    xai.handler = lambda request: httpx.Response(429, json={"error": "private prompt echo"})
    runtime, dirs = _runtime(tmp_path)
    command = await tools.grok_generate_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="private prompt")
    message = _message(command)
    assert "plan limit" in message and "private prompt echo" not in message
    assert len(xai.requests) == 1
    assert list(dirs["outputs"].iterdir()) == []


@pytest.mark.asyncio
async def test_url_results_download_only_from_pinned_hosts_and_without_the_token(xai, tmp_path):
    runtime, _ = _runtime(tmp_path)

    def handler(request):
        if request.url.host == "api.x.ai":
            return httpx.Response(200, json={"data": [{"url": xai.file_url}]})
        return httpx.Response(200, content=PNG_1PX)

    xai.handler = handler
    xai.file_url = "https://imgen.x.ai/xai-tmp/one.png"
    command = await tools.grok_generate_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="cat")
    assert "images" in json.loads(_message(command))
    download = xai.requests[1]
    assert download.url.host == "imgen.x.ai" and "authorization" not in download.headers

    xai.requests.clear()
    xai.file_url = "https://evil.example/one.png"
    command = await tools.grok_generate_image_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="cat")
    assert "unexpected host" in _message(command)
    assert [request.url.host for request in xai.requests] == ["api.x.ai"]


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal,expected", [("done", None), ("failed", "failed"), ("expired", "expired")])
async def test_video_polls_until_a_terminal_status(xai, tmp_path, monkeypatch, terminal, expected):
    runtime, dirs = _runtime(tmp_path)
    xai.listed = ["grok-imagine-video"]
    xai.extra = {"poll_interval_seconds": 0.01}
    statuses = iter(["pending", terminal])

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(tools.asyncio, "sleep", no_sleep)

    def handler(request):
        if request.url.path == "/v1/videos/generations":
            return httpx.Response(200, json={"request_id": "req-1"})
        if request.url.path == "/v1/videos/req-1":
            state = next(statuses)
            return httpx.Response(200, json={"status": state, "video": {"url": "https://vidgen.x.ai/clip.mp4"}})
        return httpx.Response(200, content=b"mp4-bytes")

    xai.handler = handler
    command = await tools.grok_generate_video_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="waves", duration=6)
    message = _message(command)
    if expected is None:
        payload = json.loads(message)
        assert command.update["artifacts"] == [payload["video"]] and payload["video"].endswith(".mp4")
        assert payload["contact_sheet"] is None
        assert (dirs["outputs"] / payload["video"].rsplit("/", 1)[1]).read_bytes() == b"mp4-bytes"
        assert json.loads(xai.requests[0].content) == {"model": "grok-imagine-video", "prompt": "waves", "duration": 6}
    else:
        assert message.startswith("Error:") and expected in message
        assert list(dirs["outputs"].iterdir()) == []


@pytest.mark.asyncio
async def test_video_gives_up_at_its_timeout(xai, tmp_path, monkeypatch):
    runtime, _ = _runtime(tmp_path)
    xai.extra = {"timeout_seconds": 10, "poll_interval_seconds": 4}
    clock = [0.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])

    async def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(tools.asyncio, "sleep", sleep)
    xai.handler = lambda request: httpx.Response(200, json={"request_id": "req-1"} if request.method == "POST" else {"status": "pending"})
    command = await tools.grok_generate_video_tool.coroutine(runtime=runtime, tool_call_id="t1", prompt="waves")
    assert "after 10 seconds" in _message(command)


@pytest.mark.asyncio
async def test_x_search_sends_filters_and_returns_cited_posts(xai):
    xai.listed = ["grok-4.3", "grok-build-0.1"]
    output = {
        "output": [
            {"type": "custom_tool_call"},
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "People are excited.",
                        "annotations": [{"type": "url_citation", "url": "https://x.com/a/status/1", "title": "post"}, {"type": "url_citation", "url": "javascript:alert(1)"}],
                    }
                ],
            },
        ],
        "citations": ["https://x.com/a/status/1", "https://x.com/b/status/2"],
    }
    xai.handler = lambda request: httpx.Response(200, json=output)
    result = json.loads(await tools.x_search_tool.coroutine(query="launch reactions", from_date="2026-10-01", allowed_handles=["@SpaceX"]))
    body = json.loads(xai.requests[0].content)
    assert body["tools"] == [{"type": "x_search", "from_date": "2026-10-01", "allowed_x_handles": ["SpaceX"]}]
    assert body["store"] is False and body["model"] == "grok-4.3"
    assert result["answer"] == "People are excited."
    assert [source["url"] for source in result["sources"]] == ["https://x.com/a/status/1", "https://x.com/b/status/2"]
    assert "untrusted" in result["note"]


@pytest.mark.asyncio
async def test_x_search_refuses_bad_filters_locally(xai):
    for kwargs in ({"from_date": "October 1"}, {"allowed_handles": ["a"], "excluded_handles": ["b"]}, {"allowed_handles": ["not a handle!"]}):
        assert "error" in json.loads(await tools.x_search_tool.coroutine(query="q", **kwargs))
    assert xai.requests == []
