#!/usr/bin/env python3
"""Whole-instance backup and restore (fork feature).

DeerFlow has per-feature memory import/export, but nothing snapshots
``.deer-flow`` *as a unit*: memory, threads, chat tabs, runtime settings,
uploads, integration credentials. A personal AI accumulates months of that on a
single machine with no redundancy — which is exactly the deployment shape this
fork targets.

Usage:
    python3 scripts/backup.py create [--output-dir DIR] [--include-secrets]
    python3 scripts/backup.py restore ARCHIVE [--force]
    python3 scripts/backup.py inspect ARCHIVE

## The secrets decision

**Credentials are excluded by default.** Integration credentials under
``users/{user_id}/integrations/`` are ``0700``/``0600`` for a reason, and ``.env``
holds every API key. A backup that quietly copies those into a
world-readable tarball in ``~/Downloads`` is worse than no backup at all — it
turns a durability feature into a credential-exfiltration feature that nobody
asked for.

``--include-secrets`` opts in explicitly. The resulting archive is written
``0600`` (owner-only) and refuses to exist otherwise, and the manifest records
the choice so a restore can say what it is about to write. A restore of a
secret-free archive leaves the target's existing credentials alone rather than
deleting what the backup does not carry.

## Restore against a running stack

Refused. Writing underneath a live Gateway means half-restored SQLite next to a
process holding the old file open, and thread directories changing under an
active run. ``restore`` probes the Gateway and nginx ports and stops with the
list of what is up; ``--force`` is the deliberate override.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

ARCHIVE_ROOT = "deerflow-backup"
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
PG_DUMP_NAME = "postgres.dump.sql"

# Ports that mean "a stack is up on this machine". Both are the fork's defaults:
# nginx is the published entry, the Gateway is what actually holds the database.
RUNNING_PORTS: tuple[tuple[str, str, int], ...] = (
    ("Gateway", "127.0.0.1", 8001),
    ("nginx", "127.0.0.1", 2026),
)

# Paths relative to the project root, included as a unit. `.env` is listed here
# but filtered out by SECRET_PATTERNS below unless --include-secrets: it must be
# a candidate for the opt-in to be able to carry it at all.
INCLUDED_PATHS: tuple[str, ...] = (
    "config.yaml",
    "extensions_config.json",
    ".env",
    "backend/.deer-flow",
    ".deer-flow",
    "skills/custom",
)

# Excluded unless --include-secrets. Matched against the POSIX relative path.
SECRET_PATTERNS: tuple[str, ...] = (
    r"(^|/)\.env$",
    r"(^|/)integrations/",
)

# Never worth carrying: rebuildable caches and transient scratch.
ALWAYS_EXCLUDED: tuple[str, ...] = (
    r"(^|/)skills_view(/|$)",
    r"(^|/)\.retrieval(/|$)",
    r"(^|/)__pycache__(/|$)",
    r"(^|/)browser-frames(/|$)",
    r"\.upload-[^/]*\.part$",
)


class BackupError(RuntimeError):
    """A refusal or a failure that must stop the operation, not degrade it."""


# ---------------------------------------------------------------------------
# Inspection helpers
# ---------------------------------------------------------------------------


def _probe_port(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_running_services(probe: Callable[[str, int], bool] = _probe_port) -> list[str]:
    """Names of DeerFlow services currently accepting connections locally."""
    return [f"{name} ({host}:{port})" for name, host, port in RUNNING_PORTS if probe(host, port)]


def _read_database_settings(config_path: Path) -> tuple[str, str | None]:
    """Return ``(backend, url)`` from config.yaml's ``database:`` section.

    A pure-text scan, like the sibling sync scripts: this runs under plain
    python3 from the repo root, with no guarantee the backend venv exists.
    """
    if not config_path.exists():
        return "sqlite", None
    backend, url = "sqlite", None
    in_section = False
    try:
        lines = config_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return backend, url
    for line in lines:
        if not in_section:
            if re.match(r"^database:\s*(#.*)?$", line):
                in_section = True
            continue
        if line and not line[0].isspace():
            if re.match(r"^[A-Za-z_][\w-]*:", line):
                break
            continue
        match = re.match(r"^\s+([A-Za-z_][\w-]*):\s*([^#]*)", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip().strip("\"'")
        if key == "backend" and value:
            backend = value.lower()
        elif key == "url" and value:
            url = value
    return backend, url


def _run_pg_dump(url: str, destination: Path) -> bool:
    if not shutil.which("pg_dump"):
        return False
    try:
        with destination.open("wb") as handle:
            result = subprocess.run(["pg_dump", "--no-owner", "--no-privileges", url], stdout=handle, stderr=subprocess.PIPE, check=False)
    except OSError:
        return False
    if result.returncode != 0:
        sys.stderr.write((result.stderr or b"").decode("utf-8", "replace"))
        return False
    return True


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def _matches(rel_path: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, rel_path) for pattern in patterns)


def _collect(project_root: Path, include_secrets: bool) -> tuple[list[tuple[Path, str]], list[str]]:
    """Walk the included paths, returning ``(files, skipped_secret_paths)``."""
    files: list[tuple[Path, str]] = []
    skipped: list[str] = []

    for relative in INCLUDED_PATHS:
        source = project_root / relative
        if not source.exists():
            continue
        if source.is_file():
            candidates = [source]
        else:
            candidates = [p for p in source.rglob("*") if p.is_file()]
        for path in candidates:
            rel = path.relative_to(project_root).as_posix()
            if _matches(rel, ALWAYS_EXCLUDED):
                continue
            if _matches(rel, SECRET_PATTERNS):
                if not include_secrets:
                    skipped.append(rel)
                    continue
            files.append((path, rel))
    return files, skipped


def create_backup(
    project_root: Path,
    output_dir: Path,
    *,
    include_secrets: bool = False,
    pg_dump: Callable[[str, Path], bool] = _run_pg_dump,
    now: dt.datetime | None = None,
) -> Path:
    """Write one timestamped archive of everything this instance accumulated."""
    project_root = Path(project_root)
    if not project_root.exists():
        raise BackupError(f"project root not found: {project_root}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files, skipped = _collect(project_root, include_secrets)
    backend, url = _read_database_settings(project_root / "config.yaml")

    stamp = (now or dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    archive = output_dir / f"deerflow-backup-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as scratch:
        extra: list[tuple[Path, str]] = []

        if backend.startswith("postgres"):
            if not url:
                raise BackupError("database.backend is postgres but no database.url is configured; cannot dump")
            dump_path = Path(scratch) / PG_DUMP_NAME
            if not pg_dump(url, dump_path):
                raise BackupError(f"pg_dump failed (is pg_dump installed and {url.split('@')[-1]} reachable?) — refusing to write a backup with no database in it")
            extra.append((dump_path, PG_DUMP_NAME))

        manifest = {
            "version": MANIFEST_VERSION,
            "created_at": (now or dt.datetime.now()).isoformat(timespec="seconds"),
            "project_root": str(project_root),
            "includes_secrets": include_secrets,
            "database_backend": backend,
            "file_count": len(files) + len(extra),
            "excluded": sorted(set(skipped)),
        }
        manifest_path = Path(scratch) / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        extra.append((manifest_path, MANIFEST_NAME))

        # Create owner-only from the start: an archive that is briefly
        # world-readable while it is being written is still world-readable.
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
            for path, rel in files:
                tar.add(path, arcname=f"{ARCHIVE_ROOT}/{rel}", recursive=False)
            # Directory entries carry the modes that matter (0700 on
            # integrations/), which per-file adds alone would not restore.
            for relative in INCLUDED_PATHS:
                source = project_root / relative
                if not source.is_dir():
                    continue
                for directory in [source, *[p for p in source.rglob("*") if p.is_dir()]]:
                    rel = directory.relative_to(project_root).as_posix()
                    if _matches(rel, ALWAYS_EXCLUDED):
                        continue
                    if _matches(rel + "/", SECRET_PATTERNS) and not include_secrets:
                        continue
                    info = tar.gettarinfo(str(directory), arcname=f"{ARCHIVE_ROOT}/{rel}")
                    tar.addfile(info)
            for path, name in extra:
                tar.add(path, arcname=f"{ARCHIVE_ROOT}/{name}", recursive=False)

    return archive


# ---------------------------------------------------------------------------
# Inspect / restore
# ---------------------------------------------------------------------------


def inspect_backup(archive: Path) -> dict:
    """Read the manifest without extracting anything."""
    with tarfile.open(archive, "r:gz") as tar:
        try:
            handle = tar.extractfile(f"{ARCHIVE_ROOT}/{MANIFEST_NAME}")
            if handle is None:
                raise KeyError(MANIFEST_NAME)
            return json.loads(handle.read().decode("utf-8"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise BackupError(f"{archive} has no readable DeerFlow backup manifest — refusing to treat it as one ({exc})") from exc


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Members re-rooted under the target, rejecting anything that escapes it."""
    members: list[tarfile.TarInfo] = []
    for member in tar.getmembers():
        name = member.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise BackupError(f"unsafe path in archive: {name!r} — refusing to extract")
        if not (name == ARCHIVE_ROOT or name.startswith(f"{ARCHIVE_ROOT}/")):
            raise BackupError(f"unsafe path in archive: {name!r} is outside {ARCHIVE_ROOT}/ — refusing to extract")
        member.name = name[len(ARCHIVE_ROOT) + 1 :] if name != ARCHIVE_ROOT else "."
        if member.name in ("", ".", MANIFEST_NAME, PG_DUMP_NAME):
            continue
        members.append(member)
    return members


