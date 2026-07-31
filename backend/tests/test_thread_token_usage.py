"""Tests for thread-level token usage aggregation API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.pricing import build_pricing_map
from app.gateway.routers import thread_runs
from deerflow.runtime import aux_usage


def _make_app(run_store: MagicMock):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    app.state.run_store = run_store
    return app


def test_thread_token_usage_returns_stable_shape():
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 150,
            "total_input_tokens": 90,
            "total_output_tokens": 60,
            "total_runs": 2,
            "by_model": {"unknown": {"tokens": 150, "runs": 2, "input_tokens": 90, "output_tokens": 60, "cache_read_tokens": 0}},
            "by_caller": {
                "lead_agent": 120,
                "subagent": 25,
                "middleware": 5,
            },
        },
    )
    app = _make_app(run_store)

    # No pricing configured → cost fields null, aux empty. Patch the pricing map
    # so the assertion does not depend on whatever config.yaml the test env has.
    with patch.object(thread_runs, "_thread_pricing_map", return_value={}), TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage")

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": "thread-1",
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
        "currency": None,
        "aux": {},
    }
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=False)


def test_thread_token_usage_can_include_active_runs():
    run_store = MagicMock()
    run_store.aggregate_tokens_by_thread = AsyncMock(
        return_value={
            "total_tokens": 175,
            "total_input_tokens": 120,
            "total_output_tokens": 55,
            "total_runs": 3,
            "by_model": {"unknown": {"tokens": 175, "runs": 3}},
            "by_caller": {
                "lead_agent": 145,
                "subagent": 25,
                "middleware": 5,
            },
        },
    )
    app = _make_app(run_store)

    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/token-usage?include_active=true")

    assert response.status_code == 200
    assert response.json()["total_tokens"] == 175
    assert response.json()["total_runs"] == 3
    run_store.aggregate_tokens_by_thread.assert_awaited_once_with("thread-1", include_active=True)


def _priced_map():
    return build_pricing_map(
        [
            SimpleNamespace(name="lead", model="lead-model", pricing={"currency": "USD", "input_per_million": 5, "output_per_million": 25}),
            SimpleNamespace(name="sub", model="sub-model", pricing={"currency": "USD", "input_per_million": 1, "output_per_million": 4}),
        ],
    )


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
        with patch.object(thread_runs, "_thread_pricing_map", side_effect=_priced_map), TestClient(app) as client:
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
    with patch.object(thread_runs, "_thread_pricing_map", return_value={}), TestClient(app) as client:
        data = client.get("/api/threads/thread-x/token-usage").json()
    assert data["total_cost"] is None
    assert data["currency"] is None
    assert data["by_model"]["m"]["cost"] is None
