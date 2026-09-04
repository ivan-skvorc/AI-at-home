"""Per-user automatic conversation renaming (fork feature, FORK.md §33).

Three independent properties, each silent when broken:

* the rename runs from ``after_agent`` (the end of the turn), not
  ``after_model`` — a move back to ``after_model`` still produces titles, so
  nothing else in the suite goes red;
* the per-run preference is a one-way opt-out layered on ``config.yaml ->
  title``, and an unconfigured model name is dropped rather than dialled;
* both context keys reach the run config, which is the only way the preference
  travels from the browser to the middleware.
"""

from types import SimpleNamespace

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.title_middleware import TitleMiddleware
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
        from unittest.mock import AsyncMock

        from langchain_core.messages import AIMessage
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
            ctx=RunContext(checkpointer=checkpointer),
            agent_factory=lambda *, config: _DummyAgent(),
            graph_input={},
            config={},
        )

        fetched = await run_manager.get(record.run_id)
        assert fetched is not None and fetched.status == RunStatus.success
        assert checkpointer.written_titles == ["Rename me from this"]
