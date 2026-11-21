"""Offline tests for the git-pr-workflow skill.

The CLI is skills/public/git-pr-workflow/scripts/gitflow.sh, run with bash in
throwaway repositories that use a local bare repository as origin. PATH holds
every tool of the host except gh, so a test decides whether gh exists by
placing a fake one. Pull-request commands talk to an in-process fake of the
GitHub REST API on the loopback interface (GITFLOW_API_URL), and the Python
helpers are also imported directly with urllib mocked. Fake secrets are
assembled at runtime so this file never contains a token-shaped string.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "public" / "git-pr-workflow"
SCRIPTS_DIR = SKILL_DIR / "scripts"
GITFLOW = SCRIPTS_DIR / "gitflow.sh"
GIT = shutil.which("git")
BASH = shutil.which("bash")
GITHUB_URL = "https://github.com/acme/widgets.git"
FAKE_TOKEN = "fake-" + "token-" + "0123456789abcdef"


def _bash_is_recent() -> bool:
    if BASH is None:
        return False
    probe = subprocess.run([BASH, "-c", "echo ${BASH_VERSINFO[0]} ${BASH_VERSINFO[1]}"], capture_output=True, text=True, check=False)
    major, minor = (int(part) for part in probe.stdout.split())
    return (major, minor) >= (4, 4)


pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="gitflow.sh targets POSIX systems"),
    pytest.mark.skipif(GIT is None, reason="git is not installed"),
    pytest.mark.skipif(not _bash_is_recent(), reason="gitflow.sh needs bash 4.4 or newer"),
]


# ------------------------------------------------------------- environment


@pytest.fixture(scope="session")
def host_tools(tmp_path_factory) -> str:
    """A PATH with every host executable except gh; python3 is this interpreter.

    The first directory holds links to the first match of every name on the host
    PATH. The host directories that do not contain gh follow it, so a wrapper that
    delegates to "the next one on PATH" (an rm guard, for example) still works.
    """
    tools = tmp_path_factory.mktemp("host-tools")
    host_dirs = [directory for directory in os.environ.get("PATH", "").split(os.pathsep) if directory and os.path.isdir(directory)]
    for directory in host_dirs:
        for entry in os.scandir(directory):
            if entry.name == "gh" or (tools / entry.name).exists() or (tools / entry.name).is_symlink():
                continue
            if entry.is_file() and os.access(entry.path, os.X_OK):
                (tools / entry.name).symlink_to(entry.path)
    for name in ("python3", "python"):
        link = tools / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(sys.executable)
    without_gh = [directory for directory in host_dirs if not os.path.exists(os.path.join(directory, "gh"))]
    return os.pathsep.join([str(tools), *without_gh])


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch, host_tools):
    """Hermetic git config, no gh unless a test adds one, no proxies, no tokens."""
    home = tmp_path / "home"
    home.mkdir()
    fakes = tmp_path / "bin"
    fakes.mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = Test Agent\n\temail = agent@example.com\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    for name in list(os.environ):
        if name.startswith(("GIT_", "GITFLOW_", "GH_")) or name in ("GITHUB_TOKEN", "GITHUB_ENTERPRISE_TOKEN") or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("PATH", f"{fakes}{os.pathsep}{host_tools}")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return fakes


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def run_cli(*args: str, cwd: Path, stdin: str | None = None, env: dict | None = None) -> tuple[int, dict | None, str, str]:
    proc = subprocess.run([BASH, str(GITFLOW), *args], cwd=cwd, input=stdin, capture_output=True, text=True, timeout=120, check=False, env=env)
    payload = json.loads(proc.stdout) if proc.stdout.startswith("{") else None
    return proc.returncode, payload, proc.stdout, proc.stderr


def ok(*args: str, cwd: Path, stdin: str | None = None) -> dict:
    code, payload, stdout, stderr = run_cli(*args, cwd=cwd, stdin=stdin)
    assert code == 0, f"gitflow {' '.join(args)} exited {code}: {stdout} {stderr}"
    assert payload["ok"] is True and stderr == ""
    return payload


def refused(*args: str, cwd: Path, stdin: str | None = None) -> dict:
    code, payload, stdout, stderr = run_cli(*args, cwd=cwd, stdin=stdin)
    assert code == 1, f"expected a refusal from gitflow {' '.join(args)}: {stdout} {stderr}"
    assert payload["ok"] is False and payload["error"]
    assert f"error: {payload['error']}" in stderr
    return payload


def fake_tool(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(f"#!{BASH}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def repos(tmp_path):
    """origin.git (bare, default branch main), seed (pushes to it) and work (a clone)."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    (seed / "README.md").write_text("hello\n", encoding="utf-8")
    (seed / ".gitignore").write_text("*.log\n", encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "initial")
    git(seed, "remote", "add", "origin", str(origin))
    git(seed, "push", "-q", "origin", "main")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(origin), str(work))
    return SimpleNamespace(origin=origin, seed=seed, work=work, tmp=tmp_path, bin=tmp_path / "bin")


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def helpers(monkeypatch):
    """The Python helpers imported in-process (they start no processes)."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "path", [str(SCRIPTS_DIR), *sys.path])
    names = ("gitflow_json", "gitflow_scan", "gitflow_github")
    for name in names:
        sys.modules.pop(name, None)
    modules = {}
    for name in names:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules[name.removeprefix("gitflow_")] = module
    yield SimpleNamespace(**modules)
    for name in names:
        sys.modules.pop(name, None)


# ----------------------------------------------------------- package rules

SPAWNING_MODULES = {"subprocess", "pty", "multiprocessing", "pexpect", "asyncio.subprocess"}
SPAWNING_OS_CALLS = {"system", "popen", "fork", "forkpty", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp"}


def test_python_helpers_never_start_processes():
    """gitflow.sh is the reviewed place where processes start; the helpers only compute."""
    scripts = sorted(SCRIPTS_DIR.glob("*.py"))
    assert {path.name for path in scripts} == {"gitflow_github.py", "gitflow_json.py", "gitflow_scan.py"}
    for path in scripts:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name for alias in node.names} & SPAWNING_MODULES, path.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in SPAWNING_MODULES, path.name
                if node.module == "os":
                    assert not {alias.name for alias in node.names} & SPAWNING_OS_CALLS, path.name
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
                assert node.attr not in SPAWNING_OS_CALLS and not node.attr.startswith("exec"), f"{path.name}: os.{node.attr}"
                assert node.attr != "environ", f"{path.name} reads the environment in bulk"


def test_usage_errors_exit_2_without_json(repos):
    for args in (["frobnicate"], ["commit"], ["pr", "merge"], ["branch"]):
        code, payload, stdout, stderr = run_cli(*args, cwd=repos.work)
        assert code == 2 and payload is None and "usage error" in stderr, (args, code, stdout, stderr)
    code, _, stdout, _ = run_cli("--help", cwd=repos.work)
    assert code == 0 and "worktree add NAME" in stdout


# --------------------------------------------------------------- preflight


def test_preflight_reports_branch_default_and_dirty_state(repos):
    work = repos.work
    (work / "README.md").write_text("changed\n", encoding="utf-8")
    (work / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(work, "add", "staged.txt")
    (work / "new.txt").write_text("new\n", encoding="utf-8")
    (work / "debug.log").write_text("ignored\n", encoding="utf-8")

    facts = ok("preflight", cwd=work)

    assert facts["repo_root"] == str(work.resolve())
    assert facts["branch"] == "main" and facts["detached"] is False
    assert facts["default_branch"] == "main" and facts["default_branch_source"] == "origin/HEAD"
    assert facts["on_default_branch"] is True
    assert facts["upstream"] == "origin/main" and facts["ahead"] == 0 and facts["behind"] == 0
    assert facts["dirty"] is True
    assert facts["staged"] == ["staged.txt"] and facts["unstaged"] == ["README.md"] and facts["untracked"] == ["new.txt"]
    assert facts["counts"] == {"staged": 1, "unstaged": 1, "untracked": 1, "conflicted": 0}
    assert facts["gh"] == {"installed": False, "authenticated": False}
    assert facts["token_present"] is False and facts["token_env"] == []
    assert facts["github_repo"] is None and facts["checkpoints"] == 0 and facts["linked_worktree"] is False
    assert any("protected branch 'main'" in warning for warning in facts["warnings"])


def test_preflight_redacts_credentials_and_never_prints_token_values(repos, monkeypatch):
    work = repos.work
    password = "pw-" + "never-print-me-42"
    git(work, "remote", "set-url", "origin", f"https://agent:{password}@github.com/acme/widgets.git")
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)

    code, facts, stdout, stderr = run_cli("preflight", "--repo", str(work), cwd=repos.tmp)

    assert code == 0
    assert facts["remote_url"] == "https://***@github.com/acme/widgets.git"
    assert facts["remote_url_has_credentials"] is True
    assert facts["github_repo"] == "acme/widgets" and facts["github_host"] == "github.com"
    assert facts["token_env"] == ["GH_TOKEN"] and facts["token_present"] is True
    assert any("embeds credentials" in warning for warning in facts["warnings"])
    assert password not in stdout + stderr and FAKE_TOKEN not in stdout + stderr


def test_preflight_outside_a_repository_fails_with_a_hint(tmp_path):
    payload = refused("preflight", cwd=tmp_path)
    assert "not inside a git work tree" in payload["error"]
    assert "--repo" in payload["hint"]


# ------------------------------------------------------------------ branch


def test_branch_starts_from_the_freshly_fetched_default_branch(repos):
    fresh = commit_file(repos.seed, "later.txt", "later\n", "later on main")
    git(repos.seed, "push", "-q", "origin", "main")

    created = ok("branch", "feat/fresh", cwd=repos.work)

    assert created["created"] is True and created["fetched"] is True
    assert created["base"] == "origin/main" and created["base_sha"] == fresh
    assert created["head"] == fresh and created["branch"] == "feat/fresh"
    assert created["upstream"] is None
    assert git(repos.work, "branch", "--show-current") == "feat/fresh"

    git(repos.work, "switch", "-q", "main")
    again = ok("branch", "feat/fresh", cwd=repos.work)
    assert again["created"] is False and again["source"] == "existing local branch"
    assert git(repos.work, "branch", "--show-current") == "feat/fresh"


def test_branch_tracks_a_branch_that_exists_only_on_the_remote(repos):
    git(repos.seed, "switch", "-q", "-c", "feat/shared")
    tip = commit_file(repos.seed, "shared.txt", "shared\n", "shared work")
    git(repos.seed, "push", "-q", "origin", "feat/shared")

    result = ok("branch", "feat/shared", cwd=repos.work)

    assert result["source"] == "origin/feat/shared" and result["head"] == tip
    assert result["upstream"] == "origin/feat/shared"


@pytest.mark.parametrize("name", ["bad..name", "has space", "main"])
def test_branch_rejects_invalid_and_protected_names(repos, name):
    refused("branch", name, cwd=repos.work)
    assert git(repos.work, "branch", "--show-current") == "main"


# ------------------------------------------------------------- checkpoints


def test_checkpoint_snapshots_untracked_files_and_restore_brings_them_back(repos):
    work = repos.work
    ok("branch", "feat/ck", cwd=work)
    (work / "README.md").write_text("edited\n", encoding="utf-8")
    (work / "notes.txt").write_text("untracked notes\n", encoding="utf-8")
    (work / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(work, "add", "staged.txt")
    (work / "debug.log").write_text("ignored\n", encoding="utf-8")
    status_before = git(work, "status", "--porcelain")
    head_before = git(work, "rev-parse", "HEAD")

    checkpoint = ok("checkpoint", "-m", "before experiment", cwd=work)

    assert checkpoint["ref"] == "refs/deerflow-checkpoints/" + checkpoint["id"]
    assert checkpoint["head"] == head_before and checkpoint["branch"] == "feat/ck" and checkpoint["same_as_head"] is False
    assert git(work, "status", "--porcelain") == status_before, "checkpoint must not touch the index or work tree"
    assert git(work, "rev-parse", "HEAD") == head_before
    snapshot = git(work, "ls-tree", "-r", "--name-only", checkpoint["commit"]).splitlines()
    assert {"README.md", "notes.txt", "staged.txt", ".gitignore"} <= set(snapshot) and "debug.log" not in snapshot
    assert checkpoint["files"] == len(snapshot)
    assert git(work, "show", f"{checkpoint['commit']}:README.md") == "edited"

    (work / "README.md").write_text("broken\n", encoding="utf-8")
    (work / "notes.txt").unlink()
    (work / "later.txt").write_text("created after\n", encoding="utf-8")
    (work / "sub" / "dir").mkdir(parents=True)
    (work / "sub" / "dir" / "deep.txt").write_text("deep\n", encoding="utf-8")
    (work / "after.log").write_text("ignored, created after\n", encoding="utf-8")

    restored = ok("restore", checkpoint["id"], cwd=work)
    assert (work / "README.md").read_text(encoding="utf-8") == "edited\n"
    assert (work / "notes.txt").read_text(encoding="utf-8") == "untracked notes\n"
    assert (work / "later.txt").exists(), "without --clean newer files stay"
    assert restored["deleted"] == [] and restored["safety_checkpoint"]

    assert "matches 2 checkpoints" in refused("restore", "2", cwd=work)["error"], "an ambiguous prefix is refused"
    cleaned = ok("restore", checkpoint["commit"][:10], "--clean", cwd=work)
    assert sorted(cleaned["deleted"]) == ["later.txt", "sub/dir/deep.txt"]
    assert not (work / "later.txt").exists() and not (work / "sub").exists()
    assert (work / "after.log").exists() and (work / "debug.log").exists(), "ignored files are never deleted"
    assert git(work, "rev-parse", "HEAD") == head_before
    assert git(work, "diff", "--cached", "--name-only") == "staged.txt", "restore leaves the index alone"

    undo = ok("restore", cleaned["safety_checkpoint"], "--clean", cwd=work)
    assert (work / "later.txt").read_text(encoding="utf-8") == "created after\n"
    assert undo["deleted"] == []

    listing = ok("checkpoints", cwd=work)
    assert listing["count"] == 4
    ids = [item["id"] for item in listing["checkpoints"]]
    assert ids == sorted(ids, reverse=True) and checkpoint["id"] in ids
    assert listing["checkpoints"][-1]["message"] == "deerflow checkpoint: before experiment"
    assert listing["checkpoints"][-1]["branch"] == "feat/ck" and listing["checkpoints"][-1]["worktree"] == str(work.resolve())
    assert ok("checkpoints", "--limit", "1", cwd=work)["checkpoints"][0]["id"] == ids[0]


def test_restore_with_paths_only_touches_those_paths(repos):
    work = repos.work
    ok("branch", "feat/paths", cwd=work)
    (work / "a.txt").write_text("a1\n", encoding="utf-8")
    (work / "b.txt").write_text("b1\n", encoding="utf-8")
    checkpoint = ok("checkpoint", cwd=work)
    (work / "a.txt").write_text("a2\n", encoding="utf-8")
    (work / "b.txt").write_text("b2\n", encoding="utf-8")

    result = ok("restore", "latest", "--paths", "a.txt", cwd=work)

    assert result["id"] == checkpoint["id"] and result["restored"] == ["a.txt"] and result["paths"] == ["a.txt"]
    assert (work / "a.txt").read_text(encoding="utf-8") == "a1\n"
    assert (work / "b.txt").read_text(encoding="utf-8") == "b2\n"
    refused("restore", "no-such-checkpoint", cwd=work)
    refused("restore", "latest", "--paths", "../outside.txt", cwd=work)


# ------------------------------------------------------------------ commit

GH_SECRET = "ghp_" + "Ab3dE" * 8
PAT_SECRET = "github_pat_" + "11AbCdEfGh" * 4
AWS_SECRET = "AKIA" + "QWERTYUIOPASDFGH"
SLACK_SECRET = "xoxb-" + "1234567890-abcdefghij"
LITERAL_SECRET = "q8Zr2Lk9" + "Wm4Tn7Vb"
SECRET_CASES = [
    ("config.py", f'GITHUB = "{GH_SECRET}"\n', "github-token", GH_SECRET),
    ("config.py", f'PAT = "{PAT_SECRET}"\n', "github-token", PAT_SECRET),
    ("deploy.sh", f"export KEY_ID={AWS_SECRET}\n", "aws-access-key", AWS_SECRET),
    ("deploy_key", "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc\n", "private-key", "OPENSSH PRIVATE"),
    ("notify.js", f'const hook = "{SLACK_SECRET}";\n', "slack-token", SLACK_SECRET),
    ("settings.py", f'DB_PASSWORD = "{LITERAL_SECRET}"\n', "hardcoded-credential", LITERAL_SECRET),
    ("settings.json", f'{{"api_key": "{LITERAL_SECRET}"}}\n', "hardcoded-credential", LITERAL_SECRET),
    # (12) a type annotation between the name and the value
    ("typed.py", f'    api_key: str = "{LITERAL_SECRET}"\n', "hardcoded-credential", LITERAL_SECRET),
    ("client.ts", f'const apiKey: string = "{LITERAL_SECRET}";\n', "hardcoded-credential", LITERAL_SECRET),
    # (13) a credential after the first 4000 characters of a minified line
    ("bundle.min.js", '{"padding": "' + "a" * 4100 + f'", "client_secret": "{LITERAL_SECRET}"}}\n', "hardcoded-credential", LITERAL_SECRET),
]


@pytest.mark.parametrize(("filename", "secret_line", "rule", "secret_value"), SECRET_CASES)
def test_commit_refuses_secrets_in_the_staged_diff(repos, filename, secret_line, rule, secret_value):
    work = repos.work
    ok("branch", "feat/secret", cwd=work)
    head = git(work, "rev-parse", "HEAD")
    (work / filename).write_text("# settings\n" + secret_line, encoding="utf-8")

    code, payload, stdout, stderr = run_cli("commit", "-m", "add settings", "--paths", filename, cwd=work)

    assert code == 1 and payload["ok"] is False
    assert payload["findings"][0] == {"file": filename, "line": 2, "rule": rule}
    assert f"{filename}:2" in payload["error"]
    assert payload["index_restored"] is True
    assert git(work, "diff", "--cached", "--name-only") == "", "the refused paths are unstaged again"
    assert git(work, "rev-parse", "HEAD") == head
    assert secret_value not in stdout + stderr, "the secret itself is never printed"


@pytest.mark.parametrize("filename", [".env", ".env.production", "certs/server.pem", "id_rsa", "deploy/id_ed25519"])
def test_commit_refuses_sensitive_files(repos, filename):
    work = repos.work
    ok("branch", "feat/files", cwd=work)
    (work / filename).parent.mkdir(parents=True, exist_ok=True)
    (work / filename).write_text("harmless\n", encoding="utf-8")

    payload = refused("commit", "-m", "add file", "--all", cwd=work)

    assert {"file": filename, "line": None, "rule": "sensitive-file"} in payload["findings"]
    assert git(work, "diff", "--cached", "--name-only") == ""


def test_commit_accepts_placeholders_examples_and_marked_fixtures(repos):
    work = repos.work
    ok("branch", "feat/placeholders", cwd=work)
    (work / ".env.example").write_text("API_KEY=\nGITHUB_TOKEN=\n", encoding="utf-8")
    (work / "app.py").write_text(
        'import os\napi_key = os.environ["API_KEY"]\npassword = "<your-password-here>"\ntoken = "${DEPLOY_TOKEN_VALUE}"\nenv_name = "GITHUB_TOKEN_NAME_HERE"\n',
        encoding="utf-8",
    )
    (work / "test_fixture.py").write_text('FAKE = "' + "ghp_" + "Zz9yX" * 8 + '"  # pragma: allowlist secret\n', encoding="utf-8")

    result = ok("commit", "-m", "chore: add examples", "--paths", ".env.example", "app.py", "test_fixture.py", cwd=work)

    assert sorted(result["files"]) == [".env.example", "app.py", "test_fixture.py"]
    assert result["files_changed"] == 3 and result["insertions"] == 8 and result["deletions"] == 0


def test_commit_refuses_the_default_branch_unless_allowed(repos):
    work = repos.work
    (work / "README.md").write_text("changed on main\n", encoding="utf-8")
    payload = refused("commit", "-m", "docs: tweak", "--all", cwd=work)
    assert "protected branch 'main'" in payload["error"] and "branch" in payload["hint"]
    assert git(work, "diff", "--cached", "--name-only") == ""

    allowed = ok("commit", "-m", "docs: tweak", "--all", "--allow-default-branch", cwd=work)
    assert allowed["branch"] == "main" and allowed["sha"] == git(work, "rev-parse", "HEAD")


def test_commit_refuses_an_empty_commit_and_detached_head(repos):
    work = repos.work
    ok("branch", "feat/empty", cwd=work)
    assert "nothing to commit" in refused("commit", "-m", "nothing", "--all", cwd=work)["error"]
    git(work, "switch", "-q", "--detach", "HEAD")
    (work / "x.txt").write_text("x\n", encoding="utf-8")
    assert "detached" in refused("commit", "-m", "x", "--all", cwd=work)["error"]


def test_commit_takes_the_message_verbatim_from_stdin_and_only_named_paths(repos):
    work = repos.work
    ok("branch", "feat/message", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    (work / "README.md").write_text("not part of this commit\n", encoding="utf-8")
    message = "fix: handle \"quotes\", `backticks` and $(dollar) signs\n\nBody with $HOME, a # heading, 'single' quotes and \\n literally.\n"

    result = ok("commit", "--paths", "a.txt", "--message-file", "-", cwd=work, stdin=message)

    assert git(work, "log", "-1", "--format=%B") == message.strip()
    assert result["files"] == ["a.txt"] and result["subject"] == message.splitlines()[0]
    assert result["shortstat"] == "1 file changed, 1 insertion(+)"
    assert git(work, "status", "--porcelain") == "M README.md"

    paragraphs = ok("commit", "--repo", str(work), "-m", "docs: readme", "-m", "Second paragraph.", "--paths", str(work / "README.md"), cwd=repos.tmp / "home")
    assert paragraphs["files"] == ["README.md"]
    assert git(work, "log", "-1", "--format=%B") == "docs: readme\n\nSecond paragraph."


def test_commit_refuses_when_other_changes_are_already_staged(repos):
    work = repos.work
    ok("branch", "feat/staged", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    (work / "b.txt").write_text("b\n", encoding="utf-8")
    git(work, "add", "b.txt")

    payload = refused("commit", "-m", "add a", "--paths", "a.txt", cwd=work)

    assert payload["staged_outside_paths"] == ["b.txt"]
    assert git(work, "diff", "--cached", "--name-only") == "b.txt"


def test_commit_restores_the_index_when_staging_fails_halfway(repos):
    work = repos.work
    ok("branch", "feat/ignored", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    (work / "debug.log").write_text("ignored by .gitignore\n", encoding="utf-8")

    payload = refused("commit", "-m", "add", "--paths", "a.txt", "debug.log", cwd=work)

    assert "ignored" in payload["error"] and payload["index_restored"] is True and ".gitignore" in payload["hint"]
    assert git(work, "diff", "--cached", "--name-only") == ""


# -------------------------------------------------------------------- push


def test_push_to_the_bare_remote_is_verified_and_keeps_checkpoints_local(repos):
    work = repos.work
    ok("branch", "feat/push", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    ok("checkpoint", "-m", "local only", cwd=work)
    sha = ok("commit", "-m", "feat: add a", "--paths", "a.txt", cwd=work)["sha"]

    pushed = ok("push", cwd=work)

    assert pushed["verified"] is True and pushed["result"] == "new branch" and pushed["forced"] is False
    assert pushed["local_sha"] == sha == pushed["remote_sha"]
    assert git(repos.origin, "rev-parse", "refs/heads/feat/push") == sha
    assert pushed["upstream"] == "origin/feat/push" and pushed["attempts"] == 1 and pushed["retry_delays_seconds"] == []
    assert pushed["new_pull_request_url"] is None, "the remote is not a GitHub URL"
    assert "deerflow-checkpoints" not in git(work, "ls-remote", "origin")

    again = ok("push", cwd=work)
    assert again["result"] == "up to date" and again["remote_sha"] == sha


def test_push_refuses_protected_branches(repos):
    assert "protected branch 'main'" in refused("push", cwd=repos.work)["error"]


def test_push_rejects_rewritten_history_without_lease_and_accepts_it_with_lease(repos):
    work = repos.work
    ok("branch", "feat/rewrite", cwd=work)
    commit_file(work, "a.txt", "a\n", "feat: a")
    ok("push", cwd=work)
    git(work, "commit", "-q", "--amend", "-m", "feat: a (reworded)")
    amended = git(work, "rev-parse", "HEAD")

    rejected = refused("push", cwd=work)
    assert "rebase" in rejected["hint"] and rejected["attempts"] == 1
    assert git(repos.origin, "rev-parse", "refs/heads/feat/rewrite") != amended

    forced = ok("push", "--force-with-lease", cwd=work)
    assert forced["forced"] is True and forced["result"] == "forced update" and forced["remote_sha"] == amended


def _flaky_git(bin_dir: Path, counter: Path, failures: int, stderr_line: str) -> None:
    fake_tool(
        bin_dir,
        "git",
        f"""for arg in "$@"; do
  if [ "$arg" = push ]; then
    count=$(cat {counter} 2>/dev/null || echo 0)
    if [ "$count" -lt {failures} ]; then
      echo $((count + 1)) > {counter}
      printf '%s\\n' "{stderr_line}" >&2
      exit 128
    fi
    break
  fi
