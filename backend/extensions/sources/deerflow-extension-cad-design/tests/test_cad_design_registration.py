"""Packaged browser-asset checks (registration itself is in test_install.py)."""

import json
import re
from pathlib import Path

import pytest

from deerflow_extension_cad_design import install

MiB = 1024 * 1024
# Gateway assets carry CSP: sandbox, so a Worker's origin is opaque: no imports, no network.
NETWORK = re.compile(r"\bimport\s*[(\"'{*]|\bfetch\(|importScripts|XMLHttpRequest\s*\(")


class Registry:
    def __init__(self):
        self.plugins = []

    def plugin(self, contribution):
        self.plugins.append(contribution)
        return True

    def middlewares(self, contributor):
        pass

    def service(self, service):
        pass


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    registry = Registry()
    install(registry, {})
    return Path(registry.plugins[0].frontend.root)


def test_the_manifest_lists_exactly_the_built_files_within_the_host_limits(root):
    manifest = json.loads((root / "ui_manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry"] == "static/dist/index.mjs"
    assert len(set(manifest["files"])) == len(manifest["files"])
    built = sorted(path.relative_to(root).as_posix() for path in (root / "static").rglob("*") if path.is_file())
    assert built == sorted(manifest["files"])
    sizes = {name: (root / name).stat().st_size for name in manifest["files"]}
    assert all(size < 4 * MiB for size in sizes.values()), sizes
    assert sum(sizes.values()) < 16 * MiB
    # The page renders nothing itself: no OpenSCAD WebAssembly build, which kept the package GPL.
    assert not any(name.endswith(".wasm") for name in manifest["files"])
    assert not any("scad-worker" in name for name in manifest["files"])


def test_the_mesh_worker_is_one_module_that_fetches_nothing(root):
    source = (root / "static/dist/chunks/model-worker.mjs").read_text(encoding="utf-8")
    assert NETWORK.search(source) is None
