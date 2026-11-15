"""The CAD module ships installed and enabled (FORK.md §51).

Three places must agree, and none of them drifts loudly on its own:

- ``examples/deerflow-extension-cad`` is the source, where its tests run;
- ``backend/extensions/sources/deerflow-extension-cad`` is the managed snapshot
  uv installs from (the Docker build context excludes ``examples/``);
- ``config.example.yaml``'s ``plugins:`` record turns it on.

An edit to the example that skips the snapshot ships stale code to every
install while every CAD test stays green against the example. For a module
whose interpreter is a security boundary, stale is the wrong default.
"""

from __future__ import annotations

import os
import shutil
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

from deerflow.extensions.loader import ExtensionLoadError, ExtensionSpec, load_extensions
from deerflow.extensions.manager import _SNAPSHOT_IGNORES, _validate_locked_local_sources
from deerflow.tools.internet_access import LOCAL_EXTENSION_TOOL_GROUP

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
EXAMPLE = REPO_ROOT / "examples" / "deerflow-extension-cad"
SNAPSHOT = BACKEND / "extensions" / "sources" / "deerflow-extension-cad"
# Caches a test or lint run leaves beside the example; the manager's own list has no need for them.
_LOCAL_CACHES = (".ruff_cache", ".pytest_cache")


def _files(root: Path) -> dict[str, bytes]:
    """Every file the extension manager would snapshot, keyed by relative path."""
    ignore = shutil.ignore_patterns(*_SNAPSHOT_IGNORES, *_LOCAL_CACHES)
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

    hint = "copy examples/deerflow-extension-cad/ over backend/extensions/sources/deerflow-extension-cad/ (without __pycache__)"
    assert snapshot.keys() == example.keys(), hint
    stale = sorted(name for name in example if example[name] != snapshot[name])
    assert not stale, f"{hint}; stale: {stale}"


def test_the_backend_installs_it_from_the_snapshot_everywhere_but_windows():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    entries = [Requirement(entry) for entry in project["dependency-groups"]["extensions"]]
    (cad,) = [entry for entry in entries if entry.name == "deerflow-extension-cad"]

    # The worker is POSIX-only (process group, resource limits): a Windows
    # `uv sync` must skip the module and its 1.7 GB kernel rather than install it.
    assert cad.marker is not None and not cad.marker.evaluate({"sys_platform": "win32"})
    assert cad.marker.evaluate({"sys_platform": "linux"}) and cad.marker.evaluate({"sys_platform": "darwin"})
    assert project["tool"]["uv"]["sources"]["deerflow-extension-cad"] == {"path": "extensions/sources/deerflow-extension-cad"}
    # The stock image build copies backend/ only; the lock must not point outside it.
    _validate_locked_local_sources(BACKEND / "uv.lock", BACKEND)


def test_a_pull_that_changes_only_code_rebuilds_the_installed_copy():
    # uv rebuilds a directory dependency only when its pyproject.toml changes unless told
    # otherwise: without these keys a `git pull` that changed the interpreter kept the old one installed.
    project = tomllib.loads((SNAPSHOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["cache-keys"] == [{"file": "pyproject.toml"}, {"file": "deerflow_extension_cad/**/*"}]


def test_the_shipped_record_loads_enabled_and_offers_one_offline_safe_tool():
    example = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    (record,) = [entry for entry in example["plugins"] if entry["name"] == "cad"]
    assert (record["package"], record["enabled"], record["required"]) == ("deerflow-extension-cad", True, False)

    loaded, diagnostics = load_extensions([ExtensionSpec(**record)])

    assert not diagnostics, diagnostics
    ((_, declaration),) = loaded.plugins
    assert declaration.namespace == "cad" and declaration.enabled is True
    (tool,) = declaration.tools
    assert (tool.name, tool.group) == ("cad_build", LOCAL_EXTENSION_TOOL_GROUP)
    # A Gateway that starts with the module on does not load the kernel: that happens in a child, per build.
    assert not {"cadquery", "OCP", "vtk"} & set(sys.modules)


def test_the_record_is_not_required_so_a_host_without_the_package_still_starts():
    # Windows gets the record from the example and no package (the marker above).
    # A required plugin that cannot be imported stops the Gateway; this one must not.
    example = yaml.safe_load((REPO_ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    (record,) = [entry for entry in example["plugins"] if entry["name"] == "cad"]
    missing = {**record, "use": "deerflow_extension_cad_not_installed:install"}

    loaded, diagnostics = load_extensions([ExtensionSpec(**missing)])

    # Reported, not fatal: the Gateway starts without the tool.
    assert not loaded.plugins
    assert [diagnostic.source for diagnostic in diagnostics] == ["deerflow_extension_cad_not_installed:install"]
    with pytest.raises(ExtensionLoadError):
        load_extensions([ExtensionSpec(**{**missing, "required": True})])
