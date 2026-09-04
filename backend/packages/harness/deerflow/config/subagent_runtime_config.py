"""Startup-only process capacity for native subagent execution."""

from typing import Literal

from pydantic import BaseModel, Field


class LocalModelCapacityConfig(BaseModel):
    """Fork feature. Gate concurrent subagents by what the local GPU can hold.

    ``max_running`` above is a process-wide number chosen once, at startup, with
    no idea which model a subagent will run on. That is the right shape for a
    hosted model and the wrong one for a local one: three subagents on a model
    that fits the card once do not run three times faster, they queue inside the
    daemon where the Gateway cannot see them while their own timeouts run down.
    This gate re-asks the question per dispatch, against the numbers
    ``scripts/sync-ollama-models.py`` already wrote into `config.yaml`.
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Whether local-model dispatches wait for GPU residency before they run. On by default because it only ever engages when a model is served by Ollama AND `ollama.vram_gb` is set AND the "
            "model carries the sizing metadata the sync writes; anything else stays ungated."
        ),
    )
    queue_timeout_seconds: int = Field(
        default=1800,
        ge=1,
        le=86_400,
        description=(
            "Maximum wait for GPU residency before a subagent fails admission. Deliberately far longer than `queue_timeout_seconds` above: that one bounds a wait for a *process* slot, while this "
            "one bounds a wait for work that is deliberately serialized, so the last of five sequential subagents must not time out just for being fifth."
        ),
    )


class SubagentRuntimeConfig(BaseModel):
    """Process-local admission and execution limits shared by all subagents."""

    max_running: int = Field(
        default=3,
        ge=1,
        le=64,
        description="Maximum native subagents that may execute concurrently in one Gateway process.",
    )
    max_queued: int = Field(
        default=64,
        ge=0,
        le=10_000,
        description="Maximum native subagents waiting for a process execution slot.",
    )
    admission_policy: Literal["queue", "reject"] = Field(
        default="queue",
        description="Whether a full execution pool queues work or rejects it immediately.",
    )
    queue_timeout_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        description="Maximum wait for a queued native subagent before it fails admission.",
    )
    local_model_capacity: LocalModelCapacityConfig = Field(
        default_factory=LocalModelCapacityConfig,
        description="Fork feature. GPU-residency admission for subagents running on a local Ollama model.",
    )
