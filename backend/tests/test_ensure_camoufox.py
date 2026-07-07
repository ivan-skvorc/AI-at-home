"""Tests for scripts/ensure_camoufox.py.

The script auto-fetches the Camoufox browser binaries after `uv sync` on every
launch path when the camoufox web_fetch backend is selected. These pin the pure
browser-presence probe, which mirrors
`deerflow.community.camoufox_fetch.browser._camoufox_browser_present` so the
launch-time and runtime checks agree.
"""

from __future__ import annotations

import importlib.util
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
