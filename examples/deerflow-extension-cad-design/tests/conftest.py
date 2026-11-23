"""Fakes for the host: a principal, an AgentRuns handle and a registry."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
# Without an installed copy, import the API and this package from the checkout.
sys.path.insert(0, str(ROOT / "backend/packages/extension-api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow_extension_api import AgentRun, AgentRunError  # noqa: E402

from deerflow_extension_cad_design.actions import Designs  # noqa: E402
from deerflow_extension_cad_design.store import Store  # noqa: E402


class FakeRuns:
    def __init__(self):
        self.threads = []
        self.started = []
        self.cancelled = []
        self.status = "running"
        self.state = {"values": {"messages": []}}
        self.files = {}
        self.refuse = None
        self.deleted = []
        self.delete_refuse = None

    def for_plugin(self, namespace):
        self.namespace = namespace
        return self

    async def create_thread(self, *, assistant_id="lead_agent", thread_id=None, metadata=None, parent_thread_id=None):
        thread = f"thread-{len(self.threads) + 1}"
        self.threads.append({"thread_id": thread, "metadata": dict(metadata or {})})
        return thread

    async def delete_thread(self, *, thread_id):
        if self.delete_refuse:
            raise AgentRunError(*self.delete_refuse)
        self.deleted.append(thread_id)

    async def start(self, *, thread_id, input, context=None, idempotency_key=None, execution_fence=None, artifact_imports=None, stream_mode=None):
        if self.refuse:
            raise AgentRunError(*self.refuse)
        run_id = f"run-{len(self.started) + 1}"
        self.started.append({"thread_id": thread_id, "input": input, "context": context, "stream_mode": stream_mode, "run_id": run_id})
        return AgentRun(thread_id=thread_id, run_id=run_id, status="pending")

    async def get(self, *, thread_id, run_id):
        return AgentRun(thread_id=thread_id, run_id=run_id, status=self.status)

    async def get_state(self, *, thread_id):
        return self.state

    async def cancel(self, *, thread_id, run_id, execution_fence=None):
        self.cancelled.append((thread_id, run_id))

    async def read_artifact(self, *, thread_id, path, expected_checkpoint_id=None):
        if (thread_id, path) not in self.files:
            raise AgentRunError(404, "missing")
        return self.files[(thread_id, path)]


def action_context(user="alice", runs=None):
    return SimpleNamespace(principal=SimpleNamespace(user_id=user), settings={"enabled": True}, agent_runs=runs, interaction="session")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "designs.sqlite")


@pytest.fixture
def runs():
    return FakeRuns()


@pytest.fixture
def designs(store):
    return Designs(store, 65536)
