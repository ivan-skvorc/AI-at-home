"""Offline tests for the claude-to-deerflow skill's chat.sh.

The script runs unchanged under bash with the real curl, against an in-process
fake of the DeerFlow endpoints it calls on the loopback interface: the Gateway
health check, thread creation and the streamed run.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_SH = REPO_ROOT / "skills" / "public" / "claude-to-deerflow" / "scripts" / "chat.sh"
BASH = shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="chat.sh targets POSIX systems"),
    pytest.mark.skipif(BASH is None or shutil.which("curl") is None, reason="chat.sh needs bash and curl"),
]

_STREAM = 'event: values\ndata: {"messages": [{"type": "human", "content": "hi"}, {"type": "ai", "content": "Hello from DeerFlow"}]}\n\n'


class _FakeDeerFlow(BaseHTTPRequestHandler):
    thread_reply: tuple[int, str] = (200, json.dumps({"thread_id": "thread-1"}))

    def log_message(self, *args):  # keep pytest output clean
        pass

    def _reply(self, status: int, body: str, content_type: str = "application/json") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, '{"status": "ok"}')
        else:
            self._reply(404, "{}")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/api/langgraph/threads":
            self._reply(*self.thread_reply)
        elif self.path == "/api/langgraph/threads/thread-1/runs/stream":
            self._reply(200, _STREAM, "text/event-stream")
        else:
            self._reply(404, "{}")


@pytest.fixture
def deerflow():
    handler = type("Handler", (_FakeDeerFlow,), {})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield handler, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _chat(url: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("DEERFLOW_")}
    env.update({"DEERFLOW_URL": url, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}, **extra_env)
    return subprocess.run([BASH, str(CHAT_SH), "hi", "", "flash"], env=env, capture_output=True, text=True, timeout=60)


def test_prints_the_agent_reply_for_a_new_thread(deerflow):
    _, url = deerflow

    result = _chat(url)

    assert result.returncode == 0, result.stderr
    assert "Hello from DeerFlow" in result.stdout
    assert "Thread: thread-1" in result.stderr


@pytest.mark.parametrize("reply", [(500, '{"detail": "boom"}'), (200, "not json")], ids=["server-error", "unparseable"])
def test_a_failed_thread_creation_reports_the_response(deerflow, reply):
    handler, url = deerflow
    handler.thread_reply = reply

    result = _chat(url)

    assert result.returncode == 1
    assert "ERROR: Failed to create thread. Response: " + reply[1] in result.stderr


def test_an_unreachable_thread_endpoint_reports_instead_of_exiting_silently(deerflow):
    # Health passes on the Gateway while the LangGraph URL refuses the
    # connection, so curl itself fails inside the thread creation.
    _, url = deerflow

    result = _chat(url, DEERFLOW_GATEWAY_URL=url, DEERFLOW_LANGGRAPH_URL=_closed_port_url())

    assert result.returncode == 1
    assert "ERROR: Failed to create thread." in result.stderr
