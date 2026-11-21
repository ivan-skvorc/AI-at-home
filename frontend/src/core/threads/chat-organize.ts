/**
 * Chat clean-up mode (fork feature): the client half of the organize pass.
 *
 * The user picks some conversations (or all of them) and a model. The model
 * reads each conversation through `POST /api/threads/{id}/organize/suggest`
 * and suggests a clearer title and a folder; in auto mode one more call,
 * `POST /api/chat-organize/consolidate`, merges the free categories into a few
 * folders. Both routes are **read-only**. What comes back is a plan the user
 * reviews and edits, and only an approved plan is written, through the
 * ordinary routes:
 *
 * - new folders: one whole-list `PUT /api/settings/chat-folders`, built in a
 *   single fold over a freshly fetched list (N `createFolder` calls would each
 *   start from the same stale list and keep only the last folder);
 * - placement: the placement-only `PATCH /api/threads/{id}` carrying nothing
 *   but `deerflow_folder`, which the Gateway exempts from bumping `updated_at`;
 * - titles: `POST /api/threads/{id}/state` with `preserve_recency`, so a bulk
 *   rename does not reshuffle the recency-ordered sidebar.
 *
 * Every write skips a no-op (a chat already in its target folder, a title
 * that is already the title), so applying the same plan twice writes nothing
 * the second time. A failed write is reported per conversation and never
 * retried on its own (workspace AGENTS.md).
 *
 * Nothing React here: the dialog in `components/workspace/chat-cleanup/` owns
 * the state, this module owns the rules, and the rules are unit-tested.
 */

import {
  GatewayApiError,
  throwGatewayApiError,
  UnauthorizedError,
} from "@/core/api/errors";
import { fetch as fetchWithAuth } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import type { Model } from "@/core/models/types";
import { isRecord } from "@/lib/utils";

import {
  BULK_THREAD_CONCURRENCY,
  httpStatusOf,
  settleWithConcurrency,
  uniqueThreadIds,
} from "./bulk";
import {
  addFolder,
  folderIdOfThread,
  MAX_CHAT_FOLDERS,
  normalizeFolderName,
  THREAD_FOLDER_METADATA_KEY,
  type ChatFolder,
} from "./chat-folders";
import type { AgentThread } from "./types";

/** How many conversations one pass reads. Mirrors the Gateway's consolidate cap. */
export const MAX_ORGANIZE_THREADS = 200;
/** Folders one suggest call may choose from (the registry's own cap). */
export const MAX_ORGANIZE_TARGETS = MAX_CHAT_FOLDERS;
export const DEFAULT_MAX_NEW_FOLDERS = 8;
/** The Gateway accepts `max_new_folders` in 1..20. */
export const MAX_NEW_FOLDERS_LIMIT = 20;
/**
 * A local model reads one conversation at a time: Ollama queues extra requests
 * out of sight (FORK.md §34), so three in flight would only turn two of them
 * into timeouts. A hosted model takes a few at once.
 */
export const LOCAL_MODEL_CONCURRENCY = 1;
export const HOSTED_MODEL_CONCURRENCY = 3;

// Typed folder names in targets mode do not exist yet, so the model is shown a
// placeholder id for each. The prefix cannot collide with a stored folder id
// (a UUID or `folder-...`), and the Gateway answers with one of the ids it was
// given, so a misspelled name can never come back as a phantom folder.
const NEW_TARGET_ID_PREFIX = "new:";
const AUTO_FOLDER_KEY_PREFIX = "auto:";
// The consolidate route caps these fields; trimming here keeps one long title
// from failing the whole request with a 422.
const MAX_CONSOLIDATE_CATEGORY_CHARS = 200;
const MAX_CONSOLIDATE_TEXT_CHARS = 1000;

export type OrganizeMode = "none" | "targets" | "auto";

/** A folder as the organize routes see it: its registry id and display name. */
export type FolderChoice = { id: string; name: string };

// ---------------------------------------------------------------------------
// Wire: the organize routes (read-only) and the two writes they lead to.
// ---------------------------------------------------------------------------

export type OrganizeSuggestion = {
  threadId: string;
  /** The title when the Gateway read the conversation. */
  currentTitle: string | null;
  /** The suggested title; equals `currentTitle` when the model kept it. */
  title: string | null;
  titleChanged: boolean;
  /** The operator turned renaming off (`title.enabled: false`). */
  renameDisabled: boolean;
  /** The chosen folder's id in targets mode, or null when none fits. */
  targetId: string | null;
  /** Auto mode's free category and one-line summary, for consolidation. */
  category: string | null;
  summary: string | null;
};

export type ConsolidatedFolder = {
  name: string;
  /** Set when the folder already exists; null means "create it". */
  existingFolderId: string | null;
  threadIds: string[];
};

export type ConsolidationResult = {
  folders: ConsolidatedFolder[];
  unfiled: string[];
};

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function malformedResponse(fallback: string): GatewayApiError {
  return new GatewayApiError({
    message: fallback,
    status: 502,
    code: "malformed_response",
    params: {},
    rawMessage: "",
  });
}

