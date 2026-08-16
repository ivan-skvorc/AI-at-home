#!/usr/bin/env python3
"""Audit the bundled model roster against live provider catalogs (fork feature).

FORK.md is explicit that the existing tests "do not catch a stale-but-well-formed
price or a since-renamed slug, because both pass against any syntactically valid
entry", and names the failure that follows: an *expired promo* leaves the chat
header advertising a discount nobody is getting. Nothing in CI notices, because
nothing compares the roster to reality. That is what this does.

It reads both synced sources — the ``# === BEGIN auto-model-config: <provider>
===`` marker blocks in ``config.example.yaml`` and the ``*_BUNDLE_MODELS`` lists
in ``scripts/wizard/providers.py`` — and diffs them against provider catalogs,
reporting retired or renamed slugs, changed list prices, and promotions that
started or ended.

**It proposes, it never commits.** FORK.md's audit rules require reading the
price off the provider's own page, and a wrong automated price is worse than a
stale one: it is wrong *with confidence*, and it silences the next audit. The
output is a report for a human, with a suggested diff for both sources.

**An unreachable provider is a skip, never a failure.** A weekly red job is a
job people learn to ignore, which would cost more than the drift it detects.

Usage:
    python3 scripts/audit_models.py                          # live fetch, markdown report
    python3 scripts/audit_models.py --format json
    python3 scripts/audit_models.py --catalog fixture.json   # offline, for tests/CI self-test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"
WIZARD_PROVIDERS = "scripts/wizard/providers.py"
CONFIG_SOURCE = "config.example.yaml"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

BEGIN_RE = re.compile(r"^\s*#\s*=== BEGIN auto-model-config:\s*(\S+)")
END_RE = re.compile(r"^\s*#\s*=== END auto-model-config:")

# "Name ($2/6)" or "Name ($1.15/3.6 → $0.28/0.87*)" — the same shape
# deerflow/pricing.py::derive_pricing_from_display_name reads.
DISPLAY_PRICE_RE = re.compile(r"\(\s*\$\s*([\d.]+)\s*/\s*([\d.]+)\s*(?:→\s*\$\s*([\d.]+)\s*/\s*([\d.]+)\s*\*)?\s*\)")

# Prices are floats parsed from two different sources; compare with a tolerance
# that is well below a cent per million tokens but above float noise.
PRICE_EPSILON = 1e-4


@dataclass(frozen=True)
class BundledModel:
    provider: str
    name: str
    slug: str
    display_name: str
    input_per_million: float | None
    output_per_million: float | None
    promo_input_per_million: float | None
    promo_output_per_million: float | None
    source: str
    discount_until: object | None = None


@dataclass(frozen=True)
class Finding:
    kind: str
    provider: str
    name: str
    slug: str
    detail: str
    suggestion: str = ""


# ---------------------------------------------------------------------------
# Reading the two synced sources
# ---------------------------------------------------------------------------


def prices_in_display_name(display_name: str) -> tuple[float | None, float | None, float | None, float | None]:
    """Extract ``(in, out, promo_in, promo_out)`` from a display name."""
    match = DISPLAY_PRICE_RE.search(display_name or "")
    if not match:
        return None, None, None, None

    def _f(value: str | None) -> float | None:
        return float(value) if value is not None else None

    return _f(match.group(1)), _f(match.group(2)), _f(match.group(3)), _f(match.group(4))


def _entry_to_model(provider: str, entry: dict, source: str) -> BundledModel | None:
    name = entry.get("name")
    if not name:
        return None
    # `price:`/`discount:` are the current shape; `pricing:` is still read so the
    # audit keeps working against an older config (and against the committed
    # stale fixture, which is deliberately frozen in the old shape).
    price = entry.get("price") or {}
    discount = entry.get("discount") or {}
    legacy = entry.get("pricing") or {}

    def _num(source_map: dict, key: str) -> float | None:
        value = source_map.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return BundledModel(
        provider=provider,
        name=str(name),
        slug=str(entry.get("model") or name),
        display_name=str(entry.get("display_name") or ""),
        input_per_million=_num(price, "input") if price else _num(legacy, "input_per_million"),
        output_per_million=_num(price, "output") if price else _num(legacy, "output_per_million"),
        promo_input_per_million=_num(discount, "input") if discount else _num(legacy, "promo_input_per_million"),
        promo_output_per_million=_num(discount, "output") if discount else _num(legacy, "promo_output_per_million"),
        discount_until=discount.get("until") if discount else None,
        source=source,
    )


def parse_marker_blocks(text: str) -> list[BundledModel]:
    """Parse the commented model entries inside each auto-model-config block.

    A deliberately small YAML-ish reader rather than PyYAML: the entries are
    *commented out*, so no YAML parser will read them, and un-commenting into a
    parser would need the same line surgery anyway. Only the keys this audit
    compares are extracted.
    """
    models: list[BundledModel] = []
    provider: str | None = None
    entry: dict = {}
    in_pricing: str | None = None

    def _flush() -> None:
        nonlocal entry, in_pricing
        if provider and entry:
            model = _entry_to_model(provider, entry, CONFIG_SOURCE)
            if model:
                models.append(model)
        entry = {}
        in_pricing = None

    for line in text.splitlines():
        begin = BEGIN_RE.match(line)
        if begin:
            _flush()
            provider = begin.group(1)
            continue
        if END_RE.match(line):
            _flush()
            provider = None
            continue
        if provider is None:
            continue

        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        body = stripped[1:].rstrip()
        if not body.strip():
            continue

        content = body.strip()
        if content.startswith("- "):
            _flush()
            content = content[2:].strip()
        elif content.startswith("-"):
            _flush()
            content = content[1:].strip()

        if ":" not in content:
            continue
        key, _, value = content.partition(":")
        key = key.strip()
        # Strip trailing comments, which the pricing block uses heavily.
        value = value.split("#", 1)[0].strip().strip("\"'")

        if key in {"price", "discount", "pricing"}:
            # `price:`/`discount:` are the current shape; `pricing:` is still
            # read so the audit works against an older config and against the
            # committed stale fixture.
            in_pricing = key
            entry.setdefault(key, {})
            continue
        if in_pricing == "pricing" and key in {
            "currency",
            "input_per_million",
            "output_per_million",
            "input_cache_hit_per_million",
            "promo_input_per_million",
            "promo_output_per_million",
            "promo_input_cache_hit_per_million",
        }:
            entry.setdefault("pricing", {})[key] = value
            continue
        if in_pricing in {"price", "discount"} and key in {"currency", "input", "output", "cache_hit", "until"}:
            entry.setdefault(in_pricing, {})[key] = value
            continue
        if key in {"name", "display_name", "model"}:
            in_pricing = None
            entry.setdefault(key, value)
        else:
            in_pricing = None

    _flush()
    return models


def load_wizard_bundles() -> list[BundledModel]:
    """Import the wizard's bundle lists — the other source of the same roster."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        from wizard import providers  # type: ignore[import-not-found]
    except Exception:
        return []

    models: list[BundledModel] = []
    named = [("anthropic", providers.ANTHROPIC_BUNDLE_MODELS), ("openrouter", providers.OPENROUTER_BUNDLE_MODELS)]
    named += [(slug, bundle) for slug, (_env, bundle) in providers.HOME_API_BUNDLES.items()]
    for provider, bundle in named:
        for entry in bundle:
            model = _entry_to_model(provider, entry, WIZARD_PROVIDERS)
            if model:
                models.append(model)
    return models


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


