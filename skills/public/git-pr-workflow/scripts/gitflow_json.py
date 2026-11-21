#!/usr/bin/env python3
"""JSON output helper for gitflow.sh: parsing and formatting only, no processes.

gitflow.sh writes a record stream and pipes it in:

    gitflow_json.py emit --command NAME (--ok | --fail) < RECORDS

RECORDS is a sequence of NUL-terminated (type, key, value) triples:

    s  string              n  integer, or null when the value is empty
    b  true/false          z  null
    j  raw JSON            a  append a string to the list KEY
    A  make KEY a list     o  start a new object in the list KEY
    .s .n .b .z .j         set field KEY on the object started by the last o
    P  run the parser KEY on the file named on the value's first line

Parsers: status (git status --porcelain=v2 --branch -z), checkpoints (the
for-each-ref format gitflow.sh uses; second value line is the limit) and
worktrees (git worktree list --porcelain; then the main root and a file of
NUL-separated path/dirty pairs).

With --fail the records describe an error: error, hint, fallback_hint,
git_subcommand and stderr are understood, everything else is passed through.
The JSON goes to stdout and a one-line diagnostic plus hint to stderr. All
output is redacted: URL credentials, token-shaped strings and the values of the
GitHub token variables become ***.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

TOKEN_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
LIST_LIMIT = 200
CHECKPOINT_NAMESPACE = "refs/deerflow-checkpoints/"

# scheme://userinfo@ -- userinfo of an http(s) URL is always hidden; for other
# schemes only when it carries a password (ssh://git@host stays readable).
_URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>[^/@\s\"']+)@")
_TOKEN_SHAPES_RE = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")

_HINTS = (
    (re.compile(r"dubious ownership"), "The checkout belongs to another user. Run: git config --global --add safe.directory <repo path>"),
    (
        re.compile(r"(?i)please tell me who you are|unable to auto-detect email|empty ident"),
        'Set an identity for this repository: git config user.name "Name" && git config user.email "you@example.com" (ask the user which identity to use).',
    ),
    (
        re.compile(r"(?i)could not read username|authentication failed|invalid username or password|returned error: 40[13]|permission denied|\b403\b|repository not found"),
        "Authentication or permission failure. Run preflight: GitHub must be connected (a token in the sandbox) with push access to this repository. Do not put a token in the remote URL.",
    ),
    (re.compile(r"(?i)non-fast-forward|fetch first|stale info"), "The remote branch has commits you do not have. Fetch and rebase onto it (git pull --rebase), resolve conflicts, then push again."),
    (re.compile(r"(?i)protected branch|GH006|GH013"), "The remote refused the update (branch protection or a repository rule). Push to a feature branch and open a pull request."),
    (re.compile(r"(?i)paths are ignored by one of your \.gitignore"), "One of the paths is ignored by .gitignore; leave it out of --paths, or ask the user before committing an ignored file."),
)


def _redact_userinfo(match: re.Match[str]) -> str:
    scheme = match.group("scheme")
    if scheme.lower().startswith("http") or ":" in match.group("userinfo"):
        return f"{scheme}***@"
    return match.group(0)


def redact(text: str) -> str:
    """Hide credentials in URLs, token-shaped strings and the live token values."""
    text = _URL_USERINFO_RE.sub(_redact_userinfo, text)
    text = _TOKEN_SHAPES_RE.sub("***", text)
    for name in TOKEN_ENV_NAMES:
        value = (os.getenv(name) or "").strip()
        if len(value) >= 8:
            text = text.replace(value, "***")
    return text


def hint_for(text: str) -> str | None:
    for pattern, hint in _HINTS:
        if pattern.search(text):
            return hint
    return None


def git_failure_summary(subcommand: str, stderr: str) -> str:
    lines = [line for line in stderr.splitlines() if line.strip()]
    # git's advice lines ("hint: ...") follow the actual error; keep the error.
    lines = [line for line in lines if not line.startswith("hint:")] or lines
    summary = " | ".join(lines[-3:]) if lines else "no error output"
    return f"git {subcommand} failed: {summary}"


# ------------------------------------------------------------------ parsers


def _split_z(raw: bytes) -> list[str]:
    return [item for item in raw.decode("utf-8", errors="surrogateescape").split("\0")]


def parse_status(raw: bytes) -> dict[str, Any]:
    """Fields from git status --porcelain=v2 --branch -z."""
    branch = head = upstream = None
    ahead = behind = None
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    conflicted: list[str] = []
    records = _split_z(raw)
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
                head = None if value == "(initial)" else value
            elif key == "branch.head":
                branch = None if value == "(detached)" else value
            elif key == "branch.upstream":
                upstream = value
            elif key == "branch.ab":
                match = re.match(r"\+(\d+) -(\d+)", value)
                if match:
                    ahead, behind = int(match.group(1)), int(match.group(2))
        elif kind in "12":
            fields = record.split(" ", 8 if kind == "1" else 9)
            xy, path = fields[1], fields[-1]
            if kind == "2":
                index += 1  # the rename/copy source is the next record
            if xy[0] != ".":
                staged.append(path)
            if xy[1] != ".":
                unstaged.append(path)
        elif kind == "u":
            conflicted.append(record.split(" ", 10)[-1])
        elif kind == "?":
            untracked.append(record[2:])
    return {
        "branch": branch,
        "detached": branch is None,
        "head": head,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(staged or unstaged or untracked or conflicted),
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicted": conflicted,
        "counts": {"staged": len(staged), "unstaged": len(unstaged), "untracked": len(untracked), "conflicted": len(conflicted)},
    }


def parse_checkpoints(raw: bytes, limit: int | None = None) -> dict[str, Any]:
    """Records of five NUL-terminated fields: id, commit, created, subject, body."""
    fields = _split_z(raw)
    items = []
    for start in range(0, len(fields) - 4, 5):
        ident, commit, created, subject, body = fields[start : start + 5]
        meta = dict(re.findall(r"^(branch|head|worktree): (.*)$", body, re.MULTILINE))
        items.append(
            {
                "id": ident.strip("\n"),
                "commit": commit,
                "created": created,
                "message": subject,
                "branch": meta.get("branch"),
                "head": meta.get("head"),
                "worktree": meta.get("worktree"),
            }
        )
    return {"count": len(items), "checkpoints": items[:limit] if limit else items}


def parse_worktrees(raw: bytes, root: str, dirty_raw: bytes) -> dict[str, Any]:
    pairs = _split_z(dirty_raw)
    dirty = {pairs[i]: pairs[i + 1] == "true" for i in range(0, len(pairs) - 1, 2)}
    agent_dir = os.path.join(root, ".worktrees")
    items = []
    for block in raw.decode("utf-8", errors="surrogateescape").split("\n\n"):
        item: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                item["path"] = value
            elif key == "HEAD":
                item["head"] = value
            elif key == "branch":
                item["branch"] = value.removeprefix("refs/heads/")
        if not item.get("path"):
            continue
        flags = {line.split(" ", 1)[0] for line in block.splitlines()}
        agent = os.path.dirname(item["path"]) == agent_dir
        items.append(
            {
                "path": item["path"],
                "branch": item.get("branch"),
                "head": item.get("head"),
                "agent": agent,
                "name": os.path.basename(item["path"]) if agent else None,
                "detached": "detached" in flags,
                "locked": "locked" in flags,
                "prunable": "prunable" in flags,
                "dirty": dirty.get(item["path"]) if agent else None,
            }
        )
    return {"main_root": root, "worktrees": items}


def _run_parser(name: str, value: str) -> dict[str, Any]:
    lines = value.split("\n")
    data = Path(lines[0]).read_bytes()
    if name == "status":
        return parse_status(data)
    if name == "checkpoints":
        return parse_checkpoints(data, int(lines[1]) if len(lines) > 1 and lines[1] else None)
    if name == "worktrees":
        return parse_worktrees(data, lines[1], Path(lines[2]).read_bytes())
    raise ValueError(f"unknown parser {name!r}")


# ------------------------------------------------------------------ records


def _convert(kind: str, value: str) -> Any:
    if kind == "s":
        return value
    if kind == "n":
        return int(value) if value.strip() else None
    if kind == "b":
        return value == "true"
    if kind == "z":
        return None
    if kind == "j":
        return json.loads(value)
    raise ValueError(f"unknown record type {kind!r}")


def build(raw: bytes) -> dict[str, Any]:
    """Assemble one JSON object from a record stream."""
    fields = _split_z(raw)
    out: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for start in range(0, len(fields) - 2, 3):
        kind, key, value = fields[start : start + 3]
        if kind == "a":
            out.setdefault(key, []).append(value)
        elif kind == "A":
            out.setdefault(key, [])
        elif kind == "o":
            current = {}
            out.setdefault(key, []).append(current)
        elif kind.startswith("."):
            if current is None:
                raise ValueError(f"field {key!r} before any object")
            current[key] = _convert(kind[1:], value)
        elif kind == "P":
            out.update(_run_parser(key, value))
        else:
            out[key] = _convert(kind, value)
    for key, value in list(out.items()):
        if isinstance(value, list) and len(value) > LIST_LIMIT and all(isinstance(item, str) for item in value):
            out[key] = value[:LIST_LIMIT]
            out.setdefault("truncated", []).append(key)
    return out


def emit_ok(command: str, data: dict[str, Any], stdout: Any = None) -> int:
    stdout = stdout or sys.stdout
    stdout.write(redact(json.dumps({"ok": True, "command": command, **data}, indent=2, ensure_ascii=False)) + "\n")
    return 0


def emit_fail(command: str, data: dict[str, Any], stdout: Any = None, stderr: Any = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    data = dict(data)
    git_stderr = str(data.get("stderr") or "")
    subcommand = data.pop("git_subcommand", None)
    fallback = data.pop("fallback_hint", None)
    if subcommand and not data.get("error"):
        data["error"] = git_failure_summary(str(subcommand), git_stderr)
    if git_stderr:
        data["stderr"] = git_stderr[-4000:]
    hint = data.get("hint") or hint_for(git_stderr) or fallback
    payload: dict[str, Any] = {"ok": False, "command": command, "error": data.pop("error", "failed")}
    data.pop("hint", None)
    if hint:
        payload["hint"] = hint
    payload.update(data)
    stdout.write(redact(json.dumps(payload, indent=2, ensure_ascii=False)) + "\n")
    stderr.write(redact(f"gitflow {command}: error: {payload['error']}") + "\n")
    if hint:
        stderr.write(redact(f"hint: {hint}") + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="gitflow_json.py", description="Format gitflow.sh records as JSON.")
    sub = parser.add_subparsers(dest="action", required=True)
    emit = sub.add_parser("emit")
    emit.add_argument("--command", required=True)
    mode = emit.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ok", action="store_true")
    mode.add_argument("--fail", action="store_true")
    redact_cmd = sub.add_parser("redact", help="redact stdin to stdout")
    redact_cmd.set_defaults()
    args = parser.parse_args(argv)
    if args.action == "redact":
        sys.stdout.write(redact(sys.stdin.read()))
        return 0
    data = build(sys.stdin.buffer.read())
    return emit_ok(args.command, data) if args.ok else emit_fail(args.command, data)


if __name__ == "__main__":
    sys.exit(main())
