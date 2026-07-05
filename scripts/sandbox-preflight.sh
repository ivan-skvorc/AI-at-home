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
    return 0
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    aio_sandbox_preflight "${1:-config.yaml}"
fi
