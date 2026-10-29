## Support Bundle Runtime Home

Thread manifests use a nonempty `DEER_FLOW_HOME` exclusively, resolving relative
values from the checkout like the local launcher. Read root `.env` path settings
without exporting secrets; dotenv overrides shell exports, including empty values.
Expand unquoted leading tildes, preserving quoted literals. If python-dotenv is
unavailable or `.env` cannot be read/decoded as UTF-8, retain shell/legacy lookup
so troubleshooting remains usable. Read the complete file before applying any
assignments so a decoding failure cannot partially override shell values.
Resolve `$NAME`, `${NAME}` and `${NAME:-literal}` in unquoted/double-quoted
values using a private environment with checkout `PWD` and earlier dotenv
assignments. Single-quoted values and escaped dollars stay literal. Parse the
file without sourcing it or executing command substitutions.
When home is unset and `DEER_FLOW_PROJECT_ROOT` is configured, search the launcher's
`backend/.deer-flow` first, then the standalone harness project root. Scan both
legacy threads and user-scoped threads in that root. With no override, retain
the two checkout layouts. Display an external home as `{DEER_FLOW_HOME}` rather
than its absolute host path, and never include file contents in the manifest.
Coverage lives in `backend/tests/test_support_bundle.py`.
This lookup follows the local launcher's root `.env`; it does not discover
`backend/.env` or `DEER_FLOW_ENV_FILE` used by standalone Gateway launches.
For those launches, export the effective `DEER_FLOW_HOME` when collecting a bundle
and ensure the checkout `.env` does not override it. Tests clear all three runtime
path variables and compare storage defaults with the launcher's actual shell blocks.

## Dependency and Label Checks

`check_extension.py`: Gateway wheel asset validator; example CI:
`extension-package-check.yml`. Tests: `backend/tests/test_extension_check_script.py`.

`check.py`: UTF-8 replacement decoding; pnpm uses
`PYTHONIOENCODING=utf-8:backslashreplace`. Preserve `make check` Unicode/exit
status in any locale. Tests: `backend/tests/test_check_script.py`.

`doctor.py`/`setup_wizard.py`: at `main` start, retain stdout encoding with
`errors="replace"`; guard `reconfigure` for embedded/captured streams.
Legacy-terminal/pipe tests: `backend/tests/test_setup_script_encoding.py`.

`sync_labels.py`: guard stdout/stderr `reconfigure` at `main` start. Retain
TTY encodings; intentionally force UTF-8 on redirects for CI logs. Both use
`errors="backslashreplace"`; decode `gh` output as UTF-8 with replacement.
Tests (stub `gh`/`yaml`, ASCII stdio): `backend/tests/test_sync_labels_script.py`.

`check_label_declarations.py`: stdlib-only; reject unsupported expressions.
Tests: `backend/tests/test_label_declarations.py`.

## Manual Claude OAuth Export

`export_claude_code_oauth.py` validates Keychain JSON as an object containing an
object `claudeAiOauth` and a nonblank string `accessToken` before any export action.
Malformed containers use the existing token-missing error without exposing their
contents. The loader returns the full container together with the validated token;
export actions use that token without repeating credential-shape assumptions or
trimming its contents. Offline CLI coverage:
`backend/tests/test_claude_keychain_export.py`.

## Service Startup Contracts

`serve.sh` reads `DEER_FLOW_GATEWAY_STARTUP_TIMEOUT` after root `.env` for
local Gateway port readiness (positive integer seconds, default 30). Reject
invalid values before cleanup/startup except `--stop`; keep frontend/nginx waits.
Launcher/wait-loop tests (processes, readiness and time stubbed):
`backend/tests/test_serve_gateway_startup_timeout.py`.

Both launchers call `sandbox-mode.sh` via Bash; keep it Bash/awk-only.
Dev passes `$PROJECT_ROOT/config.yaml`; prod passes `$DEER_FLOW_CONFIG_PATH`.
For AIO, omitted/blank/empty-quoted/YAML-null URLs (including comments) select
`aio`; preserve quoting so `"null"` and `"~"` remain nonempty strings.
This is not a general YAML parser or URL validator; aliases, multiline values
and environment expansion are out of scope. Offline helper and launcher tests:
`backend/tests/test_docker_sandbox_mode_detection.py`.

The setup wizard offers Webz.io as a news-only `web_search` provider using
`deerflow.community.webz.tools:web_search_tool` and `WEBZ_API_KEY`. Keep its
entry aligned with the credential check in `doctor.py` and the example config.
The adapter uses async HTTPS requests, offloads lazy config loading, and maps
`source` to provider `domain`; explicit `published_from` overrides recency.
Explicit `max_results` overrides the wizard's configured default; omission or
null uses configuration or 5. Reject boolean/fractional configured counts before
clamping to 1–100. `returned_results` is the normalized page size, not a match total.
Skip malformed page entries with index-only warnings; retain valid neighbors.
Reject malformed envelopes and nonempty pages with no valid entries, logging
no provider payloads or credentials. Contract tests live in `backend/tests/test_webz_tools.py`.

