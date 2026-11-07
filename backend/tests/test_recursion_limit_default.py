"""The fork's 250-super-step run budget, and the three places it must agree.

Upstream ships 100. This fork ships 250 because its own use case is a long
clone-and-iterate agent session: many `bash` / `read_file` / `write_file` /
`str_replace` turns, each one a LangGraph super-step, which abort mid-task with
``GraphRecursionError`` under a lower cap.

Why this needs a test at all: the failure is **silent to the suite**. Taking
upstream's 100 in a sync conflict changes no API, breaks no import, and leaves
every other test green — the only symptom is a long run that stops early, in
production, with a recursion error the user reads as the agent giving up.

Three values have to say 250 together, because each one is the number some
deployment actually gets:

* ``AppConfig.recursion_limit`` — the default for an existing install whose
  ``config.yaml`` predates the key and therefore never mentions it.
* ``config.example.yaml`` — what a fresh install copies.
* ``services._DEFAULT_RECURSION_LIMIT`` — the fallback when app config cannot
  be loaded at all.

A sync that updates one and not the others is the same silent shortfall for
whichever population reads the stale one.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.gateway import services
from deerflow.config.app_config import AppConfig

FORK_RECURSION_LIMIT = 250
CONFIG_EXAMPLE = Path(__file__).resolve().parents[2] / "config.example.yaml"


def test_app_config_defaults_to_the_fork_budget():
    """The value an install with no `recursion_limit` key in config.yaml gets.

    Read off the field rather than an instance: `AppConfig` has required fields,
    and it is precisely the *unset* case this pins.
    """
    assert AppConfig.model_fields["recursion_limit"].default == FORK_RECURSION_LIMIT


def test_the_config_load_failure_fallback_matches_the_configured_default():
    """A missing config.yaml must not quietly shorten runs to upstream's 100."""
    assert services._DEFAULT_RECURSION_LIMIT == FORK_RECURSION_LIMIT


def test_config_example_ships_the_fork_budget():
    """What a fresh `make config` writes — the value most installs run on."""
    text = CONFIG_EXAMPLE.read_text(encoding="utf-8")
    match = re.search(r"^recursion_limit:\s*(\d+)\s*$", text, re.MULTILINE)
    assert match is not None, "config.example.yaml no longer ships a top-level recursion_limit"
    assert int(match.group(1)) == FORK_RECURSION_LIMIT


def test_the_budget_stays_under_the_shipped_ceiling():
    """A default above `max_recursion_limit` would be clamped on every run."""
    assert AppConfig.model_fields["recursion_limit"].default <= AppConfig.model_fields["max_recursion_limit"].default


class TestDoublePlusUltracodeStepCeiling:
    """Double Plus Ultracode runs to the operator's step ceiling (FORK.md §44).

    Its workflow agents send no ``recursion_limit``, so they stopped at the
    default with the task unfinished even though tool-call limits were off.
    """

    def _config(self, mode, limit=FORK_RECURSION_LIMIT):
        return {"recursion_limit": limit, "context": {"mode": mode}, "configurable": {"thread_id": "t"}}

    def test_a_double_plus_run_without_a_step_limit_gets_the_ceiling(self, monkeypatch):
        monkeypatch.setattr(services, "_resolve_max_recursion_limit", lambda: 1000)
        config = self._config("double_ultracode")
        services.apply_double_ultracode_step_ceiling(config, None)
        assert config["recursion_limit"] == 1000

    def test_other_modes_keep_the_default(self, monkeypatch):
        monkeypatch.setattr(services, "_resolve_max_recursion_limit", lambda: 1000)
        for mode in ("ultracode", "ultra", None):
            config = self._config(mode)
            services.apply_double_ultracode_step_ceiling(config, {})
            assert config["recursion_limit"] == FORK_RECURSION_LIMIT, mode

    def test_an_explicit_client_limit_is_left_to_the_ordinary_clamp(self, monkeypatch):
        monkeypatch.setattr(services, "_resolve_max_recursion_limit", lambda: 1000)
        config = self._config("double_ultracode", limit=40)
        services.apply_double_ultracode_step_ceiling(config, {"recursion_limit": 40})
        assert config["recursion_limit"] == 40
