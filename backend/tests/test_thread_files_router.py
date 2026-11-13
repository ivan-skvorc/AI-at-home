"""GET /api/threads/{thread_id}/files: the file explorer's directory listing.

The explorer browses a thread's sandbox user-data tree (``/mnt/user-data``)
and opens files through the existing artifacts route, so these tests pin the
listing's wire contract (shape, ordering, caps, hidden transient files) and
the confinement it shares with ``get_artifact``: lexical normalization before
the prefix check, symlink-aware containment in ``user-data``, links reported
rather than followed, and the owner check plus the per-user storage bucket.
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

import app.gateway.routers.thread_files as thread_files_router
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, INTERNAL_SYSTEM_ROLE
from app.gateway.routers.artifacts import _ARTIFACT_EDIT_TEMP_PREFIX
from deerflow.config.paths import Paths, make_safe_user_id
from deerflow.uploads.manager import UPLOAD_STAGING_PREFIX, UPLOAD_STAGING_SUFFIX

THREAD_ID = "thread-1"
USER_ID = "user-1"
URL = f"/api/threads/{THREAD_ID}/files"


@pytest.fixture
def paths(tmp_path, monkeypatch) -> Paths:
    paths = Paths(tmp_path / "home")
    monkeypatch.setattr("app.gateway.path_utils.get_paths", lambda: paths)
    return paths


@pytest.fixture
def user_data(paths) -> Path:
    """The thread's host user-data directory; tests create it as needed."""
    return paths.sandbox_user_data_dir(THREAD_ID, user_id=USER_ID)


def _client_for(user) -> TestClient:
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.include_router(thread_files_router.router)
    return TestClient(app)


@pytest.fixture
def client(paths):
    with _client_for(SimpleNamespace(id=USER_ID, system_role="user")) as client:
        yield client


def _list(client: TestClient, path: str | None = None):
    return client.get(URL, params=None if path is None else {"path": path})


def _names(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [entry["name"] for entry in response.json()["entries"]]


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")


def test_root_lists_the_standard_directories_in_the_frontend_contract_shape(client, user_data):
    for name in ("workspace", "uploads", "outputs"):
        (user_data / name).mkdir(parents=True)

    response = _list(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"path", "exists", "entries", "truncated", "total"}
    assert body["path"] == "/mnt/user-data"
    assert body["exists"] is True
    assert body["truncated"] is False
    assert body["total"] == 3
    assert all(set(entry) == {"name", "path", "kind", "size", "modified_at"} for entry in body["entries"])
    assert [(entry["name"], entry["path"], entry["kind"], entry["size"]) for entry in body["entries"]] == [
        ("outputs", "/mnt/user-data/outputs", "directory", None),
        ("uploads", "/mnt/user-data/uploads", "directory", None),
        ("workspace", "/mnt/user-data/workspace", "directory", None),
    ]
    assert all(entry["modified_at"].endswith("+00:00") for entry in body["entries"])


@pytest.mark.parametrize("requested", [None, "/mnt/user-data", "mnt/user-data", "/mnt/user-data/", "//mnt//user-data/./", "/mnt/user-data/workspace/.."])
def test_every_spelling_of_the_root_lists_the_root(client, user_data, requested):
    (user_data / "workspace").mkdir(parents=True)

    response = _list(client, requested)

    assert _names(response) == ["workspace"]
    assert response.json()["path"] == "/mnt/user-data"


@pytest.mark.parametrize(
    "requested",
    [
        "/mnt/user-data/workspace/src",
        "mnt/user-data/workspace/src",
        "/mnt/user-data/workspace/src/",
        # ``..`` that stays inside user-data is collapsed lexically, so the
        # intermediate directory need not exist.
        "/mnt/user-data/outputs/../workspace/./src",
    ],
)
def test_nested_directory_listing_uses_normalized_virtual_paths(client, user_data, requested):
    src = user_data / "workspace" / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "app.py").write_bytes(b"print('hi')\n")

    response = _list(client, requested)

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "/mnt/user-data/workspace/src"
    assert [(entry["name"], entry["path"], entry["kind"]) for entry in body["entries"]] == [
        ("pkg", "/mnt/user-data/workspace/src/pkg", "directory"),
        ("app.py", "/mnt/user-data/workspace/src/app.py", "file"),
    ]


