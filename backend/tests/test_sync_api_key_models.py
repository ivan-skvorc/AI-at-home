"""Tests for scripts/sync-api-key-models.py.

The script is a text-surgery editor that *uncomments* the Anthropic / OpenRouter
model blocks in config.yaml (between BEGIN/END auto-model-config markers) when
the matching API key is present in .env. These tests pin:
- key detection ignores placeholders / unresolved "$VAR" / empty values;
- uncommenting produces valid YAML matching the block, and only for present keys;
- it is idempotent, never re-comments, skips already-active blocks, and no-ops
  when the markers are absent;
- the real config.example.yaml block round-trips to valid, correct YAML;
- it refuses to edit a config with duplicate top-level keys.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync-api-key-models.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_api_key_models", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_api = _load_script()


def same_model(model_id: str) -> str:
    """Compare a direct id with an OpenRouter slug's bare half.

    Case differs per API (MiniMax-M3 ↔ minimax-m3), and so does the version
    separator: Anthropic's API hyphenates it (claude-fable-5-1) where OpenRouter
    dots it (anthropic/claude-fable-5.1). Only comparisons normalise — deriving
    one spelling from the other is how an uncallable routed slug shipped.
    """
    return model_id.lower().replace(".", "-")


# A miniature config carrying both marker blocks in the same commented shape the
# real config.example.yaml uses.
SAMPLE_CONFIG = """config_version: 1
models:
  # QUICK START prose that must never be uncommented.
  # === BEGIN auto-model-config: anthropic (uncommented at startup when ANTHROPIC_API_KEY is set) ===
  # - name: claude-opus-4-8
  #   display_name: Claude Opus 4.8
  #   use: langchain_anthropic:ChatAnthropic
  #   model: claude-opus-4-8
  #   api_key: $ANTHROPIC_API_KEY
  #   max_tokens: 32000
  #   supports_vision: true
  # === END auto-model-config: anthropic ===

  # === BEGIN auto-model-config: openrouter (uncommented at startup when OPENROUTER_API_KEY is set) ===
  # - name: openrouter-fable-5-1
  #   display_name: Claude Fable 5.1 (OpenRouter)
  #   use: langchain_openai:ChatOpenAI
  #   model: anthropic/claude-fable-5.1
  #   api_key: $OPENROUTER_API_KEY
  #   base_url: https://openrouter.ai/api/v1
  #   max_tokens: 32000
  #   supports_vision: true
  # === END auto-model-config: openrouter ===
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
"""


def _model_names(config_text: str) -> list[str]:
    data = yaml.safe_load(config_text)
    return [m["name"] for m in (data.get("models") or [])]


class TestKeyDetection:
    @pytest.mark.parametrize("value", ["sk-ant-realkey123", "or-1234567890", "abc"])
    def test_real_keys_detected(self, value):
        assert sync_api.looks_like_real_key(value) is True

    @pytest.mark.parametrize(
        "value",
        [None, "", "   ", "your-anthropic-api-key", "your_openrouter_key", "$ANTHROPIC_API_KEY", "<paste-key-here>"],
    )
    def test_placeholders_rejected(self, value):
        assert sync_api.looks_like_real_key(value) is False

    def test_env_file_parsing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('ANTHROPIC_API_KEY=sk-ant-xyz\nexport OPENROUTER_API_KEY="or-abc"\n# comment\nSERPER_API_KEY=your-serper-api-key\n')
        values = sync_api.parse_env_file(env)
        assert values["ANTHROPIC_API_KEY"] == "sk-ant-xyz"
        assert values["OPENROUTER_API_KEY"] == "or-abc"
        assert values["SERPER_API_KEY"] == "your-serper-api-key"

    def test_missing_env_file_is_empty(self, tmp_path):
        assert sync_api.parse_env_file(tmp_path / "nope.env") == {}


class TestUncomment:
    def test_anthropic_only(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        assert _model_names(out) == ["claude-opus-4-8"]
        # OpenRouter block stayed commented.
        assert "  # - name: openrouter-fable-5-1" in out
        # Markers themselves stay commented.
        assert "# === BEGIN auto-model-config: anthropic" in out

    def test_openrouter_only(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"openrouter"})
        assert _model_names(out) == ["openrouter-fable-5-1"]
        assert "  # - name: claude-opus-4-8" in out

    def test_both_keys(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        assert _model_names(out) == ["claude-opus-4-8", "openrouter-fable-5-1"]

    def test_no_keys_is_noop(self):
        out = sync_api.sync(SAMPLE_CONFIG, set())
        assert out == SAMPLE_CONFIG

    def test_uncommented_yaml_is_valid_and_typed(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        data = yaml.safe_load(out)
        entry = data["models"][0]
        assert entry["model"] == "claude-opus-4-8"
        assert entry["max_tokens"] == 32000  # stays an int, not a string
        assert entry["supports_vision"] is True

    def test_prose_comment_not_uncommented(self):
        out = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        assert "  # QUICK START prose that must never be uncommented." in out

    def test_idempotent(self):
        once = sync_api.sync(SAMPLE_CONFIG, {"anthropic", "openrouter"})
        twice = sync_api.sync(once, {"anthropic", "openrouter"})
        assert once == twice

    def test_already_active_block_is_skipped(self):
        # First run activates anthropic; a second run must not duplicate it.
        once = sync_api.sync(SAMPLE_CONFIG, {"anthropic"})
        twice = sync_api.sync(once, {"anthropic"})
        assert _model_names(twice) == ["claude-opus-4-8"]

    def test_missing_markers_is_noop(self):
        text = "config_version: 1\nmodels:\n  - name: hand\n    model: x\nsandbox:\n  use: y\n"
        assert sync_api.sync(text, {"anthropic", "openrouter"}) == text

    def test_trailing_newline_preserved(self):
        assert sync_api.sync(SAMPLE_CONFIG, {"anthropic"}).endswith("\n")


class TestUncommentLine:
    def test_list_item(self):
        assert sync_api.uncomment_line("  # - name: x") == "  - name: x"

    def test_nested_key(self):
        assert sync_api.uncomment_line("  #   display_name: X") == "    display_name: X"

    def test_blank_separator_collapses(self):
        assert sync_api.uncomment_line("  #") == ""

    def test_inline_comment_preserved(self):
        # Only the leading "# " is stripped; the trailing YAML comment survives.
        assert sync_api.uncomment_line("  #       budget_tokens: 4096   # required") == "        budget_tokens: 4096   # required"

    def test_already_uncommented_unchanged(self):
        assert sync_api.uncomment_line("    display_name: X") == "    display_name: X"


class TestRealExampleConfig:
    """The shipped config.example.yaml blocks must round-trip to correct YAML."""

    def setup_method(self):
        self.text = (REPO_ROOT / "config.example.yaml").read_text()

    def test_both_blocks_present(self):
        assert sync_api.find_block(self.text.splitlines(), "anthropic") is not None
        assert sync_api.find_block(self.text.splitlines(), "openrouter") is not None

    def test_anthropic_block_enables_expected_models(self):
        out = sync_api.sync(self.text, {"anthropic"})
        data = yaml.safe_load(out)
        names = {m["model"] for m in data["models"]}
        assert {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"}.issubset(names)
        assert all(m["api_key"] == "$ANTHROPIC_API_KEY" for m in data["models"])

    def test_anthropic_adaptive_models_request_summarized_thinking(self):
        """The adaptive Claude models (Fable 5.1, Opus 5.5, Opus 5, Sonnet 5,
        Sonnet 4.6) must request `display: summarized` when thinking is enabled.
        Their default (`omitted`) returns thinking blocks with empty text, which
        langchain-anthropic drops on multi-turn tool-use replay, producing a 400
        (`messages.N.content.0.thinking.thinking: Field required`). Haiku 4.5 uses the
        older `type: enabled` budget form, which returns full thinking text, so it
        needs no display override."""
        out = sync_api.sync(self.text, {"anthropic"})
        data = yaml.safe_load(out)
        by_model = {m["model"]: m for m in data["models"]}

        for slug in ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6"):
            enabled = by_model[slug]["when_thinking_enabled"]["thinking"]
            assert enabled.get("type") == "adaptive", slug
            assert enabled.get("display") == "summarized", slug

        haiku_enabled = by_model["claude-haiku-4-5"]["when_thinking_enabled"]["thinking"]
        assert haiku_enabled.get("type") == "enabled"
        assert haiku_enabled.get("budget_tokens")
        assert "display" not in haiku_enabled

    def test_fable_never_sends_disabled_thinking_but_opus_sonnet_do(self):
        """Fable 5.1 and Opus 5.5 reject `thinking: {type: disabled}` with a 400, so
        neither may send it on either toggle state: when thinking is "disabled" they
        keep adaptive+summarized (they cannot turn thinking off, and summarized keeps
        the multi-turn replay legal). Opus 5 / Sonnet 5 / Sonnet 4.6 accept
        and keep `type: disabled`. Regression guard against both the disable-path 400
        and the omitted-display replay 400.

        Opus 5 additionally rejects `type: disabled` above reasoning effort `high`,
        but DeerFlow never sends an effort/`output_config` parameter to
        ChatAnthropic, so the API default (`high`) applies — see
        `test_anthropic_entries_do_not_opt_into_reasoning_effort`."""
        out = sync_api.sync(self.text, {"anthropic"})
        data = yaml.safe_load(out)
        by_model = {m["model"]: m for m in data["models"]}

        for always_on in ("claude-fable-5-1", "claude-opus-5-5"):
            disabled = by_model[always_on]["when_thinking_disabled"]["thinking"]
            assert disabled.get("type") == "adaptive", (always_on, disabled)
            assert disabled.get("display") == "summarized", (always_on, disabled)

        for slug in ("claude-opus-5", "claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5"):
            disabled = by_model[slug].get("when_thinking_disabled") or {}
            assert disabled.get("thinking", {}).get("type") == "disabled", slug

    def test_openrouter_block_enables_expected_models(self):
        out = sync_api.sync(self.text, {"openrouter"})
        data = yaml.safe_load(out)
        ids = {m["model"] for m in data["models"]}
        expected = {
            "anthropic/claude-fable-5.1",
            # Anthropic and OpenAI each route a *pair* — FORK.md step 3.
            "anthropic/claude-opus-5.5",
            "x-ai/grok-4.6",
            "openai/gpt-6-astra",
            "openai/gpt-5.6-sol",
            "openai/gpt-5.3-codex",
            "google/gemini-3.8-flash",
            "meta-llama/llama-4-maverick",
            "minimax/minimax-m3",
            "qwen/qwen3.8-max",
            "moonshotai/kimi-k3",
            "mistralai/mistral-large-2512",
            "deepseek/deepseek-v4-pro",
            "z-ai/glm-5.3",
            "nvidia/nemotron-3-ultra-550b-a55b",
        }
        assert expected == ids
        assert all(m["api_key"] == "$OPENROUTER_API_KEY" for m in data["models"])

    def test_openrouter_block_has_no_unreleased_slugs(self):
        """Guard against re-introducing slugs for models that never shipped.

        Both of these were in the bundle and failed at request time:
        `openai/gpt-5.5-codex` (the Codex line stops at 5.3 — there is no 5.5 or
        5.6 Codex) and `google/gemini-3.5-pro` (delayed three times; as of
        2026-07-21 Google shipped 3.6 Flash / 3.5 Flash-Lite / Flash Cyber with
        still no 3.5 Pro)."""
        out = sync_api.sync(self.text, {"openrouter"})
        ids = {m["model"] for m in yaml.safe_load(out)["models"]}
        assert "openai/gpt-5.5-codex" not in ids
        assert "google/gemini-3.5-pro" not in ids

    def test_anthropic_entries_do_not_opt_into_reasoning_effort(self):
        """Opus 5 rejects `thinking: {type: disabled}` above reasoning effort
        `high`. The Anthropic entries must not set `supports_reasoning_effort`,
        which is the only way DeerFlow's model factory forwards a `reasoning_effort`
        kwarg — without it the API default (`high`) applies and the disable path
        stays legal."""
        out = sync_api.sync(self.text, {"anthropic"})
        for entry in yaml.safe_load(out)["models"]:
            assert entry.get("supports_reasoning_effort") is not True, entry["model"]
            assert "reasoning_effort" not in entry, entry["model"]

    def test_example_config_default_state_has_no_active_models(self):
        # Without any key, the example config stays fully commented (0 models).
        assert sync_api.sync(self.text, set()) == self.text
        data = yaml.safe_load(self.text)
        assert (data.get("models") or []) == []


class TestHomeApiBlocks:
    """The first-party 'home' blocks (openai, xai, google, deepseek, mistral,
    moonshot, qwen, minimax, zai) each enable one lab's lineup on its own key,
    mirroring the Anthropic block. They round-trip to exactly the wizard bundles."""

    def setup_method(self):
        self.text = (REPO_ROOT / "config.example.yaml").read_text()
        from wizard.providers import HOME_API_BUNDLES

        self.bundles = HOME_API_BUNDLES

    def test_every_home_slug_is_registered_and_present(self):
        registered = {slug for slug, _env in sync_api.PROVIDERS}
        for slug, (env_var, _bundle) in self.bundles.items():
            assert slug in registered, f"{slug} missing from sync PROVIDERS"
            assert (slug, env_var) in sync_api.PROVIDERS, f"{slug} env mismatch in PROVIDERS"
            assert sync_api.find_block(self.text.splitlines(), slug) is not None, f"{slug} block missing from config.example.yaml"

    def test_each_block_round_trips_to_its_wizard_bundle(self):
        """config.example.yaml ↔ scripts/wizard/providers.py must stay in sync:
        uncommenting a home block yields exactly that lab's bundle entries."""
        for slug, (_env, bundle) in self.bundles.items():
            out = sync_api.sync(self.text, {slug})
            active = {m["name"]: m for m in yaml.safe_load(out)["models"]}
            for entry in bundle:
                assert active.get(entry["name"]) == entry, f"{slug}/{entry['name']} drifted between config.example.yaml and providers.py"

    def test_home_entries_use_the_labs_own_key(self):
        for slug, (env_var, _bundle) in self.bundles.items():
            out = sync_api.sync(self.text, {slug})
            for m in yaml.safe_load(out)["models"]:
                key = m.get("api_key") or m.get("gemini_api_key")
                assert key == f"${env_var}", f"{slug}/{m['name']} key {key!r}"

    def test_home_entries_carry_no_openrouter_privacy_marker(self):
        for slug, (_env, _bundle) in self.bundles.items():
            out = sync_api.sync(self.text, {slug})
            for m in yaml.safe_load(out)["models"]:
                assert "(p)" not in m["display_name"], f"{slug}/{m['name']} must not carry the OpenRouter (p) marker"

    def test_all_keys_present_enables_every_block_without_name_collision(self):
        all_slugs = {slug for slug, _env in sync_api.PROVIDERS}
        out = sync_api.sync(self.text, all_slugs)
        names = [m["name"] for m in yaml.safe_load(out)["models"]]
        assert len(names) == len(set(names)), "model names collide when every key is set"
        # 6 Anthropic + 15 OpenRouter + 23 home = 44 distinct models.
        # OpenRouter gained Opus 5 and GPT-6 Astra (the two paired labs of
        # FORK.md step 3); the OpenAI home block gained Astra's direct twin.
        assert len(names) == 44

    def test_openai_home_and_openrouter_gpt_are_distinct_entries(self):
        """The GPT flagship is doubled: a direct OpenAI entry AND the OpenRouter
        Sol + Codex double both survive with distinct names."""
        out = sync_api.sync(self.text, {"openai", "openrouter"})
        by_name = {m["name"]: m for m in yaml.safe_load(out)["models"]}
        assert by_name["openai-gpt-5.6-sol"]["model"] == "gpt-5.6-sol"
        assert by_name["openai-gpt-5.6-sol"]["api_key"] == "$OPENAI_API_KEY"
        assert by_name["openrouter-gpt-5.6-sol"]["model"] == "openai/gpt-5.6-sol"
        assert by_name["openrouter-gpt-5.3-codex"]["model"] == "openai/gpt-5.3-codex"


