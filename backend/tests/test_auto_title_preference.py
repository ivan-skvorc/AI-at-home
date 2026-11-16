"""Per-user automatic conversation renaming (fork feature, FORK.md §33).

Five independent properties, each silent when broken:

* the rename runs from ``after_agent`` (the end of the turn), not
  ``after_model`` — a move back to ``after_model`` still produces titles, so
  nothing else in the suite goes red;
* the per-run preference is a one-way opt-out layered on ``config.yaml ->
  title``, and an unconfigured model name is dropped rather than dialled;
* both context keys reach the run config, and the lead agent builds its
  middleware chain from the resolved preference;
* the preference is stored per user on the server and applied at run
  admission, so a run that does not come from the browser holding the switch
  (an IM channel, another device or origin, an extension's child thread) still
  honors it — an opt-out is ANDed in, never overridden by the request;
* the worker's end-of-run fallback title respects an opted-out run, with or
  without an ``app_config`` on the run context.
"""

import logging
from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.title_middleware import TitleMiddleware
from deerflow.config import paths as paths_module
from deerflow.config import user_ui_state
from deerflow.config.title_config import (
    AUTO_TITLE_ENABLED_CONTEXT_KEY,
    AUTO_TITLE_MODEL_CONTEXT_KEY,
    AUTO_TITLE_NO_MODEL,
    TitleConfig,
    apply_auto_title_preference,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def isolated_ui_state(tmp_path, monkeypatch):
    """A private ``DEER_FLOW_HOME`` so the stored preference never reads a
    developer's own ``ui_state.json``, with the real reader re-bound at run
    admission (the suite-wide conftest fixture stubs it out)."""
    from app.gateway import services

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(paths_module, "_paths", None)
    monkeypatch.setattr(services, "get_auto_title_preference", user_ui_state.get_auto_title_preference)
    user_ui_state.reset_cache_for_tests()
    yield
    monkeypatch.setattr(paths_module, "_paths", None)
    user_ui_state.reset_cache_for_tests()


def _app_config(*, enabled: bool = True, model_name: str | None = None, models: list[str] | None = ("cheap-model", "big-model")) -> SimpleNamespace:
    """A minimal config-shaped stub.

    Deliberately not ``AppConfig.from_file()``: ``config.yaml`` is gitignored and
    absent on CI, so a test that resolves ambient config passes locally and
    fails there.
    """

    class _Stub(SimpleNamespace):
        def model_copy(self, *, update: dict):
            return _Stub(**{**self.__dict__, **update})

    return _Stub(
        title=TitleConfig(enabled=enabled, model_name=model_name),
        models=None if models is None else [SimpleNamespace(name=name) for name in models],
    )


class TestRenameRunsAfterTheResponse:
    """The hook the title is written from decides *when* the sidebar changes.

    A manual rename is refused with 409 while a run is in flight, so the
    automatic one is deliberately scheduled for the moment the user gets their
    own rename back — the end of the turn.
    """

    def test_the_title_is_written_from_after_agent_not_after_model(self):
        # These are the exact predicates langchain's agent factory uses to
        # decide whether a middleware gets an `after_agent` exit node or an
        # `after_model` node inside the loop, so asserting on them pins the
        # graph position rather than the method names.
        assert TitleMiddleware.after_agent is not AgentMiddleware.after_agent
        assert TitleMiddleware.aafter_agent is not AgentMiddleware.aafter_agent

        assert TitleMiddleware.after_model is AgentMiddleware.after_model
        assert TitleMiddleware.aafter_model is AgentMiddleware.aafter_model

    def test_the_prompt_describes_the_final_answer_not_the_tool_scaffolding(self):
        """A tool-using turn opens with an AI message that has no text at all.

        Titling from the *first* assistant message — correct while the hook ran
        after the first model call — now yields an empty ``assistant_msg`` and a
        title written from the request alone. The last assistant message with
        text is the answer the user actually saw.
        """
        middleware = TitleMiddleware(title_config=TitleConfig(model_name="cheap-model"))
        state = {
            "messages": [
                HumanMessage(content="How much disk is left?"),
                AIMessage(content="", tool_calls=[{"id": "1", "name": "bash", "args": {"command": "df -h"}}]),
                AIMessage(content="You have 12 GB free on /."),
            ]
        }

        prompt, _user_msg = middleware._build_title_prompt(state)

        assert "You have 12 GB free on /." in prompt

    def test_a_reasoning_only_answer_still_reaches_the_prompt(self):
        """``<think>`` blocks are stripped, and a message that is *only* thinking
        must not shadow the real answer that came after it."""
        middleware = TitleMiddleware(title_config=TitleConfig(model_name="cheap-model"))
        state = {
            "messages": [
                HumanMessage(content="Explain quicksort"),
                AIMessage(content="<think>planning</think>"),
                AIMessage(content="Quicksort partitions around a pivot."),
            ]
        }

        prompt, _user_msg = middleware._build_title_prompt(state)

        assert "Quicksort partitions around a pivot." in prompt
        assert "planning" not in prompt


class TestPerRunPreference:
    def test_no_preference_returns_the_operator_config_unchanged(self):
        app_config = _app_config(enabled=True, model_name="big-model")

        assert apply_auto_title_preference(app_config, {}) is app_config

    def test_switching_renaming_off_disables_it_for_this_run(self):
        app_config = _app_config(enabled=True)

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_ENABLED_CONTEXT_KEY: False})

        assert resolved.title.enabled is False
        # The caller's config is shared across runs; overriding must copy.
        assert app_config.title.enabled is True

    def test_a_client_cannot_switch_renaming_on_when_the_operator_disabled_it(self):
        """One-way opt-out, exactly like the memory preference. Collapsing this
        into "the client decides" hands any browser a way to re-enable a
        feature the operator turned off in config.yaml."""
        app_config = _app_config(enabled=False)

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_ENABLED_CONTEXT_KEY: True})

        assert resolved.title.enabled is False

    def test_a_configured_model_is_honored(self):
        app_config = _app_config(model_name=None)

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_MODEL_CONTEXT_KEY: "cheap-model"})

        assert resolved.title.model_name == "cheap-model"

    def test_an_unconfigured_model_is_dropped_rather_than_dialled(self):
        """The name arrives from the browser. Honoring it unchecked lets a
        client name any string as the run's title model."""
        app_config = _app_config(model_name="big-model")

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_MODEL_CONTEXT_KEY: "not-in-catalog"})

        assert resolved.title.model_name == "big-model"

    def test_the_empty_string_means_rename_without_a_model_call(self):
        """Distinct from the key being absent: absent follows the operator's
        model, "" clears it so the middleware takes its local fallback path."""
        app_config = _app_config(model_name="big-model")

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_MODEL_CONTEXT_KEY: AUTO_TITLE_NO_MODEL})

        assert resolved.title.model_name is None
        assert resolved.title.enabled is True

    def test_a_config_without_a_model_catalog_accepts_the_name(self):
        """Config-shaped stubs used by embedders predate ``models``; "no catalog"
        must not read as "an empty catalog", which would reject every name."""
        app_config = _app_config(models=None)

        resolved = apply_auto_title_preference(app_config, {AUTO_TITLE_MODEL_CONTEXT_KEY: "some-model"})

        assert resolved.title.model_name == "some-model"

    def test_both_overrides_apply_together(self):
        app_config = _app_config(enabled=True, model_name=None)

        resolved = apply_auto_title_preference(
            app_config,
            {AUTO_TITLE_ENABLED_CONTEXT_KEY: False, AUTO_TITLE_MODEL_CONTEXT_KEY: "cheap-model"},
        )

        assert resolved.title.enabled is False
        assert resolved.title.model_name == "cheap-model"

    @pytest.mark.parametrize("preference", [{AUTO_TITLE_ENABLED_CONTEXT_KEY: False}, {AUTO_TITLE_MODEL_CONTEXT_KEY: ""}])
    def test_a_disabled_run_writes_no_title(self, preference):
        """End to end through the middleware: the resolved config is what
        ``_should_generate_title`` reads."""
        app_config = _app_config(enabled=True)
        resolved = apply_auto_title_preference(app_config, preference)
        middleware = TitleMiddleware(title_config=resolved.title)
        state = {"messages": [HumanMessage(content="Hello there"), AIMessage(content="Hi!")]}

        result = middleware._generate_title_result(state)

        if preference.get(AUTO_TITLE_ENABLED_CONTEXT_KEY) is False:
            assert result is None
        else:
            assert result == {"title": "Hello there"}