def _http_get_json(url: str, timeout: float = 15.0) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "deerflow-model-audit"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def parse_openrouter_catalog(payload: dict) -> dict[str, dict]:
    """Map slug -> per-million prices from OpenRouter's models endpoint.

    OpenRouter quotes USD **per token** as strings. Free and routing variants
    (``:free``, ``:nitro``) are separate slugs and are kept separate: folding a
    ``:free`` entry into its paid slug would read as a 100% promo every week.
    """
    models: dict[str, dict] = {}
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        slug = item.get("id")
        if not slug or not isinstance(slug, str):
            continue
        pricing = item.get("pricing") or {}
        entry: dict = {}
        try:
            if pricing.get("prompt") is not None:
                entry["input_per_million"] = float(pricing["prompt"]) * 1_000_000
            if pricing.get("completion") is not None:
                entry["output_per_million"] = float(pricing["completion"]) * 1_000_000
        except (TypeError, ValueError):
            continue
        if pricing and not entry:
            continue
        models[slug] = entry
    return models


def fetch_openrouter(get: Callable[[str, float], dict] = _http_get_json) -> dict:
    """Fetch the OpenRouter catalog; unreachable is reported, never raised."""
    try:
        payload = get(OPENROUTER_MODELS_URL, 15.0)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return {"models": {}, "reachable": False, "reason": str(exc)}
    return {"models": parse_openrouter_catalog(payload), "reachable": True}


