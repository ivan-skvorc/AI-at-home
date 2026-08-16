"""Config-integrity tests: duplicate-key hard errors and unknown-key lint.

Covers the wiring of deerflow.config.yaml_guard into AppConfig.from_file and
the lint checks in deerflow.config.config_lint. Motivating incident: a
config.yaml with two top-level ``sandbox:`` keys silently reverted a user to
LocalSandboxProvider (YAML last-key-wins); the only symptom was "bash is
disabled" at runtime.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.config.app_config import AppConfig, reset_app_config
from deerflow.config.config_lint import lint_unknown_config_keys
from deerflow.config.yaml_guard import DuplicateKeyError, safe_load_guarded

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_config():
    reset_app_config()
    yield
    reset_app_config()


class TestFromFileDuplicateKeys:
    def test_duplicate_top_level_sandbox_raises_with_both_line_numbers(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.community.aio_sandbox:AioSandboxProvider
                models: []
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(DuplicateKeyError) as excinfo:
            AppConfig.from_file(str(config))
        message = str(excinfo.value)
        assert "duplicate top-level key 'sandbox'" in message
        assert "first defined at line 1" in message
        assert "duplicated at line 4" in message
        assert str(config) in message

    def test_clean_config_loads(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                models:
                  - name: gpt
                    use: langchain_openai:ChatOpenAI
                    model: gpt-test
                """
            ),
            encoding="utf-8",
        )
        loaded = AppConfig.from_file(str(config))
        assert loaded.models[0].name == "gpt"


class TestShippedExampleConfig:
    def test_example_config_has_no_duplicate_keys(self):
        example = REPO_ROOT / "config.example.yaml"
        with open(example, encoding="utf-8") as f:
            assert safe_load_guarded(f) is not None

    def test_example_config_passes_lint(self):
        example = REPO_ROOT / "config.example.yaml"
        with open(example, encoding="utf-8") as f:
            data = safe_load_guarded(f)
        assert lint_unknown_config_keys(data) == []


