"""The child process is bounded and isolated, whatever it does.

These tests replace ``worker.py`` with small stand-ins, so they need no CAD
kernel: what is under test is the parent's hold on the child.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from pathlib import Path

import pytest

from deerflow_extension_cad import tool

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups and signals are POSIX")


def _stand_in(tmp_path: Path, monkeypatch, body: str) -> Path:
    script = tmp_path / "stand_in_worker.py"
    pid_file = tmp_path / "child.pid"
    script.write_text(f"import json, os, signal, sys, time\nopen({str(pid_file)!r}, 'w').write(str(os.getpid()))\n{body}\n", encoding="utf-8")
    monkeypatch.setattr(tool, "WORKER", script)
    return pid_file


def _gone(pid_file: Path) -> bool:
    pid = int(pid_file.read_text())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    # Killed and waiting for its new parent to collect it: dead, as far as running goes.
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().rpartition(")")[2].split()[0] == "Z"


def _leftovers() -> set[str]:
    import tempfile

    return {name for name in os.listdir(tempfile.gettempdir()) if name.startswith("deerflow-cad-")}


async def test_a_build_past_its_wall_clock_is_killed_and_reported(tmp_path, monkeypatch):
    pid_file = _stand_in(tmp_path, monkeypatch, "time.sleep(60)")
    before = _leftovers()
    started = time.monotonic()
    result = await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    assert time.monotonic() - started < 10
    assert result["status"] == "failed" and "did not finish within 1 seconds" in result["message"]
    assert _gone(pid_file)
    assert _leftovers() == before


async def test_a_cancelled_tool_call_does_not_leave_a_kernel_running(tmp_path, monkeypatch):
    # The host stops a plugin tool after 30 seconds by cancelling it; a stopped run does the same.
    pid_file = _stand_in(tmp_path, monkeypatch, "time.sleep(60)")
    before = _leftovers()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(tool.run_worker("x = 1", timeout_seconds=25, memory_mb=4096), 1)
    assert _gone(pid_file)
    assert _leftovers() == before


async def test_a_child_that_ignores_the_polite_signal_is_still_killed(tmp_path, monkeypatch):
    pid_file = _stand_in(tmp_path, monkeypatch, "signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)")
    result = await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    assert result["status"] == "failed" and _gone(pid_file)


async def test_a_grandchild_is_killed_with_the_worker(tmp_path, monkeypatch):
    grandchild = tmp_path / "grandchild.pid"
    body = f"import subprocess\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\nopen({str(grandchild)!r}, 'w').write(str(p.pid))\ntime.sleep(60)"
    _stand_in(tmp_path, monkeypatch, body)
    await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    await asyncio.sleep(0.2)
    assert _gone(grandchild)


async def test_a_crashed_kernel_is_an_answer_not_an_exception(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, "os.kill(os.getpid(), signal.SIGSEGV)")
    result = await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096)
    assert result == {"status": "failed", "message": f"the CAD kernel stopped without an answer (signal {int(signal.SIGSEGV)}); it may have run out of memory"}


async def test_the_child_sees_the_script_but_nothing_of_the_gateways_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    body = (
        "request = json.load(open('request.json'))\n"
        "json.dump({'status': 'built', 'measured': {'environment': sorted(os.environ), 'isolated': sys.flags.isolated, 'cwd': os.getcwd(),"
        " 'script': request['script'], 'stdin': sys.stdin.read()}, 'files': {}}, open('result.json', 'w'))"
    )
    _stand_in(tmp_path, monkeypatch, body)
    result = await tool.run_worker("the script text", timeout_seconds=5, memory_mb=4096)
    seen = result["measured"]
    assert seen["script"] == "the script text"
    assert seen["isolated"] == 1
    assert "OPENAI_API_KEY" not in seen["environment"] and "PYTHONPATH" not in seen["environment"]
    assert set(seen["environment"]) <= {"PATH", "LANG", "HOME", "LC_CTYPE", "OPENBLAS_NUM_THREADS"}
    assert Path(seen["cwd"]).name.startswith("deerflow-cad-") and not Path(seen["cwd"]).exists()
    assert seen["stdin"] == ""


async def test_only_bounded_files_from_the_childs_own_directory_are_read(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the conversation")
    body = (
        f"os.symlink({str(secret)!r}, 'link.step')\n"
        "open('part.glb', 'wb').write(b'glTF')\n"
        f"open('big.stl', 'wb').truncate({tool.MAX_EXPORT_BYTES + 1})\n"
        f"json.dump({{'status': 'built', 'measured': {{}}, 'files': {{'step': 'link.step', 'outside': {str(secret)!r}, 'up': '../x', 'stl': 'big.stl', 'glb': 'part.glb'}}}}, open('result.json', 'w'))"
    )
    _stand_in(tmp_path, monkeypatch, body)
    result = await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096)
    # A link, a path outside the directory and a file over the cap are not read into the Gateway.
    assert result["files"] == {"glb": b"glTF"}


async def test_an_oversized_or_malformed_answer_is_not_trusted(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, f"open('result.json', 'w').write('[' + '0,' * {tool.MAX_RESULT_BYTES} + '0]')")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"
    _stand_in(tmp_path, monkeypatch, "open('result.json', 'w').write('[1, 2]')")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"
    _stand_in(tmp_path, monkeypatch, "open('result.json', 'w').write('not json')")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"


def test_the_real_worker_applies_the_memory_ceiling_before_it_reads_the_script():
    source = (Path(tool.__file__).with_name("worker.py")).read_text(encoding="utf-8")
    assert source.index("_limit(") < source.index("compile_script(request")
    assert json.dumps({"memory_mb": 1}) and tool.MIN_MEMORY_MB >= 2048
