"""The parse-only syntax checker behind the write tools' warning and the HarnessGuard gate.

What matters most is the false positive: a warning on a valid file costs the
model a turn of second-guessing correct work, and teaches it to ignore the
warning. So JSON with comments, templated YAML and YAML custom tags are pinned
as accepted, beside the real errors that must still be reported.
"""

import pytest

from deerflow.agents.middlewares.harness_guard_middleware import verify_content_syntax
from deerflow.sandbox.syntax_check import MAX_CHECK_BYTES, check_syntax, is_checked_path, syntax_advisory


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("a.py", "def f(x):\n    return x\n"),
        ("a.pyi", "def f(x: int) -> int: ...\n"),
        ("a.json", '{"a": [1, 2]}'),
        ("tsconfig.json", '{\n  // comment\n  "compilerOptions": {"strict": true, /* block */},\n}\n'),
        ("a.json", '{"url": "http://example.com//path"}'),
        ("a.yaml", "a: 1\nb: [1, 2]\n---\nc: d\n"),
        ("template.yml", "spec:\n  replicas: {{ .Values.replicas }}\n"),
        ("cfn.yaml", "Value: !Ref MyBucket\n"),
        ("a.toml", '[tool]\nname = "x"\n'),
        ("README.md", "def (:\n"),
        ("a.py", ""),
    ],
)
def test_valid_or_unchecked_content_reports_nothing(path: str, content: str) -> None:
    assert check_syntax(path, content) is None


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        ("a.py", "def f(:\n", "Python syntax error at line 1"),
        ("a.json", '{"a": }', "Invalid JSON at line 1"),
        ("a.yaml", "a: [1, 2\n", "Invalid YAML"),
        ("a.yml", "a: b: c\n", "Invalid YAML at line 1"),
        ("a.toml", "name = \n", "Invalid TOML"),
    ],
)
def test_broken_content_is_reported_with_where(path: str, content: str, expected: str) -> None:
    error = check_syntax(path, content)
    assert error is not None and error.startswith(expected), error


def test_huge_content_is_not_parsed() -> None:
    assert check_syntax("big.json", "{" * (MAX_CHECK_BYTES + 1)) is None


def test_is_checked_path_matches_the_parsers() -> None:
    assert is_checked_path("/x/A.PY") and is_checked_path("c:\\x\\a.toml") and is_checked_path("a.yml")
    assert not is_checked_path("a.ts") and not is_checked_path("Makefile")


def test_the_advisory_names_the_path_and_says_writes_in_parts_are_fine() -> None:
    note = syntax_advisory("/mnt/user-data/workspace/a.py", "def f(:\n")
    assert note is not None and note.startswith("Warning: /mnt/user-data/workspace/a.py does not parse")
    assert "in parts" in note
    assert syntax_advisory("a.py", "x = 1\n") is None


def test_the_harness_guard_gate_uses_the_same_parsers() -> None:
    # One parser set: a file the advisory accepts is never blocked by the gate.
    assert verify_content_syntax("tsconfig.json", '{"a": 1, // c\n}') is None
    assert verify_content_syntax("a.yaml", "a: [1\n") is not None