done
exec {GIT} "$@"
""",
    )


def test_push_retries_transient_failures_with_exponential_backoff(repos, monkeypatch):
    work = repos.work
    ok("branch", "feat/flaky", cwd=work)
    sha = commit_file(work, "a.txt", "a\n", "feat: a")
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    secret_url = "https://x-access-token:" + FAKE_TOKEN + "@github.com/acme/widgets.git/"
    _flaky_git(repos.bin, repos.tmp / "push-count", 2, f"fatal: unable to access '{secret_url}': Could not resolve host: github.com")
    sleeps = repos.tmp / "sleeps"
    fake_tool(repos.bin, "sleep", f'echo "$1" >> {sleeps}\n')

    code, payload, stdout, stderr = run_cli("push", cwd=work)

    assert code == 0, stdout + stderr
    assert payload["verified"] is True and payload["remote_sha"] == sha
    assert payload["attempts"] == 3 and payload["retry_delays_seconds"] == [2, 4]
    assert sleeps.read_text(encoding="utf-8").split() == ["2", "4"]
    assert FAKE_TOKEN not in stdout + stderr


def test_push_does_not_retry_authentication_failures(repos, monkeypatch):
    work = repos.work
    ok("branch", "feat/denied", cwd=work)
    commit_file(work, "a.txt", "a\n", "feat: a")
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)
    secret_url = "https://agent:" + FAKE_TOKEN + "@github.com/acme/widgets.git/"
    _flaky_git(repos.bin, repos.tmp / "push-count", 99, f"fatal: unable to access '{secret_url}': The requested URL returned error: 403")
    sleeps = repos.tmp / "sleeps"
    fake_tool(repos.bin, "sleep", f'echo "$1" >> {sleeps}\n')

    code, payload, stdout, stderr = run_cli("push", cwd=work)

    assert code == 1 and payload["attempts"] == 1 and not sleeps.exists()
    assert "Authentication" in payload["hint"]
    assert FAKE_TOKEN not in stdout + stderr and "https://***@github.com" in stdout


# -------------------------------------------------------------- worktrees


def test_worktrees_isolate_parallel_agents(repos):
    work = repos.work
    first = ok("worktree", "add", "api", cwd=work)
    second = ok("worktree", "add", "docs", cwd=work)

    assert first["created"] is True and first["branch"] == "agent/api" and first["exclude_added"] is True
    assert Path(first["path"]) == work.resolve() / ".worktrees" / "api"
    assert Path(second["path"]) == work.resolve() / ".worktrees" / "docs" and second["exclude_added"] is False
    assert "/.worktrees/" in (work / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert git(work, "status", "--porcelain") == "", "worktrees never show up as untracked"

    api = Path(first["path"])
    (api / "api.txt").write_text("api work\n", encoding="utf-8")
    ok("commit", "-m", "feat: api", "--paths", "api.txt", cwd=api)
    assert not (Path(second["path"]) / "api.txt").exists()
    assert git(work, "branch", "--show-current") == "main"
    assert ok("preflight", cwd=api)["linked_worktree"] is True

    assert ok("worktree", "add", "api", cwd=work)["created"] is False
    listing = ok("worktree", "list", cwd=work)
    agents = {item["name"]: item for item in listing["worktrees"] if item["agent"]}
    assert set(agents) == {"api", "docs"} and agents["api"]["dirty"] is False and agents["api"]["branch"] == "agent/api"

    assert "running in" in refused("worktree", "remove", "api", cwd=api)["error"]
    removed = ok("worktree", "remove", "api", "--delete-branch", cwd=work)
    assert removed["removed"] is True and removed["branch_deleted"] is False, "unmerged work keeps its branch"
    assert git(work, "rev-parse", "--verify", "agent/api")

    docs = Path(second["path"])
    (docs / "draft.md").write_text("unsaved\n", encoding="utf-8")
    assert "uncommitted" in refused("worktree", "remove", "docs", cwd=work)["error"]
    forced = ok("worktree", "remove", "docs", "--force", cwd=work)
    assert forced["removed"] is True and not docs.exists()
    assert git(work, "show", f"refs/deerflow-checkpoints/{forced['checkpoint']}:draft.md") == "unsaved"
    refused("worktree", "add", "../escape", cwd=work)


# --------------------------------------------------------- pull requests


class FakeGitHub:
    """In-memory slice of the GitHub REST API that gitflow_github.py uses."""

    def __init__(self, owner: str = "acme", name: str = "widgets") -> None:
        self.prefix = f"/repos/{owner}/{name}"
        self.owner = owner
        self.pulls: dict[int, dict] = {}
        self.hidden_from_first_list: set[int] = set()
        self.requests: list[dict] = []
        self.check_runs: list[dict] = []
        self.statuses: list[dict] = []
        self.reviews: list[dict] = []
        self.head_sha = ""
        self.truncate_next_post = False

    def add_pull(self, branch: str, sha: str, base: str = "main", title: str = "existing") -> dict:
        number = len(self.pulls) + 1
        self.pulls[number] = {
            "number": number,
            "html_url": f"https://github.com/acme/widgets/pull/{number}",
            "title": title,
            "state": "open",
            "draft": False,
            "merged": False,
            "merged_at": None,
            "mergeable": True,
            "mergeable_state": "clean",
            "head": {"ref": branch, "sha": sha},
            "base": {"ref": base},
        }
        return self.pulls[number]

    def handle(self, method: str, path: str, query: dict, body, headers: dict) -> tuple[int, object]:
        self.requests.append({"method": method, "path": path, "query": query, "body": body, "headers": headers})
        if path == self.prefix + "/pulls" and method == "GET":
            owner, _, branch = query["head"][0].partition(":")
            state = query.get("state", ["open"])[0]
            found = [pull for pull in self.pulls.values() if owner == self.owner and pull["head"]["ref"] == branch and state in ("all", pull["state"])]
            if self.hidden_from_first_list:
                found = [pull for pull in found if pull["number"] not in self.hidden_from_first_list]
                self.hidden_from_first_list.clear()
            return 200, sorted(found, key=lambda pull: -pull["number"])
        if path == self.prefix + "/pulls" and method == "POST":
            if any(pull["head"]["ref"] == body["head"] and pull["state"] == "open" for pull in self.pulls.values()):
                return 422, {"message": "Validation Failed", "errors": [{"message": f"A pull request already exists for acme:{body['head']}."}]}
            pull = self.add_pull(body["head"], self.head_sha, base=body["base"], title=body["title"])
            pull["draft"] = body["draft"]
            pull["mergeable"] = None
            return 201, pull
        if path.startswith(self.prefix + "/pulls/") and path.endswith("/reviews"):
            return 200, self.reviews
        if path.startswith(self.prefix + "/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            return (200, self.pulls[number]) if number in self.pulls else (404, {"message": "Not Found"})
        if path.endswith("/check-runs"):
            return 200, {"total_count": len(self.check_runs), "check_runs": self.check_runs}
        if path.endswith("/status"):
            return 200, {"state": "success", "statuses": self.statuses}
        return 404, {"message": "Not Found"}

    def urlopen(self, request, timeout=None):
        """Stand-in for urllib.request.urlopen when the helper is imported in-process."""
        url = urlsplit(request.full_url)
        assert (url.scheme, url.netloc) == ("https", "api.github.com")
        body = json.loads(request.data) if request.data else None
        status, payload = self.handle(request.get_method(), url.path, parse_qs(url.query), body, dict(request.header_items()))
        data = json.dumps(payload).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(data))
        response = io.BytesIO(data)
        response.status = status
        return response


@pytest.fixture
def github(repos, monkeypatch):
    """work's origin is a GitHub URL that git rewrites to the bare repository; the API is a loopback fake."""
    git(repos.work, "remote", "set-url", "origin", GITHUB_URL)
    git(repos.work, "config", f"url.{repos.origin}.insteadOf", GITHUB_URL)
    fake = FakeGitHub()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, payload = fake.handle(self.command, url.path, parse_qs(url.query), body, dict(self.headers.items()))
            data = json.dumps(payload).encode("utf-8")
            declared = len(data)
            if self.command == "POST" and fake.truncate_next_post:
                # The pull request is created, then the connection drops mid-response.
                fake.truncate_next_post = False
                declared += 500
                self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(declared))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _serve

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GITFLOW_API_URL", f"http://127.0.0.1:{server.server_address[1]}")
    yield SimpleNamespace(fake=fake, **vars(repos))
    server.shutdown()
    server.server_close()


