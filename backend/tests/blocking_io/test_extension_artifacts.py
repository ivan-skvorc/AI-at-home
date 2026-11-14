"""Artifact import must keep real file publication off the Gateway event loop."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from deerflow_extension_api.plugins import ModelTool, PluginContribution

# Imported here, not in the test: a first import reads files, and the gate
# below is about the write path, not about module loading.
import deerflow.sandbox.tools  # noqa: F401
from deerflow.config import paths
from deerflow.extensions.plugin_tools import build_plugin_tools
from deerflow.extensions.registry import ExtensionRegistry


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="Descriptor-confined imports require POSIX")
async def test_import_retained_artifact_does_not_block_event_loop(tmp_path, monkeypatch):
    from app.gateway import extension_artifacts
    from deerflow.config.paths import get_paths

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(extension_artifacts, "get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))
    content = b"binary\x00\xff" * 1024
    result = await extension_artifacts.import_snapshot(None, "alice", "thread", "fixture", "report.pdf", content)
    captured = await asyncio.to_thread(lambda: (get_paths().sandbox_uploads_dir("thread", user_id="alice") / result["filename"]).read_bytes())
    assert captured == content


@pytest.mark.asyncio
async def test_plugin_tool_file_output_does_not_block_event_loop(tmp_path, monkeypatch):
    """The in-run write (API 0.2.12) reads its caps, writes and copies off the loop."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "_paths", None)
    copied = []

    class RemoteSandbox:
        def update_file(self, path, content):
            # A real remote copy is a blocking network call; stand in with file I/O.
            (tmp_path / "remote-copy.bin").write_bytes(content)
            copied.append(path)

    async def run_sandbox(runtime):
        return RemoteSandbox()

    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda **kwargs: SimpleNamespace(uses_thread_data_mounts=False))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized_async", run_sandbox)
    content = b"binary\x00\xff" * 1024

    async def handler(payload, context):
        return {"path": await context.write_output("report.bin", content)}

    registry = ExtensionRegistry()
    plugin = PluginContribution(namespace="community.files", title="Files", enabled=True, tools=(ModelTool("write", "Write a file", {"type": "object", "properties": {}}, handler),))
    with registry.attributed_to("test"):
        registry.plugin(plugin)
    (tool,) = build_plugin_tools(registry.build())
    outputs = await asyncio.to_thread(lambda: paths.get_paths().sandbox_outputs_dir("thread", user_id="alice"))
    runtime = SimpleNamespace(context={"user_id": "alice", "thread_id": "thread"}, config={"configurable": {"user_id": "alice"}}, state={"thread_data": {"outputs_path": str(outputs)}}, tool_call_id="call")

    command = await tool.coroutine(runtime=runtime)

    assert command.update["artifacts"] == ["/mnt/user-data/outputs/report.bin"]
    assert copied == ["/mnt/user-data/outputs/report.bin"]
    assert await asyncio.to_thread((outputs / "report.bin").read_bytes) == content