Optional browser dependency detection reads the top-level `tools:` sequence
without requiring `name` to be its first mapping key. Both indented and
indentless lists are supported; nested option names and block-scalar text
must not enable the browser extra. Keep the detector standard-library-only
because it runs before dependency synchronization. Read UTF-8 config files
with or without a leading BOM so the first section remains detectable.
`detect_uv_extras.py` checks an existing `DEER_FLOW_CONFIG_PATH` first, then
`DEER_FLOW_PROJECT_ROOT/config.yaml`, before the legacy checkout candidates.
Keep this lookup standard-library-only; test shadowing checkout configs and
the CLI under `python -S` in `backend/tests/test_detect_uv_extras.py`.
For Discord and Buzz, detect the provider extra when either legacy
`channels.<provider>.enabled` is true or both `channel_connections.enabled`
and `channel_connections.<provider>.enabled` are true. Keep these gates aligned
with `enabled_transport_providers()` in the channel service, including setup
wizard output. The provider set includes only channel providers declared in
`backend/pyproject.toml` under `[project.optional-dependencies]`; update it when
a channel gains or loses an extra. Providers whose SDKs are core dependencies
must not be added to this set. Nonempty `UV_EXTRAS` continues to override
config-derived extras.
`serve.sh`'s config-presence gate also accepts the project-root file when the
checkout has no config. `tests/test_serve_config_presence.py` runs the full
launcher through dependency detection with service operations stubbed.
`setup-sandbox.sh` also strips the leading BOM and normalizes CRLF before selecting the image;
keep its shell filter compatible with GNU and BSD sed.
An Apple Container pull that succeeds on macOS must not fail the setup step
just because Docker is absent. Keep the Docker pull when Docker is available,
including after an Apple Container failure, and retain the final image-config
note rather than exiting early on Apple Container success.

The root `PORT` value configures Docker's published nginx ingress only; local
orchestration pins Next.js to `3000`. Local runs bind the Gateway and Next.js to
`127.0.0.1`; `nginx-local-conf.sh` keeps nginx on loopback or, for a set
`BIND_HOST` (strict IP/hostname check), renders `temp/nginx.local.conf`
listening there. `serve.sh` resolves it before stopping anything, so a bad
value cannot tear down a running stack. Keep `dev.mjs`'s all-interfaces default: the Docker dev frontend needs
it. Runtime commands launch from the already
synchronized environment with `uv run --no-sync`. Production Compose probes
Gateway `/health`, and `deploy.sh` waits for all services before reporting
success; failures print Compose status and recent Gateway logs.

Both compose files mark `../.env` and `../frontend/.env` optional
(`path`/`required: false`, Compose 2.24+), so `make up`, `make down` and
`make prod-logs` on a fresh checkout neither abort nor create them; an
unreadable `.env` still fails. Do not seed them from the examples in
`deploy.sh` as `docker.sh start` does: `.env.example` holds placeholder API
keys the production Gateway would receive, and `make config` skips files that
exist. Pinned by `backend/tests/test_compose_default_bind_host.py` and
`backend/tests/test_gateway_startup.py`.

`docker.sh start` runs Compose from `docker/` without `--env-file`, so
dev-compose interpolation sees only the shell. `load_proxy_env_from_dotenv`
exports the `.env` keys interpolation needs (proxy variables and
`AUTH_TRUSTED_PROXIES`, whose `environment:` default would otherwise replace
the `env_file` value); shell exports still win. Pinned by
`backend/tests/test_compose_auth_trusted_proxies.py`.

`deploy.sh` never sources the repo-root `.env`; Compose reads it via
`--env-file`, and shell exports outrank that file during interpolation (an
exported-but-empty variable still wins). So `BETTER_AUTH_SECRET`,
`DEER_FLOW_INTERNAL_AUTH_TOKEN` and `DEER_FLOW_CREDENTIALS_KEY` resolve shell →
`.env` → persisted file under `DEER_FLOW_HOME` → freshly generated, and a
`.env`-provided value is left
unexported so Compose parses it itself. Whether `.env` provides one is
Compose's answer, not a `KEY=VALUE` grep: Compose also accepts `KEY: VALUE`
lines and interpolates `${VAR}` inside values, so the script renders a stub
project whose only environment entry is `${KEY}` through
`docker compose config` (same `--env-file`, stub on stdin, project directory
`docker/`) and reads the value back; `""` means empty or unset and falls
through to the persisted/generated secret. This works on every Compose v2
(the README floor is 2.24; `config --environment` would need 2.28), and a
failing probe stops the script rather than guessing. `read_dotenv_value`
stays for the end-of-run summary only. Do not export a value the script read
from `.env`: that shadows Compose's own dotenv parsing and re-creates the bug
where `make up` replaced the operator's secret with a generated one.
The credentials key (a Fernet key) persists as `.credentials_key`, the file the
Gateway itself generates in that runtime home, via a noclobber (`O_EXCL`)
create that reads a concurrent winner back.
`backend/tests/test_deploy_dotenv_secrets.py` pins the order and the probe;
its real-Compose cases run against the installed `docker` CLI and against any
standalone binaries listed in `DEER_FLOW_TEST_COMPOSE_BINARIES`.

