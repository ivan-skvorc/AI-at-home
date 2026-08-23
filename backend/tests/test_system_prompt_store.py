"""Tests for the editable lead-agent system prompt (fork feature).

Covers the override store — validation, persistence, resolution — and the way
``apply_prompt_template`` consumes it. The guiding rule is that a saved
override may change the prompt but must never be able to *break a run*: an
override that cannot be rendered falls back to the built-in template.
"""

from unittest.mock import patch

import pytest

from deerflow.agents.lead_agent import system_prompt_store as store
from deerflow.agents.lead_agent.prompt import (
    SYSTEM_PROMPT_PLACEHOLDERS,
    SYSTEM_PROMPT_TEMPLATE,
    apply_prompt_template,
    get_system_prompt_template,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig


@pytest.fixture
def base_dir(tmp_path):
    """Point the override store at an isolated base directory."""
    with patch.object(store, "get_paths", return_value=Paths(base_dir=tmp_path)):
        yield tmp_path


@pytest.fixture
def app_config() -> AppConfig:
    """An in-memory AppConfig for the render tests.

    ``apply_prompt_template`` falls back to loading the repo-root
    ``config.yaml`` when it gets ``None``. That file is gitignored, so relying
    on it makes a test pass on a machine that has run ``make config`` and fail
    in CI. Every render below passes this explicitly.
    """
    return AppConfig(sandbox=SandboxConfig(use="test"))


class TestPlaceholderExtraction:
    def test_extracts_named_fields(self):
        assert store.extract_placeholders("a {one} b {two}") == frozenset({"one", "two"})

    def test_escaped_braces_are_not_placeholders(self):
        assert store.extract_placeholders("literal {{not_a_field}} here") == frozenset()

    def test_builtin_template_placeholders_are_all_named(self):
        # The built-in template is the source of truth for the allowed set;
        # every field in it must be a bare identifier so the UI can list them.
        assert SYSTEM_PROMPT_PLACEHOLDERS
        assert all(name.isidentifier() for name in SYSTEM_PROMPT_PLACEHOLDERS)

    def test_builtin_template_is_valid_against_itself(self):
        store.validate_system_prompt_template(SYSTEM_PROMPT_TEMPLATE, allowed=SYSTEM_PROMPT_PLACEHOLDERS)


class TestValidation:
    def test_accepts_a_subset_of_the_allowed_placeholders(self):
        store.validate_system_prompt_template("just {soul}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_accepts_a_template_with_no_placeholders(self):
        store.validate_system_prompt_template("a plain prompt", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_an_unknown_placeholder(self):
        with pytest.raises(store.SystemPromptTemplateError) as excinfo:
            store.validate_system_prompt_template("{not_a_real_field}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert "not_a_real_field" in str(excinfo.value)

    def test_rejects_unbalanced_braces(self):
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{soul", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_positional_fields(self):
        # str.format is called with keyword arguments only, so "{}" / "{0}"
        # would raise IndexError at render time.
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{0}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_attribute_and_index_access(self):
        # "{soul.__class__}" renders object internals into the prompt; the
        # substituted values are plain strings, so bare names are all we allow.
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{soul.__class__}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{soul[0]}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_a_nested_format_spec(self):
        # Parses to the allowed field `agent_name`, but the inner `width` would
        # raise KeyError at render time. Catching it here is what makes "saved"
        # mean "will render".
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("{agent_name:{width}}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_accepts_a_conversion_and_a_plain_format_spec(self):
        # Both render fine against string values, so neither should be refused.
        store.validate_system_prompt_template("{agent_name!r} {soul:>4}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_an_empty_template(self):
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("   \n  ", allowed=SYSTEM_PROMPT_PLACEHOLDERS)

    def test_rejects_an_oversized_template(self):
        with pytest.raises(store.SystemPromptTemplateError):
            store.validate_system_prompt_template("x" * (store.MAX_TEMPLATE_CHARS + 1), allowed=SYSTEM_PROMPT_PLACEHOLDERS)


class TestPersistence:
    def test_no_override_by_default(self, base_dir):
        assert store.load_custom_system_prompt() is None

    def test_save_then_load_round_trips(self, base_dir):
        store.save_custom_system_prompt("You are {agent_name}.", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert store.load_custom_system_prompt() == "You are {agent_name}."
        assert store.custom_system_prompt_path().exists()

    def test_save_rejects_an_invalid_template_without_writing(self, base_dir):
        with pytest.raises(store.SystemPromptTemplateError):
            store.save_custom_system_prompt("{nope}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert not store.custom_system_prompt_path().exists()

    def test_a_rejected_save_leaves_no_temp_file(self, base_dir):
        with pytest.raises(store.SystemPromptTemplateError):
            store.save_custom_system_prompt("{nope}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert list(base_dir.glob("SYSTEM_PROMPT.md*")) == []

    def test_clear_removes_the_override(self, base_dir):
        store.save_custom_system_prompt("You are {agent_name}.", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert store.clear_custom_system_prompt() is True
        assert store.load_custom_system_prompt() is None

    def test_clear_is_idempotent(self, base_dir):
        assert store.clear_custom_system_prompt() is False

    def test_a_blank_file_reads_as_no_override(self, base_dir):
        path = store.custom_system_prompt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("   \n", encoding="utf-8")
        assert store.load_custom_system_prompt() is None


class TestResolution:
    def test_default_is_the_builtin_template(self, base_dir):
        assert store.resolve_system_prompt_template(SYSTEM_PROMPT_TEMPLATE) == SYSTEM_PROMPT_TEMPLATE

    def test_override_wins_when_present(self, base_dir):
        store.save_custom_system_prompt("You are {agent_name}.", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert store.resolve_system_prompt_template(SYSTEM_PROMPT_TEMPLATE) == "You are {agent_name}."

    def test_an_invalid_override_on_disk_falls_back_to_the_builtin(self, base_dir):
        # Hand-edited outside the API: never fail the run, just ignore it.
        path = store.custom_system_prompt_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{unknown_field}", encoding="utf-8")
        assert store.resolve_system_prompt_template(SYSTEM_PROMPT_TEMPLATE) == SYSTEM_PROMPT_TEMPLATE

    def test_get_system_prompt_template_reads_the_override(self, base_dir):
        store.save_custom_system_prompt("You are {agent_name}.", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        assert get_system_prompt_template() == "You are {agent_name}."


class TestConfigIndependence:
    """These tests must not depend on a repo-root ``config.yaml``.

    ``config.yaml`` is gitignored: it exists on a developer machine that has run
    ``make config`` and nowhere in CI. An earlier version of this file rendered
    without passing ``app_config``, so ``apply_prompt_template`` fell back to
    loading that file — green locally, ``FileNotFoundError`` in CI. This guard
    fails loudly if a future edit reintroduces the fallback.
    """

    def test_rendering_never_resolves_config_from_disk(self, base_dir, app_config, monkeypatch):
        # Trip on *any* attempt to resolve config.yaml. Checking "does it work
        # without the file" is not enough: `_legacy_config_candidates()` locates
        # the repo root from `__file__`, so a developer's config.yaml is found
        # whatever the cwd, and the fallback stays invisible until CI. Every
        # disk resolution funnels through resolve_config_path, so failing it
        # here makes the omission fail on the developer's machine instead.
        def _fail() -> None:
            raise AssertionError("apply_prompt_template resolved config.yaml from disk; pass app_config explicitly")

        monkeypatch.setattr(AppConfig, "resolve_config_path", staticmethod(_fail))
        rendered = apply_prompt_template(agent_name="Tester", app_config=app_config)
        assert "<role>" in rendered


class TestApplyPromptTemplate:
    def test_uses_the_override(self, base_dir, app_config):
        store.save_custom_system_prompt("CUSTOM PROMPT for {agent_name}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        rendered = apply_prompt_template(agent_name="Tester", app_config=app_config)
        assert rendered == "CUSTOM PROMPT for Tester"

    def test_falls_back_when_the_override_cannot_render(self, base_dir, app_config):
        # Simulate a template that passes validation but still explodes at
        # render time (a placeholder the renderer does not supply); the run must
        # survive it on the built-in prompt.
        with patch("deerflow.agents.lead_agent.prompt.get_system_prompt_template", return_value="{agent_name} {boom}"):
            rendered = apply_prompt_template(agent_name="Tester", app_config=app_config)
        assert "<role>" in rendered
        assert "You are Tester" in rendered

    def test_default_path_still_renders_the_builtin(self, base_dir, app_config):
        rendered = apply_prompt_template(agent_name="Tester", app_config=app_config)
        assert "<role>" in rendered
        assert "You are Tester" in rendered

    def test_an_override_dropping_a_section_renders_without_it(self, base_dir, app_config):
        store.save_custom_system_prompt("Only skills:\n{skills_section}", allowed=SYSTEM_PROMPT_PLACEHOLDERS)
        rendered = apply_prompt_template(agent_name="Tester", app_config=app_config)
        assert rendered.startswith("Only skills:")
        assert "<thinking_style>" not in rendered
