"""Fork feature: GPU-residency admission for subagents on a local Ollama model.

The failure these tests defend against is silent by construction. Ollama does
not reject an over-dispatch — it queues the extra requests inside the daemon
where the Gateway cannot see them, or evicts one model's weights to load
another's — so nothing raises, nothing logs, and the only symptom is that local
subagents are inexplicably slow. Every assertion here is therefore about a
decision made *before* a request is sent, because after it is sent there is
nothing left to observe.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deerflow.config.model_config import ModelConfig
from deerflow.config.ollama_config import OllamaConfig
from deerflow.config.subagent_runtime_config import LocalModelCapacityConfig, SubagentRuntimeConfig
from deerflow.subagents.capacity import SubagentCapacityError
from deerflow.subagents.local_residency import (
    GIB,
    VRAM_OVERHEAD_BYTES,
    LocalModelProfile,
    LocalModelResidencyGate,
    LocalModelResidencyTimeout,
    LocalResidencyPlan,
    build_local_residency_plan,
    configure_subagent_local_residency,
    get_subagent_local_residency_gate,
    model_footprint_bytes,
    reset_subagent_local_residency,
)

CARD = 24 * GIB
BUDGET = CARD - VRAM_OVERHEAD_BYTES


def ollama_model(name: str, *, weights_gib: float, kv_per_token: float | None = 100_000.0, num_ctx: int | None = 16384, model: str | None = None) -> ModelConfig:
    payload = {
        "name": name,
        "use": "langchain_ollama:ChatOllama",
        "model": model or name,
        "size_bytes": int(weights_gib * GIB),
    }
    if kv_per_token is not None:
        payload["kv_bytes_per_token"] = kv_per_token
    if num_ctx is not None:
        payload["num_ctx"] = num_ctx
        payload["context_window"] = num_ctx
    return ModelConfig(**payload)


def app_config(models, *, ollama: OllamaConfig | None = None, capacity: LocalModelCapacityConfig | None = None):
    """A config-shaped object; the plan builder reads it with getattr only."""
    return SimpleNamespace(
        models=models,
        ollama=ollama if ollama is not None else OllamaConfig(vram_gb=24),
        subagent_runtime=SubagentRuntimeConfig(local_model_capacity=capacity or LocalModelCapacityConfig()),
    )


def profile(name: str, *, footprint_bytes: int, parallel_slots: int = 1, daemon_model: str | None = None) -> LocalModelProfile:
    return LocalModelProfile(config_name=name, daemon_model=daemon_model or name, footprint_bytes=footprint_bytes, parallel_slots=parallel_slots)


def plan(*profiles: LocalModelProfile, vram_bytes: int = BUDGET, queue_timeout_seconds: float = 30) -> LocalResidencyPlan:
    return LocalResidencyPlan(vram_bytes=vram_bytes, profiles={item.config_name: item for item in profiles}, queue_timeout_seconds=queue_timeout_seconds)


class TestFootprint:
    """A local model's resident cost is weights *plus* the cache it asks for."""

    def test_footprint_is_weights_plus_the_kv_cache_for_every_parallel_slot(self):
        model = ollama_model("qwen3:32b", weights_gib=20, kv_per_token=100_000.0, num_ctx=16384)
        assert model_footprint_bytes(model, num_parallel=1) == (int(20 * GIB) + 100_000 * 16384, False)
        # Ollama allocates a KV cache per slot up front, so slots multiply the
        # cache and not the weights. Costing them as extra copies of the model
        # would refuse dispatches the card can actually hold.
        assert model_footprint_bytes(model, num_parallel=2) == (int(20 * GIB) + 2 * 100_000 * 16384, False)

    def test_weights_alone_are_used_and_flagged_when_the_cache_cost_is_unknown(self):
        # A config synced before `kv_bytes_per_token` existed. Weights-only
        # under-counts, so it is reported as an estimate rather than silently
        # treated as the real footprint — but it still bounds dispatch, which is
        # strictly better than the unbounded behavior it replaces.
        model = ollama_model("qwen3:32b", weights_gib=20, kv_per_token=None)
        assert model_footprint_bytes(model, num_parallel=1) == (int(20 * GIB), True)

    def test_a_model_with_no_weight_size_has_no_footprint_at_all(self):
        model = ModelConfig(name="mystery", use="langchain_ollama:ChatOllama", model="mystery")
        assert model_footprint_bytes(model, num_parallel=1) is None


