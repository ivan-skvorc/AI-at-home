#!/usr/bin/env bash
#
# backend-python.sh - run a repo script that needs only PyYAML.
#
# Usage: bash scripts/backend-python.sh SCRIPT [ARGS...]
#
# Where `make install` ran, the backend environment is the right interpreter:
# `uv run python` inside backend/ has PyYAML and the deerflow package. A
# Docker-only host (`make up`) has neither uv nor backend/.venv, and `uv run`
# without a .venv would first install every backend dependency just to edit
# config.yaml. So: uv when both uv and backend/.venv exist, otherwise the host
# python3/python if it can import yaml, otherwise stop and say what to install.
#
# Used by scripts/config-upgrade.sh and `make sandbox-enable/disable`. Pinned by
# backend/tests/test_backend_python_fallback.py.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -lt 1 ]; then
    echo "usage: $0 SCRIPT [ARGS...]" >&2
    exit 2
fi

script="$1"
shift
# The uv branch runs from backend/, so a relative path must be anchored first.
# C:\... and C:/... (cygpath -w output from config-upgrade.sh) are absolute.
case "$script" in
    /* | [A-Za-z]:*) ;;
    *) script="$PWD/$script" ;;
esac

if command -v uv >/dev/null 2>&1 && [ -d "$REPO_ROOT/backend/.venv" ]; then
    cd "$REPO_ROOT/backend"
    exec uv run python "$script" "$@"
fi

# `import yaml` doubles as a liveness probe: the Windows Store python3 alias
# answers `command -v` but cannot run anything.
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
        exec "$candidate" "$script" "$@"
    fi
done

echo "✗ $(basename "$script") needs Python 3 with PyYAML." >&2
echo "  Either run 'make install' (uv + backend/.venv), or install PyYAML for the" >&2
echo "  host interpreter (e.g. 'sudo apt install python3-yaml' or 'python3 -m pip install --user pyyaml')." >&2
exit 1
