"""Tests for scripts/configure.py (the `make config` bootstrap flow).

Focused on the sandbox choice: opting into the containerized AIO sandbox must
write the per-thread *container* mode (no base_url) — matching `make setup` and
the recommended clone-and-debug workflow — not the external `base_url` mode
that needs a separate `make sandbox-up`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "configure.py"


def _load():
    spec = importlib.util.spec_from_file_location("deerflow_configure", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


configure = _load()


def test_sandbox_choice_enables_container_mode(monkeypatch):
    monkeypatch.setattr(configure, "_prompt_yes_no", lambda _q, **_kw: True)
    calls: list[list[str]] = []

    class _Result:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(configure.subprocess, "run", fake_run)

    configure._offer_sandbox_choice(REPO_ROOT)

    assert len(calls) == 1
    cmd = calls[0]
    assert str(SCRIPT_PATH.parent / "sandbox_toggle.py") in cmd
    assert cmd[-3:] == ["enable", "--mode", "container"]


def test_sandbox_choice_declined_is_a_noop(monkeypatch):
    monkeypatch.setattr(configure, "_prompt_yes_no", lambda _q, **_kw: False)
    called = False

    def fake_run(cmd, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(configure.subprocess, "run", fake_run)

    configure._offer_sandbox_choice(REPO_ROOT)

    assert called is False


def test_sandbox_choice_reports_failure(monkeypatch, capsys):
    monkeypatch.setattr(configure, "_prompt_yes_no", lambda _q, **_kw: True)

    class _Result:
        returncode = 1

    monkeypatch.setattr(configure.subprocess, "run", lambda cmd, **kwargs: _Result())

    configure._offer_sandbox_choice(REPO_ROOT)

    out = capsys.readouterr().out
    assert "edit config.yaml by hand" in out


def test_declined_choice_does_not_mention_sandbox_up(monkeypatch, capsys):
    """Container mode auto-starts; the success path must not tell users to run make sandbox-up."""
    monkeypatch.setattr(configure, "_prompt_yes_no", lambda _q, **_kw: True)

    class _Result:
        returncode = 0

    monkeypatch.setattr(configure.subprocess, "run", lambda cmd, **kwargs: _Result())

    configure._offer_sandbox_choice(REPO_ROOT)

    out = capsys.readouterr().out
    assert "sandbox-up" not in out


class TestPromptDefaults:
    """The yes/no prompt honors a per-question default; non-interactive stays no."""

    class _FakeTty:
        @staticmethod
        def isatty():
            return True

    class _FakePipe:
        @staticmethod
        def isatty():
            return False

    def test_non_interactive_returns_false_even_with_default_yes(self, monkeypatch):
        monkeypatch.setattr(configure.sys, "stdin", self._FakePipe())
        assert configure._prompt_yes_no("q?", default=True) is False

    def test_empty_answer_returns_the_default(self, monkeypatch):
        monkeypatch.setattr(configure.sys, "stdin", self._FakeTty())
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        assert configure._prompt_yes_no("q?", default=True) is True
        assert configure._prompt_yes_no("q?", default=False) is False

    def test_explicit_no_beats_default_yes(self, monkeypatch):
        monkeypatch.setattr(configure.sys, "stdin", self._FakeTty())
        monkeypatch.setattr("builtins.input", lambda _prompt: "n")
        assert configure._prompt_yes_no("q?", default=True) is False

    def test_prompt_suffix_reflects_default(self, monkeypatch):
        monkeypatch.setattr(configure.sys, "stdin", self._FakeTty())
        seen: list[str] = []

        def fake_input(prompt: str) -> str:
            seen.append(prompt)
            return ""

        monkeypatch.setattr("builtins.input", fake_input)
        configure._prompt_yes_no("q?", default=True)
        configure._prompt_yes_no("q?", default=False)
        assert "[Y/n]" in seen[0]
        assert "[y/N]" in seen[1]


class TestSandboxOfferDefault:
    """The AIO sandbox offer defaults to yes exactly when a container runtime exists."""

    def _seen_default(self, monkeypatch, runtime_available: bool) -> bool:
        monkeypatch.setattr(configure, "_container_runtime_available", lambda: runtime_available)
        seen: dict[str, bool] = {}

        def fake_prompt(question, *, default=False):
            seen["default"] = default
            return False

        monkeypatch.setattr(configure, "_prompt_yes_no", fake_prompt)
        configure._offer_sandbox_choice(REPO_ROOT)
        return seen["default"]

    def test_defaults_to_yes_with_container_runtime(self, monkeypatch):
        assert self._seen_default(monkeypatch, runtime_available=True) is True

    def test_defaults_to_no_without_container_runtime(self, monkeypatch):
        assert self._seen_default(monkeypatch, runtime_available=False) is False

    def test_declining_prints_how_to_enable_later(self, monkeypatch, capsys):
        monkeypatch.setattr(configure, "_prompt_yes_no", lambda _q, **_kw: False)
        configure._offer_sandbox_choice(REPO_ROOT)
        out = capsys.readouterr().out
        assert "bash" in out
        assert "make sandbox-enable MODE=container" in out
