"""A conversation records which model it runs on, without moving in the sidebar.

The per-conversation model / subagent model / mode / reasoning effort used to
live only in the browser's ``localStorage``, which knows about the chats *this*
browser has touched under *this* origin. Everywhere else the selection fell back
to the app default, so opening an older conversation showed whichever model
happened to be selected last rather than the one that conversation had been
using. Recording it on the thread makes it a property of the conversation.

Two invariants, and both are silent when broken:

1. The value guard is strict. It decides whether a PATCH gets the "do not touch
   ``updated_at``" exemption, so a loose guard hands that exemption to arbitrary
   metadata writes — and the sidebar quietly stops re-sorting on real activity.
2. A workflow patch takes the exemption. Without it, changing a model bumps
   ``updated_at`` and the recency-ordered sidebar shoves that conversation to
   the top — reshuffling the list under the user's cursor for a change that is
   not activity at all.
"""

from __future__ import annotations

from app.gateway.routers.threads import _is_ui_placement_metadata_patch
from deerflow.persistence.thread_meta import (
    THREAD_ARCHIVED_METADATA_KEY,
    THREAD_FOLDER_METADATA_KEY,
    THREAD_PINNED_METADATA_KEY,
    THREAD_WORKFLOW_METADATA_KEY,
    is_valid_thread_workflow,
)
from deerflow.persistence.thread_meta.base import MAX_WORKFLOW_VALUE_CHARS


class TestTheValueGuard:
    def test_accepts_the_full_workflow(self) -> None:
        assert is_valid_thread_workflow(
            {
                "model_name": "claude-opus-5",
                "subagent_model_name": "ollama:llama3",
                "mode": "ultra",
                "reasoning_effort": "high",
            }
        )

    def test_accepts_a_partial_workflow(self) -> None:
        """A chat on the default mode records only what it has."""
        assert is_valid_thread_workflow({"model_name": "claude-opus-5"})

    def test_accepts_an_empty_workflow(self) -> None:
        """Clearing the record is a real state, not a malformed one."""
        assert is_valid_thread_workflow({})

    def test_rejects_an_unknown_key(self) -> None:
        """Otherwise any metadata rides in under the workflow key's exemption."""
        assert not is_valid_thread_workflow({"model_name": "x", "api_key": "sk-live-secret"})

    def test_rejects_a_non_string_value(self) -> None:
        assert not is_valid_thread_workflow({"model_name": {"nested": "object"}})
        assert not is_valid_thread_workflow({"mode": 5})
        assert not is_valid_thread_workflow({"mode": None})

    def test_rejects_a_non_dict(self) -> None:
        assert not is_valid_thread_workflow("claude-opus-5")
        assert not is_valid_thread_workflow(["claude-opus-5"])
        assert not is_valid_thread_workflow(None)

    def test_rejects_an_oversized_value(self) -> None:
        """The API is untrusted input and this is echoed on every thread read."""
        assert not is_valid_thread_workflow({"model_name": "x" * (MAX_WORKFLOW_VALUE_CHARS + 1)})
        assert is_valid_thread_workflow({"model_name": "x" * MAX_WORKFLOW_VALUE_CHARS})


class TestThePatchExemption:
    def test_a_workflow_patch_does_not_bump_the_timestamp(self) -> None:
        """Changing a model is not activity, so it must not reorder the list."""
        assert _is_ui_placement_metadata_patch({THREAD_WORKFLOW_METADATA_KEY: {"model_name": "claude-opus-5"}})

    def test_it_still_pairs_with_the_other_placement_keys(self) -> None:
        assert _is_ui_placement_metadata_patch(
            {
                THREAD_WORKFLOW_METADATA_KEY: {"mode": "pro"},
                THREAD_PINNED_METADATA_KEY: True,
                THREAD_FOLDER_METADATA_KEY: "folder-1",
                THREAD_ARCHIVED_METADATA_KEY: False,
            }
        )

    def test_a_malformed_workflow_falls_back_to_the_ordinary_path(self) -> None:
        """Not an error — it just does not get the exemption.

        This is the direction that matters: a rejected shape takes the normal
        metadata path (and bumps ``updated_at``), so a bad guard degrades the
        sidebar's ordering rather than letting arbitrary metadata through
        silently.
        """
        assert not _is_ui_placement_metadata_patch({THREAD_WORKFLOW_METADATA_KEY: {"model_name": 5}})
        assert not _is_ui_placement_metadata_patch({THREAD_WORKFLOW_METADATA_KEY: "claude-opus-5"})

    def test_an_unrelated_key_alongside_it_loses_the_exemption(self) -> None:
        assert not _is_ui_placement_metadata_patch({THREAD_WORKFLOW_METADATA_KEY: {"mode": "pro"}, "title": "renamed"})
