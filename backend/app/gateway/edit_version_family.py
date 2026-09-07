"""Which threads make up one conversation, once its messages have been edited.

Editing a message does not rewrite a turn in place — it **branches the
conversation into a new thread** (fork feature: gaslight-mode edit versions, see
FORK.md §22). The reader still sees one conversation with a ``‹ 2/2 ›`` switcher,
and the sidebar still shows one entry, but the spend behind it is spread over
several thread ids: the turns before the edit were billed to the parent thread,
the replayed ones to the version thread.

Anything that has to answer *"what did this conversation cost"* therefore has to
work on the **family**, not the open thread. Aggregating one thread id reports
only the runs that happened to land in it — after an edit that is a total lower
than the money spent, and a chart missing the turns the reader can still see.

The family is described entirely by thread metadata written by the frontend
(``core/threads/edit-versions.ts``); this module is the server-side reader of the
same keys. Every field is validated on the way in: metadata is client-writable,
so a malformed or hostile value must degrade to "this thread stands alone"
rather than reach the aggregation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Metadata keys, mirroring ``frontend/src/core/threads/edit-versions.ts``. They
# are a wire contract between the two halves: renaming one here without the
# other silently returns every conversation to single-thread costing.
EDIT_VERSION_FLAG_KEY = "deerflow_edit_version"
EDIT_VERSION_GROUPS_KEY = "deerflow_edit_version_groups"
EDIT_ROOT_THREAD_ID_KEY = "edit_root_thread_id"
EDIT_PARENT_THREAD_ID_KEY = "edit_parent_thread_id"
EDIT_TURN_INDEX_KEY = "edit_turn_index"
EDIT_ANCESTORS_KEY = "edit_ancestor_thread_ids"

# A conversation cannot be edited without bound: this caps how many threads one
# family may pull into a single aggregation, so a corrupted (or crafted) group
# list cannot turn one cost request into an unbounded fan-out of store reads.
MAX_FAMILY_THREADS = 64
# Ancestry is a chain, and a deep one is already pathological; the walk is also
# cycle-guarded, so this only bounds the honest case.
MAX_LINEAGE_DEPTH = 32


@dataclass(frozen=True)
class VisibleAncestor:
    """An ancestor thread whose earlier turns this conversation still shows.

    ``inherited_turns`` is how many of that thread's own visible turns survived
    the branch — the edit replaced turn *n*, so turns ``0 … n-1`` are still on
    screen and turn *n* onward were replaced. Runs beyond that point were still
    paid for, so they stay in the total as replaced spend.
    """

    thread_id: str
    inherited_turns: int


@dataclass(frozen=True)
class EditVersionFamily:
    """Every thread whose spend belongs to one conversation's bill."""

    root_thread_id: str
    #: Root plus every version thread, including the open one.
    member_thread_ids: tuple[str, ...]
    #: Root → … → parent of the open thread, each with its surviving turn count.
    visible_ancestors: tuple[VisibleAncestor, ...]

    @property
    def is_single_thread(self) -> bool:
        """Whether this conversation has never been edited.

        The overwhelmingly common case, and the one that must stay on exactly
        the old code path: one member, no ancestors, nothing to merge.
        """
        return len(self.member_thread_ids) <= 1 and not self.visible_ancestors


