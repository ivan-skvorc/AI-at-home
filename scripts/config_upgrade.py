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
    50: {
        "description": "Persist run events by default so scroll-back history survives a restart",
        # Anchored on the section header, so `backend: memory` under `database:`
        # (or any other section) is untouched. Both upgrade paths run this: the
        # text migration is applied to the raw file before it is re-parsed, so
        # the merge path re-dumps the migrated value rather than the old one.
        #
        # This rewrites a value the user may have set deliberately, which the
        # merge normally never does. It is the intended exception: `memory` is
        # a data-loss setting whose only symptom is a long conversation that
        # silently stops loading older messages after a Gateway restart, and
        # an install on `database.backend: memory` is unaffected either way
        # because make_run_event_store() falls back to the in-memory store when
        # there is no session factory to write through.
        "replacements": [("run_events:\n  backend: memory", "run_events:\n  backend: db")],
    },
    # Future migrations go here:
    # 51: {
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


def backfill_missing_default_tools(user: dict, example: dict) -> list[str]:
    """Append example ``tools:`` entries whose names are missing from the user list.

    ``merge_missing`` is dict-based, so a ``tools:`` list that exists but lost
    default entries (e.g. a wizard run that declined bash, or a config created
    before a tool existed) would stay reduced forever. The default toolset is
    meant to be available out of the box, so missing entries are appended,
    keyed by ``name`` — existing entries (a different web_search provider,
    customized settings) are never touched or duplicated. An appended ``bash``
    entry stays runtime-inactive on the local sandbox unless
    ``sandbox.allow_host_bash`` is true, so this cannot widen the security
    boundary.
    """
    example_tools = example.get("tools")
    user_tools = user.get("tools")
    if not isinstance(example_tools, list) or not isinstance(user_tools, list):
        # An absent tools section is handled wholesale by merge_missing.
        return []
    existing_names = {tool.get("name") for tool in user_tools if isinstance(tool, dict)}
    added = []
    for tool in example_tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if name and name not in existing_names:
            user_tools.append(copy.deepcopy(tool))
            added.append(f"tools[{name}]")
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
        # An equal version does not mean an equal shape. Upstream merges add
        # sections to config.example.yaml without touching config_version --
        # upstream's copy of it sits permanently behind the fork's, because the
        # fork bumps for its own sections and upstream never sees them. Trusting
        # the version alone here is what let the 2026-08-12 sync's `mcp_tasks:`
        # reach a fresh config.yaml and no existing one: the delivery silently
        # depended on a human noticing and bumping. Decide on the shape instead.
        #
        # Deliberately warn rather than deliver. This script runs on every launch
        # path, and the merge branch below rewrites through yaml.dump, which drops
        # every comment in the user's config. Silently rewriting a config -- and
        # destroying its inline documentation -- because the example grew a
        # section is a worse outcome than the missing section. So: name it, keep
        # the file byte-identical, and let the version bump stay the explicit gate.
        probe = copy.deepcopy(user)
        pending = merge_missing(probe, example)
        pending.extend(backfill_missing_default_tools(probe, example))
        if pending:
            print(f"! config.yaml is stamped current (version {user_version}) but is missing {len(pending)} field(s) the example ships:")
            for name in pending:
                print(f"    - {name}")
            print("  Nothing was written. If you maintain this fork, bump `config_version` in")
            print("  config.example.yaml (and both chart copies) so this reaches existing installs;")
            print("  upstream adds sections without bumping it. Then re-run `make config-upgrade`.")
            return 0
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
    added.extend(backfill_missing_default_tools(user, example))
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
