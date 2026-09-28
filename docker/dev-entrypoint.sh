#!/usr/bin/env sh
#
# DeerFlow gateway dev entrypoint — runs inside the docker-compose-dev gateway
# container. Extracted from docker/docker-compose-dev.yaml's inline `command:`
# (PR #2767, addressing review on Issue #2754).
#
# Responsibilities:
#   0. Run as the host user: hand root-owned paths the Gateway writes to the
#      ids scripts/docker.sh passed (DEER_FLOW_UID/GID), then re-exec under
#      them, so nothing the stack creates in the checkout is owned by root.
#   1. Resolve `--extra X` flags through scripts/detect_uv_extras.py, using the
#      selected config plus explicit UV_EXTRAS and runtime-required backends.
#   2. Validate each extra against [A-Za-z][A-Za-z0-9_-]* so a stray shell
#      metacharacter in `.env` cannot reach `uv sync`.
#   3. `uv sync --locked --all-packages` so the declared extension group and
#      workspace member extras (deerflow-harness's
#      postgres extra in particular) are installed — see PR #2584.
#   4. Self-heal: if the first sync fails, recreate .venv and retry once. The
#      retry stays `--locked`, so it repairs a broken .venv but not a stale
#      lock; a second failure aborts with recovery instructions rather than
#      starting uvicorn against an environment that does not match the lock.
#   5. Hand off to uvicorn with reload, replacing this shell so uvicorn becomes
#      PID 1 inside the container.
#
# Anchored at /bin/sh (not bash) since alpine-based base images may not ship
# bash. Uses POSIX-only constructs throughout.

set -e

# `--print-extras` is a dry-run hook: parse + validate UV_EXTRAS, print the
# resulting `--extra X` flags to stdout, and exit. Used by the unit test in
# backend/tests/test_dev_entrypoint.py and useful for ad-hoc debugging.
# `--print-run-as` likewise prints the privilege drop step 0 would perform
# (backend/tests/test_dev_stack_host_user.py).
PRINT_EXTRAS_ONLY=0
PRINT_RUN_AS_ONLY=0
case "${1:-}" in
    --print-extras) PRINT_EXTRAS_ONLY=1 ;;
    --print-run-as) PRINT_RUN_AS_ONLY=1 ;;
esac

# ── Run as the host user ────────────────────────────────────────────────────
# The checkout is bind-mounted read-write, so as root everything the Gateway
# creates there (backend/.deer-flow, logs/, skills/custom, __pycache__) lands
# on the host owned by root, and `git pull` / `git clean` then fail for the
# normal user. This runs as root on purpose, not as a compose `user:`: only
# root can hand the named volumes (.venv, uv cache, camoufox) to the host uid
# and join a DooD socket's group, whose gid is only known here.
#
# Unset or 0 keeps the old run-as-root behavior (Docker Desktop, or an
# explicit DEER_FLOW_UID=0).
RUN_AS=""
if [ "$(id -u)" = "0" ] && [ -n "${DEER_FLOW_UID:-}" ] && [ "$DEER_FLOW_UID" != "0" ]; then
    RUN_UID="$DEER_FLOW_UID"
    RUN_GID="${DEER_FLOW_GID:-$DEER_FLOW_UID}"
    for id_value in "$RUN_UID" "$RUN_GID"; do
        case "$id_value" in
            '' | *[!0-9]*)
                echo "[startup] DEER_FLOW_UID/DEER_FLOW_GID must be numeric ids (got '$RUN_UID'/'$RUN_GID') — aborting" >&2
                exit 1
                ;;
        esac
    done
    RUN_GROUPS="--clear-groups"
    DOCKER_SOCKET="${DEER_FLOW_RUN_AS_DOCKER_SOCKET:-/var/run/docker.sock}"
    if [ -S "$DOCKER_SOCKET" ]; then
        RUN_GROUPS="--groups=$(stat -c %g "$DOCKER_SOCKET")"
    fi
    RUN_AS="setpriv --reuid=$RUN_UID --regid=$RUN_GID $RUN_GROUPS"
fi

