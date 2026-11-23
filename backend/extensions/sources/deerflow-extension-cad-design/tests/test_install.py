"""Registration through a fake host registry (the asset checks are in test_cad_design_registration.py)."""

import json
from pathlib import Path

import pytest

from deerflow_extension_cad_design import install, resolve_config
from deerflow_extension_cad_design.actions import ACTIONS

PACKAGE = Path(__file__).resolve().parents[1] / "deerflow_extension_cad_design"


class Registry:
    def __init__(self, accept=True):
        self.accept = accept
        self.plugins = []
        self.contributors = []
        self.router_sets = []

    def plugin(self, contribution):
        self.plugins.append(contribution)
        return self.accept

    def middlewares(self, contributor):
        self.contributors.append(contributor)

    def routers(self, routers):
        self.router_sets.append(tuple(routers))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return tmp_path


def test_install_registers_tool_actions_page_middleware_and_route(home):
    registry = Registry()
    install(registry, {})
    (plugin,) = registry.plugins
    assert plugin.namespace == "cad-design" and plugin.enabled is True
    assert [tool.name for tool in plugin.tools] == ["scad_draft"] and plugin.tools[0].group == "local_extensions"
    assert [action.name for action in plugin.backend] == list(ACTIONS)
    assert plugin.frontend.module == "cad-design" and Path(plugin.frontend.root) == PACKAGE
    assert len(registry.contributors) == 1 and len(registry.router_sets) == 1
    paths = [route.path for route in registry.router_sets[0][0].routes]
    assert paths == ["/api/extensions/cad-design/designs/{design_id}/files/{name}"]
    assert not (home / "cad-design").exists(), "the store is created on first use"


def test_a_disabled_record_still_filters_the_tool():
    registry = Registry()
    install(registry, {"enabled": False})
    assert registry.plugins[0].enabled is False
    assert registry.contributors, "an administrator can enable it at runtime"


def test_configuration_is_checked(home, monkeypatch):
    assert resolve_config({})["storage_path"] == str(home / "cad-design/designs.sqlite")
    assert resolve_config({"storage_path": "/srv/d.sqlite"})["storage_path"] == "/srv/d.sqlite"
    for bad in ({"enabled": "yes"}, {"max_source_bytes": 10}, {"max_source_bytes": True}, {"storage_path": ""}, {"surprise": 1}):
        with pytest.raises(ValueError):
            resolve_config(bad)
    monkeypatch.setenv("DEER_FLOW_HOME", "relative")
    with pytest.raises(ValueError):
        resolve_config({})


def test_an_unsupported_host_fails_clearly():
    with pytest.raises(RuntimeError):
        install(Registry(accept=False), {})


def test_the_api_version_is_stamped():
    assert install.__deerflow_api__ == "0.2.14" and install.__deerflow_name__ == "cad-design"


def test_documentation_has_both_locales():
    docs = json.loads((PACKAGE / "deerflow-extension.json").read_text(encoding="utf-8"))
    assert docs["id"] == "cad-design" and set(docs["locales"]) == {"en-US", "zh-CN"}
    for locale in docs["locales"].values():
        assert locale["title"] and locale["description"] and locale["usage"] and locale["requirements"]


def test_documentation_passes_the_host_validator():
    documentation = pytest.importorskip("deerflow.extensions.documentation")
    raw = (PACKAGE / "deerflow-extension.json").read_bytes()
    assert len(raw) <= documentation.MAX_BYTES
    documentation.validate_documentation(json.loads(raw))
