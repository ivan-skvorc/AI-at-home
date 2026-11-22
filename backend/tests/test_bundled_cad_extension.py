"""The CAD module ships installed and enabled (FORK.md §51).

Three places must agree, and none of them drifts loudly on its own:

- ``examples/deerflow-extension-cad`` is the source, where its tests run;
- ``backend/extensions/sources/deerflow-extension-cad`` is the managed snapshot
  uv installs from (the Docker build context excludes ``examples/``);
- ``config.example.yaml``'s ``plugins:`` record turns it on.

A fourth follows from the first: ``skills/public/cad-modeling/references/operations.md``
is the allow-list as a model reads it.

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


def test_the_skills_operations_page_is_the_installed_allow_list():
    # The cad-modeling skill teaches a model the methods a script may call. Its own test runs in
    # Skill Review CI, which a change to the allow-list alone does not start: this one runs with it.
    allowlist = pytest.importorskip("deerflow_extension_cad.allowlist", reason="the CAD module is not installed on this host")

    page = REPO_ROOT / "skills" / "public" / "cad-modeling" / "references" / "operations.md"
    hint = "regenerate it: python examples/deerflow-extension-cad/deerflow_extension_cad/allowlist.py > skills/public/cad-modeling/references/operations.md"
    assert page.read_text(encoding="utf-8") == allowlist.reference(), hint


def test_the_backend_installs_it_from_the_snapshot_only_where_the_kernel_has_wheels():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    (cad,) = [Requirement(entry) for entry in project["dependency-groups"]["cad"]]
    assert cad.name == "deerflow-extension-cad" and cad.marker is not None

    def installs(sys_platform: str, platform_machine: str) -> bool:
        return cad.marker.evaluate({"sys_platform": sys_platform, "platform_machine": platform_machine})

    assert installs("linux", "x86_64") and installs("linux", "aarch64") and installs("darwin", "arm64")
    # The kernel has no wheel for an Intel Mac, and its worker is POSIX-only. A locked sync that
    # names a package without a wheel for the host fails whole, and the install stops starting.
    assert not installs("darwin", "x86_64") and not installs("win32", "AMD64") and not installs("linux", "armv7l")
    # In a group of its own, in the default set: installed without being asked for, and droppable alone.
    assert "cad" in project["tool"]["uv"]["default-groups"]
    assert not [entry for entry in project["dependency-groups"]["extensions"] if Requirement(entry).name == "deerflow-extension-cad"]
    assert project["tool"]["uv"]["sources"]["deerflow-extension-cad"] == {"path": "extensions/sources/deerflow-extension-cad"}
    # The stock image build copies backend/ only; the lock must not point outside it.
    _validate_locked_local_sources(BACKEND / "uv.lock", BACKEND)


def test_a_host_the_kernel_cannot_be_installed_on_still_installs_everything_else():
    # glibc older than 2.31 has no wheel either, and no marker can say so. Every local path that
    # syncs with --locked retries once without the group instead of leaving the install unable to start.
    serve = (REPO_ROOT / "scripts" / "serve.sh").read_text(encoding="utf-8")
    multi = (REPO_ROOT / "scripts" / "dev_multi_instance.sh").read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for text, first in ((serve, "uv sync --locked --quiet --all-packages $UV_EXTRAS_FLAGS"), (multi, "uv sync --locked --quiet --all-packages $extras"), (makefile, "cd backend && uv sync --locked ||")):
        retry = text.index("--no-group cad")
        assert 0 <= text.index(first) < retry, first
    # The retry drops this group only: the workflows extension stays installed.
    assert "--no-group extensions" not in serve and "--no-group extensions" not in multi
    assert "uv sync --locked --no-group cad" in makefile


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
