# shellcheck shell=bash
#
# Helpers shared by the two Docker launch paths, scripts/deploy.sh (`make up`)
# and scripts/docker.sh (`make docker-start`), so both read `.env` and decide
# the loopback co-bind the same way. Sourcing it defines functions only.
#
# The caller sets DOCKER_LAUNCH_ENV_FILE to the dotenv file Compose
# interpolates from: deploy.sh's selected DEER_FLOW_COMPOSE_ENV_FILE, or the
# repo-root `.env` for docker.sh. The file is parsed, never sourced.

# Strip one dotenv value the way Compose's --env-file reads the simple forms:
# a trailing CR, surrounding whitespace, then one pair of matching quotes.
dotenv_unquote() {
    local value="$1"
    value="${value%$'\r'}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    printf '%s' "$value"
}

# Print the last `KEY=` line (an `export ` prefix allowed) of
# $DOCKER_LAUNCH_ENV_FILE, or nothing when the file or the key is missing.
dotenv_line() {
    [ -n "${DOCKER_LAUNCH_ENV_FILE:-}" ] && [ -f "$DOCKER_LAUNCH_ENV_FILE" ] || return 0
    grep -E "^[[:space:]]*(export[[:space:]]+)?$1[[:space:]]*=" "$DOCKER_LAUNCH_ENV_FILE" | tail -n 1 || true
}

# Read one key the way `docker compose --env-file` interpolates it, so the
# banners report the values the stack actually came up with. The shell never
# sources the dotenv file, so reading the environment alone would report
# "loopback only" for a stack that `.env` exposed to the network.
read_dotenv_value() {
    local key="$1"
    local line=""

    # An exported shell variable wins, matching compose precedence.
    if [ -n "${!key+x}" ]; then
        printf '%s' "${!key}"
        return 0
    fi

    line="$(dotenv_line "$key")"
    [ -n "$line" ] || return 0
    dotenv_unquote "${line#*=}"
}

# BIND_HOST publishes exactly ONE interface (a bind address, not an
# allowlist). Set to a single external interface such as a Tailscale IP, it
# refuses the host's own http://localhost:PORT. Echo "yes" in that case so the
# caller appends docker/docker-compose.loopback.yaml and also publishes on
# 127.0.0.1. Wildcards already cover loopback (a second mapping would collide
# on the port), and loopback binds need nothing extra. Pinned by
# test_deploy_loopback_cobind.py and test_docker_dev_tailnet.py.
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

# Print the first of python3 or python that runs Python 3.6 or newer, for the
# host-side detectors and generators; fail when neither does.
pick_detector_python() {
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
