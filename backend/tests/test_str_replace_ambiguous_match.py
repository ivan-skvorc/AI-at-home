"""str_replace refuses an ``old_str`` that matches more than one place.

The tool's contract always said "must appear exactly once", but the code
replaced the first occurrence and reported ``OK``: an edit aimed at the second
``return None`` landed on the first, and nothing told the model. The refusal
names the lines so a retry with more context is one call, and it leaves the
file untouched. ``replace_all=True`` is the explicit way to change every copy.

The same module appends a syntax warning to a successful write that leaves a
Python/JSON/YAML/TOML file unparseable (FORK.md §55); the write itself still
happens, because a file written in parts is legitimately broken in between.
"""

from pathlib import Path
from types import SimpleNamespace

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.tools import str_replace_tool, write_file_tool


def _runtime(tmp_path: Path) -> SimpleNamespace:
    for sub in ("workspace", "uploads", "outputs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    thread_data = {
        "workspace_path": str(tmp_path / "workspace"),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "outputs"),
    }
    return SimpleNamespace(state={"sandbox": {"sandbox_id": "local:t1"}, "thread_data": thread_data}, context={"thread_id": "t1"})


def _patch_sandbox(monkeypatch) -> None:
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: LocalSandbox("t1"))
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_thread_directories_exist", lambda runtime: None)


def _replace(tmp_path, monkeypatch, *, name: str, content: str, old_str: str, new_str: str, replace_all: bool = False) -> tuple[str, str]:
    _patch_sandbox(monkeypatch)
    runtime = _runtime(tmp_path)
    target = tmp_path / "workspace" / name
    target.write_text(content, encoding="utf-8")
    result = str_replace_tool.func(runtime=runtime, path=f"/mnt/user-data/workspace/{name}", old_str=old_str, new_str=new_str, replace_all=replace_all)
    return result, target.read_text(encoding="utf-8")


SOURCE = "def a():\n    return None\n\n\ndef b():\n    return None\n"


def test_a_repeated_old_str_is_refused_and_the_file_is_left_alone(tmp_path, monkeypatch) -> None:
    result, after = _replace(tmp_path, monkeypatch, name="m.py", content=SOURCE, old_str="    return None", new_str="    return 1")

    assert result.startswith("Error:"), result
    assert "matches 2 places" in result
    assert "lines 2, 6" in result
    assert "replace_all=true" in result
    assert after == SOURCE


def test_context_that_makes_it_unique_succeeds(tmp_path, monkeypatch) -> None:
    result, after = _replace(tmp_path, monkeypatch, name="m.py", content=SOURCE, old_str="def b():\n    return None", new_str="def b():\n    return 1")

    assert result == "OK"
    assert after == "def a():\n    return None\n\n\ndef b():\n    return 1\n"


def test_replace_all_still_changes_every_copy(tmp_path, monkeypatch) -> None:
    result, after = _replace(tmp_path, monkeypatch, name="m.py", content=SOURCE, old_str="return None", new_str="return 0", replace_all=True)

    assert result == "OK"
    assert after.count("return 0") == 2


def test_many_matches_list_a_bounded_set_of_lines(tmp_path, monkeypatch) -> None:
    content = "x = 1\n" * 30
    result, after = _replace(tmp_path, monkeypatch, name="data.txt", content=content, old_str="x = 1", new_str="x = 2")

    assert "matches 30 places" in result
    assert result.count(",") <= 12 and ", ..." in result
    assert after == content


def test_an_edit_that_breaks_python_succeeds_with_a_warning(tmp_path, monkeypatch) -> None:
    result, after = _replace(tmp_path, monkeypatch, name="m.py", content=SOURCE, old_str="def b():", new_str="def b(:")

    assert result.startswith("OK\n\nWarning: /mnt/user-data/workspace/m.py does not parse"), result
    assert "Python syntax error at line 5" in result
    assert "def b(:" in after  # advisory, not a block


def test_write_file_warns_on_invalid_json_but_writes_it(tmp_path, monkeypatch) -> None:
    _patch_sandbox(monkeypatch)
    result = write_file_tool.func(runtime=_runtime(tmp_path), path="/mnt/user-data/workspace/cfg.json", content='{"a": 1,, }')

    assert result.startswith("OK\n\nWarning:"), result
    assert "Invalid JSON" in result
    assert (tmp_path / "workspace" / "cfg.json").read_text(encoding="utf-8") == '{"a": 1,, }'


def test_write_file_stays_plain_ok_for_valid_or_unchecked_content(tmp_path, monkeypatch) -> None:
    _patch_sandbox(monkeypatch)
    runtime = _runtime(tmp_path)

    assert write_file_tool.func(runtime=runtime, path="/mnt/user-data/workspace/ok.py", content="print('hi')\n") == "OK"
    assert write_file_tool.func(runtime=runtime, path="/mnt/user-data/workspace/notes.md", content="def (:\n") == "OK"
    # An append carries only the tail; a half-written file is not judged.
    assert write_file_tool.func(runtime=runtime, path="/mnt/user-data/workspace/ok.py", content="def broken(:\n", append=True) == "OK"
