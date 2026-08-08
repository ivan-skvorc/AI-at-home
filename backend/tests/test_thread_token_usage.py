"""Tests for thread-level token usage and context-window usage."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway import context_usage
from app.gateway.pricing import build_pricing_map, lookup_pricing, token_cost
from app.gateway.routers import thread_runs
from deerflow.runtime import aux_usage
from deerflow.runtime.runs.store.memory import MemoryRunStore


def _aggregate_result() -> dict:
    return {
        "total_tokens": 150,
        "total_input_tokens": 90,
        "total_output_tokens": 60,
        "total_runs": 2,
        "by_model": {"unknown": {"tokens": 150, "runs": 2, "input_tokens": 90, "output_tokens": 60, "cache_read_tokens": 0, "cost": None}},
        "by_caller": {
            "lead_agent": 120,
            "subagent": 25,
            "middleware": 5,
        },
        "total_cost": None,
        "promo_total_cost": None,
        "currency": None,
        "unpriced_models": [],
        "aux": {},
    }


def _make_run_store(*, model_name: str | None = None) -> MagicMock:
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_aggregate_result())
    runs = [{"model_name": model_name}] if model_name else []
    run_store.list_by_thread = AsyncMock(return_value=runs)
    return run_store


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


def test_thread_token_usage_returns_stable_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    build_context_usage = AsyncMock(return_value=None)
    monkeypatch.setattr(thread_runs, "build_context_usage", build_context_usage)
    # No pricing configured → cost fields null, aux empty. Patch the pricing map
    # so the assertion does not depend on whatever config.yaml the test env has.
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", lambda: {})
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
        **_aggregate_result(),
        "context_usage": None,
    }
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=False)
    build_context_usage.assert_awaited_once()


def test_thread_token_usage_can_include_active_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    build_context_usage = AsyncMock(return_value=None)
    monkeypatch.setattr(thread_runs, "build_context_usage", build_context_usage)
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


def _priced_map():
    return build_pricing_map(
        [
            SimpleNamespace(name="lead", model="lead-model", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            SimpleNamespace(name="sub", model="sub-model", pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
        ],
    )


def _priced_anthropic_map():
    """The fork's direct-Anthropic prices, so the switching-conversation math
    matches real config ($5/25, $3/15, $1/5 per 1M tokens)."""
    return build_pricing_map(
        [
            SimpleNamespace(name="Claude Opus 4.8", model="claude-opus-4-8", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            SimpleNamespace(name="Claude Sonnet 4.6", model="claude-sonnet-4-6", pricing={"currency": "USD", "input_per_million": 3, "output_per_million": 15}),
            SimpleNamespace(name="Claude Haiku 4.5", model="claude-haiku-4-5", pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 5}),
        ],
    )


@pytest.mark.anyio
async def test_cost_tracks_model_switching_across_turns():
    """The 'as the conversation goes on' property: when the selected model changes
    each turn, the cumulative cost is the sum of every turn priced at the model
    that actually ran it — no turn's tokens are cross-attributed to another
    model's rate.

    Unlike ``test_thread_token_usage_computes_model_aware_cost_and_aux`` (which
    prices a *mocked* aggregate), this drives the real cross-run per-model store
    aggregation and feeds it through the same pricing helpers the endpoint uses,
    so it pins the whole store→price chain across a multi-turn thread.
    """
    store = MemoryRunStore()
    thread = "thread-model-switch"

    async def _turn(run_id: str, model_name: str, input_tokens: int, output_tokens: int) -> None:
        total = input_tokens + output_tokens
        await store.put(run_id, thread_id=thread, status="pending", model_name=model_name)
        await store.update_run_completion(
            run_id,
            status="success",
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            total_tokens=total,
            llm_call_count=1,
            lead_agent_tokens=total,
            subagent_tokens=0,
            middleware_tokens=0,
            token_usage_by_model={model_name: {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}},
            message_count=0,
        )

    # Turn 1 on Opus, turn 2 on Sonnet, turn 3 on Haiku.
    await _turn("t1", "claude-opus-4-8", 1_000_000, 200_000)
    await _turn("t2", "claude-sonnet-4-6", 2_000_000, 400_000)
    await _turn("t3", "claude-haiku-4-5", 3_000_000, 1_000_000)

    agg = await store.aggregate_tokens_by_thread(thread)
    pricing = _priced_anthropic_map()

    # Price exactly as the endpoint does: each per-model bucket at its own rate.
    per_model_cost: dict[str, float] = {}
    total_cost = 0.0
    for model, bucket in agg["by_model"].items():
        price = lookup_pricing(pricing, model)
        assert price is not None, f"no price resolved for {model}"
        cost = token_cost(bucket["input_tokens"], bucket["output_tokens"], price, bucket["cache_read_tokens"])
        per_model_cost[model] = cost
        total_cost += cost

    # Opus 1M@$5 + 0.2M@$25 = 10 ; Sonnet 2M@$3 + 0.4M@$15 = 12 ; Haiku 3M@$1 + 1M@$5 = 8.
    assert per_model_cost["claude-opus-4-8"] == pytest.approx(10.0)
    assert per_model_cost["claude-sonnet-4-6"] == pytest.approx(12.0)
    assert per_model_cost["claude-haiku-4-5"] == pytest.approx(8.0)
    # Cumulative conversation cost is the sum, each turn billed at its own model.
    assert total_cost == pytest.approx(30.0)
    # Each turn contributes exactly one run to its own bucket — no cross-attribution.
    assert {model: bucket["runs"] for model, bucket in agg["by_model"].items()} == {
        "claude-opus-4-8": 1,
        "claude-sonnet-4-6": 1,
        "claude-haiku-4-5": 1,
    }
    assert agg["total_runs"] == 3


def test_thread_token_usage_prices_provider_reported_model_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end regression for "the cost estimate always showed —".

    The store's per-model buckets are keyed by what the *provider* reported
    (``response_metadata.model_name``), not by the id in ``config.yaml``:
    LangChain records the API-resolved model, so Anthropic's undated alias comes
    back as a dated snapshot and OpenRouter appends a ``:variant`` tag. Every
    bucket therefore missed the pricing map and ``total_cost`` stayed ``None``
    while ``currency`` was set — exactly the "—" the header rendered.

    This drives the real endpoint over realistic reported ids across a
    model switch, so a regression in the id resolution fails here and not only
    in the pricing unit tests.
    """
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 8_600_000,
            "total_input_tokens": 6_000_000,
            "total_output_tokens": 2_600_000,
            "total_runs": 3,
            "by_model": {
                # Turn 1: direct Anthropic, alias resolved to a dated snapshot.
                "claude-opus-4-8-20260115": {"tokens": 1_200_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 200_000, "cache_read_tokens": 0},
                # Turn 2: the user switched models mid-conversation.
                "claude-sonnet-4-6-20260115": {"tokens": 2_400_000, "runs": 1, "input_tokens": 2_000_000, "output_tokens": 400_000, "cache_read_tokens": 0},
                # Turn 3: routed through OpenRouter with a variant tag.
                "anthropic/claude-haiku-4-5:nitro": {"tokens": 4_000_000, "runs": 1, "input_tokens": 3_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0},
            },
            "by_caller": {"lead_agent": 8_600_000, "subagent": 0, "middleware": 0},
        },
    )
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", _priced_anthropic_map)
    app = _make_app(run_store)

    with TestClient(app) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    assert data["currency"] == "USD"
    # Opus 1M@$5 + 0.2M@$25 = 10 ; Sonnet 2M@$3 + 0.4M@$15 = 12 ; Haiku 3M@$1 + 1M@$5 = 8.
    assert data["by_model"]["claude-opus-4-8-20260115"]["cost"] == pytest.approx(10.0)
    assert data["by_model"]["claude-sonnet-4-6-20260115"]["cost"] == pytest.approx(12.0)
    assert data["by_model"]["anthropic/claude-haiku-4-5:nitro"]["cost"] == pytest.approx(8.0)
    assert data["total_cost"] == pytest.approx(30.0)