def test_directories_sort_first_then_case_insensitive_then_exact_name(client, user_data):
    workspace = user_data / "workspace"
    for name in ("beta", "Alpha"):
        (workspace / name).mkdir(parents=True)
    for name in ("b.txt", "A.txt", "c.txt", "readme"):
        (workspace / name).write_text("x", encoding="utf-8")
    # A link to a directory is not followed, so it sorts with the non-directories.
    _symlink_or_skip(workspace / "B-link", workspace / "beta", target_is_directory=True)
    # The exact-name tie-break needs names that differ only by case.
    case_sensitive = not (workspace / "README").exists()
    if case_sensitive:
        (workspace / "README").write_text("x", encoding="utf-8")

    names = _names(_list(client, "/mnt/user-data/workspace"))

    expected = ["Alpha", "beta", "A.txt", "B-link", "b.txt", "c.txt", "README", "readme"]
    assert names == (expected if case_sensitive else [name for name in expected if name != "README"])


def test_reports_regular_file_size_and_utc_modified_time_to_the_second(client, user_data):
    outputs = user_data / "outputs"
    (outputs / "charts").mkdir(parents=True)
    report = outputs / "report.csv"
    report.write_bytes(b"a,b\n1,2\n")
    os.utime(report, ns=(1_700_000_000_750_000_000, 1_700_000_000_750_000_000))
    os.utime(outputs / "charts", (1_600_000_000, 1_600_000_000))

    response = _list(client, "/mnt/user-data/outputs")

    entries = {entry["name"]: entry for entry in response.json()["entries"]}
    assert entries["report.csv"]["kind"] == "file"
    assert entries["report.csv"]["size"] == 8
    assert entries["report.csv"]["modified_at"] == "2023-11-14T22:13:20+00:00"
    assert entries["charts"]["size"] is None
    assert entries["charts"]["modified_at"] == "2020-09-13T12:26:40+00:00"


def test_hides_only_gateway_transient_files(client, user_data):
    uploads = user_data / "uploads"
    outputs = user_data / "outputs"
    uploads.mkdir(parents=True)
    outputs.mkdir(parents=True)
    (uploads / "doc.pdf").write_bytes(b"%PDF")
    (uploads / f"{UPLOAD_STAGING_PREFIX}a1b2c3{UPLOAD_STAGING_SUFFIX}").write_bytes(b"in-flight upload")
    # Near misses of the staging pattern are ordinary files.
    (uploads / f"{UPLOAD_STAGING_PREFIX}notes.txt").write_text("x", encoding="utf-8")
    (uploads / f"notes{UPLOAD_STAGING_SUFFIX}").write_text("x", encoding="utf-8")
    (outputs / "report.md").write_text("# report", encoding="utf-8")
    (outputs / f"{_ARTIFACT_EDIT_TEMP_PREFIX}k3j2h1").write_text("in-flight edit", encoding="utf-8")
    # Ordinary dotfiles are what the model created and stay visible.
    (outputs / ".git").mkdir()
    (outputs / ".env").write_text("x", encoding="utf-8")

    uploads_response = _list(client, "/mnt/user-data/uploads")
    outputs_response = _list(client, "/mnt/user-data/outputs")

    assert _names(uploads_response) == [f"{UPLOAD_STAGING_PREFIX}notes.txt", "doc.pdf", f"notes{UPLOAD_STAGING_SUFFIX}"]
    assert uploads_response.json()["total"] == 3
    assert _names(outputs_response) == [".git", ".env", "report.md"]
    assert outputs_response.json()["total"] == 3


def test_listing_is_cut_at_the_entry_cap_after_sorting(client, user_data, monkeypatch):
    workspace = user_data / "workspace"
    (workspace / "zdir").mkdir(parents=True)
    for name in ("e.txt", "d.txt", "c.txt", "b.txt"):
        (workspace / name).write_text("x", encoding="utf-8")

    monkeypatch.setattr(thread_files_router, "MAX_LISTED_ENTRIES", 3)
    capped = _list(client, "/mnt/user-data/workspace").json()
    monkeypatch.setattr(thread_files_router, "MAX_LISTED_ENTRIES", 5)
    exact = _list(client, "/mnt/user-data/workspace").json()

    assert [entry["name"] for entry in capped["entries"]] == ["zdir", "b.txt", "c.txt"]
    assert capped["truncated"] is True
    assert capped["total"] == 5
    assert len(exact["entries"]) == 5
    assert exact["truncated"] is False
    assert exact["total"] == 5


