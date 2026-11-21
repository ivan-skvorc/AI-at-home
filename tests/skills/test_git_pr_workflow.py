"""Offline tests for the git-pr-workflow skill's gitflow.py.

Every test builds throwaway repositories under tmp_path with a local bare
repository as origin. The GitHub REST API is an in-memory fake behind
urllib.request.urlopen, and PATH holds only git, so gh is never found and the
REST path is the one exercised. Fake secrets are assembled at runtime so this
file itself never contains a token-shaped string.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "skills" / "public" / "git-pr-workflow" / "scripts"
GITFLOW = SCRIPTS_DIR / "gitflow.py"
GIT = shutil.which("git")
GITHUB_URL = "https://github.com/acme/widgets.git"
FAKE_TOKEN = "fake-" + "token-" + "0123456789abcdef"

pytestmark = [
    pytest.mark.skipif(GIT is None, reason="git is not installed"),
    pytest.mark.skipif(os.name != "posix", reason="gitflow.py targets POSIX shells and paths"),
]


# --------------------------------------------------------------- helpers


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Hermetic git: private HOME and global config, PATH with git and nothing else."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(GIT)
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = Test Agent\n\temail = agent@example.com\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    for name in list(os.environ):
        if name.startswith("GIT_") or name in ("GH_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout.strip()


def run_cli(*args: str, cwd: Path, stdin: str | None = None) -> tuple[int, dict | None, str, str]:
    proc = subprocess.run([sys.executable, "-B", str(GITFLOW), *args], cwd=cwd, input=stdin, capture_output=True, text=True, timeout=120, check=False)
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, payload, proc.stdout, proc.stderr


def ok(*args: str, cwd: Path, stdin: str | None = None) -> dict:
    code, payload, stdout, stderr = run_cli(*args, cwd=cwd, stdin=stdin)
    assert code == 0, f"gitflow {' '.join(args)} exited {code}: {stdout} {stderr}"
    assert payload["ok"] is True
    return payload


def refused(*args: str, cwd: Path, stdin: str | None = None) -> dict:
    code, payload, stdout, stderr = run_cli(*args, cwd=cwd, stdin=stdin)
    assert code == 1, f"expected a refusal from gitflow {' '.join(args)}: {stdout} {stderr}"
    assert payload["ok"] is False and payload["error"]
    assert payload["error"] in stderr
    return payload


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
    return SimpleNamespace(origin=origin, seed=seed, work=work, tmp=tmp_path)


def commit_file(repo: Path, name: str, text: str, message: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def gitflow(monkeypatch):
    """gitflow.py imported in-process, for mocking urllib and the retry clock."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in ("gitflow_github", "gitflow_under_test"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("gitflow_under_test", GITFLOW)
    module = importlib.util.module_from_spec(spec)
    sys.modules["gitflow_under_test"] = module
    spec.loader.exec_module(module)
    yield module
    for name in ("gitflow_github", "gitflow_under_test"):
        sys.modules.pop(name, None)


def call(module, capsys, *args: str) -> tuple[int, dict, str]:
    code = module.main(list(args))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.out + captured.err


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
    assert facts["staged"] == ["staged.txt"]
    assert facts["unstaged"] == ["README.md"]
    assert facts["untracked"] == ["new.txt"]
    assert facts["gh"] == {"installed": False, "authenticated": False}
    assert facts["token_present"] is False and facts["token_env"] == []
    assert facts["github_repo"] is None
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
    assert password not in stdout + stderr
    assert FAKE_TOKEN not in stdout + stderr


def test_preflight_outside_a_repository_fails_with_a_hint(tmp_path):
    payload = refused("preflight", cwd=tmp_path)
    assert "not inside a git work tree" in payload["error"]
    assert "--repo" in payload["hint"]


def test_redact_hides_url_credentials_token_shapes_and_live_values(gitflow, monkeypatch):
    live = "live-" + "value-" + "9876543210"
    monkeypatch.setenv("GITHUB_TOKEN", live)
    token_shape = "ghp_" + "Ab3dE" * 8
    text = gitflow.redact(f"fatal: unable to access 'https://x-access-token:{live}@github.com/a/b.git/' https://{token_shape}@github.com/a/b.git {token_shape} {live} ssh://git@github.com/a/b.git git@github.com:a/b.git")
    assert live not in text and token_shape not in text
    assert "https://***@github.com/a/b.git/" in text
    assert "ssh://git@github.com/a/b.git" in text and "git@github.com:a/b.git" in text


