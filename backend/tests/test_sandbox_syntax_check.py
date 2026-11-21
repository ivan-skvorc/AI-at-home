"""The parse-only syntax checker behind the write tools' warning and the HarnessGuard gate.

What matters most is the false positive: a warning on a valid file costs the
model a turn of second-guessing correct work, and teaches it to ignore the
warning. So JSON with comments, templated YAML and YAML custom tags are pinned
as accepted, beside the real errors that must still be reported.
"""

import sys

import pytest
import yaml

from deerflow.agents.middlewares.harness_guard_middleware import verify_content_syntax
from deerflow.sandbox.syntax_check import MAX_CHECK_BYTES, MAX_YAML_CHECK_BYTES, check_syntax, is_checked_path, syntax_advisory

_PYTHON = f"Python {sys.version_info.major}.{sys.version_info.minor}"


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
        ("jinja.yaml", "{# rendered by the deploy job #}\na: 1\n"),
        ("cfn.yaml", "Value: !Ref MyBucket\n"),
        ("a.toml", '[tool]\nname = "x"\n'),
        ("README.md", "def (:\n"),
        ("a.py", ""),
        # A UTF-8 BOM (Windows editors) is not a syntax error for the tools that read these files.
        ("bom.json", '\ufeff{"a": 1}'),
        ("bom.py", "\ufeffx = 1\n"),
        ("bom.toml", '\ufeffname = "x"\n'),
        ("bom.yaml", "\ufeffa: 1\n"),
    ],
)
def test_valid_or_unchecked_content_reports_nothing(path: str, content: str) -> None:
    assert check_syntax(path, content) is None


@pytest.mark.parametrize(
    ("path", "content", "expected"),
    [
        # The interpreter version is named, so newer syntax flagged by an older parser is recognisable.
        ("a.py", "def f(:\n", f"{_PYTHON} syntax error at line 1"),
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


def test_yaml_has_a_lower_cap_and_uses_libyaml_when_installed(monkeypatch) -> None:
    # Pure-Python YAML costs seconds per megabyte on every edit; JSON keeps the larger cap.
    broken = "a: [1\n" + "# padding\n" * (MAX_YAML_CHECK_BYTES // 10 + 1)
    assert MAX_YAML_CHECK_BYTES < len(broken) < MAX_CHECK_BYTES
    assert check_syntax("big.yaml", broken) is None
    assert check_syntax("big.json", "[" + " " * MAX_YAML_CHECK_BYTES) is not None

    loaders: list[type] = []
    real_compose_all = yaml.compose_all

    def spy(stream, Loader):  # noqa: N803 - PyYAML's keyword
        loaders.append(Loader)
        return real_compose_all(stream, Loader=Loader)

    monkeypatch.setattr(yaml, "compose_all", spy)
    assert check_syntax("a.yaml", "a: 1\n") is None
    assert loaders == [getattr(yaml, "CSafeLoader", yaml.SafeLoader)]


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("big.json", '{"a": ' + "1" * 5000 + "}"),
        ("big.toml", "a = " + "1" * 5000 + "\n"),
    ],
    ids=["json", "toml"],
)
def test_a_parser_failure_that_is_not_a_syntax_error_means_not_checked(path: str, content: str) -> None:
    # Python's 4300-digit int limit raises a plain ValueError. The write already
    # happened, so the checker must never turn it into a reported failure.
    assert check_syntax(path, content) is None
    assert syntax_advisory(path, content) is None


@pytest.mark.parametrize(
    "content",
    [
        '{\n  // compiler options\n  "a": 1,\n  "b": 2,\n  "c" 3\n}\n',
        '{\n  /* compiler\n     options */\n  "a": 1,\n  "c" 3\n}\n',
    ],
)
def test_json_with_comments_reports_the_real_error_line(content: str) -> None:
    # The strict parse stops at the first comment; the error the model must fix is the missing colon.
    error = check_syntax("tsconfig.json", content)
    assert error is not None and error.startswith("Invalid JSON at line 5, column 7:"), error


def test_an_edit_warns_only_when_it_broke_a_file_that_parsed() -> None:
    assert syntax_advisory("a.py", "def f(:\n", before="def f():\n    pass\n") is not None
    assert syntax_advisory("a.py", "def f(:\n    x\n", before="def f(:\n") is None


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
