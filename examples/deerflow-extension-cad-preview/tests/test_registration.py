"""Offline registration and packaged browser-asset checks."""

import json
import re
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/packages/extension-api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

install = import_module("deerflow_extension_cad_preview").install


def _register(config):
    contributions = []
    install(
        SimpleNamespace(plugin=lambda value: contributions.append(value) or True),
        config,
    )
    return contributions[0]


class RegistrationTests(unittest.TestCase):
    def test_registration_has_only_the_browser_contribution(self):
        contribution = _register({})
        self.assertEqual(contribution.namespace, "cad-preview")
        self.assertEqual(contribution.frontend.module, "cad-preview")
        self.assertTrue(contribution.enabled)
        self.assertFalse(contribution.backend)
        self.assertFalse(contribution.tools)

    def test_packaged_assets_fit_the_host_limits(self):
        root = _register({}).frontend.root
        manifest = json.loads((root / "ui_manifest.json").read_text(encoding="utf-8"))
        self.assertIn(manifest["entry"], manifest["files"])
        self.assertEqual(len(set(manifest["files"])), len(manifest["files"]))
        listed = sorted(
            str(path.relative_to(root))
            for path in (root / "static").rglob("*")
            if path.is_file()
        )
        self.assertEqual(listed, sorted(manifest["files"]))
        for filename in manifest["files"]:
            self.assertLess((root / filename).stat().st_size, 4 * 1024 * 1024, filename)

    def test_the_worker_is_one_module_that_fetches_nothing(self):
        # Gateway assets carry CSP: sandbox, so the Worker has an opaque origin.
        worker = (
            _register({}).frontend.root / "static/dist/chunks/model-worker.mjs"
        ).read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"\bimport\s*[(\"'{*]|\bfetch\(|importScripts", worker)
        )

    def test_disabled_and_invalid_configuration(self):
        self.assertFalse(_register({"enabled": False}).enabled)
        registry = SimpleNamespace(plugin=lambda value: True)
        for enabled in ("false", 1, None):
            with self.assertRaises(ValueError):
                install(registry, {"enabled": enabled})

    def test_unsupported_host_fails_clearly(self):
        with self.assertRaises(RuntimeError):
            install(SimpleNamespace(plugin=lambda value: False), {})


if __name__ == "__main__":
    unittest.main()