def test_parse_remote_url_accepts_https_ssh_and_enterprise_forms(gitflow):
    parse = gitflow.github_api.parse_remote_url
    assert parse("https://github.com/acme/widgets.git").slug == "acme/widgets"
    assert parse("https://user:pw@github.com/acme/widgets").slug == "acme/widgets"
    assert parse("git@github.com:acme/widgets.git").slug == "acme/widgets"
    assert parse("ssh://git@ssh.github.com:443/acme/widgets.git").host == "github.com"
    enterprise = parse("https://git.corp.example/team/tool.git")
    assert (enterprise.host, enterprise.owner, enterprise.name) == ("git.corp.example", "team", "tool")
    assert gitflow.github_api.api_base(enterprise.host) == "https://git.corp.example/api/v3"
    assert parse("/srv/git/widgets.git") is None
    assert parse("../widgets.git") is None
    assert parse("file:///srv/git/widgets.git") is None


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
    assert checkpoint["head"] == head_before and checkpoint["branch"] == "feat/ck"
    assert git(work, "status", "--porcelain") == status_before, "checkpoint must not touch the index or work tree"
    assert git(work, "rev-parse", "HEAD") == head_before
    snapshot = git(work, "ls-tree", "-r", "--name-only", checkpoint["commit"]).splitlines()
    assert {"README.md", "notes.txt", "staged.txt", ".gitignore"} <= set(snapshot)
    assert "debug.log" not in snapshot
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


def test_restore_with_paths_only_touches_those_paths(repos):
    work = repos.work
    ok("branch", "feat/paths", cwd=work)
    (work / "a.txt").write_text("a1\n", encoding="utf-8")
    (work / "b.txt").write_text("b1\n", encoding="utf-8")
    checkpoint = ok("checkpoint", cwd=work)
    (work / "a.txt").write_text("a2\n", encoding="utf-8")
    (work / "b.txt").write_text("b2\n", encoding="utf-8")

    result = ok("restore", "latest", "--paths", "a.txt", cwd=work)

    assert result["id"] == checkpoint["id"] and result["restored"] == ["a.txt"]
    assert (work / "a.txt").read_text(encoding="utf-8") == "a1\n"
    assert (work / "b.txt").read_text(encoding="utf-8") == "b2\n"
    refused("restore", "no-such-checkpoint", cwd=work)


# ------------------------------------------------------------------ commit

SECRET_CASES = [
    ("config.py", 'GITHUB = "' + "ghp_" + "Ab3dE" * 8 + '"\n', "github-token"),
    ("config.py", 'PAT = "' + "github_pat_" + "11AbCdEfGh" * 4 + '"\n', "github-token"),
    ("deploy.sh", "export KEY_ID=" + "AKIA" + "QWERTYUIOPASDFGH" + "\n", "aws-access-key"),
    ("deploy_key", "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc\n", "private-key"),
    ("notify.js", 'const hook = "' + "xoxb-" + "1234567890-abcdefghij" + '";\n', "slack-token"),
    ("settings.py", 'DB_PASSWORD = "' + "q8Zr2Lk9" + "Wm4Tn7Vb" + '"\n', "hardcoded-credential"),
    ("settings.json", '{"api_key": "' + "Zx81Qp0" + "Lm22Rt9" + '"}\n', "hardcoded-credential"),
]


@pytest.mark.parametrize(("filename", "secret_line", "rule"), SECRET_CASES)
def test_commit_refuses_secrets_in_the_staged_diff(repos, filename, secret_line, rule):
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
    secret_value = secret_line.split('"')[1] if '"' in secret_line else secret_line.split("=")[-1].strip()
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
    assert result["files_changed"] == 3 and result["insertions"] == 8


def test_commit_refuses_the_default_branch_unless_allowed(repos):
    work = repos.work
    (work / "README.md").write_text("changed on main\n", encoding="utf-8")
    payload = refused("commit", "-m", "docs: tweak", "--all", cwd=work)
    assert "protected branch 'main'" in payload["error"]
    assert "branch" in payload["hint"]
    assert git(work, "diff", "--cached", "--name-only") == ""

    allowed = ok("commit", "-m", "docs: tweak", "--all", "--allow-default-branch", cwd=work)
    assert allowed["branch"] == "main" and allowed["sha"] == git(work, "rev-parse", "HEAD")