class TestPreferenceReachesTheRun:
    def test_both_keys_are_forwarded_from_the_request_context(self):
        """Without this the toggle is a browser-local no-op: the Gateway drops
        every context key that is not on the allowlist."""
        from app.gateway.services import merge_run_context_overrides

        config: dict = {}
        merge_run_context_overrides(config, {AUTO_TITLE_ENABLED_CONTEXT_KEY: False, AUTO_TITLE_MODEL_CONTEXT_KEY: "cheap-model"})

        for bucket in ("configurable", "context"):
            assert config[bucket][AUTO_TITLE_ENABLED_CONTEXT_KEY] is False
            assert config[bucket][AUTO_TITLE_MODEL_CONTEXT_KEY] == "cheap-model"

    @pytest.mark.parametrize(("preference", "expected"), [(False, False), (True, True), (None, True)], ids=["opted-out", "opted-in", "absent"])
    def test_the_lead_agent_chain_is_built_with_renaming_off(self, monkeypatch, preference, expected):
        """The Gateway-merged context must reach the config TitleMiddleware is
        built from. Removing ``apply_auto_title_preference`` from lead-agent
        assembly keeps every other test green and renames every conversation
        again; this is the test that notices."""
        import deerflow.tools as tools_module
        from app.gateway.services import merge_run_context_overrides
        from deerflow.agents.lead_agent import agent as lead_agent_module
        from deerflow.config.app_config import AppConfig
        from deerflow.config.model_config import ModelConfig
        from deerflow.config.sandbox_config import SandboxConfig

        app_config = AppConfig(
            models=[
                ModelConfig(
                    name="safe-model",
                    display_name="safe-model",
                    description=None,
                    use="langchain_openai:ChatOpenAI",
                    model="safe-model",
                    supports_thinking=False,
                    supports_vision=False,
                )
            ],
            sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        )
        assert app_config.title.enabled is True
        built_with: list[TitleConfig] = []

        def _build_middlewares(*args, **kwargs):
            built_with.append(kwargs["app_config"].title)
            return []

        monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
        monkeypatch.setattr(lead_agent_module, "build_middlewares", _build_middlewares)
        monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "system prompt")
        monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
        monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
        monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
        monkeypatch.setattr(tools_module, "get_available_tools", lambda **kwargs: [])

        context = {} if preference is None else {AUTO_TITLE_ENABLED_CONTEXT_KEY: preference}
        config: dict = {"configurable": {}}
        merge_run_context_overrides(config, {"mode": "pro", **context})
        lead_agent_module._make_lead_agent(config, app_config=app_config)

        assert [title.enabled for title in built_with] == [expected]
        # The operator's config is shared by every run; an opt-out must copy it.
        assert app_config.title.enabled is True


