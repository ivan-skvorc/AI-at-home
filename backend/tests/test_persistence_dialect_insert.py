"""The shared dialect ``INSERT`` choice for upserting repositories.

Five repositories (folder ledger, thread reads, channel runtime configs, channel
thread bindings, login throttle) each carried a private helper that picked the
PostgreSQL or SQLite ``insert`` and raised for any other dialect. They now call
``deerflow.persistence.dialect_insert.dialect_insert``.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import deerflow.persistence.dialect_insert as owner

PERSISTENCE_ROOT = Path(owner.__file__).resolve().parent


def test_postgres_and_sqlite_get_their_conflict_capable_insert():
    assert owner.dialect_insert("postgresql", component="folder ledger") is pg_insert
    assert owner.dialect_insert("sqlite", component="folder ledger") is sqlite_insert


@pytest.mark.parametrize("dialect", ["mysql", "", "PostgreSQL"])
def test_any_other_dialect_is_an_error_naming_the_repository(dialect):
    with pytest.raises(ValueError, match=f"^Unsupported thread read database dialect: {dialect}$"):
        owner.dialect_insert(dialect, component="thread read")


def _returns_a_dialect_insert(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id in {"pg_insert", "sqlite_insert"} for node in ast.walk(fn))


def test_no_repository_defines_its_own_dialect_insert_helper():
    """A private helper returning ``pg_insert`` / ``sqlite_insert`` is the folded shape.

    Inline ``sqlite_insert if ... else pg_insert`` choices are out of scope: they
    sit next to a dialect check that also feeds other dialect-specific SQL.
    """
    offenders = []
    for path in sorted(PERSISTENCE_ROOT.rglob("*.py")):
        if path == Path(owner.__file__).resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _returns_a_dialect_insert(node):
                offenders.append(f"{path.relative_to(PERSISTENCE_ROOT)}::{node.name}")
    assert offenders == [], f"use deerflow.persistence.dialect_insert.dialect_insert instead: {offenders}"