Deployment commands check `DEER_FLOW_HOME` writability before setup and check
persisted secret readability only when shell/Compose dotenv overrides are absent.
Both failures identify the affected path and print the recursive ownership
recovery hint for the runtime home. Existing secrets are only read, so a
readable, read-only file is valid. `down` skips these checks and all secret
resolution/generation so permission damage cannot prevent teardown. Coverage:
`backend/tests/test_deploy_home_writability.py`.

`doctor.py` checks the config file the Gateway would load, not a fixed
`<checkout>/config.yaml`. It mirrors how `serve.sh` hands the two
config-location variables to the Gateway: `.env` values for
`DEER_FLOW_CONFIG_PATH` / `DEER_FLOW_PROJECT_ROOT` override the shell (other
keys stay shell-first), an unquoted leading `~` in them expands as `source`
does (a quoted one stays literal), and an unset or empty
`DEER_FLOW_PROJECT_ROOT` becomes the checkout. It then asks the harness
(`AppConfig.resolve_config_path`) instead of re-implementing its order. An
override the Gateway would reject (`DEER_FLOW_CONFIG_PATH` missing,
`DEER_FLOW_PROJECT_ROOT` not a directory) fails `config.yaml found` with the
Gateway's error, and the config-dependent checks skip. Any failure to import
the harness is reported, never raised: doctor diagnoses broken environments.
Pinned by `backend/tests/test_doctor.py::TestMainConfigResolution`.

Doctor screens Browserless fetch/capture and Crawl4AI, Firecrawl, and fastCRW
fetch backends with the runtime's `validate_delegated_backend_url`, before
provider success shortcuts. Keep endpoint defaults, `CRW_API_URL` precedence,
config environment resolution, and isolation acknowledgement coercion aligned
with those tools. `allow_private_addresses` affects targets only. Doctor reports
refused delegation with the deployment guide; it does not verify egress policies.
Offline coverage lives in `backend/tests/test_doctor.py`.

CLI credential JSON checks accept UTF-8 with or without a leading BOM, matching
the runtime credential loader. Keep `_load_json_object` on `utf-8-sig`; malformed
JSON and invalid encoding remain missing/invalid sources without exposing tokens.
Public doctor/runtime agreement is pinned by
`backend/tests/test_credential_file_encoding.py`.

Root `make install` runs pre-commit through uv, so uv's tool bin directory
need not be on `PATH`.

`config-upgrade.sh` upgrades the file the Gateway loads by asking the harness
(`AppConfig.resolve_config_path`) rather than copying its lookup order. It
defaults `DEER_FLOW_PROJECT_ROOT` to the checkout, as `serve.sh` does, so
`<checkout>/config.yaml` wins over a legacy `backend/config.yaml`. A missing
`DEER_FLOW_CONFIG_PATH` or invalid project root is an error, never a fallback.
Only "no config anywhere" creates `<checkout>/config.yaml` from the example.
Fork: the lookup is `config_upgrade.py --print-config-path` via
`backend-python.sh`, never `uv run`; without the harness (a Docker-only host)
it applies the same order by hand.
`backend/tests/test_config_version.py::test_config_upgrade_*` and
`test_config_upgrade_script.py::TestResolveConfigPath` pin this.

## ComfyUI Provisioning and Model Files

`detect_comfyui.py`, `comfyui.sh` and `comfyui_models.py` carry silent
contracts; read [COMFYUI.md](COMFYUI.md) before editing them.

## Multi-Instance Dev Harness

`dev_multi_instance.{sh,py}` must keep the rendered config passing the real
multi-instance gate and every endpoint/data root inside its state dir
(`backend/tests/test_dev_multi_instance_script.py`).
Unless `keep_channels` is requested, disable provider flags in both `channels`
and `channel_connections`; UI credentials can otherwise connect a bot
later. Preserve `channels.leader_lease` and connection metadata.
`--out` is a file path for `render-config`, `secrets` and `nginx-conf`; a
directory, or a file ancestor, is rejected before any write.

## Shell Script Invocation Contract

