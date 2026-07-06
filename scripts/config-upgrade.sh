#!/usr/bin/env bash
#
# config-upgrade.sh - Upgrade config.yaml to match config.example.yaml
#
# Thin wrapper: resolves the config file locations and the Python environment,
# then delegates to scripts/config_upgrade.py (unit-testable), which:
# 1. Refuses duplicate-keyed configs (names the key and both line numbers)
# 2. Runs version-specific migrations (value replacements, renames, etc.)
# 3. Merges missing fields from the example into the user config
# 4. Backs up config.yaml to config.yaml.bak before modifying.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE="$REPO_ROOT/config.example.yaml"

# Resolve config.yaml location: env var > backend/ > repo root
if [ -n "$DEER_FLOW_CONFIG_PATH" ] && [ -f "$DEER_FLOW_CONFIG_PATH" ]; then
    CONFIG="$DEER_FLOW_CONFIG_PATH"
elif [ -f "$REPO_ROOT/backend/config.yaml" ]; then
    CONFIG="$REPO_ROOT/backend/config.yaml"
elif [ -f "$REPO_ROOT/config.yaml" ]; then
    CONFIG="$REPO_ROOT/config.yaml"
else
    CONFIG=""
fi

if [ ! -f "$EXAMPLE" ]; then
    echo "✗ config.example.yaml not found at $EXAMPLE"
    exit 1
fi

if [ -z "$CONFIG" ]; then
    echo "No config.yaml found — creating from example..."
    cp "$EXAMPLE" "$REPO_ROOT/config.yaml"
    echo "OK config.yaml created. Please review and set your API keys."
    exit 0
fi

if command -v cygpath >/dev/null 2>&1; then
    CONFIG_WIN="$(cygpath -w "$CONFIG")"
    EXAMPLE_WIN="$(cygpath -w "$EXAMPLE")"
    SCRIPT_WIN="$(cygpath -w "$REPO_ROOT/scripts/config_upgrade.py")"
else
    CONFIG_WIN="$CONFIG"
    EXAMPLE_WIN="$EXAMPLE"
    SCRIPT_WIN="$REPO_ROOT/scripts/config_upgrade.py"
fi

cd "$REPO_ROOT/backend" && uv run python "$SCRIPT_WIN" "$CONFIG_WIN" "$EXAMPLE_WIN"