def restore_backup(
    archive: Path,
    project_root: Path,
    *,
    is_running: Callable[[], list[str]] = detect_running_services,
    force: bool = False,
) -> dict:
    """Extract an archive over ``project_root``, refusing unsafe situations."""
    archive = Path(archive)
    project_root = Path(project_root)
    if not archive.exists():
        raise BackupError(f"archive not found: {archive}")

    manifest = inspect_backup(archive)

    if not force:
        running = is_running()
        if running:
            raise BackupError(f"DeerFlow is running ({', '.join(running)}) — restoring underneath a live Gateway corrupts the database it has open. Run `make stop` (or `make down`) first, or pass --force if you are certain.")

    project_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar)
        # filter="tar" keeps the recorded permission bits (0700 on credential
        # dirs) while still refusing absolute paths and traversal; "data" would
        # strip exactly the modes this feature exists to preserve. Ownership is
        # only restorable as root, which is documented rather than attempted.
        tar.extractall(path=project_root, members=members, filter="tar")

        if manifest.get("database_backend", "").startswith("postgres"):
            handle = tar.extractfile(f"{ARCHIVE_ROOT}/{PG_DUMP_NAME}")
            if handle is not None:
                dump_target = project_root / PG_DUMP_NAME
                dump_target.write_bytes(handle.read())
                dump_target.chmod(0o600)
                manifest["postgres_dump_written_to"] = str(dump_target)

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up and restore a whole DeerFlow instance.")
    repo_root = Path(__file__).resolve().parents[1]
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Write a timestamped archive of this instance")
    create.add_argument("--project-root", default=str(repo_root))
    create.add_argument("--output-dir", default=str(repo_root / "backups"))
    create.add_argument(
        "--include-secrets",
        action="store_true",
        help="Also archive .env and users/*/integrations/ (API keys, OAuth tokens). The archive is written owner-only (0600); treat it as a credential file.",
    )

    restore = sub.add_parser("restore", help="Extract an archive over this instance")
    restore.add_argument("archive")
    restore.add_argument("--project-root", default=str(repo_root))
    restore.add_argument("--force", action="store_true", help="Restore even if a stack appears to be running")
    restore.add_argument("--assume-running", action="store_true", help=argparse.SUPPRESS)

    inspect = sub.add_parser("inspect", help="Print an archive's manifest without extracting")
    inspect.add_argument("archive")

    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            archive = create_backup(Path(args.project_root), Path(args.output_dir), include_secrets=args.include_secrets)
            manifest = inspect_backup(archive)
            print(f"Backup written: {archive}")
            print(f"  {manifest['file_count']} file(s), database backend: {manifest['database_backend']}")
            if manifest["includes_secrets"]:
                print("  ⚠ This archive CONTAINS credentials (.env, integration tokens). It is mode 0600 — keep it that way.")
            else:
                print(f"  Credentials excluded ({len(manifest['excluded'])} path(s)). Re-run with --include-secrets to carry them.")
            return 0

        if args.command == "restore":
            probe = (lambda: ["a stack (assumed)"]) if args.assume_running else detect_running_services
            manifest = restore_backup(Path(args.archive), Path(args.project_root), is_running=probe, force=args.force)
            print(f"Restored {manifest['file_count']} file(s) from {args.archive} into {args.project_root}")
            if manifest.get("postgres_dump_written_to"):
                print(f"  Postgres dump written to {manifest['postgres_dump_written_to']} — load it yourself with `psql < {PG_DUMP_NAME}`; this script does not touch a live database.")
            if not manifest.get("includes_secrets"):
                print("  This archive carried no credentials; any .env / integration tokens already on this machine were left untouched.")
            return 0

        info = inspect_backup(Path(args.archive))
        print(json.dumps(info, indent=2))
        return 0

    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
