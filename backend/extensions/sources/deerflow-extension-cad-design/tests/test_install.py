"""Registration through a fake host registry (the asset checks are in test_cad_design_registration.py)."""

import json
from pathlib import Path

import pytest

from deerflow_extension_cad_design import install, resolve_config
from deerflow_extension_cad_design.actions import ACTIONS, HostSandbox

PACKAGE = Path(__file__).resolve().parents[1] / "deerflow_extension_cad_design"


class Registry:
    def __init__(self, accept=True):
        self.accept = accept
        self.plugins = []
        self.contributors = []
        self.services = []
        self.router_sets = []

    def plugin(self, contribution):
        self.plugins.append(contribution)
        return self.accept

    def middlewares(self, contributor):
        self.contributors.append(contributor)

    def service(self, service):
        self.services.append(service)

    def routers(self, routers):
        self.router_sets.append(tuple(routers))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return tmp_path


def test_install_registers_actions_page_middleware_and_the_sandbox_service(home):
    registry = Registry()
    install(registry, {})
    (plugin,) = registry.plugins
    assert plugin.namespace == "cad-design" and plugin.enabled is True
    # No model tool and no route: the model works with the container's bash, the page reads through the host.
    assert plugin.tools == () and registry.router_sets == []
    assert [action.name for action in plugin.backend] == list(ACTIONS)
    assert plugin.frontend.module == "cad-design" and Path(plugin.frontend.root) == PACKAGE
    assert len(registry.contributors) == 1
    (service,) = registry.services
    assert isinstance(service, HostSandbox) and service.container is False
    assert not (home / "cad-design").exists(), "the store is created on first use"


def test_a_disabled_record_still_scopes_the_brief():
    registry = Registry()
    install(registry, {"enabled": False})
    assert registry.plugins[0].enabled is False
    assert registry.contributors, "an administrator can enable it at runtime"


def test_configuration_is_checked(home, monkeypatch):
    assert resolve_config({})["storage_path"] == str(home / "cad-design/designs.sqlite")
    assert resolve_config({"storage_path": "/srv/d.sqlite"})["storage_path"] == "/srv/d.sqlite"
    for bad in ({"enabled": "yes"}, {"storage_path": ""}, {"storage_path": 3}, {"surprise": 1}):
        with pytest.raises(ValueError):
            resolve_config(bad)
    monkeypatch.setenv("DEER_FLOW_HOME", "relative")
    with pytest.raises(ValueError):
        resolve_config({})


def test_a_config_from_the_first_release_still_loads(home):
    """max_source_bytes sized the retired scad_draft tool; migration 79 removes it, and until then it is ignored."""
    resolved = resolve_config({"enabled": True, "storage_path": "cad-design/designs.sqlite", "max_source_bytes": 65536})
    assert resolved == {"enabled": True, "storage_path": str(home / "cad-design/designs.sqlite")}
    registry = Registry()
    install(registry, {"max_source_bytes": "anything"})
    assert registry.plugins[0].enabled is True


def test_an_unsupported_host_fails_clearly():
    with pytest.raises(RuntimeError):
        install(Registry(accept=False), {})


def test_the_api_version_is_stamped():
    assert install.__deerflow_api__ == "0.2.15" and install.__deerflow_name__ == "cad-design"


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