if [ "$PRINT_RUN_AS_ONLY" = "1" ]; then
    printf '%s\n' "${RUN_AS:-as-is}"
    exit 0
fi

if [ -n "$RUN_AS" ] && [ "$PRINT_EXTRAS_ONLY" = "0" ]; then
    : "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"
    mkdir -p /app/logs "$DEER_FLOW_HOME" /app/backend/sandbox
    # Only root-owned entries change hands, so this is a no-op after the first
    # start and also heals a checkout an older root-run stack left behind.
    # /root holds HOME and the uv/camoufox volumes; the /app/project prunes
    # skip trees mounted twice (backend/, skills/, logs/) and large ones the
    # Gateway never writes. -h: never follow a symlink out of the tree.
    for claim_path in /root /app/logs /app/backend /app/skills /app/project; do
        [ -e "$claim_path" ] || continue
        find "$claim_path" \( -path /app/project/backend -o -path /app/project/skills -o -path /app/project/logs \
            -o -name node_modules -o -name .git -o -name .next \) -prune \
            -o -user 0 -exec chown -h "$RUN_UID:$RUN_GID" {} + ||
            echo "[startup] could not hand every root-owned path under $claim_path to $RUN_UID:$RUN_GID; continuing" >&2
    done
    echo "[startup] running as $RUN_UID:$RUN_GID ($RUN_GROUPS)" >&2
    # shellcheck disable=SC2086 # $RUN_AS is a fixed, validated argument list
    exec $RUN_AS -- sh "$0" "$@"
fi

# Mirror the legacy command's behavior: redirect both stdout and stderr to the
# host-mounted log file (../logs/gateway.log → /app/logs/gateway.log). Skip
# the redirect under --print-extras so the test runner can capture stdout.
if [ "$PRINT_EXTRAS_ONLY" = "0" ]; then
    exec >/app/logs/gateway.log 2>&1
fi

# ── Resolve extras ──────────────────────────────────────────────────────────

EXTRAS_FLAGS=""
EXTRA_NAMES=""
set -f

append_extra() {
    extra_name="$1"
    case "$extra_name" in
        [!A-Za-z]* | *[!A-Za-z0-9_-]*)
            echo "[startup] UV_EXTRAS entry '$extra_name' is invalid (must match [A-Za-z][A-Za-z0-9_-]*) — aborting" >&2
            exit 1
            ;;
    esac
    case " $EXTRA_NAMES " in
        *" $extra_name "*) return ;;
    esac
    EXTRA_NAMES="$EXTRA_NAMES $extra_name"
    EXTRAS_FLAGS="$EXTRAS_FLAGS --extra $extra_name"
}

# Validate explicit input before the detector normalizes it. The shared
# detector deliberately drops invalid names with a warning, while container
# startup fails closed so malformed .env input cannot be silently ignored.
if [ -n "${UV_EXTRAS:-}" ]; then
    for raw in $(printf '%s' "$UV_EXTRAS" | tr ',' ' '); do
        [ -z "$raw" ] || append_extra "$raw"
    done
fi

# Docker dev mounts the host checkout at /app/project while
# DEER_FLOW_PROJECT_ROOT points at /app for runtime path translation. Prefer
# both locations, then the checkout-relative path used by direct invocations.
ENTRYPOINT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DETECTOR_PATH=""
for candidate in \
    "${DEER_FLOW_PROJECT_ROOT:+$DEER_FLOW_PROJECT_ROOT/scripts/detect_uv_extras.py}" \
    /app/project/scripts/detect_uv_extras.py \
    "$ENTRYPOINT_DIR/../scripts/detect_uv_extras.py"
do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
        DETECTOR_PATH="$candidate"
        break
    fi
done
if [ -z "$DETECTOR_PATH" ]; then
    echo "[startup] scripts/detect_uv_extras.py is unavailable" >&2
    exit 1
fi
if command -v python3 >/dev/null 2>&1; then
    DETECTOR_PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    DETECTOR_PYTHON=python
else
    echo "[startup] Python is required to resolve optional dependencies" >&2
    exit 1
fi
if ! DETECTED_FLAGS=$("$DETECTOR_PYTHON" "$DETECTOR_PATH"); then
    echo "[startup] detect_uv_extras.py failed" >&2
    exit 1
