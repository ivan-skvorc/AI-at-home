"""Manual "Auto rename" from the chat header (fork feature, FORK.md §38).

Four properties, each silent when broken:

* an Ultra turn's subagent transcript lives in ``ToolMessage`` results, and a
  title written from those describes the models' deliberation instead of the
  answer the user read;
* the answer for a turn is the *last* AI message carrying text — the earlier
  ones are tool-call scaffolding with empty content;
* the model name arrives from a browser and picks what spends money, so an
  unconfigured one is **refused**, not silently swapped for another model;
* the call is billed to the conversation, or the chat header understates the
  thread by exactly what the user chose to spend on renaming it.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.gateway.routers import threads
from deerflow.config.title_config import TitleConfig
from deerflow.runtime import aux_usage
from deerflow.utils import oneshot_llm
from deerflow.utils.title_transcript import (
    DEFAULT_EXCHANGE_LIMIT,
    extract_visible_exchanges,
    render_exchanges,
)


def _config(*, model_name: str | None = "title-model", models: list[str] | None = ("title-model", "big-model"), enabled: bool = True) -> SimpleNamespace:
    """A minimal config-shaped stub.

    Deliberately not ``AppConfig.from_file()``: ``config.yaml`` is gitignored
    and absent on CI, so a test that resolves ambient config passes locally and
    fails there.
    """
    return SimpleNamespace(
        title=TitleConfig(model_name=model_name, enabled=enabled),
        models=None if models is None else [SimpleNamespace(name=name) for name in models],
    )


def _snapshot(messages: list) -> SimpleNamespace:
    return SimpleNamespace(
        config={"configurable": {"checkpoint_id": "cp-1"}},
        values={"messages": messages},
    )


def _install_route_stubs(monkeypatch, *, messages: list, config, response_content: str = "Fixing The Flaky Test"):
    accessor = SimpleNamespace(aget=AsyncMock(return_value=_snapshot(messages)))
    monkeypatch.setattr(
        threads,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(accessor, {"configurable": {"thread_id": "t-1"}})),
    )
    monkeypatch.setattr(threads, "get_app_config", lambda: config)

    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content=response_content, response_metadata={}, usage_metadata={"input_tokens": 90, "output_tokens": 5, "total_tokens": 95}))
    monkeypatch.setattr(oneshot_llm, "create_chat_model", MagicMock(return_value=fake_model))

    recorded: list = []
    monkeypatch.setattr(threads, "arecord_aux_usage_metadata", AsyncMock(side_effect=lambda *a, **kw: recorded.append((a, kw))))
    return fake_model, recorded


def _call(body: threads.ThreadTitleSuggestRequest):
    return asyncio.run(threads.suggest_thread_title.__wrapped__("t-1", body, request=None))


# ---------------------------------------------------------------------------
# What the user saw, and nothing else
# ---------------------------------------------------------------------------


class TestOnlyTheVisibleConversationIsTitled:
    def test_an_ultra_turns_subagent_transcript_never_reaches_the_prompt(self):
        """The whole point of the ``ToolMessage`` filter.

        A delegating turn stores every panelist's deliberation in the ``task``
        tool result. Feeding that to the title model is not merely wasteful —
        it is *longer* than the answer, so it dominates the prompt and the
        thread ends up named after the debate.
        """
        subagent_chatter = "Panelist A: I propose we... Panelist B: I disagree because... " * 40
        messages = [
            HumanMessage(content="Compare Rust and Go for this service"),
            AIMessage(content="", tool_calls=[{"name": "task", "args": {}, "id": "c1"}]),
            ToolMessage(content=subagent_chatter, tool_call_id="c1"),
            AIMessage(content="Go, for the smaller team."),
        ]

        exchanges = extract_visible_exchanges(messages)

        assert len(exchanges) == 1
        assert exchanges[0].assistant_text == "Go, for the smaller team."
        assert "Panelist" not in render_exchanges(exchanges)

        # And with the answer removed — a panel the user cancelled mid-run, then
        # renamed — the tool result is the last thing in the turn. Nothing may
        # promote it to "the answer": the exchange is simply unanswered. This is
        # the assert that fails if the ToolMessage filter is ever relaxed;
        # keeping only the case above passes either way, because the final AI
        # message overwrites whatever came before it.
        cancelled = extract_visible_exchanges(messages[:-1])

        assert cancelled[0].assistant_text == ""
        assert "Panelist" not in render_exchanges(cancelled)

    def test_the_answer_is_the_last_ai_message_with_text_not_the_scaffolding(self):
        messages = [
            HumanMessage(content="Read config.yaml"),
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "c1"}]),
            ToolMessage(content="title:\n  enabled: true", tool_call_id="c1"),
            AIMessage(content="Automatic titles are enabled."),
        ]

        assert extract_visible_exchanges(messages)[0].assistant_text == "Automatic titles are enabled."

    def test_messages_the_ui_hides_are_not_prompts_or_answers(self):
        """``hide_from_ui`` and the named control messages are invisible on screen.

        A dynamic-context reminder is a ``HumanMessage`` carrying the date and
        the memory block. Counting it as a prompt shifts every exchange by one
        and the title describes bookkeeping.
        """
        messages = [
            HumanMessage(content="<reminder>today is...</reminder>", additional_kwargs={"hide_from_ui": True}),
            HumanMessage(content="Why is the build slow?"),
            AIMessage(content="internal note", additional_kwargs={"hide_from_ui": True}),
            AIMessage(content="conversation so far", name="summary"),
            AIMessage(content="Because the cache misses."),
        ]

        exchanges = extract_visible_exchanges(messages)

        assert len(exchanges) == 1
        assert exchanges[0].user_text == "Why is the build slow?"
        assert exchanges[0].assistant_text == "Because the cache misses."

    def test_reasoning_blocks_are_stripped_from_the_answer(self):
        messages = [HumanMessage(content="hi"), AIMessage(content="<think>hmm</think>Hello there.")]

        assert extract_visible_exchanges(messages)[0].assistant_text == "Hello there."

    def test_only_the_first_two_exchanges_are_described(self):
        messages: list = []
        for index in range(5):
            messages.append(HumanMessage(content=f"prompt {index}"))
            messages.append(AIMessage(content=f"answer {index}"))

        exchanges = extract_visible_exchanges(messages)

        assert DEFAULT_EXCHANGE_LIMIT == 2
        assert [e.user_text for e in exchanges] == ["prompt 0", "prompt 1"]

    def test_an_unanswered_first_prompt_is_still_nameable(self):
        """A cancelled or in-flight run leaves a prompt with no answer."""
        exchanges = extract_visible_exchanges([HumanMessage(content="Draft the release notes")])

        assert len(exchanges) == 1
        assert exchanges[0].assistant_text == ""
        assert "(no answer yet)" in render_exchanges(exchanges)

    def test_the_users_own_words_win_over_the_model_facing_rewrite(self):
        """Input middleware replaces user text with transport wrappers.

        Titling from the rewritten content names the conversation after
        ``<uploaded_files>`` scaffolding rather than the question.
        """
        messages = [
            HumanMessage(
                content="<uploaded_files>report.pdf</uploaded_files>\nSummarize",
                additional_kwargs={"original_user_content": "Summarize this report"},
            ),
            AIMessage(content="It is about Q3."),
        ]

        assert extract_visible_exchanges(messages)[0].user_text == "Summarize this report"


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


class TestTheEndpoint:
    def test_the_picked_model_writes_the_title(self, monkeypatch):
        config = _config()
        fake_model, _ = _install_route_stubs(
            monkeypatch,
            messages=[HumanMessage(content="Why is the build slow?"), AIMessage(content="Cache misses.")],
            config=config,
        )

        result = _call(threads.ThreadTitleSuggestRequest(model_name="big-model"))

        assert result.title == "Fixing The Flaky Test"
        assert result.exchange_count == 1
        assert oneshot_llm.create_chat_model.call_args.kwargs["name"] == "big-model"
        assert fake_model.ainvoke.await_args.kwargs["config"]["run_name"] == "title_suggest"

    def test_an_unconfigured_model_is_refused_rather_than_quietly_swapped(self, monkeypatch):
        """The one place this diverges from the automatic rename on purpose.

        ``apply_auto_title_preference`` *drops* an unknown name because the run
        must still finish. Here the user pressed a button naming a model; going
        ahead on a different one spends their money on a choice they did not
        make, so it is a 400.
        """
        _install_route_stubs(monkeypatch, messages=[HumanMessage(content="hi"), AIMessage(content="hello")], config=_config())

        with pytest.raises(HTTPException) as excinfo:
            _call(threads.ThreadTitleSuggestRequest(model_name="model-the-operator-never-configured"))

        assert excinfo.value.status_code == 400
        assert oneshot_llm.create_chat_model.called is False

    def test_no_model_picked_falls_back_to_the_operators_title_model(self, monkeypatch):
        _install_route_stubs(monkeypatch, messages=[HumanMessage(content="hi"), AIMessage(content="hello")], config=_config(model_name="title-model"))

        _call(threads.ThreadTitleSuggestRequest())

        assert oneshot_llm.create_chat_model.call_args.kwargs["name"] == "title-model"

    def test_the_rename_is_billed_to_the_conversation(self, monkeypatch):
        """An uncounted sink makes the header cheaper than the thread was."""
        _, recorded = _install_route_stubs(monkeypatch, messages=[HumanMessage(content="hi"), AIMessage(content="hello")], config=_config())

        _call(threads.ThreadTitleSuggestRequest())

        assert len(recorded) == 1
        args, kwargs = recorded[0]
        assert args == ("t-1", aux_usage.AUX_CATEGORY_TITLE)
        assert kwargs["usage"]["total_tokens"] == 95

    def test_the_operators_master_switch_covers_this_button_too(self, monkeypatch):
        """``title.enabled: false`` is how an operator stops paying for names.

        Honouring it only on the automatic path leaves a button that bills them
        for exactly the thing they turned off — and nothing else in the suite
        notices, because the button still works.
        """
        _install_route_stubs(monkeypatch, messages=[HumanMessage(content="hi"), AIMessage(content="hello")], config=_config(enabled=False))

        with pytest.raises(HTTPException) as excinfo:
            _call(threads.ThreadTitleSuggestRequest())

        assert excinfo.value.status_code == 404
        assert oneshot_llm.create_chat_model.called is False

    def test_the_echoed_model_name_is_length_bounded(self):
        """The name comes back in the 400, so a client must not size its own error."""
        with pytest.raises(Exception):
            threads.ThreadTitleSuggestRequest(model_name="x" * 201)

        assert threads.ThreadTitleSuggestRequest(model_name="x" * 200).model_name is not None

    def test_a_conversation_with_nothing_in_it_is_refused_before_the_model_call(self, monkeypatch):
        _install_route_stubs(monkeypatch, messages=[], config=_config())

        with pytest.raises(HTTPException) as excinfo:
            _call(threads.ThreadTitleSuggestRequest())

        assert excinfo.value.status_code == 409
        assert oneshot_llm.create_chat_model.called is False

    def test_an_attachment_only_opening_turn_does_not_block_the_rename(self, monkeypatch):
        """A first message that is only a file has no text of its own.

        Refusing on the *first* exchange alone would make the button useless on
        a conversation whose second message asks the actual question.
        """
        _install_route_stubs(
            monkeypatch,
            messages=[
                HumanMessage(content=""),
                AIMessage(content="I have read report.pdf."),
                HumanMessage(content="What does it conclude?"),
                AIMessage(content="Revenue grew 4%."),
            ],
            config=_config(),
        )

        result = _call(threads.ThreadTitleSuggestRequest())

        assert result.exchange_count == 2
        assert oneshot_llm.create_chat_model.called is True

    def test_the_endpoint_only_reads_and_never_writes_the_title(self, monkeypatch):
        """The rename itself stays on ``POST /{id}/state``.

        Writing here would put the "409 while a run is in flight" rule in two
        places, and this one would not hold ``reserve_checkpoint_write``.
        """
        _install_route_stubs(monkeypatch, messages=[HumanMessage(content="hi"), AIMessage(content="hello")], config=_config())
        mutation = AsyncMock()
        monkeypatch.setattr(threads, "build_thread_checkpoint_state_mutation_accessor", mutation)

        _call(threads.ThreadTitleSuggestRequest())

        mutation.assert_not_awaited()


class TestTitleCleaning:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('"Fixing the flaky test"', "Fixing the flaky test"),
            ("```\nFixing the flaky test\n```", "Fixing the flaky test"),
            ("<think>the user wants...</think>Fixing the flaky test", "Fixing the flaky test"),
            ("Fixing the flaky test\n\nI chose this because it is short.", "Fixing the flaky test"),
        ],
    )
    def test_a_chatty_model_still_yields_a_bare_title(self, raw, expected):
        assert threads._clean_suggested_title(raw, max_chars=60) == expected

    def test_the_title_honours_max_chars(self):
        assert len(threads._clean_suggested_title("x" * 200, max_chars=60)) == 60
