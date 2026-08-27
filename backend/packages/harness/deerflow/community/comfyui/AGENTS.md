### Local Media Generation (`packages/harness/deerflow/community/comfyui/`)

Fork feature (roadmap items 12–15): images and short video clips rendered by a
diffusion model on the operator's own GPU, through a long-lived ComfyUI
service. No API key, no network egress, free at the margin. Read this before
changing anything here — several properties below are **silent when broken**.

Tools (config `group: media`, all commented out in `config.example.yaml`
because a fresh machine has neither ComfyUI nor a checkpoint):
`list_media_models`, `generate_image`, `generate_video`, `refine_start`,
`refine_verdict`.

Module map: `client.py` (HTTP transport only) · `templates.py` (typed params →
API-format graph, plus validation) · `templates/*.json` (the graphs) ·
`service.py` (config/env resolution, URL guard, model resolution, output
writing) · `arbiter.py` (GPU residency) · `sessions.py` (refine bookkeeping) ·
`frames.py` (stills + contact sheet) · `tools.py` (agent contract).

**Gateway-process, not sandbox.** These tools write straight to the host-side
thread outputs directory (`runtime.state["thread_data"]["outputs_path"]`), the
same path `present_files` normalizes against. That is what keeps them correct
under every sandbox mode — local, local-container, remote AIO — and it keeps
the process-wide GPU semaphore on the same side of the wall as the code that
generates. Do not move this into a skill script.

**The model never authors graph JSON.** Templates plus typed parameters, always.
A model that can emit arbitrary node graphs can load arbitrary files and run
arbitrary custom nodes on the machine holding the GPU. `patch_graph` refuses a
parameter the template does not bind rather than ignoring it — a silently
dropped seed makes an iteration loop unreadable.

**Templates are validated against `/object_info`, and the failure names the
node.** API-format graphs address nodes by numeric id, so a custom-node update
or a renamed input invalidates a template while ComfyUI's own complaint is a
validation dump. Validation runs at *first use per (base_url, template)* and is
cached (`service.reset_validation_cache()` in tests) rather than at Gateway
startup: ComfyUI is usually not up when the Gateway boots, and a startup check
that cannot reach the service checks nothing. `make doctor` runs the reachable
version of the same idea.

**Model files come from the build's own enums.** `CheckpointLoaderSimple.ckpt_name`
*is* the installed checkpoint list; same for `UNETLoader`/`CLIPLoader`/`VAELoader`.
Never hardcode a model name, and never invent one in a message — resolution
order is request → config → first installed.

**The submitted graph is saved beside every output** as `<name>.workflow.json`
(the `prompt` half only, so it opens in ComfyUI and reproduces the result). It
is the whole of "inspect how the nodes are set up"; do not drop it to save a
file write.

**Image and video carry separate timeouts** (`media.comfyui.image_timeout` /
`video_timeout`). A clip is minutes; a single shared timeout either abandons
working clips or lets a wedged image hold the GPU for half an hour. The video
tool is not bound by `sandbox.bash_command_timeout` — that is one of the reasons
it is a tool and not a skill script.

**Video is judged from a contact sheet, never from the MP4.** `view_image`
accepts png/jpg/webp/gif only, capped at 20 MB. The tool emits evenly spaced
stills *and* one tiled sheet; the sheet is one vision-token bill instead of six,
and temporal faults (flicker, morphing, identity drift) read far more clearly
side by side. `select_indices` includes both endpoints on purpose — identity
drift shows up at the ends. Pillow is imported lazily: a missing Pillow degrades
to "no contact sheet" with a named error and **must not** lose the clip.

#### GPU arbiter (`arbiter.py`)

- Eviction happens **inside the tool call**, never in the agent's plan: a turn
  is a chain of model calls, so the lead model reloads the moment a tool
  returns.
- **Verify, never assume**: residency is re-read per acquire (Ollama `/api/ps`,
  ComfyUI `/system_stats`, `nvidia-smi` as tiebreak). In-process bookkeeping
  cannot see a crashed Gateway's leftovers; the tiebreak is what recovers them.
- **Tenants, not special cases**: `location: cloud` is never resident, so a
  cloud lead makes every eviction a no-op with no branch of its own.
- Ollama eviction passes `keep_alive: 0` **per request**. Never set it globally —
  `ollama.keep_alive` exists to stop subagent cold starts in ordinary chat.
- `policy: auto` is *computed* from `budget_gb - reserve_gb` against the sum of
  local estimates and logged with its reasoning, so a bigger card resolves to
  `shared` on its own. `budget_gb: auto` reuses
  `scripts/wizard/steps/ollama.py::detect_vram_gb`; do not write a second
  detector.
- One depth-1 semaphore **per event loop**, process-wide. It serializes
  tenants, not callers; a caller that waits is told so.

#### Refine sessions (`sessions.py`)

The loop is the agent's (`skills/public/image-refine/`); only the bookkeeping is
here, because that is what a model loses track of: the frozen 3–6 criteria, the
server-held iteration counter (N+1 is *refused* with a reportable message), the
wall-clock budget measured from the first iteration, and the one-named-change
rule on a retry. The session JSON beside the outputs is the audit trail.
A failed generation still consumes its iteration — otherwise a loop that fails
every time never stops.

#### Tests

`tests/test_comfyui_tools.py`, `tests/test_gpu_arbiter.py`,
`tests/test_refine_session.py`, `tests/test_comfyui_video.py`,
`tests/test_detect_comfyui.py`, plus `TestCheckMediaGeneration` in
`tests/test_doctor.py`. Fakes live in `tests/_comfyui_helpers.py`, and the
`/object_info` fixture is derived from the template under test so a template
edit cannot silently invalidate its own validation tests.