def _agg_with_models(by_model: dict) -> dict:
    total_in = sum(b["input_tokens"] for b in by_model.values())
    total_out = sum(b["output_tokens"] for b in by_model.values())
    return {
        "total_tokens": total_in + total_out,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_runs": len(by_model),
        "by_model": by_model,
        "by_caller": {"lead_agent": total_in + total_out, "subagent": 0, "middleware": 0},
    }


@pytest.mark.parametrize(
    ("by_model", "expected_cost", "expected_unpriced"),
    [
        # Every model priced → no report, full total.
        (
            {"claude-opus-4-8": {"tokens": 0, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0}},
            5.0,
            [],
        ),
        # Nothing priced → the "—" case. The models are named so the operator
        # can tell a missing pricing block from a broken feature.
        (
            {"gpt-5.6-sol": {"tokens": 0, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0}},
            None,
            ["gpt-5.6-sol"],
        ),
        # Mixed → the total is real but understates the spend; say so.
        (
            {
                "claude-opus-4-8": {"tokens": 0, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0},
                "grok-4.5": {"tokens": 0, "runs": 1, "input_tokens": 500_000, "output_tokens": 0, "cache_read_tokens": 0},
            },
            5.0,
            ["grok-4.5"],
        ),
        # Zero-token buckets are not "unpriced" — nothing was spent on them.
        (
            {
                "claude-opus-4-8": {"tokens": 0, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 0},
                "idle-model": {"tokens": 0, "runs": 1, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0},
            },
            5.0,
            [],
        ),
    ],
    ids=["all-priced", "none-priced", "partially-priced", "zero-token-bucket-ignored"],
)
def test_thread_token_usage_reports_unpriced_models(monkeypatch, by_model, expected_cost, expected_unpriced):
    """An unexplained "—" is indistinguishable from a broken cost feature.

    The endpoint therefore names any model that burned tokens without a
    configured price, so the UI can point at the model that needs one.
    """
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_agg_with_models(by_model))
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", _priced_anthropic_map)

    with TestClient(_make_app(run_store)) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    assert data["unpriced_models"] == expected_unpriced
    if expected_cost is None:
        assert data["total_cost"] is None
    else:
        assert data["total_cost"] == pytest.approx(expected_cost)


