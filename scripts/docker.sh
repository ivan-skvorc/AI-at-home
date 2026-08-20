#!/usr/bin/env bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$PROJECT_ROOT/docker"

# Shared tailnet publish + origin merging, identical to the `make up` path.
# shellcheck source=scripts/tailscale_lib.sh
. "$SCRIPT_DIR/tailscale_lib.sh"

# Docker Compose command with project name.
#
# `--env-file` is load-bearing, not cosmetic. Every command below runs after
# `cd "$DOCKER_DIR"`, so without it Compose resolves the `${BIND_HOST}` /
# `${PORT}` in docker-compose-dev.yaml's `ports:` against `docker/.env` — a file
# that does not exist — and the repo-root `.env` the README documents is simply
# ignored for **port interpolation**. (`env_file: ../.env` on a service only
# populates that container's environment; it has no effect on interpolation.)
# The symptom is silent: you set BIND_HOST in the root .env, `make docker-start`
# reports success, and nginx is still published on 127.0.0.1 only.
# Pinned by backend/tests/test_docker_dev_tailnet.py.
COMPOSE_CMD="docker compose -p deer-flow-dev"
if [ -f "$PROJECT_ROOT/.env" ]; then
    COMPOSE_CMD="$COMPOSE_CMD --env-file $PROJECT_ROOT/.env"
fi
COMPOSE_CMD="$COMPOSE_CMD -f docker-compose-dev.yaml"

load_proxy_env_from_dotenv() {
    local env_file="$PROJECT_ROOT/.env"
    local var
    local line
    local value

    if [ ! -f "$env_file" ]; then
        return
    fi

    for var in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
        if [ -z "${!var+x}" ]; then
            line="$(grep -E "^[[:space:]]*${var}=" "$env_file" | tail -n 1 || true)"
            if [ -n "$line" ]; then
                value="${line#*=}"
                value="${value%\"}"
                value="${value#\"}"
                value="${value%\'}"
                value="${value#\'}"
                value="${value%$'\r'}"
                export "${var}=${value}"
            fi
        fi
    done
}

# Read one key from the repo-root .env the way `docker compose --env-file`
# interpolates it, so the banner reports the values the stack actually came up
# with. The shell never sources .env, so reading these from the environment
# alone would report "loopback only" for a stack that .env exposed elsewhere.
# Mirrors scripts/deploy.sh::read_dotenv_value.
read_dotenv_value() {
    local key="$1"
    local line=""
    local value=""

    # An exported shell variable wins, matching compose precedence.
    if [ -n "${!key+x}" ]; then
        printf '%s' "${!key}"
        return 0
    fi

    [ -f "$PROJECT_ROOT/.env" ] || return 0

    line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "$PROJECT_ROOT/.env" | tail -n 1 || true)"
    [ -n "$line" ] || return 0

    value="${line#*=}"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    printf '%s' "$value"
}

# BIND_HOST publishes exactly ONE interface (it is a bind address, not an
# allowlist), so pointing it at a single external interface refuses the host's
# own http://localhost:PORT. Echo "yes" when that is the case so the caller can
# append docker/docker-compose.loopback.yaml and ALSO publish on 127.0.0.1.
# Wildcards already cover loopback (a second mapping would collide on the port);
# loopback binds need nothing extra. Mirrors scripts/deploy.sh so both Docker
# paths behave identically. Pinned by backend/tests/test_docker_dev_tailnet.py.
should_cobind_loopback() {
    local bind
    bind="$(read_dotenv_value BIND_HOST)"
    case "$bind" in
        "" | 127.0.0.1 | ::1 | localhost | 0.0.0.0 | ::)
            echo "no"
            ;;
        *)
            echo "yes"
            ;;
    esac
}

