"""Two chats must be able to answer at the same time.

The user-visible promise: send a prompt in one chat, walk over to another chat
and send a prompt there, and both answers arrive — the second does not wait for
the first. The Gateway already scopes its run lock to one thread
(``_checkpoint_thread_lock(thread_id)`` in ``runtime/runs/worker.py``), and
these tests pin that boundary in both directions, because a lock widened to a
process-global one would still pass every other test in the suite and would
silently turn concurrent chats back into a queue.

The frontend half of the same promise — a run outliving the SSE consumer that
started it, so leaving a chat does not cancel it — is
``on_disconnect: "continue"`` on the run request (see
``tests/test_wait_disconnect_handling.py`` and the frontend's
``tests/unit/core/threads/run-disconnect.test.ts``).
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.schemas import RunStatus
from deerflow.runtime.runs.worker import RunContext, run_agent

# A run that cannot start until the other one has also started. If the two runs
# were serialized, the first would wait here for a partner that cannot begin
# until it finishes, and the timeout below would fire.
RENDEZVOUS_TIMEOUT_SECONDS = 5.0

# Long enough that a second run sharing the event loop would certainly have
# reached its own astream() inside this window if nothing held it back.
OVERLAP_WINDOW_SECONDS = 0.05


def _make_bridge():
    return SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())


async def _execute(run_manager: RunManager, record, agent) -> None:
    await run_agent(
        _make_bridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=MemoryRunEventStore()),
        agent_factory=lambda *, config: agent,
        graph_input={},
        config={},
    )


@pytest.mark.anyio
async def test_runs_in_different_chats_answer_at_the_same_time():
    run_manager = RunManager()
    first = await run_manager.create("thread-a")
    second = await run_manager.create("thread-b")

    both_streaming = asyncio.Event()
    streaming = 0

    class RendezvousAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            nonlocal streaming
            streaming += 1
            if streaming == 2:
                both_streaming.set()
            await asyncio.wait_for(both_streaming.wait(), timeout=RENDEZVOUS_TIMEOUT_SECONDS)
            yield {"messages": []}

    await asyncio.gather(
        _execute(run_manager, first, RendezvousAgent()),
        _execute(run_manager, second, RendezvousAgent()),
    )

    assert (await run_manager.get(first.run_id)).status == RunStatus.success
    assert (await run_manager.get(second.run_id)).status == RunStatus.success


@pytest.mark.anyio
async def test_two_runs_in_one_chat_still_take_turns():
    """The other half of the boundary: one chat is a queue, on purpose.

    Both runs mutate the same conversation's checkpoint, so interleaving them
    would corrupt the thread. Concurrency is across chats, not within one.
    """
    run_manager = RunManager()
    first = await run_manager.create("thread-shared")
    second = await run_manager.create("thread-shared")

    log: list[str] = []

    def _agent(name: str):
        class LoggingAgent:
            async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
                log.append(f"{name}-start")
                await asyncio.sleep(OVERLAP_WINDOW_SECONDS)
                log.append(f"{name}-end")
                yield {"messages": []}

        return LoggingAgent()

    await asyncio.gather(
        _execute(run_manager, first, _agent("first")),
        _execute(run_manager, second, _agent("second")),
    )

    # Whichever ran first, it ran to completion before the other started.
    assert log in (
        ["first-start", "first-end", "second-start", "second-end"],
        ["second-start", "second-end", "first-start", "first-end"],
    ), log
