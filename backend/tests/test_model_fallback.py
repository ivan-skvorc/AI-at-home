"""Tests for model fallback chains (fork feature, roadmap item 6).

FORK.md §3 notes that models flagged `supports_tools: false` stay selectable and
"tool-using subagents will simply fail at runtime". That is one instance of a
general problem: running local models means absorbing local-model failure modes
— daemon down, OOM, context overflow, no tool support — and today the user
absorbs them by hand. This is the reliability cost of the fork's central bet.

The distinction that matters most here is between a failure (fall back) and a
*decision* (do not): a user interrupt, a spend cap, and a guardrail refusal are
things the system meant to do, and retrying them on another model would both
defeat them and spend money doing it.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.models import fallback as fallback_module
from deerflow.models.fallback import FallbackChatModel, resolve_fallback_chain, should_fall_back


class _Boom(Exception):
    """A provider error carrying an optional HTTP status, like the SDK ones do."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class _FailingModel(FakeMessagesListChatModel):
    """A model that always raises; used as the primary in the chain."""

    error: Exception = None  # type: ignore[assignment]
    calls: list = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        raise self.error

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        raise self.error


def failing(error: Exception) -> _FailingModel:
    model = _FailingModel(responses=[AIMessage(content="unused")])
    object.__setattr__(model, "error", error)
    object.__setattr__(model, "calls", [])
    return model


def answering(text: str, model_name: str = "backup") -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=[AIMessage(content=text, response_metadata={"model_name": model_name})])


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestShouldFallBack:
    @pytest.mark.parametrize(
        "error",
        [
            ConnectionError("connection refused"),
            _Boom("Connection error: [Errno 111] Connection refused"),
            _Boom("upstream connect error or disconnect/reset before headers"),
            TimeoutError("read timeout"),
        ],
    )
    def test_connection_failures_fall_back(self, error):
        # The Ollama-daemon-is-down case, which is the whole point.
        assert should_fall_back(error) is True

    @pytest.mark.parametrize(
        "message",
        [
            "This model's maximum context length is 8192 tokens",
            "context_length_exceeded",
            "input length exceeds the context window",
            "Requested tokens exceed context window of 4096",
        ],
    )
    def test_context_length_rejections_fall_back(self, message):
        assert should_fall_back(_Boom(message, status_code=400)) is True

    @pytest.mark.parametrize(
        "message",
        [
            "registry.ollama.ai/library/llama3.2 does not support tools",
            "Tool calling is not supported by this model",
            "tools is not supported",
        ],
    )
    def test_unsupported_tool_calls_fall_back(self, message):
        assert should_fall_back(_Boom(message, status_code=400)) is True

    @pytest.mark.parametrize("status", [500, 502, 503, 504, 529])
    def test_provider_5xx_falls_back(self, status):
        assert should_fall_back(_Boom("upstream error", status_code=status)) is True

    def test_a_plain_4xx_does_not_fall_back(self):
        # A 400 that is not a context/tool problem is a request bug; retrying it
        # on another model produces the same error and hides the cause.
        assert should_fall_back(_Boom("invalid 'messages[3]': missing content", status_code=400)) is False

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures_do_not_fall_back(self, status):
        # A bad key is a config error the operator must see, not a degradation.
        assert should_fall_back(_Boom("invalid api key", status_code=status)) is False

    def test_a_user_interrupt_does_not_fall_back(self):
        assert should_fall_back(asyncio.CancelledError()) is False
        assert should_fall_back(KeyboardInterrupt()) is False

    def test_a_budget_stop_does_not_fall_back(self):
        class SpendBudgetExceeded(Exception):
            pass

        # An intentional stop. Falling back would defeat the cap *and* spend
        # money on the retry — the exact opposite of what the cap is for.
        assert should_fall_back(SpendBudgetExceeded("daily limit reached")) is False

    def test_a_guardrail_refusal_does_not_fall_back(self):
        class GuardrailBlocked(Exception):
            pass

        assert should_fall_back(GuardrailBlocked("blocked by policy")) is False

    def test_an_unrecognized_error_does_not_fall_back(self):
        # Defaulting to "retry on another model" would make every bug cost twice.
        assert should_fall_back(ValueError("something else entirely")) is False


# ---------------------------------------------------------------------------
# Chain resolution
# ---------------------------------------------------------------------------


class _Cfg:
    def __init__(self, name, fallback=None):
        self.name = name
        self.fallback = fallback