class TestPlan:
    """No opinion is a valid answer, and it is the answer more often than not."""

    def test_a_configured_card_and_a_sized_model_produce_a_plan(self):
        built = build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20)]))
        assert built is not None
        assert built.vram_bytes == BUDGET
        assert built.profile_for("qwen3:32b").footprint_bytes == int(20 * GIB) + 100_000 * 16384

    def test_no_vram_budget_means_no_gate(self):
        # The GPU's size is the one number the gate cannot infer. Guessing it
        # would serialize work on exactly the deployments that told it least.
        assert build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20)], ollama=OllamaConfig())) is None

    def test_turning_the_feature_off_means_no_gate(self):
        built = build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20)], capacity=LocalModelCapacityConfig(enabled=False)))
        assert built is None

    def test_hosted_models_are_not_in_the_plan(self):
        hosted = ModelConfig(name="claude-opus-5", use="langchain_anthropic:ChatAnthropic", model="claude-opus-5")
        assert build_local_residency_plan(app_config([hosted])) is None

    def test_num_parallel_is_the_slot_count_every_profile_carries(self):
        built = build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=8)], ollama=OllamaConfig(vram_gb=24, num_parallel=2)))
        assert built.profile_for("qwen3:32b").parallel_slots == 2

    def test_a_weights_only_estimate_says_so_at_startup(self, caplog):
        # An under-count is the one state an operator can act on (re-run the
        # sync), so it is named once rather than left to be inferred from
        # sub-agents that overlap more than the card should allow.
        with caplog.at_level("INFO", logger="deerflow.subagents.local_residency"):
            built = build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20, kv_per_token=None)]))
        assert built.profile_for("qwen3:32b").weights_only is True
        assert "costed at weights only" in caplog.text
        assert "qwen3:32b" in caplog.text

    def test_two_entries_for_one_pulled_model_share_a_residency_at_the_larger_cost(self):
        # The daemon loads `qwen3:32b` once no matter how many config entries
        # point at it, so both aliases must reserve against the same key — and
        # at the larger of the two footprints, or the ledger admits a load that
        # does not fit.
        small_window = ollama_model("qwen3-short", weights_gib=8, num_ctx=8192, model="qwen3:32b")
        big_window = ollama_model("qwen3-long", weights_gib=8, num_ctx=32768, model="qwen3:32b")
        built = build_local_residency_plan(app_config([small_window, big_window]))
        assert built.profile_for("qwen3-short").daemon_model == "qwen3:32b"
        assert built.profile_for("qwen3-short").footprint_bytes == built.profile_for("qwen3-long").footprint_bytes
        assert built.profile_for("qwen3-short").footprint_bytes == int(8 * GIB) + 100_000 * 32768


