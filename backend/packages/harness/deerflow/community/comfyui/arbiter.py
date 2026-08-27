"""GPU residency arbiter — one card, several tenants, no silent thrashing.

A language model and a diffusion model both want the whole card, and on a 24 GB
consumer GPU they do not both fit. The failure is silent rather than loud:
Ollama does not error when weights do not fit, it offloads layers to system RAM
and answers several times slower.

Four properties are load-bearing here; a refactor must not "simplify" any of
them away:

1. **Eviction happens inside the tool call.** An agent turn is a chain of model
   calls, so the lead model reloads the moment a tool returns. A swap sequenced
   at the plan level therefore puts both tenants on the card at once.
   ``generate_image`` acquires, evicts, generates, releases (evicting itself),
   and the agent never needs to know VRAM exists.
2. **Tenants, not special cases.** Each tenant declares ``location: local |
   cloud``. A cloud tenant is never resident, so every eviction against it is a
   no-op — that is what keeps a cloud lead from needing a code path of its own.
3. **Verify, never assume.** Residency is re-read from the services on every
   acquire (Ollama ``/api/ps``, ComfyUI ``/system_stats``, ``nvidia-smi`` as
   tiebreak) instead of from in-process bookkeeping. A Gateway that died
   mid-generation leaves the card held; the next acquire is what recovers it.
4. **One tenant at a time, process-wide.** A depth-1 semaphore serializes
   *tenants*, not callers: two threads generating at once would otherwise
   thrash with neither finishing. Callers queue behind it and are told they are
   waiting.

The Ollama eviction passes ``keep_alive: 0`` **per request**. The global
``ollama.keep_alive`` exists to stop subagent cold starts and keeps its value
for ordinary chat.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx

from deerflow.config.media_config import GpuArbiterConfig, GpuTenantConfig

from .client import ComfyUIClient

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
# Below this, "used VRAM" is the desktop compositor, not a held model.
_TIEBREAK_HELD_MB = 1024.0


class GpuBusyError(RuntimeError):
    """The GPU semaphore was held past the caller's patience."""


@dataclass(frozen=True)
class PolicyDecision:
    """The residency policy plus the reasoning that produced it."""

    policy: str  # "exclusive" | "shared" | "none"
    reason: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.policy} ({self.reason})"


@dataclass
class AcquireOutcome:
    """What the arbiter had to do to hand over the card."""

    tenant: str
    policy: PolicyDecision
    waited_seconds: float = 0.0
    evicted: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"gpu policy: {self.policy}"]
        if self.waited_seconds >= 1.0:
            parts.append(f"waited {self.waited_seconds:.0f}s for the GPU")
        if self.evicted:
            parts.append("evicted " + ", ".join(self.evicted))
        parts.extend(self.notes)
        return "; ".join(parts)


def compute_policy(config: GpuArbiterConfig, budget_gb: float | None) -> PolicyDecision:
    """Derive exclusive / shared / none, with the reasoning that got there.

    Computed by default so a later GPU upgrade is a config outcome rather than
    a code change: a bigger card resolves to ``shared`` on its own and the
    swapping stops.
    """
    if not config.enabled:
        return PolicyDecision("none", "media.gpu.enabled is false")
    if config.policy != "auto":
        return PolicyDecision(config.policy, "set explicitly in config")

    local = [tenant for tenant in config.tenants if tenant.location == "local"]
    if len(local) < 2:
        return PolicyDecision("none", f"{len(local)} local tenant(s) — nothing to arbitrate")
    if budget_gb is None:
        return PolicyDecision("exclusive", "GPU budget unknown (set media.gpu.budget_gb) — assuming the card holds one tenant")

    usable = budget_gb - config.reserve_gb
    unknown = [tenant.name for tenant in local if tenant.estimate_gb <= 0]
    if unknown:
        return PolicyDecision("exclusive", f"no VRAM estimate for {', '.join(sorted(unknown))} — assuming they do not co-reside")
    total = sum(tenant.estimate_gb for tenant in local)
    if total <= usable:
        return PolicyDecision("shared", f"local tenants need {total:.1f} GiB, budget leaves {usable:.1f} GiB — they co-reside")
    return PolicyDecision("exclusive", f"local tenants need {total:.1f} GiB but budget leaves only {usable:.1f} GiB")


