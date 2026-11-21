#!/usr/bin/env python3
"""Secret scan of a staged diff for gitflow.sh commit. Reads only; starts no processes.

    gitflow_scan.py --names NAMES_FILE < DIFF

DIFF is the output of git diff --cached --unified=0 --no-renames with a/ and b/
prefixes; NAMES_FILE holds the staged file names, NUL-separated (git diff
--cached --name-only -z). Only added lines are scanned, and a renamed file
counts as added, so a secret moved to a new file is still caught.

Exit 0 and no output when nothing is found. Otherwise exit 3 and print two
lines: a short summary such as "app.py:2, .env", then a JSON array of findings
({"file", "line", "rule"}; line is null for the file-name rule). The secret
itself is never printed.
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import sys
from pathlib import Path
from typing import Any

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
FINDINGS_EXIT = 3


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


def scan_diff(diff: str, names: list[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = [{"file": name, "line": None, "rule": "sensitive-file"} for name in names if name and sensitive_file(name)]
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


def summarize(findings: list[dict[str, Any]]) -> str:
    return ", ".join(f"{item['file']}:{item['line']}" if item["line"] else item["file"] for item in findings[:20])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gitflow_scan.py", description="Scan a staged diff (stdin) for secrets.")
    parser.add_argument("--names", required=True, help="file with NUL-separated staged file names")
    args = parser.parse_args(argv)
    names = Path(args.names).read_bytes().decode("utf-8", errors="surrogateescape").split("\0")
    diff = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    findings = scan_diff(diff, names)
    if not findings:
        return 0
    sys.stdout.write(summarize(findings).replace("\n", " ") + "\n" + json.dumps(findings, ensure_ascii=False) + "\n")
    return FINDINGS_EXIT


if __name__ == "__main__":
    sys.exit(main())