def test_commit_refuses_an_empty_commit_and_detached_head(repos):
    work = repos.work
    ok("branch", "feat/empty", cwd=work)
    payload = refused("commit", "-m", "nothing", "--all", cwd=work)
    assert "nothing to commit" in payload["error"]
    git(work, "switch", "-q", "--detach", "HEAD")
    (work / "x.txt").write_text("x\n", encoding="utf-8")
    assert "detached" in refused("commit", "-m", "x", "--all", cwd=work)["error"]


def test_commit_takes_the_message_verbatim_from_stdin_and_only_named_paths(repos):
    work = repos.work
    ok("branch", "feat/message", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    (work / "README.md").write_text("not part of this commit\n", encoding="utf-8")
    message = 'fix: handle "quotes", `backticks` and $(dollar) signs\n\nBody with $HOME, a # heading and \\n literally.\n'

    result = ok("commit", "--paths", "a.txt", "--message-file", "-", cwd=work, stdin=message)

    assert git(work, "log", "-1", "--format=%B") == message.strip()
    assert result["files"] == ["a.txt"] and result["subject"] == message.splitlines()[0]
    assert result["shortstat"] == "1 file changed, 1 insertion(+)"
    assert git(work, "status", "--porcelain") == "M README.md"


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

    assert "ignored" in payload["error"] and payload["index_restored"] is True
    assert git(work, "diff", "--cached", "--name-only") == ""


# -------------------------------------------------------------------- push


def test_push_to_the_bare_remote_is_verified_and_keeps_checkpoints_local(repos):
    work = repos.work
    ok("branch", "feat/push", cwd=work)
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    ok("checkpoint", "-m", "local only", cwd=work)
    sha = ok("commit", "-m", "feat: add a", "--paths", "a.txt", cwd=work)["sha"]

    pushed = ok("push", cwd=work)

    assert pushed["verified"] is True and pushed["result"] == "new branch"
    assert pushed["local_sha"] == sha == pushed["remote_sha"]
    assert git(repos.origin, "rev-parse", "refs/heads/feat/push") == sha
    assert pushed["upstream"] == "origin/feat/push" and pushed["attempts"] == 1
    assert "deerflow-checkpoints" not in git(work, "ls-remote", "origin")

    again = ok("push", cwd=work)
    assert again["result"] == "up to date" and again["remote_sha"] == sha


def test_push_refuses_protected_branches(repos):
    payload = refused("push", cwd=repos.work)
    assert "protected branch 'main'" in payload["error"]


def test_push_rejects_rewritten_history_without_lease_and_accepts_it_with_lease(repos):
    work = repos.work
    ok("branch", "feat/rewrite", cwd=work)
    commit_file(work, "a.txt", "a\n", "feat: a")
    ok("push", cwd=work)
    git(work, "commit", "-q", "--amend", "-m", "feat: a (reworded)")
    amended = git(work, "rev-parse", "HEAD")

    rejected = refused("push", cwd=work)
    assert "rebase" in rejected["hint"]
    assert git(repos.origin, "rev-parse", "refs/heads/feat/rewrite") != amended

    forced = ok("push", "--force-with-lease", cwd=work)
    assert forced["forced"] is True and forced["remote_sha"] == amended


def test_push_retries_transient_failures_with_backoff(gitflow, repos, monkeypatch, capsys):
    work = repos.work
    ok("branch", "feat/flaky", cwd=work)
    sha = commit_file(work, "a.txt", "a\n", "feat: a")
    real_git = gitflow._git
    failures = {"left": 2}
    secret_url = "https://x-access-token:" + FAKE_TOKEN + "@github.com/acme/widgets.git/"

    def flaky_git(repo, *args, **kwargs):
        if args[:1] == ("push",) and failures["left"]:
            failures["left"] -= 1
            return gitflow.Result(128, "", f"fatal: unable to access '{secret_url}': Could not resolve host: github.com")
        return real_git(repo, *args, **kwargs)

    sleeps: list[float] = []
    monkeypatch.setattr(gitflow, "_git", flaky_git)
    monkeypatch.setattr(gitflow, "_sleep", sleeps.append)

    code, payload, output = call(gitflow, capsys, "push", "--repo", str(work))

    assert code == 0 and payload["verified"] is True and payload["remote_sha"] == sha
    assert payload["attempts"] == 3 and sleeps == [2.0, 4.0]
    assert FAKE_TOKEN not in output


def test_push_does_not_retry_authentication_failures(gitflow, repos, monkeypatch, capsys):
    work = repos.work
    ok("branch", "feat/denied", cwd=work)
    commit_file(work, "a.txt", "a\n", "feat: a")
    secret_url = "https://agent:" + FAKE_TOKEN + "@github.com/acme/widgets.git/"

    def denied_git(repo, *args, **kwargs):
        if args[:1] == ("push",):
            return gitflow.Result(128, "", f"remote: Permission denied.\nfatal: unable to access '{secret_url}': The requested URL returned error: 403")
        return real_git(repo, *args, **kwargs)

    real_git = gitflow._git
    sleeps: list[float] = []
    monkeypatch.setattr(gitflow, "_git", denied_git)
    monkeypatch.setattr(gitflow, "_sleep", sleeps.append)

    code, payload, output = call(gitflow, capsys, "push", "--repo", str(work))

    assert code == 1 and payload["attempts"] == 1 and sleeps == []
    assert "Authentication" in payload["hint"]
    assert FAKE_TOKEN not in output and "https://***@github.com" in output


# -------------------------------------------------------------- worktrees


def test_worktrees_isolate_parallel_agents(repos):
    work = repos.work
    first = ok("worktree", "add", "api", cwd=work)
    second = ok("worktree", "add", "docs", cwd=work)

    assert first["created"] is True and first["branch"] == "agent/api"
    assert Path(first["path"]) == work / ".worktrees" / "api"
    assert Path(second["path"]) == work / ".worktrees" / "docs"
    assert "/.worktrees/" in (work / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert git(work, "status", "--porcelain") == "", "worktrees never show up as untracked"

    api = Path(first["path"])
    (api / "api.txt").write_text("api work\n", encoding="utf-8")
    ok("commit", "-m", "feat: api", "--paths", "api.txt", cwd=api)
    assert not (Path(second["path"]) / "api.txt").exists()
    assert git(work, "branch", "--show-current") == "main"

    assert ok("worktree", "add", "api", cwd=work)["created"] is False
    listing = ok("worktree", "list", cwd=work)
    agents = {item["name"]: item for item in listing["worktrees"] if item["agent"]}
    assert set(agents) == {"api", "docs"} and agents["api"]["dirty"] is False

    removed = ok("worktree", "remove", "api", "--delete-branch", cwd=work)
    assert removed["removed"] is True and removed["branch_deleted"] is False, "unmerged work keeps its branch"
    assert git(work, "rev-parse", "--verify", "agent/api")

    docs = Path(second["path"])
    (docs / "draft.md").write_text("unsaved\n", encoding="utf-8")
    payload = refused("worktree", "remove", "docs", cwd=work)
    assert "uncommitted" in payload["error"]
    forced = ok("worktree", "remove", "docs", "--force", cwd=work)
    assert forced["removed"] is True and not docs.exists()
    assert git(work, "show", f"refs/deerflow-checkpoints/{forced['checkpoint']}:draft.md") == "unsaved"


# --------------------------------------------------------- pull requests


class FakeResponse(io.BytesIO):
    def __init__(self, status: int, payload) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status


class FakeGitHub:
    """In-memory slice of the GitHub REST API that gitflow.py uses."""

    def __init__(self, owner: str = "acme", name: str = "widgets") -> None:
        self.prefix = f"/repos/{owner}/{name}"
        self.owner = owner
        self.pulls: dict[int, dict] = {}
        self.hidden_from_first_list: set[int] = set()
        self.requests: list[dict] = []
        self.check_runs: list[dict] = []
        self.statuses: list[dict] = []
        self.reviews: list[dict] = []

    def __call__(self, request, timeout=None):
        url = urlsplit(request.full_url)
        assert (url.scheme, url.netloc) == ("https", "api.github.com")
        body = json.loads(request.data) if request.data else None
        entry = {"method": request.get_method(), "path": url.path, "query": parse_qs(url.query), "body": body, "headers": dict(request.header_items())}
        self.requests.append(entry)
        status, payload = self.route(entry)
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(json.dumps(payload).encode("utf-8")))
        return FakeResponse(status, payload)

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

    def route(self, entry):
        method, path, query = entry["method"], entry["path"], entry["query"]
        if path == self.prefix + "/pulls" and method == "GET":
            owner, _, branch = query["head"][0].partition(":")
            state = query.get("state", ["open"])[0]
            found = [pull for pull in self.pulls.values() if owner == self.owner and pull["head"]["ref"] == branch and state in ("all", pull["state"])]
            if self.hidden_from_first_list:
                found = [pull for pull in found if pull["number"] not in self.hidden_from_first_list]
                self.hidden_from_first_list.clear()
            return 200, sorted(found, key=lambda pull: -pull["number"])
        if path == self.prefix + "/pulls" and method == "POST":
            body = entry["body"]
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


@pytest.fixture
def github(repos, monkeypatch):
    """work's origin is a GitHub URL that git rewrites to the local bare repository."""
    git(repos.work, "remote", "set-url", "origin", GITHUB_URL)
    git(repos.work, "config", f"url.{repos.origin}.insteadOf", GITHUB_URL)
    fake = FakeGitHub()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return SimpleNamespace(fake=fake, **vars(repos))


def pushed_branch(work: Path, name: str) -> str:
    ok("branch", name, cwd=work)
    commit_file(work, "feature.txt", "feature\n", "feat: widget")
    return ok("push", cwd=work)["remote_sha"]


def test_pr_create_uses_rest_without_gh_and_is_idempotent(gitflow, github, monkeypatch, capsys):
    work = github.work
    sha = pushed_branch(work, "feat/widget")
    github.fake.head_sha = sha
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    body_file = github.tmp / "body.md"
    body_file.write_text("## Summary\n\n- Adds the widget\n", encoding="utf-8")

    code, created, output = call(gitflow, capsys, "pr", "create", "--repo", str(work), "--title", "feat: widget", "--body-file", str(body_file))

    assert code == 0, output
    assert created["created"] is True and created["via"] == "rest"
    assert created["number"] == 1 and created["url"] == "https://github.com/acme/widgets/pull/1"
    assert created["state"] == "open" and created["base"] == "main" and created["head"] == "feat/widget"
    assert created["head_matches_remote"] is True and created["head_matches_local"] is True
    lookup, post, readback = github.fake.requests
    assert lookup["method"] == "GET" and lookup["query"] == {"head": ["acme:feat/widget"], "state": ["open"], "per_page": ["20"], "sort": ["created"], "direction": ["desc"]}
    assert post["method"] == "POST" and post["body"] == {"title": "feat: widget", "body": "## Summary\n\n- Adds the widget\n", "head": "feat/widget", "base": "main", "draft": False}
    assert readback["method"] == "GET" and readback["path"] == "/repos/acme/widgets/pulls/1"
    assert all(request["headers"]["Authorization"] == "Bearer " + FAKE_TOKEN for request in github.fake.requests)
    assert FAKE_TOKEN not in output

    code, again, output = call(gitflow, capsys, "pr", "create", "--repo", str(work), "--title", "feat: widget v2", "--body", "other")

    assert code == 0 and again["created"] is False and again["number"] == 1
    assert [request["method"] for request in github.fake.requests].count("POST") == 1
    assert any("already existed" in warning for warning in again["warnings"])


def test_pr_create_returns_the_pull_request_that_won_a_creation_race(gitflow, github, monkeypatch, capsys):
    work = github.work
    sha = pushed_branch(work, "feat/race")
    github.fake.head_sha = sha
    existing = github.fake.add_pull("feat/race", sha, title="opened elsewhere")
    github.fake.hidden_from_first_list.add(existing["number"])
    monkeypatch.setenv("GITHUB_TOKEN", FAKE_TOKEN)

    code, payload, output = call(gitflow, capsys, "pr", "create", "--repo", str(work), "--title", "feat: race", "--body", "x", "--draft")

    assert code == 0, output
    assert payload["created"] is False and payload["number"] == existing["number"] and payload["title"] == "opened elsewhere"
    assert len(github.fake.pulls) == 1


def test_pr_create_requires_a_pushed_branch_and_credentials(gitflow, github, monkeypatch, capsys):
    work = github.work
    ok("branch", "feat/local-only", cwd=work)
    commit_file(work, "x.txt", "x\n", "feat: x")
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)
    code, payload, _ = call(gitflow, capsys, "pr", "create", "--repo", str(work), "--title", "t", "--body", "b")
    assert code == 1 and "not on origin" in payload["error"] and "push" in payload["hint"]

    ok("push", cwd=work)
    monkeypatch.delenv("GH_TOKEN")
    code, payload, _ = call(gitflow, capsys, "pr", "create", "--repo", str(work), "--title", "t", "--body", "b")
    assert code == 1 and "no GitHub credentials" in payload["error"]
    assert github.fake.requests == []