def test_unpriced_models_empty_when_no_pricing_configured(monkeypatch):
    """With no pricing at all the cost UI is hidden, so the list stays quiet.

    Reporting every model as "unpriced" here would nag operators who simply
    never opted into cost tracking.
    """
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value=_agg_with_models(
            {"gpt-5.6-sol": {"tokens": 0, "runs": 1, "input_tokens": 1_000, "output_tokens": 500, "cache_read_tokens": 0}},
        ),
    )
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", dict)

    with TestClient(_make_app(run_store)) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    assert data["currency"] is None
    assert data["total_cost"] is None
    assert data["unpriced_models"] == []


def test_thread_token_usage_computes_model_aware_cost_and_aux():
    """Cost is priced per model (subagent on a cheaper model billed correctly),
    and memory/suggestions LLM calls surface as separate priced aux counters."""
    aux_usage.reset_aux_usage()
    # A memory call on an *unpriced* model → tokens shown, cost null.
    aux_usage.record_aux_usage("thread-cost", "memory", model_name="mem-model", input_tokens=1000, output_tokens=200)
    # A suggestions call on the priced sub-model.
    aux_usage.record_aux_usage("thread-cost", "suggestions", model_name="sub-model", input_tokens=500_000, output_tokens=100_000)

    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 5_000_000,
            "total_input_tokens": 3_000_000,
            "total_output_tokens": 2_000_000,
            "total_runs": 2,
            "by_model": {
                "lead-model": {"tokens": 2_000_000, "runs": 2, "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0},
                "sub-model": {"tokens": 3_000_000, "runs": 1, "input_tokens": 2_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0},
            },
            "by_caller": {"lead_agent": 2_000_000, "subagent": 3_000_000, "middleware": 0},
        },
    )
    app = _make_app(run_store)

    try:
        with (
            patch.object(thread_runs, "_thread_pricing_map", side_effect=_priced_map),
            patch.object(thread_runs, "build_context_usage", AsyncMock(return_value=None)),
            TestClient(app) as client,
        ):
            data = client.get("/api/threads/thread-cost/token-usage").json()
    finally:
        aux_usage.reset_aux_usage()

    assert data["currency"] == "USD"
    # lead: 5 + 25 = 30 ; sub: 2*1 + 1*4 = 6 ; run total = 36.
    assert data["total_cost"] == pytest.approx(36.0)
    assert data["by_model"]["lead-model"]["cost"] == pytest.approx(30.0)
    assert data["by_model"]["sub-model"]["cost"] == pytest.approx(6.0)

    # Aux is separate from total_cost.
    assert data["aux"]["memory"]["tokens"] == 1200
    assert data["aux"]["memory"]["cost"] is None  # unpriced memory model
    assert data["aux"]["suggestions"]["calls"] == 1
    # suggestions: 0.5M @ $1/M + 0.1M @ $4/M = 0.5 + 0.4 = 0.9
    assert data["aux"]["suggestions"]["cost"] == pytest.approx(0.9)


