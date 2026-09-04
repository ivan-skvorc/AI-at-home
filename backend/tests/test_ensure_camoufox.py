"""Tests for scripts/ensure_camoufox.py.

The script auto-fetches the Camoufox browser binaries after `uv sync` on every
launch path when the camoufox web_fetch backend is selected. These pin the pure
browser-presence probe, which mirrors
`deerflow.community.camoufox_fetch.browser._camoufox_browser_present` so the
launch-time and runtime checks agree.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ensure_camoufox.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("ensure_camoufox", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ensure_camoufox = _load_script()


class TestBrowserPresent:
    def test_missing_version_json_is_absent(self, tmp_path: Path):
        assert ensure_camoufox.browser_present(tmp_path) is False

    def test_version_json_present_is_present(self, tmp_path: Path):
        (tmp_path / "version.json").write_text("{}", encoding="utf-8")
        assert ensure_camoufox.browser_present(tmp_path) is True

    def test_none_install_dir_is_absent(self):
        assert ensure_camoufox.browser_present(None) is False

    def test_nonexistent_dir_is_absent(self, tmp_path: Path):
        assert ensure_camoufox.browser_present(tmp_path / "does-not-exist") is False


class TestFetchEnvironment:
    """`camoufox fetch` must not inherit a GitHub credential.

    Camoufox resolves its browser release by calling the GitHub releases API.
    Unauthenticated calls succeed (200, or 403 when rate-limited); a *stale*
    credential gets 401, and camoufox treats that as fatal rather than retrying
    anonymously — "Synced 0 versions from 0 repos", then every web_fetch fails.
    The gateway container loads the whole repo-root .env, which is where
    GITHUB_TOKEN lives for the sandbox, so this is the default Docker path.
    """

    def test_github_credentials_are_stripped(self):
        env = ensure_camoufox.fetch_environment({"PATH": "/usr/bin", "GITHUB_TOKEN": "ghp_stale", "GH_TOKEN": "also_stale", "HOME": "/root"})
        assert "GITHUB_TOKEN" not in env
        assert "GH_TOKEN" not in env

    def test_everything_else_is_preserved(self):
        env = ensure_camoufox.fetch_environment({"PATH": "/usr/bin", "HOME": "/root", "HTTPS_PROXY": "http://proxy:3128"})
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/root"
        assert env["HTTPS_PROXY"] == "http://proxy:3128"

    def test_the_caller_environment_is_not_mutated(self):
        original = {"GITHUB_TOKEN": "ghp_stale"}
        ensure_camoufox.fetch_environment(original)
        assert original == {"GITHUB_TOKEN": "ghp_stale"}

    def test_the_fetch_call_site_actually_uses_the_scrubbed_environment(self, monkeypatch):
        """Pins the wiring, not just the helper.

        `fetch_environment` can be correct while the call site fails to reach it
        — the first version of this fix passed every helper test and would have
        raised NameError on the real path, because the module never imported
        `os`. Only exercising the subprocess call catches that.
        """
        captured = {}

        def fake_call(argv, env=None):
            captured["argv"] = argv
            captured["env"] = env
            return 0

        # main() returns early unless the camoufox extra is importable; this
        # suite runs without it, so stand one in.
        monkeypatch.setitem(sys.modules, "camoufox", types.ModuleType("camoufox"))
        monkeypatch.setattr(ensure_camoufox.subprocess, "call", fake_call)
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_stale")
        monkeypatch.setattr(ensure_camoufox, "browser_install_dir", lambda: None)
        monkeypatch.setattr(ensure_camoufox, "browser_present", lambda *_a, **_k: False)

        ensure_camoufox.main()

        assert captured["env"] is not None, "fetch ran with an inherited environment"
        assert "GITHUB_TOKEN" not in captured["env"]
        assert "camoufox" in captured["argv"]