def test_pr_status_summarizes_checks_reviews_and_mergeability(gitflow, github, monkeypatch, capsys):
    work = github.work
    sha = pushed_branch(work, "feat/status")
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
    monkeypatch.setenv("GH_TOKEN", FAKE_TOKEN)

    code, status, output = call(gitflow, capsys, "pr", "status", "--repo", str(work))

    assert code == 0, output
    assert status["number"] == 1 and status["state"] == "open" and status["merged"] is False and status["mergeable"] is True
    assert status["head_matches_local"] is True
    checks = status["checks"]
    assert checks["sha"] == sha and checks["state"] == "failure"
    assert checks["counts"] == {"total": 4, "success": 2, "failure": 1, "pending": 1, "other": 0}
    assert [item["name"] for item in checks["failing"]] == ["lint"] and checks["pending"] == ["e2e"]
    assert status["reviews"] == {"approved": 1, "changes_requested": 0, "commented": 1}

    github.fake.check_runs = [{"name": "tests", "status": "completed", "conclusion": "success"}]
    code, green, _ = call(gitflow, capsys, "pr", "status", "--repo", str(work), "--number", "1")
    assert code == 0 and green["checks"]["state"] == "success"


FAKE_GH = """#!{python}
import json, sys
args = sys.argv[1:]
stdin = sys.stdin.read() if "--input" in args else None
with open({log!r}, "a", encoding="utf-8") as log:
    log.write(json.dumps({{"args": args, "stdin": stdin}}) + "\\n")
if args[:2] == ["auth", "status"]:
    sys.exit(0)
pull = {{"number": 7, "html_url": "https://github.com/acme/widgets/pull/7", "title": "feat: gh", "state": "open",
        "draft": True, "merged": False, "mergeable": None, "head": {{"ref": "feat/gh", "sha": {sha!r}}}, "base": {{"ref": "main"}}}}
method = args[args.index("--method") + 1]
endpoint = [arg for arg in args if arg.startswith("repos/")][0]
if method == "POST":
    print("HTTP/2.0 201 Created\\nContent-Type: application/json\\n\\n" + json.dumps(pull))
elif endpoint.endswith("/pulls/7"):
    print("HTTP/2.0 200 OK\\n\\n" + json.dumps(pull))
else:
    print("HTTP/2.0 200 OK\\n\\n[]")
"""


