#!/usr/bin/env python3
"""Upgrade config.yaml to match config.example.yaml.

Called by scripts/config-upgrade.sh (which resolves the file locations and the
Python environment). Kept as a real module — not inline shell Python — so the
behavior is unit-testable (backend/tests/test_config_upgrade_script.py).

Behavior:
1. Refuses to touch a config.yaml with duplicate keys (names the key and both
   line numbers) — PyYAML's last-key-wins would otherwise silently drop the
   first occurrence during the merge.
2. Runs version-specific text migrations (value replacements/renames).
3. Merges missing fields from the example into the user config. The merge is
   dict-based and only ever *adds missing keys* — it never appends a section
   that already exists.
4. Idempotent: exits without writing when the config is already at the example
   version. When only the version stamp changes (no migrations, no new keys),
   the version line is rewritten in place so user comments survive; a full
   structural re-dump happens only when new keys must be inserted.
5. Backs up config.yaml to config.yaml.bak before any write.
"""

from __future__ import annotations

import copy
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import yaml

# ── Migrations ───────────────────────────────────────────────────────────────
# Each migration targets a specific version upgrade.
# 'replacements': list of (old_string, new_string) applied to the raw YAML text.
#   This handles value changes that a dict merge cannot catch.

MIGRATIONS = {
    1: {
        "description": "Rename src.* module paths to deerflow.*",
        "replacements": [
            ("src.community.", "deerflow.community."),
            ("src.sandbox.", "deerflow.sandbox."),
            ("src.models.", "deerflow.models."),
            ("src.tools.", "deerflow.tools."),
        ],
    },
    # Future migrations go here:
    # 2: {
    #     'description': '...',
    #     'replacements': [('old', 'new')],
    # },
}


def load_yaml_guard(repo_root: Path):
    """Return (safe_load_guarded, DuplicateKeyError) from the shared harness module.

    Prefers the installed ``deerflow`` package (the .sh wrapper runs this under
    the backend uv environment); falls back to loading the file directly so the
    script also works under a bare python3 that only has PyYAML.
    """
    try:
        from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded

        return safe_load_guarded, DuplicateKeyError
    except ImportError:
        guard_path = repo_root / "backend" / "packages" / "harness" / "deerflow" / "config" / "yaml_guard.py"
        spec = importlib.util.spec_from_file_location("_deerflow_yaml_guard", guard_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.safe_load_guarded, module.DuplicateKeyError


def merge_missing(target: dict, source: dict, path: str = "") -> list[str]:
    """Recursively merge source into target, adding missing keys only."""
    added = []
    for key, value in source.items():
        key_path = f"{path}.{key}" if path else key
        if key not in target:
            target[key] = copy.deepcopy(value)
            added.append(key_path)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            added.extend(merge_missing(target[key], value, key_path))
    return added


def replace_version_line(raw_text: str, new_version: int) -> str | None:
    """Rewrite the config_version line in place; None if it isn't present."""
    new_text, count = re.subn(r"(?m)^config_version:.*$", f"config_version: {new_version}", raw_text, count=1)
    return new_text if count else None


def upgrade(config_path: Path, example_path: Path, repo_root: Path) -> int:
    safe_load_guarded, duplicate_key_error = load_yaml_guard(repo_root)

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        user = safe_load_guarded(raw_text, source=str(config_path)) or {}
    except duplicate_key_error as exc:
        print(f"✗ {exc}")
        print("  Remove one of the duplicate sections from config.yaml, then retry.")
        return 1

    with open(example_path, encoding="utf-8") as f:
        example = safe_load_guarded(f) or {}

    user_version = user.get("config_version", 0)
    example_version = example.get("config_version", 0)

    if user_version >= example_version:
        print(f"OK config.yaml is already up to date (version {user_version}).")
        return 0

    print(f"Upgrading config.yaml: version {user_version} -> {example_version}")
    print()

    # Apply migrations in order for versions (user_version, example_version]
    migrated = []
    for version in range(user_version + 1, example_version + 1):
        migration = MIGRATIONS.get(version)
        if not migration:
            continue
        for old, new in migration.get("replacements", []):
            if old in raw_text:
                raw_text = raw_text.replace(old, new)
                migrated.append(f"{old} -> {new}")

    # Re-parse after text migrations
    user = safe_load_guarded(raw_text, source=str(config_path)) or {}

    if migrated:
        print(f"Applied {len(migrated)} migration(s):")
        for m in migrated:
            print(f"  ~ {m}")
        print()

    added = merge_missing(user, example)
    user["config_version"] = example_version

    backup = config_path.with_suffix(".yaml.bak")
    shutil.copy2(config_path, backup)
    print(f"Backed up to {backup.name}")

    if added:
        # New keys must be inserted structurally — full re-dump (comments in
        # the user file are lost on this path; the backup keeps them).
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(user, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        print(f"Added {len(added)} new field(s):")
        for a in added:
            print(f"  + {a}")
    else:
        # Version stamp (plus any text migrations) only: rewrite the raw text
        # so user comments and layout survive.
        new_text = replace_version_line(raw_text, example_version)
        if new_text is None:
            new_text = f"config_version: {example_version}\n{raw_text}"
        config_path.write_text(new_text, encoding="utf-8")
        print("No changes needed (version bumped only).")

    print()
    print(f"OK config.yaml upgraded to version {example_version}.")
    print("  Please review the changes and set any new required values.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: config_upgrade.py CONFIG_PATH EXAMPLE_PATH", file=sys.stderr)
        return 2
    config_path = Path(argv[1])
    example_path = Path(argv[2])
    repo_root = Path(__file__).resolve().parent.parent
    if not example_path.is_file():
        print(f"✗ config.example.yaml not found at {example_path}")
        return 1
    return upgrade(config_path, example_path, repo_root)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
