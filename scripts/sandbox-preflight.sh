#!/usr/bin/env bash
#
# sandbox-preflight.sh — verify the containerized (AIO) sandbox can start
# before launching host-run services (invoked by scripts/serve.sh).
#
# Usage:
#   ./scripts/sandbox-preflight.sh [path/to/config.yaml]
#
# Behavior by sandbox mode detected from config.yaml:
#   local        — nothing to check, exit 0
#   provisioner  — pods are managed externally, exit 0 with a note
#   aio          — require a working container runtime and ensure the sandbox
#                  image is present (pulling it on first run). Exits non-zero
#                  with actionable guidance — including how to fall back to
#                  LocalSandboxProvider — when the environment cannot run it.
#
# Sandbox containers themselves are created per conversation by
# AioSandboxProvider, which waits up to 60s for each container's health
# endpoint and raises a clear error on timeout; this preflight ensures that
# first acquisition cannot fail on a missing daemon or a cold image pull.
#
# The file is source-guarded so tests can source the functions directly.

DEFAULT_SANDBOX_IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"

# Print local / aio / provisioner for the given config file.
detect_sandbox_mode_from_config() {
    local config_file="$1"
    local sandbox_use=""
    local provisioner_url=""

    [ -f "$config_file" ] || { echo "local"; return; }

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*use:[[:space:]]*/, "", line); print line; exit
        }
    ' "$config_file")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line); print line; exit
        }
    ' "$config_file")

    if [[ "$sandbox_use" == *"deerflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# Print the sandbox.base_url from config.yaml (empty if unset/commented).
sandbox_base_url_from_config() {
    local config_file="$1"
    [ -f "$config_file" ] || return 0
    awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*base_url:[[:space:]]*/ {
            line=$0; sub(/^[[:space:]]*base_url:[[:space:]]*/, "", line);
            sub(/[[:space:]]*#.*$/, "", line); print line; exit
        }
    ' "$config_file"
}

# True (0) when the external sandbox answers its readiness endpoint.
_external_sandbox_healthy() {
    local base_url="$1"
    command -v curl >/dev/null 2>&1 || return 1
    curl -fsS --max-time 3 "${base_url%/}/v1/sandbox" >/dev/null 2>&1
}

_external_fallback_hint() {
    echo "  Inspect the container:   make sandbox-logs" >&2
    echo "  Or revert to local mode: make sandbox-disable" >&2
}

# External base_url mode: ensure the pre-existing sandbox container is up.
# $1 = base_url, $2 = repo root.
external_sandbox_preflight() {
    local base_url="$1"
    local repo_root="$2"
    local compose_file="$repo_root/docker/docker-compose.sandbox.yml"

    echo "Sandbox: external AIO mode detected (base_url: $base_url) — checking reachability..."

    if _external_sandbox_healthy "$base_url"; then
        echo "✓ Sandbox: external container already reachable at $base_url"
        return 0
    fi

    echo "Sandbox: $base_url is not reachable — attempting to start the bundled container..."

    local compose_cmd=""
    if docker compose version >/dev/null 2>&1; then
        compose_cmd="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        compose_cmd="docker-compose"
    fi

    if [ -z "$compose_cmd" ] || [ ! -f "$compose_file" ]; then
        echo "✗ Sandbox: cannot auto-start the external sandbox (docker compose or $compose_file unavailable)." >&2
        _external_fallback_hint
        return 1
    fi

    if ! $compose_cmd -f "$compose_file" up -d; then
        echo "✗ Sandbox: 'docker compose -f $compose_file up -d' failed." >&2
        _external_fallback_hint
        return 1
    fi

    # Health-poll base_url (bounded ~60s).
    local waited=0
    while [ "$waited" -lt 60 ]; do
        if _external_sandbox_healthy "$base_url"; then
            echo "✓ Sandbox: external container is ready at $base_url"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done

    echo "✗ Sandbox: started the container but $base_url did not become ready within 60s." >&2
    _external_fallback_hint
    return 1
}

# ── Host-run Ollama reachability (advisory) ──────────────────────────────────
# In-container code reaches host services as host.docker.internal, which maps
# to the Docker bridge gateway on Linux. A host Ollama bound to loopback only —
# its default — answers on localhost but refuses bridge-gateway connections,
# so agent-run Ollama clients inside the sandbox would get "connection
# refused". Detect that case and print the one-line fix. Advisory only: it
# never fails preflight, and stays quiet when reachability cannot be
# determined (no docker CLI, no bridge network) or on Docker Desktop (which
# proxies host loopback for host.docker.internal).

OLLAMA_DEFAULT_PORT=11434

_ollama_answers() {
    command -v curl >/dev/null 2>&1 || return 1
    curl -fsS --max-time 2 "$1/api/version" >/dev/null 2>&1
}

_docker_bridge_gateway_ip() {
    local ip
    ip="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null)" || return 1
    [ -n "$ip" ] || return 1
    echo "$ip"
}

_is_docker_desktop() {
    docker info --format '{{.OperatingSystem}}' 2>/dev/null | grep -qi "docker desktop"
}

warn_if_host_ollama_unreachable_from_containers() {
    _ollama_answers "http://localhost:${OLLAMA_DEFAULT_PORT}" || return 0
    _is_docker_desktop && return 0
    local gateway_ip
    gateway_ip="$(_docker_bridge_gateway_ip)" || return 0
    _ollama_answers "http://${gateway_ip}:${OLLAMA_DEFAULT_PORT}" && return 0
    echo "⚠ Ollama answers on localhost:${OLLAMA_DEFAULT_PORT} but not on the Docker bridge gateway (${gateway_ip}) — it is bound to loopback only." >&2
    echo "  Code inside the sandbox container reaches the host as host.docker.internal:${OLLAMA_DEFAULT_PORT}, so those connections will be refused." >&2
    echo "  Fix: make Ollama listen on all interfaces, then restart it:" >&2
    echo "      systemd: sudo systemctl edit ollama   # add:  [Service]  Environment=\"OLLAMA_HOST=0.0.0.0\"" >&2
    echo "      manual:  OLLAMA_HOST=0.0.0.0 ollama serve" >&2
    echo "  (Advisory only — DeerFlow's own model calls run on the host and are unaffected.)" >&2
    return 0
}

# Print the sandbox image from config.yaml, or the provider default.
sandbox_image_from_config() {
    local config_file="$1"
    local image=""

    if [ -f "$config_file" ]; then
        image=$(awk '
            /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
            in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
            in_sandbox && /^[[:space:]]*image:[[:space:]]*/ {
                line=$0; sub(/^[[:space:]]*image:[[:space:]]*/, "", line);
                sub(/[[:space:]]*#.*$/, "", line); print line; exit
            }
        ' "$config_file")
    fi

    if [ -n "$image" ]; then
        echo "$image"
    else
        echo "$DEFAULT_SANDBOX_IMAGE"
    fi
}

_aio_fallback_hint() {
    echo "  To keep working without Docker, switch config.yaml back to the local sandbox:" >&2
    echo "      sandbox:" >&2
    echo "        use: deerflow.sandbox.local:LocalSandboxProvider" >&2
    echo "  (the default; see 'Option 1' in config.example.yaml)" >&2
}

# Main preflight. $1 = config file path.
aio_sandbox_preflight() {
    local config_file="$1"
    local mode image

    mode="$(detect_sandbox_mode_from_config "$config_file")"

    case "$mode" in
        local)
            return 0
            ;;
        provisioner)
            echo "Sandbox: provisioner-managed AIO mode — pods are created by the provisioner service; skipping local Docker checks."
            return 0
            ;;
    esac

    # External mode: a single pre-existing container addressed by base_url.
    local base_url
    base_url="$(sandbox_base_url_from_config "$config_file")"
    if [ -n "$base_url" ]; then
        local repo_root rc
        repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        external_sandbox_preflight "$base_url" "$repo_root"
        rc=$?
        [ "$rc" -eq 0 ] && warn_if_host_ollama_unreachable_from_containers
        return $rc
    fi

    echo "Sandbox: containerized AIO mode detected in config.yaml — checking Docker..."

    # Apple Container is a first-class runtime for this provider on macOS.
    if [ "$(uname)" = "Darwin" ] && command -v container >/dev/null 2>&1; then
        echo "✓ Apple Container detected — sandbox containers will use it (created per conversation on first use)"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        echo "✗ Sandbox: config.yaml selects the containerized AIO sandbox, but Docker is not installed." >&2
        echo "  Install Docker: https://docs.docker.com/get-docker/" >&2
        _aio_fallback_hint
        return 1
    fi

    if ! docker info >/dev/null 2>&1; then
        echo "✗ Sandbox: Docker is installed but the daemon is not reachable." >&2
        echo "  Start Docker (e.g. 'sudo systemctl start docker' on Linux, or open Docker Desktop) and retry." >&2
        _aio_fallback_hint
        return 1
    fi

    image="$(sandbox_image_from_config "$config_file")"
    if docker image inspect "$image" >/dev/null 2>&1; then
        echo "✓ Sandbox image present: $image"
    else
        echo "Sandbox image not found locally — pulling $image"
        echo "  (first run only; this image is large and can take several minutes)"
        if ! docker pull "$image"; then
            echo "✗ Sandbox: failed to pull the sandbox image '$image'." >&2
            echo "  Check network/registry access, or pre-pull it later with: make setup-sandbox" >&2
            _aio_fallback_hint
            return 1
        fi
        echo "✓ Sandbox image pulled: $image"
    fi

    echo "✓ Sandbox: Docker ready — containers are created per conversation (readiness is health-checked with a 60s timeout)"
    warn_if_host_ollama_unreachable_from_containers
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    aio_sandbox_preflight "${1:-config.yaml}"
fi
