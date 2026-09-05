"""Run event storage configuration.

Controls where run events (messages + execution traces) are persisted.

Backends:
- db (default): SQL database via SQLAlchemy ORM. Provides full query
  capability, and is the only backend whose thread history survives a
  Gateway restart on a single-node install.
- memory: In-memory storage, data lost on restart. Suitable for
  development and testing.
- jsonl: Append-only JSONL files. Lightweight alternative for
  single-node deployments that need persistence without a database.

Why the default is ``db`` and not ``memory``: scroll-back through a long
conversation is served by ``GET /api/threads/{id}/messages/page``, which
reads this store and nothing else. Under ``memory`` that store is process
state, so a Gateway restart empties it while the LangGraph checkpoint --
durable under the default ``database.backend: sqlite`` -- keeps rendering
the recent window. The thread therefore looks intact and simply refuses to
page backwards, with no error anywhere. ``db`` writes into the same
``deerflow.db`` the checkpointer already uses, so the durable default costs
no extra setup; ``make_run_event_store`` still falls back to ``memory`` when
``database.backend: memory`` leaves no session factory to write through.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunEventsConfig(BaseModel):
    backend: Literal["memory", "db", "jsonl"] = Field(
        default="db",
        description=("Storage backend for run events. 'db' (default) persists thread history across restarts via SQL; 'memory' for development (scroll-back history is lost on restart); 'jsonl' for lightweight single-node persistence."),
    )
    max_trace_content: int = Field(
        default=10240,
        description="Maximum trace content size in bytes before truncation (db backend only).",
    )
    track_token_usage: bool = Field(
        default=True,
        description="Whether RunJournal should accumulate token counts to RunRow.",
    )
