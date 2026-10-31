"""Host side of extension API 0.2.10, which Double Plus Ultracode builds on.

Per-run plugin options (run-only, bounded), the host-stamped marker on messages
an extension posts, server-owned child-thread links and the parent's spend
roll-up, and AgentRuns workspace copy/merge with its safety rules.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow_extension_api import EXTENSION_MESSAGE_ORIGIN_KEY, AgentRunError, WorkspaceSnapshot, plugin_run_options
from fastapi import HTTPException
from test_extension_agent_runs import host as _host_fixture  # noqa: F401
from test_extension_agent_runs import runtime as _runtime_fixture  # noqa: F401

from app.gateway import extension_workspaces as workspaces
from app.gateway.services import merge_run_context_overrides, normalize_input, sanitize_plugin_options
from deerflow.config.paths import Paths

host = _host_fixture
runtime = _runtime_fixture

posix_only = pytest.mark.skipif(os.name != "posix", reason="Workspace copies use POSIX descriptor-relative IO")


# --- Per-run plugin options ---------------------------------------------------


def test_plugin_options_are_run_only_and_never_a_checkpoint_default():
    config = {"configurable": {"plugin_options": {"stale": {}}}, "context": {}}
    options = {"community.workflows": {"mode": "ultracode", "max_agents": 9}}
    merge_run_context_overrides(config, {"plugin_options": options})
    assert config["context"]["plugin_options"] == options
    assert "plugin_options" not in config["configurable"]
    # A copy, so a later mutation of the request body cannot reach the run.
    options["community.workflows"]["max_agents"] = 1_000
    assert config["context"]["plugin_options"]["community.workflows"]["max_agents"] == 9


@pytest.mark.parametrize(
    "value",
    [
        "ultracode",
        {"a:b": {}},
        {"": {}},
        {"ns": "not an object"},
        {"ns": {"x": float("nan")}},
        {"ns": {"x": "y" * 5000}},
        {f"ns{i}": {} for i in range(9)},
    ],
)
def test_malformed_plugin_options_are_refused(value):
    assert sanitize_plugin_options(value) is None
    with pytest.raises(HTTPException) as refused:
        merge_run_context_overrides({"configurable": {}, "context": {}}, {"plugin_options": value})
    assert refused.value.status_code == 400


def test_plugin_options_smuggled_through_config_are_sanitized_or_dropped():
    config = {"configurable": {}, "context": {"plugin_options": {"ns": "bad"}}}
    merge_run_context_overrides(config, {"model_name": "m"})
    assert "plugin_options" not in config["context"]


def test_a_tool_receives_only_its_own_plugin_slice():
    context = {"plugin_options": {"community.workflows": {"mode": "ultracode"}, "community.other": {"secret": 1}}}
    assert dict(plugin_run_options(context, "community.workflows")) == {"mode": "ultracode"}
    assert dict(plugin_run_options(context, "community.missing")) == {}
    assert dict(plugin_run_options({"plugin_options": "bad"}, "community.workflows")) == {}


@pytest.mark.asyncio
async def test_plugin_tool_dispatch_passes_the_run_options(monkeypatch):
    from deerflow_extension_api import ModelTool, PluginContribution

    from deerflow.extensions import plugin_tools

    seen = {}

    async def handler(payload, context):
        seen["options"] = dict(context.run_options)
        return {"ok": True}

    plugin = PluginContribution(namespace="community.probe", title="Probe", enabled=True, tools=(ModelTool("probe", "Probe tool", {"type": "object", "properties": {}, "additionalProperties": False}, handler),))
    monkeypatch.setattr(plugin_tools, "plugin_settings", lambda source, plugin: {"enabled": True})
    (tool,) = plugin_tools.build_plugin_tools(SimpleNamespace(plugins=[("probe", plugin)]))
    runtime_context = {"thread_id": "t1", "user_id": "alice", "plugin_options": {"community.probe": {"limit": 3}, "community.other": {"x": 1}}}
    await tool.coroutine(runtime=SimpleNamespace(context=runtime_context, config={"configurable": {"user_id": "alice"}}))
    assert seen["options"] == {"limit": 3}


# --- Messages an extension posts ---------------------------------------------


def test_browser_copies_of_the_marker_are_stripped():
    normalized = normalize_input({"messages": [{"role": "user", "content": "hi", "additional_kwargs": {EXTENSION_MESSAGE_ORIGIN_KEY: {"namespace": "community.workflows"}}}]})
    assert EXTENSION_MESSAGE_ORIGIN_KEY not in normalized["messages"][0].additional_kwargs


@pytest.mark.asyncio
async def test_plugin_scoped_runs_mark_their_input_and_unscoped_ones_do_not(runtime):
    runs, _, _, _, _ = runtime
    scoped = runs.for_plugin("community.workflows")
    thread = await scoped.create_thread(thread_id="posted")
    forged = {"messages": [{"role": "user", "content": "result", "additional_kwargs": {EXTENSION_MESSAGE_ORIGIN_KEY: {"namespace": "community.evil"}}}]}
    run = await scoped.start(thread_id=thread, input=forged)
    assert (await scoped.wait(thread_id=thread, run_id=run.run_id, timeout=5)).status == "success"
    first = (await scoped.get_state(thread_id=thread))["values"]["messages"][0]
    assert first["additional_kwargs"][EXTENSION_MESSAGE_ORIGIN_KEY] == {"namespace": "community.workflows"}

    plain = await runs.create_thread(thread_id="unscoped")
    run = await runs.start(thread_id=plain, input=forged)
    assert (await runs.wait(thread_id=plain, run_id=run.run_id, timeout=5)).status == "success"
    first = (await runs.get_state(thread_id=plain))["values"]["messages"][0]
    assert EXTENSION_MESSAGE_ORIGIN_KEY not in first.get("additional_kwargs", {})


# --- Child-thread links --------------------------------------------------------


@pytest.mark.asyncio
async def test_child_thread_links_are_server_owned_and_owner_checked(runtime):
    runs, state, request, _, _ = runtime
    owner = str(request.state.user.id)
    parent = await runs.create_thread(thread_id="parent-conversation")
    child = await runs.create_thread(thread_id="child-agent", parent_thread_id=parent, metadata={"deerflow_parent_thread_id": "forged"})
    stored = await state.thread_store.get(child, user_id=owner)
    assert stored["metadata"]["deerflow_parent_thread_id"] == parent
    # Metadata alone can never create the link.
    loose = await runs.create_thread(thread_id="loose-thread", metadata={"deerflow_parent_thread_id": parent})
    assert "deerflow_parent_thread_id" not in (await state.thread_store.get(loose, user_id=owner))["metadata"]
    await state.thread_store.create("someone-elses", user_id="other")
    with pytest.raises(AgentRunError) as hidden:
        await runs.create_thread(thread_id="child-2", parent_thread_id="someone-elses")
    assert hidden.value.status_code == 404


@pytest.mark.asyncio
async def test_parent_spend_overview_rolls_up_linked_children(monkeypatch):
    from app.gateway.routers import thread_runs

    children = [{"thread_id": "child-a"}, {"thread_id": "child-b"}]

    class Threads:
        async def search(self, *, metadata, limit, offset, user_id):
            assert metadata == {"deerflow_parent_thread_id": "parent"}
            return children[offset : offset + limit]

    class RunStore:
        async def aggregate_tokens_by_thread(self, thread_id, *, include_active, user_id):
            return {
                "total_runs": 1,
                "total_tokens": 300,
                "by_run": [{"run_id": f"{thread_id}-r", "by_model": {"m": {"input_tokens": 200, "output_tokens": 100}}}],
            }

    async def current_user(request):
        return "alice"

    monkeypatch.setattr(thread_runs, "get_current_user", current_user)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(thread_store=Threads())))
    price = SimpleNamespace(promo=lambda: None)
    monkeypatch.setattr(thread_runs, "resolve_run_pricing", lambda pricing, snapshot, currency, logger: pricing)
    monkeypatch.setattr(thread_runs, "lookup_pricing", lambda pricing, model: price)
    monkeypatch.setattr(thread_runs, "token_cost", lambda i, o, p, c: 0.5)
    usage = await thread_runs._delegated_usage(request, RunStore(), "parent", {"m": price}, "USD", include_active=False, user_id="alice")
    assert usage.threads == 2 and usage.runs == 2 and usage.tokens == 600
    assert usage.cost == 1.0 and usage.promo_cost is None

    children.clear()
    assert await thread_runs._delegated_usage(request, RunStore(), "parent", {}, "USD", include_active=False, user_id="alice") is None


# --- Workspace copy and merge ---------------------------------------------------


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    paths = Paths(base_dir=tmp_path)
    monkeypatch.setattr(workspaces, "get_paths", lambda: paths)
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))

    def root(thread_id):
        directory = Path(paths.sandbox_user_data_dir(thread_id, user_id="alice"))
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    return root


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@posix_only
def test_copy_takes_workspace_and_uploads_but_never_follows_links(mounted, tmp_path):
    parent = mounted("parent")
    write(parent / "workspace/src/app.py", "print(1)\n")
    write(parent / "uploads/brief.md", "brief")
    write(parent / "outputs/report.md", "not copied")
    write(tmp_path / "secret.txt", "outside")
    os.symlink(tmp_path / "secret.txt", parent / "workspace/link.txt")
    os.symlink(tmp_path, parent / "workspace/escape")

    files = workspaces.copy_workspace("alice", "parent", "child")
    assert set(files) == {"workspace/src/app.py", "uploads/brief.md"}
    child = mounted("child")
    assert (child / "workspace/src/app.py").read_text() == "print(1)\n"
    assert not (child / "workspace/link.txt").exists() and not (child / "workspace/escape").exists()
    assert not (child / "outputs/report.md").exists()


@posix_only
def test_merge_applies_only_unchanged_paths_and_never_deletes(mounted):
    parent = mounted("parent")
    for name in ("a", "b", "d"):
        write(parent / f"workspace/{name}.txt", f"{name} original")
    write(parent / "uploads/u.txt", "upload")
    base = workspaces.copy_workspace("alice", "parent", "child")
    child = mounted("child")
    write(child / "workspace/a.txt", "a edited by child")  # parent unchanged: applied
    write(child / "workspace/c.txt", "c new")  # new path: applied
    (child / "workspace/b.txt").unlink()  # deletion: reported, never applied
    write(child / "workspace/d.txt", "d edited by child")
    write(parent / "workspace/d.txt", "d edited meanwhile")  # conflict: untouched
    write(child / "uploads/u.txt", "upload edited")  # uploads are never written back
    write(child / "outputs/report.md", "report")  # outputs merge as new files

    applied, conflicts, skipped = workspaces.merge_workspace("alice", "child", "parent", base)
    assert applied == ["outputs/report.md", "workspace/a.txt", "workspace/c.txt"]
    assert conflicts == ["workspace/d.txt"] and skipped == ["workspace/b.txt"]
    assert (parent / "workspace/a.txt").read_text() == "a edited by child"
    assert (parent / "workspace/b.txt").read_text() == "b original"
    assert (parent / "workspace/d.txt").read_text() == "d edited meanwhile"
    assert (parent / "uploads/u.txt").read_text() == "upload"
    # Running the same merge again changes nothing: everything already matches.
    assert workspaces.merge_workspace("alice", "child", "parent", base)[0] == []


@posix_only
def test_merge_refuses_a_forged_base(mounted):
    mounted("parent")
    mounted("child")
    for base in ({"../escape": "0" * 64}, {"workspace/a.txt": "short"}, {"/etc/passwd": "0" * 64}):
        with pytest.raises(AgentRunError) as refused:
            workspaces.merge_workspace("alice", "child", "parent", base)
        assert refused.value.status_code == 422


@posix_only
def test_copy_is_bounded(mounted, monkeypatch):
    parent = mounted("parent")
    for index in range(4):
        write(parent / f"workspace/{index}.txt", "x")
    monkeypatch.setattr(workspaces, "MAX_FILES", 3)
    with pytest.raises(AgentRunError) as refused:
        workspaces.copy_workspace("alice", "parent", "child")
    assert refused.value.status_code == 422


def test_a_synced_sandbox_fails_closed(monkeypatch):
    monkeypatch.setattr("deerflow.sandbox.sandbox_provider.get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=False))
    with pytest.raises(AgentRunError) as refused:
        workspaces.copy_workspace("alice", "parent", "child")
    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_agent_runs_checks_both_threads_and_the_merge_base(runtime, mounted):
    runs, state, _, _, _ = runtime
    await state.thread_store.create("someone-elses", user_id="other")
    mine = await runs.create_thread(thread_id="mine")
    with pytest.raises(AgentRunError) as hidden:
        await runs.copy_workspace(source_thread_id="someone-elses", thread_id=mine)
    assert hidden.value.status_code == 404
    with pytest.raises(AgentRunError) as mismatched:
        await runs.merge_workspace(thread_id=mine, into_thread_id="other-thread", base=WorkspaceSnapshot(source_thread_id="not-the-target", files={}))
    assert mismatched.value.status_code == 422
