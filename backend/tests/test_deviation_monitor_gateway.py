"""The Gateway side of the deviation monitor.

Silent when broken: a run-context key missing from the allowlist is dropped
without a word (the button would look on and do nothing); a raw client value
would be checkpointed as sent; a client could forge the monitor's status
channel; and the composer would offer a button the operator switched off.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import features
from app.gateway.services import SERVER_OWNED_STATE_CHANNELS, merge_run_context_overrides, normalize_input, strip_server_owned_state_metadata
from deerflow.config.deviation_monitor_config import DeviationMonitorConfig

VALID = {"enabled": True, "model": "judge-small", "cadence": {"mode": "turns", "every": 3}}


class TestRunContext:
    def test_a_valid_request_reaches_both_sections_in_canonical_form(self) -> None:
        config: dict = {}
        merge_run_context_overrides(config, {"deviation_monitor": {**VALID, "model": "  judge-small  "}})
        for section in ("configurable", "context"):
            assert config[section]["deviation_monitor"] == VALID

    @pytest.mark.parametrize(
        ("raw", "code"),
        [
            ({"enabled": True, "model": "judge-small", "cadence": {"mode": "steps", "every": 500}}, "cadence_out_of_range"),
            ({"enabled": True, "model": "judge-small", "cadence": {"mode": "steps", "every": 1}, "note": "x" * 50}, "unknown_keys"),
            ("on", "not_an_object"),
        ],
    )
    def test_an_invalid_request_is_stored_as_off_with_its_reason_code_and_never_fails_the_run(self, raw, code) -> None:
        config: dict = {}
        merge_run_context_overrides(config, {"deviation_monitor": raw})
        for section in ("configurable", "context"):
            assert config[section]["deviation_monitor"] == {"enabled": False, "rejected": code}

    def test_a_raw_value_smuggled_through_body_config_is_normalized_too(self) -> None:
        config = {"configurable": {"deviation_monitor": {"enabled": True, "model": "judge-small", "cadence": {"mode": "steps", "every": 0}, "x": [1] * 10}}}
        merge_run_context_overrides(config, None)
        assert config["configurable"]["deviation_monitor"] == {"enabled": False, "rejected": "unknown_keys"}

    def test_absent_stays_absent(self) -> None:
        config: dict = {}
        merge_run_context_overrides(config, {"mode": "pro"})
        assert "deviation_monitor" not in config["configurable"] and "deviation_monitor" not in config["context"]


class TestStateChannel:
    def test_clients_cannot_write_the_monitor_status(self) -> None:
        assert "deviation_monitor" in SERVER_OWNED_STATE_CHANNELS
        forged = {"deviation_monitor": {"status": "on_track"}}
        with pytest.raises(HTTPException):
            strip_server_owned_state_metadata(forged)
        with pytest.raises(HTTPException):
            normalize_input(forged)


def _features_app(**config) -> FastAPI:
    app = FastAPI()
    app.state.scheduled_task_repo = None
    app.state.scheduled_task_service = None
    app.state.mcp_tasks_available = False
    app.state.subagent_batches_available = False
    app.state.subagent_batch_repo = None
    app.include_router(features.router)
    fake = SimpleNamespace(
        agents_api=SimpleNamespace(enabled=False),
        tools=[],
        subagent_runtime=SimpleNamespace(max_running=3),
        title=SimpleNamespace(enabled=True, model_name=None),
        knowledge_base=SimpleNamespace(enabled=False, scope_selection_enabled=False),
        scheduler=SimpleNamespace(enabled=False, tool_enabled=False, min_once_delay_seconds=60),
        get_tool_config=lambda name: None,
        **config,
    )
    app.dependency_overrides[get_config] = lambda: fake
    return app


@pytest.mark.parametrize(("operator", "expected"), [(DeviationMonitorConfig(), True), (DeviationMonitorConfig(enabled=False), False)])
def test_features_report_whether_the_operator_offers_the_monitor(monkeypatch, operator, expected) -> None:
    monkeypatch.delenv("GATEWAY_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with TestClient(_features_app(deviation_monitor=operator)) as client:
        response = client.get("/api/features")
    assert response.status_code == 200 and response.json()["deviation_monitor"] == {"enabled": expected}
