from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.subagents import SubagentRuntime


def test_runtime_rejects_batch_repository_without_enabled_batch_config() -> None:
    with pytest.raises(ValueError, match="batch_config.enabled"):
        SubagentRuntime(
            SubagentRuntimeConfig(),
            batch_repository=MagicMock(),
            batch_config=SubagentBatchesConfig(enabled=False),
        )


def test_runtime_rejects_batch_repository_without_app_config_snapshot() -> None:
    with pytest.raises(ValueError, match="explicit app_config snapshot"):
        SubagentRuntime(
            SubagentRuntimeConfig(),
            batch_repository=MagicMock(),
            batch_config=SubagentBatchesConfig(enabled=True),
        )


def test_runtime_uses_one_caller_owned_app_config_snapshot() -> None:
    app_config = SimpleNamespace(
        subagent_runtime=SubagentRuntimeConfig(max_running=11),
        subagents=SimpleNamespace(max_total_per_run=14),
        subagent_batches=SubagentBatchesConfig(enabled=False),
    )

    runtime = SubagentRuntime.from_app_config(app_config)

    assert runtime.config.max_running == 11
    assert runtime.max_total_per_run == 14
    assert runtime.app_config is app_config
    assert runtime.batch_submitter is None


@pytest.mark.asyncio
async def test_runtime_owns_batch_worker_lifecycle_and_shared_capacity() -> None:
    service = MagicMock()
    service.start = AsyncMock()
    service.stop = AsyncMock()
    repository = MagicMock()
    app_config = MagicMock()

    with patch(
        "deerflow.subagents.batch_service.SubagentBatchService",
        return_value=service,
    ) as service_type:
        runtime = SubagentRuntime(
            SubagentRuntimeConfig(max_running=9),
            batch_repository=repository,
            batch_config=SubagentBatchesConfig(enabled=True),
            app_config=app_config,
        )
        assert runtime.batch_submitter is None

        async with runtime:
            assert runtime.batch_submitter is service

        assert runtime.batch_submitter is None

    service_type.assert_called_once_with(
        repository=repository,
        config=runtime.batch_config,
        runtime_config=runtime.config,
        app_config=app_config,
        execution_capacity=runtime.execution_capacity,
        local_residency_gate=runtime.local_residency_gate,
    )
    service.start.assert_awaited_once_with()
    service.stop.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_runtime_shares_one_gpu_residency_gate_with_its_batch_worker() -> None:
    """Fork: a durable batch is where over-dispatch onto one local model lands.

    The batch worker builds its own executors, so a gate the runtime kept to
    itself would leave batch items ungated — and a batch is precisely the shape
    of work that fans out onto a single local model.
    """
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.ollama_config import OllamaConfig

    service = MagicMock()
    service.start = AsyncMock()
    service.stop = AsyncMock()
    app_config = SimpleNamespace(
        models=[ModelConfig(name="qwen3:32b", use="langchain_ollama:ChatOllama", model="qwen3:32b", size_bytes=20 * 1024**3, kv_bytes_per_token=100_000.0, num_ctx=16384)],
        ollama=OllamaConfig(vram_gb=24),
        subagent_runtime=SubagentRuntimeConfig(),
        subagents=SimpleNamespace(max_total_per_run=6),
        subagent_batches=SubagentBatchesConfig(enabled=True),
    )

    with patch("deerflow.subagents.batch_service.SubagentBatchService", return_value=service) as service_type:
        runtime = SubagentRuntime(
            SubagentRuntimeConfig(),
            batch_repository=MagicMock(),
            batch_config=SubagentBatchesConfig(enabled=True),
            app_config=app_config,
        )

    assert runtime.local_residency_gate is not None
    assert runtime.local_residency_gate.plan.profile_for("qwen3:32b") is not None
    assert service_type.call_args.kwargs["local_residency_gate"] is runtime.local_residency_gate


def test_runtime_without_a_config_snapshot_has_no_gpu_gate() -> None:
    # No snapshot means no model catalog and no `ollama:` block. Inventing a
    # plan from the global YAML here would give an SDK caller a limit it never
    # configured, on a machine the runtime knows nothing about.
    assert SubagentRuntime(SubagentRuntimeConfig()).local_residency_gate is None
