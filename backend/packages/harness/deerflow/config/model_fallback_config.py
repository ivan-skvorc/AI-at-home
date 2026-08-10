"""Global model fallback chain (fork feature).

Per-model ``fallback:`` lists live on :class:`ModelConfig`. This section is the
default for models that declare none — the common shape being "every local model
falls back to one cheap cloud model", which would otherwise have to be repeated
on every entry the Ollama sync regenerates (and would be wiped on the next sync,
since that block is machine-owned).

Off by default, consistent with how this fork treats anything that changes agent
behavior.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelFallbackConfig(BaseModel):
    """Default fallback chain applied to models that declare no ``fallback:``."""

    enabled: bool = Field(default=False, description="Whether the global fallback chain applies. Off by default; a per-model `fallback:` works regardless of this switch.")
    chain: list[str] = Field(
        default_factory=list,
        description=("Ordered model names to try when a model with no per-model `fallback:` fails with a recoverable provider error. The failing model is always removed from its own chain, so listing it here is harmless."),
    )
