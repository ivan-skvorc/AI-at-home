"""Fork feature. The local Ollama daemon's settings, read at runtime.

`make setup` writes the top-level `ollama:` block and
`scripts/sync-ollama-models.py` sizes every local model's `num_ctx` against it,
but until the subagent residency gate nothing in the *running* Gateway read it
back: the numbers described the GPU at sync time and were never consulted at
dispatch time. `deerflow/subagents/local_residency.py` is the first runtime
reader, which is why the section is typed here instead of being left to
``AppConfig``'s ``extra="allow"``.

Every field is optional and every default is the "nothing configured" answer, so
a deployment with no GPU (or no `ollama:` block at all) parses to a config that
turns the gate off rather than to a validation error.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KV_CACHE_BYTES_PER_ELEMENT: dict[str, float] = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}


class OllamaConfig(BaseModel):
    """Mirror of the `ollama:` block that `make setup` and the sync script own."""

    model_config = ConfigDict(extra="allow")

    vram_gb: float | None = Field(
        default=None,
        gt=0,
        description="GPU memory budget in GiB, summed across cards. Unset means the GPU size is unknown, which disables every VRAM-derived behavior rather than guessing one.",
    )
    system_ram_gb: float | None = Field(
        default=None,
        gt=0,
        description="System RAM in GiB that Ollama's offloaded layers spill into. Warn-only; it never reassigns a model choice.",
    )
    kv_cache_type: Literal["f16", "q8_0", "q4_0"] = Field(
        default="f16",
        description="KV-cache quantization the sizing assumes. Must match the daemon's OLLAMA_KV_CACHE_TYPE to be accurate.",
    )
    num_parallel: int = Field(
        default=1,
        ge=1,
        le=64,
        description=(
            "The daemon's OLLAMA_NUM_PARALLEL: how many requests one loaded copy of a model serves at once. Ollama allocates a KV cache per slot up front, so this both divides the sized "
            "`num_ctx` and is the real ceiling on how many subagents can share one resident model."
        ),
    )
    keep_alive: str | None = Field(
        default=None,
        description="How long the daemon keeps each model resident (e.g. `30m`, `-1` for never unload). Passed to Ollama verbatim; unset leaves its own 5-minute default.",
    )
    preload: bool = Field(
        default=False,
        description="Warm `models[0]` at launch so the first turn is not a cold start.",
    )
    keep_alive_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Per-model `keep_alive`, winning over the global value above.",
    )