def test_scan_stops_at_its_bound_and_counts_only_visible_entries(client, user_data, monkeypatch):
    workspace = user_data / "workspace"
    workspace.mkdir(parents=True)
    for index in range(6):
        (workspace / f"f{index}.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(thread_files_router, "MAX_SCANNED_ENTRIES", 4)

    over = _list(client, "/mnt/user-data/workspace").json()

    # ``total`` is the lower bound the bounded scan reached.
    assert over["total"] == 4
    assert over["truncated"] is True
    names = [entry["name"] for entry in over["entries"]]
    assert len(names) == 4
    assert names == sorted(names)

    for index in (4, 5):
        (workspace / f"f{index}.txt").unlink()
    for index in range(3):
        (workspace / f"{UPLOAD_STAGING_PREFIX}{index}{UPLOAD_STAGING_SUFFIX}").write_bytes(b"")

    at_bound = _list(client, "/mnt/user-data/workspace").json()

    assert [entry["name"] for entry in at_bound["entries"]] == ["f0.txt", "f1.txt", "f2.txt", "f3.txt"]
    assert at_bound["total"] == 4
    assert at_bound["truncated"] is False


@pytest.mark.parametrize("requested", [None, "/mnt/user-data", "mnt/user-data/"])
def test_missing_user_data_root_reports_exists_false(client, user_data, requested):
    assert not user_data.exists()

    response = _list(client, requested)

    assert response.status_code == 200
    assert response.json() == {"path": "/mnt/user-data", "exists": False, "entries": [], "truncated": False, "total": 0}


@pytest.mark.parametrize("create_root", [True, False])
@pytest.mark.parametrize("requested", ["/mnt/user-data/workspace/missing", "/mnt/user-data/outputs/report.md/inner"])
def test_missing_directory_below_the_root_is_404(client, user_data, create_root, requested):
    if create_root:
        (user_data / "workspace").mkdir(parents=True)
        (user_data / "outputs").mkdir()
        (user_data / "outputs" / "report.md").write_text("x", encoding="utf-8")

    assert _list(client, requested).status_code == 404


def test_file_path_is_400(client, user_data):
    (user_data / "outputs").mkdir(parents=True)
    (user_data / "outputs" / "report.md").write_text("x", encoding="utf-8")

    response = _list(client, "/mnt/user-data/outputs/report.md")

    assert response.status_code == 400


@pytest.mark.parametrize(
    "requested",
    ["/mnt/other", "/mnt/user-dataX", "mnt/user-dataX/workspace", "/mnt", "/", "", "/etc", "/mnt/user-data/work\x00space"],
)
def test_paths_outside_user_data_or_unusable_are_400(client, user_data, requested):
    (user_data / "workspace").mkdir(parents=True)

    assert _list(client, requested).status_code == 400


@pytest.mark.parametrize(
    "query",
    [
        "path=/mnt/user-data/../../..",
        "path=/mnt/user-data/workspace/../../upload-companions",
        # Percent-encoded dot segments reach the route decoded.
        "path=%2Fmnt%2Fuser-data%2F%2e%2e%2Fupload-companions",
        "path=mnt/user-data/workspace/%2E%2E/%2E%2E/%2E%2E/%2E%2E",
    ],
)
def test_dot_dot_traversal_never_lists_outside_user_data(client, user_data, query):
    (user_data / "workspace").mkdir(parents=True)
    # Server-owned records live beside user-data, outside the sandbox mount.
    sibling = user_data.parent / "upload-companions"
    sibling.mkdir()
    (sibling / "secret-record.json").write_text("{}", encoding="utf-8")

    response = client.get(f"{URL}?{query}")

    assert response.status_code in {400, 403}
    assert "secret-record" not in response.text


def test_symlink_escaping_user_data_is_listed_as_a_link_and_never_entered(client, user_data, tmp_path):
    outside = tmp_path / "outside"
    (outside / "nested").mkdir(parents=True)
    (outside / "secret.txt").write_text("host secret", encoding="utf-8")
    workspace = user_data / "workspace"
    workspace.mkdir(parents=True)
    _symlink_or_skip(workspace / "escape", outside, target_is_directory=True)

    listing = _list(client, "/mnt/user-data/workspace")

    entry = {entry["name"]: entry for entry in listing.json()["entries"]}["escape"]
    assert entry["path"] == "/mnt/user-data/workspace/escape"
    assert entry["kind"] == "symlink"
    assert entry["size"] is None
    for requested in ("/mnt/user-data/workspace/escape", "/mnt/user-data/workspace/escape/", "/mnt/user-data/workspace/escape/nested"):
        through = _list(client, requested)
        assert through.status_code == 403
        assert "entries" not in through.json()
        assert "secret.txt" not in through.text


def test_symlink_that_stays_inside_user_data_can_be_listed_through(client, user_data):
    (user_data / "outputs").mkdir(parents=True)
    (user_data / "outputs" / "chart.png").write_bytes(b"png")
    (user_data / "workspace").mkdir()
    _symlink_or_skip(user_data / "workspace" / "results", Path("..") / "outputs", target_is_directory=True)

    through = _list(client, "/mnt/user-data/workspace/results")

    assert through.status_code == 200
    body = through.json()
    assert body["path"] == "/mnt/user-data/workspace/results"
    assert [(entry["name"], entry["path"]) for entry in body["entries"]] == [("chart.png", "/mnt/user-data/workspace/results/chart.png")]


@pytest.mark.skipif(os.name == "nt", reason="Windows has no descriptor-relative opens and lists by path")
@pytest.mark.parametrize("swapped", ["listed", "ancestor"])
@pytest.mark.parametrize(("moment", "expected_status"), [("after-resolution", 404), ("before-scan", 200)])
def test_a_directory_swapped_for_an_outside_link_after_the_check_is_never_listed(client, user_data, tmp_path, monkeypatch, swapped, moment, expected_status):
    # The sandbox can write below user-data, so it can replace a directory the
    # route has already confined with a link to any host directory.
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "SECRET-TOP.txt").write_text("host", encoding="utf-8")
    (outside / "sub" / "SECRET-SUB.txt").write_text("host", encoding="utf-8")
    workspace = user_data / "workspace"
    (workspace / "x" / "sub").mkdir(parents=True)
    (workspace / "x" / "inside-top.txt").write_text("x", encoding="utf-8")
    (workspace / "x" / "sub" / "inside-sub.txt").write_text("x", encoding="utf-8")
    _symlink_or_skip(workspace / "x-link", outside, target_is_directory=True)
    listed = "/mnt/user-data/workspace/x" if swapped == "listed" else "/mnt/user-data/workspace/x/sub"
    swaps: list[str] = []

    def swap() -> None:
        if not swaps:
            (workspace / "x").rename(workspace / "x-moved")
            (workspace / "x-link").rename(workspace / "x")
            swaps.append(moment)

    if moment == "after-resolution":
        real_resolve = thread_files_router.resolve_thread_virtual_path

        def resolve_then_swap(thread_id, virtual_path, user_id=None):
            resolved = real_resolve(thread_id, virtual_path, user_id=user_id)
            if virtual_path == listed:
                swap()
            return resolved

        monkeypatch.setattr(thread_files_router, "resolve_thread_virtual_path", resolve_then_swap)
    else:
        real_scandir = os.scandir

        def swap_then_scan(target):
            swap()
            return real_scandir(target)

        monkeypatch.setattr(thread_files_router.os, "scandir", swap_then_scan)

    response = _list(client, listed)

    assert swaps == [moment]
    assert "SECRET" not in response.text
    assert response.status_code == expected_status
    if expected_status == 200:
        # The directory that was checked, now beside the link, is what is listed.
        assert _names(response) == (["sub", "inside-top.txt"] if swapped == "listed" else ["inside-sub.txt"])


