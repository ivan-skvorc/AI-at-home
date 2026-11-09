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

Settings → Models can also store the GPU memory (``ollama_vram_gb`` in
``runtime_settings.json`` under the DeerFlow home). It lives outside
``config.yaml`` on purpose: a config upgrade or the launch sync can never
rewrite it, and it wins over ``ollama.vram_gb`` while it is set. The sync reads
the same key; :func:`effective_vram_gb` is the runtime's reader.
"""

import logging
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from deerflow.config.runtime_settings import get_runtime_setting, set_runtime_setting

logger = logging.getLogger(__name__)

#: Key in ``runtime_settings.json``. ``scripts/sync-ollama-models.py`` names it too.
VRAM_GB_SETTING_KEY = "ollama_vram_gb"
#: Upper bound on a saved value: a typo, not a card, beyond this.
MAX_VRAM_GB = 1024.0

KV_CACHE_BYTES_PER_ELEMENT: dict[str, float] = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}


class OllamaConfig(BaseModel):
    """Mirror of the `ollama:` block that `make setup` and the sync script own."""

    model_config = ConfigDict(extra="allow")

    vram_gb: float | None = Field(
        default=None,
        ge=0,
        description=(
            "GPU memory budget in GiB, summed across cards. Unset: the launch sync detects a local dedicated GPU for context sizing, and every runtime VRAM-derived behavior "
            "stays off rather than guessing. 0: GPU sizing off everywhere (the sync keeps its flat 32768 cap)."
        ),
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


def get_saved_vram_gb() -> float | None:
    """The GPU memory Settings → Models saved, or None when it saved none.

    A hand-edited value that is not a number in ``[0, MAX_VRAM_GB]`` is ignored
    (and logged) so ``config.yaml`` applies, rather than sizing from garbage.
    """
    raw = get_runtime_setting(VRAM_GB_SETTING_KEY)
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= MAX_VRAM_GB:
        logger.error("runtime_settings: ignoring invalid %s; config.yaml applies", VRAM_GB_SETTING_KEY)
        return None
    return float(raw)


def set_saved_vram_gb(value: float | None) -> float | None:
    """Persist the GPU memory (None removes it, so config.yaml applies again)."""
    set_runtime_setting(VRAM_GB_SETTING_KEY, None if value is None else float(value))
    return get_saved_vram_gb()


def effective_vram_gb(configured: float | None) -> float | None:
    """The budget to size against: the saved Settings value, else ``ollama.vram_gb``."""
    saved = get_saved_vram_gb()
    return configured if saved is None else saved
