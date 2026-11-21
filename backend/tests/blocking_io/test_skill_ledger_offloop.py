"""Regression anchor: counting a skill load and queuing the curator stay off the event loop.

``record_skill_usage`` counts a load while the tool call or model call that
loaded the skill is still running on the loop, and ``aafter_agent`` queues the
curator; both hand storage resolution, the ledger's file lock and its writes
to the background recorder (FORK.md §55).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow.agents.lead_agent import prompt as prompt_module
from deerflow.agents.middlewares.completion_review_middleware import CompletionReviewMiddleware
from deerflow.agents.middlewares.skill_usage import flush_skill_ledger_jobs, record_skill_usage

pytestmark = pytest.mark.asyncio


class _Storage:
    def __init__(self, custom_root: Path) -> None:
        self.custom_root = custom_root
        self.enabled = {"stale": True}

    def get_user_custom_root(self) -> Path:
        return self.custom_root

    def load_skills(self, *, enabled_only: bool = False):
        return [SimpleNamespace(name=name, category="custom") for name, on in self.enabled.items() if on or not enabled_only]

    def read_history(self, name: str) -> list[dict]:
        return [{"ts": "2020-01-01T00:00:00+00:00", "action": "create", "author": "agent"}]

    def get_custom_skill_file(self, name: str) -> Path:
        return self.custom_root / name / "SKILL.md"

    def set_skill_enabled_state(self, name: str, enabled: bool) -> None:
        self.enabled[name] = enabled


def _seed_ledger(skills_root: Path) -> None:
    skills_root.mkdir(parents=True, exist_ok=True)
    tracking_since = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    (skills_root / "_skill_ledger.json").write_text(json.dumps({"version": 1, "skills": {}, "tracking_since": tracking_since}), encoding="utf-8")


async def test_a_load_and_the_curator_run_off_the_loop(tmp_path: Path, monkeypatch) -> None:
    storage = _Storage(tmp_path / "users" / "u1" / "skills" / "custom")
    await asyncio.to_thread(_seed_ledger, storage.custom_root.parent)
    monkeypatch.setattr("deerflow.skills.storage.get_or_new_user_skill_storage", lambda user_id, **_kw: storage)
    refreshed: list[str] = []
    monkeypatch.setattr(prompt_module, "invalidate_user_skill_cache", refreshed.append)
    monkeypatch.setattr(prompt_module, "publish_skills_cache_reset", lambda *, user_id=None: None)

    context = {"thread_id": "t1", "run_id": "r1", "user_id": "u1", "user_role": "admin", "app_config": SimpleNamespace(skill_evolution=SimpleNamespace(enabled=True))}
    runtime = SimpleNamespace(context=context)

    try:
        record_skill_usage(runtime, {"name": "report", "category": "custom"})
        middleware = CompletionReviewMiddleware(verify_code_edits=False, skill_learning=True, archive_unused_after_days=90)
        assert await middleware.aafter_agent({"messages": []}, runtime) is None
    finally:
        assert await asyncio.to_thread(flush_skill_ledger_jobs)

    ledger = json.loads(await asyncio.to_thread((storage.custom_root.parent / "_skill_ledger.json").read_text, encoding="utf-8"))
    assert ledger["skills"]["report"]["use_count"] == 1
    assert storage.enabled["stale"] is False and refreshed == ["u1"]