def test_thread_token_usage_cost_null_when_no_pricing():
    aux_usage.reset_aux_usage()
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 100,
            "total_input_tokens": 60,
            "total_output_tokens": 40,
            "total_runs": 1,
            "by_model": {"m": {"tokens": 100, "runs": 1, "input_tokens": 60, "output_tokens": 40, "cache_read_tokens": 0}},
            "by_caller": {"lead_agent": 100, "subagent": 0, "middleware": 0},
        },
    )
    app = _make_app(run_store)
    with (
        patch.object(thread_runs, "_thread_pricing_map", return_value={}),
        patch.object(thread_runs, "build_context_usage", AsyncMock(return_value=None)),
        TestClient(app) as client,
    ):
        data = client.get("/api/threads/thread-x/token-usage").json()
    assert data["total_cost"] is None
    assert data["currency"] is None
    assert data["by_model"]["m"]["cost"] is None


def test_thread_token_usage_serializes_context_percentage(monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _make_run_store()
    monkeypatch.setattr(
        thread_runs,
        "build_context_usage",
        AsyncMock(
            return_value={
                "token_count": 350,
                "max_context_tokens": 1000,
                "percentage": 35.0,
            }
        ),
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json()["context_usage"] == {
        "token_count": 350,
        "max_context_tokens": 1000,
        "percentage": 35.0,
    }


def test_build_context_usage_payload_computes_percentage() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=1000) == {
        "token_count": 350,
        "max_context_tokens": 1000,
        "percentage": 35.0,
    }


def test_build_context_usage_payload_handles_unknown_capacity() -> None:
    assert context_usage.build_context_usage_payload(token_count=350, max_context_tokens=None) == {
        "token_count": 350,
        "max_context_tokens": None,
        "percentage": None,
    }


@pytest.mark.asyncio
async def test_resolve_thread_model_prefers_latest_run() -> None:
    run_store = _make_run_store(model_name="thread-model")
    app_config = SimpleNamespace(models=[SimpleNamespace(name="fallback-model")])

    assert await context_usage._resolve_thread_model_name(run_store, "thread-1", app_config) == "thread-model"


@pytest.mark.asyncio
async def test_resolve_thread_model_falls_back_to_first_configured_model() -> None:
    run_store = _make_run_store()
    app_config = SimpleNamespace(models=[SimpleNamespace(name="fallback-model")])

    assert await context_usage._resolve_thread_model_name(run_store, "thread-1", app_config) == "fallback-model"


@pytest.mark.asyncio
async def test_build_context_usage_counts_materialized_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [SimpleNamespace(content="hello")]
    snapshot = SimpleNamespace(values={"messages": messages})
    accessor = SimpleNamespace(aget=AsyncMock(return_value=snapshot))
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(return_value=(accessor, {"configurable": {"thread_id": "thread-1"}})),
    )
    model_config = SimpleNamespace(context_window=1000)
    app_config = SimpleNamespace(
        models=[SimpleNamespace(name="fallback-model")],
        get_model_config=lambda name: model_config if name == "thread-model" else None,
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: app_config)
    monkeypatch.setattr(context_usage, "_count_messages_approximately", lambda value: 250 if value == messages else 0)

    result = await context_usage.build_context_usage(
        request=SimpleNamespace(app=SimpleNamespace()),
        thread_id="thread-1",
        run_store=_make_run_store(model_name="thread-model"),
    )

    assert result == {
        "token_count": 250,
        "max_context_tokens": 1000,
        "percentage": 25.0,
    }