fi

# The detector emits only validated `--extra NAME` pairs. Parse that small
# interface instead of evaluating shell text, and validate again at the final
# shell boundary before any value can reach uv.
set -- $DETECTED_FLAGS
while [ "$#" -gt 0 ]; do
    if [ "$1" != "--extra" ] || [ "$#" -lt 2 ]; then
        echo "[startup] detect_uv_extras.py returned invalid output" >&2
        exit 1
    fi
    append_extra "$2"
    shift 2
done

if [ "$PRINT_EXTRAS_ONLY" = "1" ]; then
    # Trim leading space for tidier output, then exit.
    printf '%s\n' "${EXTRAS_FLAGS# }"
    exit 0
fi

if [ -n "$EXTRAS_FLAGS" ]; then
    echo "[startup] uv extras:$EXTRAS_FLAGS"
fi

# Keep runtime-owned files out of uvicorn's reload watcher. Each excluded path
# must exist before uvicorn starts so watchfiles treats it as an excluded
# directory, not as a plain glob pattern — on Python 3.12, globbing an absolute
# pattern raises NotImplementedError and crashes startup (#3459 / #3454). That
# means `sandbox` must be created here too, not just `.deer-flow`.
: "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"
export DEER_FLOW_HOME
mkdir -p "$DEER_FLOW_HOME" /app/backend/.deer-flow /app/backend/sandbox

# ── Sync dependencies (with self-heal) ──────────────────────────────────────

cd /app/backend

# `--all-packages` propagates extras into workspace members (PR #2584).
# docker-compose-dev's default DEER_FLOW_STREAM_BRIDGE_REDIS_URL is translated
# to `--extra redis` by the shared detector, alongside config and UV_EXTRAS.
# `$EXTRAS_FLAGS` intentionally unquoted so each `--extra X` becomes its own arg.
# shellcheck disable=SC2086 # word-splitting is intentional here
if ! uv sync --locked --all-packages $EXTRAS_FLAGS; then
    echo "[startup] uv sync failed; recreating .venv and retrying once"
    uv venv --clear .venv
    # The retry keeps `--locked` on purpose: it repairs a corrupt or partial
    # .venv, not a lock that disagrees with pyproject.toml. Startup must never
    # silently resolve dependencies, so a second failure is fatal rather than
    # something uvicorn limps past and reports later as an import error.
    # `set -e` would already stop here; abort explicitly so the operator gets
    # the fix instead of a bare uv exit code.
    # shellcheck disable=SC2086
    if ! uv sync --locked --all-packages $EXTRAS_FLAGS; then
        echo "[startup] uv sync --locked failed again after recreating .venv." >&2
        echo "[startup] backend/uv.lock does not match backend/pyproject.toml, or a locked artifact is unreachable." >&2
        echo "[startup] Run 'make install' on the host to refresh the lock, then restart this container." >&2
        exit 1
    fi
fi

# ── Camoufox browser ────────────────────────────────────────────────────────
# When config selected the camoufox web_fetch backend, the `camoufox` uv extra
# was installed above; fetch the browser binaries too so the backend works
# without a manual `make fetch-browser`. Idempotent + best-effort: a no-op when
# camoufox is not installed or the browser is already present. Requires the
# repo `scripts/` dir mounted at /app/scripts (docker/docker-compose-dev.yaml);
# INSTALL_DIR (~/.cache/camoufox) is a named volume so the download survives
# container recreation.
if [ -f /app/scripts/ensure_camoufox.py ]; then
    uv run python /app/scripts/ensure_camoufox.py || true
fi

# ── Hand off to uvicorn ─────────────────────────────────────────────────────

PYTHONPATH=. exec uv run --no-sync uvicorn app.gateway.app:app \
    --host 0.0.0.0 --port 8001 \
    --reload \
    --reload-include='*.yaml' \
    --reload-include='.env' \
    --reload-exclude=/app/backend/sandbox \
    --reload-exclude="$DEER_FLOW_HOME" \
    --reload-exclude=/app/backend/.deer-flow
