"""Shared fakes for the local media generation tests (roadmap items 12–15).

The ComfyUI ``/object_info`` fixture is *derived from the template under test*
rather than hand-written, so a template edit cannot silently invalidate the
tests it is validated against. Enum values (checkpoints, unets, …) are injected
per test, which is what the interesting cases turn on.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from deerflow.community.comfyui.client import OutputFile, PromptResult
from deerflow.community.comfyui.templates import WorkflowTemplate

# A real 4x3 PNG: small enough to inline, valid enough for Pillow to open.
PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000040000000308020000003b9639910000001449444154789c633c51a1c100034c0c48008503003544016ef4272f230000000049454e44ae426082")


def runtime(outputs_path: str | None = None, thread_id: str = "thread-1"):
    state = {"thread_data": {"outputs_path": outputs_path} if outputs_path else {}}
    return SimpleNamespace(context={"thread_id": thread_id}, state=state)


def object_info_for(template: WorkflowTemplate, enums: dict[tuple[str, str], list[str]] | None = None) -> dict[str, Any]:
    """Build an /object_info catalogue that satisfies ``template``.

    ``enums`` maps ``(class_type, input_name)`` to the enum a real ComfyUI would
    report for it, e.g. the installed checkpoints.
    """
    enums = enums or {}
    catalogue: dict[str, Any] = {}
    for node in template.graph.values():
        class_type = str(node.get("class_type"))
        required = catalogue.setdefault(class_type, {"input": {"required": {}}})["input"]["required"]
        for input_name in node.get("inputs") or {}:
            values = enums.get((class_type, input_name))
            required[input_name] = [values, {}] if values is not None else ["STRING", {}]
    for (class_type, input_name), values in enums.items():
        required = catalogue.setdefault(class_type, {"input": {"required": {}}})["input"]["required"]
        required[input_name] = [values, {}]
    return catalogue


class FakeComfyUIClient:
    """Records what was submitted; returns canned outputs."""

    def __init__(
        self,
        object_info: dict[str, Any],
        *,
        outputs: list[OutputFile] | None = None,
        content: dict[str, bytes] | None = None,
        base_url: str = "http://localhost:8188",
        duration: float = 4.2,
    ) -> None:
        self.base_url = base_url
        self._object_info = object_info
        self._outputs = outputs or []
        self._content = content or {}
        self._duration = duration
        self.submitted: list[dict[str, Any]] = []
        self.timeouts: list[float] = []
        self.downloads: list[OutputFile] = []
        self.freed = 0
        self.stats: dict[str, Any] = {"devices": [{"torch_vram_total": 0}]}

    async def object_info(self) -> dict[str, Any]:
        return self._object_info

    async def run(self, graph: dict[str, Any], *, timeout: float, **kwargs: Any) -> PromptResult:
        self.submitted.append(graph)
        self.timeouts.append(timeout)
        return PromptResult(prompt_id="p1", outputs=list(self._outputs), duration_seconds=self._duration)

    async def download(self, output: OutputFile) -> bytes:
        self.downloads.append(output)
        return self._content.get(output.filename, PNG_1PX)

    async def system_stats(self) -> dict[str, Any]:
        return self.stats

    async def free(self, **kwargs: Any) -> bool:
        self.freed += 1
        return True


def image_output(filename: str = "deerflow_00001_.png") -> OutputFile:
    return OutputFile(filename=filename, subfolder="", type="output", node_id="9", kind="image")


def video_output(filename: str = "deerflow_00001.mp4") -> OutputFile:
    return OutputFile(filename=filename, subfolder="", type="output", node_id="12", kind="animation")


def frame_outputs(count: int) -> list[OutputFile]:
    return [OutputFile(filename=f"deerflow-frame_{index:05d}_.png", subfolder="", type="output", node_id="10", kind="image") for index in range(count)]