function threadUrl(threadId: string, suffix = ""): string {
  return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}${suffix}`;
}

/** Narrow a suggest response; a body that is not one throws rather than guessing. */
export function readOrganizeSuggestion(
  data: unknown,
  threadId: string,
): OrganizeSuggestion {
  if (!isRecord(data)) {
    throw malformedResponse("The conversation could not be analyzed.");
  }
  return {
    threadId,
    currentTitle: optionalString(data.current_title),
    title: optionalString(data.title),
    titleChanged: data.title_changed === true,
    renameDisabled: data.rename_disabled === true,
    targetId: optionalString(data.target_id),
    category: optionalString(data.category),
    summary: optionalString(data.summary),
  };
}

/** Narrow a consolidate response, dropping malformed entries. */
export function readConsolidation(data: unknown): ConsolidationResult {
  if (!isRecord(data) || !Array.isArray(data.folders)) {
    throw malformedResponse("The folders could not be generated.");
  }
  const folders: ConsolidatedFolder[] = [];
  for (const entry of data.folders) {
    if (!isRecord(entry) || typeof entry.name !== "string") {
      continue;
    }
    const threadIds = Array.isArray(entry.thread_ids)
      ? entry.thread_ids.filter((id): id is string => typeof id === "string")
      : [];
    folders.push({
      name: entry.name,
      existingFolderId: optionalString(entry.existing_folder_id),
      threadIds,
    });
  }
  const unfiled = Array.isArray(data.unfiled)
    ? data.unfiled.filter((id): id is string => typeof id === "string")
    : [];
  return { folders, unfiled };
}

export type OrganizeRequestOptions = {
  /** Omitted (not sent as null) for the operator's title model. */
  modelName?: string;
  rename: boolean;
  mode: OrganizeMode;
  /** Targets mode: the folders the model may choose from. */
  targets: readonly FolderChoice[];
  /** Auto mode: the user's folders, offered for reuse. */
  existing: readonly FolderChoice[];
};

/** Ask the Gateway for one conversation's title and folder. Writes nothing. */
export async function suggestThreadOrganization({
  threadId,
  modelName,
  rename,
  mode,
  targets,
  existing,
  signal,
}: OrganizeRequestOptions & {
  threadId: string;
  signal?: AbortSignal;
}): Promise<OrganizeSuggestion> {
  const body: Record<string, unknown> = { rename, mode };
  if (modelName) {
    body.model_name = modelName;
  }
  if (mode === "targets") {
    body.targets = targets;
  }
  if (mode === "auto" && existing.length > 0) {
    body.existing = existing;
  }
  const response = await fetchWithAuth(
    threadUrl(threadId, "/organize/suggest"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(
      response,
      "The conversation could not be analyzed.",
    );
  }
  return readOrganizeSuggestion(await response.json(), threadId);
}

export type ConsolidationItem = {
  thread_id: string;
  category: string;
  title?: string;
  summary?: string;
};

/** Merge auto mode's free categories into folders (auto mode only). Writes nothing. */
export async function consolidateChatCategories({
  modelName,
  items,
  existing,
  maxNewFolders,
  minGroupSize,
  signal,
}: {
  modelName?: string;
  items: readonly ConsolidationItem[];
  existing: readonly FolderChoice[];
  maxNewFolders: number;
  minGroupSize: number;
  signal?: AbortSignal;
}): Promise<ConsolidationResult> {
  const response = await fetchWithAuth(
    `${getBackendBaseURL()}/api/chat-organize/consolidate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...(modelName ? { model_name: modelName } : {}),
        items,
        existing,
        max_new_folders: maxNewFolders,
        min_group_size: minGroupSize,
      }),
      signal,
    },
  );
  if (!response.ok) {
    await throwGatewayApiError(response, "The folders could not be generated.");
  }
  return readConsolidation(await response.json());
}

/**
 * Rename without moving the conversation to the top of the sidebar.
 *
 * The ordinary rename (`useRenameThread`) bumps `updated_at`, which is right
 * for a person retitling the chat they are in and wrong for a pass over two
 * hundred old ones. `preserve_recency` keeps the checkpoint write identical and
 * only stops the display-name sync from touching the timestamp; the 409 while a
 * run is in flight still applies.
 */
export async function renameThreadKeepingRecency(
  threadId: string,
  title: string,
): Promise<void> {
  const response = await fetchWithAuth(threadUrl(threadId, "/state"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values: { title }, preserve_recency: true }),
  });
  if (!response.ok) {
    await throwGatewayApiError(response, "The conversation was not renamed.");
  }
}

/**
 * File a conversation into a folder with the placement-only PATCH.
 *
 * The body carries `deerflow_folder` and nothing else: the Gateway's exemption
 * from bumping `updated_at` is guarded per key, so adding any other metadata
 * key here (an "organized" marker, say) would quietly reorder the sidebar.
 */
export async function fileThreadInFolder(
  threadId: string,
  folderId: string,
): Promise<Record<string, unknown>> {
  const response = await fetchWithAuth(threadUrl(threadId), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      metadata: { [THREAD_FOLDER_METADATA_KEY]: folderId },
    }),
  });
  if (!response.ok) {
    await throwGatewayApiError(response, "The conversation was not moved.");
  }
  const data: unknown = await response.json().catch(() => null);
  return isRecord(data) && isRecord(data.metadata) ? data.metadata : {};
}

