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
    """Every bundled paid model must carry a machine-readable ``pricing:`` block.

    A model without one contributes nothing to the chat header's cost estimate,
    so a conversation run entirely on unpriced models reports no cost at all —
    which is what shipped when only the Anthropic block was priced. These pin
    the whole bundle so a newly added model cannot silently reintroduce it.
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
            # Uncomment the block the same way sync-api-key-models.py does, then
            # parse it as the YAML list it becomes once enabled.
            body = "\n".join(re.sub(r"^  # ?", "  ", line) for line in match.group(2).splitlines())
            blocks[match.group(1)] = yaml.safe_load(body) or []
        return blocks

    def test_every_bundled_model_prices_without_its_pricing_block(self):
        """The block must be redundant, not load-bearing.

        Shipping `pricing:` blocks in `config.example.yaml` only ever reaches a
        **fresh** `config.yaml`. `sync-api-key-models.py` skips a provider block
        whose models are already active (correct — it must not duplicate them),
        and `config_upgrade.py`'s `merge_missing` is dict-based so it cannot add
        a key inside an existing list entry. So a user who ran DeerFlow before a
        price shipped keeps that model active and unpriced forever, and their
        chat header stays on `—` no matter how many times the example is fixed.

        `pricing.py::derive_pricing_from_display_name` closes that by reading the
        price the name already states. This test pins the property that makes it
        work: every bundled model must resolve a price from its `display_name`
        **alone**, with its block removed. A new bundled model whose name does
        not carry a parseable `($in/out)` pair would price on a fresh install and
        silently not price on an upgraded one — fail here instead.
        """
        from app.gateway.pricing import build_pricing_map, lookup_pricing

        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                stripped = SimpleNamespace(name=entry["name"], model=entry["model"], pricing=None, display_name=entry["display_name"])
                pricing = build_pricing_map([stripped])
                price = lookup_pricing(pricing, entry["model"])
                assert price is not None, f"{slug}:{entry['name']} cannot be priced from its display_name alone"
                # And the derived figures must equal the shipped block, or an
                # upgraded install would silently bill a different rate than a
                # fresh one.
                shipped = entry["pricing"]
                assert price.input_per_million == pytest.approx(shipped["input_per_million"]), f"{slug}:{entry['name']}"
                assert price.output_per_million == pytest.approx(shipped["output_per_million"]), f"{slug}:{entry['name']}"
                assert price.promo() is not None if shipped.get("promo_input_per_million") else price.promo() is None, f"{slug}:{entry['name']}"

    def test_every_bundled_model_is_priced(self):
        unpriced = [f"{slug}:{entry.get('name')}" for slug, entries in self._marker_blocks().items() for entry in entries if not entry.get("pricing")]
        assert unpriced == [], f"bundled models missing a pricing block: {unpriced}"

    def test_pricing_blocks_are_well_formed_and_single_currency(self):
        currencies: set[str] = set()
        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                pricing = entry["pricing"]
                name = f"{slug}:{entry.get('name')}"
                currencies.add(pricing["currency"])
                assert pricing["input_per_million"] > 0, name
                assert pricing["output_per_million"] > 0, name
                hit = pricing.get("input_cache_hit_per_million")
                # Optional, but when present it must be cheaper than a miss —
                # otherwise caching would be priced as a penalty.
                assert hit is None or 0 <= hit <= pricing["input_per_million"], name
        # Mixed currencies disable cost reporting entirely (see FORK.md §2).
        assert currencies == {"USD"}, currencies

    def test_price_matches_the_price_in_name_pair(self):
        """The two prices a model carries must agree.

        `display_name` shows `($<in>/<out>)` for humans and `pricing:` bills
        against it. A promo name (`$list → $promo*`) bills at the **standard**
        rate — the promo can end at any time.
        """
        import re

        pair = re.compile(r"\(\$(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)")
        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                match = pair.search(entry["display_name"])
                assert match, f"{slug}:{entry['name']} has no price in its display_name"
                assert entry["pricing"]["input_per_million"] == pytest.approx(float(match.group(1))), entry["name"]
                assert entry["pricing"]["output_per_million"] == pytest.approx(float(match.group(2))), entry["name"]

    def test_promo_price_matches_the_starred_pair_in_the_name(self):
        """A starred `$list → $promo*` name and its `promo_*` block must agree.

        The starred pair is the human-readable "you pay less right now" signal
        and `promo_*_per_million` is the machine-readable one the header renders
        in green. They are two spellings of one number: if a promo ends and only
        the name is updated, the UI keeps advertising a discount that no longer
        exists, which is worse than showing no promo at all. This also enforces
        the converse — a `promo_*` block with no starred pair in the name.
        """
        import re

        starred = re.compile(r"\(\$\d+(?:\.\d+)?/\d+(?:\.\d+)?\s*→\s*\$(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\*\)")
        for slug, entries in self._marker_blocks().items():
            for entry in entries:
                pricing = entry["pricing"]
                label = f"{slug}:{entry['name']}"
                match = starred.search(entry["display_name"])
                has_promo_block = "promo_input_per_million" in pricing or "promo_output_per_million" in pricing
                if match is None:
                    assert not has_promo_block, f"{label} has promo pricing but no starred pair in its display_name"
                    continue
                assert has_promo_block, f"{label} advertises a promo in its display_name but ships no promo_* pricing"
                assert pricing["promo_input_per_million"] == pytest.approx(float(match.group(1))), label
                assert pricing["promo_output_per_million"] == pytest.approx(float(match.group(2))), label
                # A "promo" at or above list price would be billed as a discount
                # while costing the user more — the pricing loader drops it, so
                # catch it here where the fix is obvious.
                assert pricing["promo_input_per_million"] <= pricing["input_per_million"], label
                assert pricing["promo_output_per_million"] <= pricing["output_per_million"], label

    def test_wizard_bundles_match_the_config_marker_blocks(self):
        """`make setup` and the auto-config path must write identical prices."""
        import sys

        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import wizard.providers as providers

        wizard = {"anthropic": providers.ANTHROPIC_BUNDLE_MODELS, "openrouter": providers.OPENROUTER_BUNDLE_MODELS}
        wizard.update({slug: bundle for slug, (_, bundle) in providers.HOME_API_BUNDLES.items()})

        config = {entry["name"]: entry.get("pricing") for entries in self._marker_blocks().values() for entry in entries}
        drift = [(entry["name"], entry.get("pricing"), config.get(entry["name"])) for bundle in wizard.values() for entry in bundle if entry.get("pricing") != config.get(entry["name"])]
        assert drift == [], f"pricing drift between providers.py and config.example.yaml: {drift}"


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
