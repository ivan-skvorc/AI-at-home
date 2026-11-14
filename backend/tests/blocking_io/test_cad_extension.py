"""The CAD tool must never make the Gateway's event loop wait on a build.

The real handler runs here with its real child-process plumbing (spawn, wall
clock, reading the answer and the exported files, cleaning up) and the host's
real writer. Only the worker script is a stand-in, because the kernel is not
installed in the backend environment and what is under test is the parent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Imported here, not in the test: a first import reads files, and the gate is
# about the tool call, not about module loading.
import deerflow.sandbox.tools  # noqa: F401
from deerflow.config import paths
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.plugin_tools import build_plugin_tools

PACKAGE = Path(__file__).resolve().parents[3] / "examples" / "deerflow-extension-cad"
sys.path.insert(0, str(PACKAGE))
import deerflow_extension_cad.tool as cad_tool  # noqa: E402

STAND_IN = """\
import json, time
time.sleep(0.3)
open("part.step", "wb").write(b"ISO-10303-21;" + b"x" * 200000)
open("part.stl", "wb").write(b"stl" * 1000)
open("part.glb", "wb").write(b"glTF" + b"\\x00" * 1000)
measured = {"solids": 1, "valid": True, "closed": True, "bbox_mm": [1.0, 1.0, 1.0], "volume_mm3": 1.0, "holes": []}
json.dump({"status": "built", "measured": measured, "files": {"step": "part.step", "stl": "part.stl", "glb": "part.glb"}}, open("result.json", "w"))
"""


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "posix", reason="the worker is started in its own POSIX session")
async def test_cad_build_does_not_block_the_event_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths, "_paths", None)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda **kwargs: SimpleNamespace(uses_thread_data_mounts=True))
    worker = tmp_path / "stand_in_worker.py"
    await asyncio.to_thread(worker.write_text, STAND_IN, "utf-8")
    monkeypatch.setattr(cad_tool, "WORKER", worker)

    loaded, diagnostics = await asyncio.to_thread(load_extensions, [ExtensionSpec(use="deerflow_extension_cad:install", config={})])
    assert not diagnostics
    (tool,) = build_plugin_tools(loaded)
    outputs = await asyncio.to_thread(lambda: paths.get_paths().sandbox_outputs_dir("thread", user_id="alice"))
    runtime = SimpleNamespace(context={"user_id": "alice", "thread_id": "thread"}, config={"configurable": {"user_id": "alice"}}, state={"thread_data": {"outputs_path": str(outputs)}}, tool_call_id="call")

    # A heartbeat on the same loop: if the build made the loop wait, it would miss beats.
    beats = 0

    async def heartbeat():
        nonlocal beats
        while True:
            await asyncio.sleep(0.02)
            beats += 1

    pulse = asyncio.create_task(heartbeat())
    try:
        command = await tool.coroutine(runtime=runtime, name="cube", script="result = cq.Workplane('XY').box(1, 1, 1)\n", bbox_xyz_mm=[1, 1, 1])
    finally:
        pulse.cancel()

    answer = json.loads(command.update["messages"][0].content)
    assert answer["passed"] is True
    assert sorted(Path(path).name for path in command.update["artifacts"]) == ["cube.glb", "cube.py", "cube.report.json", "cube.step", "cube.stl"]
    assert len(await asyncio.to_thread((outputs / "cube.step").read_bytes)) == 200013
    assert beats >= 5