// ---------------------------------------------------------------------------
// Setup: model, pace, remembered preferences, the thread list, the targets.
// ---------------------------------------------------------------------------

/**
 * The model a pass will actually run on: the user's pick, else the operator's
 * `title.model_name`, else the Gateway's default model (the first configured,
 * which the catalog lists first). Null when it cannot be told.
 */
export function resolveOrganizeModel(
  models: readonly Model[],
  picked: string | undefined,
  operatorTitleModel: string | null | undefined,
): Model | null {
  const name = picked ?? operatorTitleModel ?? undefined;
  if (name) {
    return models.find((model) => model.name === name) ?? null;
  }
  return models[0] ?? null;
}

/**
 * Suggest calls in flight at once. A model with on-disk weights (`size_bytes`,
 * written by the Ollama sync) is local; an unknown model is treated as local
 * too, because the cost of guessing wrong is a slower pass, not a pile of
 * timeouts.
 */
export function organizeConcurrency(
  model: Pick<Model, "size_bytes"> | null,
): number {
  if (!model) {
    return LOCAL_MODEL_CONCURRENCY;
  }
  return typeof model.size_bytes === "number" && model.size_bytes > 0
    ? LOCAL_MODEL_CONCURRENCY
    : HOSTED_MODEL_CONCURRENCY;
}

export type ChatCleanupPreferences = {
  modelName: string | undefined;
  rename: boolean;
  folderMode: OrganizeMode;
  maxNewFolders: number;
};

export function clampMaxNewFolders(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return DEFAULT_MAX_NEW_FOLDERS;
  }
  return Math.min(MAX_NEW_FOLDERS_LIMIT, Math.max(1, Math.round(value)));
}

/**
 * The dialog's remembered setup, repaired: a model that has left the catalog
 * falls back to the server default rather than leaving the picker on a name
 * the Gateway refuses with a 400, and a hand-edited mode or cap snaps back.
 */
export function readCleanupPreferences(
  stored: Partial<ChatCleanupPreferences> | undefined,
  models: readonly Pick<Model, "name">[],
): ChatCleanupPreferences {
  const modelName = stored?.modelName;
  return {
    modelName:
      typeof modelName === "string" &&
      models.some((model) => model.name === modelName)
        ? modelName
        : undefined,
    rename: stored?.rename !== false,
    folderMode:
      stored?.folderMode === "none" ||
      stored?.folderMode === "targets" ||
      stored?.folderMode === "auto"
        ? stored.folderMode
        : "auto",
    maxNewFolders: clampMaxNewFolders(stored?.maxNewFolders),
  };
}

/** One conversation as the pass needs it. */
export type OrganizeThreadInfo = {
  threadId: string;
  title: string | null;
  folderId: string | null;
};

export function toOrganizeThreadInfo(
  thread: Pick<AgentThread, "thread_id" | "values" | "metadata">,
): OrganizeThreadInfo {
  const title: unknown = thread.values?.title;
  return {
    threadId: thread.thread_id,
    title: typeof title === "string" && title.trim() ? title : null,
    folderId: folderIdOfThread(thread),
  };
}

/**
 * The comparison key for folder names: trimmed, inner whitespace collapsed,
 * case-folded. "Work" and " work " are one folder; that is what keeps a second
 * pass from creating "Work" next to the "work" the first one made.
 */
export function folderNameKey(name: string): string | null {
  const normalized = normalizeFolderName(name);
  return normalized
    ? normalized.replace(/\s+/g, " ").toLocaleLowerCase()
    : null;
}

/** A folder the plan would create. `key` is unique within one plan. */
export type ProposedFolder = { key: string; name: string };

/**
 * Targets mode's folder list: the existing folders the user ticked, then the
 * names they typed. A typed name that matches an existing folder (ignoring
 * case) is that folder, not a second one. Capped at {@link MAX_ORGANIZE_TARGETS}.
 */
export function buildTargetChoices(
  folders: readonly ChatFolder[],
  selectedFolderIds: readonly string[],
  newFolderNames: readonly string[],
): { targets: FolderChoice[]; proposed: ProposedFolder[] } {
  const targets: FolderChoice[] = [];
  const proposed: ProposedFolder[] = [];
  const takenKeys = new Set<string>();
  const takenIds = new Set<string>();
  const pushExisting = (folder: ChatFolder) => {
    const key = folderNameKey(folder.name);
    if (!key || takenIds.has(folder.id) || takenKeys.has(key)) {
      return;
    }
    takenIds.add(folder.id);
    takenKeys.add(key);
    targets.push({ id: folder.id, name: folder.name });
  };
  for (const folderId of selectedFolderIds) {
    const folder = folders.find((candidate) => candidate.id === folderId);
    if (folder) {
      pushExisting(folder);
    }
  }
  newFolderNames.forEach((raw, index) => {
    const name = normalizeFolderName(raw);
    const key = name ? folderNameKey(name) : null;
    if (!name || !key || takenKeys.has(key)) {
      return;
    }
    const existing = folders.find(
      (folder) => folderNameKey(folder.name) === key,
    );
    if (existing) {
      pushExisting(existing);
      return;
    }
    const id = `${NEW_TARGET_ID_PREFIX}${index}`;
    takenKeys.add(key);
    targets.push({ id, name });
    proposed.push({ key: id, name });
  });
  const capped = targets.slice(0, MAX_ORGANIZE_TARGETS);
  const kept = new Set(capped.map((target) => target.id));
  return {
    targets: capped,
    proposed: proposed.filter((folder) => kept.has(folder.key)),
  };
}