def pushed_branch(work: Path, name: str) -> dict:
    ok("branch", name, cwd=work)
    commit_file(work, "feature.txt", "feature\n", "feat: widget")
    return ok("push", cwd=work)


def test_pr_create_uses_the_token_variable_and_is_idempotent(github, monkeypatch):
    work = github.work
    pushed = pushed_branch(work, "feat/widget")
    assert pushed["new_pull_request_url"] == "https://github.com/acme/widgets/pull/new/feat/widget"
    github.fake.head_sha = pushed["remote_sha"]
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    body_file = github.tmp / "body.md"
    body_file.write_text("## Summary\n\n- Adds the widget with `ticks` and $VARS\n", encoding="utf-8")

    code, created, stdout, stderr = run_cli("pr", "create", "--title", "feat: widget", "--body-file", str(body_file), cwd=work)

    assert code == 0, stdout + stderr
    assert created["created"] is True and created["via"] == "env" and created["repository"] == "acme/widgets"
    assert created["number"] == 1 and created["url"] == "https://github.com/acme/widgets/pull/1"
    assert created["state"] == "open" and created["base"] == "main" and created["head"] == "feat/widget"
    assert created["head_matches_remote"] is True and created["head_matches_local"] is True
    lookup, post, readback = github.fake.requests
    assert lookup["method"] == "GET" and lookup["query"]["head"] == ["acme:feat/widget"] and lookup["query"]["state"] == ["open"]
    assert post["method"] == "POST" and post["body"] == {"title": "feat: widget", "body": body_file.read_text(encoding="utf-8"), "head": "feat/widget", "base": "main", "draft": False}
    assert readback["method"] == "GET" and readback["path"] == "/repos/acme/widgets/pulls/1"
    assert all(request["headers"]["Authorization"] == "Bearer " + FAKE_TOKEN for request in github.fake.requests)
    assert FAKE_TOKEN not in stdout + stderr

    again = ok("pr", "create", "--title", "feat: widget v2", "--body", "other", cwd=work)
    assert again["created"] is False and again["number"] == 1
    assert [request["method"] for request in github.fake.requests].count("POST") == 1
    assert any("already existed" in warning for warning in again["warnings"])


