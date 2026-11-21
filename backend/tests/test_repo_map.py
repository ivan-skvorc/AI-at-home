"""The repo map in docs/repo-map/ stays in step with the tracked files.

The map is the lookup table for a level 1 change cycle: a changed file is found
in the file -> features index, and the tests of each feature listed there are
run. These checks keep that lookup trustworthy: every shipping file resolves to
a row under the documented matching rule, no row is stale, every feature in the
index has an entry, every listed test exists, and every area file opens with its
board. Stdlib only, offline, one ``git ls-files`` call.
"""

from __future__ import annotations

import bisect
import functools
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_DIR = REPO_ROOT / "docs" / "repo-map"
INDEX = MAP_DIR / "index.md"

SYNC_LINE = re.compile(r'^Synced by change cycle: \d{4}-\d{2}-\d{2}, level [123], ".+"$')
SPECIAL_FEATURES = frozenset({"ALL", "none (dev tooling)"})
ENTRY_FIELDS = ("What:", "Entry points:", "Files:", "Data:", "External:", "Tests:")

# Paths that other in-flight changes are adding. Index rows, Files: entries and
# Tests: entries naming them are allowed not to match a tracked file yet. Empty
# this set once those changes have landed.
PENDING_PATHS: frozenset[str] = frozenset()

_TEST_FILE = re.compile(r"(^test_.*\.py$)|(^conftest\.py$)|(\.(test|spec)\.[cm]?[jt]sx?$)")
_TEST_DIRS = frozenset({"tests", "test", "__tests__"})


def is_excluded(path: str) -> bool:
    """The documented exclusions: docs, tests and test fixtures.

    Docs are everything under docs/, every Markdown file and every licence
    text, except under skills/public/, whose files ship as skill content.
    Tests are the three test trees, any directory named tests/test, test
    modules and specs by name, and the extension test fixtures.
    """
    name = path.rsplit("/", 1)[-1]
    parts = path.split("/")
    shipped_skill = path.startswith("skills/public/")
    if path.startswith("docs/"):
        return True
    if not shipped_skill and (name.endswith(".md") or "LICENSE" in name):
        return True
    if path.startswith(("backend/tests/", "frontend/tests/", "tests/", "backend/extension_test_fixtures/")):
        return True
    if any(part in _TEST_DIRS for part in parts[:-1]):
        return True
    return bool(_TEST_FILE.search(name))


@functools.cache
def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """``**`` spans directories, ``*`` and ``?`` stay inside one path segment."""
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def is_pattern(row: str) -> bool:
    return any(ch in row for ch in "*?")


def specificity(row: str) -> tuple[int, int]:
    """The matching rule: an exact path beats any pattern; a longer pattern beats a shorter one."""
    return (0 if is_pattern(row) else 1, len(row))


@functools.cache
def _literal_prefix(row: str) -> str:
    return re.split(r"[*?]", row, maxsplit=1)[0]


def matches(row: str, path: str) -> bool:
    if not is_pattern(row):
        return row == path
    return path.startswith(_literal_prefix(row)) and bool(_pattern_regex(row).match(path))


@functools.lru_cache(maxsize=1)
def tracked_files() -> tuple[str, ...]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return tuple(p for p in result.stdout.decode("utf-8").split("\0") if p)


@functools.lru_cache(maxsize=1)
def sorted_tracked_files() -> list[str]:
    return sorted(tracked_files())


def shipping_files() -> list[str]:
    return [p for p in tracked_files() if not is_excluded(p)]


def _split_features(cell: str) -> tuple[str, ...]:
    cell = cell.strip()
    if cell in SPECIAL_FEATURES:
        return (cell,)
    return tuple(f.strip() for f in cell.split(",") if f.strip())


@functools.lru_cache(maxsize=1)
def index_rows() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Rows of the ``| File | Features |`` table, backticks stripped."""
    rows = []
    in_table = False
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if re.match(r"^\|\s*File\s*\|\s*Features\s*\|$", stripped):
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 2 or set(cells[0]) <= set("-: "):
            continue
        rows.append((cells[0].strip("`"), _split_features(cells[1])))
    return tuple(rows)


def winning_rows(path: str, rows) -> list[tuple[str, tuple[str, ...]]]:
    hits = [row for row in rows if matches(row[0], path)]
    if not hits:
        return []
    best = max(specificity(r[0]) for r in hits)
    return [r for r in hits if specificity(r[0]) == best]


def _directory_key(row: str) -> str:
    prefix = _literal_prefix(row)
    return prefix[: prefix.rfind("/") + 1]


@functools.lru_cache(maxsize=1)
def resolved() -> dict[str, list[tuple[str, tuple[str, ...]]]]:
    """Each shipping file with the index rows that win it under the matching rule.

    Rows are bucketed by the directory part of their literal prefix, so a file
    is only tested against rows rooted at one of its ancestor directories.
    """
    buckets: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    for row in index_rows():
        buckets.setdefault(_directory_key(row[0]), []).append(row)
    result = {}
    for path in shipping_files():
        parts = path.split("/")
        candidates = []
        for depth in range(len(parts)):
            candidates.extend(buckets.get("/".join(parts[:depth]) + ("/" if depth else ""), ()))
        result[path] = winning_rows(path, candidates)
    return result


def matches_a_tracked_file(row: str) -> bool:
    tracked = sorted_tracked_files()
    prefix = _literal_prefix(row)
    start = bisect.bisect_left(tracked, prefix)
    for path in tracked[start:]:
        if not path.startswith(prefix):
            return False
        if matches(row, path):
            return True
    return False


def area_files() -> list[Path]:
    return sorted(p for p in MAP_DIR.glob("*.md") if p.name != "index.md")


@functools.lru_cache(maxsize=1)
def feature_entries() -> dict[str, dict[str, str]]:
    """``### Name`` entries of every area file, with their spec fields."""
    entries: dict[str, dict[str, str]] = {}
    for area in area_files():
        current = None
        for line in area.read_text(encoding="utf-8").splitlines():
            if line.startswith("### "):
                current = line[4:].strip()
                assert current not in entries, f"feature {current!r} has two entries"
                entries[current] = {"__area__": area.name}
                continue
            if line.startswith("#"):
                current = None
                continue
            if current is None:
                continue
            for field in ENTRY_FIELDS:
                if line.startswith(field):
                    entries[current][field] = line[len(field) :].strip()
    return entries