/** The user's folders as auto mode offers them for reuse. */
export function existingFolderChoices(
  folders: readonly ChatFolder[],
): FolderChoice[] {
  return folders
    .slice(0, MAX_ORGANIZE_TARGETS)
    .map((folder) => ({ id: folder.id, name: folder.name }));
}

// ---------------------------------------------------------------------------
// Run: one suggest call per conversation, then (auto) one consolidation.
// ---------------------------------------------------------------------------

export type OrganizeFailure = {
  threadId: string;
  status: number | undefined;
  code: string | null;
  message: string;
};

/** Why a whole pass stopped: the same answer would come back for every chat. */
export type OrganizeStop = {
  status: number | undefined;
  code: string | null;
  message: string;
};

export type OrganizeCollection = {
  /** In the order the conversations were given. */
  suggestions: OrganizeSuggestion[];
  failures: OrganizeFailure[];
  stop: OrganizeStop | null;
};

/**
 * Statuses that are about the request, not the conversation: an unknown model
 * (400), a signed-out session (401), the spend cap (402), a model the role may
 * not use (403), a folder list the model cannot take (422). Asking again for
 * the next conversation would fail the same way — and for 402, spend nothing
 * more is the whole point.
 */
const STOPPING_STATUSES: ReadonlySet<number> = new Set([
  400, 401, 402, 403, 422,
]);

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "";
}

function errorCode(error: unknown): string | null {
  if (typeof error !== "object" || error === null) {
    return null;
  }
  const code = Reflect.get(error, "code");
  return typeof code === "string" && code ? code : null;
}

/**
 * Run the suggest call over every conversation with at most `concurrency` in
 * flight, stopping the whole pass on the first request-level refusal.
 *
 * A stop aborts the calls still in flight; their aborts are not reported as
 * per-conversation failures. So does the caller's `signal` (Cancel, or the
 * dialog closing), after which the result is simply discarded.
 */
export async function collectOrganizeSuggestions({
  threadIds,
  options,
  concurrency,
  signal,
  suggest = suggestThreadOrganization,
  onProgress,
}: {
  threadIds: readonly string[];
  options: OrganizeRequestOptions;
  concurrency: number;
  signal?: AbortSignal;
  suggest?: typeof suggestThreadOrganization;
  onProgress?: (done: number, total: number) => void;
}): Promise<OrganizeCollection> {
  const ids = uniqueThreadIds(threadIds);
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  if (signal?.aborted) {
    controller.abort();
  } else {
    signal?.addEventListener("abort", forwardAbort, { once: true });
  }
  const results = new Map<string, OrganizeSuggestion>();
  const failures: OrganizeFailure[] = [];
  let stop: OrganizeStop | null = null;
  let next = 0;
  let done = 0;

  const worker = async () => {
    while (!controller.signal.aborted && next < ids.length) {
      const threadId = ids[next]!;
      next += 1;
      try {
        results.set(
          threadId,
          await suggest({ threadId, ...options, signal: controller.signal }),
        );
      } catch (error) {
        if (controller.signal.aborted) {
          // Cancelled, or another call stopped the pass: not this chat's fault.
          break;
        }
        // A signed-out session has already started the login redirect; every
        // later call would do the same.
        const status =
          error instanceof UnauthorizedError ? 401 : httpStatusOf(error);
        const failure: OrganizeFailure = {
          threadId,
          status,
          code: errorCode(error),
          message: errorMessage(error),
        };
        if (status === undefined ? false : STOPPING_STATUSES.has(status)) {
          stop ??= {
            status: failure.status,
            code: failure.code,
            message: failure.message,
          };
          controller.abort();
          break;
        }
        failures.push(failure);
      }
      done += 1;
      onProgress?.(done, ids.length);
    }
  };

  try {
    await Promise.all(
      Array.from(
        { length: Math.max(1, Math.min(concurrency, ids.length)) },
        worker,
      ),
    );
  } finally {
    signal?.removeEventListener("abort", forwardAbort);
  }
  return {
    suggestions: ids.flatMap((id) => {
      const suggestion = results.get(id);
      return suggestion ? [suggestion] : [];
    }),
    failures,
    stop,
  };
}