def test_pr_create_uses_the_credentials_of_an_authenticated_gh(github):
    work = github.work
    pushed = pushed_branch(work, "feat/gh")
    github.fake.head_sha = pushed["remote_sha"]
    gh_secret = "gh-" + "stored-" + "credential-0987654321"
    fake_tool(github.bin, "gh", f'case "$1 $2" in\n  "auth status") exit 0 ;;\n  "auth token") printf "%s\\n" "{gh_secret}" ;;\n  *) exit 1 ;;\nesac\n')

    code, created, stdout, stderr = run_cli("pr", "create", "--title", "feat: gh", "--body-file", "-", "--draft", cwd=work, stdin="Body from stdin\n")

    assert code == 0, stdout + stderr
    assert created["via"] == "gh" and created["created"] is True and created["draft"] is True
    assert github.fake.requests[1]["body"]["body"] == "Body from stdin\n"
    assert all(request["headers"]["Authorization"] == "Bearer " + gh_secret for request in github.fake.requests)
    assert gh_secret not in stdout + stderr
    assert ok("preflight", cwd=work)["gh"] == {"installed": True, "authenticated": True}


def test_pr_create_requires_a_pushed_branch_and_credentials(github, monkeypatch):
    work = github.work
    ok("branch", "feat/local-only", cwd=work)
    commit_file(work, "x.txt", "x\n", "feat: x")
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    payload = refused("pr", "create", "--title", "t", "--body", "b", cwd=work)
    assert "not on origin" in payload["error"] and "push" in payload["hint"]

    ok("push", cwd=work)
    monkeypatch.delenv("GH_TOKEN")
    payload = refused("pr", "create", "--title", "t", "--body", "b", cwd=work)
    assert "no GitHub credentials" in payload["error"] and "connect GitHub" in payload["hint"]
    assert github.fake.requests == []


