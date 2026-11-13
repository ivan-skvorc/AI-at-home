# Fork notes for the orchestration scripts

Split out of [`AGENTS.md`](AGENTS.md) to keep it within its guidance budget
(`scripts/check_agent_guidance.py`). The rules there are the entry point; this
is the detail behind them. ComfyUI provisioning has its own notes in
[COMFYUI.md](COMFYUI.md).

## Ollama model sync

`sync-ollama-models.py` runs on every launch path and owns only its marked
block. GPU sizing never writes a `num_ctx` below `MIN_AGENT_NUM_CTX` (32768),
the window `backend/tests/test_context_fit_critical.py` proves the agent fits.
KV cost counts only layers that keep a cache: a zero in a per-layer
`head_count_kv` is a linear-attention or state-space layer, not unreadable.
A GPU memory saved in Settings → Models (`ollama_vram_gb` in
`$DEER_FLOW_HOME/runtime_settings.json`, else `backend/.deer-flow/`) beats
`ollama.vram_gb`; only `--vram-gb` beats it. Keep its key and bounds equal to
`deerflow/config/ollama_config.py`. With no budget it sizes a loopback daemon from
`wizard/steps/ollama.py::detect_dedicated_vram_gb`; never add a second
detector. `vram_gb: 0` means off. Detection stays sync-only: the runtime
residency gate needs a configured budget. With no `OLLAMA_HOST`/`--host` and
no answer on localhost, it queries the host its managed entries point at;
never override a host the operator named.

## Config upgrade

`config-upgrade.sh` upgrades the file the Gateway loads by asking the harness
(`AppConfig.resolve_config_path`) rather than copying its lookup order. In this
fork the lookup is `config_upgrade.py --print-config-path` via
`backend-python.sh`, never `uv run`; without the harness (a Docker-only host)
it applies the same order by hand. An optional first argument names the project
root; `docker.sh start` passes its `PROJECT_ROOT`, so a launcher run against
another root never seeds or upgrades this checkout's config
(`test_compose_credentials_key.py`).
`backend/tests/test_config_version.py::test_config_upgrade_*` and
`test_config_upgrade_script.py::TestResolveConfigPath` pin this.
`serve.sh`, `deploy.sh` and `docker.sh` all run it before starting the
Gateway (the Docker two best-effort): `git pull` + restart is the documented
update, so a launcher that skips it strands new config. A migration's
`plugins_from_example` appends a bundled `plugins:` record once and never
touches one that matches it (`TestBundledPluginDelivery`).

## PyYAML-only scripts

Scripts that need only PyYAML (`config_upgrade.py`, `sandbox_toggle.py`) run
through `scripts/backend-python.sh`, never a bare `uv run`: it uses `uv run`
in `backend/` only when both uv and `backend/.venv` exist, else a host
`python3`/`python` that can import yaml, else it exits naming the fix (a
Docker-only host has no uv, and `uv run` without a venv installs the whole
backend). `make doctor` stays on uv — it imports `deerflow`.

## Dev stack ownership

The dev gateway runs as the invoking user (`DEER_FLOW_UID`/`DEER_FLOW_GID`,
`setpriv`); never add a compose `user:` to it or a default for those variables
(FORK.md, *Dev stack file ownership*).
