"""The design brief reaches design runs only.

The host forwards only removed tools and appended system text from a
``MODEL_LOGICAL`` middleware, so the cases that matter run through its
isolation wrapper when the host is installed (backend/.venv); the bare calls
cover the middleware's own logic on a checkout without it.
"""

from types import SimpleNamespace

import pytest
from deerflow_extension_api import AgentScope, Placement
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import SystemMessage

from deerflow_extension_cad_design.middleware import Contributor, DesignMode
from deerflow_extension_cad_design.notes import DESIGN_BRIEF, NO_CONTAINER
from deerflow_extension_cad_design.store import Store

DESIGN = "a" * 32
OTHER_TOOL = {"type": "function", "function": {"name": "web_search", "description": "", "parameters": {}}}
BASH = {"type": "function", "function": {"name": "bash", "description": "", "parameters": {}}}


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "d.sqlite")
    store.create_design("alice", DESIGN, "One", "thread-1")
    return store


def request(context, tools=(OTHER_TOOL, BASH)):
    return ModelRequest(model=None, messages=[], system_message=SystemMessage(content="BASE", id="sys"), tools=list(tools), state={}, runtime=SimpleNamespace(context=context))


def flagged(thread="thread-1", design=DESIGN):
    return {"thread_id": thread, "plugin_options": {"cad-design": {"design_id": design}}}


def run(middleware, req):
    seen = []
    middleware.wrap_model_call(req, lambda r: seen.append(r) or "ok")
    return seen[0]


async def arun(middleware, req):
    seen = []

    async def handler(r):
        seen.append(r)
        return "ok"

    await middleware.awrap_model_call(req, handler)
    return seen[0]


def wrapped(store):
    """DesignMode as the host injects it."""
    injection = pytest.importorskip("deerflow.extensions.injection")
    (placed,) = Contributor(store).contribute_middlewares(None, SimpleNamespace(scope=AgentScope.LEAD))
    diagnostics = []
    return injection.isolate(placed, "cad-design", diagnostics.append), diagnostics


ORDINARY = [
    {},
    {"thread_id": "thread-1"},
    # A design flag the run's own thread does not back: a forged or stale option.
    flagged(thread="thread-2"),
    flagged(design="b" * 32),
    {"thread_id": "thread-1", "plugin_options": {"cad-design": {"design_id": "../x"}}},
    {"thread_id": "thread-1", "plugin_options": {"cad-design": "a" * 32}},
]


@pytest.mark.parametrize("context", ORDINARY)
async def test_without_a_design_run_nothing_changes(store, context):
    middleware = DesignMode(store)
    for sent in (run(middleware, request(context)), await arun(middleware, request(context))):
        assert sent.tools == [OTHER_TOOL, BASH]
        assert sent.system_message.content == "BASE"


@pytest.mark.parametrize("context", ORDINARY)
def test_through_the_host_wrapper_nothing_changes_outside_a_design_run(store, context):
    middleware, diagnostics = wrapped(store)
    original = request(context)
    sent = run(middleware, original)
    assert sent.tools == original.tools and sent.system_message.content == "BASE"
    assert not diagnostics


def test_no_flag_never_touches_the_store(tmp_path):
    store = Store(tmp_path / "never.sqlite")
    run(DesignMode(store), request({"thread_id": "t"}))
    assert not store.exists()


async def test_a_design_run_gets_the_brief_and_keeps_its_tools(store):
    for sent in (run(DesignMode(store), request(flagged())), await arun(DesignMode(store), request(flagged()))):
        assert sent.tools == [OTHER_TOOL, BASH]
        assert sent.system_message.content == "BASE\n\n" + DESIGN_BRIEF
        assert sent.system_message.id == "sys"


def test_through_the_host_wrapper_the_brief_reaches_the_model(store):
    middleware, diagnostics = wrapped(store)
    sent = run(middleware, request(flagged()))
    assert sent.system_message.content == "BASE\n\n" + DESIGN_BRIEF and sent.tools == [OTHER_TOOL, BASH]
    sent = run(middleware, request(flagged(), tools=(OTHER_TOOL,)))
    assert sent.system_message.content == "BASE\n\n" + DESIGN_BRIEF + "\n\n" + NO_CONTAINER
    assert not diagnostics


async def test_without_bash_the_model_is_told_to_send_the_user_to_the_setup(store):
    sent = await arun(DesignMode(store), request(flagged(), tools=(OTHER_TOOL,)))
    assert sent.tools == [OTHER_TOOL]
    assert sent.system_message.content.endswith(NO_CONTAINER)
    for command in ("make sandbox-cad-image", "make sandbox-enable MODE=container IMAGE=cad", "restart the Gateway"):
        assert command in NO_CONTAINER
    # A tool object (not a schema dict) named bash counts too.
    sent = await arun(DesignMode(store), request(flagged(), tools=(SimpleNamespace(name="bash"),)))
    assert NO_CONTAINER not in sent.system_message.content


def test_the_brief_names_the_fixed_paths_and_stays_short():
    for text in ("/mnt/user-data/outputs/design", "/mnt/user-data/workspace/design/model.scad", "--print-layout", "/mnt/skills/public/cad-modeling/SKILL.md", "report.json"):
        assert text in DESIGN_BRIEF, text
    # The size of the brief it replaced; backend/tests/test_context_fit_critical.py measures the whole request.
    assert len(DESIGN_BRIEF) + len(NO_CONTAINER) <= 1100


def test_a_trashed_design_gets_no_brief(store):
    store.delete("alice", DESIGN)
    assert run(DesignMode(store), request(flagged())).system_message.content == "BASE"


def test_the_contributor_is_lead_only(store):
    placed = Contributor(store).contribute_middlewares(None, SimpleNamespace(scope=AgentScope.LEAD))
    assert len(placed) == 1 and placed[0].placement == Placement.MODEL_LOGICAL
    assert placed[0].scope == AgentScope.LEAD and isinstance(placed[0].middleware, DesignMode)
    # The brief is the lead's: a delegated subagent works from the task the lead writes it.
    assert Contributor(store).contribute_middlewares(None, SimpleNamespace(scope=AgentScope.SUBAGENT)) == ()