def test_a_link_that_changes_while_the_path_resolves_is_not_a_server_error(client, user_data, monkeypatch):
    (user_data / "outputs").mkdir(parents=True)
    workspace = user_data / "workspace"
    workspace.mkdir()
    link = workspace / "results"
    _symlink_or_skip(link, Path("..") / "outputs", target_is_directory=True)
    real_readlink = os.readlink
    swaps: list[str] = []

    def readlink_after_swap(path, *args, **kwargs):
        # The link turns into a directory between the resolver's lstat and readlink.
        if os.fspath(path) == os.fspath(link) and not swaps:
            link.unlink()
            link.mkdir()
            swaps.append(os.fspath(path))
        return real_readlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "readlink", readlink_after_swap)

    response = _list(client, "/mnt/user-data/workspace/results")

    assert swaps == [os.fspath(link)]
    # Python 3.12's resolver raises when a link changes under it; 3.13 resolves
    # to the directory now in its place. Neither is a server error.
    if sys.version_info < (3, 13):
        assert response.status_code == 404
    else:
        assert _names(response) == []


def test_hosts_without_descriptor_walks_list_by_path(client, user_data, monkeypatch):
    # Windows has neither dir_fd opens nor descriptor scans, so it keeps the
    # by-path listing; the statuses must match the descriptor walk's.
    monkeypatch.setattr(thread_files_router, "_LISTS_BY_DESCRIPTOR", False)
    (user_data / "workspace" / "src").mkdir(parents=True)
    (user_data / "workspace" / "app.py").write_text("x", encoding="utf-8")

    assert _names(_list(client, "/mnt/user-data/workspace")) == ["src", "app.py"]
    assert _list(client, "/mnt/user-data/workspace/app.py").status_code == 400
    assert _list(client, "/mnt/user-data/workspace/missing").status_code == 404