def _metadata_of(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    metadata = record.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _read_thread_id(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _read_turn_index(metadata: dict[str, Any]) -> int:
    value = metadata.get(EDIT_TURN_INDEX_KEY)
    # ``bool`` is an ``int`` subclass and would silently read as turn 0/1.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _is_version_thread(metadata: dict[str, Any]) -> bool:
    return metadata.get(EDIT_VERSION_FLAG_KEY) is True


def _group_thread_ids(metadata: dict[str, Any]) -> list[str]:
    """Every thread id named by the root's version groups, order preserved."""
    groups = metadata.get(EDIT_VERSION_GROUPS_KEY)
    if not isinstance(groups, list):
        return []
    found: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        thread_ids = group.get("thread_ids")
        if not isinstance(thread_ids, list):
            continue
        for thread_id in thread_ids:
            if isinstance(thread_id, str) and thread_id:
                found.append(thread_id)
    return found


def _standalone(thread_id: str) -> EditVersionFamily:
    return EditVersionFamily(root_thread_id=thread_id, member_thread_ids=(thread_id,), visible_ancestors=())


async def resolve_edit_version_family(thread_store: Any, thread_id: str, *, user_id: str | None = None) -> EditVersionFamily:
    """Resolve the family the open thread belongs to.

    Never raises and never returns nothing: an unreadable store, absent
    metadata, a dangling parent, or a cycle all degrade to "this thread stands
    alone", which is exactly the pre-edit-versions behaviour. Costing one thread
    too few is a wrong number; failing the request takes the whole token counter
    down with it.
    """
    try:
        return await _resolve(thread_store, thread_id, user_id=user_id)
    except Exception:  # noqa: BLE001 - a cost overview must never fail the request
        logger.warning("thread token-usage: failed to resolve the edit-version family; costing the open thread alone", exc_info=True)
        return _standalone(thread_id)


async def _get_metadata(thread_store: Any, thread_id: str, *, user_id: str | None) -> dict[str, Any]:
    try:
        record = await thread_store.get(thread_id, user_id=user_id)
    except TypeError:
        # A store (or test double) whose ``get`` takes no ``user_id``.
        record = await thread_store.get(thread_id)
    return _metadata_of(record)


async def _resolve(thread_store: Any, thread_id: str, *, user_id: str | None) -> EditVersionFamily:
    if thread_store is None:
        return _standalone(thread_id)

    open_metadata = await _get_metadata(thread_store, thread_id, user_id=user_id)

    if _is_version_thread(open_metadata):
        root_thread_id = _read_thread_id(open_metadata, EDIT_ROOT_THREAD_ID_KEY) or thread_id
        root_metadata = open_metadata if root_thread_id == thread_id else await _get_metadata(thread_store, root_thread_id, user_id=user_id)
    else:
        # Not a version itself. It is the root of its own family — which is
        # still a family when the reader is looking at the *original* wording of
        # a turn they have since edited: those siblings' spend is theirs too.
        root_thread_id = thread_id
        root_metadata = open_metadata

    members = [root_thread_id]
    for member in _group_thread_ids(root_metadata):
        if member not in members:
            members.append(member)
        if len(members) >= MAX_FAMILY_THREADS:
            break
    if thread_id not in members:
        members.append(thread_id)

    visible_ancestors = await _walk_lineage(thread_store, thread_id, open_metadata, root_thread_id, user_id=user_id)

    return EditVersionFamily(
        root_thread_id=root_thread_id,
        member_thread_ids=tuple(members),
        visible_ancestors=visible_ancestors,
    )


async def _walk_lineage(
    thread_store: Any,
    thread_id: str,
    open_metadata: dict[str, Any],
    root_thread_id: str,
    *,
    user_id: str | None,
) -> tuple[VisibleAncestor, ...]:
    """Walk parent links from the open thread up to the root.

    Each hop tells us where the child branched off its parent, which is exactly
    how many of the parent's turns the reader still sees. Returned root-first,
    because that is the order the conversation is read (and charted) in.
    """
    ancestors: list[VisibleAncestor] = []
    metadata = open_metadata
    current = thread_id
    seen = {thread_id}
    while _is_version_thread(metadata):
        parent_id = _read_thread_id(metadata, EDIT_PARENT_THREAD_ID_KEY)
        if parent_id is None or parent_id in seen:
            # A dangling or looping parent link: stop rather than walk forever.
            # The turns above the break stay in the total as replaced spend,
            # which is the safe direction to be wrong in — money is never lost.
            break
        ancestors.append(VisibleAncestor(thread_id=parent_id, inherited_turns=_read_turn_index(metadata)))
        seen.add(parent_id)
        if len(ancestors) >= MAX_LINEAGE_DEPTH:
            break
        if parent_id == root_thread_id:
            break
        current = parent_id
        metadata = await _get_metadata(thread_store, current, user_id=user_id)
    ancestors.reverse()
    return tuple(ancestors)