# ---------------------------------------------------------------------------
# The stored preference, applied at run admission
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_app_config():
    """Keep admission independent from a developer-local ``config.yaml``."""
    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config

    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
    yield
    reset_app_config()


def _session_user(user_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, system_role="user", oauth_provider=None, oauth_id=None)


def _admission_request(*, user=None, auth_source=None, headers=None) -> SimpleNamespace:
    """The smallest request ``start_run`` admits: in-memory stores, no worker."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    store = InMemoryStore()
    state = SimpleNamespace(auth_source=auth_source)
    if user is not None:
        state.user = user
    return SimpleNamespace(
        headers=dict(headers or {}),
        state=state,
        app=SimpleNamespace(
            state=SimpleNamespace(
                stream_bridge=SimpleNamespace(),
                run_manager=RunManager(store=MemoryRunStore()),
                checkpointer=InMemorySaver(),
                store=store,
                run_event_store=MemoryRunEventStore(),
                run_events_config=None,
                thread_store=MemoryThreadMetaStore(store),
            )
        ),
    )


async def _admitted_config(request, context: dict) -> dict:
    """Run the real ``start_run`` and return the config the worker received."""
    from unittest.mock import patch

    from app.gateway.run_models import RunCreateRequest
    from app.gateway.services import start_run

    captured: dict = {}

    async def fake_run_agent(*args, **kwargs):
        captured["config"] = kwargs["config"]

    body = RunCreateRequest(input={"messages": [{"role": "user", "content": "hello"}]}, context=context)
    with (
        patch("app.gateway.services.resolve_agent_factory", return_value=object()),
        patch("app.gateway.services.run_agent", side_effect=fake_run_agent),
    ):
        record = await start_run(body, "thread-auto-title", request)
        await record.task
    return captured["config"]


def _title_keys(config: dict) -> dict[str, dict]:
    """The two auto-title keys as each run-config section carries them."""
    keys = (AUTO_TITLE_ENABLED_CONTEXT_KEY, AUTO_TITLE_MODEL_CONTEXT_KEY)
    return {section: {key: config[section][key] for key in keys if key in config[section]} for section in ("configurable", "context")}


@pytest.mark.usefixtures("isolated_ui_state", "stub_app_config")
class TestTheStoredPreferenceAppliesAtAdmission:
    """The switch used to live only in one browser origin's ``localStorage``.

    Every run that did not come from that browser — an IM channel, the PWA,
    another device, ``localhost`` vs the tailnet name, an extension's child
    thread — sent no key and fell back to ``config.yaml``, so conversations kept
    being renamed with the switch off. ``start_run`` is the one door all of them
    pass through, so the stored preference is applied there.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("requested", [True, None], ids=["explicit-true", "absent"])
    async def test_a_stored_opt_out_wins_over_the_request(self, requested):
        """AND, not "the request decides": a browser whose own cache still says
        on must not re-enable renaming the user switched off elsewhere."""
        user_ui_state.set_auto_title_preference("alice", {"enabled": False})
        context = {} if requested is None else {AUTO_TITLE_ENABLED_CONTEXT_KEY: requested}

        config = await _admitted_config(_admission_request(user=_session_user("alice")), context)

        for section in _title_keys(config).values():
            assert section[AUTO_TITLE_ENABLED_CONTEXT_KEY] is False

    @pytest.mark.anyio
    async def test_an_explicit_opt_out_in_the_request_is_kept(self):
        user_ui_state.set_auto_title_preference("alice", {"enabled": True})

        config = await _admitted_config(_admission_request(user=_session_user("alice")), {AUTO_TITLE_ENABLED_CONTEXT_KEY: False})

        for section in _title_keys(config).values():
            assert section[AUTO_TITLE_ENABLED_CONTEXT_KEY] is False

    @pytest.mark.anyio
    async def test_a_never_set_preference_leaves_the_run_on_the_operator_config(self):
        config = await _admitted_config(_admission_request(user=_session_user("alice")), {})

        assert _title_keys(config) == {"configurable": {}, "context": {}}

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("requested", "expected"),
        [({}, "cheap-model"), ({AUTO_TITLE_MODEL_CONTEXT_KEY: ""}, ""), ({AUTO_TITLE_MODEL_CONTEXT_KEY: "big-model"}, "big-model")],
        ids=["absent-filled", "explicit-no-model-kept", "explicit-name-kept"],
    )
    async def test_the_stored_model_fills_only_an_absent_key(self, requested, expected):
        user_ui_state.set_auto_title_preference("alice", {"enabled": True, "model_name": "cheap-model"})

        config = await _admitted_config(_admission_request(user=_session_user("alice")), requested)

        for section in _title_keys(config).values():
            assert section[AUTO_TITLE_MODEL_CONTEXT_KEY] == expected

    @pytest.mark.anyio
    async def test_the_no_model_choice_is_stored_and_applied_as_the_empty_string(self):
        """``""`` (rename without a model call) differs from an absent key
        (follow ``title.model_name``); a falsy check would merge the two."""
        user_ui_state.set_auto_title_preference("alice", {"enabled": True, "model_name": AUTO_TITLE_NO_MODEL})

        config = await _admitted_config(_admission_request(user=_session_user("alice")), {})

        for section in _title_keys(config).values():
            assert section[AUTO_TITLE_MODEL_CONTEXT_KEY] == AUTO_TITLE_NO_MODEL

    @pytest.mark.anyio
    async def test_an_im_channel_run_reads_the_connection_owners_preference(self):
        """The channel worker authenticates as the internal user and names the
        owner in a trusted header; the preference is the owner's, not the
        synthetic internal user's."""
        from app.gateway.auth_disabled import AUTH_SOURCE_INTERNAL
        from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user

        user_ui_state.set_auto_title_preference("alice", {"enabled": False})
        request = _admission_request(
            user=get_internal_user(),
            auth_source=AUTH_SOURCE_INTERNAL,
            headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: "alice"},
        )

        config = await _admitted_config(request, {"user_id": "alice"})

        for section in _title_keys(config).values():
            assert section[AUTO_TITLE_ENABLED_CONTEXT_KEY] is False

    @pytest.mark.anyio
    async def test_another_users_preference_does_not_apply(self):
        user_ui_state.set_auto_title_preference("bob", {"enabled": False, "model_name": "cheap-model"})

        config = await _admitted_config(_admission_request(user=_session_user("alice")), {})

        assert _title_keys(config) == {"configurable": {}, "context": {}}

    @pytest.mark.anyio
    async def test_an_unreadable_store_does_not_fail_the_run(self, monkeypatch, caplog):
        """A UI preference is not a reason to refuse a run: log and keep the
        request's own context."""
        from app.gateway import services

        calls: list[str] = []

        def _broken_store(user_id):
            calls.append(user_id)
            raise OSError("disk unavailable")

        monkeypatch.setattr(services, "get_auto_title_preference", _broken_store)

        with caplog.at_level(logging.WARNING, logger="app.gateway.services"):
            config = await _admitted_config(_admission_request(user=_session_user("alice")), {AUTO_TITLE_ENABLED_CONTEXT_KEY: True})

        assert calls == ["alice"]  # the injected failure fired
        assert _title_keys(config) == {"configurable": {AUTO_TITLE_ENABLED_CONTEXT_KEY: True}, "context": {AUTO_TITLE_ENABLED_CONTEXT_KEY: True}}
        assert any("auto-title preference" in record.getMessage() for record in caplog.records)


