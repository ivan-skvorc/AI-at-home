"""The CAD model preview ships installed and enabled (FORK.md, viewer section).

Three places must agree, and none of them drifts loudly on its own:

- ``examples/deerflow-extension-cad-preview`` is the source, where its tests run
  and where ``node build.mjs`` writes the browser bundle;
- ``backend/extensions/sources/deerflow-extension-cad-preview`` is the managed
  snapshot uv installs from (the Docker build context excludes ``examples/``);
- ``config.example.yaml``'s ``plugins:`` record turns it on, and migration 76
  of ``scripts/config_upgrade.py`` hands that record to an existing install.

An edit to the example that skips the snapshot ships a stale viewer to every
install while every preview test stays green against the example.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.manager import _SNAPSHOT_IGNORES, _validate_locked_local_sources

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
EXAMPLE = REPO_ROOT / "examples" / "deerflow-extension-cad-preview"
SNAPSHOT = BACKEND / "extensions" / "sources" / "deerflow-extension-cad-preview"
# Caches a test or lint run leaves beside the example; the manager's own list has no need for them.
_LOCAL_CACHES = (".ruff_cache", ".pytest_cache")
# The example's build tools (three and esbuild, about 20 MB). The bundle they build ships
# in static/dist; the tools themselves must never reach the snapshot.
_BUILD_TOOLS = ("node_modules",)
RECORD = {
    "name": "cad-preview",
    "package": "deerflow-extension-cad-preview",
    "use": "deerflow_extension_cad_preview:install",
    "enabled": True,
    "required": False,
    "config": {"enabled": True},
}
BASE = "sandbox:\n  use: custom\nmodels: []\n"


def _files(root: Path, *extra_ignores: str) -> dict[str, bytes]:
    """Every file the extension manager would snapshot, keyed by relative path."""
    ignore = shutil.ignore_patterns(*_SNAPSHOT_IGNORES, *_LOCAL_CACHES, *extra_ignores)
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        ignored = ignore(dirpath, dirnames + filenames)
        dirnames[:] = [name for name in dirnames if name not in ignored]
        for name in filenames:
            if name not in ignored:
                path = Path(dirpath) / name
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _config_upgrade():
    spec = importlib.util.spec_from_file_location("config_upgrade", REPO_ROOT / "scripts" / "config_upgrade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shipped_example() -> dict:
    return yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))


def test_the_installed_snapshot_matches_the_example_source():
    # node_modules is left out on the example side only: a snapshot that carries it fails here.
    example, snapshot = _files(EXAMPLE, *_BUILD_TOOLS), _files(SNAPSHOT)

    hint = "rsync -a --delete --exclude node_modules --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache examples/deerflow-extension-cad-preview/ backend/extensions/sources/deerflow-extension-cad-preview/"
    assert snapshot, f"no snapshot yet; {hint}"
    assert snapshot.keys() == example.keys(), hint
    stale = sorted(name for name in example if example[name] != snapshot[name])
    assert not stale, f"{hint}; stale: {stale}"
    # The browser bundle is built, not installed: the snapshot must carry it.
    assert "deerflow_extension_cad_preview/static/dist/index.mjs" in snapshot


def test_the_backend_installs_it_from_the_snapshot_on_every_host():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    entries = [Requirement(entry) for entry in project["dependency-groups"]["extensions"]]
    (preview,) = [entry for entry in entries if entry.name == "deerflow-extension-cad-preview"]

    # Pure Python and a prebuilt browser bundle: no platform has a reason to skip it.
    assert preview.marker is None
    assert "extensions" in project["tool"]["uv"]["default-groups"]
    assert project["tool"]["uv"]["sources"]["deerflow-extension-cad-preview"] == {"path": "extensions/sources/deerflow-extension-cad-preview"}
    # The stock image build copies backend/ only; the lock must not point outside it.
    _validate_locked_local_sources(BACKEND / "uv.lock", BACKEND)


def test_a_pull_that_changes_only_the_bundle_rebuilds_the_installed_copy():
    # uv rebuilds a directory dependency only when its pyproject.toml changes unless told
    # otherwise: without these keys a `git pull` that rebuilt the viewer kept the old bundle installed.
    project = tomllib.loads((SNAPSHOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["cache-keys"] == [{"file": "pyproject.toml"}, {"file": "deerflow_extension_cad_preview/**/*"}]


def test_the_shipped_record_loads_enabled_with_only_a_browser_contribution():
    (record,) = [entry for entry in _shipped_example()["plugins"] if entry["name"] == "cad-preview"]
    assert record == RECORD

    loaded, diagnostics = load_extensions([ExtensionSpec(**record)])

    assert not diagnostics, diagnostics
    ((_, contribution),) = loaded.plugins
    assert (contribution.namespace, contribution.enabled) == ("cad-preview", True)
    assert contribution.frontend.module == "cad-preview"
    # Browser-only: no tool in any model's context, no route on the Gateway.
    assert not contribution.tools and not contribution.backend
    assert not loaded.routers


def test_the_migration_delivers_the_shipped_record():
    config_upgrade = _config_upgrade()
    example = _shipped_example()

    assert example["config_version"] >= 76
    assert config_upgrade.MIGRATIONS[76]["plugins_from_example"] == ("cad-preview",)


def test_an_install_on_the_previous_version_gets_the_record_exactly_once(tmp_path):
    config_upgrade = _config_upgrade()
    example = tmp_path / "config.example.yaml"
    example.write_text(f"config_version: 76\n{BASE}" + yaml.safe_dump({"plugins": [RECORD]}, sort_keys=False), encoding="utf-8")
    acme = {"name": "acme", "use": "acme_ext:install"}
    config = tmp_path / "config.yaml"
    config.write_text(f"config_version: 75\n{BASE}" + yaml.safe_dump({"plugins": [acme]}, sort_keys=False), encoding="utf-8")

    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
    upgraded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert (upgraded["config_version"], upgraded["plugins"]) == (76, [acme, RECORD])

    # The operator removes the record afterwards: the next launch's upgrade must not bring it back.
    removed = f"config_version: 76\n{BASE}" + yaml.safe_dump({"plugins": [acme]}, sort_keys=False)
    config.write_text(removed, encoding="utf-8")
    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
    assert config.read_text(encoding="utf-8") == removed


def test_a_record_the_operator_already_has_is_left_alone(tmp_path):
    """A disabled record, or one `make extension-install` wrote, keeps its own settings."""
    config_upgrade = _config_upgrade()
    example = tmp_path / "config.example.yaml"
    example.write_text(f"config_version: 76\n{BASE}" + yaml.safe_dump({"plugins": [RECORD]}, sort_keys=False), encoding="utf-8")
    mine = {"name": "model-viewer", "package": "deerflow_extension_cad_preview", "use": "deerflow_extension_cad_preview:install", "enabled": False}
    config = tmp_path / "config.yaml"
    config.write_text(f"config_version: 75\n{BASE}" + yaml.safe_dump({"plugins": [mine]}, sort_keys=False), encoding="utf-8")

    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0

    assert yaml.safe_load(config.read_text(encoding="utf-8"))["plugins"] == [mine]