def test_pr_create_prefers_an_authenticated_gh(github):
    work = github.work
    sha = pushed_branch(work, "feat/gh")
    log = github.tmp / "gh-calls.jsonl"
    gh = github.tmp / "bin" / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable, log=str(log), sha=sha), encoding="utf-8")
    gh.chmod(0o755)

    created = ok("pr", "create", "--title", "feat: gh", "--body", "Body with `ticks` and $VARS", "--draft", cwd=work)

    assert created["via"] == "gh" and created["created"] is True and created["number"] == 7
    assert created["draft"] is True and created["head_matches_remote"] is True
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["args"][:2] == ["auth", "status"]
    api_calls = [call for call in calls if call["args"][:1] == ["api"]]
    assert [call["args"][call["args"].index("--method") + 1] for call in api_calls] == ["GET", "POST", "GET"]
    assert "repos/acme/widgets/pulls?head=acme:feat/gh&state=open" in api_calls[0]["args"][-1]
    assert json.loads(api_calls[1]["stdin"]) == {"title": "feat: gh", "body": "Body with `ticks` and $VARS", "head": "feat/gh", "base": "main", "draft": True}
    assert github.fake.requests == [], "the urllib transport is not used when gh works"


def test_parse_gh_include_reads_status_and_body(gitflow):
    parse = gitflow.parse_gh_include
    assert parse('HTTP/2.0 201 Created\nContent-Type: application/json\n\n{"number": 5}') == (201, {"number": 5})
    assert parse('HTTP/2.0 422 Unprocessable Entity\r\nX-Id: 1\r\n\r\n{"message": "Validation Failed"}') == (422, {"message": "Validation Failed"})
    assert parse("HTTP/2.0 204 No Content\n\n") == (204, None)
    assert parse("gh: not logged in") == (None, None)
