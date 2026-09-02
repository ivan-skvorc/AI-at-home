"""An abandoned embedded stream must clean up *deterministically* (fork patch).

``DeerFlowClient._stream_turn`` wraps the graph iterator in
``_stream_with_sandbox_lease_cleanup``, whose ``finally`` releases the sandbox
execution lease. Left as the ``for`` loop's anonymous iterator, that wrapper is
finalized by refcount when ``_stream_turn``'s frame is torn down — which happens
*after* ``stream()``'s own ``finally`` has run ``reset_trace_id``, and later
still (at GC) for a caller that simply drops the generator. Two things ride on
the timing, and neither raises when it slips:

* the **sandbox execution lease** is held past the point the stream ended, so an
  abandoned turn keeps a sandbox reserved until something collects it;
* the agent's own cleanup — logs, callbacks — runs with **no trace id bound**,
  so it correlates with nothing.

``with closing(...)`` in ``_stream_turn`` is what makes both run while
``GeneratorExit`` is still propagating, i.e. inside the caller's binding.
Upstream's ``test_stream_abandoned_generator_cleanup_stays_inside_trace_binding``
covers the trace half; this file covers the lease half and pins the ordering
directly, so a refactor that drops the ``closing`` fails here even if the trace
assertion is reworked. FORK.md, *Post-sync feature checklist*.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deerflow.client import DeerFlowClient
from deerflow.config.authorization_config import AuthorizationConfig


def _stub_agent_creation(monkeypatch, fake_agent: Any) -> None:
    def _stub_ensure_agent(self, config, **kwargs):
        self._agent = fake_agent
        self._agent_config_key = ("stub",)

    monkeypatch.setattr(DeerFlowClient, "_ensure_agent", _stub_ensure_agent)


def _make_client() -> DeerFlowClient:
    client = DeerFlowClient.__new__(DeerFlowClient)
    client._app_config = SimpleNamespace(
        models=[SimpleNamespace(name="stub-model")],
        authorization=AuthorizationConfig(enabled=False),
    )
    client._checkpoint_channel_mode = "full"
    client._extensions_config = None
    client._model_name = "stub-model"
    client._thinking_enabled = False
    client._plan_mode = False
    client._subagent_enabled = False
    client._agent_name = None
    client._available_skills = None
    client._middlewares = None
    client._checkpointer = None
    client._agent = None
    client._agent_config_key = None
    client._environment = None
    return client


class _NeverEndingAgent:
    """A graph that keeps yielding, so the caller must abandon it."""

    def __init__(self) -> None:
        self.checkpointer = None
        self.store = None

    def stream(self, state, *, config, context, stream_mode):
        while True:
            yield ("values", {"messages": [], "artifacts": []})


@pytest.fixture
def released(monkeypatch) -> list[str | None]:
    """Record the trace id bound at each sandbox-lease release."""
    from deerflow.trace_context import get_current_trace_id

    calls: list[str | None] = []
    monkeypatch.setattr(
        "deerflow.sandbox.lease.release_sandbox_execution_lease",
        lambda context: calls.append(get_current_trace_id()),
    )
    return calls


def test_closing_the_stream_releases_the_lease_inside_the_turns_trace_binding(monkeypatch, released):
    """The release must land while the turn's trace id is still bound.

    This is the assertion that goes red if the ``closing`` wrapper is dropped.
    Checking only *that* the lease came back is not enough: the wrapper is
    finalized during frame teardown either way, so a plain
    ``released == [...]`` after ``close()`` passes on the broken code too. What
    the fix actually changes is *when* — before or after ``stream()``'s
    ``finally`` has run ``reset_trace_id`` — so the trace id at release time is
    the only observable that distinguishes them, and it is the one the release's
    own logging correlates on.
    """
    _stub_agent_creation(monkeypatch, _NeverEndingAgent())
    client = _make_client()

    gen = client.stream("hi", thread_id="thread-abandoned-lease")
    next(gen)
    assert released == [], "the lease must still be held while the stream is live"

    gen.close()

    assert len(released) == 1, "the sandbox execution lease was not released"
    assert released[0] is not None, "the lease was released after the turn's trace binding was torn down"


def test_dropping_the_stream_without_closing_it_still_releases_the_lease(monkeypatch, released):
    """The GC path stays a safety net, not the mechanism.

    A caller that abandons the generator without calling ``close()`` must still
    get the lease back; this pins that the ``closing`` wrapper did not turn the
    fallback into a leak.
    """
    _stub_agent_creation(monkeypatch, _NeverEndingAgent())
    client = _make_client()

    gen = client.stream("hi", thread_id="thread-dropped-lease")
    next(gen)
    del gen

    import gc

    gc.collect()

    assert len(released) == 1


def test_an_exhausted_stream_releases_the_lease_exactly_once(monkeypatch, released):
    """A normal end-of-stream must not double-release.

    ``closing`` calls ``close()`` on a generator the ``for`` loop already drove
    to exhaustion; closing an exhausted generator is a no-op, so the ``finally``
    inside the wrapper must not run a second time.
    """

    class _ShortAgent:
        checkpointer = None
        store = None

        def stream(self, state, *, config, context, stream_mode):
            yield ("values", {"messages": [], "artifacts": []})

    _stub_agent_creation(monkeypatch, _ShortAgent())
    client = _make_client()

    list(client.stream("hi", thread_id="thread-exhausted-lease"))

    assert len(released) == 1
