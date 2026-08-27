"""Local media generation (ComfyUI) configuration — fork feature.

Text inference in this fork already has a free local tier (Ollama, auto-synced,
priced at zero). Images and video did not: both bundled media skills call
MiniMax or Gemini over HTTPS, so every picture cost money and every prompt left
the house. This section configures the local alternative — a ComfyUI service on
the same machine, driven by Gateway-side tools.

Three groups of knobs live here:

* ``comfyui`` — how to reach the service and how long to wait. Image and video
  carry **separate** timeouts on purpose: a clip is minutes, an image is
  seconds, and a single shared timeout would either abandon working video runs
  or let a wedged image run hold the GPU for half an hour.
* ``image`` / ``video`` / ``refine`` — generation defaults and the iteration
  caps the *server* enforces (a model asked to count its own iterations loses
  count; see :mod:`deerflow.community.comfyui.sessions`).
* ``gpu`` — the residency arbiter. A language model and a diffusion model share
  one card that usually cannot hold both, and the failure is silent: Ollama
  does not error when weights do not fit, it offloads layers to system RAM and
  runs several times slower. ``policy: auto`` derives exclusive/shared from the
  budget rather than making a GPU upgrade a code change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ComfyUIServiceConfig(BaseModel):
    """How the Gateway reaches the ComfyUI service."""

    base_url: str = Field(default="http://localhost:8188", description="ComfyUI HTTP endpoint. DEER_FLOW_COMFYUI_BASE_URL overrides it (set in-network by the Docker stacks).")
    allow_private_addresses: bool = Field(
        default=True,
        description=("SSRF opt-out for the shared URL guard. A loopback / LAN ComfyUI is the intentional-internal-target case, so this defaults to true here (unlike web tools). Set false when base_url points at a public host."),
    )
    request_timeout: float = Field(default=30.0, gt=0, description="Timeout (seconds) for individual ComfyUI HTTP calls (submit, history poll, view, object_info).")
    poll_interval: float = Field(default=1.5, gt=0, description="Seconds between /history polls while a prompt is running.")
    image_timeout: float = Field(default=600.0, gt=0, description="Wall-clock cap (seconds) for one image generation, measured from submit to output.")
    video_timeout: float = Field(default=2400.0, gt=0, description="Wall-clock cap (seconds) for one video generation. Deliberately its own value: a clip is minutes, not seconds.")


class ImageDefaultsConfig(BaseModel):
    """Defaults for ``generate_image`` so a bare 'make me a picture' needs no model reasoning."""

    template: str = Field(default="txt2img", description="Workflow template name under the tool package's templates/ directory.")
    width: int = Field(default=1024, gt=0, description="Default image width in pixels.")
    height: int = Field(default=1024, gt=0, description="Default image height in pixels.")
    steps: int = Field(default=25, gt=0, description="Default sampler steps.")
    cfg: float = Field(default=6.0, gt=0, description="Default classifier-free guidance scale.")
    sampler: str = Field(default="euler", description="Default sampler name (must exist in the ComfyUI build's KSampler enum).")
    scheduler: str = Field(default="normal", description="Default scheduler name.")
    negative_prompt: str = Field(default="", description="Default negative prompt applied when the caller does not pass one.")


class VideoDefaultsConfig(BaseModel):
    """Defaults for ``generate_video``, sized for what a 24 GB consumer card actually runs."""

    template: str = Field(default="txt2video", description="Workflow template name under the tool package's templates/ directory. Switch to 'txt2video-gguf' for a GGUF-quantized UNet (needs the ComfyUI-GGUF custom node).")
    unet: str | None = Field(default=None, description="Diffusion model file for the video template. Unset resolves the first one ComfyUI reports for that loader node.")
    clip: str | None = Field(default=None, description="Text encoder file for the video template. Unset resolves the first one ComfyUI reports.")
    vae: str | None = Field(default=None, description="VAE file for the video template. Unset resolves the first one ComfyUI reports.")
    width: int = Field(default=832, gt=0, description="Default clip width in pixels.")
    height: int = Field(default=480, gt=0, description="Default clip height in pixels.")
    frames: int = Field(default=49, gt=0, description="Default frame count. 49 frames at 16 fps is ~3 seconds.")
    fps: int = Field(default=16, gt=0, description="Default frames per second for the assembled clip.")
    steps: int = Field(default=20, gt=0, description="Default sampler steps.")
    cfg: float = Field(default=6.0, gt=0, description="Default guidance scale.")
    contact_sheet_columns: int = Field(default=3, gt=0, description="Columns in the contact-sheet PNG the critic looks at.")
    contact_sheet_stills: int = Field(default=6, gt=1, description="How many evenly spaced stills are extracted and tiled into the contact sheet.")
    contact_sheet_tile_width: int = Field(default=480, gt=0, description="Width each still is scaled to inside the contact sheet.")


class RefineConfig(BaseModel):
    """Caps for the self-critiquing generation loop, enforced server-side."""

    max_iterations: int = Field(default=4, gt=0, description="Hard cap on generations per refine session. The counter lives on the server; iteration N+1 is refused with a message the agent can report.")
    budget_seconds: float = Field(default=1800.0, gt=0, description="Wall-clock budget per refine session, from the first iteration.")
    min_criteria: int = Field(default=3, gt=0, description="Fewest criteria a session may freeze. Fewer than this and 'is it good?' has no checkable answer.")
    max_criteria: int = Field(default=6, gt=0, description="Most criteria a session may freeze. More than this and no iteration can ever pass them all.")

    @model_validator(mode="after")
    def _validate_criteria_range(self) -> RefineConfig:
        if self.min_criteria > self.max_criteria:
            raise ValueError(f"media.refine.min_criteria ({self.min_criteria}) is above max_criteria ({self.max_criteria}), so no session can ever start")
        return self


class GpuTenantConfig(BaseModel):
    """One consumer of the GPU.

    ``location`` is what removes the cloud special case: a cloud tenant is
    simply never resident, so every eviction against it is a no-op without a
    code path of its own.
    """

    name: str = Field(..., min_length=1, description="Tenant name, used in logs and in the arbiter's decision reasoning.")
    location: Literal["local", "cloud"] = Field(default="local", description="'local' tenants hold VRAM on this machine; 'cloud' tenants never do and are skipped by the arbiter.")
    kind: Literal["ollama", "comfyui"] | None = Field(default=None, description="Eviction mechanism: 'ollama' (per-request keep_alive: 0) or 'comfyui' (POST /free). Required for local tenants.")
    base_url: str | None = Field(default=None, description="Service endpoint used for the residency probe and the eviction call. Defaults per kind when unset.")
    estimate_gb: float = Field(default=0.0, ge=0, description="Approximate VRAM this tenant needs, in GiB. 0 means unknown, which makes a computed policy fall back to 'exclusive'.")

    @model_validator(mode="after")
    def _validate_local_has_kind(self) -> GpuTenantConfig:
        if self.location == "local" and self.kind is None:
            raise ValueError(f"media.gpu tenant '{self.name}' is local but declares no kind; set kind: ollama or kind: comfyui so the arbiter knows how to evict it")
        return self


class GpuArbiterConfig(BaseModel):
    """GPU residency policy for the local tenants that share one card."""

    enabled: bool = Field(default=True, description="Whether generation acquires the GPU through the arbiter. Disabling it keeps the acquire/generate/release lifecycle but makes every eviction a no-op.")
    budget_gb: float | Literal["auto"] = Field(default="auto", description="GPU memory budget in GiB. 'auto' detects it the same way the setup wizard does (nvidia-smi / rocm-smi / Apple unified memory).")
    reserve_gb: float = Field(default=1.0, ge=0, description="Headroom held back from the budget for the desktop, KV cache growth and allocator slack.")
    policy: Literal["auto", "exclusive", "shared", "none"] = Field(
        default="auto",
        description=(
            "'auto' computes exclusive/shared from budget_gb - reserve_gb against the sum of local tenant estimates and logs the reasoning "
            "(so a bigger card resolves to 'shared' on its own); 'exclusive' always swaps; 'shared' never evicts; 'none' disables arbitration."
        ),
    )
    wait_timeout_seconds: float = Field(default=900.0, gt=0, description="How long a generation waits for the GPU semaphore before giving up with an honest message instead of queueing forever.")
    tenants: list[GpuTenantConfig] = Field(
        default_factory=lambda: [
            GpuTenantConfig(name="ollama", location="local", kind="ollama", base_url="http://localhost:11434"),
            GpuTenantConfig(name="comfyui", location="local", kind="comfyui"),
        ],
        description="The card's tenants. Defaults describe the fork's own pairing: a local Ollama daemon and the local ComfyUI service.",
    )


class MediaConfig(BaseModel):
    """Local image and video generation (fork feature)."""

    default_checkpoint: str | None = Field(
        default=None,
        description="Checkpoint used when a request names none. Unset resolves the first checkpoint ComfyUI reports from /object_info, so a fresh install still generates.",
    )
    comfyui: ComfyUIServiceConfig = Field(default_factory=ComfyUIServiceConfig, description="ComfyUI service endpoint and timeouts.")
    image: ImageDefaultsConfig = Field(default_factory=ImageDefaultsConfig, description="Image generation defaults.")
    video: VideoDefaultsConfig = Field(default_factory=VideoDefaultsConfig, description="Video generation defaults, including the contact sheet the critic judges.")
    refine: RefineConfig = Field(default_factory=RefineConfig, description="Self-critiquing loop caps, enforced at the tool boundary.")
    gpu: GpuArbiterConfig = Field(default_factory=GpuArbiterConfig, description="GPU residency arbiter settings.")