Root Makefile recipes must invoke repository `.sh` files through
`RUN_SHELL_SCRIPT`. On POSIX this expands to `$(BASH)`; on Windows it uses the
Git Bash wrapper. Shell scripts that invoke sibling repository scripts must
likewise prefix the target with `bash`. This keeps documented `make` commands
working when a source archive, `core.fileMode=false`, or a non-POSIX filesystem
does not preserve executable bits.

The Windows wrapper resolves `bash.exe` under the Git installation root, which
is the parent of `cmd/`, `bin/`, or `mingw64/bin/` depending on the distribution:
Git for Windows puts `git.exe` in `cmd/`, while PortableGit and GitHub Desktop
put it in `mingw64/bin/`. Bash and sh stay at `<root>/bin` and `<root>/usr/bin`
in both layouts. `backend/tests/support/shell.py` mirrors the same rule for the
shell-script suites.

`make clean` deletes `backend/.deer-flow` (database, users, threads, uploads,
secrets), which both compose stacks mount into `deer-flow-gateway`. Its recipe
runs `check-data-not-in-use.sh` before `make stop` (which would stop a live
stack's sandboxes) and refuses while that container runs; an absent or
unreachable Docker passes. `make stop` must still run before the delete: it
stops `deer-flow-sandbox*` containers, whose thread mounts live in that tree.
`cleanup-containers.sh` must verify an anchored `<prefix>-` name after Docker's
substring `name=` filter, and use the same rule for Apple Container IDs. Parse
Apple Container JSON without interpolating the prefix into Python source; bad
entries must not hide later valid containers. Offline stub coverage lives in
`backend/tests/test_cleanup_containers_script.py`.
`RUNTIME_DATA_CONTENTS` feeds both the help line and the deletion notice.

Host-side pnpm calls must go through `scripts/pnpm.py`. With native Windows
Python (`os.name == "nt"`), it checks `pnpm.cmd` before the generic `pnpm`
lookup, which uses `PATH`/`PATHEXT` and may select an `.exe` or `.bat` in the
same or an earlier PATH directory. If neither is found, it falls back to
Corepack, checking `corepack.cmd` before `corepack`. POSIX Python (including
MSYS/Cygwin Python) keeps the generic name first for each tool; the gate is
based on Python's `os.name`, not the invoking shell.

Scripts that need only PyYAML (`config_upgrade.py`, `sandbox_toggle.py`) run
through `scripts/backend-python.sh`, never a bare `uv run`: it uses `uv run`
in `backend/` only when both uv and `backend/.venv` exist, else a host
`python3`/`python` that can import yaml, else it exits naming the fix (a
Docker-only host has no uv, and `uv run` without a venv installs the whole
backend). `make doctor` stays on uv — it imports `deerflow`.

The dev gateway runs as the invoking user (`DEER_FLOW_UID`/`DEER_FLOW_GID`,
`setpriv`); never add a compose `user:` to it or a default for those variables
(FORK.md, *Dev stack file ownership*).

## Public Skill Review Waivers

`review_changed_public_skills.py` keeps the analyzer strict and applies narrow
CI-only exceptions from `.github/skill-review-waivers.v1.json`. The manifest is
versioned by `contracts/skill_review/waiver_manifest.v1.schema.json`; each entry
must identify one current error by package, source, rule, path, line, and
evidence, and pin the complete source file with SHA-256 plus an expiry date.
An optional, bounded `preapproved_file_sha256s` list authorizes reviewed future
full-file digests without relaxing the exact finding match. Blockers are never
waivable, and waived errors are still printed with their original severity and
justification.

For pull requests, only the base revision's manifest is effective. The head
manifest is parsed and checked against the current analyzer output, but cannot
self-authorize a finding in the same pull request. Push comparisons use the
same before/after trust boundary. A waiver-only change can therefore land
without weakening its own check, then become effective for later changes after
it is part of the trusted base. Preapproved digests must be code-reviewed in
that first change; after the corresponding file revision lands, promote the
consumed digest to `file_sha256` and remove it from the preapproval list.

## Backend Static Analysis Commands

`detect-thread-boundaries`, `detect-blocking-io`, the blocking-I/O runtime gate,
memory-backend async boundaries, browser-session process limits and
support-bundle/doctor capture encoding carry silent contracts; read
[STATIC_ANALYSIS.md](STATIC_ANALYSIS.md) before editing them.

## Production dotenv selection

`deploy.sh` resolves `DEER_FLOW_COMPOSE_ENV_FILE` from the checkout before
creating state or probing secrets. Keep Compose interpolation, Gateway and
provisioner env files, secret probes, and UV_EXTRAS discovery on that one path.
Normalize host paths for Git Bash; quote path arguments rather than sourcing
dotenv files. Unset/empty selection preserves the optional root .env default;
explicit invalid files reject build/start before Docker. Stopping remains
possible after the selected file is removed. Tests: `test_deploy_env_file.py`
and the existing deployment/Compose suites.
