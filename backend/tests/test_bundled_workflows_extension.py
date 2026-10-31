"""The Script workflows extension ships installed and enabled (Double Plus Ultracode).

Three places must agree, and none of them drifts loudly on its own:

- ``examples/deerflow-extension-workflows`` is the source, where its tests run;
- ``backend/extensions/sources/deerflow-extension-workflows`` is the managed
  snapshot uv installs from (the Docker build context excludes ``examples/``);
- ``config.example.yaml``'s ``plugins:`` record turns it on.

An edit to the example that skips the snapshot ships stale code to every
install while every workflow test stays green against the example.
"""

from __future__ import annotations

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
EXAMPLE = REPO_ROOT / "examples" / "deerflow-extension-workflows"
SNAPSHOT = BACKEND / "extensions" / "sources" / "deerflow-extension-workflows"


def _files(root: Path) -> dict[str, bytes]:
    """Every file the extension manager would snapshot, keyed by relative path."""
    ignore = shutil.ignore_patterns(*_SNAPSHOT_IGNORES)
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        ignored = ignore(dirpath, dirnames + filenames)
        dirnames[:] = [name for name in dirnames if name not in ignored]
        for name in filenames:
            if name not in ignored:
                path = Path(dirpath) / name
                files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def test_the_installed_snapshot_matches_the_example_source():
    example, snapshot = _files(EXAMPLE), _files(SNAPSHOT)

    hint = "copy examples/deerflow-extension-workflows/ over backend/extensions/sources/deerflow-extension-workflows/ (without __pycache__)"
    assert snapshot.keys() == example.keys(), hint
    stale = sorted(name for name in example if example[name] != snapshot[name])
    assert not stale, f"{hint}; stale: {stale}"


def test_the_backend_installs_it_from_the_snapshot_everywhere_but_windows():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    entries = [Requirement(entry) for entry in project["dependency-groups"]["extensions"]]
    (workflows,) = [entry for entry in entries if entry.name == "deerflow-extension-workflows"]

    # QuickJS has no Windows wheel and the worker is POSIX-only: a Windows
    # `uv sync` must skip it rather than fail to build it.
    assert workflows.marker is not None and not workflows.marker.evaluate({"sys_platform": "win32"})
    assert workflows.marker.evaluate({"sys_platform": "linux"}) and workflows.marker.evaluate({"sys_platform": "darwin"})
    assert project["tool"]["uv"]["sources"]["deerflow-extension-workflows"] == {"path": "extensions/sources/deerflow-extension-workflows"}
    # The stock image build copies backend/ only; the lock must not point outside it.
    _validate_locked_local_sources(BACKEND / "uv.lock", BACKEND)


def test_the_shipped_record_loads_enabled_with_its_store_under_deer_flow_home(tmp_path, monkeypatch):
    example = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    (record,) = [entry for entry in example["plugins"] if entry["name"] == "workflows"]
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))

    loaded, diagnostics = load_extensions([ExtensionSpec(**record)])

    assert not diagnostics, diagnostics
    ((_, declaration),) = loaded.plugins
    # The composer offers Double Plus Ultracode only for an enabled community.workflows.
    assert declaration.namespace == "community.workflows" and declaration.enabled is True
    service = next(action.handler for action in declaration.backend if action.name == "launch").__self__
    assert service.config["storage_path"] == str(tmp_path / "workflows" / "workflows.sqlite")