/** Auto mode's consolidation input: the conversations that got a category. */
export function buildConsolidationItems(
  suggestions: readonly OrganizeSuggestion[],
): ConsolidationItem[] {
  return suggestions.flatMap((suggestion) => {
    const category = suggestion.category?.trim();
    if (!category) {
      return [];
    }
    const title = (suggestion.title ?? suggestion.currentTitle)?.trim();
    const summary = suggestion.summary?.trim();
    return [
      {
        thread_id: suggestion.threadId,
        category: category.slice(0, MAX_CONSOLIDATE_CATEGORY_CHARS),
        ...(title ? { title: title.slice(0, MAX_CONSOLIDATE_TEXT_CHARS) } : {}),
        ...(summary
          ? { summary: summary.slice(0, MAX_CONSOLIDATE_TEXT_CHARS) }
          : {}),
      },
    ];
  });
}

/**
 * How many conversations a NEW folder needs. Two keeps a large pass from
 * scattering one-chat folders; a pass over three chats would otherwise file
 * nothing at all unless two happened to share a topic.
 */
export function consolidationMinGroupSize(itemCount: number): number {
  return itemCount < 4 ? 1 : 2;
}

// ---------------------------------------------------------------------------
// Plan: what the preview shows and the user edits. Nothing is written yet.
// ---------------------------------------------------------------------------

export type OrganizeTarget =
  | { kind: "keep" }
  | { kind: "existing"; folderId: string }
  | { kind: "new"; key: string };

export type OrganizePlanItem = {
  threadId: string;
  currentTitle: string | null;
  currentFolderId: string | null;
  /** What the model suggested; null when it kept the title or did not rename. */
  suggestedTitle: string | null;
  /** The title to apply, editable. Blank or equal to the current one = keep. */
  title: string;
  target: OrganizeTarget;
  include: boolean;
};

export type OrganizePlan = {
  items: OrganizePlanItem[];
  /** Folders the plan would create; edited (renamed, merged) in the preview. */
  proposedFolders: ProposedFolder[];
};

/** The title an item would be renamed to, or null for "leave it". */
export function pendingTitle(item: OrganizePlanItem): string | null {
  const title = item.title.trim();
  if (!title || title === (item.currentTitle ?? "").trim()) {
    return null;
  }
  return title;
}

/** Whether applying the item would move it. */
export function pendingFolderChange(item: OrganizePlanItem): boolean {
  switch (item.target.kind) {
    case "keep":
      return false;
    case "existing":
      return item.target.folderId !== item.currentFolderId;
    case "new":
      return true;
  }
}

export function itemHasChanges(item: OrganizePlanItem): boolean {
  return pendingTitle(item) !== null || pendingFolderChange(item);
}

/** Items that the Apply button would write. */
export function applicableItems(plan: OrganizePlan): OrganizePlanItem[] {
  return plan.items.filter((item) => item.include && itemHasChanges(item));
}

/**
 * Turn the suggestions into a plan.
 *
 * Targets mode maps each `target_id` back to the folder it names (an existing
 * one, or a typed name the plan would create). Auto mode maps the
 * consolidation: a folder the Gateway matched to an existing one files there,
 * a new name that equals an existing folder's (ignoring case) is that folder,
 * and the rest become proposed folders, one per distinct name. A conversation
 * the model left unfiled keeps its place.
 */
export function buildOrganizePlan({
  threads,
  suggestions,
  mode,
  folders,
  proposed = [],
  consolidation = null,
}: {
  threads: readonly OrganizeThreadInfo[];
  suggestions: readonly OrganizeSuggestion[];
  mode: OrganizeMode;
  folders: readonly ChatFolder[];
  /** Targets mode: the typed folder names, keyed by their placeholder id. */
  proposed?: readonly ProposedFolder[];
  consolidation?: ConsolidationResult | null;
}): OrganizePlan {
  const infoById = new Map(threads.map((info) => [info.threadId, info]));
  const folderIds = new Set(folders.map((folder) => folder.id));
  const folderIdByKey = new Map<string, string>();
  for (const folder of folders) {
    const key = folderNameKey(folder.name);
    if (key && !folderIdByKey.has(key)) {
      folderIdByKey.set(key, folder.id);
    }
  }
  const proposedFolders: ProposedFolder[] =
    mode === "targets" ? [...proposed] : [];
  const proposedKeys = new Set(proposedFolders.map((folder) => folder.key));

  const autoTargets = new Map<string, OrganizeTarget>();
  if (mode === "auto" && consolidation) {
    const proposedKeyByName = new Map<string, string>();
    for (const folder of consolidation.folders) {
      let target: OrganizeTarget | null = null;
      if (folder.existingFolderId && folderIds.has(folder.existingFolderId)) {
        target = { kind: "existing", folderId: folder.existingFolderId };
      } else {
        const name = normalizeFolderName(folder.name);
        const nameKey = name ? folderNameKey(name) : null;
        if (name && nameKey) {
          const existingId = folderIdByKey.get(nameKey);
          if (existingId) {
            target = { kind: "existing", folderId: existingId };
          } else {
            let key = proposedKeyByName.get(nameKey);
            if (!key) {
              key = `${AUTO_FOLDER_KEY_PREFIX}${proposedKeyByName.size}`;
              proposedKeyByName.set(nameKey, key);
              proposedFolders.push({ key, name });
            }
            target = { kind: "new", key };
          }
        }
      }
      if (!target) {
        continue;
      }
      for (const threadId of folder.threadIds) {
        if (!autoTargets.has(threadId)) {
          autoTargets.set(threadId, target);
        }
      }
    }
  }

  const items = suggestions.map((suggestion): OrganizePlanItem => {
    const info = infoById.get(suggestion.threadId);
    const currentTitle = suggestion.currentTitle ?? info?.title ?? null;
    const suggested = suggestion.title?.trim();
    const suggestedTitle =
      suggestion.titleChanged && suggested ? suggested : null;
    let target: OrganizeTarget = { kind: "keep" };
    if (mode === "targets" && suggestion.targetId) {
      if (proposedKeys.has(suggestion.targetId)) {
        target = { kind: "new", key: suggestion.targetId };
      } else if (folderIds.has(suggestion.targetId)) {
        target = { kind: "existing", folderId: suggestion.targetId };
      }
    } else if (mode === "auto") {
      target = autoTargets.get(suggestion.threadId) ?? target;
    }
    const item: OrganizePlanItem = {
      threadId: suggestion.threadId,
      currentTitle,
      currentFolderId: info?.folderId ?? null,
      suggestedTitle,
      title: suggestedTitle ?? currentTitle ?? "",
      target,
      include: false,
    };
    return { ...item, include: itemHasChanges(item) };
  });
  return { items, proposedFolders: referencedFolders(items, proposedFolders) };
}

