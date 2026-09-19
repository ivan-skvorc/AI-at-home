"""Primary = the whole agent loop, driven through the running Gateway.

The pipeline runner grades the document path. This one grades what the user
actually experiences: upload a large PDF to a thread, give the agent one
specific task, and read back what it did. That is the only place the real
drift mechanism can appear, because only here does the document compete with
the instruction for the same context window, and only here can compaction
drop the instruction entirely.

It needs the stack up (``make dev``). Everything it does goes through public
HTTP endpoints — no in-process shortcuts — so a pass here is a statement about
the deployed system.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8001"
# A large document against a small local model is genuinely slow: 150 map calls
# at a few seconds each. A timeout shorter than the work turns every real run
# into a false failure.
DEFAULT_TIMEOUT_SECONDS = 3_600


@dataclass
class AgentRun:
    """The agent's final answer plus the trace needed to explain it."""

    answer: str
    coverage: str = ""
    thread_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    used_analyze_document: bool = False
    message_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "coverage": self.coverage,
            "thread_id": self.thread_id,
            "tool_calls": self.tool_calls,
            "used_analyze_document": self.used_analyze_document,
            "message_count": self.message_count,
            "error": self.error,
        }


def _headers() -> dict[str, str]:
    """Bearer token from the environment, never from a flag or a file.

    A token on the command line lands in shell history and in the run record
    this harness writes; an env var does neither.
    """
    token = os.environ.get("DEER_FLOW_API_TOKEN") or os.environ.get("DEER_FLOW_DRIFT_EVAL_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _text_of_message(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""


async def run_agent_primary(
    pdf_path: Path,
    task: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    thread_id: str | None = None,
    assistant_id: str = "agent",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AgentRun:
    """Upload *pdf_path* to a thread and give the agent *task* over it."""
    import uuid

    import httpx

    thread = thread_id or f"drift-eval-{uuid.uuid4().hex[:12]}"
    base = base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=timeout, headers=_headers()) as client:
        try:
            with pdf_path.open("rb") as handle:
                upload = await client.post(
                    f"{base}/api/threads/{thread}/uploads",
                    files={"files": (pdf_path.name, handle, "application/pdf")},
                )
            upload.raise_for_status()
            uploaded = upload.json().get("files") or []
        except Exception as exc:
            logger.exception("Upload failed")
            return AgentRun(answer="", thread_id=thread, error=f"upload failed: {type(exc).__name__}: {exc}")

        # The frontend attaches the upload metadata to the human message; the
        # UploadsMiddleware reads it from there and nowhere else, so a run that
        # omits it gets no <current_uploads> block and tests nothing.
        files_kwarg = [
            {
                "filename": entry.get("filename"),
                "size": entry.get("size", 0),
                "path": entry.get("path") or f"/mnt/user-data/uploads/{entry.get('filename')}",
                "status": "uploaded",
            }
            for entry in uploaded
        ]

        body = {
            "assistant_id": assistant_id,
            "input": {"messages": [{"role": "user", "content": task, "additional_kwargs": {"files": files_kwarg}}]},
            "config": {"configurable": {"thread_id": thread}},
        }
        try:
            response = await client.post(f"{base}/api/runs/wait", json=body)
            response.raise_for_status()
            state = response.json()
        except Exception as exc:
            logger.exception("Agent run failed")
            return AgentRun(answer="", thread_id=thread, error=f"run failed: {type(exc).__name__}: {exc}")

    if not isinstance(state, dict) or "messages" not in state:
        return AgentRun(answer="", thread_id=thread, error=f"run returned no state: {json.dumps(state)[:400]}")

    messages = state.get("messages") or []
    tool_calls: list[str] = []
    coverage_lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            name = call.get("name") if isinstance(call, dict) else None
            if name:
                tool_calls.append(name)
        # The tool states its own coverage in the string it returns; that line
        # is what the judge grades honesty against.
        if message.get("type") == "tool":
            text = _text_of_message(message)
            for line in text.splitlines():
                if "— source:" in line or "read " in line and " of " in line and " parts" in line:
                    coverage_lines.append(line.strip())

    final = ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("type") == "ai" and not message.get("tool_calls"):
            final = _text_of_message(message)
            if final.strip():
                break

    return AgentRun(
        answer=final,
        coverage="\n".join(coverage_lines),
        thread_id=thread,
        tool_calls=tool_calls,
        used_analyze_document="analyze_document" in tool_calls,
        message_count=len(messages),
    )
