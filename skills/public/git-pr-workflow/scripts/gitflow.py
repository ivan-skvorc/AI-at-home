#!/usr/bin/env python3
"""gitflow.py -- reliable git and pull-request primitives for DeerFlow agents.

Standard library only, Python 3.10+, POSIX. Every subcommand prints one JSON
object on stdout. On failure it also writes a one-line diagnostic (plus a hint)
on stderr and exits non-zero. Output never contains a token: credentials in
remote URLs and known token values are redacted before anything is printed.

Subcommands (run gitflow.py <command> --help for details):

  preflight                         repository, branch and auth facts
  branch NAME [--from REF]          create or switch to a work branch from a fresh base
  checkpoint [-m MSG]               snapshot the working tree (untracked files too)
  checkpoints                       list snapshots
  restore ID [--paths P..] [--clean]  bring a snapshot's files back
  commit (-m MSG | --message-file F) [--paths P.. | --all]
  push [--remote R] [--force-with-lease]
  pr create --title T (--body B | --body-file F) [--base B] [--draft]
  pr status [--number N]
  worktree add NAME [--from REF] | worktree remove NAME | worktree list

Paths given to --paths are relative to the repository root (absolute paths
inside the repository work too).
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

# The skill directory is mounted read-only in the sandbox and is statically
# reviewed in the repository, so never leave __pycache__ next to the scripts.
sys.dont_write_bytecode = True
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import gitflow_github as github_api  # noqa: E402

CHECKPOINT_NAMESPACE = "refs/deerflow-checkpoints/"
WORKTREE_DIR = ".worktrees"
WORKTREE_BRANCH_PREFIX = "agent/"
PUSH_ATTEMPTS = 5  # the first try plus up to 4 retries
RETRY_BASE_SECONDS = 2.0
LOCK_ATTEMPTS = 4
GIT_TIMEOUT = 120
NETWORK_TIMEOUT = 300
LIST_LIMIT = 200
CHECKPOINT_IDENTITY = {
    "GIT_AUTHOR_NAME": "DeerFlow checkpoint",
    "GIT_AUTHOR_EMAIL": "checkpoint@deerflow.invalid",
    "GIT_COMMITTER_NAME": "DeerFlow checkpoint",
    "GIT_COMMITTER_EMAIL": "checkpoint@deerflow.invalid",
}

# ---------------------------------------------------------------- redaction

# scheme://userinfo@ -- userinfo of an http(s) URL is always hidden; for other
# schemes only when it carries a password (ssh://git@host stays readable).
_URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/@\s\"']+)@")
_TOKEN_SHAPES_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


def _redact_userinfo(match: re.Match[str]) -> str:
    scheme = match.group("scheme")
    userinfo = match.group("userinfo")
    if scheme.lower().startswith("http") or ":" in userinfo:
        return f"{scheme}***@"
    return match.group(0)


def redact(text: str) -> str:
    """Hide credentials in URLs, token-shaped strings and the live token values."""
    text = _URL_USERINFO_RE.sub(_redact_userinfo, text)
    text = _TOKEN_SHAPES_RE.sub("***", text)
    for name in github_api.TOKEN_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if len(value) >= 8:
            text = text.replace(value, "***")
    return text


def url_has_credentials(url: str) -> bool:
    return redact(url) != url


# ------------------------------------------------------------------ errors


class GitflowError(Exception):
    def __init__(self, message: str, *, hint: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.hint = hint
        self.details = details or {}


_HINTS = (
    (re.compile(r"dubious ownership"), "The checkout belongs to another user. Run: git config --global --add safe.directory <repo path>"),
    (
        re.compile(r"(?i)please tell me who you are|unable to auto-detect email|empty ident"),
        'Set an identity for this repository: git config user.name "Name" && git config user.email "you@example.com" (ask the user which identity to use).',
    ),
    (
        re.compile(r"(?i)could not read username|authentication failed|invalid username or password|returned error: 40[13]|permission denied|403|repository not found"),
        "Authentication or permission failure. Run preflight: a token must be present (the user connects GitHub in DeerFlow) and allow pushing to this repository. Do not put a token in the remote URL.",
    ),
    (re.compile(r"(?i)non-fast-forward|fetch first|stale info"), "The remote branch has commits you do not have. Fetch and rebase onto it (git pull --rebase), resolve conflicts, then push again."),
    (re.compile(r"(?i)protected branch|GH006|GH013"), "The remote refused the update (branch protection or a repository rule). Push to a feature branch and open a pull request."),
)


def _hint_for(text: str) -> str | None:
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return hint
    return None


# ------------------------------------------------------------------ process


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _run(argv: list[str], *, cwd: Path | str, env_extra: dict[str, str] | None = None, input_text: str | None = None, timeout: float = GIT_TIMEOUT) -> Result:
    """Run one fixed argv without a shell. This is the module's only subprocess call."""
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_EDITOR": "true", "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"})
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            env=env,
            input=input_text.encode("utf-8", errors="surrogateescape") if input_text is not None else None,
            capture_output=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        raise GitflowError(f"{argv[0]} is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        return Result(124, "", f"{argv[0]} {argv[1] if len(argv) > 1 else ''}: operation timed out after {int(timeout)}s")
    return Result(proc.returncode, proc.stdout.decode("utf-8", errors="surrogateescape"), proc.stderr.decode("utf-8", errors="surrogateescape"))


_LOCK_ERROR_RE = re.compile(r"(?i)unable to create '[^']*\.lock'|cannot lock ref|index\.lock|another git process seems to be running")


def _git(repo: Path | str, *args: str, check: bool = True, env_extra: dict[str, str] | None = None, input_text: str | None = None, timeout: float = GIT_TIMEOUT) -> Result:
    """Run git in repo. Lock contention from a parallel git process is retried."""
    extra = {"LC_ALL": "C"}
    if env_extra:
        extra.update(env_extra)
    result = Result(1, "", "")
    for attempt in range(1, LOCK_ATTEMPTS + 1):
        result = _run(["git", *args], cwd=repo, env_extra=extra, input_text=input_text, timeout=timeout)
        if result.returncode != 0 and attempt < LOCK_ATTEMPTS and _LOCK_ERROR_RE.search(result.stderr):
            _sleep(0.5 * attempt)
            continue
        break
    if check and result.returncode != 0:
        raise _git_failure(args, result)
    return result


def _git_failure(args: tuple[str, ...] | list[str], result: Result) -> GitflowError:
    stderr = result.stderr.strip() or result.stdout.strip()
    lines = [line for line in stderr.splitlines() if line.strip()]
    # git's advice lines ("hint: ...") follow the actual error; keep the error.
    lines = [line for line in lines if not line.startswith("hint:")] or lines
    summary = " | ".join(lines[-3:]) if lines else f"exit status {result.returncode}"
    return GitflowError(f"git {args[0]} failed: {summary}", hint=_hint_for(stderr), details={"stderr": stderr[-4000:]})


def _out(repo: Path | str, *args: str) -> str:
    return _git(repo, *args).stdout.strip()


_TRANSIENT_RE = re.compile(
    r"(?i)could not resolve host|temporary failure in name resolution|name or service not known|connection (?:timed out|reset|refused|closed)|"
    r"operation timed out|timed out|early eof|rpc failed|remote end hung up unexpectedly|failed to connect|network is unreachable|"
    r"unexpected disconnect|broken pipe|ssl_|gnutls|tls connection|returned error: 5\d\d|http 5\d\d|internal server error|bad gateway|"
    r"service unavailable|gateway time-?out"
)
_PERMANENT_RE = re.compile(r"(?i)authentication failed|permission denied|could not read username|returned error: 4\d\d|repository not found|\[rejected\]|remote rejected|non-fast-forward|protected branch|stale info")


def _is_transient(stderr: str) -> bool:
    return bool(_TRANSIENT_RE.search(stderr)) and not _PERMANENT_RE.search(stderr)


def _git_network(repo: Path | str, *args: str, attempts: int = PUSH_ATTEMPTS) -> tuple[Result, int]:
    """Run a networked git command, retrying transient failures with exponential backoff."""
    result = Result(1, "", "")
    for attempt in range(1, attempts + 1):
        result = _git(repo, *args, check=False, timeout=NETWORK_TIMEOUT)
        if result.returncode == 0 or attempt == attempts or not _is_transient(result.stderr):
            return result, attempt
        _sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
    return result, attempts


# ------------------------------------------------------------- repo facts


def _repo_root(path: str | None) -> Path:
    start = Path(path or os.getcwd()).expanduser()
    if not start.is_dir():
        raise GitflowError(f"{start} is not a directory", hint="Pass --repo with the path of the repository checkout.")
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=start, env_extra={"LC_ALL": "C"})
    if result.returncode != 0:
        stderr = result.stderr.strip()
        hint = _hint_for(stderr) or "cd into the repository (for a clone, /mnt/user-data/workspace/<repo>) or pass --repo DIR."
        raise GitflowError(f"{start} is not inside a git work tree: {stderr.splitlines()[-1] if stderr else 'no repository'}", hint=hint)
    return Path(result.stdout.strip())


