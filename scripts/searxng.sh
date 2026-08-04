#!/usr/bin/env bash
#
# searxng.sh — start, stop, or update the standalone bundled SearXNG container
#
# Usage:
#   ./scripts/searxng.sh up      # start (default)
#   ./scripts/searxng.sh stop    # stop
#   ./scripts/searxng.sh update  # pull the latest image, recreate if running
#
# Runs the `searxng` service from docker/docker-compose.yaml under the same
# compose project as `make up` (deer-flow), so the standalone container and
# the production stack share one instance instead of conflicting.
#
# The exported defaults below only satisfy compose interpolation of the other
# services in the file (their volume specs reject empty values); `up searxng`
# starts nothing but searxng and none of these values reach that container.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="${1:-up}"

export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$REPO_ROOT/backend/.deer-flow}"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$REPO_ROOT/config.yaml}"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$REPO_ROOT/extensions_config.json}"
export DEER_FLOW_REPO_ROOT="${DEER_FLOW_REPO_ROOT:-$REPO_ROOT}"
export BETTER_AUTH_SECRET="${BETTER_AUTH_SECRET:-placeholder}"
export DEER_FLOW_INTERNAL_AUTH_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-placeholder}"

case "$CMD" in
    up)
        exec docker compose -p deer-flow -f "$REPO_ROOT/docker/docker-compose.yaml" up -d searxng
        ;;
    stop)
        exec docker compose -p deer-flow -f "$REPO_ROOT/docker/docker-compose.yaml" stop searxng
        ;;
    update)
        # docker.io/searxng/searxng:latest only re-pulls when told to, so a
        # long-running stack never picks up upstream fixes on its own. Pull the
        # newest image, then recreate the container ONLY if it is currently
        # running (an idle checkout just pre-fetches the image for its next
        # `up`; a live stack rolls onto the new image). `up -d` is a no-op when
        # the image is unchanged.
        compose_file="$REPO_ROOT/docker/docker-compose.yaml"
        docker compose -p deer-flow -f "$compose_file" pull searxng || exit 1
        if [ -n "$(docker compose -p deer-flow -f "$compose_file" ps -q searxng 2>/dev/null)" ]; then
            exec docker compose -p deer-flow -f "$compose_file" up -d searxng
        fi
        echo "SearXNG image pulled; bundled container is not running, nothing to recreate."
        ;;
    *)
        echo "Usage: $0 [up|stop|update]"
        exit 1
        ;;
esac