def test_pr_status_summarizes_checks_reviews_and_mergeability(github, monkeypatch):
    work = github.work
    sha = pushed_branch(work, "feat/status")["remote_sha"]
    github.fake.add_pull("feat/status", sha, title="feat: status")
    github.fake.check_runs = [
        {"name": "tests", "status": "completed", "conclusion": "success"},
        {"name": "lint", "status": "completed", "conclusion": "failure", "html_url": "https://github.com/acme/widgets/runs/2"},
        {"name": "e2e", "status": "in_progress", "conclusion": None},
    ]
    github.fake.statuses = [{"context": "legacy/ci", "state": "success", "target_url": None}]
    github.fake.reviews = [
        {"user": {"login": "amy"}, "state": "CHANGES_REQUESTED"},
        {"user": {"login": "amy"}, "state": "APPROVED"},
        {"user": {"login": "bob"}, "state": "COMMENTED"},
    ]
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)

    status = ok("pr", "status", cwd=work)

    assert status["number"] == 1 and status["state"] == "open" and status["merged"] is False and status["mergeable"] is True
    assert status["head_matches_local"] is True
    checks = status["checks"]
    assert checks["sha"] == sha and checks["state"] == "failure"
    assert checks["counts"] == {"total": 4, "success": 2, "failure": 1, "pending": 1, "other": 0}
    assert [item["name"] for item in checks["failing"]] == ["lint"] and checks["pending"] == ["e2e"]
    assert status["reviews"] == {"approved": 1, "changes_requested": 0, "commented": 1}

    github.fake.check_runs = [{"name": "tests", "status": "completed", "conclusion": "success"}]
    assert ok("pr", "status", "--number", "1", cwd=work)["checks"]["state"] == "success"


# ------------------------------------------------------- helper internals


