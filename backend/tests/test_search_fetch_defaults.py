"""Shipped defaults for the two tools that reach the internet.

Both defaults were set for a fast, unfiltered connection and fail on the
configuration this fork actually targets — a self-hosted stack behind a
commercial VPN, which is the normal shape for a privacy-motivated deployment.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"
SEARXNG_SETTINGS = REPO_ROOT / "docker" / "searxng" / "settings.yml"

# Engines that tolerate datacenter and VPN exit IPs. The stock SearXNG default
# set leans on Google CSE, DuckDuckGo, Brave and Startpage, all of which
# CAPTCHA or block shared ranges aggressively — so a VPN user gets zero results
# with every engine suspended for ~180s, and the retry extends the suspension.
# Deliberately NOT brave/duckduckgo/startpage/"google cse": those are the four
# that were observed failing together on a VPN exit, so adding them back as a
# "fallback" would be adding more of the same failure.
VPN_TOLERANT_ENGINES = ("mojeek", "qwant", "bing", "yep", "mwmbl", "seznam", "presearch", "yahoo")


class TestWebFetchTimeout:
    """Camoufox is a full Firefox render, not an HTTP GET."""

    def test_web_fetch_timeout_is_not_the_old_ten_seconds(self):
        text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
        block = re.search(r"^  - name: web_fetch$(.*?)(?=^  - name: |\Z)", text, re.MULTILINE | re.DOTALL)
        assert block, "web_fetch tool block not found in config.example.yaml"
        timeout = re.search(r"^\s*timeout:\s*(\d+)", block.group(1), re.MULTILINE)
        assert timeout, "web_fetch has no timeout"
        # 10s fails on most JS-heavy sites even on a fast connection, and far
        # more often over a VPN; with `fallback:` commented out, one timeout
        # takes the tool down for the rest of the run.
        assert int(timeout.group(1)) >= 30


class TestSearxngEngineMix:
    """A blocked consumer engine must degrade, not zero out the whole search."""

    def test_settings_enable_at_least_one_vpn_tolerant_engine(self):
        data = yaml.safe_load(SEARXNG_SETTINGS.read_text(encoding="utf-8"))
        engines = data.get("engines") or []
        names = {str(e.get("name", "")).lower() for e in engines if isinstance(e, dict)}
        enabled = {str(e.get("name", "")).lower() for e in engines if isinstance(e, dict) and e.get("disabled") is False}
        assert names, "settings.yml declares no engines: the stock default mix blocks VPN exits"
        assert enabled & set(VPN_TOLERANT_ENGINES), f"no VPN-tolerant engine enabled; found {sorted(enabled)}"

    def test_the_json_format_and_limiter_deltas_survive(self):
        # The two deltas that make the instance usable at all; an engine edit
        # must not drop them.
        data = yaml.safe_load(SEARXNG_SETTINGS.read_text(encoding="utf-8"))
        assert "json" in data["search"]["formats"]
        assert data["server"]["limiter"] is False
