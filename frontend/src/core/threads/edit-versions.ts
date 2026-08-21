import type { AgentThread } from "./types";

/**
 * Hidden conversation versions created by editing a message.
 *
 * Editing a user message does not rewrite history in place. It creates a *new*
 * thread that carries the conversation up to the turn before the edited
 * message, then replays the edited message there. The original thread is left
 * untouched, so both readings of the conversation stay available.
 *
 * Two properties keep that from turning into a pile of look-alike chats in the
 * sidebar:
 *
 * - every version thread is flagged with {@link EDIT_VERSION_METADATA_KEY} and
 *   filtered out of the primary thread lists (`filterThreadSearchResults`), so
 *   the family shows up exactly once — as its root;
 * - the root records which version is currently "the" conversation
 *   ({@link EDIT_ACTIVE_VERSION_METADATA_KEY}), so the single sidebar entry
 *   opens the version the user last chose rather than always version 1.
 *
 * The switcher rendered on the edited message is derived entirely from the
 * root's {@link EDIT_VERSION_GROUPS_METADATA_KEY} list plus the open thread's
 * ancestry, so no extra per-message bookkeeping is needed.
 */

/** Set to `true` on every hidden version thread. */
export const EDIT_VERSION_METADATA_KEY = "deerflow_edit_version";
/** Root-thread key holding every {@link EditVersionGroup} in the family. */
export const EDIT_VERSION_GROUPS_METADATA_KEY = "deerflow_edit_version_groups";
/** Root-thread key naming the version its sidebar entry should open. */
export const EDIT_ACTIVE_VERSION_METADATA_KEY = "deerflow_edit_active_version";

export const EDIT_VERSION_ROOT_THREAD_ID_KEY = "edit_root_thread_id";
export const EDIT_VERSION_PARENT_THREAD_ID_KEY = "edit_parent_thread_id";
export const EDIT_VERSION_BASE_MESSAGE_ID_KEY = "edit_base_message_id";
export const EDIT_VERSION_TURN_INDEX_KEY = "edit_turn_index";
export const EDIT_VERSION_ANCESTORS_KEY = "edit_ancestor_thread_ids";

/**
 * Group key for an edit of the very first user message: there is no preceding
 * assistant message to branch from, so the empty string stands for "the start
 * of the conversation".
 */
export const CONVERSATION_START_BASE_MESSAGE_ID = "";

type ThreadMetadata = Record<string, unknown> | null | undefined;

type ThreadLike = Pick<AgentThread, "metadata"> | { metadata?: ThreadMetadata };

/**
 * One set of alternative readings of the same turn.
 *
 * `base_message_id` is the assistant message the versions branch from, which
 * makes it a lineage-safe key: two threads only ever agree on it when their
 * history up to that point is the same copied history. `turn_index` is carried
 * alongside purely so the UI can anchor the switcher without re-deriving it.
 */
export type EditVersionGroup = {
  base_message_id: string;
  turn_index: number;
  thread_ids: string[];
};

export type EditVersionThreadInfo = {
  rootThreadId: string;
  parentThreadId: string;
  baseMessageId: string;
  turnIndex: number;
  ancestorThreadIds: string[];
};

export type EditVersionSwitcher = {
  baseMessageId: string;
  turnIndex: number;
  threadIds: string[];
  currentIndex: number;
};

function metadataOf(thread: ThreadLike): ThreadMetadata {
  return thread.metadata as ThreadMetadata;
}

