"""GPU residency arbiter (fork feature, roadmap 13).

Everything here is a property that is **silent when broken** — a card that
quietly holds two tenants does not raise, it just runs several times slower
because Ollama offloaded layers to system RAM. So each test pins one of:

* the policy is *computed* from the budget and logged with its reasoning, so a
  bigger card resolves to ``shared`` without a code change;
* eviction happens on acquire and again on release, inside the tool call;
* residency is re-read from the services, never from in-process bookkeeping —
  a Gateway that died mid-generation is recovered by the next acquire;
* a cloud tenant is simply not resident, with no code path of its own;
* Ollama's eviction is per request, so the global ``ollama.keep_alive`` keeps
  its value for ordinary chat;
* one tenant at a time, process-wide, with an honest wait instead of a thrash.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from deerflow.community.comfyui.arbiter import (
    CloudTenant,
    ComfyUITenant,
    GpuArbiter,
    GpuBusyError,
    OllamaTenant,
    build_controllers,
    compute_policy,
    detect_budget_gb,
    nvidia_smi_used_mb,
)
from deerflow.config.media_config import GpuArbiterConfig, GpuTenantConfig


def _config(**overrides) -> GpuArbiterConfig:
    base = {
        "tenants": [
            GpuTenantConfig(name="ollama", kind="ollama", estimate_gb=20.0),
            GpuTenantConfig(name="comfyui", kind="comfyui", estimate_gb=16.0),
        ]
    }
    base.update(overrides)
    return GpuArbiterConfig(**base)


@dataclass
class FakeTenant:
    """A controller whose residency and evictions are observable."""

    name: str
    location: str = "local"
    is_resident: bool | None = True
    evictions: int = 0
    probes: int = 0
    evict_ok: bool = True
    log: list[str] = field(default_factory=list)

    async def resident(self) -> bool | None:
        self.probes += 1
        return self.is_resident

    async def evict(self) -> bool:
        self.evictions += 1
        self.log.append("evict")
        if self.evict_ok:
            self.is_resident = False
        return self.evict_ok


class TestPolicyComputation:
    def test_two_local_tenants_that_do_not_fit_resolve_to_exclusive(self):
        decision = compute_policy(_config(budget_gb=24.0, reserve_gb=1.0), 24.0)
        assert decision.policy == "exclusive"
        assert "36.0" in decision.reason and "23.0" in decision.reason, decision.reason

    def test_a_bigger_card_resolves_to_shared_on_its_own(self):
        """The upgrade path: config outcome, not a code change."""
        decision = compute_policy(_config(budget_gb=48.0, reserve_gb=1.0), 48.0)
        assert decision.policy == "shared"
        assert "co-reside" in decision.reason

    def test_an_unknown_estimate_falls_back_to_exclusive_and_says_which_tenant(self):
        config = _config()
        config.tenants[1].estimate_gb = 0.0
        decision = compute_policy(config, 48.0)
        assert decision.policy == "exclusive"
        assert "comfyui" in decision.reason

    def test_an_unknown_budget_assumes_the_card_holds_one_tenant(self):
        decision = compute_policy(_config(), None)
        assert decision.policy == "exclusive"
        assert "budget unknown" in decision.reason

    def test_a_single_local_tenant_has_nothing_to_arbitrate(self):
        config = _config(tenants=[GpuTenantConfig(name="comfyui", kind="comfyui")])
        assert compute_policy(config, 24.0).policy == "none"

    def test_a_cloud_lead_leaves_one_local_tenant_and_no_arbitration(self):
        config = _config(tenants=[GpuTenantConfig(name="claude", location="cloud"), GpuTenantConfig(name="comfyui", kind="comfyui")])
        assert compute_policy(config, 24.0).policy == "none"

    def test_an_explicit_policy_wins_and_says_so(self):
        decision = compute_policy(_config(policy="shared", budget_gb=8.0), 8.0)
        assert (decision.policy, decision.reason) == ("shared", "set explicitly in config")

    def test_disabling_the_arbiter_disables_arbitration(self):
        assert compute_policy(_config(enabled=False), 24.0).policy == "none"


class TestBudgetDetection:
    def test_an_explicit_budget_is_used_verbatim(self):
        assert detect_budget_gb(_config(budget_gb=12.5)) == 12.5

    def test_auto_reuses_the_wizard_detector_rather_than_a_second_one(self):
        calls = []

        def fake_detector():
            calls.append(1)
            return (24.0, "nvidia-smi")

        assert detect_budget_gb(_config(budget_gb="auto"), fake_detector) == 24.0
        assert calls == [1]

    def test_auto_degrades_to_unknown_when_nothing_is_detectable(self):
        assert detect_budget_gb(_config(budget_gb="auto"), lambda: None) is None

    def test_nvidia_smi_sums_every_card(self):
        assert nvidia_smi_used_mb(lambda _cmd: "1024\n2048\n") == 3072.0

    def test_nvidia_smi_absence_is_unknown_not_zero(self):
        assert nvidia_smi_used_mb(lambda _cmd: None) is None


@pytest.mark.asyncio
class TestAcquireRelease:
    def _arbiter(self, controllers, *, budget: float | None = 24.0, **overrides) -> GpuArbiter:
        config = _config(**overrides)
        return GpuArbiter(config, {tenant.name: tenant for tenant in controllers}, budget_gb=budget, used_vram_mb=lambda: None)

    async def test_exclusive_evicts_the_other_tenant_before_generating(self):
        ollama = FakeTenant("ollama")
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])
        async with arbiter.acquire("comfyui") as outcome:
            assert ollama.evictions == 1, "the lead model must be off the card before generation starts"
            assert outcome.evicted == ["ollama"]

    async def test_exclusive_evicts_itself_on_release_so_the_card_comes_back_empty(self):
        ollama = FakeTenant("ollama")
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])
        async with arbiter.acquire("comfyui"):
            assert comfy.evictions == 0
        assert comfy.evictions == 1, "leaving the diffusion weights resident makes the next chat turn slow"

    async def test_shared_evicts_nothing(self):
        ollama = FakeTenant("ollama")
        comfy = FakeTenant("comfyui")
        arbiter = self._arbiter([ollama, comfy], policy="shared")
        async with arbiter.acquire("comfyui"):
            pass
        assert (ollama.evictions, comfy.evictions) == (0, 0)

    async def test_a_cloud_tenant_is_never_evicted(self):
        cloud = FakeTenant("claude", location="cloud", is_resident=False)
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([cloud, comfy])
        async with arbiter.acquire("comfyui"):
            pass
        assert cloud.evictions == 0

    async def test_residency_is_re_read_on_every_acquire(self):
        """In-process bookkeeping cannot see a model another process loaded."""
        ollama = FakeTenant("ollama", is_resident=False)
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])
        async with arbiter.acquire("comfyui"):
            pass
        assert ollama.probes == 1 and ollama.evictions == 0
        ollama.is_resident = True
        async with arbiter.acquire("comfyui"):
            pass
        assert ollama.probes == 2 and ollama.evictions == 1

    async def test_vram_held_while_nobody_claims_it_is_evicted_anyway(self):
        """The crashed-Gateway case: recovered by the next acquire, not a restart."""
        ollama = FakeTenant("ollama", is_resident=False)
        comfy = FakeTenant("comfyui", is_resident=False)
        config = _config()
        arbiter = GpuArbiter(config, {"ollama": ollama, "comfyui": comfy}, budget_gb=24.0, used_vram_mb=lambda: 18_000.0)
        async with arbiter.acquire("comfyui") as outcome:
            pass
        assert ollama.evictions == 1
        assert any("evicting anyway" in note for note in outcome.notes), outcome.notes

    async def test_a_failed_eviction_is_reported_rather_than_hidden(self):
        ollama = FakeTenant("ollama", evict_ok=False)
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])
        async with arbiter.acquire("comfyui") as outcome:
            pass
        assert any("could not evict ollama" in note for note in outcome.notes), outcome.notes

    async def test_the_gpu_is_released_even_when_generation_raises(self):
        ollama = FakeTenant("ollama")
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])
        with pytest.raises(RuntimeError):
            async with arbiter.acquire("comfyui"):
                raise RuntimeError("generation blew up")
        # The semaphore must be free again: a second acquire would hang otherwise.
        async with asyncio.timeout(2):
            async with arbiter.acquire("comfyui"):
                pass

    async def test_two_generations_are_serialized_not_run_together(self):
        order: list[str] = []
        ollama = FakeTenant("ollama", is_resident=False)
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([ollama, comfy])

        async def generate(label: str) -> None:
            async with arbiter.acquire("comfyui"):
                order.append(f"{label}-start")
                await asyncio.sleep(0.02)
                order.append(f"{label}-end")

        await asyncio.gather(generate("a"), generate("b"))
        assert order in (["a-start", "a-end", "b-start", "b-end"], ["b-start", "b-end", "a-start", "a-end"]), order

    async def test_waiting_past_the_timeout_says_so_instead_of_queueing_forever(self):
        comfy = FakeTenant("comfyui", is_resident=False)
        arbiter = self._arbiter([comfy], wait_timeout_seconds=0.05)
        async with arbiter.acquire("comfyui"):
            with pytest.raises(GpuBusyError, match="held the GPU"):
                async with arbiter.acquire("comfyui"):
                    pass


@pytest.mark.asyncio
class TestTenantControllers:
    async def test_ollama_unloads_with_a_per_request_keep_alive_zero(self):
        """The global ollama.keep_alive must keep its value for ordinary chat."""
        import httpx

        posts: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/ps":
                return httpx.Response(200, json={"models": [{"model": "qwen3:8b", "size_vram": 8_000_000_000}]})
            if request.url.path == "/api/generate":
                import json as _json

                posts.append(_json.loads(request.content))
                return httpx.Response(200, json={})
            raise AssertionError(request.url.path)

        tenant = OllamaTenant(name="ollama", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tenant.resident() is True
        assert await tenant.evict() is True
        assert posts == [{"model": "qwen3:8b", "keep_alive": 0}]

    async def test_a_cpu_only_ollama_model_is_not_a_gpu_tenant(self):
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"models": [{"model": "qwen3:8b", "size_vram": 0}]})

        tenant = OllamaTenant(name="ollama", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tenant.resident() is False

    async def test_an_unreachable_ollama_reports_unknown_not_free(self):
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down", request=request)

        tenant = OllamaTenant(name="ollama", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await tenant.resident() is None

    async def test_comfyui_residency_reads_torch_vram(self):
        class _Client:
            base_url = "http://localhost:8188"
            freed = 0

            async def system_stats(self):
                return {"devices": [{"torch_vram_total": 6_000_000_000}]}

            async def free(self, **kwargs):
                type(self).freed += 1
                return True

        tenant = ComfyUITenant(name="comfyui", client=_Client())
        assert await tenant.resident() is True
        assert await tenant.evict() is True
        assert _Client.freed == 1

    async def test_a_cloud_tenant_is_never_resident(self):
        tenant = CloudTenant(name="claude")
        assert await tenant.resident() is False
        assert await tenant.evict() is True


class TestControllerConstruction:
    def test_each_configured_tenant_gets_a_controller_of_its_kind(self):
        controllers = build_controllers(
            _config(
                tenants=[
                    GpuTenantConfig(name="ollama", kind="ollama", base_url="http://ollama.test:11434"),
                    GpuTenantConfig(name="comfyui", kind="comfyui"),
                    GpuTenantConfig(name="claude", location="cloud"),
                ]
            )
        )
        assert isinstance(controllers["ollama"], OllamaTenant)
        assert controllers["ollama"].base_url == "http://ollama.test:11434"
        assert isinstance(controllers["comfyui"], ComfyUITenant)
        assert isinstance(controllers["claude"], CloudTenant)

    def test_a_local_tenant_without_an_eviction_mechanism_is_rejected_at_config_load(self):
        with pytest.raises(ValueError, match="declares no kind"):
            GpuTenantConfig(name="mystery", location="local")