function referencedFolders(
  items: readonly OrganizePlanItem[],
  proposedFolders: readonly ProposedFolder[],
): ProposedFolder[] {
  const referenced = new Set(
    items.flatMap((item) =>
      item.target.kind === "new" ? [item.target.key] : [],
    ),
  );
  return proposedFolders.filter((folder) => referenced.has(folder.key));
}

/** Edit one row. Changing what a row does re-ticks it; the user can untick. */
export function updatePlanItem(
  plan: OrganizePlan,
  threadId: string,
  patch: Partial<Pick<OrganizePlanItem, "title" | "target" | "include">>,
): OrganizePlan {
  return {
    ...plan,
    items: plan.items.map((item) => {
      if (item.threadId !== threadId) {
        return item;
      }
      const next = { ...item, ...patch };
      if (
        patch.include === undefined &&
        (patch.title !== undefined || patch.target)
      ) {
        next.include = itemHasChanges(next);
      }
      return next;
    }),
  };
}

export function setAllIncluded(
  plan: OrganizePlan,
  include: boolean,
): OrganizePlan {
  return {
    ...plan,
    items: plan.items.map((item) =>
      item.include === include ? item : { ...item, include },
    ),
  };
}

/** Rename a proposed folder. A blank name changes nothing. */
export function renameProposedFolder(
  plan: OrganizePlan,
  key: string,
  rawName: string,
): OrganizePlan {
  const name = normalizeFolderName(rawName);
  if (!name) {
    return plan;
  }
  return {
    ...plan,
    proposedFolders: plan.proposedFolders.map((folder) =>
      folder.key === key ? { ...folder, name } : folder,
    ),
  };
}

/**
 * Fold a proposed folder into another target — another proposed folder, an
 * existing folder, or "keep" (unfile them) — and drop it from the plan.
 */
export function mergeProposedFolder(
  plan: OrganizePlan,
  key: string,
  into: OrganizeTarget,
): OrganizePlan {
  if (into.kind === "new" && into.key === key) {
    return plan;
  }
  const items = plan.items.map((item) => {
    if (item.target.kind !== "new" || item.target.key !== key) {
      return item;
    }
    const next = { ...item, target: into };
    return { ...next, include: itemHasChanges(next) && item.include };
  });
  return {
    items,
    proposedFolders: referencedFolders(
      items,
      plan.proposedFolders.filter((folder) => folder.key !== key),
    ),
  };
}

// ---------------------------------------------------------------------------
// Apply: folders in one fold and one PUT, then per-chat move and rename.
// ---------------------------------------------------------------------------

/**
 * Create every named folder in **one** fold over `folders`.
 *
 * A name that matches an existing folder (ignoring case and spacing), or a
 * name earlier in this same call, reuses that folder's id. `addFolder` refuses
 * a blank name and anything past {@link MAX_CHAT_FOLDERS}; those answer `null`.
 * Returns the same `folders` reference when nothing was created, so a caller
 * can skip the write.
 */
export function foldNewFolders(
  folders: readonly ChatFolder[],
  names: readonly string[],
  newId: () => string,
): {
  next: readonly ChatFolder[];
  ids: Array<string | null>;
  created: string[];
} {
  const idByKey = new Map<string, string>();
  for (const folder of folders) {
    const key = folderNameKey(folder.name);
    if (key && !idByKey.has(key)) {
      idByKey.set(key, folder.id);
    }
  }
  let next = folders;
  const created: string[] = [];
  const ids = names.map((raw) => {
    const name = normalizeFolderName(raw);
    const key = name ? folderNameKey(name) : null;
    if (!name || !key) {
      return null;
    }
    const existing = idByKey.get(key);
    if (existing) {
      return existing;
    }
    const id = newId();
    const added = addFolder(next, { id, name, parentId: null });
    if (added === next) {
      return null;
    }
    next = added;
    idByKey.set(key, id);
    created.push(id);
    return id;
  });
  return { next, ids, created };
}