def _load_wizard_vram_detector() -> Callable[[], tuple[float, str] | None] | None:
    """Import ``scripts/wizard/steps/ollama.py::detect_vram_gb``, or None.

    That function already parses nvidia-smi / rocm-smi / Apple unified memory,
    and a second detector would drift from it. The Gateway runs from
    ``backend/`` with the repo's ``scripts/`` directory off ``sys.path``, so the
    plain import fails there; the repo root is located from this file's own
    path (or ``DEER_FLOW_REPO_ROOT``) before giving up. A packaged install
    without the repo scripts degrades to "budget unknown", which the policy
    reads as exclusive — the safe direction.
    """
    for module_path in ("wizard.steps.ollama", "scripts.wizard.steps.ollama"):
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue
        return getattr(module, "detect_vram_gb", None)

    roots: list[Path] = []
    env_root = os.environ.get("DEER_FLOW_REPO_ROOT", "").strip()
    if env_root:
        roots.append(Path(env_root))
    roots.extend(Path(__file__).resolve().parents[:8])
    for root in roots:
        candidate = root / "scripts" / "wizard" / "steps" / "ollama.py"
        if not candidate.is_file():
            continue
        # Import it as the package it is, rather than loading the file alone:
        # the module imports its siblings (`wizard.ui`, `wizard.providers`), so
        # a bare file load fails on the first of them. Appended, never
        # prepended — the repo's scripts/ directory must not shadow anything.
        scripts_dir = str(root / "scripts")
        if scripts_dir not in sys.path:
            sys.path.append(scripts_dir)
        try:
            module = importlib.import_module("wizard.steps.ollama")
        except Exception as exc:
            logger.debug(f"could not import the wizard VRAM detector from {candidate}: {exc}")
            return None
        return getattr(module, "detect_vram_gb", None)
    logger.debug("media.gpu.budget_gb is 'auto' but the wizard VRAM detector could not be located")
    return None


@lru_cache(maxsize=1)
def _detected_budget_gb() -> float | None:
    """Detected VRAM, cached for the process.

    Detection shells out to nvidia-smi / rocm-smi; a generation must not pay
    that on every call, and a card does not change size while the Gateway runs.
    """
    detect = _load_wizard_vram_detector()
    if detect is None:
        return None
    return _run_detector(detect)


def detect_budget_gb(config: GpuArbiterConfig, detector: Callable[[], tuple[float, str] | None] | None = None) -> float | None:
    """Resolve ``budget_gb``: an explicit number, or the wizard's detection."""
    if config.budget_gb != "auto":
        return float(config.budget_gb)
    if detector is None:
        return _detected_budget_gb()
    return _run_detector(detector)


def _run_detector(detect: Callable[[], tuple[float, str] | None]) -> float | None:
    try:
        detected = detect()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"GPU budget detection failed: {exc}")
        return None
    if not detected:
        return None
    return float(detected[0])


def nvidia_smi_used_mb(run: Callable[[list[str]], str | None] | None = None) -> float | None:
    """Used VRAM from nvidia-smi, or None when the tool is not available."""
    runner = run or _run_command
    output = runner(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    if not output:
        return None
    total = 0.0
    seen = False
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            total += float(line)
            seen = True
        except ValueError:
            continue
    return total if seen else None


def _run_command(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=5.0, check=False)  # noqa: S603 - fixed argv, no shell
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


class TenantController(Protocol):
    """One tenant's residency probe and eviction mechanism."""

    name: str
    location: str

    async def resident(self) -> bool | None:
        """True/False, or None when the service could not be asked."""

    async def evict(self) -> bool:
        """Release this tenant's VRAM. Returns False when it could not."""


@dataclass
class CloudTenant:
    """A tenant that lives somewhere else. Never resident, never evicted."""

    name: str
    location: str = "cloud"

    async def resident(self) -> bool | None:
        return False

    async def evict(self) -> bool:
        return True


@dataclass
class OllamaTenant:
    """Ollama, evicted with a per-request ``keep_alive: 0``."""

    name: str
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    location: str = "local"
    timeout: float = 10.0
    client_factory: Any = None

    def _client(self) -> httpx.AsyncClient:
        factory = self.client_factory or (lambda: httpx.AsyncClient(timeout=self.timeout))
        return factory()

    async def _resident_models(self) -> list[str] | None:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url.rstrip('/')}/api/ps")
                if response.status_code >= 400:
                    return None
                data = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []
        resident: list[str] = []
        for entry in models:
            if not isinstance(entry, dict):
                continue
            # size_vram is the part actually on the card; a CPU-only load is
            # not a GPU tenant and must not trigger an eviction.
            if float(entry.get("size_vram") or 0) <= 0:
                continue
            name = entry.get("model") or entry.get("name")
            if name:
                resident.append(str(name))
        return resident

    async def resident(self) -> bool | None:
        models = await self._resident_models()
        if models is None:
            return None
        return bool(models)

    async def evict(self) -> bool:
        models = await self._resident_models()
        if not models:
            return models is not None
        ok = True
        for model in models:
            try:
                async with self._client() as client:
                    response = await client.post(
                        f"{self.base_url.rstrip('/')}/api/generate",
                        json={"model": model, "keep_alive": 0},
                    )
                ok = ok and response.status_code < 400
            except httpx.HTTPError as exc:
                logger.warning(f"could not unload Ollama model {model}: {exc}")
                ok = False
        return ok


