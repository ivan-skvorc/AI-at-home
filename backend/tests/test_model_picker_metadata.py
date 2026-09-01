"""`/api/models` exposes what a picker row needs to size a local model.

Fork feature. A model's weights and its context window are the two halves of one
question — a 20 GiB model and a 32K window do not both fit on a 24 GiB card —
and both live in `config.yaml`, where the frontend cannot see them. Until they
were returned here the picker could only show a name and a price, so choosing a
local model meant guessing and then watching the daemon offload to CPU.

The failure mode is silent, which is what these pin: dropping either field from
the response leaves every row valid and every test elsewhere green, and simply
renders no size for any model — indistinguishable from a daemon that never
reported one.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.deps import get_config
from app.gateway.routers import models as models_router
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.config.token_usage_config import TokenUsageConfig

LOCAL = ModelConfig(
    name="qwen3:8b",
    model="qwen3:8b",
    display_name="qwen3:8b (Ollama)",
    use="langchain_ollama:ChatOllama",
    context_window=32768,
    size_bytes=5_200_000_000,
)
HOSTED = ModelConfig(
    name="claude",
    model="claude-opus-5",
    display_name="Claude Opus 5 (Anthropic)",
    use="langchain_anthropic:ChatAnthropic",
)


def _client() -> TestClient:
    config = AppConfig(
        models=[LOCAL, HOSTED],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        token_usage=TokenUsageConfig(enabled=False),
    )
    app = FastAPI()
    app.include_router(models_router.router)
    # Injected rather than resolved: `config.yaml` is gitignored, so a test that
    # falls back to `AppConfig.from_file()` passes locally and fails CI.
    app.dependency_overrides[get_config] = lambda: config
    return TestClient(app)


def _by_name(payload: dict) -> dict:
    return {model["name"]: model for model in payload["models"]}


class TestListModels:
    def test_a_local_model_reports_its_weights_and_window(self):
        models = _by_name(_client().get("/api/models").json())
        assert models["qwen3:8b"]["size_bytes"] == 5_200_000_000
        assert models["qwen3:8b"]["context_window"] == 32768

    def test_a_hosted_model_reports_neither_rather_than_zero(self):
        # Null is what tells the row to show nothing. A 0 would render as a
        # size, and a wrong one, on every cloud model in the list.
        models = _by_name(_client().get("/api/models").json())
        assert models["claude"]["size_bytes"] is None
        assert models["claude"]["context_window"] is None


class TestGetModel:
    def test_the_single_model_route_agrees_with_the_list(self):
        # Two routes build `ModelResponse` by hand; a field added to one and not
        # the other is a difference nothing else would notice.
        client = _client()
        listed = _by_name(client.get("/api/models").json())["qwen3:8b"]
        single = client.get("/api/models/qwen3:8b").json()
        assert single["size_bytes"] == listed["size_bytes"]
        assert single["context_window"] == listed["context_window"]
