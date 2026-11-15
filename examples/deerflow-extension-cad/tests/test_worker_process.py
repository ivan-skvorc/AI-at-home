"""The child process is bounded and isolated, whatever it does.

These tests replace ``worker.py`` with small stand-ins, so they need no CAD
kernel: what is under test is the parent's hold on the child.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
import threading
import time
from pathlib import Path

import pytest

from deerflow_extension_cad import tool

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups and signals are POSIX")


@pytest.fixture(autouse=True)
def own_build_directory(tmp_path, monkeypatch):
    """Builds of this test only: another build on the machine must not read as a leftover."""
    builds = tmp_path / "builds"
    builds.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(builds))


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
    started = time.monotonic()
    result = await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    # Within seconds: a signal the child may ignore would return only when its own sleep ends.
    assert time.monotonic() - started < 10
    assert result["status"] == "failed" and _gone(pid_file)


async def test_a_grandchild_is_killed_with_the_worker(tmp_path, monkeypatch):
    grandchild = tmp_path / "grandchild.pid"
    body = f"import subprocess\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\nopen({str(grandchild)!r}, 'w').write(str(p.pid))\ntime.sleep(60)"
    _stand_in(tmp_path, monkeypatch, body)
    started = time.monotonic()
    await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    assert time.monotonic() - started < 10
    await asyncio.sleep(0.2)
    assert _gone(grandchild)


async def test_a_grandchild_does_not_outlive_a_worker_that_finished_by_itself(tmp_path, monkeypatch):
    # The worker starts no process of its own; one that exists means the kernel was made to, and it is not left running.
    grandchild = tmp_path / "grandchild.pid"
    body = (
        f"import subprocess\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\nopen({str(grandchild)!r}, 'w').write(str(p.pid))\n"
        "json.dump({'status': 'built', 'measured': {}, 'files': {}}, open('result.json', 'w'))"
    )
    _stand_in(tmp_path, monkeypatch, body)
    result = await tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096)
    assert result["status"] == "built"
    await asyncio.sleep(0.2)
    assert _gone(grandchild)


async def test_a_second_cancellation_still_removes_the_script_from_disk(tmp_path, monkeypatch):
    pid_file = _stand_in(tmp_path, monkeypatch, "time.sleep(60)")
    task = asyncio.ensure_future(tool.run_worker("x = 1", timeout_seconds=25, memory_mb=4096))
    while not pid_file.exists():
        await asyncio.sleep(0.05)
    # Three in a row: the first reaches the wait, the second the clean-up, the third the shield around it.
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    assert _gone(pid_file) and _leftovers() == set()


def test_a_loop_that_ends_right_after_a_cancellation_leaves_no_kernel_no_script_and_no_taken_slot(tmp_path, monkeypatch):
    # The host runs tools on short-lived loops too. Clean-up left to a task alone never ran there:
    # a task cancelled before its first step does nothing.
    pid_file = _stand_in(tmp_path, monkeypatch, "time.sleep(60)")
    slots = threading.BoundedSemaphore(1)

    async def main():
        task = asyncio.ensure_future(tool.run_worker("x = 1", timeout_seconds=25, memory_mb=4096, slots=slots))
        while not pid_file.exists():
            await asyncio.sleep(0.05)
        task.cancel()

    thread = threading.Thread(target=lambda: asyncio.run(main()))
    thread.start()
    thread.join(30)
    time.sleep(0.3)
    assert _gone(pid_file) and _leftovers() == set()
    assert slots.acquire(blocking=False)


async def test_a_kernel_still_loading_at_the_time_limit_is_not_blamed_on_the_part(tmp_path, monkeypatch):
    # The first build after an install or an update: Python is still compiling the kernel's
    # modules when the clock runs out. What it compiled stays, so the next call is quick.
    _stand_in(tmp_path, monkeypatch, "open('phase', 'w').write('loading')\ntime.sleep(60)")
    result = await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    assert result["status"] == "loading" and "still loading" in result["message"] and "Simplify" not in result["message"]


async def test_a_build_stopped_while_measuring_is_not_told_to_simplify_its_pattern(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, "open('phase', 'w').write('measuring')\ntime.sleep(60)")
    result = await tool.run_worker("x = 1", timeout_seconds=1, memory_mb=4096)
    assert result["status"] == "failed" and "measuring it did not finish" in result["message"] and "pattern points" not in result["message"]


async def test_a_call_cancelled_while_its_directory_is_being_made_leaves_none(tmp_path, monkeypatch):
    real_prepare = tool._prepare

    def slow_prepare(*arguments):
        time.sleep(0.3)
        return real_prepare(*arguments)

    monkeypatch.setattr(tool, "_prepare", slow_prepare)
    _stand_in(tmp_path, monkeypatch, "time.sleep(60)")
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(tool.run_worker("x = 1", timeout_seconds=25, memory_mb=4096), 0.1)
    await asyncio.sleep(0.8)
    assert _leftovers() == set()


def test_a_directory_being_made_when_its_loop_ends_is_removed_by_the_thread_that_made_it(tmp_path, monkeypatch):
    # No callback on a loop that is gone: the thread finds the call abandoned and cleans up after itself.
    real_prepare = tool._prepare

    def slow_prepare(*arguments):
        time.sleep(0.5)
        return real_prepare(*arguments)

    monkeypatch.setattr(tool, "_prepare", slow_prepare)
    _stand_in(tmp_path, monkeypatch, "time.sleep(60)")

    async def main():
        task = asyncio.ensure_future(tool.run_worker("x = 1", timeout_seconds=25, memory_mb=4096))
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(main())
    time.sleep(1.0)
    assert _leftovers() == set()


def test_a_request_that_cannot_be_written_leaves_no_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(tool.json, "dumps", lambda request: (_ for _ in ()).throw(OSError("No space left on device")))
    with pytest.raises(OSError):
        tool._prepare("x = 1", 4096, 20)
    assert _leftovers() == set()


async def test_builds_beyond_the_parallel_limit_are_told_to_call_again_and_the_slot_comes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "QUEUE_SECONDS", 0.3)
    _stand_in(tmp_path, monkeypatch, "time.sleep(2)\njson.dump({'status': 'built', 'measured': {}, 'files': {}}, open('result.json', 'w'))")
    slots = threading.BoundedSemaphore(1)
    first = asyncio.ensure_future(tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096, slots=slots))
    await asyncio.sleep(0.2)
    started = time.monotonic()
    second = await tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096, slots=slots)
    # Not a timeout that blames the part: the second build never started.
    assert second["status"] == "busy" and time.monotonic() - started < 1.5
    assert (await first)["status"] == "built"
    # The slot is back after a finished build and after a cancelled one.
    assert (await tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096, slots=slots))["status"] == "built"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096, slots=slots), 0.5)
    await asyncio.sleep(0.5)
    assert (await tool.run_worker("x = 1", timeout_seconds=10, memory_mb=4096, slots=slots))["status"] == "built"


async def test_the_processor_backstop_cannot_fire_before_the_wall_clock(tmp_path, monkeypatch):
    # The kernel works on several cores at once: a backstop counted in processor seconds of one core
    # stopped honest builds well inside their time and blamed memory.
    _stand_in(tmp_path, monkeypatch, "request = json.load(open('request.json'))\njson.dump({'status': 'built', 'measured': request, 'files': {}}, open('result.json', 'w'))")
    request = (await tool.run_worker("x = 1", timeout_seconds=7, memory_mb=4096))["measured"]
    assert request["cpu_seconds"] > 7 * (os.cpu_count() or 1)


async def test_a_crashed_kernel_is_an_answer_not_an_exception(tmp_path, monkeypatch):
    _stand_in(tmp_path, monkeypatch, "os.kill(os.getpid(), signal.SIGSEGV)")
    result = await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096)
    assert result["status"] == "failed"
    assert f"stopped without an answer (signal {int(signal.SIGSEGV)})" in result["message"] and "memory or processor time" in result["message"]


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
    # Well-formed and claiming success, but larger than the Gateway reads.
    _stand_in(tmp_path, monkeypatch, f"json.dump({{'status': 'built', 'measured': {{'pad': 'x' * {tool.MAX_RESULT_BYTES}}}, 'files': {{}}}}, open('result.json', 'w'))")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"
    _stand_in(tmp_path, monkeypatch, "open('result.json', 'w').write('[1, 2]')")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"
    _stand_in(tmp_path, monkeypatch, "open('result.json', 'w').write('not json')")
    assert (await tool.run_worker("x = 1", timeout_seconds=5, memory_mb=4096))["status"] == "failed"


def test_the_real_worker_answers_for_a_fault_of_its_own_instead_of_dying_silently(tmp_path):
    # Without an answer the parent can only guess ("it may have run out of memory"), which sends a model the wrong way.
    import subprocess
    import sys

    (tmp_path / "request.json").write_text("{}", encoding="utf-8")
    worker = Path(tool.__file__).with_name("worker.py")
    subprocess.run([sys.executable, "-I", str(worker)], cwd=tmp_path, check=False, timeout=60, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    answer = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert answer["status"] == "failed" and "KeyError" in answer["message"] and "could not finish" in answer["message"]


def test_the_real_worker_applies_the_memory_ceiling_before_it_reads_the_script():
    source = (Path(tool.__file__).with_name("worker.py")).read_text(encoding="utf-8")
    main = source[source.index("def main()") :]
    assert 0 < main.index("_limit(int(request") < main.index("compile_script(request")


def test_a_mesh_file_cut_short_is_recognised(tmp_path):
    from deerflow_extension_cad import build

    triangle = bytes(50)
    whole, cut = tmp_path / "whole.stl", tmp_path / "cut.stl"
    whole.write_bytes(bytes(80) + (2).to_bytes(4, "little") + triangle * 2)
    cut.write_bytes(bytes(80) + (2).to_bytes(4, "little") + triangle)
    assert build.whole_stl(whole) and not build.whole_stl(cut) and not build.whole_stl(tmp_path / "missing.stl")
