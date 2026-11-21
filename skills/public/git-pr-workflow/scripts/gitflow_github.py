"""GitHub REST helpers for gitflow.py.

Standard library only. This module owns everything that talks to the GitHub API
over HTTPS: parsing the repository from a git remote URL, a urllib transport,
and the pull-request logic shared by the urllib transport and gitflow.py's
gh api transport.

The urllib transport reads the token from GH_TOKEN or GITHUB_TOKEN by
name and sends it only in the Authorization header to the API host derived
from the repository's own remote. It never reads the environment in bulk, and
it never puts the token in a URL, a log line, or an error message.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

TOKEN_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
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


def web_url(repo: RemoteRepo, path: str = "") -> str:
    return f"https://{repo.host}/{repo.owner}/{repo.name}{path}"


def new_pull_url(repo: RemoteRepo, branch: str) -> str:
    return web_url(repo, "/pull/new/" + urllib.parse.quote(branch, safe="/"))


def token_from_env() -> tuple[str | None, str | None]:
    """Return (variable name, value) of the first GitHub token variable that is set."""
    for name in TOKEN_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if value:
            return name, value
    return None, None


def token_env_names_present() -> list[str]:
    return [name for name in TOKEN_ENV_NAMES if (os.getenv(name) or "").strip()]


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

    def __init__(self, host: str, auth_value: str, *, timeout: float = 30.0) -> None:
        self.host = host
        self.base = api_base(host)
        self._auth_value = auth_value
        self.timeout = timeout

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
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
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
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < attempts:
                    time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
                    continue
                reason = getattr(exc, "reason", exc)
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
        # The request may have reached GitHub before the connection dropped.
        existing = find_pulls(transport, repo, head)
        if existing:
            return get_pull(transport, repo, int(existing[0]["number"])), False
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
