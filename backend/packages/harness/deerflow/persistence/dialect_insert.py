"""The dialect ``INSERT`` constructor that upserting repositories share.

``on_conflict_do_update`` and ``on_conflict_do_nothing`` exist only on the
PostgreSQL and SQLite ``insert`` constructs, so a repository that upserts picks
one by the session's dialect. Five repositories carried their own copy of this
choice; any other dialect is an error naming the repository, because the
generic ``insert`` has no conflict clause and the upsert would fail later with a
less useful message.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def dialect_insert(dialect_name: str, *, component: str):
    """Return the PostgreSQL or SQLite ``insert`` for ``dialect_name``.

    ``component`` names the repository in the error raised for any other
    dialect, for example ``"folder ledger"``.
    """
    if dialect_name == "postgresql":
        return pg_insert
    if dialect_name == "sqlite":
        return sqlite_insert
    raise ValueError(f"Unsupported {component} database dialect: {dialect_name}")