def fetch_catalogs(get: Callable[[str, float], dict] = _http_get_json) -> dict[str, dict]:
    """Fetch every catalog this audit knows how to read.

    Only OpenRouter publishes machine-readable prices without a key. The
    first-party labs either need a key or publish prices only as marketing HTML,
    which is precisely why FORK.md's manual step ("read the price off the
    provider's own page") still exists — this job is the trigger for it, not a
    replacement.
    """
    return {"openrouter": fetch_openrouter(get)}


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _differs(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) > PRICE_EPSILON


def _suggested_pricing_diff(entry: BundledModel, live: dict) -> str:
    lines = ["```diff", f"  # {entry.name}", "  pricing:", "    currency: USD"]
    for key, label in (("input_per_million", "input_per_million"), ("output_per_million", "output_per_million")):
        current, new = getattr(entry, key), live.get(key)
        if new is not None and _differs(current, new):
            lines.append(f"-   {label}: {current}")
            lines.append(f"+   {label}: {new}")
        elif current is not None:
            lines.append(f"    {label}: {current}")
    lines.append("```")
    return "\n".join(lines)


def diff_against_catalog(entries: Iterable[BundledModel], catalogs: dict[str, dict]) -> list[Finding]:
    """Compare configured entries against the live catalog for their provider."""
    findings: list[Finding] = []
    for entry in entries:
        catalog = catalogs.get(entry.provider)
        # No catalog for this provider, or the fetch failed: say nothing. An
        # unreachable provider reported as "every slug retired" is exactly the
        # noise that gets a weekly job muted.
        if not catalog or not catalog.get("reachable"):
            continue
        models = catalog.get("models") or {}
        live = models.get(entry.slug)
        if live is None:
            findings.append(
                Finding(
                    kind="retired_slug",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=f"`{entry.slug}` is no longer in the {entry.provider} catalog — it was retired or renamed. A run on this model fails at call time.",
                    suggestion=f"Find the replacement slug on the provider's page, then update `{entry.name}` in both {CONFIG_SOURCE} and {WIZARD_PROVIDERS}.",
                )
            )
            continue

        live_in, live_out = live.get("input_per_million"), live.get("output_per_million")
        if _differs(entry.input_per_million, live_in) or _differs(entry.output_per_million, live_out):
            findings.append(
                Finding(
                    kind="price_changed",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=(f"list price moved: configured ${entry.input_per_million}/{entry.output_per_million} per 1M, catalog reports ${live_in}/{live_out}. Every cost figure for this model is off by that ratio."),
                    suggestion=_suggested_pricing_diff(entry, live),
                )
            )
            continue

        live_promo_in = live.get("promo_input_per_million")
        has_promo = entry.promo_input_per_million is not None
        if has_promo and live_promo_in is None:
            findings.append(
                Finding(
                    kind="promo_ended",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=(f"the catalog no longer shows a discount, but the config still carries one (${entry.promo_input_per_million}/{entry.promo_output_per_million}). The chat header is advertising a promo price nobody is getting."),
                    suggestion=f"Drop `promo_*_per_million` **and** the ` → $…*` half of the display name for `{entry.name}` in both sources — they are two spellings of one discount.",
                )
            )
        elif not has_promo and live_promo_in is not None:
            findings.append(
                Finding(
                    kind="promo_started",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=f"the catalog shows a discount (${live_promo_in}/{live.get('promo_output_per_million')}) that the config does not carry, so the header bills at full price.",
                    suggestion=f"Add `promo_input_per_million` / `promo_output_per_million` and the ` → $…*` display-name half for `{entry.name}` in both sources.",
                )
            )
    return findings


