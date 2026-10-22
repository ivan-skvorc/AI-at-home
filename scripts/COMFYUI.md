# ComfyUI provisioning and model files

Split out of [`AGENTS.md`](AGENTS.md) to keep it within its guidance budget
(`scripts/check_agent_guidance.py`). Read it before changing
`detect_comfyui.py`, `comfyui.sh` or `comfyui_models.py`.

`detect_comfyui.py` answers two separate questions and must keep them separate.
`resolve()` is "which endpoint" and stays a pure function of the probes;
`autostart_decision()` is "may we provision one here", and depends on the
machine (Docker **and** a detected GPU, overridable in both directions with
`DEER_FLOW_COMFYUI_AUTOSTART`). The CLI prints `skip`, `external <url>`,
`bundled start`, or `bundled hold` — the launch scripts branch on those exact
words, and any failure must degrade to `bundled hold`, the branch that changes
nothing. `gpu_present()` reuses `wizard/steps/ollama.py::detect_vram_gb` rather
than adding a second detector.

`comfyui.sh` owns the container for every caller (launch scripts and
`make comfy-up` alike) under its own compose project, `deer-flow-comfyui`. It is
deliberately not a service of the main compose project: `deploy.sh` runs
`up --remove-orphans`, which would delete a container the passed compose files
do not mention. `up` is idempotent by inspection (`docker inspect` first) —
recreating a running instance evicts the model weights it is holding — and the
Docker launch paths call `attach <network>` afterwards so the gateway container
can resolve `http://deer-flow-comfyui:8188`.

`comfyui_models.py` installs model files into whichever instance is in use and
is stdlib-only (the root Makefile runs it with the system interpreter, not the
backend venv). For an external instance it resolves the models directory from
`--models-dir`, `DEER_FLOW_COMFYUI_EXTERNAL_MODELS`, that container's own
`…/models` mount, then well-known paths — and **refuses rather than falling back
to the bundled directory**, because a successful download into the ComfyUI the
Gateway is not talking to looks exactly like success.