class TestGate:
    """What actually runs at once, which is the whole point of the feature."""

    @pytest.mark.anyio
    async def test_a_model_that_fits_the_card_once_runs_one_subagent_at_a_time(self):
        # The headline case: five delegations, a 20 GiB model, a 24 GiB card.
        # They must run, and they must run one after another — not three at once
        # into a daemon queue nobody can see.
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=int(21 * GIB))))
        concurrent = 0
        peak = 0
        order: list[int] = []

        async def dispatch(index: int) -> None:
            nonlocal concurrent, peak
            async with gate.slot("big"):
                concurrent += 1
                peak = max(peak, concurrent)
                order.append(index)
                await asyncio.sleep(0)
                concurrent -= 1

        await asyncio.gather(*(dispatch(index) for index in range(5)))
        assert peak == 1
        assert order == [0, 1, 2, 3, 4]

    @pytest.mark.anyio
    async def test_a_model_the_card_holds_twice_runs_two_at_a_time(self):
        # "Twice" for one model is not two copies of the weights — Ollama loads
        # a model once — it is two OLLAMA_NUM_PARALLEL slots against that copy,
        # whose cache the sync already sized for both.
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=int(21 * GIB), parallel_slots=2)))
        concurrent = 0
        peak = 0

        async def dispatch() -> None:
            nonlocal concurrent, peak
            async with gate.slot("big"):
                concurrent += 1
                peak = max(peak, concurrent)
                await asyncio.sleep(0.01)
                concurrent -= 1

        await asyncio.gather(*(dispatch() for _ in range(5)))
        assert peak == 2

    @pytest.mark.anyio
    async def test_models_that_co_reside_run_in_parallel(self):
        # The other half of the contract: work that CAN run in parallel must.
        # A gate that only ever serializes would be a regression dressed up as
        # a fix.
        gate = LocalModelResidencyGate(plan(profile("a", footprint_bytes=int(5 * GIB)), profile("b", footprint_bytes=int(5 * GIB))))
        started = asyncio.Event()

        async def first() -> None:
            async with gate.slot("a"):
                started.set()
                await asyncio.sleep(0.05)

        async def second() -> None:
            await started.wait()
            async with gate.slot("b"):
                assert gate.snapshot().running == {"a": 1, "b": 1}

        await asyncio.wait_for(asyncio.gather(first(), second()), timeout=2)

    @pytest.mark.anyio
    async def test_a_model_bigger_than_the_card_runs_alone_rather_than_never(self):
        # Ollama offloads layers to system RAM for these (FORK.md §30): slow,
        # not impossible. Charging it the whole card is what keeps "alone" from
        # becoming "deadlocked".
        gate = LocalModelResidencyGate(plan(profile("huge", footprint_bytes=int(60 * GIB)), profile("small", footprint_bytes=int(2 * GIB))))
        async with gate.slot("huge"):
            assert gate.snapshot().reserved_bytes == BUDGET
        # And it is still admitted, twice over, one at a time.
        for _ in range(2):
            await asyncio.wait_for(_hold(gate, "huge"), timeout=2)

    @pytest.mark.anyio
    async def test_a_small_model_does_not_jump_the_queue_ahead_of_a_waiting_large_one(self):
        # Strict FIFO. Admitting the small model here raises throughput and
        # starves the large one for as long as small work keeps arriving, which
        # is the failure mode this gate exists to prevent.
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=int(20 * GIB)), profile("small", footprint_bytes=int(1 * GIB))))
        admitted: list[str] = []
        release = asyncio.Event()

        async def holder() -> None:
            async with gate.slot("big"):
                admitted.append("holder")
                await release.wait()

        async def queued(name: str) -> None:
            async with gate.slot(name):
                admitted.append(name)

        first = asyncio.create_task(holder())
        while not admitted:
            await asyncio.sleep(0)
        second = asyncio.create_task(queued("big"))
        await asyncio.sleep(0)
        third = asyncio.create_task(queued("small"))
        await asyncio.sleep(0)

        assert gate.snapshot().queued == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second, third), timeout=2)
        assert admitted == ["holder", "big", "small"]

    @pytest.mark.anyio
    async def test_an_unknown_model_is_not_gated_at_all(self):
        # A hosted model, or one the sync never sized: the gate has no opinion,
        # and no opinion must mean the dispatch behaves as it did before it
        # existed — not "wait", and not "guess".
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=BUDGET)))
        async with gate.slot("big"):
            async with gate.slot("claude-opus-5") as resolved:
                assert resolved is None
            async with gate.slot(None) as resolved:
                assert resolved is None

    @pytest.mark.anyio
    async def test_waiting_past_the_deadline_fails_admission_rather_than_the_work(self):
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=BUDGET), queue_timeout_seconds=0.05))
        release = asyncio.Event()

        async def holder() -> None:
            async with gate.slot("big"):
                await release.wait()

        first = asyncio.create_task(holder())
        await asyncio.sleep(0)
        with pytest.raises(LocalModelResidencyTimeout, match="GPU residency"):
            async with gate.slot("big"):
                raise AssertionError("unreachable")
        # The executor already turns a capacity error into a failed result
        # flagged as an admission failure; inheriting keeps a GPU wait from
        # looking like the subagent's own work failing.
        assert issubclass(LocalModelResidencyTimeout, SubagentCapacityError)
        release.set()
        await first
        assert gate.snapshot().queued == 0
        assert gate.snapshot().running == {}

    @pytest.mark.anyio
    async def test_a_timed_out_waiter_does_not_leave_the_queue_blocked(self):
        gate = LocalModelResidencyGate(plan(profile("big", footprint_bytes=BUDGET), queue_timeout_seconds=0.05))
        release = asyncio.Event()
        finished: list[str] = []

        async def holder() -> None:
            async with gate.slot("big"):
                await release.wait()

        async def doomed() -> None:
            with pytest.raises(LocalModelResidencyTimeout):
                async with gate.slot("big"):
                    pass
            finished.append("doomed")

        first = asyncio.create_task(holder())
        await asyncio.sleep(0)
        await doomed()
        release.set()
        await first
        # The queue is clean, so the next dispatch is admitted immediately.
        await asyncio.wait_for(_hold(gate, "big"), timeout=2)
        assert finished == ["doomed"]


class TestProcessSingleton:
    @pytest.fixture(autouse=True)
    def _reset(self):
        yield
        reset_subagent_local_residency()

    @pytest.mark.anyio
    async def test_an_unconfigured_process_has_no_gate(self):
        reset_subagent_local_residency()
        assert get_subagent_local_residency_gate() is None

    @pytest.mark.anyio
    async def test_a_live_ledger_never_silently_moves_event_loops(self):
        # Waiters hold futures bound to the loop that created them. Handing a
        # caller on a new loop a fresh gate would drop a live ledger and leave
        # those awaits unresolvable — silently over-admitting the card.
        configure_subagent_local_residency(build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20)])))
        gate = get_subagent_local_residency_gate()
        async with gate.slot("qwen3:32b"):
            gate._plan = LocalResidencyPlan(vram_bytes=gate.plan.vram_bytes, profiles=gate.plan.profiles)
            from deerflow.subagents import local_residency

            with local_residency._state.lock:
                local_residency._state.loop = None
            with pytest.raises(RuntimeError, match="move event loops"):
                get_subagent_local_residency_gate()

    @pytest.mark.anyio
    async def test_the_configured_plan_is_what_the_gate_admits_against(self):
        configure_subagent_local_residency(build_local_residency_plan(app_config([ollama_model("qwen3:32b", weights_gib=20)])))
        gate = get_subagent_local_residency_gate()
        assert gate is not None
        assert gate is get_subagent_local_residency_gate()
        assert gate.plan.profile_for("qwen3:32b") is not None


async def _hold(gate: LocalModelResidencyGate, model: str) -> None:
    async with gate.slot(model):
        return