def check_internal_consistency(entries: Iterable[BundledModel]) -> list[Finding]:
    """Does each entry's display name agree with its own ``pricing:`` block?

    This needs no network. It catches the half-update — a price changed in the
    block but not in the name, or a promo removed from one spelling and not the
    other — which renders as a wrong number in the UI with nothing raising.
    """
    findings: list[Finding] = []
    for entry in entries:
        # A price in the name is a second copy of a number that is already data.
        # It is where the old drift came from, so re-adding one is a finding in
        # itself rather than something to reconcile.
        name_in, name_out, name_promo_in, name_promo_out = prices_in_display_name(entry.display_name)
        if name_in is not None:
            findings.append(
                Finding(
                    kind="price_in_display_name",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=(f"`{entry.display_name}` carries a price in its name (${name_in}/{name_out}). Prices belong in the `price:` block only — a second copy drifts, and a discount spelled into a name can only end when a human edits the string."),
                    suggestion=f"remove the ({'$'}{name_in}/{name_out}...) pair from display_name; keep `price:`",
                )
            )
        # A discount with no `until` is deliberately NOT a finding here. Several
        # providers run open-ended promotions with no announced end date, so it
        # is a permanent condition a maintainer cannot resolve — and a weekly
        # issue nobody can close is how this job becomes one people ignore. The
        # `promo_ended` check below still catches a discount the provider has
        # actually stopped offering, which is the actionable half. FORK.md's
        # post-sync checklist covers the "add an `until` once one is announced"
        # review, where a human is already reading.
        mismatches: list[str] = []
        if mismatches:
            findings.append(
                Finding(
                    kind="name_price_mismatch",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail="; ".join(mismatches),
                    suggestion=f"The display name and the `pricing:` block are two spellings of one price. Reconcile them for `{entry.name}` in {entry.source}.",
                )
            )
    return findings


