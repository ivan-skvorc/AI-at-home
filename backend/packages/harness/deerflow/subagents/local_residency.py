"""Fork feature. GPU-residency admission for subagents on a local Ollama model.

``capacity.py`` answers "how many subagents may run in this process at once?"
with one number chosen at startup. For a hosted model that is the right
question. For a local one it is the wrong question asked of the wrong resource:
what actually bounds the work is the card, and the card's answer depends on
which model was picked — a 4B model and a 120B model on the same 24 GiB GPU are
not the same amount of parallelism.

Over-dispatching does not make Ollama fail, which is exactly why it went
unnoticed. One model, more requests than ``OLLAMA_NUM_PARALLEL`` slots: the
extra requests queue *inside the daemon*, invisible to the Gateway, while each
subagent's own execution timeout runs down. Two different local models that do
not co-reside: the daemon evicts one to load the other, on every alternation,
and a run that would have taken minutes takes tens of them. Both failures are
silent and both look like "local models are slow".

Three properties are load-bearing; a refactor must not "simplify" any away:

1. **Same model, different models — two different limits, both real.** Ollama
   does not load a second copy of a model it already has resident; concurrency
   there is ``OLLAMA_NUM_PARALLEL`` slots against the *one* copy, whose KV cache
   was already sized for them by ``scripts/sync-ollama-models.py``. Distinct
   models each need their own residency, so those are bounded by VRAM instead.
   Collapsing the two into a single "max concurrent local subagents" number gets
   one of the cases wrong whichever number is chosen.
2. **Strict FIFO, and a model bigger than the card runs alone.** Admitting a
   small model past a waiting large one raises throughput and starves the large
   one indefinitely, which is the failure this gate exists to prevent, not a
   tuning opportunity. A model whose footprint exceeds VRAM (Ollama offloads
   layers to system RAM) can never satisfy the ledger, so it is admitted when
   the ledger is otherwise empty rather than never.
3. **Unknown means ungated.** No ``ollama.vram_gb``, a hosted model, a model
   with no ``size_bytes`` — every one of those yields "no opinion", and no
   opinion means the dispatch proceeds exactly as it did before this module
   existed. A gate that guesses a footprint would serialize work for no reason
   on the deployments that gave it the least information.

The ComfyUI arbiter (``community/comfyui/arbiter.py``) solves the neighbouring
problem and deliberately does the opposite thing: it re-reads residency from the
services on every acquire, because a diffusion model's residency is owned by
another process and cannot be known in-process. This gate arbitrates *this
process's own* dispatches against numbers the sync already measured, so its
bookkeeping is authoritative and it does not put an HTTP round trip in front of
every subagent.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from deerflow.config.subagent_runtime_config import LocalModelCapacityConfig
from deerflow.subagents.capacity import SubagentCapacityTimeout

logger = logging.getLogger(__name__)

GIB = 1024**3

# Mirrors VRAM_OVERHEAD_BYTES in scripts/sync-ollama-models.py: CUDA context,
# the compositor, and the daemon's own allocations are not available to models,
# and the sizing that produced these footprints already subtracted the same
# amount. Divergence here would make the gate disagree with the num_ctx it is
# reading.
VRAM_OVERHEAD_BYTES = int(1.5 * GIB)

# The provider class the sync writes for every local entry. Matched on the class
# name so a `use:` written with either separator (`module:Class`, `module.Class`)
# resolves the same way.
_OLLAMA_CHAT_CLASS = "ChatOllama"


class LocalModelResidencyTimeout(SubagentCapacityTimeout):
    """A subagent waited for GPU residency past the configured deadline.

    Subclasses the capacity timeout on purpose: the executor already turns a
    ``SubagentCapacityError`` into a failed result flagged ``admission_failure``,
    and a wait for the GPU is the same kind of event as a wait for a process
    slot — it must not look like the subagent's own work failed.
    """


@dataclass(frozen=True)
class LocalModelProfile:
    """What one configured local model costs, and how many callers it serves."""

    config_name: str
    daemon_model: str
    footprint_bytes: int
    parallel_slots: int
    # True when only the weights were known, so the KV cache is missing from the
    # figure. Reported rather than hidden: the answer is still better than no
    # limit at all, but it under-counts, and re-running the sync fixes it.
    weights_only: bool = False


@dataclass(frozen=True)
class LocalResidencyPlan:
    """The card, the models that may sit on it, and how long to wait for a seat."""

    vram_bytes: int
    profiles: Mapping[str, LocalModelProfile]
    # Seconds, as ``asyncio.wait_for`` takes them. The config field is an int;
    # the float here is what lets a test express a sub-second deadline without
    # reaching into the gate's internals.
    queue_timeout_seconds: float = 1800

    def profile_for(self, model_name: str | None) -> LocalModelProfile | None:
        if not model_name:
            return None
        return self.profiles.get(model_name)


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_ollama_model(model: object) -> bool:
    use = getattr(model, "use", None)
    if not isinstance(use, str):
        return False
    return use.rsplit(":", 1)[-1].rsplit(".", 1)[-1] == _OLLAMA_CHAT_CLASS


def model_footprint_bytes(model: object, *, num_parallel: int) -> tuple[int, bool] | None:
    """Resident VRAM one copy of this model occupies: weights plus its KV cache.

    Returns ``(bytes, weights_only)``, or None when even the weights are
    unknown. ``num_ctx`` is preferred over ``context_window`` because it is the
    number actually sent to the daemon; they are written together and equal by
    the sync, but a hand-edited entry can disagree and the daemon follows
    ``num_ctx``.
    """
    weights = _positive_int(getattr(model, "size_bytes", None))
    if weights is None:
        return None
    extra = getattr(model, "model_extra", None) or {}
    num_ctx = _positive_int(extra.get("num_ctx")) or _positive_int(getattr(model, "context_window", None))
    kv_per_token = getattr(model, "kv_bytes_per_token", None)
    try:
        kv_per_token = float(kv_per_token) if kv_per_token is not None else None
    except (TypeError, ValueError):
        kv_per_token = None
    if num_ctx is None or kv_per_token is None or kv_per_token <= 0:
        return weights, True
    return weights + int(kv_per_token * num_ctx * max(1, num_parallel)), False


def build_local_residency_plan(app_config: object) -> LocalResidencyPlan | None:
    """Build the plan from a config snapshot, or None when there is no opinion.

    None is returned — meaning "do not gate anything" — when the feature is off,
    when the GPU budget is unknown, or when no configured model is both served by
    Ollama and carries a weight size. Those are the states in which any limit
    this module could produce would be invented rather than measured.
    """
    runtime = getattr(app_config, "subagent_runtime", None)
    settings = getattr(runtime, "local_model_capacity", None)
    if not isinstance(settings, LocalModelCapacityConfig) or not settings.enabled:
        return None

    ollama = getattr(app_config, "ollama", None)
    vram_gb = getattr(ollama, "vram_gb", None)
    try:
        vram_bytes = int(float(vram_gb) * GIB) - VRAM_OVERHEAD_BYTES
    except (TypeError, ValueError):
        return None
    if vram_bytes <= 0:
        return None

    num_parallel = _positive_int(getattr(ollama, "num_parallel", None)) or 1
    models: Iterable[object] = getattr(app_config, "models", None) or []

    # Two config entries may alias one pulled model (a second entry with a
    # different num_ctx, say). The daemon loads it once, so residency is keyed by
    # the daemon-side name and costed at the largest footprint any alias claims —
    # under-costing it would let the ledger admit a load that does not fit.
    footprints: dict[str, int] = {}
    weights_only: dict[str, bool] = {}
    aliases: list[tuple[str, str]] = []
    for model in models:
        if not _is_ollama_model(model):
            continue
        config_name = getattr(model, "name", None)
        daemon_model = getattr(model, "model", None) or config_name
        if not isinstance(config_name, str) or not isinstance(daemon_model, str):
            continue
        costed = model_footprint_bytes(model, num_parallel=num_parallel)
        if costed is None:
            continue
        footprint, estimated = costed
        if footprint > footprints.get(daemon_model, 0):
            footprints[daemon_model] = footprint
            weights_only[daemon_model] = estimated
        aliases.append((config_name, daemon_model))

    profiles = {
        config_name: LocalModelProfile(
            config_name=config_name,
            daemon_model=daemon_model,
            footprint_bytes=footprints[daemon_model],
            parallel_slots=num_parallel,
            weights_only=weights_only[daemon_model],
        )
        for config_name, daemon_model in aliases
    }
    if not profiles:
        return None

    estimated = sorted(name for name, footprint in weights_only.items() if footprint)
    if estimated:
        # The one state worth a startup line: these models are costed at their
        # weights alone, so the ledger under-counts them and admits more than
        # the card really holds. Re-running the sync writes the missing
        # `kv_bytes_per_token` and the number becomes exact.
        logger.info(
            "Subagent GPU residency: %s costed at weights only (no kv_bytes_per_token); re-run scripts/sync-ollama-models.py for an exact footprint",
            ", ".join(estimated),
        )
    logger.debug("Subagent GPU residency planned: %.1f GiB usable, %d local model(s), %d slot(s) each", vram_bytes / GIB, len(footprints), num_parallel)

    return LocalResidencyPlan(
        vram_bytes=vram_bytes,
        profiles=profiles,
        queue_timeout_seconds=settings.queue_timeout_seconds,
    )


@dataclass
class _Waiter:
    profile: LocalModelProfile
    future: asyncio.Future[None]


@dataclass(frozen=True)
class LocalResidencySnapshot:
    vram_bytes: int
    reserved_bytes: int
    running: Mapping[str, int]
    queued: int


@dataclass
class _Residency:
    reserved_bytes: int
    running: int = 0


class LocalModelResidencyGate:
    """Admits a local-model dispatch only when the GPU can actually hold it."""

    def __init__(self, plan: LocalResidencyPlan) -> None:
        self._plan = plan
        self._lock = asyncio.Lock()
        self._resident: dict[str, _Residency] = {}
        self._waiters: deque[_Waiter] = deque()

    @property
    def plan(self) -> LocalResidencyPlan:
        return self._plan

    def snapshot(self) -> LocalResidencySnapshot:
        # ``list(dict.items())`` and ``len(deque)`` are single C-level calls, so
        # a reader on another thread cannot catch the loop thread mid-mutation;
        # iterating the live mapping could raise "dict changed size during
        # iteration". Same reasoning as the note in capacity.py.
        resident = list(self._resident.items())
        return LocalResidencySnapshot(
            vram_bytes=self._plan.vram_bytes,
            reserved_bytes=sum(entry.reserved_bytes for _, entry in resident),
            running={name: entry.running for name, entry in resident},
            queued=len(self._waiters),
        )

    def _required_bytes(self, profile: LocalModelProfile) -> int:
        # A model that does not fit the card is not un-runnable — Ollama offloads
        # layers to system RAM and answers slowly (FORK.md §30). Charging it the
        # whole card is what makes it run alone instead of never.
        return min(profile.footprint_bytes, self._plan.vram_bytes)

    def _can_admit(self, profile: LocalModelProfile) -> bool:
        entry = self._resident.get(profile.daemon_model)
        if entry is not None:
            # Already loaded: the question is slots on the existing copy, not
            # VRAM. A second copy is never loaded, so VRAM cannot be the answer.
            return entry.running < profile.parallel_slots
        used = sum(current.reserved_bytes for current in self._resident.values())
        return used + self._required_bytes(profile) <= self._plan.vram_bytes

    def _admit_locked(self, profile: LocalModelProfile) -> None:
        entry = self._resident.get(profile.daemon_model)
        if entry is None:
            entry = _Residency(reserved_bytes=self._required_bytes(profile))
            self._resident[profile.daemon_model] = entry
        entry.running += 1

    def _release_locked(self, profile: LocalModelProfile) -> None:
        entry = self._resident.get(profile.daemon_model)
        if entry is None:
            raise RuntimeError(f"Local residency released for {profile.daemon_model} without an owner")
        entry.running -= 1
        if entry.running <= 0:
            del self._resident[profile.daemon_model]
        self._drain_locked()

    def _drain_locked(self) -> None:
        """Admit waiters from the head while the head itself can be admitted.

        Strictly in order. Stopping at the first waiter that does not fit is the
        anti-starvation property: skipping it to admit a smaller model behind it
        is precisely how a large model waits forever on a busy card.
        """
        while self._waiters:
            head = self._waiters[0]
            if head.future.done():
                self._waiters.popleft()
                continue
            if not self._can_admit(head.profile):
                return
            self._waiters.popleft()
            self._admit_locked(head.profile)
            head.future.set_result(None)

    async def _acquire(self, profile: LocalModelProfile) -> None:
        waiter: _Waiter | None = None
        async with self._lock:
            if not self._waiters and self._can_admit(profile):
                self._admit_locked(profile)
                return
            waiter = _Waiter(profile=profile, future=asyncio.get_running_loop().create_future())
            self._waiters.append(waiter)

        try:
            await asyncio.wait_for(waiter.future, timeout=self._plan.queue_timeout_seconds)
        except (TimeoutError, asyncio.CancelledError) as exc:
            async with self._lock:
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    # A drain admitted this waiter as the deadline fired. The
                    # admission is real and this caller owns it, so it has to be
                    # given back before the failure is reported.
                    if waiter.future.done() and not waiter.future.cancelled():
                        self._release_locked(profile)
                else:
                    # Removing a waiter can unblock the one behind it.
                    self._drain_locked()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise LocalModelResidencyTimeout(f"Timed out after {self._plan.queue_timeout_seconds}s waiting for GPU residency for '{profile.config_name}' on the local Ollama daemon") from exc

    async def _release(self, profile: LocalModelProfile) -> None:
        async with self._lock:
            self._release_locked(profile)

    @asynccontextmanager
    async def slot(self, model_name: str | None) -> AsyncIterator[LocalModelProfile | None]:
        """Hold GPU residency for the duration of the block, when it applies."""
        profile = self._plan.profile_for(model_name)
        if profile is None:
            yield None
            return
        await self._acquire(profile)
        try:
            yield profile
        finally:
            await self._release(profile)


@dataclass
class _GateState:
    plan: LocalResidencyPlan | None = None
    gate: LocalModelResidencyGate | None = None
    loop: asyncio.AbstractEventLoop | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _GateState()


def configure_subagent_local_residency(plan: LocalResidencyPlan | None) -> None:
    """Install the process-wide plan. Application startup calls this once."""
    with _state.lock:
        if _state.plan == plan:
            return
        _state.plan = plan
        _state.gate = None
        _state.loop = None


def get_subagent_local_residency_gate() -> LocalModelResidencyGate | None:
    """Return the gate bound to the running loop, or None when unconfigured."""
    loop = asyncio.get_running_loop()
    with _state.lock:
        if _state.plan is None:
            return None
        if _state.gate is not None and _state.loop is not loop:
            snapshot = _state.gate.snapshot()
            if snapshot.running or snapshot.queued:
                # The waiters hold futures bound to the old loop. Rebinding here
                # would silently drop a live ledger and leave those awaits
                # unresolvable, so it is an error rather than a recovery — the
                # same rule capacity.py applies to its own controller.
                raise RuntimeError("Subagent GPU residency cannot move event loops while dispatches are in flight")
            _state.gate = None
        if _state.gate is None:
            # Native subagents run on a persistent isolated loop; direct async
            # callers and tests may legitimately arrive on a new one once the
            # previous idle loop has closed.
            _state.gate = LocalModelResidencyGate(_state.plan)
            _state.loop = loop
        return _state.gate


def reset_subagent_local_residency() -> None:
    """Drop the configured plan. For tests and for a full config reload."""
    configure_subagent_local_residency(None)