_pick_python() {
    local candidate
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import sys; sys.version_info >= (3, 6) or sys.exit(1)' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Prints "skip", "bundled", or "external <url>" — see scripts/detect_searxng.py.
resolve_searxng() {
    local detect_python
    detect_python="$(_pick_python || true)"
    if [ -n "$detect_python" ]; then
        local args=(--context docker --config "$PROJECT_ROOT/config.yaml")
        [ -f "$PROJECT_ROOT/.env" ] && args+=(--env-file "$PROJECT_ROOT/.env")
        "$detect_python" "$SCRIPT_DIR/detect_searxng.py" "${args[@]}" || echo "bundled"
    elif ! grep -E 'deerflow\.community\.searxng' "$PROJECT_ROOT/config.yaml" 2>/dev/null | grep -qv '^[[:space:]]*#'; then
        # No Python available for detection: fall back to the config grep only.
        echo "skip"
    else
        echo "bundled"
    fi
}

detect_sandbox_mode() {
    local config_file="$PROJECT_ROOT/config.yaml"
    local sandbox_use=""
    local provisioner_url=""

    if [ ! -f "$config_file" ]; then
        echo "local"
        return
    fi

    sandbox_use=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*use:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*use:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    provisioner_url=$(awk '
        /^[[:space:]]*sandbox:[[:space:]]*$/ { in_sandbox=1; next }
        in_sandbox && /^[^[:space:]#]/ { in_sandbox=0 }
        in_sandbox && /^[[:space:]]*provisioner_url:[[:space:]]*/ {
            line=$0
            sub(/^[[:space:]]*provisioner_url:[[:space:]]*/, "", line)
            print line
            exit
        }
    ' "$config_file")

    if [[ "$sandbox_use" == *"deerflow.sandbox.local:LocalSandboxProvider"* ]]; then
        echo "local"
    elif [[ "$sandbox_use" == *"deerflow.community.aio_sandbox:AioSandboxProvider"* ]]; then
        if [ -n "$provisioner_url" ]; then
            echo "provisioner"
        else
            echo "aio"
        fi
    else
        echo "local"
    fi
}

# Cleanup function for Ctrl+C
cleanup() {
    echo ""
    echo -e "${YELLOW}Operation interrupted by user${NC}"
    exit 130
}

# Set up trap for Ctrl+C
trap cleanup INT TERM

docker_available() {
    # Check that the docker CLI exists
    if ! command -v docker >/dev/null 2>&1; then
        return 1
    fi

    # Check that the Docker daemon is reachable
    if ! docker info >/dev/null 2>&1; then
        return 1
    fi

    return 0
}

# Initialize: pre-pull the sandbox image so first Pod startup is fast
init() {
    echo "=========================================="
    echo "  DeerFlow Init — Pull Sandbox Image"
    echo "=========================================="
    echo ""

    SANDBOX_IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest"

    # Detect sandbox mode from config.yaml
    local sandbox_mode
    sandbox_mode="$(detect_sandbox_mode)"

    # Skip image pull for local sandbox mode (no container image needed)
    if [ "$sandbox_mode" = "local" ]; then
        echo -e "${GREEN}Detected local sandbox mode — no Docker image required.${NC}"
        echo ""

        if docker_available; then
            echo -e "${GREEN}✓ Docker environment is ready.${NC}"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
        else
            echo -e "${YELLOW}Docker does not appear to be installed, or the Docker daemon is not reachable.${NC}"
            echo "Local sandbox mode itself does not require Docker, but Docker-based workflows (e.g., docker-start) will fail until Docker is available."
            echo ""
            echo -e "${YELLOW}Install and start Docker, then run: make docker-init && make docker-start${NC}"
        fi

        return 0
    fi

    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${SANDBOX_IMAGE}$"; then
        echo -e "${BLUE}Pulling sandbox image: $SANDBOX_IMAGE ...${NC}"
        echo ""

        if ! docker pull "$SANDBOX_IMAGE" 2>&1; then
            echo ""
            echo -e "${YELLOW}⚠ Failed to pull sandbox image.${NC}"
            echo ""
            echo "This is expected if:"
            echo "  1. You are using local sandbox mode (default — no image needed)"
            echo "  2. You are behind a corporate proxy or firewall"
            echo "  3. The registry requires authentication"
            echo ""
            echo -e "${GREEN}The Docker development environment can still be started.${NC}"
            echo "If you need AIO sandbox (container-based execution):"
            echo "  - Ensure you have network access to the registry"
            echo "  - Or configure a custom sandbox image in config.yaml"
            echo ""
            echo -e "${YELLOW}Next step: make docker-start${NC}"
            return 0
        fi
    else
        echo -e "${GREEN}Sandbox image already exists locally: $SANDBOX_IMAGE${NC}"
    fi

    echo ""
    echo -e "${GREEN}✓ Sandbox image is ready.${NC}"
    echo ""
    echo -e "${YELLOW}Next step: make docker-start${NC}"
}

# Start Docker development environment
start() {
    local sandbox_mode
    local services

    if [ "$#" -gt 0 ]; then
        echo -e "${YELLOW}Unknown option for start: $1${NC}"
        echo "Usage: $0 start"
        exit 1
    fi

    echo "=========================================="
    echo "  Starting DeerFlow Docker Development"
    echo "=========================================="
    echo ""

    sandbox_mode="$(detect_sandbox_mode)"

    services="redis frontend gateway nginx"
    if [ "$sandbox_mode" = "provisioner" ]; then
        services="redis frontend gateway provisioner nginx"
    fi

    # Only aio mode (AioSandboxProvider without provisioner_url) needs the host
    # Docker socket. Mount it via the opt-in docker-compose.dood.yaml overlay so
    # the default (local) and provisioner modes never expose the host daemon.
    # Mounting the socket = root-equivalent host control; see SECURITY.md.
    if [ "$sandbox_mode" = "aio" ]; then
        local docker_socket="${DEER_FLOW_DOCKER_SOCKET:-/var/run/docker.sock}"
        if [ ! -S "$docker_socket" ]; then
            echo -e "${YELLOW}⚠ Docker socket not found at $docker_socket — AioSandboxProvider (DooD) will not work.${NC}"
            exit 1
        fi
        echo -e "${YELLOW}Mounting host Docker socket into gateway (DooD = host root-equivalent). See SECURITY.md.${NC}"
        COMPOSE_CMD="$COMPOSE_CMD -f $DOCKER_DIR/docker-compose.dood.yaml"
    fi

    echo -e "${BLUE}Runtime: Gateway embedded agent runtime${NC}"
    echo -e "${BLUE}Detected sandbox mode: $sandbox_mode${NC}"
    if [ "$sandbox_mode" = "provisioner" ]; then
        echo -e "${BLUE}Provisioner enabled (Kubernetes mode).${NC}"
    else
        echo -e "${BLUE}Provisioner disabled (not required for this sandbox mode).${NC}"
    fi
    echo ""
    
    # Set DEER_FLOW_ROOT for provisioner if not already set
    if [ -z "$DEER_FLOW_ROOT" ]; then
        export DEER_FLOW_ROOT="$PROJECT_ROOT"
        echo -e "${BLUE}Setting DEER_FLOW_ROOT=$DEER_FLOW_ROOT${NC}"
        echo ""
    fi
    
    # Ensure config.yaml exists before starting.
    if [ ! -f "$PROJECT_ROOT/config.yaml" ]; then
        if [ -f "$PROJECT_ROOT/config.example.yaml" ]; then
            cp "$PROJECT_ROOT/config.example.yaml" "$PROJECT_ROOT/config.yaml"
            echo ""
            echo -e "${YELLOW}============================================================${NC}"
            echo -e "${YELLOW}  config.yaml has been created from config.example.yaml.${NC}"
            echo -e "${YELLOW}  Please edit config.yaml to set your API keys and model   ${NC}"
            echo -e "${YELLOW}  configuration before starting DeerFlow.                  ${NC}"
            echo -e "${YELLOW}============================================================${NC}"
            echo ""
            echo -e "${YELLOW}  Recommended: run 'make setup' before starting Docker.    ${NC}"
            echo -e "${YELLOW}  Edit the file:  $PROJECT_ROOT/config.yaml${NC}"
            echo -e "${YELLOW}  Then run:        make docker-start${NC}"
            echo ""
            exit 0
        else
            echo -e "${YELLOW}✗ config.yaml not found and no config.example.yaml to copy from.${NC}"
            exit 1
        fi
    fi

    # Ensure extensions_config.json exists as a file before mounting.
    # Docker creates a directory when bind-mounting a non-existent host path.
    if [ ! -f "$PROJECT_ROOT/extensions_config.json" ]; then
        if [ -f "$PROJECT_ROOT/extensions_config.example.json" ]; then
            cp "$PROJECT_ROOT/extensions_config.example.json" "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created extensions_config.json from example${NC}"
        else
            echo "{}" > "$PROJECT_ROOT/extensions_config.json"
            echo -e "${BLUE}Created empty extensions_config.json${NC}"
        fi
    fi

    # ── Ollama auto-populate ─────────────────────────────────────────────
    # Reconcile config.yaml's managed models block with the host's installed
    # Ollama models before the containers mount config.yaml. Runs on the HOST
    # (config.yaml is mounted read-only into the gateway container) and writes
    # base_url http://host.docker.internal:11434 via --container, since inside
    # the container `localhost` is the container itself, not the Docker host
    # where a host-run Ollama listens (host.docker.internal is mapped via
    # extra_hosts in the compose files). Best-effort: unreachable daemon = no-op.
    local ollama_python
    ollama_python="$(_pick_python || true)"
    if [ -n "$ollama_python" ]; then
        "$ollama_python" "$SCRIPT_DIR/sync-ollama-models.py" --config "$PROJECT_ROOT/config.yaml" --container --verbose || true
    fi

    # ── API-key model auto-config ────────────────────────────────────────
    # Enable the Anthropic / OpenRouter model blocks in config.yaml on the
    # HOST before the containers mount it, when their keys are present in
    # .env. Best-effort: missing key = no-op.
    if [ -n "$ollama_python" ]; then
        "$ollama_python" "$SCRIPT_DIR/sync-api-key-models.py" --config "$PROJECT_ROOT/config.yaml" --env-file "$PROJECT_ROOT/.env" --verbose || true
    fi

    # ── SearXNG (web_search backend) ─────────────────────────────────────
    # Reuse an existing SearXNG instance on this machine when containers can
    # reach it; otherwise start the bundled service (scripts/detect_searxng.py).
    local searxng_resolution
    searxng_resolution="$(resolve_searxng)"
    case "$searxng_resolution" in
        skip)
            echo -e "${BLUE}SearXNG: config.yaml does not use the SearXNG web_search provider — bundled service not started${NC}"
            ;;
        external\ *)
            export DEER_FLOW_SEARXNG_BASE_URL="${searxng_resolution#external }"
            echo -e "${GREEN}✓ SearXNG: using existing instance at $DEER_FLOW_SEARXNG_BASE_URL${NC}"
            ;;
        *)
            # Pin the in-network URL so a stale value cannot contradict the decision.
            export DEER_FLOW_SEARXNG_BASE_URL="http://searxng:8080"
            services="$services searxng"
            echo -e "${BLUE}SearXNG: no existing instance found — starting the bundled service${NC}"
            ;;
    esac

    load_proxy_env_from_dotenv

    # ── Tailnet reachability ─────────────────────────────────────────────
    # Publish nginx on this host's Tailscale CGNAT address IN ADDITION to the
    # loopback default, and merge the tailnet origins into every allowlist that
    # could reject a browser on another tailnet device. Entirely a no-op when
    # Tailscale is not running (or DEER_FLOW_TAILSCALE_PUBLISH=0): the default
    # published surface stays 127.0.0.1 only.
    local entry_port
    entry_port="$(read_dotenv_value PORT)"
    entry_port="${entry_port:-2026}"
    DEER_FLOW_TAILNET_PORT="$entry_port"
    tailscale_detect "$entry_port"
    tailscale_merge_origins
    if tailscale_should_publish; then
        COMPOSE_CMD="$COMPOSE_CMD -f $DOCKER_DIR/docker-compose.tailscale.yaml"
        echo -e "${GREEN}✓ Tailscale detected — also publishing on ${DEER_FLOW_TAILNET_IPV4}:${entry_port} (tailnet only, not the LAN).${NC}"
    fi

    # BIND_HOST names a single interface, so pointing it at an external one
    # (e.g. a Tailscale IP, the pre-overlay way of doing the above) refuses the
    # host's own localhost. Co-bind 127.0.0.1 so both keep working — same rule
    # deploy.sh already applies to `make up`.
    if [ "$(should_cobind_loopback)" = "yes" ]; then
        COMPOSE_CMD="$COMPOSE_CMD -f $DOCKER_DIR/docker-compose.loopback.yaml"
        echo -e "${GREEN}✓ Co-binding 127.0.0.1 so http://localhost stays reachable (BIND_HOST=$(read_dotenv_value BIND_HOST)).${NC}"
    fi

    echo "Building and starting containers..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD up --build -d --remove-orphans $services
    echo ""
    echo "=========================================="
    echo "  DeerFlow Docker is starting!"
    echo "=========================================="
    echo ""
    echo "  🌐 Application: http://localhost:${entry_port}"
    echo "  📡 API Gateway: http://localhost:${entry_port}/api/*"
    echo "  🤖 Runtime:     Gateway embedded"
    echo "  API:            /api/langgraph/* → Gateway"
    # Print every URL that actually listens, not just localhost.
    tailscale_print_urls "$entry_port"
    echo ""
    echo "  📋 View logs: make docker-logs"
    echo "  🛑 Stop:      make docker-stop"
    echo ""
}