class TestResolveFallbackChain:
    def test_per_model_chain_wins(self):
        chain = resolve_fallback_chain("local", {"local": _Cfg("local", ["cloud-a", "cloud-b"])}, global_chain=["other"])
        assert chain == ["cloud-a", "cloud-b"]

    def test_global_chain_applies_when_the_model_declares_none(self):
        chain = resolve_fallback_chain("local", {"local": _Cfg("local")}, global_chain=["cloud-a"])
        assert chain == ["cloud-a"]

    def test_the_model_is_removed_from_its_own_chain(self):
        # Otherwise a global chain retries the model that just failed.
        chain = resolve_fallback_chain("cloud-a", {"cloud-a": _Cfg("cloud-a")}, global_chain=["cloud-a", "cloud-b"])
        assert chain == ["cloud-b"]

    def test_duplicates_are_collapsed(self):
        chain = resolve_fallback_chain("local", {"local": _Cfg("local", ["a", "a", "b"])}, global_chain=[])
        assert chain == ["a", "b"]

    def test_unknown_names_are_dropped_rather_than_raising(self):
        chain = resolve_fallback_chain("local", {"local": _Cfg("local", ["ghost", "a"]), "a": _Cfg("a")}, global_chain=[], known={"local", "a"})
        assert chain == ["a"]

    def test_the_chain_is_bounded(self):
        long_chain = [f"m{i}" for i in range(20)]
        chain = resolve_fallback_chain("local", {"local": _Cfg("local", long_chain)}, global_chain=[])
        assert len(chain) <= fallback_module.MAX_CHAIN

    def test_no_chain_configured_is_empty(self):
        assert resolve_fallback_chain("local", {"local": _Cfg("local")}, global_chain=[]) == []


# ---------------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------------