def test_looping_and_dangling_symlinks_are_listed_but_cannot_be_entered(client, user_data):
    workspace = user_data / "workspace"
    workspace.mkdir(parents=True)
    _symlink_or_skip(workspace / "loop", Path("loop"))
    _symlink_or_skip(workspace / "dangling", Path("missing-target"))

    listing = _list(client, "/mnt/user-data/workspace")

    assert [(entry["name"], entry["kind"], entry["size"]) for entry in listing.json()["entries"]] == [
        ("dangling", "symlink", None),
        ("loop", "symlink", None),
    ]
    assert _list(client, "/mnt/user-data/workspace/loop").status_code == 404
    assert _list(client, "/mnt/user-data/workspace/loop/inner").status_code == 404
    assert _list(client, "/mnt/user-data/workspace/dangling").status_code == 404


@pytest.mark.skipif(os.name == "nt", reason="POSIX filenames can hold bytes that are not UTF-8")
def test_undecodable_filename_is_shown_with_replacement_characters(client, user_data):
    workspace = user_data / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "plain.txt").write_text("x", encoding="utf-8")
    try:
        fd = os.open(os.path.join(os.fsencode(workspace), b"caf\xe9.txt"), os.O_CREAT | os.O_WRONLY, 0o644)
    except OSError:
        pytest.skip("this filesystem rejects names that are not UTF-8")
    os.close(fd)

    response = _list(client, "/mnt/user-data/workspace")

    assert _names(response) == ["caf�.txt", "plain.txt"]


FOREIGN_OWNER = "ou_7d8a.6e6d@example:id"
MISSING_RECORD = object()


@pytest.mark.parametrize(
    ("record_owner", "internal", "owner_header", "expected_status"),
    [
        ("reader", False, None, 200),
        (FOREIGN_OWNER, False, None, 404),
        # The owner header is honored only for trusted internal callers.
        (FOREIGN_OWNER, False, FOREIGN_OWNER, 404),
        # A trusted internal caller lists the owner's bucket, under the
        # make_safe_user_id normalization runs store files with.
        (FOREIGN_OWNER, True, FOREIGN_OWNER, 200),
        (None, False, None, 200),
        # Like get_artifact, a read route keeps untracked legacy threads readable.
        (MISSING_RECORD, False, None, 200),
    ],
    ids=["owned", "foreign", "foreign-with-ignored-header", "internal-for-owner", "shared", "untracked"],
)
def test_thread_access_follows_the_artifact_owner_rules(paths, monkeypatch, record_owner, internal, owner_header, expected_status):
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta import memory as memory_thread_meta
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore

    monkeypatch.setattr(memory_thread_meta, "is_multi_user_mode_enabled", lambda: True)
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    if record_owner is not MISSING_RECORD:
        asyncio.run(thread_store.create(THREAD_ID, user_id=record_owner))
    for owner in ("reader", FOREIGN_OWNER):
        workspace = paths.sandbox_user_data_dir(THREAD_ID, user_id=make_safe_user_id(owner)) / "workspace"
        workspace.mkdir(parents=True)
        (workspace / f"{make_safe_user_id(owner)}.txt").write_text(owner, encoding="utf-8")

    user = SimpleNamespace(id="reader", system_role=INTERNAL_SYSTEM_ROLE if internal else "user")
    app = make_authed_test_app(user_factory=lambda: user, bind_current_user=True)
    app.state.thread_store = thread_store
    app.include_router(thread_files_router.router)
    headers = {INTERNAL_OWNER_USER_ID_HEADER_NAME: owner_header} if owner_header else {}
    with TestClient(app) as client:
        response = client.get(URL, params={"path": "/mnt/user-data/workspace"}, headers=headers)

    assert response.status_code == expected_status
    if expected_status == 200:
        bucket = make_safe_user_id(owner_header) if internal else "reader"
        assert _names(response) == [f"{bucket}.txt"]
    else:
        assert make_safe_user_id(FOREIGN_OWNER) not in response.text