def _current_branch(repo: Path) -> str | None:
    result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _rev(repo: Path, ref: str) -> str | None:
    result = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _ref_exists(repo: Path, ref: str) -> bool:
    return _git(repo, "show-ref", "--verify", "--quiet", ref, check=False).returncode == 0


def _remotes(repo: Path) -> list[str]:
    return _out(repo, "remote").split()


def _remote_url(repo: Path, remote: str) -> str | None:
    result = _git(repo, "config", "--get", f"remote.{remote}.url", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _git_path(repo: Path, name: str) -> Path:
    path = Path(_out(repo, "rev-parse", "--git-path", name))
    return path if path.is_absolute() else repo / path


def _git_dir(repo: Path) -> Path:
    return Path(_out(repo, "rev-parse", "--absolute-git-dir"))


def _common_dir(repo: Path) -> Path:
    path = Path(_out(repo, "rev-parse", "--git-common-dir"))
    return (path if path.is_absolute() else repo / path).resolve()


def default_branch(repo: Path, remote: str = "origin") -> tuple[str, str]:
    """Return (branch, source) for the repository's default branch."""
    result = _git(repo, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD", check=False)
    prefix = f"refs/remotes/{remote}/"
    if result.returncode == 0 and result.stdout.strip().startswith(prefix):
        return result.stdout.strip()[len(prefix) :], f"{remote}/HEAD"
    for candidate in ("main", "master"):
        if _ref_exists(repo, f"refs/remotes/{remote}/{candidate}"):
            return candidate, f"{remote}/{candidate}"
    for candidate in ("main", "master"):
        if _ref_exists(repo, f"refs/heads/{candidate}"):
            return candidate, "local branch"
    if _rev(repo, "HEAD") is None:
        unborn = _current_branch(repo)
        if unborn:
            return unborn, "unborn HEAD"
    configured = _git(repo, "config", "--get", "init.defaultBranch", check=False).stdout.strip()
    if configured:
        return configured, "init.defaultBranch"
    return "main", "fallback"


def protected_branches(repo: Path, remote: str = "origin") -> set[str]:
    return {default_branch(repo, remote)[0], "main", "master"}


@dataclass
class Status:
    branch: str | None
    head: str | None
    upstream: str | None
    ahead: int | None
    behind: int | None
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]
    conflicted: list[str]

    @property
    def dirty(self) -> bool:
        return bool(self.staged or self.unstaged or self.untracked or self.conflicted)


def read_status(repo: Path) -> Status:
    raw = _git(repo, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all").stdout
    records = raw.split("\0")
    status = Status(None, None, None, None, None, [], [], [], [])
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        kind = record[0]
        if record.startswith("# "):
            key, _, value = record[2:].partition(" ")
            if key == "branch.oid":
                status.head = None if value == "(initial)" else value
            elif key == "branch.head":
                status.branch = None if value == "(detached)" else value
            elif key == "branch.upstream":
                status.upstream = value
            elif key == "branch.ab":
                match = re.match(r"\+(\d+) -(\d+)", value)
                if match:
                    status.ahead, status.behind = int(match.group(1)), int(match.group(2))
        elif kind in "12":
            fields = record.split(" ", 8 if kind == "1" else 9)
            xy, path = fields[1], fields[-1]
            if kind == "2":
                index += 1  # the rename/copy source path is the next record
            if xy[0] != ".":
                status.staged.append(path)
            if xy[1] != ".":
                status.unstaged.append(path)
        elif kind == "u":
            status.conflicted.append(record.split(" ", 10)[-1])
        elif kind == "?":
            status.untracked.append(record[2:])
    return status


def _operation_in_progress(repo: Path) -> str | None:
    git_dir = _git_dir(repo)
    for marker, name in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect")):
        if (git_dir / marker).exists():
            return name
    return None


def _capped(items: list[str]) -> list[str]:
    return items[:LIST_LIMIT]


def github_repo(repo: Path, remote: str = "origin") -> github_api.RemoteRepo:
    url = _remote_url(repo, remote)
    if not url:
        raise GitflowError(f"remote {remote!r} is not configured", hint=f"Add it: git remote add {remote} <github https url>")
    parsed = github_api.parse_remote_url(url)
    if parsed is None:
        raise GitflowError(f"remote {remote!r} ({redact(url)}) is not a GitHub-style URL", hint="Pull requests need a GitHub remote such as git@github.com:OWNER/REPO.git.")
    return parsed


def _gh_authenticated(host: str, cwd: Path) -> bool:
    if not shutil.which("gh"):
        return False
    return _run(["gh", "auth", "status", "--hostname", host], cwd=cwd, timeout=30).returncode == 0


def _ls_remote_sha(repo: Path, remote: str, branch: str) -> str | None:
    result, _ = _git_network(repo, "ls-remote", remote, f"refs/heads/{branch}", attempts=3)
    if result.returncode != 0:
        raise _git_failure(("ls-remote",), result)
    for line in result.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == f"refs/heads/{branch}":
            return sha.strip()
    return None


def _repo_paths(repo: Path, paths: list[str]) -> list[str]:
    """Normalize user paths to repository-root-relative pathspecs."""
    normalized = []
    real_root = repo.resolve()
    for raw in paths:
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute():
            located = candidate.parent.resolve() / candidate.name if candidate.name else candidate.resolve()
            try:
                rel = located.relative_to(real_root).as_posix()
            except ValueError:
                raise GitflowError(f"path {raw!r} is outside the repository {repo}") from None
        else:
            rel = os.path.normpath(raw).replace(os.sep, "/")
            if rel == ".." or rel.startswith("../"):
                raise GitflowError(f"path {raw!r} is outside the repository (paths are relative to the repository root)")
        normalized.append(rel or ".")
    return normalized


def _read_text(inline: str | None, file_arg: str | None, what: str) -> str:
    if file_arg is not None:
        if file_arg == "-":
            text = sys.stdin.read()
        else:
            try:
                text = Path(file_arg).read_text(encoding="utf-8")
            except OSError as exc:
                raise GitflowError(f"cannot read {what} file {file_arg}: {exc.strerror}") from None
    else:
        text = inline or ""
    return text


# -------------------------------------------------------------- checkpoints


def _temp_index(repo: Path) -> Path:
    git_dir = _git_dir(repo)
    return git_dir / f"deerflow-tmp-index-{os.getpid()}-{time.time_ns()}"


def _drop_temp_index(path: Path) -> None:
    for candidate in (path, Path(f"{path}.lock")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def create_checkpoint(repo: Path, message: str | None) -> dict[str, Any]:
    """Snapshot tracked and untracked (not ignored) files; HEAD and the index are untouched."""
    head = _rev(repo, "HEAD")
    branch = _current_branch(repo)
    tmp_index = _temp_index(repo)
    env = {"GIT_INDEX_FILE": str(tmp_index)}
    try:
        real_index = _git_path(repo, "index")
        copied = False
        if real_index.is_file():
            try:
                shutil.copyfile(real_index, tmp_index)
                copied = True
            except OSError:
                copied = False
        if not copied and head:
            _git(repo, "read-tree", head, env_extra=env)
        _git(repo, "add", "-A", "--", ".", env_extra=env)
        tree = _out_env(repo, env, "write-tree")
    finally:
        _drop_temp_index(tmp_index)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    subject = f"deerflow checkpoint: {message.strip() if message and message.strip() else 'manual'}"
    body = f"{subject}\n\nbranch: {branch or '(detached)'}\nhead: {head or '(none)'}\nworktree: {repo}\ncreated: {stamp}\n"
    identity = {} if _git(repo, "config", "--get", "user.email", check=False).stdout.strip() else dict(CHECKPOINT_IDENTITY)
    commit_args = ["commit-tree", "--no-gpg-sign", tree]
    if head:
        commit_args += ["-p", head]
    commit = _git(repo, *commit_args, input_text=body, env_extra=identity).stdout.strip()
    # Millisecond precision keeps ids in creation order ("latest", newest-first
    # listings) even when a restore makes its safety checkpoint in the same second.
    now_ns = time.time_ns()
    checkpoint_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now_ns // 1_000_000_000)) + f"{now_ns // 1_000_000 % 1000:03d}Z-{commit[:8]}"
    _git(repo, "update-ref", "-m", "deerflow checkpoint", CHECKPOINT_NAMESPACE + checkpoint_id, commit)
    head_tree = _out(repo, "rev-parse", f"{head}^{{tree}}") if head else None
    files = _out(repo, "ls-tree", "-r", "--name-only", "-z", tree).split("\0")
    return {
        "id": checkpoint_id,
        "ref": CHECKPOINT_NAMESPACE + checkpoint_id,
        "commit": commit,
        "tree": tree,
        "head": head,
        "branch": branch,
        "message": subject,
        "files": len([name for name in files if name]),
        "same_as_head": tree == head_tree,
    }


def _out_env(repo: Path, env: dict[str, str], *args: str) -> str:
    return _git(repo, *args, env_extra=env).stdout.strip()


def list_checkpoints(repo: Path) -> list[dict[str, Any]]:
    fmt = "%(refname)%00%(objectname)%00%(creatordate:iso-strict)%00%(contents:subject)%00%(contents:body)%1e"
    raw = _git(repo, "for-each-ref", "--sort=-refname", f"--format={fmt}", CHECKPOINT_NAMESPACE).stdout
    items = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        refname, commit, created, subject, body = (record.split("\0") + [""] * 5)[:5]
        fields = dict(re.findall(r"^(branch|head|worktree): (.*)$", body, re.MULTILINE))
        items.append(
            {
                "id": refname[len(CHECKPOINT_NAMESPACE) :],
                "commit": commit,
                "created": created,
                "message": subject,
                "branch": fields.get("branch"),
                "head": fields.get("head"),
                "worktree": fields.get("worktree"),
            }
        )
    return items


def _resolve_checkpoint(repo: Path, ident: str) -> dict[str, Any]:
    items = list_checkpoints(repo)
    if not items:
        raise GitflowError("there are no checkpoints in this repository", hint="Create one with: gitflow.py checkpoint -m '<what you are about to try>'")
    if ident == "latest":
        return items[0]
    ident = ident[len(CHECKPOINT_NAMESPACE) :] if ident.startswith(CHECKPOINT_NAMESPACE) else ident
    exact = [item for item in items if item["id"] == ident]
    if exact:
        return exact[0]
    matches = [item for item in items if item["id"].startswith(ident) or item["commit"].startswith(ident)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise GitflowError(f"no checkpoint matches {ident!r}", hint="List them with: gitflow.py checkpoints")
    raise GitflowError(f"{ident!r} matches {len(matches)} checkpoints; use the full id", details={"matches": [item["id"] for item in matches]})


def restore_checkpoint(repo: Path, commit: str, paths: list[str], clean: bool) -> tuple[list[str], list[str]]:
    """Write the checkpoint's files into the work tree; optionally delete newer files."""
    tmp_index = _temp_index(repo)
    env = {"GIT_INDEX_FILE": str(tmp_index)}
    try:
        _git(repo, "read-tree", commit, env_extra=env)
        files = [name for name in _git(repo, "ls-files", "-z", "--", *(paths or ["."]), env_extra=env).stdout.split("\0") if name]
        if files:
            _git(repo, "checkout-index", "-f", "-z", "--stdin", input_text="\0".join(files) + "\0", env_extra=env)
    finally:
        _drop_temp_index(tmp_index)
    if paths and not files and not clean:
        raise GitflowError("none of the given paths exist in the checkpoint", hint="Check the names with: git ls-tree -r --name-only <checkpoint commit>")
    deleted: list[str] = []
    if clean:
        keep = set(files)
        current = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *(paths or ["."])).stdout.split("\0")
        for name in sorted({name for name in current if name}):
            if name in keep:
                continue
            target = repo / name
            if target.is_symlink() or target.is_file():
                target.unlink()
                deleted.append(name)
                _prune_empty_dirs(repo, target.parent)
    return files, deleted


def _prune_empty_dirs(repo: Path, directory: Path) -> None:
    root = repo.resolve()
    current = directory
    while current.resolve() != root and root in current.resolve().parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


# ------------------------------------------------------------ secret scan

_SECRET_PATTERNS = (
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
)
# name = "literal" / name: "literal" where the name ends in a credential word.
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9])(?P<key>[A-Za-z0-9_.-]{0,40}?(?:api[_-]?key|secret|passw(?:or)?d|token|credential|auth)s?(?:[_-]?(?:key|value|access[_-]?key))?)"
    r"[\"']?\s*(?::=|=>|=|:)\s*(?P<quote>[\"'])(?P<value>[^\"'\s]{12,})(?P=quote)"
)
_PLACEHOLDER_HINTS = ("example", "sample", "placeholder", "changeme", "change-me", "your", "dummy", "fake", "redacted", "xxxx", "****", "<", "${", "{{", "%(", "$(")
_SENSITIVE_FILE_RE = re.compile(r"^(?:\.env(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)|.+\.(?:pem|key|p12|pfx)|\.netrc|\.pypirc)$", re.IGNORECASE)
_PUBLIC_ENV_SUFFIXES = (".example", ".sample", ".template", ".dist", ".defaults")
ALLOW_MARKER = "pragma: allowlist secret"


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    if any(hint in lowered for hint in _PLACEHOLDER_HINTS):
        return True
    if value.startswith("$") or re.fullmatch(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+", value):
        return True  # an environment variable reference or a variable name such as GITHUB_TOKEN
    return len(set(value)) <= 2


def sensitive_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not _SENSITIVE_FILE_RE.match(name):
        return False
    return not (name.lower().startswith(".env") and name.lower().endswith(_PUBLIC_ENV_SUFFIXES))


def scan_line(text: str) -> str | None:
    """Return the rule name when an added line looks like it carries a secret."""
    if ALLOW_MARKER in text:
        return None
    for rule, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return rule
    for match in _ASSIGNMENT_PATTERN.finditer(text[:4000]):
        if not _is_placeholder(match.group("value")):
            return "hardcoded-credential"
    return None


def _unquote_git_path(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        raw = codecs.escape_decode(path[1:-1].encode("utf-8", errors="surrogateescape"))[0]
        return raw.decode("utf-8", errors="replace")
    return path


def scan_staged(repo: Path) -> list[dict[str, Any]]:
    """Scan the staged (index) diff for secrets: file names and added lines."""
    findings: list[dict[str, Any]] = []
    names = _git(repo, "diff", "--cached", "--name-only", "-z", "--no-renames", "--diff-filter=ACMRT").stdout.split("\0")
    for name in names:
        if name and sensitive_file(name):
            findings.append({"file": name, "line": None, "rule": "sensitive-file"})
    diff = _git(
        repo,
        "-c",
        "core.quotepath=false",
        "diff",
        "--cached",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--unified=0",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--diff-filter=ACMRT",
    ).stdout
    current: str | None = None
    in_header = False
    line_no = 0
    for raw in diff.split("\n"):
        if raw.startswith("diff --git "):
            in_header, current = True, None
            continue
        if in_header:
            if raw.startswith("+++ "):
                target = _unquote_git_path(raw[4:].rstrip("\t"))
                current = target[2:] if target.startswith("b/") else None
            elif raw.startswith("@@"):
                in_header = False
            else:
                continue
        if raw.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            line_no = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and current:
            rule = scan_line(raw[1:])
            if rule:
                findings.append({"file": current, "line": line_no, "rule": rule})
            line_no += 1
        elif raw.startswith(" "):
            line_no += 1
    return findings


# ------------------------------------------------------------- commands


def cmd_preflight(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    status = read_status(repo)
    remote = args.remote
    branch_name, source = default_branch(repo, remote)
    url = _remote_url(repo, remote)
    parsed = github_api.parse_remote_url(url) if url else None
    host = parsed.host if parsed else "github.com"
    gh_installed = shutil.which("gh") is not None
    gh_auth = _gh_authenticated(host, repo) if gh_installed else False
    tokens = github_api.token_env_names_present()
    common = _common_dir(repo)
    warnings = []
    if status.branch is None:
        warnings.append("HEAD is detached: create a branch before committing (gitflow.py branch NAME)")
    elif status.branch in protected_branches(repo, remote):
        warnings.append(f"on protected branch {status.branch!r}: create a work branch before committing (gitflow.py branch NAME)")
    if url and url_has_credentials(url):
        warnings.append(f"remote {remote!r} URL embeds credentials; replace it with a plain URL (git remote set-url {remote} <url without credentials>) and rely on the credential helper")
    operation = _operation_in_progress(repo)
    if operation:
        warnings.append(f"a {operation} is in progress; finish or abort it before other git operations")
    if status.conflicted:
        warnings.append("unresolved merge conflicts are present")
    if parsed and not (gh_auth or tokens):
        warnings.append("no GitHub credentials: gh is not authenticated and neither GH_TOKEN nor GITHUB_TOKEN is set, so push over https and pull requests will fail")
    return {
        "repo_root": str(repo),
        "branch": status.branch,
        "detached": status.branch is None,
        "head": status.head,
        "default_branch": branch_name,
        "default_branch_source": source,
        "on_default_branch": status.branch == branch_name,
        "upstream": status.upstream,
        "ahead": status.ahead,
        "behind": status.behind,
        "dirty": status.dirty,
        "staged": _capped(status.staged),
        "unstaged": _capped(status.unstaged),
        "untracked": _capped(status.untracked),
        "conflicted": _capped(status.conflicted),
        "counts": {"staged": len(status.staged), "unstaged": len(status.unstaged), "untracked": len(status.untracked), "conflicted": len(status.conflicted)},
        "operation_in_progress": operation,
        "remote": remote,
        "remote_url": redact(url) if url else None,
        "remote_url_has_credentials": bool(url and url_has_credentials(url)),
        "github_repo": parsed.slug if parsed else None,
        "github_host": parsed.host if parsed else None,
        "gh": {"installed": gh_installed, "authenticated": gh_auth},
        "token_env": tokens,
        "token_present": bool(tokens),
        "linked_worktree": _git_dir(repo).resolve() != common,
        "checkpoints": len(list_checkpoints(repo)),
        "warnings": warnings,
    }


def _validate_branch_name(repo: Path, name: str) -> None:
    if not name or name.startswith("-") or name.startswith("@"):
        raise GitflowError(f"invalid branch name {name!r}")
    result = _git(repo, "check-ref-format", "--branch", name, check=False)
    if result.returncode != 0 or result.stdout.strip() != name:
        raise GitflowError(f"invalid branch name {name!r}", hint="Use something like feat/short-description or fix/issue-123 (no spaces, '..', '~', '^', ':', '?', '*', '[').")


def _fetch(repo: Path, remote: str) -> tuple[bool, str | None]:
    if remote not in _remotes(repo):
        return False, f"no remote named {remote!r}; using local refs"
    result, _ = _git_network(repo, "fetch", "--prune", "--quiet", remote, attempts=3)
    if result.returncode != 0:
        return False, f"fetch from {remote} failed ({_git_failure(('fetch',), result)}); the base may be stale"
    if not _ref_exists(repo, f"refs/remotes/{remote}/HEAD"):
        # Records the remote's default branch locally so later commands know it.
        _git_network(repo, "remote", "set-head", remote, "--auto", attempts=2)
    return True, None


def _resolve_base(repo: Path, remote: str, from_ref: str | None) -> tuple[str, str]:
    if from_ref:
        sha = _rev(repo, from_ref)
        if not sha:
            raise GitflowError(f"base {from_ref!r} does not name a commit", hint="Fetch first or pass an existing branch, tag or sha to --from.")
        return from_ref, sha
    name, _ = default_branch(repo, remote)
    for candidate in (f"{remote}/{name}", name):
        sha = _rev(repo, candidate)
        if sha:
            return candidate, sha
    raise GitflowError(f"cannot find the default branch {name!r} locally or on {remote}", hint="Pass --from REF, or make an initial commit first.")


def cmd_branch(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    name = args.name
    _validate_branch_name(repo, name)
    remote = args.remote
    fetched, fetch_warning = _fetch(repo, remote)
    if name in protected_branches(repo, remote):
        raise GitflowError(f"{name!r} is a protected branch; work on a feature branch", hint="Pick a name such as feat/<topic> or fix/<topic>.")
    warnings = [fetch_warning] if fetch_warning else []
    carried = read_status(repo)
    carried_changes = sorted(set(carried.staged + carried.unstaged))
    base_ref, base_sha = None, None
    if _ref_exists(repo, f"refs/heads/{name}"):
        created, source = False, "existing local branch"
        if _current_branch(repo) != name:
            _git(repo, "switch", name)
    elif _ref_exists(repo, f"refs/remotes/{remote}/{name}"):
        created, source = True, f"{remote}/{name}"
        base_ref, base_sha = f"{remote}/{name}", _rev(repo, f"{remote}/{name}")
        _git(repo, "switch", "-c", name, "--track", f"{remote}/{name}")
    else:
        base_ref, base_sha = _resolve_base(repo, remote, args.from_ref)
        created, source = True, "new branch"
        _git(repo, "switch", "--no-track", "-c", name, base_sha)
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    return {
        "branch": _current_branch(repo),
        "created": created,
        "source": source,
        "base": base_ref,
        "base_sha": base_sha,
        "head": _rev(repo, "HEAD"),
        "fetched": fetched,
        "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "carried_changes": _capped(carried_changes),
        "warnings": warnings,
    }


def cmd_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    return create_checkpoint(repo, args.message)


def cmd_checkpoints(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    items = list_checkpoints(repo)
    return {"count": len(items), "checkpoints": items[: args.limit]}


def cmd_restore(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    target = _resolve_checkpoint(repo, args.id)
    paths = _repo_paths(repo, args.paths or [])
    safety = create_checkpoint(repo, f"before restore of {target['id']}")
    restored, deleted = restore_checkpoint(repo, target["commit"], paths, args.clean)
    return {
        "id": target["id"],
        "commit": target["commit"],
        "paths": paths,
        "restored": _capped(restored),
        "restored_count": len(restored),
        "deleted": _capped(deleted),
        "deleted_count": len(deleted),
        "safety_checkpoint": safety["id"],
        "note": "HEAD and the index are unchanged; restored files show up as working-tree changes. Undo with: restore " + safety["id"] + (" --clean" if args.clean else ""),
    }


def _staged_names(repo: Path, paths: list[str] | None = None) -> list[str]:
    args = ["diff", "--cached", "--name-only", "-z", "--no-renames"]
    if paths:
        args += ["--", *paths]
    return [name for name in _git(repo, *args).stdout.split("\0") if name]


def _shortstat(repo: Path, sha: str) -> dict[str, Any]:
    text = _out(repo, "show", "--shortstat", "--format=", sha)
    numbers = {key: 0 for key in ("files_changed", "insertions", "deletions")}
    for count, word in re.findall(r"(\d+) (file|insertion|deletion)", text):
        numbers[{"file": "files_changed", "insertion": "insertions", "deletion": "deletions"}[word]] = int(count)
    return {"shortstat": text.strip(), **numbers}


def cmd_commit(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    message = "\n\n".join(args.message) if args.message else _read_text(None, args.message_file, "message")
    if not message.strip():
        raise GitflowError("the commit message is empty")
    branch = _current_branch(repo)
    if branch is None:
        raise GitflowError("HEAD is detached; commits made here are easy to lose", hint="Create a branch first: gitflow.py branch NAME")
    if branch in protected_branches(repo) and not args.allow_default_branch:
        raise GitflowError(f"refusing to commit on protected branch {branch!r}", hint="Create a work branch first (gitflow.py branch feat/<topic>); pass --allow-default-branch only when the user asked for a commit on this branch.")
    if _operation_in_progress(repo) in ("rebase", "cherry-pick", "revert", "bisect"):
        raise GitflowError("a rebase, cherry-pick, revert or bisect is in progress", hint="Finish or abort it with git before committing.")
    status = read_status(repo)
    if status.conflicted:
        raise GitflowError("unresolved merge conflicts", hint="Resolve them, then include the files in --paths.", details={"conflicted": status.conflicted})
    paths = _repo_paths(repo, args.paths or [])
    if args.paths is not None and not paths:
        raise GitflowError("--paths needs at least one path")
    if paths:
        inside = set(_staged_names(repo, paths))
        outside = [name for name in _staged_names(repo) if name not in inside]
        if outside:
            raise GitflowError(
                "other changes are already staged outside --paths and would be committed too",
                hint="Add them to --paths, or unstage them with: git restore --staged <file>",
                details={"staged_outside_paths": _capped(outside)},
            )
    saved_index = None
    if paths or args.all:
        saved = _git(repo, "write-tree", check=False)
        saved_index = saved.stdout.strip() if saved.returncode == 0 else None
    try:
        if paths or args.all:
            # A failing add (an ignored path, say) can stage some paths before it stops.
            _git(repo, "add", "-A", "--", *(paths or ["."]))
        staged = _staged_names(repo)
        if not staged:
            raise GitflowError("nothing to commit: no staged changes", hint="Pass --paths with the files you changed, or --all. Check them with preflight.")
        findings = scan_staged(repo)
        if findings:
            where = ", ".join(f"{item['file']}:{item['line']}" if item["line"] else item["file"] for item in findings[:20])
            raise GitflowError(
                f"refusing to commit: possible secrets in staged changes: {where}",
                hint=f"Remove the secret (load it from an environment variable instead) or drop the file from the commit. A verified fake value in a test may carry the marker '{ALLOW_MARKER}' on its line; tell the user.",
                details={"findings": findings},
            )
        # The message travels on stdin, so no quoting can mangle it.
        _git(repo, "commit", "--quiet", "-F", "-", input_text=message if message.endswith("\n") else message + "\n")
    except GitflowError as exc:
        if saved_index:
            _git(repo, "read-tree", saved_index, check=False)
            _git(repo, "update-index", "-q", "--refresh", check=False)
            exc.details["index_restored"] = True
        raise
    sha = _out(repo, "rev-parse", "HEAD")
    subject = message.strip().splitlines()[0]
    warnings = []
    if len(subject) > 72:
        warnings.append(f"subject is {len(subject)} characters; keep it under 72")
    return {
        "sha": sha,
        "short_sha": sha[:12],
        "branch": branch,
        "subject": subject,
        "files": _capped(staged),
        **_shortstat(repo, sha),
        "warnings": warnings,
    }


def _git_version(repo: Path) -> tuple[int, int]:
    match = re.search(r"(\d+)\.(\d+)", _out(repo, "version"))
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def cmd_push(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    remote = args.remote
    branch = _current_branch(repo)
    if branch is None:
        raise GitflowError("HEAD is detached; nothing to push", hint="Create a branch first: gitflow.py branch NAME")
    if branch in protected_branches(repo, remote):
        raise GitflowError(f"refusing to push protected branch {branch!r}", hint="Push a feature branch and open a pull request.")
    if remote not in _remotes(repo):
        raise GitflowError(f"remote {remote!r} is not configured")
    head = _rev(repo, "HEAD")
    if head is None:
        raise GitflowError("the branch has no commits yet", hint="Commit first: gitflow.py commit -m '...' --paths <files>")
    url = _git(repo, "remote", "get-url", "--push", remote, check=False).stdout.strip()
    warnings = []
    if url_has_credentials(url):
        warnings.append(f"remote {remote!r} URL embeds credentials; replace it with a plain URL and rely on the credential helper")
    push_args = ["push", "--porcelain", "-u"]
    if args.force_with_lease:
        push_args.append(f"--force-with-lease=refs/heads/{branch}")
        if _git_version(repo) >= (2, 30):
            push_args.append("--force-if-includes")
    push_args += [remote, f"refs/heads/{branch}:refs/heads/{branch}"]
    result, attempts = _git_network(repo, *push_args)
    flag, summary = None, None
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[1].endswith(f":refs/heads/{branch}"):
            flag, summary = parts[0].strip() or " ", parts[2].strip()
    if result.returncode != 0:
        error = _git_failure(("push",), Result(result.returncode, result.stdout, result.stderr + ("\n" + summary if summary else "")))
        error.details.update({"attempts": attempts, "remote_url": redact(url)})
        raise error
    remote_sha = _ls_remote_sha(repo, remote, branch)
    if remote_sha != head:
        raise GitflowError(
            f"push reported success but {remote}/{branch} is at {remote_sha or 'nothing'}, not local HEAD {head}",
            hint="Do not report the push as done. Re-run push, then check with: git ls-remote " + remote + " refs/heads/" + branch,
            details={"local_sha": head, "remote_sha": remote_sha},
        )
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    parsed = github_api.parse_remote_url(url) if url else None
    return {
        "remote": remote,
        "remote_url": redact(url),
        "branch": branch,
        "local_sha": head,
        "remote_sha": remote_sha,
        "verified": True,
        "result": {"*": "new branch", "+": "forced update", " ": "fast-forward", "=": "up to date"}.get(flag or "", summary or "pushed"),
        "forced": flag == "+",
        "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "attempts": attempts,
        "new_pull_request_url": github_api.new_pull_url(parsed, branch) if parsed else None,
        "warnings": warnings,
    }


class GhTransport:
    """GitHub REST through gh api, which brings its own authentication."""

    def __init__(self, host: str, cwd: Path) -> None:
        self.host = host
        self.cwd = cwd

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> tuple[int, Any]:
        endpoint = path.lstrip("/")
        if query:
            endpoint += "?" + "&".join(f"{key}={_quote_query(value)}" for key, value in query.items())
        argv = ["gh", "api", "--include", "--method", method, "-H", "Accept: application/vnd.github+json", endpoint]
        if self.host != "github.com":
            argv += ["--hostname", self.host]
        payload = None
        if body is not None:
            argv += ["--input", "-"]
            payload = json.dumps(body)
        result = _run(argv, cwd=self.cwd, input_text=payload, timeout=90)
        status, data = parse_gh_include(result.stdout)
        if status is None:
            transient = _is_transient(result.stderr)
            raise github_api.GitHubError(f"gh api {method} {path} failed: {result.stderr.strip()[-500:] or 'no output'}", transient=transient)
        return status, data


def _quote_query(value: str) -> str:
    return quote(str(value), safe=":/")


def parse_gh_include(output: str) -> tuple[int | None, Any]:
    """Split gh api --include output into (HTTP status, decoded JSON body)."""
    status = None
    rest = output
    while True:
        match = re.match(r"HTTP/[\d.]+ (\d{3})[^\n]*\n", rest)
        if not match:
            break
        status = int(match.group(1))
        split = re.search(r"\r?\n\r?\n", rest)
        rest = rest[split.end() :] if split else ""
    if status is None:
        return None, None
    body = rest.strip()
    if not body:
        return status, None
    try:
        return status, json.loads(body)
    except ValueError:
        return status, {"message": body[:300]}


def _transport(repo: Path, gh_repo: github_api.RemoteRepo) -> tuple[Any, str]:
    if _gh_authenticated(gh_repo.host, repo):
        return GhTransport(gh_repo.host, repo), "gh"
    _, value = github_api.token_from_env()
    if value:
        return github_api.RestTransport(gh_repo.host, value), "rest"
    raise GitflowError(
        "no GitHub credentials: gh is missing or not authenticated, and neither GH_TOKEN nor GITHUB_TOKEN is set",
        hint="Ask the user to connect GitHub (or configure a token for the sandbox). Never ask them to paste a token into chat.",
    )


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except github_api.GitHubError as exc:
        message = str(exc)
        raise GitflowError(message, hint=_hint_for(message) if exc.status in (401, 403, 404) else None, details={"status": exc.status}) from None


def cmd_pr_create(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    remote = args.remote
    branch = _current_branch(repo)
    if branch is None:
        raise GitflowError("HEAD is detached", hint="Switch to the branch you pushed.")
    if branch in protected_branches(repo, remote):
        raise GitflowError(f"the current branch {branch!r} is protected; a pull request needs a feature branch as its head")
    title = args.title.strip()
    if not title:
        raise GitflowError("the pull request title is empty")
    body = _read_text(args.body, args.body_file, "body")
    gh_repo = github_repo(repo, remote)
    base = args.base or default_branch(repo, remote)[0]
    if base == branch:
        raise GitflowError(f"base and head are both {branch!r}")
    head = _rev(repo, "HEAD")
    remote_sha = _ls_remote_sha(repo, remote, branch)
    if remote_sha is None:
        raise GitflowError(f"branch {branch!r} is not on {remote}", hint="Push it first: gitflow.py push")
    warnings = []
    if remote_sha != head:
        warnings.append(f"{remote}/{branch} is at {remote_sha[:12]} but local HEAD is {head[:12] if head else None}; push to update the pull request")
    transport, via = _transport(repo, gh_repo)
    pull, created = _call(github_api.create_pull, transport, gh_repo, title=title, body=body, head=branch, base=base, draft=args.draft)
    summary = github_api.summarize_pull(pull)
    if not created:
        warnings.append("an open pull request for this branch already existed; it was returned unchanged (title and body were not edited)")
        if summary["base"] != base:
            warnings.append(f"the existing pull request targets {summary['base']!r}, not {base!r}")
    return {
        "created": created,
        "via": via,
        "repository": gh_repo.slug,
        **summary,
        "head_matches_remote": summary["head_sha"] == remote_sha,
        "head_matches_local": summary["head_sha"] == head,
        "warnings": warnings,
    }


def cmd_pr_status(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    remote = args.remote
    gh_repo = github_repo(repo, remote)
    transport, via = _transport(repo, gh_repo)
    if args.number:
        pull = _call(github_api.get_pull, transport, gh_repo, args.number)
    else:
        branch = _current_branch(repo)
        if branch is None:
            raise GitflowError("HEAD is detached; pass --number")
        found = _call(github_api.find_pulls, transport, gh_repo, branch) or _call(github_api.find_pulls, transport, gh_repo, branch, state="all")
        if not found:
            raise GitflowError(f"no pull request found for branch {branch!r} in {gh_repo.slug}", hint="Create one with: gitflow.py pr create --title ... --body-file ...")
        pull = _call(github_api.get_pull, transport, gh_repo, int(found[0]["number"]))
    summary = github_api.summarize_pull(pull)
    checks = _call(github_api.check_summary, transport, gh_repo, summary["head_sha"]) if summary["head_sha"] else None
    reviews = _call(github_api.review_summary, transport, gh_repo, int(summary["number"]))
    head = _rev(repo, "HEAD")
    notes = []
    if summary["mergeable"] is None and summary["state"] == "open":
        notes.append("GitHub has not finished computing mergeability; run pr status again shortly")
    if summary["head_sha"] and head and summary["head_sha"] != head and summary["head"] == _current_branch(repo):
        notes.append("the pull request head differs from local HEAD; push to update it, or the checks below are for an older commit")
    return {"via": via, "repository": gh_repo.slug, **summary, "head_matches_local": summary["head_sha"] == head, "checks": checks, "reviews": reviews, "notes": notes}


_WORKTREE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _main_root(repo: Path) -> tuple[Path, Path]:
    common = _common_dir(repo)
    if common.name != ".git":
        raise GitflowError("worktrees need a non-bare repository whose git directory is .git")
    return common.parent, common


def _ensure_excluded(common: Path, pattern: str) -> bool:
    exclude = common / "info" / "exclude"
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if pattern in existing.splitlines():
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(("" if not existing or existing.endswith("\n") else "\n") + pattern + "\n")
    return True


def _worktrees(repo: Path) -> list[dict[str, Any]]:
    raw = _out(repo, "worktree", "list", "--porcelain")
    items: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        item: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                item["path"] = value
            elif key == "HEAD":
                item["head"] = value
            elif key == "branch":
                item["branch"] = value.removeprefix("refs/heads/")
            elif key in ("detached", "bare", "locked", "prunable"):
                item[key] = True
        if item.get("path"):
            items.append(item)
    return items


def _worktree_target(repo: Path, name: str) -> tuple[Path, Path, Path, str]:
    if not _WORKTREE_NAME_RE.fullmatch(name) or name.endswith(".lock") or ".." in name:
        raise GitflowError(f"invalid worktree name {name!r}", hint="Use letters, digits, '.', '_' or '-', e.g. api-tests.")
    root, common = _main_root(repo)
    return root, common, root / WORKTREE_DIR / name, WORKTREE_BRANCH_PREFIX + name


def _same_path(left: str | Path, right: Path) -> bool:
    return Path(left).resolve() == right.resolve()


def cmd_worktree_add(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    root, common, path, branch = _worktree_target(repo, args.name)
    _validate_branch_name(repo, branch)
    excluded = _ensure_excluded(common, f"/{WORKTREE_DIR}/")
    for item in _worktrees(root):
        if _same_path(item["path"], path):
            return {"name": args.name, "path": str(path), "branch": item.get("branch"), "head": item.get("head"), "created": False, "exclude_added": excluded, "warnings": []}
    if path.exists():
        raise GitflowError(f"{path} exists but is not a registered worktree", hint="Pick another name, or remove the directory after checking its contents.")
    fetched, fetch_warning = _fetch(root, args.remote)
    warnings = [fetch_warning] if fetch_warning else []
    base_ref, base_sha = None, None
    if _ref_exists(root, f"refs/heads/{branch}"):
        _git(root, "worktree", "add", str(path), branch)
    else:
        base_ref, base_sha = _resolve_base(root, args.remote, args.from_ref)
        _git(root, "branch", "--no-track", branch, base_sha)
        _git(root, "worktree", "add", str(path), branch)
    return {
        "name": args.name,
        "path": str(path),
        "branch": branch,
        "base": base_ref,
        "base_sha": base_sha,
        "head": _rev(path, "HEAD"),
        "created": True,
        "fetched": fetched,
        "exclude_added": excluded,
        "warnings": warnings,
    }


def cmd_worktree_remove(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    root, _, path, branch = _worktree_target(repo, args.name)
    if not any(_same_path(item["path"], path) for item in _worktrees(root)):
        raise GitflowError(f"no worktree named {args.name!r} at {path}", hint="List them with: gitflow.py worktree list")
    if path.resolve() == repo.resolve() or path.resolve() in Path.cwd().resolve().parents or path.resolve() == Path.cwd().resolve():
        raise GitflowError("cannot remove the worktree you are running in", hint="Run this from the main checkout (pass --repo).")
    checkpoint = None
    if path.is_dir() and read_status(path).dirty:
        if not args.force:
            raise GitflowError(f"worktree {args.name!r} has uncommitted changes", hint="Commit and push them, or pass --force (a checkpoint of the changes is saved first).")
        checkpoint = create_checkpoint(path, f"before removing worktree {args.name}")["id"]
    remove_args = ["worktree", "remove"] + (["--force"] if args.force else []) + [str(path)]
    _git(root, *remove_args)
    _git(root, "worktree", "prune", check=False)
    warnings = []
    branch_deleted = False
    if args.delete_branch:
        deleted = _git(root, "branch", "-d", branch, check=False)
        branch_deleted = deleted.returncode == 0
        if not branch_deleted:
            warnings.append(f"kept branch {branch!r}: it is not merged (git branch -D deletes it; push it first if the work matters)")
    return {"name": args.name, "path": str(path), "removed": not path.exists(), "branch": branch, "branch_deleted": branch_deleted, "checkpoint": checkpoint, "warnings": warnings}


def cmd_worktree_list(args: argparse.Namespace) -> dict[str, Any]:
    repo = _repo_root(args.repo)
    root, _ = _main_root(repo)
    agent_dir = (root / WORKTREE_DIR).resolve()
    items = []
    for item in _worktrees(root):
        path = Path(item["path"])
        agent = path.resolve().parent == agent_dir
        entry = {"path": item["path"], "branch": item.get("branch"), "head": item.get("head"), "agent": agent, "name": path.name if agent else None}
        for flag in ("detached", "locked", "prunable"):
            entry[flag] = bool(item.get(flag))
        entry["dirty"] = read_status(path).dirty if agent and path.is_dir() else None
        items.append(entry)
    return {"main_root": str(root), "worktrees": items}


# ------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", help="repository directory (default: the current directory)")
    parser = argparse.ArgumentParser(prog="gitflow.py", description="Reliable git and pull-request primitives with JSON output.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight", parents=[common], help="report repository, branch and auth facts")
    p.add_argument("--remote", default="origin")
    p.set_defaults(func=cmd_preflight, name_="preflight")

    p = sub.add_parser("branch", parents=[common], help="create or switch to a work branch from a fresh base")
    p.add_argument("name")
    p.add_argument("--from", dest="from_ref", help="base ref (default: <remote>/<default branch>)")
    p.add_argument("--remote", default="origin")
    p.set_defaults(func=cmd_branch, name_="branch")

    p = sub.add_parser("checkpoint", parents=[common], help="snapshot the working tree, including untracked files")
    p.add_argument("-m", "--message", help="what the checkpoint is for")
    p.set_defaults(func=cmd_checkpoint, name_="checkpoint")

    p = sub.add_parser("checkpoints", parents=[common], help="list checkpoints, newest first")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_checkpoints, name_="checkpoints")

    p = sub.add_parser("restore", parents=[common], help="restore files from a checkpoint (HEAD and index untouched)")
    p.add_argument("id", help="checkpoint id, unique prefix, or 'latest'")
    p.add_argument("--paths", nargs="+", help="restore only these paths (relative to the repository root)")
    p.add_argument("--clean", action="store_true", help="also delete non-ignored files that are not in the checkpoint")
    p.set_defaults(func=cmd_restore, name_="restore")

    p = sub.add_parser("commit", parents=[common], help="stage, scan for secrets and commit")
    message = p.add_mutually_exclusive_group(required=True)
    message.add_argument("-m", "--message", action="append", help="message; repeat for more paragraphs")
    message.add_argument("--message-file", help="read the message from a file ('-' for stdin)")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--paths", nargs="+", help="stage and commit only these paths (relative to the repository root)")
    scope.add_argument("--all", action="store_true", help="stage every change, including new files")
    p.add_argument("--allow-default-branch", action="store_true", help="permit a commit on the default branch")
    p.set_defaults(func=cmd_commit, name_="commit")

    p = sub.add_parser("push", parents=[common], help="push the current branch and verify the remote ref")
    p.add_argument("--remote", default="origin")
    p.add_argument("--force-with-lease", action="store_true", help="allow rewriting the remote branch if nobody else moved it")
    p.set_defaults(func=cmd_push, name_="push")

    pr = sub.add_parser("pr", help="pull requests")
    pr_sub = pr.add_subparsers(dest="pr_command", required=True)
    p = pr_sub.add_parser("create", parents=[common], help="open a pull request (or return the open one)")
    p.add_argument("--title", required=True)
    body = p.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", help="read the body from a file ('-' for stdin)")
    p.add_argument("--base", help="target branch (default: the default branch)")
    p.add_argument("--draft", action="store_true")
    p.add_argument("--remote", default="origin")
    p.set_defaults(func=cmd_pr_create, name_="pr create")
    p = pr_sub.add_parser("status", parents=[common], help="state, mergeability, reviews and checks")
    p.add_argument("--number", type=int)
    p.add_argument("--remote", default="origin")
    p.set_defaults(func=cmd_pr_status, name_="pr status")

    wt = sub.add_parser("worktree", help="isolated checkouts for parallel agents")
    wt_sub = wt.add_subparsers(dest="worktree_command", required=True)
    p = wt_sub.add_parser("add", parents=[common], help="create .worktrees/NAME on branch agent/NAME")
    p.add_argument("name")
    p.add_argument("--from", dest="from_ref")
    p.add_argument("--remote", default="origin")
    p.set_defaults(func=cmd_worktree_add, name_="worktree add")
    p = wt_sub.add_parser("remove", parents=[common], help="remove .worktrees/NAME")
    p.add_argument("name")
    p.add_argument("--force", action="store_true", help="discard uncommitted changes (checkpointed first)")
    p.add_argument("--delete-branch", action="store_true", help="also delete agent/NAME when it is merged")
    p.set_defaults(func=cmd_worktree_remove, name_="worktree remove")
    p = wt_sub.add_parser("list", parents=[common], help="list worktrees")
    p.set_defaults(func=cmd_worktree_list, name_="worktree list")
    return parser


def _emit(stream: Any, payload: dict[str, Any]) -> None:
    stream.write(redact(json.dumps(payload, indent=2, ensure_ascii=False)) + "\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    command = args.name_
    try:
        payload = args.func(args)
    except GitflowError as exc:
        error = {"ok": False, "command": command, "error": str(exc)}
        if exc.hint:
            error["hint"] = exc.hint
        error.update(exc.details)
        _emit(sys.stdout, error)
        sys.stderr.write(redact(f"gitflow {command}: error: {exc}") + "\n")
        if exc.hint:
            sys.stderr.write(redact(f"hint: {exc.hint}") + "\n")
        return 1
    _emit(sys.stdout, {"ok": True, "command": command, **payload})
    return 0


if __name__ == "__main__":
    sys.exit(main())