async def _run_untitled_first_turn(*, app_config=None, config: dict) -> list[str]:
    """Drive the real worker over a first turn that ended with no title.

    Returns the titles the worker's end-of-run fallback wrote to the checkpoint.
    """
    from unittest.mock import AsyncMock

    from langgraph.checkpoint.base import empty_checkpoint

    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.schemas import RunStatus
    from deerflow.runtime.runs.worker import RunContext, run_agent

    first_turn = [
        HumanMessage(id="u1", content="Rename me from this"),
        AIMessage(id="a1", content="", tool_calls=[{"id": "c1", "name": "ask_clarification", "args": {}}]),
    ]

    class _ClarificationCheckpointer:
        """No title in the checkpoint, exactly as the bypassed hook leaves it."""

        def __init__(self) -> None:
            self.written_titles: list[str] = []

        async def aget_tuple(self, config):
            del config
            checkpoint = empty_checkpoint()
            checkpoint["id"] = "ckpt-1"
            checkpoint["channel_values"] = {"messages": list(first_turn)}
            checkpoint["channel_versions"] = {"messages": 1}
            return SimpleNamespace(
                config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "ckpt-1"}},
                checkpoint=checkpoint,
                metadata={"source": "loop", "step": 1},
                pending_writes=[],
            )

        async def aput(self, config, checkpoint, metadata, new_versions):
            del config, metadata, new_versions
            title = (checkpoint.get("channel_values") or {}).get("title")
            if title:
                self.written_titles.append(title)
            return {"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": checkpoint["id"]}}

        def get_next_version(self, current, _channel):
            return (current or 0) + 1

    class _DummyAgent:
        async def aget_state(self, _config):
            return SimpleNamespace(
                values={"messages": list(first_turn)},
                config={"configurable": {"thread_id": "thread-1", "checkpoint_ns": "", "checkpoint_id": "ckpt-1"}},
                parent_config=None,
                metadata={},
                next=(),
                tasks=(),
                created_at=None,
            )

        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            del graph_input, config, stream_mode, subgraphs
            yield {"messages": list(first_turn)}

    checkpointer = _ClarificationCheckpointer()
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())

    await run_agent(
        bridge,
        run_manager,
        record,
        ctx=RunContext(checkpointer=checkpointer, app_config=app_config),
        agent_factory=lambda *, config: _DummyAgent(),
        graph_input={},
        config=config,
    )

    fetched = await run_manager.get(record.run_id)
    assert fetched is not None and fetched.status == RunStatus.success
    return checkpointer.written_titles


class TestTheClarificationExitIsCovered:
    """``ask_clarification`` ends the run with ``Command(goto=END)``.

    LangGraph honors that directly, so the ``after_agent`` node never runs and
    the middleware never writes a title. Because ``_should_generate_title``
    requires *exactly one* user message, missing the first turn means the
    conversation is never titled at all — the second turn has two. The worker's
    fallback write therefore runs on every terminal status, not only
    ``interrupted``.
    """

    @pytest.mark.anyio
    async def test_a_successful_first_turn_with_no_title_still_gets_one(self):
        assert await _run_untitled_first_turn(config={}) == ["Rename me from this"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("app_config", ["enabled", None], ids=["with-app-config", "without-app-config"])
    async def test_an_opted_out_first_turn_gets_no_fallback_title(self, app_config):
        """The fallback is the second place a title is written, so an opt-out
        that only reached the middleware would still rename the conversation.
        Without an ``app_config`` on the run context the worker used to fall
        back to the global title config and drop the opt-out entirely."""
        resolved = _app_config(enabled=True) if app_config == "enabled" else None

        written = await _run_untitled_first_turn(app_config=resolved, config={"context": {AUTO_TITLE_ENABLED_CONTEXT_KEY: False}})

        assert written == []