export type OrganizeApplyFailureReason =
  /** The folder vanished (deleted elsewhere) before the move. */
  | "folder_missing"
  /** The folder write failed, so the folder this chat was meant for does not exist. */
  | "folder_not_created"
  /** The folder list is full ({@link MAX_CHAT_FOLDERS}). */
  | "folder_limit"
  /** The write itself was refused; `status` says why (409: a run is in flight). */
  | "request_failed";

export type OrganizeStepResult =
  | { state: "done" }
  | { state: "skipped" }
  | {
      state: "failed";
      reason: OrganizeApplyFailureReason;
      status?: number;
      message?: string;
    };

export type OrganizeItemResult = {
  threadId: string;
  move: OrganizeStepResult;
  rename: OrganizeStepResult;
  /** The folder the chat was moved into, when it was. */
  folderId: string | null;
  /** The title it was renamed to, when it was. */
  title: string | null;
};

export type OrganizeApplyOutcome =
  | { status: "folders_unavailable" }
  | {
      status: "applied";
      results: OrganizeItemResult[];
      /** The folder list after the write (the server's normalized copy), when read. */
      folders: ChatFolder[] | null;
      /** Proposed folder key -> the stored folder it became. */
      folderIdsByKey: Record<string, string>;
      createdFolderIds: string[];
      folderSaveFailed: boolean;
    };

export type OrganizeApplyDeps = {
  fetchFolders: () => Promise<ChatFolder[] | null>;
  saveFolders: (next: readonly ChatFolder[]) => Promise<ChatFolder[] | null>;
  moveThread: (threadId: string, folderId: string) => Promise<void>;
  renameThread: (threadId: string, title: string) => Promise<void>;
  newFolderId: () => string;
  /**
   * Runs the folder read-modify-write. The dialog queues it behind the
   * sidebar's own folder writes (`CHAT_FOLDERS_MUTATION_SCOPE`), so a folder
   * the user created a moment ago is in the list this fold starts from.
   */
  serializeFolderWrite?: <T>(write: () => Promise<T>) => Promise<T>;
  concurrency?: number;
  onItem?: (result: OrganizeItemResult) => void;
};

function failed(
  reason: OrganizeApplyFailureReason,
  error?: unknown,
): OrganizeStepResult {
  const status = error === undefined ? undefined : httpStatusOf(error);
  const message = error === undefined ? undefined : errorMessage(error);
  return {
    state: "failed",
    reason,
    ...(status !== undefined ? { status } : {}),
    ...(message ? { message } : {}),
  };
}

/**
 * Write an approved plan.
 *
 * 1. When any included row moves, read the folder list fresh and stop with
 *    `folders_unavailable` if it cannot be read: a fold over an unknown list
 *    would PUT away every folder it did not know about.
 * 2. Create the needed folders in one fold and one PUT. Moves go only into ids
 *    the stored list (the server's normalized answer) contains.
 * 3. Per conversation, a few at a time: move, then rename, each on its own, so
 *    a rename refused while a run is in flight (409) still lets the chat be
 *    filed. A step with nothing to change is skipped, which is what makes
 *    applying the same plan twice a no-op the second time.
 */