function readString(metadata: ThreadMetadata, key: string): string | null {
  const value = metadata?.[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readStringList(metadata: ThreadMetadata, key: string): string[] {
  const value = metadata?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(
    (entry): entry is string => typeof entry === "string" && entry.length > 0,
  );
}

export function isEditVersionThread(thread: ThreadLike) {
  return metadataOf(thread)?.[EDIT_VERSION_METADATA_KEY] === true;
}

export function readEditVersionThreadInfo(
  metadata: ThreadMetadata,
): EditVersionThreadInfo | null {
  if (metadata?.[EDIT_VERSION_METADATA_KEY] !== true) {
    return null;
  }
  const rootThreadId = readString(metadata, EDIT_VERSION_ROOT_THREAD_ID_KEY);
  const parentThreadId = readString(
    metadata,
    EDIT_VERSION_PARENT_THREAD_ID_KEY,
  );
  if (!rootThreadId || !parentThreadId) {
    return null;
  }
  const rawBaseMessageId = metadata?.[EDIT_VERSION_BASE_MESSAGE_ID_KEY];
  const rawTurnIndex = metadata?.[EDIT_VERSION_TURN_INDEX_KEY];
  return {
    rootThreadId,
    parentThreadId,
    baseMessageId:
      typeof rawBaseMessageId === "string"
        ? rawBaseMessageId
        : CONVERSATION_START_BASE_MESSAGE_ID,
    turnIndex:
      typeof rawTurnIndex === "number" && Number.isInteger(rawTurnIndex)
        ? rawTurnIndex
        : 0,
    ancestorThreadIds: readStringList(metadata, EDIT_VERSION_ANCESTORS_KEY),
  };
}

export function readEditVersionGroups(
  metadata: ThreadMetadata,
): EditVersionGroup[] {
  const raw = metadata?.[EDIT_VERSION_GROUPS_METADATA_KEY];
  if (!Array.isArray(raw)) {
    return [];
  }
  const groups: EditVersionGroup[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const candidate = entry as Record<string, unknown>;
    const baseMessageId = candidate.base_message_id;
    const turnIndex = candidate.turn_index;
    const threadIds = candidate.thread_ids;
    if (
      typeof baseMessageId !== "string" ||
      typeof turnIndex !== "number" ||
      !Number.isInteger(turnIndex) ||
      !Array.isArray(threadIds)
    ) {
      continue;
    }
    const ids = threadIds.filter(
      (id): id is string => typeof id === "string" && id.length > 0,
    );
    if (ids.length === 0) {
      continue;
    }
    groups.push({
      base_message_id: baseMessageId,
      turn_index: turnIndex,
      thread_ids: ids,
    });
  }
  return groups;
}

export function readActiveEditVersionThreadId(metadata: ThreadMetadata) {
  return readString(metadata, EDIT_ACTIVE_VERSION_METADATA_KEY);
}

/** The thread that owns the family's version groups (itself, when not a version). */
export function resolveEditVersionRootThreadId(
  threadId: string,
  metadata: ThreadMetadata,
) {
  return readEditVersionThreadInfo(metadata)?.rootThreadId ?? threadId;
}

/**
 * Root → … → `threadId`, oldest first.
 *
 * A thread's position inside a group is resolved through this chain, so a
 * grandchild still recognises the group its *parent* belongs to.
 */
export function resolveEditVersionLineage(
  threadId: string,
  metadata: ThreadMetadata,
): string[] {
  const info = readEditVersionThreadInfo(metadata);
  if (!info) {
    return [threadId];
  }
  const lineage = info.ancestorThreadIds.filter((id) => id !== threadId);
  return [...lineage, threadId];
}

export function buildEditVersionThreadMetadata({
  rootThreadId,
  parentThreadId,
  baseMessageId,
  turnIndex,
  parentLineage,
  agentName,
}: {
  rootThreadId: string;
  parentThreadId: string;
  baseMessageId: string;
  turnIndex: number;
  /** The parent's own lineage; the new thread's ancestry is that plus nothing. */
  parentLineage: string[];
  agentName?: string | null;
}): Record<string, unknown> {
  return {
    [EDIT_VERSION_METADATA_KEY]: true,
    [EDIT_VERSION_ROOT_THREAD_ID_KEY]: rootThreadId,
    [EDIT_VERSION_PARENT_THREAD_ID_KEY]: parentThreadId,
    [EDIT_VERSION_BASE_MESSAGE_ID_KEY]: baseMessageId,
    [EDIT_VERSION_TURN_INDEX_KEY]: turnIndex,
    [EDIT_VERSION_ANCESTORS_KEY]: parentLineage,
    ...(agentName ? { agent_name: agentName } : {}),
  };
}

/**
 * Append `versionThreadId` to the group it belongs to, creating the group from
 * `parentThreadId` when this is the first edit of that turn.
 *
 * The parent is recorded as version 1 because it is the thread whose reading of
 * the turn the edit is an alternative *to*.
 */
export function addEditVersionToGroups(
  groups: readonly EditVersionGroup[],
  {
    baseMessageId,
    turnIndex,
    parentThreadId,
    versionThreadId,
  }: {
    baseMessageId: string;
    turnIndex: number;
    parentThreadId: string;
    versionThreadId: string;
  },
): EditVersionGroup[] {
  let matched = false;
  const next = groups.map((group) => {
    if (group.base_message_id !== baseMessageId) {
      return group;
    }
    matched = true;
    if (group.thread_ids.includes(versionThreadId)) {
      return group;
    }
    return { ...group, thread_ids: [...group.thread_ids, versionThreadId] };
  });
  if (matched) {
    return next;
  }
  return [
    ...next,
    {
      base_message_id: baseMessageId,
      turn_index: turnIndex,
      thread_ids: [parentThreadId, versionThreadId],
    },
  ];
}

/**
 * Which switcher (if any) belongs on each turn of the thread whose ancestry is
 * `lineage`, keyed by the group's base message id.
 *
 * A group is only relevant to a thread when the thread — or one of its
 * ancestors — is one of its versions; the *deepest* such match is the version
 * currently being read.
 */
export function resolveEditVersionSwitchers(
  groups: readonly EditVersionGroup[],
  lineage: readonly string[],
): Map<string, EditVersionSwitcher> {
  const switchers = new Map<string, EditVersionSwitcher>();
  for (const group of groups) {
    if (group.thread_ids.length < 2) {
      continue;
    }
    let currentIndex = -1;
    let deepestLineagePosition = -1;
    group.thread_ids.forEach((threadId, index) => {
      const position = lineage.indexOf(threadId);
      if (position > deepestLineagePosition) {
        deepestLineagePosition = position;
        currentIndex = index;
      }
    });
    if (currentIndex < 0) {
      continue;
    }
    switchers.set(group.base_message_id, {
      baseMessageId: group.base_message_id,
      turnIndex: group.turn_index,
      threadIds: [...group.thread_ids],
      currentIndex,
    });
  }
  return switchers;
}