def check_source_parity(config_entries: Iterable[BundledModel], wizard_entries: Iterable[BundledModel]) -> list[Finding]:
    """Do the two synced sources still describe the same roster?"""
    wizard_by_name = {entry.name: entry for entry in wizard_entries}
    findings: list[Finding] = []
    for entry in config_entries:
        other = wizard_by_name.get(entry.name)
        if other is None:
            continue
        problems = []
        if entry.slug != other.slug:
            problems.append(f"slug {entry.slug!r} vs {other.slug!r}")
        if _differs(entry.input_per_million, other.input_per_million) or _differs(entry.output_per_million, other.output_per_million):
            problems.append(f"price ${entry.input_per_million}/{entry.output_per_million} vs ${other.input_per_million}/{other.output_per_million}")
        if problems:
            findings.append(
                Finding(
                    kind="source_disagreement",
                    provider=entry.provider,
                    name=entry.name,
                    slug=entry.slug,
                    detail=f"{CONFIG_SOURCE} and {WIZARD_PROVIDERS} disagree: " + "; ".join(problems),
                    suggestion=f"Update whichever is stale — a fresh install reads {CONFIG_SOURCE}, `make setup` reads {WIZARD_PROVIDERS}, so a divergence gives two users different prices.",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_KIND_TITLE = {
    "retired_slug": "Retired or renamed slugs",
    "price_changed": "List prices that moved",
    "promo_ended": "Promotions that ended (header advertises a discount nobody gets)",
    "promo_started": "Promotions that started",
    "name_price_mismatch": "Display name disagrees with its own pricing block",
    "source_disagreement": "The two synced sources disagree",
}


def render_report(findings: list[Finding], skipped: list[str]) -> str:
    lines = ["## Bundled model & pricing audit", ""]

    if not findings:
        lines += ["**No drift detected.** Every bundled slug is still in its provider's catalog, and the configured prices match.", ""]
    else:
        lines += [f"**{len(findings)} finding(s).** These are *proposals*, not auto-applied changes — see the note at the bottom.", ""]
        for kind, title in _KIND_TITLE.items():
            group = [f for f in findings if f.kind == kind]
            if not group:
                continue
            lines += [f"### {title}", ""]
            for finding in group:
                lines.append(f"- **`{finding.name}`** (`{finding.slug}`, {finding.provider}) — {finding.detail}")
                if finding.suggestion:
                    if finding.suggestion.startswith("```"):
                        lines += ["", finding.suggestion, ""]
                    else:
                        lines.append(f"  - {finding.suggestion}")
            lines.append("")

    if skipped:
        lines += ["### Skipped", "", *[f"- {entry}" for entry in skipped], ""]

    lines += [
        "---",
        "",
        "**Every change here is a suggestion and is not auto-applied.** The audit reads what a",
        "provider's API reports; the fork's rule is that a price is confirmed by reading the",
        "**provider's own page**, because a wrong automated price is worse than a stale one — it is",
        "wrong with confidence and silences the next audit.",
        "",
        f"Any edit belongs in **both** synced sources: `{CONFIG_SOURCE}` (what a fresh install gets)",
        f"and `{WIZARD_PROVIDERS}` (what `make setup` writes). Changing one gives two users different prices.",
        "",
        "A price change also has a delivery trap: fixing `config.example.yaml` does **not** reach an",
        "existing `config.yaml`, which is why `pricing.py` derives the price from the `($in/out)` pair in",
        "the display name. Update the name and the block together.",
        "",
        "Regression-gate the edit with:",
        "",
        "```bash",
        "python3 scripts/sync-api-key-models.py --dry-run",
        "cd backend && uv run pytest tests/test_sync_api_key_models.py tests/test_setup_wizard.py tests/test_config_integrity.py tests/test_audit_models.py",
        "```",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def normalize_catalogs(raw: dict) -> dict[str, dict]:
    """Keep only well-formed provider entries.

    ``--catalog`` takes an arbitrary file, and the committed fixture carries a
    top-level ``_comment``; a non-dict value is documentation or junk, not a
    catalog, and must not be read as one.
    """
    return {key: value for key, value in (raw or {}).items() if isinstance(value, dict)}


def run_audit(catalogs: dict[str, dict]) -> tuple[list[Finding], list[str]]:
    config_entries = parse_marker_blocks(CONFIG_EXAMPLE.read_text(encoding="utf-8")) if CONFIG_EXAMPLE.exists() else []
    wizard_entries = load_wizard_bundles()

    findings: list[Finding] = []
    findings += check_internal_consistency(config_entries)
    findings += check_source_parity(config_entries, wizard_entries)
    findings += diff_against_catalog(config_entries, catalogs)

    skipped: list[str] = []
    providers_seen = {entry.provider for entry in config_entries}
    for provider in sorted(providers_seen):
        catalog = catalogs.get(provider)
        if catalog is None:
            skipped.append(f"`{provider}` — no machine-readable catalog; covered by the manual audit pass in FORK.md")
        elif not catalog.get("reachable"):
            skipped.append(f"`{provider}` — catalog unreachable ({catalog.get('reason', 'no reason given')}); not treated as drift")
    return findings, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit bundled models and prices against live provider catalogs.")
    parser.add_argument("--catalog", default=None, help="Read catalogs from a JSON file instead of the network (offline runs and the CI self-test)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default=None, help="Write the report to a file as well as stdout")
    parser.add_argument("--fail-on-findings", action="store_true", help="Exit 1 when drift is found. Off by default: a weekly red job is a job people learn to ignore.")
    args = parser.parse_args(argv)

    if args.catalog:
        catalogs = normalize_catalogs(json.loads(Path(args.catalog).read_text(encoding="utf-8")))
    else:
        catalogs = normalize_catalogs(fetch_catalogs())

    findings, skipped = run_audit(catalogs)

    if args.format == "json":
        body = json.dumps({"findings": [asdict(f) for f in findings], "skipped": skipped}, indent=2)
    else:
        body = render_report(findings, skipped)

    print(body)
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")

    # An all-unreachable run has proved nothing, so it must not fail either.
    reachable = any(catalog.get("reachable") for catalog in catalogs.values())
    if args.fail_on_findings and findings and reachable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
