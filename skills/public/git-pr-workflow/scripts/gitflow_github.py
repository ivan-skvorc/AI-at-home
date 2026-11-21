#!/usr/bin/env python3
"""GitHub REST client for gitflow.sh: urllib only, it starts no processes.

gitflow.sh calls it for everything that talks to the GitHub API:

    gitflow_github.py parse-remote URL        -> "host<TAB>owner<TAB>name", exit 1 if not GitHub-style
    gitflow_github.py token-names [--host H]  -> names of the token variables that are set (usable for H)
    gitflow_github.py new-pull-url --host H --owner O --repo R --branch B
    gitflow_github.py pr-create --host H --owner O --repo R --head B --base B --title T --body-file F
                      [--draft] --remote-sha S --local-sha S [--warning W ...] [--auth-from-stdin] [--api-url U]
    gitflow_github.py pr-status --host H --owner O --repo R (--number N | --branch B) --local-sha S
                      [--auth-from-stdin] [--api-url U]

pr-create and pr-status print one JSON object (the gitflow.sh output contract),
also when something unexpected fails.

Credentials are read by name, never in bulk. GH_TOKEN and GITHUB_TOKEN are
github.com credentials and are used only when the repository's host is
github.com. Another host gets GH_ENTERPRISE_TOKEN or GITHUB_ENTERPRISE_TOKEN,
and only when the operator lists it in GITFLOW_GITHUB_HOSTS (or names it in
GH_HOST). gitflow.sh can instead pipe in the credentials of a gh that is logged
in to that host. The token is sent only in the Authorization header, to the API
of the repository's own host (or to --api-url, which must be https, or plain
http on the loopback interface for tests); a redirect to any other origin drops
it. It never appears in a URL, a log line or the output.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

sys.dont_write_bytecode = True  # the skill directory is read-only and statically reviewed
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import gitflow_json  # noqa: E402

TOKEN_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")  # github.com only
ENTERPRISE_TOKEN_ENV_NAMES = ("GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")  # listed hosts only
ALLOWED_HOSTS_ENV = "GITFLOW_GITHUB_HOSTS"
PUBLIC_HOST = "github.com"
USER_AGENT = "deerflow-gitflow/1.0"
API_VERSION = "2022-11-28"
GET_ATTEMPTS = 3
RETRY_BASE_SECONDS = 1.0

# https://host/owner/repo(.git), ssh://user@host:port/owner/repo(.git), git://host/owner/repo(.git)
_URL_REMOTE_RE = re.compile(r"^(?:https?|ssh|git)://(?:[^@/]*@)?(?P<host>[^/:@]+)(?::\d+)?/(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$", re.IGNORECASE)
# user@host:owner/repo(.git) -- the scp-like form ssh remotes use
_SCP_REMOTE_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^/:@]+):(?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$")
_FAILING_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
_PASSING_CONCLUSIONS = {"success", "neutral", "skipped"}


class GitHubError(Exception):
    """A GitHub API call failed; the message is safe to print."""

    def __init__(self, message: str, *, status: int | None = None, transient: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient


class Transport(Protocol):
    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> tuple[int, Any]: ...


@dataclass(frozen=True)
class RemoteRepo:
    host: str
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_remote_url(url: str) -> RemoteRepo | None:
    """Return the GitHub-style host/owner/name of a remote URL, or None for local paths."""
    url = url.strip()
    match = _URL_REMOTE_RE.match(url) or _SCP_REMOTE_RE.match(url)
    if not match:
        return None
    host = match.group("host").lower()
    if host == "ssh.github.com":
        host = "github.com"
    return RemoteRepo(host=host, owner=match.group("owner"), name=match.group("name"))


def api_base(host: str) -> str:
    if host == "github.com":
        return "https://api.github.com"
    return f"https://{host}/api/v3"


def resolve_api_base(host: str, override: str | None) -> str:
    """The API root for host, or a validated override (https, or loopback for tests)."""
    if not override:
        return api_base(host)
    parts = urllib.parse.urlsplit(override)
    if parts.scheme == "https" and parts.hostname:
        return override.rstrip("/")
    if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"):
        return override.rstrip("/")
    raise GitHubError("the API URL override must use https (plain http is allowed only on the loopback interface)")


def web_url(repo: RemoteRepo, path: str = "") -> str:
    return f"https://{repo.host}/{repo.owner}/{repo.name}{path}"


def new_pull_url(repo: RemoteRepo, branch: str) -> str:
    return web_url(repo, "/pull/new/" + urllib.parse.quote(branch, safe="/"))


def enterprise_hosts() -> set[str]:
    """Hosts other than github.com that the operator allows to receive an enterprise token."""
    raw = (os.getenv(ALLOWED_HOSTS_ENV) or "").replace(",", " ")
    hosts = {host.strip().lower() for host in raw.split() if host.strip()}
    gh_host = (os.getenv("GH_HOST") or "").strip().lower()
    if gh_host and gh_host != PUBLIC_HOST:
        hosts.add(gh_host)
    return hosts


def token_names_for_host(host: str) -> tuple[str, ...]:
    host = host.lower()
    if host == PUBLIC_HOST:
        return TOKEN_ENV_NAMES
    if host in enterprise_hosts():
        return ENTERPRISE_TOKEN_ENV_NAMES
    return ()


def auth_for_host(host: str) -> tuple[str | None, str | None]:
    """Return (variable name, value) of the first token variable this host may receive."""
    for name in token_names_for_host(host):
        value = (os.getenv(name) or "").strip()
        if value:
            return name, value
    return None, None


def token_env_names_present(host: str | None = None) -> list[str]:
    names = token_names_for_host(host) if host else TOKEN_ENV_NAMES + ENTERPRISE_TOKEN_ENV_NAMES
    return [name for name in names if (os.getenv(name) or "").strip()]


def missing_credentials_message(host: str) -> str:
    if host.lower() == PUBLIC_HOST:
        return "no GitHub credentials found (gh is missing or not logged in, and neither GH_TOKEN nor GITHUB_TOKEN is set)"
    return f"no GitHub credentials found for {host}: GH_TOKEN and GITHUB_TOKEN are only sent to github.com. For a GitHub Enterprise host, list it in {ALLOWED_HOSTS_ENV} and set GH_ENTERPRISE_TOKEN, or log gh in to it"


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or {"https": 443, "http": 80}.get(scheme)


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but keep the token on the origin it was meant for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(new.full_url) != _origin(req.full_url):
            new.remove_header("Authorization")
        return new


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_SameOriginRedirectHandler())


def _decode_json(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {"message": raw[:300].decode("utf-8", errors="replace")}


def api_error_message(status: int | None, data: Any) -> str:
    message = ""
    if isinstance(data, dict):
        message = str(data.get("message") or "")
        details = []
        for item in data.get("errors") or []:
            if isinstance(item, dict):
                details.append(str(item.get("message") or item.get("code") or ""))
            else:
                details.append(str(item))
        details = [detail for detail in details if detail]
        if details:
            message = f"{message}: {'; '.join(details)}" if message else "; ".join(details)
    prefix = f"GitHub API HTTP {status}" if status else "GitHub API error"
    return f"{prefix}: {message}" if message else prefix


class RestTransport:
    """GitHub REST over urllib, authenticated with a token from the environment."""

    def __init__(self, host: str, auth_value: str, *, base: str | None = None, timeout: float = 30.0) -> None:
        self.host = host
        self.base = base or api_base(host)
        self._auth_value = auth_value
        self.timeout = timeout
        self._opener = _build_opener()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, query: dict[str, str] | None = None) -> tuple[int, Any]:
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
            "Authorization": "Bearer " + self._auth_value,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        # Only reads are retried: a retried POST could open a second pull request.
        attempts = GET_ATTEMPTS if method == "GET" else 1
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return int(response.status), _decode_json(response.read())
            except urllib.error.HTTPError as exc:
                try:
                    raw = exc.read()
                except OSError:
                    raw = b""
                if exc.code >= 500 and attempt < attempts:
                    time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
                    continue
                return int(exc.code), _decode_json(raw)
            except (http.client.HTTPException, OSError) as exc:
                # URLError, timeouts, resets, TLS errors and a response cut short
                # (IncompleteRead, BadStatusLine) all mean: the outcome is unknown.
                if attempt < attempts:
                    time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
                    continue
                reason = getattr(exc, "reason", None) or f"{type(exc).__name__}: {exc}"
                raise GitHubError(f"network error talking to {self.host}: {reason}", transient=True) from None
        raise GitHubError(f"no response from {self.host}", transient=True)


def _expect(status: int, data: Any, *expected: int) -> Any:
    if status not in expected:
        raise GitHubError(api_error_message(status, data), status=status)
    return data


def find_pulls(transport: Transport, repo: RemoteRepo, branch: str, *, state: str = "open") -> list[dict[str, Any]]:
    """Pull requests whose head is owner:branch in this repository, newest first."""
    query = {"head": f"{repo.owner}:{branch}", "state": state, "per_page": "20", "sort": "created", "direction": "desc"}
    status, data = transport.request("GET", f"/repos/{repo.owner}/{repo.name}/pulls", query=query)
    data = _expect(status, data, 200)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def get_pull(transport: Transport, repo: RemoteRepo, number: int) -> dict[str, Any]:
    status, data = transport.request("GET", f"/repos/{repo.owner}/{repo.name}/pulls/{int(number)}")
    data = _expect(status, data, 200)
    if not isinstance(data, dict) or "number" not in data:
        raise GitHubError(f"unexpected response reading pull request #{number}")
    return data


def create_pull(transport: Transport, repo: RemoteRepo, *, title: str, body: str, head: str, base: str, draft: bool) -> tuple[dict[str, Any], bool]:
    """Open a pull request, or return the open one this head branch already has.

    Returns (pull, created); pull is read back from the API, not taken from
    the create response, so the caller reports what GitHub actually stores.
    """
    existing = find_pulls(transport, repo, head)
    if existing:
        return get_pull(transport, repo, int(existing[0]["number"])), False
    payload = {"title": title, "body": body, "head": head, "base": base, "draft": bool(draft)}
    try:
        status, data = transport.request("POST", f"/repos/{repo.owner}/{repo.name}/pulls", body=payload)
    except GitHubError as exc:
        if not exc.transient:
            raise
        # The request may have reached GitHub before the connection dropped: the
        # lookup before the POST found nothing, so a pull request now is this one.
        existing = find_pulls(transport, repo, head)
        if existing:
            return get_pull(transport, repo, int(existing[0]["number"])), True
        status, data = transport.request("POST", f"/repos/{repo.owner}/{repo.name}/pulls", body=payload)
    if status == 201 and isinstance(data, dict) and "number" in data:
        return get_pull(transport, repo, int(data["number"])), True
    if status == 422 and "already exists" in api_error_message(status, data).lower():
        existing = find_pulls(transport, repo, head)
        if existing:
            return get_pull(transport, repo, int(existing[0]["number"])), False
    raise GitHubError(api_error_message(status, data), status=status)


def summarize_pull(pull: dict[str, Any]) -> dict[str, Any]:
    head = pull.get("head") or {}
    base = pull.get("base") or {}
    return {
        "number": pull.get("number"),
        "url": pull.get("html_url"),
        "title": pull.get("title"),
        "state": pull.get("state"),
        "draft": bool(pull.get("draft")),
        "merged": bool(pull.get("merged") or pull.get("merged_at")),
        "merged_at": pull.get("merged_at"),
        "mergeable": pull.get("mergeable"),
        "mergeable_state": pull.get("mergeable_state"),
        "base": base.get("ref"),
        "head": head.get("ref"),
        "head_sha": head.get("sha"),
    }


def _paged(transport: Transport, path: str, key: str | None, *, max_pages: int = 5) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        status, data = transport.request("GET", path, query={"per_page": "100", "page": str(page)})
        data = _expect(status, data, 200)
        batch = data.get(key, []) if key and isinstance(data, dict) else data
        if not isinstance(batch, list):
            break
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    return items


def check_summary(transport: Transport, repo: RemoteRepo, sha: str) -> dict[str, Any]:
    """Summarize check runs and legacy commit statuses for one commit."""
    prefix = f"/repos/{repo.owner}/{repo.name}/commits/{sha}"
    entries: list[dict[str, Any]] = []
    for run in _paged(transport, prefix + "/check-runs", "check_runs"):
        if run.get("status") != "completed":
            outcome = "pending"
        else:
            conclusion = str(run.get("conclusion") or "")
            outcome = "failure" if conclusion in _FAILING_CONCLUSIONS else "success" if conclusion in _PASSING_CONCLUSIONS else conclusion or "pending"
        entries.append({"name": run.get("name"), "kind": "check_run", "outcome": outcome, "conclusion": run.get("conclusion"), "url": run.get("html_url") or run.get("details_url")})
    status, combined = transport.request("GET", prefix + "/status")
    combined = _expect(status, combined, 200)
    for item in (combined or {}).get("statuses") or []:
        state = str(item.get("state") or "")
        outcome = {"success": "success", "pending": "pending"}.get(state, "failure")
        entries.append({"name": item.get("context"), "kind": "status", "outcome": outcome, "conclusion": state, "url": item.get("target_url")})
    counts = {"total": len(entries), "success": 0, "failure": 0, "pending": 0, "other": 0}
    for entry in entries:
        bucket = entry["outcome"] if entry["outcome"] in ("success", "failure", "pending") else "other"
        counts[bucket] += 1
    if not entries:
        overall = "none"
    elif counts["failure"]:
        overall = "failure"
    elif counts["pending"]:
        overall = "pending"
    else:
        overall = "success"
    return {
        "sha": sha,
        "state": overall,
        "counts": counts,
        "failing": [entry for entry in entries if entry["outcome"] == "failure"],
        "pending": [entry["name"] for entry in entries if entry["outcome"] == "pending"],
    }


def review_summary(transport: Transport, repo: RemoteRepo, number: int) -> dict[str, int]:
    """Latest review verdict per reviewer, counted."""
    latest: dict[str, str] = {}
    for review in _paged(transport, f"/repos/{repo.owner}/{repo.name}/pulls/{int(number)}/reviews", None):
        user = str((review.get("user") or {}).get("login") or "")
        state = str(review.get("state") or "")
        if state in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[user] = state
        elif state == "COMMENTED":
            latest.setdefault(user, state)
    values = list(latest.values())
    return {
        "approved": values.count("APPROVED"),
        "changes_requested": values.count("CHANGES_REQUESTED"),
        "commented": values.count("COMMENTED"),
    }


# ---------------------------------------------------------------------- CLI


def _load_auth(from_stdin: bool, host: str) -> tuple[str, str]:
    if from_stdin:
        value = sys.stdin.readline().strip()
        if not value:
            raise GitHubError("gh is authenticated but returned no token (gh auth token)")
        return value, "gh"
    _, value = auth_for_host(host)
    if not value:
        raise GitHubError(missing_credentials_message(host))
    return value, "env"


def _transport(args: argparse.Namespace) -> tuple[RestTransport, str]:
    base = resolve_api_base(args.host, args.api_url)
    value, source = _load_auth(args.auth_from_stdin, args.host)
    return RestTransport(args.host, value, base=base), source


def _read_body(path: str) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise GitHubError(f"cannot read the body file {path}: {exc.strerror}") from None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise GitHubError(f"the body file {path} is not UTF-8 text; convert it (for example with iconv) and try again") from None


def _fail(command: str, exc: GitHubError) -> int:
    message = str(exc)
    data: dict[str, Any] = {"error": message, "status": exc.status}
    hint = gitflow_json.hint_for(message) if exc.status in (401, 403, 404) else None
    if message.startswith("no GitHub credentials"):
        hint = "Ask the user to connect GitHub (or configure a token for the sandbox). Never ask them to paste a token into chat."
    if hint:
        data["hint"] = hint
    gitflow_json.emit_fail(command, data)
    return 1


def cmd_pr_create(args: argparse.Namespace) -> int:
    repo = RemoteRepo(args.host, args.owner, args.repo)
    try:
        transport, source = _transport(args)
        body = _read_body(args.body_file)
        pull, created = create_pull(transport, repo, title=args.title, body=body, head=args.head, base=args.base, draft=args.draft)
    except GitHubError as exc:
        return _fail("pr create", exc)
    summary = summarize_pull(pull)
    warnings = list(args.warning or [])
    if not created:
        warnings.append("an open pull request for this branch already existed; it was returned unchanged (title and body were not edited)")
        if summary["base"] != args.base:
            warnings.append(f"the existing pull request targets {summary['base']!r}, not {args.base!r}")
    data = {
        "created": created,
        "via": source,
        "repository": repo.slug,
        **summary,
        "head_matches_remote": summary["head_sha"] == args.remote_sha,
        "head_matches_local": summary["head_sha"] == args.local_sha,
        "warnings": warnings,
    }
    return gitflow_json.emit_ok("pr create", data)


def cmd_pr_status(args: argparse.Namespace) -> int:
    repo = RemoteRepo(args.host, args.owner, args.repo)
    try:
        transport, source = _transport(args)
        if args.number:
            pull = get_pull(transport, repo, args.number)
        elif not args.branch:
            raise GitHubError("pass --number or --branch")
        else:
            found = find_pulls(transport, repo, args.branch) or find_pulls(transport, repo, args.branch, state="all")
            if not found:
                gitflow_json.emit_fail(
                    "pr status",
                    {"error": f"no pull request found for branch {args.branch!r} in {repo.slug}", "hint": "Create one with: gitflow.sh pr create --title ... --body-file ..."},
                )
                return 1
            pull = get_pull(transport, repo, int(found[0]["number"]))
        summary = summarize_pull(pull)
        checks = check_summary(transport, repo, summary["head_sha"]) if summary["head_sha"] else None
        reviews = review_summary(transport, repo, int(summary["number"]))
    except GitHubError as exc:
        return _fail("pr status", exc)
    notes = []
    if summary["mergeable"] is None and summary["state"] == "open":
        notes.append("GitHub has not finished computing mergeability; run pr status again shortly")
    if summary["head_sha"] and args.local_sha and summary["head_sha"] != args.local_sha and summary["head"] == args.branch:
        notes.append("the pull request head differs from local HEAD; push to update it, or the checks below are for an older commit")
    data = {"via": source, "repository": repo.slug, **summary, "head_matches_local": summary["head_sha"] == args.local_sha, "checks": checks, "reviews": reviews, "notes": notes}
    return gitflow_json.emit_ok("pr status", data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitflow_github.py", description="GitHub REST helper for gitflow.sh.")
    sub = parser.add_subparsers(dest="action", required=True)
    remote = sub.add_parser("parse-remote")
    remote.add_argument("url")
    names = sub.add_parser("token-names")
    names.add_argument("--host", help="only the variables this host may receive")
    new_pull = sub.add_parser("new-pull-url")
    for name in ("--host", "--owner", "--repo", "--branch"):
        new_pull.add_argument(name, required=True)

    def repo_args(p: argparse.ArgumentParser) -> None:
        for name in ("--host", "--owner", "--repo"):
            p.add_argument(name, required=True)
        p.add_argument("--auth-from-stdin", action="store_true", help="read the token from stdin (piped from gh auth token)")
        p.add_argument("--api-url", help="API root override: https, or loopback http for tests")
        p.add_argument("--local-sha", default="")

    create = sub.add_parser("pr-create")
    repo_args(create)
    create.add_argument("--head", required=True)
    create.add_argument("--base", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--body-file", required=True)
    create.add_argument("--draft", action="store_true")
    create.add_argument("--remote-sha", default="")
    create.add_argument("--warning", action="append")
    status = sub.add_parser("pr-status")
    repo_args(status)
    status.add_argument("--number", type=int, help="the pull request number (default: the one for --branch)")
    status.add_argument("--branch", default="", help="the current branch")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.action == "parse-remote":
        parsed = parse_remote_url(args.url)
        if parsed is None:
            return 1
        sys.stdout.write(f"{parsed.host}\t{parsed.owner}\t{parsed.name}\n")
        return 0
    if args.action == "token-names":
        sys.stdout.write(" ".join(token_env_names_present(args.host)) + "\n")
        return 0
    if args.action == "new-pull-url":
        sys.stdout.write(new_pull_url(RemoteRepo(args.host, args.owner, args.repo), args.branch) + "\n")
        return 0
    command = "pr create" if args.action == "pr-create" else "pr status"
    try:
        return cmd_pr_create(args) if args.action == "pr-create" else cmd_pr_status(args)
    except Exception as exc:
        # The JSON contract holds even for a bug: report it instead of a traceback.
        gitflow_json.emit_fail(command, {"error": f"internal error in gitflow_github.py: {type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