@dataclass
class ComfyUITenant:
    """ComfyUI, evicted with its own ``POST /free``."""

    name: str
    client: ComfyUIClient
    location: str = "local"

    async def resident(self) -> bool | None:
        try:
            stats = await self.client.system_stats()
        except Exception:
            return None
        devices = stats.get("devices")
        if not isinstance(devices, list) or not devices:
            return None
        for device in devices:
            if isinstance(device, dict) and float(device.get("torch_vram_total") or 0) > 0:
                return True
        return False

    async def evict(self) -> bool:
        try:
            return await self.client.free()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"could not free ComfyUI VRAM: {exc}")
            return False


def build_controllers(
    config: GpuArbiterConfig,
    *,
    comfyui_client: ComfyUIClient | None = None,
) -> dict[str, TenantController]:
    """Instantiate one controller per configured tenant."""
    controllers: dict[str, TenantController] = {}
    for tenant in config.tenants:
        controllers[tenant.name] = _build_controller(tenant, comfyui_client=comfyui_client)
    return controllers


def _build_controller(tenant: GpuTenantConfig, *, comfyui_client: ComfyUIClient | None) -> TenantController:
    if tenant.location == "cloud":
        return CloudTenant(name=tenant.name)
    if tenant.kind == "ollama":
        return OllamaTenant(name=tenant.name, base_url=tenant.base_url or DEFAULT_OLLAMA_BASE_URL)
    client = comfyui_client
    if client is None or (tenant.base_url and tenant.base_url.rstrip("/") != client.base_url):
        client = ComfyUIClient(tenant.base_url or (client.base_url if client else "http://localhost:8188"))
    return ComfyUITenant(name=tenant.name, client=client)


# One semaphore per event loop: the Gateway runs a single loop, while tests
# create a fresh one per `asyncio.run`, and an asyncio primitive bound to a
# dead loop raises instead of arbitrating.
_semaphores: dict[int, asyncio.Semaphore] = {}


def _loop_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(loop)
    semaphore = _semaphores.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(1)
        _semaphores[key] = semaphore
    return semaphore


class GpuArbiter:
    """Serializes GPU tenants and enforces the residency policy."""

    def __init__(
        self,
        config: GpuArbiterConfig,
        controllers: dict[str, TenantController],
        *,
        budget_gb: float | None = None,
        used_vram_mb: Callable[[], float | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.controllers = controllers
        self.decision = compute_policy(config, budget_gb)
        self._used_vram_mb = used_vram_mb if used_vram_mb is not None else nvidia_smi_used_mb
        self._clock = clock

    @classmethod
    def from_config(cls, config: GpuArbiterConfig, *, comfyui_client: ComfyUIClient | None = None) -> GpuArbiter:
        return cls(config, build_controllers(config, comfyui_client=comfyui_client), budget_gb=detect_budget_gb(config))

    def _others(self, tenant: str) -> Sequence[TenantController]:
        return [controller for name, controller in self.controllers.items() if name != tenant]

    async def _evict_others(self, tenant: str, outcome: AcquireOutcome) -> None:
        others = self._others(tenant)
        residency: dict[str, bool | None] = {}
        for controller in others:
            residency[controller.name] = await controller.resident()

        # Tiebreak: nobody claims the card but something is holding it. That is
        # the crashed-Gateway case; evict anyway rather than degrade silently.
        held_anyway = False
        if others and all(value is False for value in residency.values()):
            used = self._used_vram_mb()
            if used is not None and used >= _TIEBREAK_HELD_MB:
                held_anyway = True
                outcome.notes.append(f"nvidia-smi reports {used:.0f} MiB held while no tenant claims it — evicting anyway")

        for controller in others:
            if controller.location != "local":
                continue
            if residency[controller.name] is False and not held_anyway:
                continue
            if await controller.evict():
                outcome.evicted.append(controller.name)
            else:
                outcome.notes.append(f"could not evict {controller.name}; generation may run degraded")

    @contextlib.asynccontextmanager
    async def acquire(self, tenant: str) -> AsyncIterator[AcquireOutcome]:
        """Hold the GPU for one tenant: acquire → (caller generates) → release."""
        outcome = AcquireOutcome(tenant=tenant, policy=self.decision)
        semaphore = _loop_semaphore()
        started = self._clock()
        if semaphore.locked():
            logger.info(f"waiting for the GPU: another generation holds it (tenant {tenant})")
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.config.wait_timeout_seconds)
        except TimeoutError as exc:
            raise GpuBusyError(f"Another generation has held the GPU for more than {self.config.wait_timeout_seconds:.0f}s; try again once it finishes.") from exc
        outcome.waited_seconds = self._clock() - started
        try:
            if self.decision.policy == "exclusive":
                await self._evict_others(tenant, outcome)
            logger.info(f"GPU acquired by {tenant}: {outcome.summary()}")
            yield outcome
        finally:
            try:
                if self.decision.policy == "exclusive":
                    controller = self.controllers.get(tenant)
                    if controller is not None and controller.location == "local":
                        # Return an empty card: the lead model reloads on the
                        # very next turn, so leaving the diffusion weights
                        # resident is what makes the next chat message slow.
                        await controller.evict()
            finally:
                semaphore.release()