class TestFirstPartyKeyCoverage:
    """FORK.md, *Auditing the model list* step 2 — every big name gets its own key.

    A lab that ships a public API must be reachable **two ways**: a home block
    gated by that lab's own `.env` key, carrying more than just the flagship, and
    that flagship *also* on OpenRouter for users who hold only an
    `OPENROUTER_API_KEY` — the Anthropic shape (six Claudes on the direct key,
    Fable 5.1 additionally routed) generalised to Grok, GPT, Gemini, Qwen, Kimi,
    DeepSeek and the rest. Everything mechanical about that rule is pinned here,
    so the audit step needs no network.
    """

    # The two labs with no first-party consumer chat API: deliberately routed-only.
    ROUTED_ONLY_PREFIXES = {"meta-llama", "nvidia"}

    def setup_method(self):
        self.text = (REPO_ROOT / "config.example.yaml").read_text()
        self.env_example = (REPO_ROOT / ".env.example").read_text()
        from wizard.providers import HOME_API_BUNDLES

        self.bundles = HOME_API_BUNDLES
        all_slugs = {slug for slug, _env in sync_api.PROVIDERS}
        self.models = yaml.safe_load(sync_api.sync(self.text, all_slugs))["models"]

    def _env_key_section(self) -> str:
        """The '── Model provider API keys ──' block of .env.example, up to '# Optional:'."""
        _, _, rest = self.env_example.partition("Model provider API keys")
        section, sep, _ = rest.partition("# Optional:")
        assert sep, ".env.example lost its '# Optional:' marker below the provider keys"
        return section

    def test_every_provider_key_is_documented_in_env_example(self):
        """A key nobody knows to set enables nothing — and it must sit in the
        provider-key section, not down among the generic OpenAI-compatible ones."""
        section = self._env_key_section()
        for _slug, env_var in sync_api.PROVIDERS:
            assert f"# {env_var}=" in section, f"{env_var} missing from .env.example's model-provider key section"

    def test_env_example_names_the_models_each_home_key_actually_enables(self):
        """The comment beside a key is where a user decides whether to go get it.

        FORK.md's audit calls out that several places describing the roster are
        prose no test reads, and this was one of them: the 2026-08-20
        roll-forward moved Mistral Small 3 to Small 4 in `config.example.yaml`,
        `providers.py`, the sync script's docstring and the README, and left
        `.env.example` advertising Small 3. Nothing failed — the key worked, the
        block uncommented, and the only symptom was a user reading the name of a
        model this fork does not carry.
        `test_every_provider_key_is_documented_in_env_example` above checks the
        key is *present*; this checks the comment is not *lying*.

        The comment abbreviates the way a human does — it drops the lab name
        when every model in the block repeats it ("Large 3 / Medium 3.5 / Small
        4", "MiniMax M3 / M2.7") — so only a leading token shared by *every*
        display name in that bundle is allowed to go missing. Everything that
        distinguishes one model from another, the version above all, must be
        there.
        """
        section = self._env_key_section()
        stale = []
        for slug, (env_var, bundle) in self.bundles.items():
            line = next((ln for ln in section.splitlines() if f"# {env_var}=" in ln), None)
            assert line, f"{env_var} has no line in .env.example's model-provider key section"

            names = [m["display_name"].split(" (")[0].strip() for m in bundle]
            heads = {n.split()[0] for n in names}
            shared_prefix = heads.pop() if len(heads) == 1 else None

            for name in names:
                tokens = name.split()
                distinguishing = " ".join(tokens[1:]) if shared_prefix and len(tokens) > 1 else name
                if distinguishing not in line and name not in line:
                    stale.append(f"{env_var} ({slug}): comment names neither {name!r} nor {distinguishing!r}")
        assert not stale, ".env.example describes models the home block does not enable:\n  " + "\n  ".join(stale)

    def test_no_home_block_is_trimmed_to_a_lone_flagship(self):
        """The fuller lineup is the whole reason to hold a lab's own key; the
        routed flagship already covers the one-model case."""
        for slug, (_env, bundle) in self.bundles.items():
            assert len(bundle) >= 2, f"home block {slug} carries only {len(bundle)} model(s) — a lone flagship is a finding"

    def test_every_lab_with_a_home_block_has_its_flagship_doubled(self):
        """A home id names the same model as the OpenRouter slug minus its
        'provider/' prefix, as `same_model` compares them."""

        direct_ids = {same_model(m["model"]) for m in self.models if not m["name"].startswith("openrouter-")}
        routed = {same_model(m["model"].split("/", 1)[1]) for m in self.models if m["name"].startswith("openrouter-") and "/" in m["model"]}
        for slug, (_env, bundle) in self.bundles.items():
            bare = {same_model(m["model"]) for m in bundle}
            assert bare & routed, f"{slug}: no home model is doubled on OpenRouter"
        # The template case this generalises: Anthropic's Fable 5.1 is direct *and* routed.
        assert "claude-fable-5-1" in direct_ids
        assert "claude-fable-5-1" in routed

    def test_routed_claude_slugs_keep_openrouters_dotted_version(self):
        """`anthropic/claude-fable-5-1` shipped for three weeks and could not be
        called: it was derived from the direct id by prefixing `anthropic/`, while
        OpenRouter spells the version with a dot. Nothing fails until a request
        does, and the weekly audit cannot see it while OpenRouter is unreachable."""
        routed_claude = [m["model"] for m in self.models if m["name"].startswith("openrouter-") and m["model"].startswith("anthropic/")]
        assert routed_claude
        for slug in routed_claude:
            assert re.fullmatch(r"anthropic/claude-[a-z]+-\d+(\.\d+)?", slug), f"{slug} is not OpenRouter's spelling (it dots the version)"

    # FORK.md, step 3: two labs route a *pair* rather than a single flagship,
    # because their top tier is really two models a factor of two apart in price.
    PAIRED_ROUTED_LABS = {
        "anthropic": ("anthropic/claude-fable-5.1", "anthropic/claude-opus-5.5"),
        "openai": ("openai/gpt-6-astra", "openai/gpt-5.6-sol"),
    }

    def test_the_paired_labs_route_both_halves(self):
        """Half a pair is the silent failure this pins.

        Anthropic and OpenAI each route two models rather than one, and either
        half alone breaks an OpenRouter-only user in a way nothing reports.
        Route only the dearer (Fable, Astra) and every routed task bills at
        roughly twice what the cheaper sibling would have charged for most of
        it — the config is valid, the model answers, the bill is just wrong.
        Route only the cheaper (Opus, Sol) and the lab's best model is
        unreachable on that key, with the home block no help, because holding
        it is precisely what this user did not do.

        A roster roll-forward is how one half goes missing: the newer model
        gets upgraded, the older one is left pointing at a retired slug or
        dropped as redundant, and `test_every_lab_with_a_home_block_has_its_
        flagship_doubled` above still passes on the surviving half. So both
        halves are named here, by slug.
        """
        routed = {m["model"].lower() for m in self.models if m["name"].startswith("openrouter-")}
        for lab, pair in self.PAIRED_ROUTED_LABS.items():
            missing = [slug for slug in pair if slug.lower() not in routed]
            assert not missing, f"{lab} routes a pair (FORK.md step 3) and is missing {missing} from the OpenRouter block"

    def test_a_paired_lab_routes_both_halves_from_its_own_home_block(self):
        """The pair is a *doubling*, so each half needs its direct twin too.

        Without this, the pair could be satisfied by routed-only entries, which
        is the one shape step 3 forbids for a lab that ships a first-party API:
        a user holding the lab's own key would see fewer models than a user
        holding OpenRouter's.
        """
        direct_ids = {same_model(m["model"]) for m in self.models if not m["name"].startswith("openrouter-")}
        for lab, pair in self.PAIRED_ROUTED_LABS.items():
            for slug in pair:
                bare = same_model(slug.split("/", 1)[1])
                assert bare in direct_ids, f"{lab}: {slug} is routed but has no direct entry — the pair must be doubled, not routed-only"

    def test_only_meta_and_nvidia_stay_openrouter_only(self):
        """Every other routed lab must own a direct block; when an OpenRouter-only
        lab ships a first-party API, this fails until it gets a home block."""
        direct_ids = {same_model(m["model"]) for m in self.models if not m["name"].startswith("openrouter-")}
        uncovered = {m["model"].split("/", 1)[0] for m in self.models if m["name"].startswith("openrouter-") and "/" in m["model"] and same_model(m["model"].split("/", 1)[1]) not in direct_ids}
        assert uncovered == self.ROUTED_ONLY_PREFIXES, f"routed-only labs drifted: {sorted(uncovered)}"


class TestDuplicateTopLevelKeys:
    def test_duplicate_models_aborts(self):
        text = "models: []\nsandbox:\n  use: a\nmodels: []\n"
        with pytest.raises(SystemExit) as excinfo:
            sync_api.check_duplicate_top_level_keys(text, "config.yaml")
        assert "duplicate top-level key 'models'" in str(excinfo.value)

    def test_clean_config_passes(self):
        sync_api.check_duplicate_top_level_keys(SAMPLE_CONFIG, "config.yaml")