# View Docker development logs
logs() {
    local service=""

    # DEER_FLOW_ROOT is referenced in docker-compose-dev.yaml; set it before
    # reading logs so Compose does not resolve mounted paths from an empty root.
    if [ -z "$DEER_FLOW_ROOT" ]; then
        export DEER_FLOW_ROOT="$PROJECT_ROOT"
    fi
    
    case "$1" in
        --frontend)
            service="frontend"
            echo -e "${BLUE}Viewing frontend logs...${NC}"
            ;;
        --gateway)
            service="gateway"
            echo -e "${BLUE}Viewing gateway logs...${NC}"
            ;;
        --nginx)
            service="nginx"
            echo -e "${BLUE}Viewing nginx logs...${NC}"
            ;;
        --redis)
            service="redis"
            echo -e "${BLUE}Viewing redis logs...${NC}"
            ;;
        --provisioner)
            service="provisioner"
            echo -e "${BLUE}Viewing provisioner logs...${NC}"
            ;;
        "")
            echo -e "${BLUE}Viewing all logs...${NC}"
            ;;
        *)
            echo -e "${YELLOW}Unknown option: $1${NC}"
            echo "Usage: $0 logs [--frontend|--gateway|--nginx|--redis|--provisioner]"
            exit 1
            ;;
    esac
    
    cd "$DOCKER_DIR" && $COMPOSE_CMD logs -f $service
}