def route_urllib(helpers, monkeypatch, handler) -> None:
    """Send every request the REST helper makes, however it opens URLs, to handler."""
    monkeypatch.setattr(urllib.request, "urlopen", handler)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda self, request, data=None, timeout=None: handler(request, timeout))
    monkeypatch.setattr(helpers.github, "_build_opener", lambda: SimpleNamespace(open=handler), raising=False)


def test_create_pull_returns_the_pull_request_that_won_a_creation_race(helpers, monkeypatch):
    fake = FakeGitHub()
    existing = fake.add_pull("feat/race", "a" * 40, title="opened elsewhere")
    fake.hidden_from_first_list.add(existing["number"])
    route_urllib(helpers, monkeypatch, fake.urlopen)
    transport = helpers.github.RestTransport("github.com", FAKE_TOKEN)
    repo = helpers.github.RemoteRepo("github.com", "acme", "widgets")

    pull, created = helpers.github.create_pull(transport, repo, title="feat: race", body="x", head="feat/race", base="main", draft=True)

    assert created is False and pull["number"] == existing["number"] and pull["title"] == "opened elsewhere"
    assert len(fake.pulls) == 1
    assert [request["method"] for request in fake.requests] == ["GET", "POST", "GET", "GET"]


def test_api_url_override_must_be_https_or_loopback(helpers):
    resolve = helpers.github.resolve_api_base
    assert resolve("github.com", None) == "https://api.github.com"
    assert resolve("git.corp.example", None) == "https://git.corp.example/api/v3"
    assert resolve("github.com", "https://api.ghe.example/") == "https://api.ghe.example"
    assert resolve("github.com", "http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    with pytest.raises(helpers.github.GitHubError):
        resolve("github.com", "http://api.example.com")


def test_parse_remote_url_accepts_https_ssh_and_enterprise_forms(helpers):
    parse = helpers.github.parse_remote_url
    assert parse("https://github.com/acme/widgets.git").slug == "acme/widgets"
    assert parse("https://user:pw@github.com/acme/widgets").slug == "acme/widgets"
    assert parse("git@github.com:acme/widgets.git").slug == "acme/widgets"
    assert parse("ssh://git@ssh.github.com:443/acme/widgets.git").host == "github.com"
    enterprise = parse("https://git.corp.example/team/tool.git")
    assert (enterprise.host, enterprise.owner, enterprise.name) == ("git.corp.example", "team", "tool")
    assert parse("/srv/git/widgets.git") is None and parse("../widgets.git") is None and parse("file:///srv/git/widgets.git") is None


def test_redact_hides_url_credentials_token_shapes_and_live_values(helpers, monkeypatch):
    live = "live-" + "value-" + "9876543210"
    monkeypatch.setenv("GITHUB_TOKEN", live)
    token_shape = "ghp_" + "Ab3dE" * 8
    text = helpers.json.redact(f"fatal: unable to access 'https://x-access-token:{live}@github.com/a/b.git/' https://{token_shape}@github.com/a/b.git {token_shape} {live} ssh://git@github.com/a/b.git git@github.com:a/b.git")
    assert live not in text and token_shape not in text
    assert "https://***@github.com/a/b.git/" in text
    assert "ssh://git@github.com/a/b.git" in text and "git@github.com:a/b.git" in text


def test_record_stream_builds_objects_lists_and_caps_long_lists(helpers):
    records = []
    for kind, key, value in [("s", "name", "x"), ("n", "count", "3"), ("n", "none", ""), ("b", "flag", "true"), ("j", "raw", '{"a": [1]}'), ("A", "empty", ""), ("o", "items", ""), (".s", "id", "one"), (".b", "agent", "false")]:
        records += [kind, key, value]
    records += [part for index in range(205) for part in ("a", "long", str(index))]
    data = helpers.json.build(("\0".join(records) + "\0").encode("utf-8"))
    assert data["name"] == "x" and data["count"] == 3 and data["none"] is None and data["flag"] is True
    assert data["raw"] == {"a": [1]} and data["empty"] == [] and data["items"] == [{"id": "one", "agent": False}]
    assert len(data["long"]) == 200 and data["truncated"] == ["long"]


def test_scan_ignores_removed_lines_and_reads_added_line_numbers(helpers):
    secret = "ghp_" + "Qw3rT" * 8
    diff = f"diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -3 +3,2 @@\n-OLD = '{secret}'\n+value = 1\n+NEW = '{secret}'\ndiff --git a/img.png b/img.png\nnew file mode 100644\nBinary files /dev/null and b/img.png differ\n"
    assert helpers.scan.scan_diff(diff, ["app.py", "img.png", "keys/prod.pem"]) == [
        {"file": "keys/prod.pem", "line": None, "rule": "sensitive-file"},
        {"file": "app.py", "line": 4, "rule": "github-token"},
    ]
    assert helpers.scan.scan_line('tokenizer = "bert-base-uncased-model"') is None
    assert helpers.scan.scan_line('password: "' + "s3cr3t-Pa55w0rd!" + '"') == "hardcoded-credential"


# ------------------------------------------- regressions from the review
# Each test names the finding it pins: (N) in the adversarial review of
# skills/public/git-pr-workflow.


def test_restore_clean_never_deletes_through_a_symlinked_directory(repos):
    """(1) a tracked directory replaced by a symlink to a folder outside the repository."""
    work = repos.work
    ok("branch", "feat/link", cwd=work)
    commit_file(work, "output/report.txt", "tracked report\n", "add report")
    outside = repos.tmp / "shared-outputs"
    outside.mkdir()
    (outside / "report.txt").write_text("IMPORTANT user file outside the repo\n", encoding="utf-8")
    shutil.rmtree(work / "output")
    (work / "output").symlink_to(outside, target_is_directory=True)
    ok("checkpoint", "-m", "with link", cwd=work)

    result = ok("restore", "latest", "--clean", cwd=work)

    assert (outside / "report.txt").read_text(encoding="utf-8") == "IMPORTANT user file outside the repo\n"
    assert "output/report.txt" not in result["deleted"]
    assert any("symlink" in warning for warning in result["warnings"])


def test_checkpoint_captures_edits_hidden_by_skip_worktree_and_assume_unchanged(repos):
    """(2) local edits in flagged files survive a restore through the safety checkpoint."""
    work = repos.work
    ok("branch", "feat/flags", cwd=work)
    commit_file(work, "settings.yml", "db: prod\n", "settings")
    commit_file(work, "hosts.txt", "prod-host\n", "hosts")
    git(work, "update-index", "--skip-worktree", "settings.yml")
    git(work, "update-index", "--assume-unchanged", "hosts.txt")
    before = ok("checkpoint", "-m", "pristine", cwd=work)
    (work / "settings.yml").write_text("db: local # my local edits\n", encoding="utf-8")
    (work / "hosts.txt").write_text("my-laptop\n", encoding="utf-8")

    edited = ok("checkpoint", "-m", "edited", cwd=work)
    assert git(work, "show", f"{edited['commit']}:settings.yml") == "db: local # my local edits"
    assert git(work, "show", f"{edited['commit']}:hosts.txt") == "my-laptop"
    assert git(work, "ls-files", "-v", "settings.yml", "hosts.txt").splitlines() == ["h hosts.txt", "S settings.yml"], "flags stay set"

    restored = ok("restore", before["id"], cwd=work)
    assert (work / "settings.yml").read_text(encoding="utf-8") == "db: prod\n"
    ok("restore", restored["safety_checkpoint"], cwd=work)
    assert (work / "settings.yml").read_text(encoding="utf-8") == "db: local # my local edits\n"
    assert (work / "hosts.txt").read_text(encoding="utf-8") == "my-laptop\n"


def test_restore_refuses_when_a_directory_or_file_is_in_the_way(repos):
    """(3) restore never removes a directory (ignored files, nested repos) to write a file."""
    work = repos.work
    ok("branch", "feat/inway", cwd=work)
    commit_file(work, "deploy", "#!/bin/sh\n", "deploy script")
    commit_file(work, "conf/app.ini", "x=1\n", "config")
    checkpoint = ok("checkpoint", cwd=work)
    (work / "deploy").unlink()
    (work / "deploy").mkdir()
    (work / "deploy" / "run.sh").write_text("new\n", encoding="utf-8")
    (work / "deploy" / "prod.log").write_text("ignored and precious\n", encoding="utf-8")
    shutil.rmtree(work / "conf")
    (work / "conf").write_text("now a file\n", encoding="utf-8")

    payload = refused("restore", checkpoint["id"], cwd=work)

    assert sorted(payload["blocked_paths"]) == ["conf", "deploy"]
    assert (work / "deploy" / "prod.log").read_text(encoding="utf-8") == "ignored and precious\n"
    assert (work / "conf").read_text(encoding="utf-8") == "now a file\n"
    assert ok("checkpoints", cwd=work)["count"] == 1, "a refused restore leaves no safety checkpoint behind"


def test_restore_keeps_ignored_files_it_overwrites_in_the_safety_checkpoint(repos):
    """(4) a file that became ignored can be brought back by the documented undo."""
    work = repos.work
    ok("branch", "feat/ignored-restore", cwd=work)
    (work / "local.cfg").write_text("API_KEY=old-key\n", encoding="utf-8")
    checkpoint = ok("checkpoint", cwd=work)
    with (work / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("local.cfg\n")
    (work / "local.cfg").write_text("API_KEY=new-rotated-key\n", encoding="utf-8")

    restored = ok("restore", checkpoint["id"], cwd=work)
    assert (work / "local.cfg").read_text(encoding="utf-8") == "API_KEY=old-key\n"
    assert git(work, "show", f"refs/deerflow-checkpoints/{restored['safety_checkpoint']}:local.cfg") == "API_KEY=new-rotated-key"

    ok("restore", restored["safety_checkpoint"], cwd=work)
    assert (work / "local.cfg").read_text(encoding="utf-8") == "API_KEY=new-rotated-key\n"


def test_worktree_remove_sees_untracked_files_whatever_the_status_config(repos):
    """(5) status.showUntrackedFiles=no must not hide new files from the dirty check."""
    work = repos.work
    git(work, "config", "status.showUntrackedFiles", "no")
    added = ok("worktree", "add", "sub1", cwd=work)
    (Path(added["path"]) / "feature.py").write_text("print('unsaved')\n", encoding="utf-8")

    assert "uncommitted" in refused("worktree", "remove", "sub1", cwd=work)["error"]
    assert (Path(added["path"]) / "feature.py").exists()
    listing = ok("worktree", "list", cwd=work)
    assert [item["dirty"] for item in listing["worktrees"] if item["agent"]] == [True]


def test_paths_are_literal_names_not_glob_patterns(repos):
    """(6) brackets, stars and question marks in --paths are file names."""
    work = repos.work
    ok("branch", "feat/literal", cwd=work)
    (work / "notes[1].md").write_text("intended\n", encoding="utf-8")
    (work / "notes1.md").write_text("private scratch\n", encoding="utf-8")

    result = ok("commit", "-m", "docs: notes", "--paths", "notes[1].md", cwd=work)

    assert result["files"] == ["notes[1].md"]
    assert git(work, "status", "--porcelain") == "?? notes1.md"
    (work / "test[1].py").write_text("kept\n", encoding="utf-8")
    checkpoint = ok("checkpoint", cwd=work)
    (work / "test1.py").write_text("unrelated new file\n", encoding="utf-8")
    cleaned = ok("restore", checkpoint["id"], "--paths", "test[1].py", "--clean", cwd=work)
    assert cleaned["deleted"] == [] and (work / "test1.py").exists()


def test_default_branch_is_asked_from_the_remote_when_origin_head_is_missing(tmp_path):
    """(7) a checkout without origin/HEAD (git init + fetch) still protects the real default branch."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "develop", str(origin))
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "-b", "develop", str(seed))
    commit_file(seed, "README.md", "hello\n", "initial")
    git(seed, "push", "-q", str(origin), "develop")
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "-b", "scratch", str(work))
    git(work, "remote", "add", "origin", str(origin))
    git(work, "fetch", "-q", "origin")
    git(work, "switch", "-q", "-c", "develop", "--track", "origin/develop")

    facts = ok("preflight", cwd=work)
    assert facts["default_branch"] == "develop" and facts["on_default_branch"] is True
    assert any("protected branch 'develop'" in warning for warning in facts["warnings"])
    (work / "b.txt").write_text("b\n", encoding="utf-8")
    assert "protected branch 'develop'" in refused("commit", "-m", "x", "--paths", "b.txt", cwd=work)["error"]
    ok("commit", "-m", "x", "--paths", "b.txt", "--allow-default-branch", cwd=work)
    assert "protected branch 'develop'" in refused("push", cwd=work)["error"]


def test_refused_commit_puts_back_index_flags_and_intent_to_add_entries(repos):
    """(8) the index backup keeps skip-worktree, assume-unchanged and intent-to-add."""
    work = repos.work
    ok("branch", "feat/index", cwd=work)
    commit_file(work, "settings.yml", "db: prod\n", "settings")
    commit_file(work, "hosts.txt", "prod-host\n", "hosts")
    git(work, "update-index", "--skip-worktree", "settings.yml")
    git(work, "update-index", "--assume-unchanged", "hosts.txt")
    (work / "settings.yml").write_text("db: local, password: hunter2-local\n", encoding="utf-8")
    (work / "planned.py").write_text("planned\n", encoding="utf-8")
    git(work, "add", "-N", "planned.py")
    flags_before = git(work, "ls-files", "-v")
    status_before = subprocess.run([GIT, "status", "--porcelain"], cwd=work, capture_output=True, text=True, check=True).stdout
    assert " A planned.py" in status_before.splitlines(), "planned.py is an intent-to-add entry"
    (work / "api.py").write_text(f'TOKEN_VALUE = "{GH_SECRET}"\n', encoding="utf-8")

    payload = refused("commit", "-m", "add api", "--paths", "api.py", cwd=work)

    assert payload["index_restored"] is True
    assert git(work, "ls-files", "-v") == flags_before
    status_after = subprocess.run([GIT, "status", "--porcelain"], cwd=work, capture_output=True, text=True, check=True).stdout
    assert status_after == status_before + "?? api.py\n"


def test_worktree_remove_force_refuses_when_the_state_cannot_be_read(repos):
    """(9) a failing status is not 'clean': --force needs a checkpoint that succeeds."""
    work = repos.work
    added = ok("worktree", "add", "sub1", cwd=work)
    wt = Path(added["path"])
    (wt / "work.py").write_text("unsaved\n", encoding="utf-8")
    (Path(git(wt, "rev-parse", "--absolute-git-dir")) / "index").write_bytes(b"x")

    refused("worktree", "remove", "sub1", "--force", cwd=work)

    assert (wt / "work.py").read_text(encoding="utf-8") == "unsaved\n"


def test_github_tokens_are_only_sent_for_github_com(helpers, monkeypatch, capsys):
    """(10) GH_TOKEN / GITHUB_TOKEN are github.com credentials; other hosts need an explicit opt-in."""
    seen = []
    route_urllib(helpers, monkeypatch, lambda request, timeout=None: seen.append(request.full_url) or pytest.fail("no request may be sent"))
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)

    code = helpers.github.main(["pr-status", "--host", "gitlab.com", "--owner", "acme", "--repo", "widgets", "--branch", "feat/x"])

    out = capsys.readouterr()
    assert code == 1 and seen == []
    payload = json.loads(out.out)
    assert payload["ok"] is False and "gitlab.com" in payload["error"]
    assert FAKE_TOKEN not in out.out + out.err
    assert helpers.github.auth_for_host("gitlab.com") == (None, None)
    assert helpers.github.auth_for_host("github.com") == ("GH_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("GH_ENTERPRISE_TOKEN", "enterprise-" + "value-123456789")
    assert helpers.github.auth_for_host("git.corp.example") == (None, None), "an enterprise token needs the host on the allowlist"
    monkeypatch.setenv("GITFLOW_GITHUB_HOSTS", "git.other.example, git.corp.example")
    assert helpers.github.auth_for_host("git.corp.example") == ("GH_ENTERPRISE_TOKEN", "enterprise-value-123456789")
    assert helpers.github.auth_for_host("gitlab.com") == (None, None)


def test_pr_create_refuses_to_send_the_token_to_a_non_github_remote(github, monkeypatch):
    """(15) end to end: the fake API never sees a request when the remote is not github.com."""
    work = github.work
    other = "https://gitea.example.org/someone/proj.git"
    git(work, "remote", "set-url", "origin", other)
    git(work, "config", f"url.{github.origin}.insteadOf", other)
    pushed_branch(work, "feat/elsewhere")
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)

    payload = refused("pr", "create", "--title", "t", "--body", "b", cwd=work)

    assert "gitea.example.org" in payload["error"] and github.fake.requests == []
    facts = ok("preflight", cwd=work)
    assert facts["github_auth"] is None
    assert any("only sent to github.com" in warning for warning in facts["warnings"])


def test_commit_scans_files_that_git_treats_as_binary(repos):
    """(11) a -diff attribute, NUL bytes or UTF-16 must not hide a token from the scan."""
    work = repos.work
    ok("branch", "feat/binary", cwd=work)
    (work / ".gitattributes").write_text("secrets.cfg -diff\n", encoding="utf-8")
    (work / "secrets.cfg").write_text(f"token = {GH_SECRET}\n", encoding="utf-8")
    payload = refused("commit", "-m", "add cfg", "--paths", ".gitattributes", "secrets.cfg", cwd=work)
    assert {"file": "secrets.cfg", "line": 1, "rule": "github-token"} in payload["findings"]

    (work / "win.ini").write_bytes(f"[auth]\r\nGITHUB={GH_SECRET}\r\n".encode("utf-16"))
    payload = refused("commit", "-m", "add ini", "--paths", "win.ini", cwd=work)
    assert [finding["rule"] for finding in payload["findings"]] == ["github-token"]


def test_rest_client_drops_authorization_on_cross_origin_redirects(helpers):
    """(14) a redirect to another host or port must not carry the token."""
    seen: dict[str, object] = {}

    class Target(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen["authorization"] = self.headers.get("Authorization")
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

    class Redirector(Target):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{target.server_address[1]}/collect")
            self.send_header("Content-Length", "0")
            self.end_headers()

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    for server in (target, origin):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        transport = helpers.github.RestTransport("github.com", FAKE_TOKEN, base=f"http://127.0.0.1:{origin.server_address[1]}")
        status, _ = transport.request("GET", "/repos/acme/widgets")
    finally:
        for server in (target, origin):
            server.shutdown()
            server.server_close()
    assert status == 200 and "authorization" in seen
    assert seen["authorization"] is None


def test_helper_failures_keep_the_json_contract(github, monkeypatch):
    """(16) a dropped create response goes through the lookup; an undecodable body is a JSON error."""
    work = github.work
    pushed = pushed_branch(work, "feat/flaky-api")
    github.fake.head_sha = pushed["remote_sha"]
    github.fake.truncate_next_post = True
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)

    created = ok("pr", "create", "--title", "feat: v", "--body", "b", cwd=work)

    assert created["number"] == 1 and created["created"] is True
    assert [request["method"] for request in github.fake.requests] == ["GET", "POST", "GET", "GET"]
    latin1 = github.tmp / "latin1.md"
    latin1.write_bytes("caf\xe9 au lait\n".encode("latin-1"))
    payload = refused("pr", "create", "--title", "t2", "--body-file", str(latin1), cwd=work)
    assert "UTF-8" in payload["error"]


def test_push_verifies_the_ref_where_it_pushed(repos):
    """(17) with a separate pushurl the read-back asks the push target, not the fetch URL."""
    work = repos.work
    fork = repos.tmp / "fork.git"
    git(repos.tmp, "init", "-q", "--bare", str(fork))
    git(work, "remote", "set-url", "--push", "origin", str(fork))
    ok("branch", "feat/fork", cwd=work)
    sha = commit_file(work, "a.txt", "a\n", "feat: a")

    pushed = ok("push", cwd=work)

    assert pushed["remote_sha"] == sha == git(fork, "rev-parse", "refs/heads/feat/fork")


def test_paths_end_at_the_next_option(repos):
    """(18) --paths stops at any option, so -m may follow it."""
    work = repos.work
    ok("branch", "feat/order", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    assert ok("commit", "--paths", "a.txt", "-m", "feat: add a", cwd=work)["files"] == ["a.txt"]
    (work / "b.txt").write_text("b\n", encoding="utf-8")
    ok("commit", "-m", "feat: add b", "--paths", "b.txt", "-m", "Body paragraph.", cwd=work)
    assert git(work, "log", "-1", "--format=%B") == "feat: add b\n\nBody paragraph."


def test_a_missing_temporary_directory_is_reported_as_json(repos):
    """(19) the mktemp failure happens before any trap; it still prints JSON."""
    env = dict(os.environ, TMPDIR=str(repos.tmp / "does-not-exist"))
    code, payload, stdout, stderr = run_cli("preflight", cwd=repos.work, env=env)
    assert code == 1 and payload is not None and payload["ok"] is False, stdout + stderr
    assert "temporary directory" in payload["error"]


def test_checkpoint_ids_keep_creation_order_without_sub_second_clock(repos):
    """(20) bash 4.4 has no EPOCHREALTIME; ids created in one second must still sort newest first."""
    work = repos.work
    ok("branch", "feat/order-ids", cwd=work)
    fake_tool(repos.bin, "date", "exit 1\n")
    for index in range(10):
        (work / "n.txt").write_text(f"{index}\n", encoding="utf-8")
        proc = subprocess.run([BASH, "-c", 'unset EPOCHREALTIME; source "$0" "$@"', str(GITFLOW), "checkpoint", "-m", f"n{index}"], cwd=work, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    listing = ok("checkpoints", cwd=work)

    assert [item["message"] for item in listing["checkpoints"]] == [f"deerflow checkpoint: n{index}" for index in reversed(range(10))]


def test_index_backup_keeps_a_sparse_checkout_sparse(repos):
    """(21) a refused commit in a sparse checkout leaves files outside the cone alone."""
    work = repos.work
    ok("branch", "feat/sparse", cwd=work)
    commit_file(work, "a/x.txt", "x\n", "a")
    commit_file(work, "b/y.txt", "y\n", "b")
    git(work, "sparse-checkout", "set", "a")
    assert not (work / "b" / "y.txt").exists()
    checkpoint = ok("checkpoint", cwd=work)
    assert "b/y.txt" in git(work, "ls-tree", "-r", "--name-only", checkpoint["commit"]).splitlines(), "a checkpoint does not record the sparse files as deleted"
    (work / "a" / "conf.py").write_text(f'TOKEN_VALUE = "{GH_SECRET}"\n', encoding="utf-8")

    refused("commit", "-m", "conf", "--paths", "a/conf.py", cwd=work)

    assert git(work, "status", "--porcelain") == "?? a/conf.py"
    assert "S b/y.txt" in git(work, "ls-files", "-v").splitlines()


def test_option_like_titles_reach_the_api_unchanged(github, monkeypatch):
    """(22) a title such as -WIP- is a value, not an option of the helper."""
    work = github.work
    github.fake.head_sha = pushed_branch(work, "feat/dash")["remote_sha"]
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)

    created = ok("pr", "create", "--title", "-WIP-", "--body", "-b", cwd=work)

    assert created["title"] == "-WIP-" and github.fake.requests[1]["body"]["body"] == "-b"


def test_commit_passes_the_message_on_stdin_as_documented(repos):
    """(23) the reference says git commit -F - with the message on stdin; the script must do that."""
    doc = (SKILL_DIR / "references" / "gitflow-cli.md").read_text(encoding="utf-8")
    script = GITFLOW.read_text(encoding="utf-8")
    assert "`git commit -F -`" in doc
    assert 'GIT_STDIN="$TMP/commit.msg"' in script and "commit --quiet -F -" in script
