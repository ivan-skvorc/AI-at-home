"""Tests that every auxiliary LLM path records its usage against its thread.

These pin the wiring from each non-graph LLM call into the per-thread aux
registry behind the chat header's separate counters, and that each sink lands in
the durable store rather than only in process memory.

The registry covers four sinks: **memory** extraction, follow-up
**suggestions**, the composer's **input_polish** draft rewrite, and the
per-turn **goal** completion check. The rule they exist to enforce is that
anything a conversation spends is priced against that conversation — an
unrecorded sink is not free, it is invisible, and the header simply reports a
number lower than the money that left the account.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest
from langchain_core.messages import AIMessage

from app.gateway.routers.suggestions import _record_suggestions_usage
from deerflow.agents.memory.manager import _host_default_extraction_callback
from deerflow.runtime import aux_usage
from deerflow.utils.oneshot_llm import OneshotResult


@pytest.fixture(autouse=True)
def _durable_registry(tmp_path, monkeypatch):
    """Exercise the wiring against a real (per-test) durable store."""
    monkeypatch.setenv("DEER_FLOW_AUX_USAGE_DB", str(tmp_path / "aux_usage.sqlite3"))
    aux_usage.reset_aux_usage()
    yield
    aux_usage.reset_aux_usage()


def test_memory_extraction_callback_records_usage_with_cache_read():
    _host_default_extraction_callback(
        {
            "thread_id": "t-mem",
            "model_name": "mem-model",
            "success": True,
            "token_usage": {
                "input_tokens": 500,
                "output_tokens": 100,
                "total_tokens": 600,
                "input_token_details": {"cache_read": 200},
            },
        },
    )
    usage = aux_usage.get_thread_aux_usage("t-mem")
    assert usage["memory"]["mem-model"] == {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600, "cache_read_tokens": 200, "calls": 1}


def test_memory_extraction_callback_no_usage_records_nothing():
    _host_default_extraction_callback({"thread_id": "t-mem", "model_name": "mem-model", "facts_extracted": 3, "facts_passed_confidence": 2})
    assert aux_usage.get_thread_aux_usage("t-mem") == {}


def test_memory_extraction_callback_ignores_non_dict_payload():
    _host_default_extraction_callback(None)  # must not raise
    assert aux_usage.get_thread_aux_usage("t-mem") == {}


def test_suggestions_helper_records_usage():
    asyncio.run(
        _record_suggestions_usage(
            "t-sug",
            "sug-model",
            {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
        )
    )
    usage = aux_usage.get_thread_aux_usage("t-sug")
    assert usage["suggestions"]["sug-model"]["total_tokens"] == 52
    assert usage["suggestions"]["sug-model"]["calls"] == 1


def test_suggestions_helper_ignores_missing_usage():
    asyncio.run(_record_suggestions_usage("t-sug", "sug-model", None))
    assert aux_usage.get_thread_aux_usage("t-sug") == {}


def test_both_sinks_survive_a_gateway_restart():
    """The `Done when` for roadmap item 1, end to end through both writers."""
    _host_default_extraction_callback(
        {
            "thread_id": "t-restart",
            "model_name": "mem-model",
            "success": True,
            "token_usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600, "input_token_details": {"cache_read": 200}},
        },
    )
    asyncio.run(_record_suggestions_usage("t-restart", "sug-model", {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52}))
    before = aux_usage.get_thread_aux_usage("t-restart")

    # Restart: process-local cache and store handle dropped, SQLite file kept.
    aux_usage.reset_aux_usage_cache()

    assert aux_usage.get_thread_aux_usage("t-restart") == before
    assert before["memory"]["mem-model"]["cache_read_tokens"] == 200
    assert before["suggestions"]["sug-model"]["total_tokens"] == 52


# ---------------------------------------------------------------------------
# The two sinks that used to spend money with nothing counting it
# ---------------------------------------------------------------------------
#
# Both are per-thread LLM calls that never become a graph run, so their tokens
# never reach ``token_usage_by_model`` — exactly the shape memory and
# suggestions already had. Until they were wired in, the chat header reported a
# total *lower* than the conversation had actually cost, with nothing on screen
# to indicate the shortfall. Neutralize either ``arecord_aux_usage_metadata``
# call and the matching test below goes red while every other test stays green,
# which is the whole failure mode: silent under-counting.


def test_input_polish_records_usage_against_its_thread():
    """The composer's draft rewrite is billed to the conversation it happened in.

    ``input_polish.enabled`` defaults to **true**, so this is the one auxiliary
    sink a user pays for without having opted into anything.
    """
    from app.gateway.routers.input_polish import polish_input

    config = SimpleNamespace(input_polish=SimpleNamespace(enabled=True, max_chars=4000, model_name="polish-model"))
    request = SimpleNamespace(state=SimpleNamespace())
    body = SimpleNamespace(text="make this better", locale="en-US", thread_id="t-polish")

    async def fake_oneshot(**kwargs):
        assert kwargs["thread_id"] == "t-polish"
        return OneshotResult(
            text="Rewrite this draft clearly.",
            usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150, "input_token_details": {"cache_read": 40}},
            model_name="polish-model-20260115",
        )

    with mock.patch("app.gateway.routers.input_polish.run_oneshot_llm_with_usage", fake_oneshot):
        asyncio.run(polish_input.__wrapped__(body=body, request=request, config=config))

    usage = aux_usage.get_thread_aux_usage("t-polish")
    # Keyed on the *provider-reported* id, not the configured override, because
    # that is the id `lookup_pricing` resolves a price from.
    assert usage["input_polish"]["polish-model-20260115"] == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cache_read_tokens": 40,
        "calls": 1,
    }


def test_input_polish_without_a_thread_id_records_nothing():
    """A draft polished before the thread exists has no conversation to bill."""
    from app.gateway.routers.input_polish import polish_input

    config = SimpleNamespace(input_polish=SimpleNamespace(enabled=True, max_chars=4000, model_name=None))
    request = SimpleNamespace(state=SimpleNamespace())
    body = SimpleNamespace(text="draft", locale=None, thread_id=None)

    async def fake_oneshot(**kwargs):
        return OneshotResult(text="Draft.", usage={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, model_name="m")

    with mock.patch("app.gateway.routers.input_polish.run_oneshot_llm_with_usage", fake_oneshot):
        asyncio.run(polish_input.__wrapped__(body=body, request=request, config=config))

    assert aux_usage.get_thread_aux_usage("") == {}
    assert aux_usage.get_thread_aux_usage(None) == {}


def test_input_polish_still_answers_when_the_counter_is_broken():
    """Accounting is best-effort: the rewrite is already paid for at the provider."""
    from app.gateway.routers import input_polish as module

    config = SimpleNamespace(input_polish=SimpleNamespace(enabled=True, max_chars=4000, model_name=None))
    request = SimpleNamespace(state=SimpleNamespace())
    body = SimpleNamespace(text="draft", locale=None, thread_id="t-broken")

    async def fake_oneshot(**kwargs):
        return OneshotResult(text="Polished draft.", usage={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}, model_name="m")

    async def exploding(*args, **kwargs):
        raise RuntimeError("store down")

    with mock.patch.object(module, "run_oneshot_llm_with_usage", fake_oneshot), mock.patch.object(module, "arecord_aux_usage_metadata", exploding):
        result = asyncio.run(module.polish_input.__wrapped__(body=body, request=request, config=config))

    assert result.rewritten_text == "Polished draft."


def test_goal_evaluator_records_usage_against_its_thread():
    """The completion check runs once per turn while a goal is active.

    It fires *after* the graph run has finished, which is precisely why its
    tokens have no run to attach to — on a long-running goal (each hidden
    continuation triggers another evaluation) that is not a rounding error.
    """
    from deerflow.runtime.goal import evaluate_goal_completion

    response = SimpleNamespace(
        content='{"satisfied": true, "blocker": "none", "reason": "done", "evidence_summary": "ok"}',
        response_metadata={"model_name": "goal-model-20260115"},
        usage_metadata={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940, "input_token_details": {"cache_read": 700}},
    )
    model = SimpleNamespace(ainvoke=mock.AsyncMock(return_value=response))
    goal = {"objective": "ship the feature"}
    messages = [AIMessage(content="I shipped it.")]

    evaluation = asyncio.run(evaluate_goal_completion(goal, messages, model=model, thread_id="t-goal"))

    assert evaluation["satisfied"] is True
    usage = aux_usage.get_thread_aux_usage("t-goal")
    assert usage["goal"]["goal-model-20260115"] == {
        "input_tokens": 900,
        "output_tokens": 40,
        "total_tokens": 940,
        "cache_read_tokens": 700,
        "calls": 1,
    }


def test_goal_evaluator_collapses_a_stream_duplicated_model_id():
    """A doubled reported id prices at zero, so it is collapsed before recording.

    Same rule as every other reader of a provider-reported id
    (`deerflow.model_ids`): only an exact whole-string repetition.
    """
    from deerflow.runtime.goal import evaluate_goal_completion

    response = SimpleNamespace(
        content='{"satisfied": false, "blocker": "goal_not_met_yet", "reason": "more", "evidence_summary": ""}',
        response_metadata={"model_name": "goal-modelgoal-model"},
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    model = SimpleNamespace(ainvoke=mock.AsyncMock(return_value=response))

    asyncio.run(evaluate_goal_completion({"objective": "x"}, [AIMessage(content="partial")], model=model, thread_id="t-dup"))

    assert list(aux_usage.get_thread_aux_usage("t-dup")["goal"]) == ["goal-model"]


def test_every_chat_aux_sink_survives_a_gateway_restart():
    """All four per-conversation sinks, through one simulated restart.

    The registry's durability is what makes the header's figure survive closing
    the laptop; a sink that is recorded but not durable resets to zero on the
    next boot and the conversation looks cheaper than it was.
    """
    _host_default_extraction_callback(
        {"thread_id": "t-all", "model_name": "mem-model", "success": True, "token_usage": {"input_tokens": 500, "output_tokens": 100, "total_tokens": 600}},
    )
    asyncio.run(_record_suggestions_usage("t-all", "sug-model", {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52}))
    asyncio.run(
        aux_usage.arecord_aux_usage_metadata(
            "t-all",
            aux_usage.AUX_CATEGORY_INPUT_POLISH,
            model_name="polish-model",
            usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
        )
    )
    asyncio.run(
        aux_usage.arecord_aux_usage_metadata(
            "t-all",
            aux_usage.AUX_CATEGORY_GOAL,
            model_name="goal-model",
            usage={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940},
        )
    )
    before = aux_usage.get_thread_aux_usage("t-all")
    assert set(before) == set(aux_usage.CHAT_AUX_CATEGORIES)

    aux_usage.reset_aux_usage_cache()  # the "restart the Gateway" shape

    assert aux_usage.get_thread_aux_usage("t-all") == before


# ---------------------------------------------------------------------------
# The shared usage_metadata unpacking
# ---------------------------------------------------------------------------


def test_usage_metadata_kwargs_carries_the_nested_cache_read():
    """The nesting is the part a hand-written call site drops.

    A dropped ``cache_read`` bills a cached prompt at the full input rate, which
    over-states spend rather than under-stating it — wrong in the other
    direction, and just as silent.
    """
    assert aux_usage.usage_metadata_kwargs(
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "input_token_details": {"cache_read": 4}},
    ) == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "cache_read_tokens": 4}


@pytest.mark.parametrize("usage", [None, "not a dict", 42, []])
def test_usage_metadata_kwargs_declines_a_non_mapping(usage):
    """A provider that reported no usage means "nothing to record", not a crash."""
    assert aux_usage.usage_metadata_kwargs(usage) is None


def test_usage_metadata_kwargs_tolerates_a_missing_details_block():
    assert aux_usage.usage_metadata_kwargs({"input_tokens": 3, "output_tokens": 1})["cache_read_tokens"] == 0