class TestBundledModelPricing:
    """Every bundled paid model must carry a structured ``price:`` block — and
    must NOT carry the price in its ``display_name``.

    A model without a price contributes nothing to the chat header's estimate,
    so a conversation run entirely on unpriced models reports no cost at all.
    These pin the whole bundle so a newly added model cannot reintroduce that.

    The second half is the newer rule. A price used to live in the name as
    ``($3/15)`` and again in a machine-readable block, i.e. one number kept in
    two places. It drifted the obvious way: a promotion could only "end" by a
    human editing a string, so an expired discount kept being advertised. The
    price is now data in one place, and the name is only a label.
    """

    @staticmethod
    def _marker_blocks() -> dict[str, list[dict]]:
        """The models each ``auto-model-config`` marker block would enable."""
        import re

        import yaml

        text = (REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8")
        blocks: dict[str, list[dict]] = {}
        for match in re.finditer(
            r"# === BEGIN auto-model-config: (\w+).*?===(.*?)# === END auto-model-config: \1",
            text,
            re.S,
        ):
            body = "\n".join(re.sub(r"^  # ?", "  ", line) for line in match.group(2).splitlines())
            blocks[match.group(1)] = yaml.safe_load(body) or []
        return blocks

    def test_every_bundled_model_is_priced(self):
        unpriced = [f"{slug}:{entry.get('name')}" for slug, entries in self._marker_blocks().items() for entry in entries if not entry.get("price")]
        assert unpriced == [], f"bundled models missing a `price:` block: {unpriced}"

    def test_no_bundled_model_carries_its_price_in_the_display_name(self):
        """The rule this change exists to enforce.

        A price in the name is a second copy of a number that is already data.
        Re-adding one would resurrect the drift: the figure a user reads and the
        figure they are billed against could disagree, and a discount would once
        again only end when someone edited a string.
        """
        import re

        pair = re.compile(r"\(\$\d")
        offenders = [f"{slug}:{entry['name']} -> {entry['display_name']}" for slug, entries in self._marker_blocks().items() for entry in entries if pair.search(entry.get("display_name") or "")]
        assert offenders == [], f"prices belong in `price:`, not the display name: {offenders}"

    def test_every_bundled_model_prices_from_its_price_block(self):
        from app.gateway.pricing import build_pricing_map, lookup_pricing

        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                cfg = SimpleNamespace(
                    name=entry["name"],
                    model=entry["model"],
                    display_name=entry["display_name"],
                    price=entry.get("price"),
                    discount=entry.get("discount"),
                    pricing=None,
                )
                price = lookup_pricing(build_pricing_map([cfg]), entry["model"])
                assert price is not None, f"{slug}:{entry['name']} cannot be priced"
                assert price.input_per_million == pytest.approx(entry["price"]["input"]), f"{slug}:{entry['name']}"
                assert price.output_per_million == pytest.approx(entry["price"]["output"]), f"{slug}:{entry['name']}"

    def test_price_blocks_are_well_formed_and_single_currency(self):
        currencies: set[str] = set()
        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                price = entry["price"]
                name = f"{slug}:{entry.get('name')}"
                currencies.add(price.get("currency", "USD"))
                assert price["input"] > 0, name
                assert price["output"] > 0, name
                hit = price.get("cache_hit")
                # Optional, but when present it must be cheaper than a miss --
                # otherwise caching would be priced as a penalty.
                assert hit is None or 0 <= hit <= price["input"], name
        # Mixed currencies disable cost reporting entirely (see FORK.md).
        assert currencies == {"USD"}, currencies

    def test_discounts_are_real_discounts_and_parse_their_expiry(self):
        """A discount must be below list, and any `until` must be readable.

        An unreadable `until` is treated as *expired* by the pricing loader, so
        a typo here would silently switch the discount off rather than fail --
        catch it where the fix is obvious.
        """
        from deerflow.pricing import parse_discount_expiry

        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                discount = entry.get("discount")
                if not discount:
                    continue
                label = f"{slug}:{entry['name']}"
                price = entry["price"]
                assert 0 < discount["input"] <= price["input"], label
                assert 0 < discount["output"] <= price["output"], label
                if "until" in discount:
                    _, valid = parse_discount_expiry(discount["until"])
                    assert valid, f"{label} has an unreadable `until`: {discount['until']!r}"

    def test_the_wizard_bundles_and_the_example_agree(self):
        """The two synced sources must ship the same price for the same model.

        They are separate files a human edits, so nothing but a test stops them
        from disagreeing -- and a disagreement means a fresh install prices
        differently depending on whether the wizard or the marker block wrote
        the entry.
        """
        import sys

        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from wizard.providers import MODEL_PRICES

        from deerflow.pricing import parse_discount_expiry

        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                record = MODEL_PRICES.get(entry["name"])
                assert record is not None, f"{slug}:{entry['name']} is not in wizard MODEL_PRICES"
                assert entry["price"] == record["price"], f"{slug}:{entry['name']} price differs between the example and the wizard"
                # Compare the discount by meaning, not spelling: YAML parses a
                # bare `until: 2026-08-31` into a `date` while the wizard table
                # holds the string. Both are accepted inputs and resolve to the
                # same instant, so only a real disagreement should fail here.
                example_discount = dict(entry.get("discount") or {})
                wizard_discount = dict(record.get("discount") or {})
                example_until = example_discount.pop("until", None)
                wizard_until = wizard_discount.pop("until", None)
                assert example_discount == wizard_discount, f"{slug}:{entry['name']} discount differs between the example and the wizard"
                assert parse_discount_expiry(example_until) == parse_discount_expiry(wizard_until), f"{slug}:{entry['name']} discount expiry differs between the example and the wizard"


class TestSandboxKeyLint:
    def test_unknown_sandbox_key_warns_with_did_you_mean(self):
        warnings = lint_unknown_config_keys({"sandbox": {"use": "x", "allow_hostbash": True}})
        assert len(warnings) == 1
        assert "unknown key 'allow_hostbash' under sandbox:" in warnings[0]
        assert "did you mean 'allow_host_bash'" in warnings[0]

    def test_unknown_sandbox_key_without_close_match_still_warns(self):
        warnings = lint_unknown_config_keys({"sandbox": {"use": "x", "frobnicate": 1}})
        assert len(warnings) == 1
        assert "unknown key 'frobnicate' under sandbox:" in warnings[0]

    def test_declared_and_provider_specific_keys_do_not_warn(self):
        sandbox = {
            "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
            "allow_host_bash": False,
            "image": "img",
            "port": 8080,
            "replicas": 3,
            "container_prefix": "p",
            "idle_timeout": 600,
            "mounts": [],
            "environment": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
            "bash_command_timeout": 600,
            # provider-specific keys read via getattr/model_extra
            "base_url": "http://localhost:8091",
            "request_timeout": 120.0,
            "provisioner_url": "http://provisioner:8002",
        }
        assert lint_unknown_config_keys({"sandbox": sandbox}) == []

    def test_non_dict_sandbox_is_ignored(self):
        assert lint_unknown_config_keys({"sandbox": None}) == []
        assert lint_unknown_config_keys({"sandbox": "nope"}) == []


class TestModelEntryLint:
    def test_typo_of_declared_field_warns(self):
        models = [{"name": "m1", "use": "x", "model": "y", "supports_thinkng": True}]
        warnings = lint_unknown_config_keys({"models": models})
        assert len(warnings) == 1
        assert "models entry 'm1'" in warnings[0]
        assert "'supports_thinkng'" in warnings[0]
        assert "possible typo of 'supports_thinking'" in warnings[0]

    def test_another_typo_warns(self):
        models = [{"name": "m1", "use": "x", "model": "y", "supports_visoin": True}]
        warnings = lint_unknown_config_keys({"models": models})
        assert len(warnings) == 1
        assert "possible typo of 'supports_vision'" in warnings[0]

    def test_legitimate_provider_passthrough_does_not_warn(self):
        # Shape produced by scripts/sync-ollama-models.py plus common extras —
        # all deliberate passthrough to the provider constructor.
        models = [
            {
                "name": "qwen3:8b",
                "display_name": "qwen3:8b (Ollama)",
                "use": "langchain_ollama:ChatOllama",
                "model": "qwen3:8b",
                "base_url": "http://localhost:11434",
                "num_predict": 8192,
                "temperature": 0.7,
                "reasoning": True,
                "supports_tools": False,
                "api_key": "$OPENAI_API_KEY",
                "max_tokens": 4096,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
            }
        ]
        assert lint_unknown_config_keys({"models": models}) == []

    def test_malformed_entries_are_ignored(self):
        assert lint_unknown_config_keys({"models": ["not-a-dict", None]}) == []
        assert lint_unknown_config_keys({"models": "nope"}) == []
        assert lint_unknown_config_keys(None) == []


class TestFromFileLintWarnings:
    def test_unknown_sandbox_key_is_logged_at_load(self, tmp_path, caplog):
        config = tmp_path / "config.yaml"
        config.write_text(
            textwrap.dedent(
                """\
                sandbox:
                  use: deerflow.sandbox.local:LocalSandboxProvider
                  allow_hostbash: true
                models:
                  - name: gpt
                    use: langchain_openai:ChatOpenAI
                    model: gpt-test
                """
            ),
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="deerflow.config.app_config"):
            AppConfig.from_file(str(config))
        assert any("allow_hostbash" in record.getMessage() for record in caplog.records)