export async function applyOrganizePlan(
  plan: OrganizePlan,
  deps: OrganizeApplyDeps,
): Promise<OrganizeApplyOutcome> {
  const items = applicableItems(plan);
  const folderIdsByKey: Record<string, string> = {};
  const keyFailures = new Map<string, OrganizeApplyFailureReason>();
  let validIds: ReadonlySet<string> = new Set();
  let stored: ChatFolder[] | null = null;
  let createdFolderIds: string[] = [];
  let folderSaveFailed = false;

  if (items.some(pendingFolderChange)) {
    const neededKeys = [
      ...new Set(
        items.flatMap((item) =>
          item.target.kind === "new" ? [item.target.key] : [],
        ),
      ),
    ];
    const proposals = neededKeys.flatMap((key) => {
      const folder = plan.proposedFolders.find(
        (candidate) => candidate.key === key,
      );
      return folder ? [folder] : [];
    });
    const serialize =
      deps.serializeFolderWrite ??
      (<T>(write: () => Promise<T>): Promise<T> => write());
    let step: {
      folders: ChatFolder[];
      ids: Array<string | null>;
      created: string[];
      saved: boolean;
    } | null;
    try {
      step = await serialize(async () => {
        const fresh = await deps.fetchFolders();
        if (!fresh) {
          return null;
        }
        const fold = foldNewFolders(
          fresh,
          proposals.map((folder) => folder.name),
          deps.newFolderId,
        );
        if (fold.next === fresh) {
          return { folders: fresh, ...fold, saved: true };
        }
        const saved = await deps.saveFolders(fold.next);
        return saved
          ? { folders: saved, ...fold, saved: true }
          : { folders: fresh, ...fold, saved: false };
      });
    } catch {
      step = null;
    }
    if (!step) {
      return { status: "folders_unavailable" };
    }
    const folderStep = step;
    stored = folderStep.folders;
    const storedIds = new Set(folderStep.folders.map((folder) => folder.id));
    validIds = storedIds;
    folderSaveFailed = !folderStep.saved;
    createdFolderIds = folderStep.saved
      ? folderStep.created.filter((id) => storedIds.has(id))
      : [];
    proposals.forEach((folder, index) => {
      const id = folderStep.ids[index];
      if (id && storedIds.has(id)) {
        folderIdsByKey[folder.key] = id;
      } else if (!id) {
        keyFailures.set(folder.key, "folder_limit");
      } else {
        keyFailures.set(
          folder.key,
          folderSaveFailed ? "folder_not_created" : "folder_missing",
        );
      }
    });
  }

  const move = async (item: OrganizePlanItem): Promise<OrganizeStepResult> => {
    if (!pendingFolderChange(item)) {
      return { state: "skipped" };
    }
    const targetId =
      item.target.kind === "existing"
        ? item.target.folderId
        : item.target.kind === "new"
          ? (folderIdsByKey[item.target.key] ?? null)
          : null;
    if (!targetId) {
      const key = item.target.kind === "new" ? item.target.key : "";
      return failed(keyFailures.get(key) ?? "folder_missing");
    }
    if (targetId === item.currentFolderId) {
      // A proposed name that turned out to be the folder it is already in.
      return { state: "skipped" };
    }
    if (!validIds.has(targetId)) {
      return failed("folder_missing");
    }
    try {
      await deps.moveThread(item.threadId, targetId);
      return { state: "done" };
    } catch (error) {
      return failed("request_failed", error);
    }
  };

  const rename = async (
    item: OrganizePlanItem,
  ): Promise<OrganizeStepResult> => {
    const title = pendingTitle(item);
    if (!title) {
      return { state: "skipped" };
    }
    try {
      await deps.renameThread(item.threadId, title);
      return { state: "done" };
    } catch (error) {
      return failed("request_failed", error);
    }
  };

  const settled = await settleWithConcurrency(
    items,
    deps.concurrency ?? BULK_THREAD_CONCURRENCY,
    async (item): Promise<OrganizeItemResult> => {
      // Move first, then rename, independently: neither outcome gates the other.
      const moveResult = await move(item);
      const renameResult = await rename(item);
      const target =
        item.target.kind === "existing"
          ? item.target.folderId
          : item.target.kind === "new"
            ? (folderIdsByKey[item.target.key] ?? null)
            : null;
      const result: OrganizeItemResult = {
        threadId: item.threadId,
        move: moveResult,
        rename: renameResult,
        folderId: moveResult.state === "done" ? target : null,
        title: renameResult.state === "done" ? pendingTitle(item) : null,
      };
      try {
        deps.onItem?.(result);
      } catch {
        // Progress display only; the write already happened.
      }
      return result;
    },
  );
  const results = settled.map((outcome, index): OrganizeItemResult => {
    if (outcome.status === "fulfilled") {
      return outcome.value;
    }
    // The task catches every write error itself; this is a bug guard.
    const threadId = items[index]!.threadId;
    return {
      threadId,
      move: failed("request_failed", outcome.reason),
      rename: { state: "skipped" },
      folderId: null,
      title: null,
    };
  });
  return {
    status: "applied",
    results,
    folders: stored,
    folderIdsByKey,
    createdFolderIds,
    folderSaveFailed,
  };
}

/**
 * Fold an apply's results back into the plan, so the preview shows what is
 * now true: moved chats sit in their folder, renamed ones carry their title,
 * created folders are existing folders, and only rows that still have
 * something to do stay ticked. Applying the result again writes nothing new;
 * the failed rows stay ticked for the user to retry by hand.
 */
export function applyResultsToPlan(
  plan: OrganizePlan,
  outcome: Extract<OrganizeApplyOutcome, { status: "applied" }>,
): OrganizePlan {
  const resultById = new Map(
    outcome.results.map((result) => [result.threadId, result]),
  );
  const items = plan.items.map((item) => {
    let next = item;
    if (next.target.kind === "new") {
      const folderId = outcome.folderIdsByKey[next.target.key];
      if (folderId) {
        next = { ...next, target: { kind: "existing", folderId } };
      }
    }
    const result = resultById.get(item.threadId);
    if (!result) {
      return next;
    }
    if (result.folderId) {
      next = { ...next, currentFolderId: result.folderId };
    }
    if (result.title) {
      next = { ...next, currentTitle: result.title, title: result.title };
    }
    return { ...next, include: itemHasChanges(next) };
  });
  return {
    items,
    proposedFolders: referencedFolders(items, plan.proposedFolders),
  };
}

export type OrganizeApplySummary = {
  renamed: number;
  moved: number;
  failed: number;
};

export function summarizeApply(
  results: readonly OrganizeItemResult[],
): OrganizeApplySummary {
  let renamed = 0;
  let moved = 0;
  let failedCount = 0;
  for (const result of results) {
    if (result.rename.state === "done") renamed += 1;
    if (result.move.state === "done") moved += 1;
    if (result.move.state === "failed" || result.rename.state === "failed") {
      failedCount += 1;
    }
  }
  return { renamed, moved, failed: failedCount };
}
