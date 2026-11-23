"""The CAD design page ships installed and enabled (FORK.md §58).

Three places must agree, and none of them drifts loudly on its own:

- ``examples/deerflow-extension-cad-design`` is the source, where its tests run
  and where ``node build.mjs`` writes the browser bundle;
- ``backend/extensions/sources/deerflow-extension-cad-design`` is the managed
  snapshot uv installs from (the Docker build context excludes ``examples/``);
- ``config.example.yaml``'s ``plugins:`` record turns it on, and migration 78
  of ``scripts/config_upgrade.py`` hands that record to an existing install.

The page's ``ui/`` imports cad-preview's ``ui/`` by relative path, so the
snapshot must sit beside the cad-preview snapshot as the examples do.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.extensions.manager import _SNAPSHOT_IGNORES, _validate_locked_local_sources
from deerflow.extensions.plugin_tools import plugin_tool_name

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
EXAMPLE = REPO_ROOT / "examples" / "deerflow-extension-cad-design"
SNAPSHOT = BACKEND / "extensions" / "sources" / "deerflow-extension-cad-design"
_LOCAL_CACHES = (".ruff_cache", ".pytest_cache")
# The example's build tools (three, CodeMirror, esbuild, the OpenSCAD npm package).
# The bundle they build ships in static/dist; the tools never reach the snapshot.
_BUILD_TOOLS = ("node_modules",)
RECORD = {
    "name": "cad-design",
    "package": "deerflow-extension-cad-design",
    "use": "deerflow_extension_cad_design:install",
    "enabled": True,
    "required": False,
    "config": {"enabled": True, "storage_path": "cad-design/designs.sqlite", "max_source_bytes": 65536},
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
    example, snapshot = _files(EXAMPLE, *_BUILD_TOOLS), _files(SNAPSHOT)

    hint = "rsync -a --delete --exclude node_modules --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache examples/deerflow-extension-cad-design/ backend/extensions/sources/deerflow-extension-cad-design/"
    assert snapshot, f"no snapshot yet; {hint}"
    assert snapshot.keys() == example.keys(), hint
    stale = sorted(name for name in example if example[name] != snapshot[name])
    assert not stale, f"{hint}; stale: {stale}"
    # The browser bundle and the OpenSCAD build are built, not installed: the snapshot carries them.
    assert "deerflow_extension_cad_design/static/dist/index.mjs" in snapshot
    assert "deerflow_extension_cad_design/static/dist/chunks/scad-worker.mjs" in snapshot
    # The relative imports of cad-preview's viewer modules resolve inside the snapshot tree.
    assert (SNAPSHOT.parent / "deerflow-extension-cad-preview" / "ui" / "mesh.js").is_file()


def test_the_backend_installs_it_from_the_snapshot_on_every_host():
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    entries = [Requirement(entry) for entry in project["dependency-groups"]["extensions"]]
    (design,) = [entry for entry in entries if entry.name == "deerflow-extension-cad-design"]

    # Pure Python plus a prebuilt browser bundle: no platform has a reason to skip it.
    assert design.marker is None
    assert "extensions" in project["tool"]["uv"]["default-groups"]
    assert project["tool"]["uv"]["sources"]["deerflow-extension-cad-design"] == {"path": "extensions/sources/deerflow-extension-cad-design"}
    _validate_locked_local_sources(BACKEND / "uv.lock", BACKEND)


def test_a_pull_that_changes_only_the_bundle_rebuilds_the_installed_copy():
    project = tomllib.loads((SNAPSHOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["tool"]["uv"]["cache-keys"] == [{"file": "pyproject.toml"}, {"file": "deerflow_extension_cad_design/**/*"}]


def test_the_shipped_record_loads_with_its_page_tool_middleware_and_route(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    (record,) = [entry for entry in _shipped_example()["plugins"] if entry["name"] == "cad-design"]
    assert record == RECORD

    loaded, diagnostics = load_extensions([ExtensionSpec(**record)])

    assert not diagnostics, diagnostics
    ((_, contribution),) = loaded.plugins
    assert (contribution.namespace, contribution.enabled) == ("cad-design", True)
    assert contribution.frontend.module == "cad-design"
    assert [tool.name for tool in contribution.tools] == ["scad_draft"]
    assert plugin_tool_name("cad-design", "scad_draft").startswith("ext_cad_design_")
    assert {"list_designs", "prompt", "finalize"} <= {action.name for action in contribution.backend}
    # The middleware keeps scad_draft out of every model call that is not a design run.
    assert len(loaded.middleware_contributors) == 1
    ((_, router),) = loaded.routers
    assert [route.path for route in router.routes] == ["/api/extensions/cad-design/designs/{design_id}/files/{name}"]
    # The design store is created on first use, not at startup.
    assert not (tmp_path / "cad-design").exists()


def test_delegated_subagents_get_the_filter_that_removes_scad_draft(tmp_path, monkeypatch):
    """The host binds plugin tools into subagents too, so the subagent stack must carry the filter."""
    from langchain.agents.middleware.types import ModelRequest
    from langchain_core.messages import AIMessage, HumanMessage

    from deerflow.agents.lead_agent.agent import build_middlewares
    from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.extensions.isolation import IsolatedMiddleware

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    loaded, diagnostics = load_extensions([ExtensionSpec(**RECORD)])
    assert not diagnostics, diagnostics
    app_config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))

    def names(stack):
        return {type(m.inner if isinstance(m, IsolatedMiddleware) else m).__name__ for m in stack}

    subagent = build_subagent_runtime_middlewares(app_config=app_config, model_name="gpt-4o", extensions=loaded)
    assert "NoDrafting" in names(subagent)
    lead = names(build_middlewares(config={"configurable": {}}, model_name="gpt-4o", app_config=app_config, extensions=loaded))
    assert "DesignMode" in lead and "NoDrafting" not in lead

    # What the wrapper the host put around it hands on, not what the filter returns.
    (wrapped,) = [m for m in subagent if isinstance(m, IsolatedMiddleware) and type(m.inner).__name__ == "NoDrafting"]
    scad_draft, other = {"name": plugin_tool_name("cad-design", "scad_draft")}, {"name": "bash"}
    request = ModelRequest(model=None, messages=[HumanMessage("hi")], system_message=None, tools=[scad_draft, other], state={}, runtime=None)
    passed = []
    wrapped.wrap_model_call(request, lambda sent: passed.append(sent) or AIMessage("ok"))
    assert passed[0].tools == [other]


def test_the_migration_delivers_the_shipped_record():
    config_upgrade = _config_upgrade()

    assert _shipped_example()["config_version"] >= 78
    assert config_upgrade.MIGRATIONS[78]["plugins_from_example"] == ("cad-design",)


@pytest.fixture
def example(tmp_path):
    path = tmp_path / "config.example.yaml"
    path.write_text(f"config_version: 78\n{BASE}" + yaml.safe_dump({"plugins": [RECORD]}, sort_keys=False), encoding="utf-8")
    return path


def test_an_install_on_the_previous_version_gets_the_record_exactly_once(tmp_path, example):
    config_upgrade = _config_upgrade()
    acme = {"name": "acme", "use": "acme_ext:install"}
    config = tmp_path / "config.yaml"
    config.write_text(f"config_version: 77\n{BASE}" + yaml.safe_dump({"plugins": [acme]}, sort_keys=False), encoding="utf-8")

    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
    upgraded = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert (upgraded["config_version"], upgraded["plugins"]) == (78, [acme, RECORD])

    # The operator removes the record afterwards: the next launch's upgrade must not bring it back.
    removed = f"config_version: 78\n{BASE}" + yaml.safe_dump({"plugins": [acme]}, sort_keys=False)
    config.write_text(removed, encoding="utf-8")
    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0
    assert config.read_text(encoding="utf-8") == removed


def test_a_record_the_operator_already_has_is_left_alone(tmp_path, example):
    config_upgrade = _config_upgrade()
    mine = {"name": "designs", "package": "deerflow_extension_cad_design", "use": "deerflow_extension_cad_design:install", "enabled": False}
    config = tmp_path / "config.yaml"
    config.write_text(f"config_version: 77\n{BASE}" + yaml.safe_dump({"plugins": [mine]}, sort_keys=False), encoding="utf-8")

    assert config_upgrade.upgrade(config, example, REPO_ROOT) == 0

    assert yaml.safe_load(config.read_text(encoding="utf-8"))["plugins"] == [mine]
