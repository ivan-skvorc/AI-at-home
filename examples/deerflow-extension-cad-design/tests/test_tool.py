from types import SimpleNamespace

from deerflow_extension_cad_design.store import Store
from deerflow_extension_cad_design.tool import DESCRIPTION, NEXT, make_handler


def tool_context(user="alice", thread="thread-1", options=None, run_id="run-1"):
    return SimpleNamespace(principal=SimpleNamespace(user_id=user), thread_id=thread, run_options=options or {}, run_id=run_id)


def make(tmp_path):
    store = Store(tmp_path / "d.sqlite")
    store.create_design("alice", "a" * 32, "One", "thread-1")
    return store, make_handler(store, 1000)


async def test_refused_without_the_design_flag(tmp_path):
    store, handler = make(tmp_path)
    answer = await handler({"code": "cube(1);"}, tool_context())
    assert answer["saved"] is False
    assert store.versions("alice", "a" * 32) == []


async def test_refused_for_another_users_design_or_thread(tmp_path):
    store, handler = make(tmp_path)
    flag = {"design_id": "a" * 32, "phase": "draft"}
    assert (await handler({"code": "cube(1);"}, tool_context(user="bob", options=flag)))["saved"] is False
    assert (await handler({"code": "cube(1);"}, tool_context(thread="thread-2", options=flag)))["saved"] is False
    assert (await handler({"code": "cube(1);"}, tool_context(options={**flag, "phase": "finalize"})))["saved"] is False
    assert (await handler({"code": "x" * 2000}, tool_context(options=flag)))["saved"] is False
    assert store.versions("alice", "a" * 32) == []


async def test_a_draft_becomes_the_head_with_its_parameters(tmp_path):
    store, handler = make(tmp_path)
    flag = {"design_id": "a" * 32, "phase": "draft"}
    first = await handler({"code": "w = 4; // [1:10]\ncube(w);", "note": "a cube"}, tool_context(options=flag))
    assert first == {"version_id": first["version_id"], "seq": 1, "next": NEXT}
    second = await handler({"code": "w = 5;\ncube(w);"}, tool_context(options={**flag, "phase": "repair"}, run_id="run-2"))
    versions = store.versions("alice", "a" * 32)
    assert [(v["seq"], v["source"], v["params"], v["run_id"]) for v in versions] == [(1, "model", {"w": 4}, "run-1"), (2, "repair", {"w": 5}, "run-2")]
    assert versions[1]["parent_id"] == first["version_id"]
    assert store.get_design("alice", "a" * 32)["head_version_id"] == second["version_id"]


def test_the_description_is_short():
    # The host's short form keeps ~280 characters; the critical check measures tokens.
    assert len(DESCRIPTION) <= 330