# Stop Docker development environment
stop() {
    # DEER_FLOW_ROOT is referenced in docker-compose-dev.yaml; set it before
    # running compose down to suppress "variable is not set" warnings.
    if [ -z "$DEER_FLOW_ROOT" ]; then
        export DEER_FLOW_ROOT="$PROJECT_ROOT"
    fi
    echo "Stopping Docker development services..."
    cd "$DOCKER_DIR" && $COMPOSE_CMD down
    echo "Cleaning up sandbox containers..."
    "$SCRIPT_DIR/cleanup-containers.sh" deer-flow-sandbox 2>/dev/null || true
    echo -e "${GREEN}✓ Docker services stopped${NC}"
}

# Restart Docker development environment
restart() {
    # DEER_FLOW_ROOT is referenced in docker-compose-dev.yaml; set it before
    # restarting services so Compose resolves mounted paths from this checkout.
    if [ -z "$DEER_FLOW_ROOT" ]; then
        export DEER_FLOW_ROOT="$PROJECT_ROOT"
    fi
    echo "========================================"
    echo "  Restarting DeerFlow Docker Services"
    echo "========================================"
    echo ""
    echo -e "${BLUE}Restarting containers...${NC}"
    cd "$DOCKER_DIR" && $COMPOSE_CMD restart
    echo ""
    echo -e "${GREEN}✓ Docker services restarted${NC}"
    echo ""
    local entry_port
    entry_port="$(read_dotenv_value PORT)"
    entry_port="${entry_port:-2026}"
    echo "  🌐 Application: http://localhost:${entry_port}"
    # `compose restart` restarts containers in place, so the published set is
    # whatever `start` created — including the tailnet port. Report it.
    tailscale_detect "$entry_port"
    tailscale_print_urls "$entry_port"
    echo "  📋 View logs: make docker-logs"
    echo ""
}

# Show help
help() {
    echo "DeerFlow Docker Management Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  init              - Pull the sandbox image (speeds up first Pod startup)"
    echo "  start             - Start Docker services (auto-detects sandbox mode from config.yaml)"
    echo "  restart           - Restart all running Docker services"
    echo "  logs [option] - View Docker development logs"
    echo "                  --frontend   View frontend logs only"
    echo "                  --gateway    View gateway logs only"
    echo "                  --nginx      View nginx logs only"
    echo "                  --redis      View redis logs only"
    echo "                  --provisioner View provisioner logs only"
    echo "  stop          - Stop Docker development services"
    echo "  help          - Show this help message"
    echo ""
}

main() {
    # Main command dispatcher
    case "$1" in
        init)
            init
            ;;
        start)
            shift
            start "$@"
            ;;
        restart)
            restart
            ;;
        logs)
            logs "$2"
            ;;
        stop)
            stop
            ;;
        help|--help|-h|"")
            help
            ;;
        *)
            echo -e "${YELLOW}Unknown command: $1${NC}"
            echo ""
            help
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
