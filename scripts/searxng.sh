#!/usr/bin/env bash
#
# searxng.sh — start or stop the standalone bundled SearXNG container
#
# Usage:
#   ./scripts/searxng.sh up      # start (default)
#   ./scripts/searxng.sh stop    # stop
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
    *)
        echo "Usage: $0 [up|stop]"
        exit 1
        ;;
esac
