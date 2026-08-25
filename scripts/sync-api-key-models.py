#!/usr/bin/env python3
"""Auto-enable the API-key model blocks in config.yaml based on the keys in .env.

A "quality of life" companion to ``scripts/sync-ollama-models.py``: it runs on
every launch path and, when it finds a real provider API key in your ``.env``
(or the process environment), uncomments the matching ready-to-use model block
in ``config.yaml`` so the models light up on first start with no manual editing.

    ANTHROPIC_API_KEY  -> direct Claude Fable 5 / Opus 5 / Opus 4.8 / Sonnet 5 /
                          Sonnet 4.6 / Haiku 4.5
    OPENROUTER_API_KEY -> Claude Fable 5 / Grok 4.6 /
                          GPT-5.6 Sol / GPT-5.3 Codex / MiniMax M3 /
                          Qwen3.8 Max / Kimi K3 / Mistral Large 3 /
                          Gemini 3.6 Flash / DeepSeek V4 Pro / GLM-5.3 /
                          Llama 4 Maverick / Nemotron 3 Ultra (all via OpenRouter)

Every big-name lab that ships a first-party API also gets a "home" block enabled
by that lab's own key, mirroring how Anthropic is handled — the lab's full lineup
on its direct API, so its flagship is reachable through both the home API and
OpenRouter:

    OPENAI_API_KEY     -> GPT-5.6 Sol / GPT-5.3 Codex / GPT-5.6 Mini (OpenAI)
    XAI_API_KEY        -> Grok 4.6 / Grok 4.5 Fast (xAI)
    GEMINI_API_KEY     -> Gemini 3.6 Flash / 3.5 Flash-Lite / 3.1 Pro (Google)
    DEEPSEEK_API_KEY   -> DeepSeek V4 Pro / V4 Flash (DeepSeek)
    MISTRAL_API_KEY    -> Mistral Large 3 / Medium 3.5 / Small 3 (Mistral)
    MOONSHOT_API_KEY   -> Kimi K3 / Kimi K2.6 (Moonshot)
    DASHSCOPE_API_KEY  -> Qwen3.8 Max / Qwen3.7 Plus (Qwen)
    MINIMAX_API_KEY    -> MiniMax M3 / MiniMax M2.7 (MiniMax)
    ZAI_API_KEY        -> GLM-5.3 / GLM-5.2 Air (z-ai)

Idempotent and bounded: the script only ever *uncomments* the model entries
between a provider's ``BEGIN/END auto-model-config`` markers, and never touches
anything outside them. It never re-comments a block (so a model you enabled by
hand is left alone) and skips a provider whose models are already active, so a
config edited by ``make setup`` or by hand is never duplicated. A provider whose
key is missing (or still a placeholder like ``your-...``) is left commented. If
the markers are absent (an older ``config.yaml`` predating this feature) the run
is a clean no-op.

Usage:
    python3 scripts/sync-api-key-models.py [--config PATH] [--env-file PATH]
                                           [--dry-run] [--verbose]

Environment:
    Keys are read from the process environment first (``make dev`` / serve.sh
    source ``.env`` before launch), then from the ``.env`` file directly so the
    Docker launch paths work even when ``.env`` was not exported.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Provider slug (used in the config markers) -> environment variable that gates it.
# The two aggregator keys (Anthropic direct, OpenRouter routed) plus a first-party
# "home" block for every big-name lab that ships its own API — enabled when THAT
# lab's own key is present, so a lab's flagship is reachable through both its home
# API and OpenRouter (see config.example.yaml's FIRST-PARTY HOME API BLOCKS).
PROVIDERS: list[tuple[str, str]] = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openrouter", "OPENROUTER_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("xai", "XAI_API_KEY"),
    ("google", "GEMINI_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("moonshot", "MOONSHOT_API_KEY"),
    ("qwen", "DASHSCOPE_API_KEY"),
    ("minimax", "MINIMAX_API_KEY"),
    ("zai", "ZAI_API_KEY"),
]

BEGIN_MARKER = "BEGIN auto-model-config: {slug}"
END_MARKER = "END auto-model-config: {slug}"

# Values that are obviously not real keys: the .env.example placeholders, empty
# strings, and unresolved "$VAR" references. Matched case-insensitively on the
# stripped value.
_PLACEHOLDER_PREFIXES = ("your-", "your_", "changeme", "replace-me", "replace_me", "<")


def looks_like_real_key(value: str | None) -> bool:
    """Return True when *value* looks like a genuine API key, not a placeholder."""
    if not value:
        return False
    stripped = value.strip().strip("\"'")
    if not stripped:
        return False
    if stripped.startswith("$"):  # unresolved "$OTHER_VAR" reference
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _PLACEHOLDER_PREFIXES):
        return False
    return True


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv file into a plain dict; missing/unreadable file -> {}.

    Deliberately small (no python-dotenv dependency, mirroring the no-PyYAML rule
    of sync-ollama-models.py): handles ``KEY=VALUE``, an optional ``export``
    prefix, surrounding quotes, and ``#`` comment lines.
    """
    values: dict[str, str] = {}
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        # Drop an inline comment on unquoted values, then strip matching quotes.
        value = value.strip()
        if value[:1] not in {'"', "'"} and "#" in value:
            value = value.split("#", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def key_present(env_var: str, env_file: dict[str, str]) -> bool:
    """Return True when *env_var* holds a real key in the process env or .env."""
    return looks_like_real_key(os.environ.get(env_var)) or looks_like_real_key(env_file.get(env_var))


def check_duplicate_top_level_keys(text: str, path) -> None:
    """Abort when a top-level YAML key appears twice.

    Mirrors sync-ollama-models.py / config/yaml_guard.py: a duplicated top-level
    key (e.g. two ``models:`` blocks) would make edits land in a section the
    application never sees. Pure-text scan — this script runs under plain
    python3 with no PyYAML.
    """
    top_key = re.compile(r"^([A-Za-z_][\w-]*):")
    seen: dict[str, int] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = top_key.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in seen:
            raise SystemExit(f"ERROR: duplicate top-level key '{key}' in {path}: first defined at line {seen[key]}, duplicated at line {lineno}\nRemove one of the duplicate sections from config.yaml, then retry.")
        seen[key] = lineno


def find_block(lines: list[str], slug: str) -> tuple[int, int] | None:
    """Return (begin_index, end_index) of a provider's marker block, or None.

    The indices point at the BEGIN and END marker lines themselves; the managed
    model entries are the lines strictly between them.
    """
    begin_needle = BEGIN_MARKER.format(slug=slug)
    end_needle = END_MARKER.format(slug=slug)
    begin = end = None
    for i, line in enumerate(lines):
        if begin is None:
            if begin_needle in line:
                begin = i
        elif end_needle in line:
            end = i
            break
    if begin is None or end is None:
        return None
    return begin, end


def active_model_names(text: str) -> set[str]:
    """Return the set of `- name:` values on non-commented (active) model lines."""
    names: set[str] = set()
    pattern = re.compile(r"^\s*-\s*name:\s*(\S+)")
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = pattern.match(line)
        if match:
            names.add(match.group(1))
    return names


def block_model_names(lines: list[str], begin: int, end: int) -> set[str]:
    """Return the `name:` values declared (commented or not) inside a block."""
    names: set[str] = set()
    pattern = re.compile(r"^\s*(?:#\s*)?-\s*name:\s*(\S+)")
    for line in lines[begin + 1 : end]:
        match = pattern.match(line)
        if match:
            names.add(match.group(1))
    return names


def uncomment_line(line: str) -> str:
    """Strip a single leading `# ` (preserving indentation) from a comment line.

    ``  # - name: x`` -> ``  - name: x`` and ``  #   key: v`` -> ``    key: v``.
    Lines that become whitespace-only are collapsed to empty. Inline ``#`` (e.g.
    a trailing YAML comment) is untouched because only the first, leading ``#``
    is removed.
    """
    new = re.sub(r"^(\s*)#\s?", r"\1", line, count=1)
    return "" if new.strip() == "" else new


def sync(text: str, present_slugs: set[str], *, verbose: bool = False) -> str:
    """Return config text with the marker blocks for *present_slugs* uncommented."""
    lines = text.splitlines()
    active = active_model_names(text)

    for slug, _env_var in PROVIDERS:
        if slug not in present_slugs:
            continue
        block = find_block(lines, slug)
        if block is None:
            if verbose:
                print(f"[api-key-sync] no '{slug}' marker block in config; skipping", file=sys.stderr)
            continue
        begin, end = block
        # Skip when any of the block's models is already an active entry, so a
        # config written by `make setup` (or hand-edited) is never duplicated.
        already = block_model_names(lines, begin, end) & active
        if already:
            if verbose:
                print(f"[api-key-sync] '{slug}' models already active ({', '.join(sorted(already))}); skipping", file=sys.stderr)
            continue
        for i in range(begin + 1, end):
            lines[i] = uncomment_line(lines[i])
        if verbose:
            print(f"[api-key-sync] enabled '{slug}' model block", file=sys.stderr)

    out = "\n".join(lines)
    if text.endswith("\n") and not out.endswith("\n"):
        out += "\n"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    repo_root = Path(__file__).resolve().parent.parent
    ap.add_argument("--config", default=str(repo_root / "config.yaml"))
    ap.add_argument("--env-file", default=str(repo_root / ".env"), help="dotenv file to read keys from (default: repo-root .env)")
    ap.add_argument("--dry-run", action="store_true", help="Print result to stdout, do not write")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        if args.verbose:
            print(f"[api-key-sync] {config_path} not found; skipping (no changes)", file=sys.stderr)
        return 0

    original = config_path.read_text()
    check_duplicate_top_level_keys(original, config_path)

    env_file = parse_env_file(Path(args.env_file))
    present = {slug for slug, env_var in PROVIDERS if key_present(env_var, env_file)}
    if args.verbose:
        detected = ", ".join(sorted(env_var for slug, env_var in PROVIDERS if slug in present)) or "none"
        print(f"[api-key-sync] provider keys detected: {detected}", file=sys.stderr)

    if not present and not args.dry_run:
        return 0

    updated = sync(original, present, verbose=args.verbose)

    if args.dry_run:
        sys.stdout.write(updated)
        return 0

    if updated == original:
        if args.verbose:
            print("[api-key-sync] no changes", file=sys.stderr)
        return 0

    config_path.write_text(updated)
    print(f"[api-key-sync] updated {config_path} (enabled: {', '.join(sorted(present))})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
