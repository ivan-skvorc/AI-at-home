import pytest
from conftest import FakeRuns
from deerflow_extension_api import AGENT_RUNS_RESOLVER_KEY, ExtensionPrincipal
from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY
from deerflow_extension_cad_design.router import build_router, valid_name
from deerflow_extension_cad_design.store import Store
from fastapi import FastAPI
from fastapi.testclient import TestClient

DESIGN = "a" * 32


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "d.sqlite")
    store.create_design("alice", DESIGN, "One", "thread-1")
    version = store.add_version("alice", DESIGN, parent_id=None, source="model", scad="cube(1);", params={})
    store.set_final("alice", DESIGN, version["id"], {"status": "built", "files": ["part.glb"]})
    runs = FakeRuns()
    runs.files[("thread-1", "/mnt/user-data/outputs/part.glb")] = b"glTF"
    runs.files[("thread-1", "/mnt/user-data/outputs/other.glb")] = b"glTF"
    app = FastAPI()
    app.include_router(build_router(store))
    user = {"id": "alice"}
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: ExtensionPrincipal(user["id"]))
    setattr(app.state, AGENT_RUNS_RESOLVER_KEY, lambda request: runs)
    return TestClient(app), user, runs


def test_a_listed_file_is_served(setup):
    client, _, runs = setup
    response = client.get(f"/api/extensions/cad-design/designs/{DESIGN}/files/part.glb")
    assert response.status_code == 200 and response.content == b"glTF"
    assert response.headers["content-type"] == "model/gltf-binary"
    assert response.headers["cache-control"] == "private, no-store"
    assert runs.namespace == "cad-design"


@pytest.mark.parametrize("path", [f"{DESIGN}/files/other.glb", f"{DESIGN}/files/..glb", f"{'b' * 32}/files/part.glb", "nope/files/part.glb", f"{DESIGN}/files/%2e%2e%2fpart.glb"])
def test_anything_else_is_404(setup, path):
    client, _, _ = setup
    assert client.get(f"/api/extensions/cad-design/designs/{path}").status_code == 404


def test_another_user_gets_404(setup):
    client, user, _ = setup
    user["id"] = "bob"
    assert client.get(f"/api/extensions/cad-design/designs/{DESIGN}/files/part.glb").status_code == 404


def test_names():
    assert valid_name("part-1.glb") and valid_name("plate.report.json")
    for name in ("", ".hidden", "../x", "a/b", "a..b", "x" * 300, "a b"):
        assert not valid_name(name), name
