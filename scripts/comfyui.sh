#!/usr/bin/env bash
#
# comfyui.sh — start, stop, or attach the bundled ComfyUI container
#
# Usage:
#   ./scripts/comfyui.sh up              # start it (no-op when one already runs)
#   ./scripts/comfyui.sh stop            # stop without removing
#   ./scripts/comfyui.sh down            # stop and remove
#   ./scripts/comfyui.sh logs            # follow the logs
#   ./scripts/comfyui.sh attach NETWORK  # join a stack network so containers reach it
#
# The launch scripts call `up` (and, in Docker mode, `attach`) when
# scripts/detect_comfyui.py resolved to `bundled start`; `make comfy-up` calls
# the same path, so the automatic and the manual door are one implementation.
#
# ONE CONTAINER, ONE PROJECT. The compose project is pinned to
# `deer-flow-comfyui` rather than inherited from the current directory, and the
# service carries a fixed container_name. That combination is what makes `up`
# idempotent across every caller: the dev stack, the prod stack and a manual
# `make comfy-up` all converge on the same container instead of racing to
# create a second one on the same GPU. It is deliberately NOT a service of the
# main compose project — `deploy.sh` runs `up --remove-orphans`, which would
# delete a container it does not know about, taking the GPU service down as a
# side effect of an unrelated restart.
#
# The exported defaults below only satisfy compose interpolation; none of them
# reaches the container.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker/docker-compose.comfyui.yml"
PROJECT="deer-flow-comfyui"
CONTAINER="deer-flow-comfyui"
CMD="${1:-up}"

export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$REPO_ROOT/backend/.deer-flow}"
export DEER_FLOW_REPO_ROOT="${DEER_FLOW_REPO_ROOT:-$REPO_ROOT}"

compose() {
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

container_state() {
    docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || true
}

case "$CMD" in
    up)
        state="$(container_state)"
        if [ "$state" = "running" ]; then
            # Already up — from an earlier launch, from `make comfy-up`, or from
            # an older checkout that used a different compose project. Reusing it
            # is the whole point; recreating would evict the weights it is holding.
            echo "ComfyUI: container '$CONTAINER' is already running."
            exit 0
        fi
        if [ -n "$state" ]; then
            # A stopped container with our name may belong to another compose
            # project (the project used to default to the checkout directory).
            # `compose up` would fail on the name; start what is there instead.
            echo "ComfyUI: starting the existing '$CONTAINER' container..."
            exec docker start "$CONTAINER"
        fi
        exec compose up -d comfyui
        ;;
    stop)
        exec compose stop comfyui
        ;;
    down)
        exec compose down
        ;;
    logs)
        exec compose logs --tail=100 -f comfyui
        ;;
    attach)
        network="${2:-}"
        if [ -z "$network" ]; then
            echo "Usage: $0 attach <network>" >&2
            exit 1
        fi
        # Idempotent: connecting a container that is already on the network
        # exits non-zero with "already exists", which is a success for us.
        if docker network connect "$network" "$CONTAINER" 2>/dev/null; then
            echo "ComfyUI: attached '$CONTAINER' to network '$network'."
        else
            echo "ComfyUI: '$CONTAINER' is already on '$network' (or the network is gone)."
        fi
        ;;
    *)
        echo "Usage: $0 [up|stop|down|logs|attach <network>]"
        exit 1
        ;;
esac
