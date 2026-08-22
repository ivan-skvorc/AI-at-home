# shellcheck shell=bash
#
# Shared tailnet wiring for the two Docker launch paths (fork feature).
#
# Sourced by scripts/docker.sh (`make docker-start`) and scripts/deploy.sh
# (`make up`) so both behave identically: the "reach it from my phone" story
# must not depend on which of the two commands a user happens to run.
#
# What it does, in one pass at start:
#
#   1. Asks scripts/detect_tailscale.py whether this machine is on a tailnet.
#      No Tailscale (or a stopped daemon, or DEER_FLOW_TAILSCALE_PUBLISH=0) ⇒
#      every function below is a no-op and the published surface is unchanged.
#   2. Exports DEER_FLOW_TAILSCALE_IPV4 so docker/docker-compose.tailscale.yaml
#      can publish nginx on the CGNAT address *in addition to* 127.0.0.1.
#   3. Merges the tailnet origins into GATEWAY_CORS_ORIGINS,
#      DEER_FLOW_TRUSTED_ORIGINS and DEER_FLOW_DEV_ALLOWED_ORIGINS without
#      discarding anything the user configured. Publishing the port without
#      this is the half-fix that loads the shell and 403s the API.
#
# Nothing here ever fails a launch: a missing python, a wedged daemon, or a
# detector that cannot decide all degrade to "no tailnet", which is exactly the
# pre-existing behavior.

# Populated by tailscale_detect. Empty string = no tailnet.
DEER_FLOW_TAILNET_IPV4=""
DEER_FLOW_TAILNET_HOSTNAME=""
DEER_FLOW_TAILNET_ORIGINS=""

# Resolve the tailnet identity for the entry port $1 (default 2026).
# Safe to call unconditionally; sets the three variables above.
tailscale_detect() {
    local port="${1:-2026}"
    local script_dir="${TAILSCALE_LIB_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
    local python_bin="${TAILSCALE_LIB_PYTHON:-}"
    local line key value

    DEER_FLOW_TAILNET_IPV4=""
    DEER_FLOW_TAILNET_HOSTNAME=""
    DEER_FLOW_TAILNET_ORIGINS=""

    if [ -z "$python_bin" ]; then
        for candidate in python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then
                python_bin="$candidate"
                break
            fi
        done
    fi
    [ -n "$python_bin" ] || return 0
    [ -f "$script_dir/detect_tailscale.py" ] || return 0

    # `|| true`: the detector already exits 0 for "absent", but a launch path
    # must not die even if it somehow does not.
    while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        case "$key" in
            DEER_FLOW_TAILSCALE_IPV4) DEER_FLOW_TAILNET_IPV4="$value" ;;
            DEER_FLOW_TAILSCALE_HOSTNAME) DEER_FLOW_TAILNET_HOSTNAME="$value" ;;
            DEER_FLOW_TAILSCALE_ORIGINS) DEER_FLOW_TAILNET_ORIGINS="$value" ;;
        esac
    done < <("$python_bin" "$script_dir/detect_tailscale.py" --format env --port "$port" 2>/dev/null || true)

    [ -n "$DEER_FLOW_TAILNET_IPV4" ] && export DEER_FLOW_TAILSCALE_IPV4="$DEER_FLOW_TAILNET_IPV4"
    return 0
}

# True when a tailnet publish should be added to the compose command.
tailscale_should_publish() {
    [ -n "$DEER_FLOW_TAILNET_IPV4" ]
}

# Merge the detected tailnet origins into every allowlist that can reject them.
#
# Each variable is merged independently and only ever grows, so a user's own
# entries survive verbatim and re-running a launch script is idempotent (the
# merge dedupes on a normalized comparison rather than appending blindly).
#
# The three lists, and why each one matters:
#   GATEWAY_CORS_ORIGINS         Gateway CORSMiddleware + CSRFMiddleware read it;
#                                without the tailnet origin, auth POSTs from a
#                                phone are answered "Cross-site auth request denied".
#   DEER_FLOW_TRUSTED_ORIGINS    Next.js SSR's gateway config (frontend container).
#   DEER_FLOW_DEV_ALLOWED_ORIGINS  Next dev-server asset/HMR origin check. The
#                                fork already ships wildcard defaults covering
#                                100.* and **.ts.net; listing the exact host too
#                                keeps working if someone sets STRICT mode.
tailscale_merge_origins() {
    local script_dir="${TAILSCALE_LIB_SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
    local python_bin="${TAILSCALE_LIB_PYTHON:-}"
    local var merged

    [ -n "$DEER_FLOW_TAILNET_ORIGINS" ] || return 0

    if [ -z "$python_bin" ]; then
        for candidate in python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then
                python_bin="$candidate"
                break
            fi
        done
    fi
    [ -n "$python_bin" ] || return 0

    for var in GATEWAY_CORS_ORIGINS DEER_FLOW_TRUSTED_ORIGINS DEER_FLOW_DEV_ALLOWED_ORIGINS; do
        # An operator who wrote "*" meant "allow everything"; narrowing that to a
        # concrete list here would tighten a setting they deliberately opened.
        if [ "${!var:-}" = "*" ]; then
            continue
        fi
        merged="$("$python_bin" "$script_dir/detect_tailscale.py" --merge-into "${!var:-}" --port "${DEER_FLOW_TAILNET_PORT:-2026}" 2>/dev/null || true)"
        # Only widen: an empty result means the helper failed, and clobbering a
        # user's allowlist with "" would break the very access we are fixing.
        if [ -n "$merged" ]; then
            export "$var=$merged"
        fi
    done
    return 0
}

# Print the URLs that actually listen, so the banner stops advertising only
# http://localhost when another URL is live.
tailscale_print_urls() {
    local port="${1:-2026}"
    local green="${GREEN:-}"
    local nc="${NC:-}"

    tailscale_should_publish || return 0
    echo -e "  ${green}📱 Tailnet:     http://${DEER_FLOW_TAILNET_IPV4}:${port}${nc}  (from any device on your tailnet)"
    if [ -n "$DEER_FLOW_TAILNET_HOSTNAME" ]; then
        if tailscale_serve_is_active "$port"; then
            echo -e "  ${green}🔒 MagicDNS:    https://${DEER_FLOW_TAILNET_HOSTNAME}${nc}  (Tailscale Serve, HTTPS)"
        else
            echo    "  💡 For HTTPS:   tailscale serve --bg --https=443 http://127.0.0.1:${port}"
            echo    "                  (then https://${DEER_FLOW_TAILNET_HOSTNAME} — needs --operator=\$USER or sudo)"
        fi
    fi
    return 0
}

# Whether `tailscale serve` is already forwarding to our entry port.
#
# Read-only on purpose. This helper never runs `tailscale serve` and never runs
# `tailscale serve reset`: Serve config is global to the machine and may carry
# rules for other services, so a start/stop of DeerFlow must not touch it.
tailscale_serve_is_active() {
    local port="${1:-2026}"
    command -v tailscale >/dev/null 2>&1 || return 1
    tailscale serve status 2>/dev/null | grep -q "127.0.0.1:${port}\|localhost:${port}"
}
