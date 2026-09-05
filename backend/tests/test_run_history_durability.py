"""Thread scroll-back history must survive a Gateway restart.

Scrolling back through a long conversation is served by
``GET /api/threads/{id}/messages/page``, which reads the run-event store and
nothing else. Under ``run_events.backend: memory`` that store is process state,
so restarting the Gateway empties it — while the LangGraph checkpoint, durable
under the default ``database.backend: sqlite``, keeps rendering the most recent
turns from the thread's own state.

That combination is the failure this file defends against, and its shape is why
it needs defending: the conversation still opens, still shows recent messages,
and simply stops loading older ones when the reader scrolls up. ``has_more``
comes back ``false``, the frontend's load-more sentinel never fires, and nothing
logs an error on either side. There is no symptom to grep for — so a default
that silently reverts to ``memory``, or a factory whose no-config path diverges
from its default-config path, would be invisible until a user reported a long
chat that had lost its history.

Run from ``backend/``:
    uv run pytest tests/test_run_history_durability.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deerflow.config.run_events_config import RunEventsConfig
from deerflow.runtime.events.store import make_run_event_store

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_EXAMPLE = REPO_ROOT / "config.example.yaml"


class TestDurableByDefault:
    """The shipped defaults, on both of the paths an install can take."""

    def test_the_schema_default_persists_run_events(self):
        # A config.yaml with no run_events section at all lands here.
        assert RunEventsConfig().backend == "db"

    def test_the_shipped_example_persists_run_events(self):
        # ...and a config.yaml copied from the example lands here. The two are
        # separate sources and have to agree: `make config` copies the example
        # verbatim, so an example that still said `memory` would override a
        # durable schema default on every fresh install.
        example = yaml.safe_load(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        assert example["run_events"]["backend"] != "memory", "config.example.yaml would ship a Gateway whose scroll-back history dies on restart"

    def test_no_config_resolves_the_same_store_as_default_config(self):
        # make_run_event_store(None) used to hardcode the memory store while
        # RunEventsConfig() described the configured default. Keeping the two
        # in lockstep is the point: a caller that passes no section must not
        # get quietly less durability than one that passes the defaults.
        assert type(make_run_event_store(None)) is type(make_run_event_store(RunEventsConfig()))


class TestNonDurableDatabaseStillWorks:
    @pytest.mark.anyio
    async def test_db_backend_without_a_session_factory_falls_back_to_memory(self):
        # `database.backend: memory` leaves nothing to write events through, so
        # the durable default must degrade rather than fail startup. This is
        # also what makes flipping the default safe for those installs.
        from deerflow.persistence.engine import close_engine, init_engine

        await init_engine("memory")
        try:
            store = make_run_event_store(RunEventsConfig(backend="db"))
            assert type(store).__name__ == "MemoryRunEventStore"
        finally:
            await close_engine()


class TestHistorySurvivesARestart:
    """The behaviour itself, across a real store teardown and rebuild."""

    @pytest.mark.anyio
    async def test_older_messages_still_page_backwards_after_a_restart(self, tmp_path):
        from deerflow.persistence.engine import close_engine, init_engine

        url = f"sqlite+aiosqlite:///{tmp_path / 'deerflow.db'}"

        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            store = make_run_event_store(RunEventsConfig())
            for index in range(5):
                await store.put(
                    thread_id="t1",
                    run_id=f"r{index}",
                    event_type="human_message",
                    category="message",
                    content=f"turn {index}",
                )
        finally:
            await close_engine()

        # The restart: a new process, a new engine, a new store object, same
        # database file. Nothing survives in memory.
        await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
        try:
            restarted = make_run_event_store(RunEventsConfig())

            newest = await restarted.list_messages("t1", limit=2)
            assert [row["content"] for row in newest] == ["turn 3", "turn 4"]

            # Paging backwards from the oldest loaded row is exactly what the
            # reader's scroll does. Under the memory store this comes back
            # empty and the thread appears to begin mid-conversation.
            older = await restarted.list_messages("t1", limit=2, before_seq=newest[0]["seq"])
            assert [row["content"] for row in older] == ["turn 1", "turn 2"]

            # seq is the cursor the whole feed is ordered by, and it continues
            # from the persisted maximum rather than restarting at 1 — a reset
            # would interleave new turns underneath old ones.
            appended = await restarted.put(
                thread_id="t1",
                run_id="r5",
                event_type="human_message",
                category="message",
                content="turn 5",
            )
            assert appended["seq"] > newest[-1]["seq"]
        finally:
            await close_engine()

    @pytest.mark.anyio
    async def test_the_memory_store_is_what_loses_it(self, tmp_path):
        # The other half of the same claim: this documents *why* the default
        # moved, and fails if someone "fixes" durability by making the memory
        # store persist instead of changing the default.
        store = make_run_event_store(RunEventsConfig(backend="memory"))
        await store.put(thread_id="t1", run_id="r0", event_type="human_message", category="message", content="turn 0")
        assert await store.list_messages("t1", limit=10)

        restarted = make_run_event_store(RunEventsConfig(backend="memory"))
        assert await restarted.list_messages("t1", limit=10) == []