class TestFallbackChatModel:
    def test_the_primary_serves_when_it_works(self):
        model = FallbackChatModel(primary=answering("from primary", "primary"), fallbacks=[answering("from backup")], model_names=["primary", "backup"])
        result = model.invoke([HumanMessage(content="hi")])
        assert result.content == "from primary"

    def test_a_connection_failure_degrades_to_the_next_model(self):
        model = FallbackChatModel(primary=failing(ConnectionError("connection refused")), fallbacks=[answering("from backup")], model_names=["local", "backup"])
        result = model.invoke([HumanMessage(content="hi")])
        assert result.content == "from backup"

    def test_tokens_are_attributed_to_the_model_that_actually_ran(self):
        # Load-bearing for the spend cap and the spend report: RunJournal keys
        # token_usage_by_model on response_metadata.model_name, so the wrapper
        # must not rewrite it to the primary's name.
        model = FallbackChatModel(primary=failing(ConnectionError("down")), fallbacks=[answering("ok", "cloud-haiku")], model_names=["local", "cloud-haiku"])
        result = model.invoke([HumanMessage(content="hi")])
        assert result.response_metadata["model_name"] == "cloud-haiku"

    def test_an_intentional_stop_is_re_raised_without_trying_the_chain(self):
        backup = answering("should never be reached")
        model = FallbackChatModel(primary=failing(asyncio.CancelledError()), fallbacks=[backup], model_names=["local", "backup"])
        with pytest.raises(asyncio.CancelledError):
            model.invoke([HumanMessage(content="hi")])

    def test_the_last_error_propagates_when_the_whole_chain_fails(self):
        model = FallbackChatModel(
            primary=failing(ConnectionError("primary down")),
            fallbacks=[failing(ConnectionError("backup down"))],
            model_names=["local", "backup"],
        )
        with pytest.raises(ConnectionError, match="backup down"):
            model.invoke([HumanMessage(content="hi")])

    def test_it_never_retries_the_same_model_twice(self):
        primary = failing(ConnectionError("down"))
        model = FallbackChatModel(primary=primary, fallbacks=[answering("ok")], model_names=["local", "backup"])
        model.invoke([HumanMessage(content="hi")])
        assert len(primary.calls) == 1

    def test_the_serving_model_is_logged(self, caplog):
        import logging

        caplog.set_level(logging.WARNING)
        model = FallbackChatModel(primary=failing(ConnectionError("daemon down")), fallbacks=[answering("ok")], model_names=["local", "backup"])
        model.invoke([HumanMessage(content="hi")])
        text = caplog.text
        assert "local" in text and "backup" in text

    @pytest.mark.asyncio
    async def test_the_async_path_falls_back_too(self):
        model = FallbackChatModel(primary=failing(ConnectionError("down")), fallbacks=[answering("from backup")], model_names=["local", "backup"])
        result = await model.ainvoke([HumanMessage(content="hi")])
        assert result.content == "from backup"

    @pytest.mark.asyncio
    async def test_async_intentional_stops_are_re_raised(self):
        backup = answering("nope")
        model = FallbackChatModel(primary=failing(asyncio.CancelledError()), fallbacks=[backup], model_names=["local", "backup"])
        # Asserted against _agenerate rather than ainvoke: LangChain's own
        # agenerate filters gathered results with isinstance(res, Exception),
        # which misses BaseException-derived CancelledError and crashes inside
        # langchain_core. The wrapper's contract is what this test owns.
        with pytest.raises(asyncio.CancelledError):
            await model._agenerate([HumanMessage(content="hi")])

    def test_bind_tools_binds_every_model_in_the_chain(self):
        class _Bindable(FakeMessagesListChatModel):
            bound: object = None

            def bind_tools(self, tools, **kwargs):
                clone = _Bindable(responses=self.responses)
                object.__setattr__(clone, "bound", tools)
                return clone

        primary, backup = _Bindable(responses=[AIMessage(content="a")]), _Bindable(responses=[AIMessage(content="b")])
        model = FallbackChatModel(primary=primary, fallbacks=[backup], model_names=["p", "b"])

        bound = model.bind_tools([{"name": "search"}])
        assert isinstance(bound, FallbackChatModel)
        assert bound.primary.bound == [{"name": "search"}]
        assert bound.fallbacks[0].bound == [{"name": "search"}]

    def test_a_model_without_bind_tools_does_not_break_the_chain(self):
        # An unsupported-tools local model is exactly why the chain exists; the
        # wrapper must not fail to build just because one member lacks the API.
        class _NoTools(_FailingModel):
            def bind_tools(self, tools, **kwargs):
                raise NotImplementedError("this model does not support tools")

        primary = _NoTools(responses=[AIMessage(content="x")])
        object.__setattr__(primary, "error", _Boom("registry.ollama.ai/library/llama3.2 does not support tools", status_code=400))
        object.__setattr__(primary, "calls", [])
        model = FallbackChatModel(primary=primary, fallbacks=[answering("ok")], model_names=["local", "backup"])
        bound = model.bind_tools([{"name": "search"}])
        assert isinstance(bound, FallbackChatModel)
        assert bound.invoke([HumanMessage(content="hi")]).content == "ok"

    def test_llm_type_names_the_chain(self):
        model = FallbackChatModel(primary=answering("x"), fallbacks=[answering("y")], model_names=["a", "b"])
        assert "fallback" in model._llm_type


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactoryWiring:
    def test_a_model_without_a_chain_is_returned_unwrapped(self, monkeypatch):
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": "solo", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "solo", "responses": []},
                ],
            }
        )
        model = factory.create_chat_model("solo", app_config=config, attach_tracing=False)
        assert not isinstance(model, FallbackChatModel)

    def test_a_configured_chain_produces_a_wrapper(self):
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": "local", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "local", "responses": [], "fallback": ["cloud"]},
                    {"name": "cloud", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "cloud", "responses": []},
                ],
            }
        )
        model = factory.create_chat_model("local", app_config=config, attach_tracing=False)
        assert isinstance(model, FallbackChatModel)
        assert model.model_names == ["local", "cloud"]

    def test_fallback_is_not_forwarded_to_the_provider_client(self):
        # ModelConfig is extra="allow", so an unexcluded key would be passed
        # into the provider constructor and then into the request payload.
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": "local", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "local", "responses": [], "fallback": ["cloud"]},
                    {"name": "cloud", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "cloud", "responses": []},
                ],
            }
        )
        model = factory.create_chat_model("local", app_config=config, attach_tracing=False)
        assert not hasattr(model.primary, "fallback")

    def test_the_global_chain_applies_to_a_model_that_declares_none(self):
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "model_fallback": {"enabled": True, "chain": ["cloud"]},
                "models": [
                    {"name": "local", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "local", "responses": []},
                    {"name": "cloud", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "cloud", "responses": []},
                ],
            }
        )
        model = factory.create_chat_model("local", app_config=config, attach_tracing=False)
        assert isinstance(model, FallbackChatModel)

    def test_the_global_chain_is_off_by_default(self):
        from deerflow.config.app_config import AppConfig

        config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [{"name": "a", "use": "x:Y", "model": "a"}]})
        assert config.model_fallback.enabled is False

    def test_a_fallback_model_is_built_without_its_own_chain(self):
        # The chain is flat by construction, which is what makes cycles
        # impossible rather than merely unlikely.
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": "a", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "a", "responses": [], "fallback": ["b"]},
                    {"name": "b", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "b", "responses": [], "fallback": ["a"]},
                ],
            }
        )
        model = factory.create_chat_model("a", app_config=config, attach_tracing=False)
        assert isinstance(model, FallbackChatModel)
        assert not isinstance(model.fallbacks[0], FallbackChatModel)

    def test_a_broken_fallback_model_does_not_break_the_primary(self):
        # A chain that cannot be built (missing key, bad class) must degrade to
        # "no fallback", never to "no model at all".
        from deerflow.config.app_config import AppConfig
        from deerflow.models import factory

        config = AppConfig.model_validate(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {"name": "local", "use": "langchain_core.language_models.fake_chat_models:FakeMessagesListChatModel", "model": "local", "responses": [], "fallback": ["broken"]},
                    {"name": "broken", "use": "deerflow.does.not:Exist", "model": "broken"},
                ],
            }
        )
        model = factory.create_chat_model("local", app_config=config, attach_tracing=False)
        assert not isinstance(model, FallbackChatModel)