@pytest.mark.asyncio
async def test_build_context_usage_returns_none_when_checkpoint_read_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        context_usage,
        "build_thread_checkpoint_state_accessor",
        AsyncMock(side_effect=RuntimeError("checkpoint unavailable")),
    )
    monkeypatch.setattr(context_usage, "get_config", lambda: SimpleNamespace())

    result = await context_usage.build_context_usage(
        request=SimpleNamespace(app=SimpleNamespace()),
        thread_id="thread-1",
        run_store=_make_run_store(),
    )

    assert result is None


def _promo_pricing_map() -> dict:
    """One discounted model beside a full-price one.

    Mirrors the shipped bundle, where only some entries carry a live promo — the
    interesting case is a thread that mixes both, because the promo total has to
    bill the undiscounted model at its ordinary rate.
    """
    return build_pricing_map(
        [
            SimpleNamespace(
                name="glm-5.2",
                model="z-ai/glm-5.2",
                pricing={
                    "currency": "USD",
                    "input_per_million": 1.15,
                    "output_per_million": 3.6,
                    "promo_input_per_million": 0.28,
                    "promo_output_per_million": 0.87,
                },
            ),
            SimpleNamespace(name="opus", model="claude-opus-5", pricing={"currency": "USD", "input_per_million": 5.0, "output_per_million": 25.0}),
        ],
    )


def test_promo_total_cost_prices_the_thread_at_the_live_discount(monkeypatch):
    """`total_cost` stays the standard rate; `promo_total_cost` is what you pay now.

    Both numbers cover the *whole* thread — a model with no promo contributes
    its ordinary cost to both totals, so the pair is always comparable rather
    than being a discounted subtotal next to a full total.
    """
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value=_agg_with_models(
            {
                "z-ai/glm-5.2": {"tokens": 2_000_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0},
                "claude-opus-5": {"tokens": 2_000_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0},
            }
        )
    )
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", _promo_pricing_map)
    app = _make_app(run_store)

    with TestClient(app) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    # standard: GLM 1.15 + 3.6 = 4.75 ; Opus 5 + 25 = 30 -> 34.75
    assert data["total_cost"] == pytest.approx(34.75)
    # promo: GLM 0.28 + 0.87 = 1.15 ; Opus undiscounted 30 -> 31.15
    assert data["promo_total_cost"] == pytest.approx(31.15)


def test_promo_total_cost_is_null_when_nothing_in_the_thread_is_discounted(monkeypatch):
    """No promo anywhere means one price, not the same number printed twice."""
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_agg_with_models({"claude-opus-5": {"tokens": 2_000_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0}}))
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", _promo_pricing_map)
    app = _make_app(run_store)

    with TestClient(app) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    assert data["total_cost"] == pytest.approx(30.0)
    assert data["promo_total_cost"] is None


def test_promo_total_cost_is_null_when_no_pricing_is_configured(monkeypatch):
    aux_usage.reset_aux_usage()
    run_store = _make_run_store()
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value=_agg_with_models({"z-ai/glm-5.2": {"tokens": 2_000_000, "runs": 1, "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0}}))
    monkeypatch.setattr(thread_runs, "build_context_usage", AsyncMock(return_value=None))
    monkeypatch.setattr(thread_runs, "_thread_pricing_map", dict)
    app = _make_app(run_store)

    with TestClient(app) as client:
        data = client.get("/api/threads/thread-1/token-usage").json()

    assert data["total_cost"] is None
    assert data["promo_total_cost"] is None
