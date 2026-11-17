"""FolderLedgerMiddleware: successful writes into writable custom mounts fill the folder ledger.

The recorder runs the real path classifier, real host probes against temporary
mount directories and the real synchronous ledger store on a SQLite file; only
the tool itself is a stand-in that writes the host file the way the local
sandbox does, and returns its result string.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from deerflow.agents.middlewares.folder_ledger_middleware import FolderLedgerMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware, build_lead_runtime_middlewares, build_subagent_runtime_middlewares
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig, VolumeMountConfig
from deerflow.folder_ledger.mounts import FolderClassifier
from deerflow.persistence.base import Base
from deerflow.persistence.folder_ledger import FolderLedgerDismissalRow, FolderLedgerEventRow, FolderLedgerFolderRow, FolderLedgerRecorderStore, FolderLedgerTouchRow
from deerflow.persistence.thread_meta.model import ThreadMetaRow

LOCAL = "deerflow.sandbox.local:LocalSandboxProvider"
_TABLES = [ThreadMetaRow, FolderLedgerFolderRow, FolderLedgerTouchRow, FolderLedgerEventRow, FolderLedgerDismissalRow]


@pytest.fixture
def hosts(tmp_path):
    projects = tmp_path / "projects"
    reference = tmp_path / "reference"
    projects.mkdir()
    reference.mkdir()
    return SimpleNamespace(projects=projects, reference=reference)


def _config(hosts, *, use=LOCAL, extra_mounts=(), **sandbox_kwargs):
    mounts = [
        VolumeMountConfig(host_path=str(hosts.projects), container_path="/mnt/projects"),
        VolumeMountConfig(host_path=str(hosts.reference), container_path="/mnt/reference", read_only=True),
        *extra_mounts,
    ]
    return SimpleNamespace(sandbox=SimpleNamespace(use=use, mounts=mounts, **sandbox_kwargs), skills=SimpleNamespace(container_path="/mnt/skills"), database=None)


@pytest.fixture
def ledger(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    Base.metadata.create_all(engine, tables=[model.__table__ for model in _TABLES])
    factory = sessionmaker(engine, expire_on_commit=False)
    store = FolderLedgerRecorderStore(factory)

    def rows(model):
        with factory() as session:
            return session.execute(select(model)).scalars().all()

    try:
        yield SimpleNamespace(store=store, rows=rows, factory=factory)
    finally:
        engine.dispose()


def _middleware(config, ledger, **kwargs):
    return FolderLedgerMiddleware(app_config=config, store_factory=lambda: ledger.store, ledger_available=lambda: True, **kwargs)


def _request(name, args, *, thread_id="thread-a", user_id="alice", run_id="run-1", call_id="call-1"):
    context = {"user_id": user_id, "run_id": run_id}
    if thread_id is not None:
        context["thread_id"] = thread_id
    return ToolCallRequest(tool_call={"name": name, "args": args, "id": call_id}, tool=None, state={"messages": []}, runtime=SimpleNamespace(context=context))


def _writing_tool(hosts, *, result="OK", status="success"):
    """Stand-in for the local sandbox's write_file: writes the host file, returns the tool string."""

    def handler(request):
        path = request.tool_call["args"]["path"]
        if result == "OK" and path.startswith("/mnt/projects/"):
            target = hosts.projects / path.removeprefix("/mnt/projects/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        return ToolMessage(content=result, tool_call_id=request.tool_call["id"], name=request.tool_call["name"], status=status)

    return handler


def _arun(middleware, request, handler):
    async def ahandler(req):
        return handler(req)

    return asyncio.run(middleware.awrap_tool_call(request, ahandler))


def test_write_creating_a_folder_is_observed_create(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)

    result = _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/index.html", "content": "x"}), _writing_tool(hosts))

    assert result.content == "OK"
    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert (folder.mount_path, folder.name, folder.kind) == ("/mnt/projects", "acme", "dir")
    assert (folder.created_attribution, folder.created_by_thread_id, folder.created_by_user_id) == ("observed_create", "thread-a", "alice")
    (touch,) = ledger.rows(FolderLedgerTouchRow)
    assert (touch.thread_id, touch.user_id, touch.role, touch.writes, touch.edits, touch.last_run_id) == ("thread-a", "alice", "created", 1, 0, "run-1")
    (event,) = ledger.rows(FolderLedgerEventRow)
    assert (event.op, event.rel_path, event.tool_call_id) == ("write", "acme/index.html", "call-1")


def test_write_into_an_existing_folder_is_preexisting(hosts, ledger):
    (hosts.projects / "legacy").mkdir()
    middleware = _middleware(_config(hosts), ledger)

    _arun(middleware, _request("write_file", {"path": "/mnt/projects/legacy/notes.md", "content": "x", "append": True}), _writing_tool(hosts))

    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert folder.created_attribution == "preexisting"
    assert folder.created_by_thread_id is None
    (touch,) = ledger.rows(FolderLedgerTouchRow)
    assert (touch.role, touch.writes) == ("edited", 1)
    assert ledger.rows(FolderLedgerEventRow)[0].op == "append"


def test_sync_path_records_and_str_replace_counts_an_edit(hosts, ledger):
    (hosts.projects / "acme").mkdir()
    middleware = _middleware(_config(hosts), ledger)

    def edit(request):
        return ToolMessage(content="OK", tool_call_id="call-1", name="str_replace")

    middleware.wrap_tool_call(_request("str_replace", {"path": "/mnt/projects/acme/a.py", "old_str": "a", "new_str": "b"}), edit)

    (touch,) = ledger.rows(FolderLedgerTouchRow)
    assert (touch.edits, touch.writes) == (1, 0)
    assert ledger.rows(FolderLedgerEventRow)[0].op == "edit"


@pytest.mark.parametrize(
    ("result", "status"),
    [("Error: String to replace not found in file: /mnt/projects/acme/a.py", "success"), ("Error: permission denied", "error"), ("Wrote 3 bytes", "success")],
)
def test_only_an_exact_ok_result_is_recorded(hosts, ledger, result, status):
    middleware = _middleware(_config(hosts), ledger)

    returned = _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/a.py", "content": "x"}), _writing_tool(hosts, result=result, status=status))

    assert returned.content == result
    assert ledger.rows(FolderLedgerFolderRow) == []


@pytest.mark.parametrize(
    "path",
    [
        "/mnt/user-data/workspace/report.md",  # the conversation's own folder
        "/mnt/reference/acme/a.md",  # read-only mount
        "/mnt/projects",  # the mount root
        "/mnt/projects/../projects/acme/a.md",  # traversal
        "/mnt/elsewhere/acme/a.md",  # not a mount
        "relative/acme.md",
    ],
)
def test_untracked_paths_are_ignored(hosts, ledger, path):
    middleware = _middleware(_config(hosts), ledger)
    calls = []

    def handler(request):
        calls.append(request)
        return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

    _arun(middleware, _request("write_file", {"path": path, "content": "x"}), handler)

    assert len(calls) == 1
    assert ledger.rows(FolderLedgerFolderRow) == []


def test_read_only_mount_nested_in_a_writable_one_wins(hosts, ledger, tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    config = _config(hosts, extra_mounts=[VolumeMountConfig(host_path=str(nested), container_path="/mnt/projects/vendor", read_only=True)])
    classifier = FolderClassifier(config)

    assert classifier.classify("/mnt/projects/vendor/lib/a.js") is None
    assert classifier.classify("/mnt/projects/acme/a.js").name == "acme"


def test_bare_file_at_the_mount_root_is_kind_file(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)

    _arun(middleware, _request("write_file", {"path": "/mnt/projects/TODO.md", "content": "x"}), _writing_tool(hosts))

    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert (folder.name, folder.kind, folder.created_attribution) == ("TODO.md", "file", "observed_create")


def test_no_thread_id_or_no_ledger_is_a_no_op(hosts, ledger):
    without_thread = _middleware(_config(hosts), ledger)
    _arun(without_thread, _request("write_file", {"path": "/mnt/projects/a/b.md", "content": "x"}, thread_id=None), _writing_tool(hosts))

    memory_backend = FolderLedgerMiddleware(app_config=_config(hosts), store_factory=lambda: ledger.store, ledger_available=lambda: False)
    _arun(memory_backend, _request("write_file", {"path": "/mnt/projects/c/d.md", "content": "x"}), _writing_tool(hosts))

    assert ledger.rows(FolderLedgerFolderRow) == []


def test_ledger_failure_fails_open(hosts, ledger, caplog):
    class BrokenStore:
        def record(self, records, removed=()):
            raise RuntimeError("database is locked")

    middleware = FolderLedgerMiddleware(app_config=_config(hosts), store_factory=BrokenStore, ledger_available=lambda: True)
    request = _request("write_file", {"path": "/mnt/projects/acme/a.md", "content": "x"})

    async_result = _arun(middleware, request, _writing_tool(hosts))
    sync_result = middleware.wrap_tool_call(request, _writing_tool(hosts))

    assert async_result.content == sync_result.content == "OK"
    assert async_result.status == "success"
    assert "could not record write_file" in caplog.text


def test_tool_exception_propagates_unchanged(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)

    def boom(request):
        raise ValueError("tool crashed")

    with pytest.raises(ValueError, match="tool crashed"):
        _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/a.md", "content": "x"}), boom)
    assert ledger.rows(FolderLedgerFolderRow) == []


def test_host_not_visible_records_preexisting_and_skips_bash(tmp_path, ledger):
    hosts = SimpleNamespace(projects=tmp_path / "docker-host-only", reference=tmp_path / "ref")
    middleware = _middleware(_config(hosts, use="deerflow.community.aio_sandbox:AioSandboxProvider"), ledger)

    def ok(request):
        return ToolMessage(content="OK", tool_call_id="call-1", name=request.tool_call["name"])

    _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/a.md", "content": "x"}), ok)
    _arun(middleware, _request("bash", {"command": "mkdir -p /mnt/projects/other"}), ok)

    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert (folder.name, folder.created_attribution) == ("acme", "preexisting")


def test_bash_reference_that_appears_is_inferred_shell_and_existing_one_is_a_shell_touch(hosts, ledger):
    (hosts.projects / "old").mkdir()
    middleware = _middleware(_config(hosts), ledger)

    def shell(request):
        (hosts.projects / "fresh").mkdir()
        (hosts.projects / "unreferenced").mkdir()  # e.g. another conversation's concurrent write
        return ToolMessage(content="done", tool_call_id="call-1", name="bash")

    command = "mkdir -p /mnt/projects/fresh && cp -r /mnt/projects/old/x /mnt/projects/fresh/ && ls /mnt/projects/ghost /mnt/reference/r"
    _arun(middleware, _request("bash", {"command": command}), shell)

    folders = {row.name: row for row in ledger.rows(FolderLedgerFolderRow)}
    assert set(folders) == {"fresh", "old"}
    assert folders["fresh"].created_attribution == "inferred_shell"
    assert folders["old"].created_attribution == "preexisting"
    assert {(touch.role, touch.shell_ops) for touch in ledger.rows(FolderLedgerTouchRow)} == {("created", 1), ("edited", 1)}


def _identity(path: Path) -> str:
    info = os.lstat(path)
    return f"{info.st_dev}:{info.st_ino}"


def test_a_created_folder_is_bound_to_its_host_entry(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)

    _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/index.html", "content": "x"}), _writing_tool(hosts))

    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert (folder.host_root, folder.host_entry) == (os.path.normpath(hosts.projects), _identity(hosts.projects / "acme"))


@pytest.mark.skipif(os.name != "posix", reason="atomic replace gives the file a new inode")
def test_the_binding_follows_a_recorded_rewrite_of_a_bare_file(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)

    def replacing_tool(request):
        staged = hosts.projects / ".TODO.md.tmp"
        staged.write_text(request.tool_call["args"]["content"], encoding="utf-8")
        os.replace(staged, hosts.projects / "TODO.md")
        return ToolMessage(content="OK", tool_call_id="call-1", name="write_file")

    _arun(middleware, _request("write_file", {"path": "/mnt/projects/TODO.md", "content": "one"}), replacing_tool)
    first = _identity(hosts.projects / "TODO.md")
    _arun(middleware, _request("write_file", {"path": "/mnt/projects/TODO.md", "content": "two"}), replacing_tool)

    (folder,) = ledger.rows(FolderLedgerFolderRow)
    assert folder.host_entry == _identity(hosts.projects / "TODO.md") != first


def test_a_folder_a_command_removed_is_retired_and_the_next_creator_is_credited(hosts, ledger):
    middleware = _middleware(_config(hosts), ledger)
    _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/a.md", "content": "x"}, thread_id="alice-1", user_id="alice"), _writing_tool(hosts))

    def remove(request):
        (hosts.projects / "acme" / "a.md").unlink()
        (hosts.projects / "acme").rmdir()
        return ToolMessage(content="", tool_call_id="call-1", name="bash")

    _arun(middleware, _request("bash", {"command": "rm -rf /mnt/projects/acme"}, thread_id="alice-1", user_id="alice"), remove)
    _arun(middleware, _request("write_file", {"path": "/mnt/projects/acme/b.md", "content": "x"}, thread_id="bob-1", user_id="bob"), _writing_tool(hosts))

    live = [row for row in ledger.rows(FolderLedgerFolderRow) if row.deleted_at is None]
    assert [(row.name, row.created_attribution, row.created_by_user_id, row.created_by_thread_id) for row in live] == [("acme", "observed_create", "bob", "bob-1")]


def test_mounts_ignored_by_the_provider_track_nothing(hosts):
    for config in (
        _config(hosts, use="deerflow.community.aio_sandbox:AioSandboxProvider", base_url="http://sandbox:8080"),
        _config(hosts, use="deerflow.community.aio_sandbox:AioSandboxProvider", provisioner_url="http://provisioner"),
        _config(hosts, use="deerflow.community.e2b_sandbox:E2BSandboxProvider"),
    ):
        assert FolderLedgerMiddleware(app_config=config).tracks_anything is False


def _app_config(hosts, *, read_only=False) -> AppConfig:
    return AppConfig(
        models=[ModelConfig(name="test-model", display_name="test-model", description=None, use="langchain_openai:ChatOpenAI", model="test-model")],
        sandbox=SandboxConfig(use=LOCAL, mounts=[VolumeMountConfig(host_path=str(hosts.projects), container_path="/mnt/projects", read_only=read_only)]),
    )


@pytest.mark.parametrize("builder", [build_lead_runtime_middlewares, build_subagent_runtime_middlewares])
def test_shared_chain_places_it_just_outside_tool_error_handling(hosts, builder):
    middlewares = builder(app_config=_app_config(hosts), lazy_init=False)
    names = [type(m).__name__ for m in middlewares]

    ledger_index = names.index("FolderLedgerMiddleware")
    assert isinstance(middlewares[ledger_index + 1], ToolErrorHandlingMiddleware), names


def test_chain_omits_it_without_a_writable_mount(hosts):
    middlewares = build_subagent_runtime_middlewares(app_config=_app_config(hosts, read_only=True), lazy_init=False)

    assert "FolderLedgerMiddleware" not in [type(m).__name__ for m in middlewares]


@pytest.mark.skipif(os.name != "posix", reason="POSIX path semantics for host probes")
def test_real_tool_error_handling_result_is_still_recognized(hosts, ledger):
    """Inner ToolErrorHandling normalizes the result; the recorder still sees exactly OK."""
    middleware = _middleware(_config(hosts), ledger)
    inner = ToolErrorHandlingMiddleware()
    tool = _writing_tool(hosts)

    async def through_error_handling(request):
        async def raw(req):
            return tool(req)

        return await inner.awrap_tool_call(request, raw)

    asyncio.run(middleware.awrap_tool_call(_request("write_file", {"path": "/mnt/projects/acme/a.md", "content": "x"}), through_error_handling))

    assert [row.name for row in ledger.rows(FolderLedgerFolderRow)] == ["acme"]
    assert Path(hosts.projects / "acme" / "a.md").exists()


def test_default_store_writes_through_the_configured_sync_url(hosts, tmp_path):
    """Without an injected store the recorder uses ``database.app_sync_sqlalchemy_url``."""
    db = tmp_path / "gateway.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine, tables=[model.__table__ for model in _TABLES])
    config = _config(hosts)
    config.database = SimpleNamespace(app_sync_sqlalchemy_url=f"sqlite:///{db}")
    middleware = FolderLedgerMiddleware(app_config=config, ledger_available=lambda: True)
    try:
        _arun(middleware, _request("write_file", {"path": "/mnt/projects/site/index.html", "content": "x"}), _writing_tool(hosts))
        with sessionmaker(engine)() as session:
            names = [row.name for row in session.execute(select(FolderLedgerFolderRow)).scalars()]
    finally:
        engine.dispose()
    assert names == ["site"]


def test_unavailable_sync_engine_turns_recording_off_once(hosts, caplog):
    calls = []

    def missing_driver():
        calls.append(1)
        raise ImportError("psycopg")

    middleware = FolderLedgerMiddleware(app_config=_config(hosts), store_factory=missing_driver, ledger_available=lambda: True)
    for name in ("a", "b"):
        assert _arun(middleware, _request("write_file", {"path": f"/mnt/projects/{name}/x.md", "content": "x"}), _writing_tool(hosts)).content == "OK"

    assert calls == [1]
    assert caplog.text.count("recording is off") == 1