def _list_field(value: str) -> list[str]:
    return [item.strip().strip("`") for item in value.split(",") if item.strip()]


def test_index_has_a_sync_line_under_the_title():
    assert INDEX.is_file(), "docs/repo-map/index.md is missing"
    lines = [line for line in INDEX.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines[0].startswith("# "), "index.md must open with its title"
    assert SYNC_LINE.match(lines[1]), f"second non-empty line is not a sync line: {lines[1]!r}"


def test_every_shipping_file_is_in_the_index():
    assert index_rows(), "the file -> features table is empty"
    unmatched = []
    ambiguous = []
    for path, winners in resolved().items():
        if not winners:
            unmatched.append(path)
        elif len({frozenset(w[1]) for w in winners}) > 1:
            ambiguous.append(f"{path}: {[w[0] for w in winners]}")
    assert not unmatched, f"{len(unmatched)} shipping files match no index row, e.g. {unmatched[:20]}"
    assert not ambiguous, f"equally specific rows disagree: {ambiguous[:20]}"


def test_no_index_row_is_stale():
    rows = index_rows()
    patterns = [r[0] for r in rows]
    duplicates = {p for p in patterns if patterns.count(p) > 1}
    assert not duplicates, f"rows listed twice: {sorted(duplicates)}"
    won = {row[0] for winners in resolved().values() for row in winners}
    stale = [p for p in patterns if p not in won and p not in PENDING_PATHS]
    assert not stale, f"rows that match no shipping file, or lose every file to a more specific row: {stale}"


def test_every_indexed_feature_has_an_entry_and_no_entry_is_orphaned():
    entries = feature_entries()
    assert entries, "no feature entries found in docs/repo-map/*.md"
    rows = index_rows()
    indexed = {f for _, features in rows for f in features} - SPECIAL_FEATURES
    missing = sorted(indexed - set(entries))
    assert not missing, f"features in the index without a ### entry: {missing}"
    all_rows = [r for r in rows if r[1] == ("ALL",)]
    orphans = []
    for name, fields in entries.items():
        if name in indexed:
            continue
        files = _list_field(fields.get("Files:", ""))
        reachable = files and all(any(matches(r[0], f) for r in all_rows) for f in files)
        if not reachable:
            orphans.append(name)
    assert not orphans, f"entries neither in the index nor reachable through ALL rows: {orphans}"


def test_every_entry_has_the_spec_fields_and_existing_tests():
    problems = []
    for name, fields in feature_entries().items():
        absent = [f for f in ENTRY_FIELDS if not fields.get(f)]
        if absent:
            problems.append(f"{name}: missing {absent}")
            continue
        for file_row in _list_field(fields["Files:"]):
            if file_row not in PENDING_PATHS and not matches_a_tracked_file(file_row):
                problems.append(f"{name}: Files entry {file_row} matches no tracked file")
        for test_path in _list_field(fields["Tests:"]):
            if test_path in PENDING_PATHS:
                continue
            if not (REPO_ROOT / test_path).is_file():
                problems.append(f"{name}: test {test_path} does not exist")
    assert not problems, "\n".join(problems)


def test_every_area_file_opens_with_its_board():
    areas = area_files()
    assert areas, "no area files in docs/repo-map/"
    for area in areas:
        lines = [line for line in area.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        assert lines and lines[0].strip() == "```mermaid", f"{area.name} must open with a ```mermaid board"


def test_every_exact_file_a_feature_lists_resolves_to_that_feature():
    """Level 1 runs a feature's tests only when the index sends a changed file there.

    A feature that names a file under Files: while the index resolves that file
    to other features is a feature whose tests level 1 silently skips when the
    file changes. Patterns (``dir/**``) are summaries and are not checked here.
    """
    rows = index_rows()
    problems = []
    for name, fields in feature_entries().items():
        for file_row in _list_field(fields["Files:"]):
            if is_pattern(file_row) or file_row in PENDING_PATHS or is_excluded(file_row):
                continue
            winners = winning_rows(file_row, rows)
            features = {feature for _, row_features in winners for feature in row_features}
            if winners and name not in features and "ALL" not in features:
                problems.append(f"{file_row}: listed by {name!r} but the index resolves it to {sorted(features)}")
    assert not problems, "\n".join(problems)
