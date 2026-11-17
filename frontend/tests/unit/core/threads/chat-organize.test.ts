import { beforeEach, describe, expect, rs, test } from "@rstest/core";

const mocks = rs.hoisted(() => ({ fetch: rs.fn() }));

rs.mock("@/core/api/fetcher", () => ({
  fetch: mocks.fetch,
  getCsrfHeaders: () => ({}),
}));

import { GatewayApiError } from "@/core/api/errors";
import type { Model } from "@/core/models/types";
import { MAX_CHAT_FOLDERS, type ChatFolder } from "@/core/threads/chat-folders";
import {
  applyOrganizePlan,
  applyResultsToPlan,
  buildConsolidationItems,
  buildOrganizePlan,
  buildTargetChoices,
  collectOrganizeSuggestions,
  fileThreadInFolder,
  foldNewFolders,
  mergeProposedFolder,
  organizeConcurrency,
  readCleanupPreferences,
  renameProposedFolder,
  renameThreadKeepingRecency,
  resolveOrganizeModel,
  suggestThreadOrganization,
  updatePlanItem,
  type OrganizeApplyDeps,
  type OrganizePlan,
  type OrganizePlanItem,
  type OrganizeSuggestion,
} from "@/core/threads/chat-organize";

/**
 * Clean-up mode's rules (fork feature). Each test pins a property that fails
 * silently when broken: a folder created twice, a chat moved into a folder the
 * server dropped, a rename failure that also loses the move, a second apply
 * that writes again, a spend-capped pass that keeps spending.
 */

beforeEach(() => {
  mocks.fetch.mockReset();
});

function httpError(status: number, message = `HTTP ${status}`, code = null) {
  return new GatewayApiError({
    message,
    status,
    code,
    params: {},
    rawMessage: message,
  });
}

function item(
  threadId: string,
  overrides: Partial<OrganizePlanItem> = {},
): OrganizePlanItem {
  return {
    threadId,
    currentTitle: `Old ${threadId}`,
    currentFolderId: null,
    suggestedTitle: null,
    title: `Old ${threadId}`,
    target: { kind: "keep" },
    include: true,
    ...overrides,
  };
}

type Calls = {
  fetches: number;
  saves: ChatFolder[][];
  moves: Array<[string, string]>;
  renames: Array<[string, string]>;
};

/** Deps over an in-memory folder store that normalizes like the server. */
function fakeDeps(
  initial: ChatFolder[],
  {
    fetchFails = false,
    saveFails = false,
    dropOnSave = [] as string[],
    moveError = {} as Record<string, Error>,
    renameError = {} as Record<string, Error>,
  } = {},
): { deps: OrganizeApplyDeps; calls: Calls; store: () => ChatFolder[] } {
  let stored = initial;
  let nextId = 0;
  const calls: Calls = { fetches: 0, saves: [], moves: [], renames: [] };
  const deps: OrganizeApplyDeps = {
    fetchFolders: async () => {
      calls.fetches += 1;
      return fetchFails ? null : [...stored];
    },
    saveFolders: async (next) => {
      calls.saves.push([...next]);
      if (saveFails) return null;
      stored = next
        .filter((folder) => !dropOnSave.includes(folder.name))
        .slice(0, MAX_CHAT_FOLDERS);
      return [...stored];
    },
    moveThread: async (threadId, folderId) => {
      if (moveError[threadId]) throw moveError[threadId];
      calls.moves.push([threadId, folderId]);
    },
    renameThread: async (threadId, title) => {
      if (renameError[threadId]) throw renameError[threadId];
      calls.renames.push([threadId, title]);
    },
    newFolderId: () => `created-${(nextId += 1)}`,
  };
  return { deps, calls, store: () => stored };
}

describe("folder creation is one fold", () => {
  test("creates every name in one pass, reusing existing folders regardless of case", () => {
    const folders: ChatFolder[] = [{ id: "work", name: "Work" }];
    let n = 0;
    const result = foldNewFolders(
      folders,
      ["  work ", "Recipes", "recipes", "Travel  plans", ""],
      () => `id-${(n += 1)}`,
    );
    expect(result.ids).toEqual(["work", "id-1", "id-1", "id-2", null]);
    expect(result.created).toEqual(["id-1", "id-2"]);
    expect(result.next).toEqual([
      { id: "work", name: "Work" },
      { id: "id-1", name: "Recipes" },
      { id: "id-2", name: "Travel  plans" },
    ]);
  });

  test("stops at the 50-folder cap and answers null past it", () => {
    const folders = Array.from({ length: MAX_CHAT_FOLDERS - 1 }, (_, i) => ({
      id: `f${i}`,
      name: `Folder ${i}`,
    }));
    let n = 0;
    const result = foldNewFolders(folders, ["Last one", "Too many"], () =>
      String((n += 1)),
    );
    expect(result.ids).toEqual(["1", null]);
    expect(result.next).toHaveLength(MAX_CHAT_FOLDERS);
  });

  test("answers the same list when nothing new is needed, so no write happens", () => {
    const folders: ChatFolder[] = [{ id: "work", name: "Work" }];
    const result = foldNewFolders(folders, ["WORK"], () => "unused");
    expect(result.next).toBe(folders);
    expect(result.created).toEqual([]);
  });
});

describe("applying a plan", () => {
  const proposedPlan = (): OrganizePlan => ({
    items: [
      item("a", { target: { kind: "new", key: "auto:0" } }),
      item("b", { target: { kind: "new", key: "auto:1" } }),
      item("c", { target: { kind: "new", key: "auto:0" } }),
      item("d", { target: { kind: "existing", folderId: "work" } }),
    ],
    proposedFolders: [
      { key: "auto:0", name: "Recipes" },
      { key: "auto:1", name: "travel" },
    ],
  });

  test("creates all new folders with a single PUT, then moves into them", async () => {
    const { deps, calls } = fakeDeps([
      { id: "work", name: "Work" },
      { id: "travel", name: "Travel" },
    ]);
    const outcome = await applyOrganizePlan(proposedPlan(), deps);

    expect(outcome.status).toBe("applied");
    expect(calls.fetches).toBe(1);
    expect(calls.saves).toHaveLength(1);
    // "travel" reused the existing "Travel"; only "Recipes" is new.
    expect(calls.saves[0]).toEqual([
      { id: "work", name: "Work" },
      { id: "travel", name: "Travel" },
      { id: "created-1", name: "Recipes" },
    ]);
    expect(calls.moves.sort()).toEqual([
      ["a", "created-1"],
      ["b", "travel"],
      ["c", "created-1"],
      ["d", "work"],
    ]);
    if (outcome.status === "applied") {
      expect(outcome.createdFolderIds).toEqual(["created-1"]);
      expect(outcome.folderIdsByKey).toEqual({
        "auto:0": "created-1",
        "auto:1": "travel",
      });
    }
  });

  test("moves only into folders the stored list contains", async () => {
    // The server's normalization dropped "Recipes" (as it would past its cap).
    const { deps, calls } = fakeDeps([{ id: "work", name: "Work" }], {
      dropOnSave: ["Recipes"],
    });
    const plan: OrganizePlan = {
      items: [
        item("a", { target: { kind: "new", key: "auto:0" } }),
        item("d", { target: { kind: "existing", folderId: "work" } }),
        item("e", { target: { kind: "existing", folderId: "gone" } }),
      ],
      proposedFolders: [{ key: "auto:0", name: "Recipes" }],
    };
    const outcome = await applyOrganizePlan(plan, deps);

    expect(calls.moves).toEqual([["d", "work"]]);
    if (outcome.status !== "applied") throw new Error("expected applied");
    const byId = new Map(outcome.results.map((r) => [r.threadId, r]));
    expect(byId.get("a")!.move).toMatchObject({
      state: "failed",
      reason: "folder_missing",
    });
    expect(byId.get("e")!.move).toMatchObject({
      state: "failed",
      reason: "folder_missing",
    });
  });

  test("an unreadable folder list writes nothing at all", async () => {
    const { deps, calls } = fakeDeps([], { fetchFails: true });
    const plan = proposedPlan();
    plan.items[0] = { ...plan.items[0]!, title: "A new title" };
    const outcome = await applyOrganizePlan(plan, deps);

    expect(outcome).toEqual({ status: "folders_unavailable" });
    expect(calls.saves).toEqual([]);
    expect(calls.moves).toEqual([]);
    expect(calls.renames).toEqual([]);
  });

  test("a failed folder write keeps moves into existing folders and reports the rest", async () => {
    const { deps, calls } = fakeDeps([{ id: "work", name: "Work" }], {
      saveFails: true,
    });
    const outcome = await applyOrganizePlan(proposedPlan(), deps);

    expect(calls.moves).toEqual([["d", "work"]]);
    if (outcome.status !== "applied") throw new Error("expected applied");
    expect(outcome.folderSaveFailed).toBe(true);
    expect(outcome.createdFolderIds).toEqual([]);
    const a = outcome.results.find((r) => r.threadId === "a")!;
    expect(a.move).toMatchObject({ reason: "folder_not_created" });
  });

  test("a full folder list reports the limit instead of moving", async () => {
    const full = Array.from({ length: MAX_CHAT_FOLDERS }, (_, i) => ({
      id: `f${i}`,
      name: `Folder ${i}`,
    }));
    const { deps, calls } = fakeDeps(full);
    const outcome = await applyOrganizePlan(
      {
        items: [item("a", { target: { kind: "new", key: "auto:0" } })],
        proposedFolders: [{ key: "auto:0", name: "One more" }],
      },
      deps,
    );
    expect(calls.saves).toEqual([]);
    if (outcome.status !== "applied") throw new Error("expected applied");
    expect(outcome.results[0]!.move).toMatchObject({ reason: "folder_limit" });
  });

  test("a refused rename does not block the move, nor a refused move the rename", async () => {
    const { deps, calls } = fakeDeps([{ id: "work", name: "Work" }], {
      renameError: { busy: httpError(409, "Thread has a run in flight.") },
      moveError: { gone: httpError(404) },
    });
    const outcome = await applyOrganizePlan(
      {
        items: [
          item("busy", {
            title: "Better title",
            target: { kind: "existing", folderId: "work" },
          }),
          item("gone", {
            title: "Another title",
            target: { kind: "existing", folderId: "work" },
          }),
        ],
        proposedFolders: [],
      },
      deps,
    );

    expect(calls.moves).toEqual([["busy", "work"]]);
    expect(calls.renames).toEqual([["gone", "Another title"]]);
    if (outcome.status !== "applied") throw new Error("expected applied");
    const [busy, gone] = outcome.results;
    expect(busy!.move.state).toBe("done");
    expect(busy!.rename).toMatchObject({ state: "failed", status: 409 });
    expect(gone!.move).toMatchObject({ state: "failed", status: 404 });
    expect(gone!.rename.state).toBe("done");
  });

  test("applying the same plan again writes nothing", async () => {
    const { deps, calls } = fakeDeps([{ id: "work", name: "Work" }]);
    const plan: OrganizePlan = {
      items: [
        item("a", {
          title: "Pasta night",
          target: { kind: "new", key: "auto:0" },
        }),
        item("d", { target: { kind: "existing", folderId: "work" } }),
      ],
      proposedFolders: [{ key: "auto:0", name: "Recipes" }],
    };
    const first = await applyOrganizePlan(plan, deps);
    if (first.status !== "applied") throw new Error("expected applied");
    expect(calls.saves).toHaveLength(1);
    expect(calls.moves).toHaveLength(2);
    expect(calls.renames).toHaveLength(1);

    const settled = applyResultsToPlan(plan, first);
    expect(settled.items.every((entry) => !entry.include)).toBe(true);
    expect(settled.proposedFolders).toEqual([]);

    // Even with every row ticked again, nothing is left to write.
    const again = await applyOrganizePlan(
      {
        ...settled,
        items: settled.items.map((entry) => ({ ...entry, include: true })),
      },
      deps,
    );
    expect(calls.saves).toHaveLength(1);
    expect(calls.moves).toHaveLength(2);
    expect(calls.renames).toHaveLength(1);
    if (again.status !== "applied") throw new Error("expected applied");
    expect(again.results).toEqual([]);
  });

  test("a fresh pass over already-organized chats skips every write", async () => {
    const { deps, calls } = fakeDeps([{ id: "recipes", name: "Recipes" }]);
    const plan = buildOrganizePlan({
      threads: [{ threadId: "a", title: "Pasta", folderId: "recipes" }],
      suggestions: [
        {
          threadId: "a",
          currentTitle: "Pasta",
          title: "Pasta",
          titleChanged: false,
          renameDisabled: false,
          targetId: null,
          category: "recipes",
          summary: null,
        },
      ],
      mode: "auto",
      folders: [{ id: "recipes", name: "Recipes" }],
      consolidation: {
        folders: [
          { name: "recipes", existingFolderId: null, threadIds: ["a"] },
        ],
        unfiled: [],
      },
    });
    const outcome = await applyOrganizePlan(
      {
        ...plan,
        items: plan.items.map((entry) => ({ ...entry, include: true })),
      },
      deps,
    );
    expect(outcome).toMatchObject({ status: "applied", results: [] });
    expect(calls).toEqual({ fetches: 0, saves: [], moves: [], renames: [] });
  });

  test("a rename-only plan never touches the folder list", async () => {
    const { deps, calls } = fakeDeps([]);
    await applyOrganizePlan(
      { items: [item("a", { title: "New name" })], proposedFolders: [] },
      deps,
    );
    expect(calls.fetches).toBe(0);
    expect(calls.renames).toEqual([["a", "New name"]]);
  });

  test("the folder read and write run inside the serialized slot", async () => {
    const { deps, calls } = fakeDeps([]);
    const order: string[] = [];
    await applyOrganizePlan(
      {
        items: [item("a", { target: { kind: "new", key: "n" } })],
        proposedFolders: [{ key: "n", name: "New" }],
      },
      {
        ...deps,
        serializeFolderWrite: async (write) => {
          order.push("enter");
          const value = await write();
          order.push(
            `exit after ${calls.fetches} fetch, ${calls.saves.length} save`,
          );
          return value;
        },
      },
    );
    expect(order).toEqual(["enter", "exit after 1 fetch, 1 save"]);
  });

  test("unticked rows are not written", async () => {
    const { deps, calls } = fakeDeps([]);
    await applyOrganizePlan(
      {
        items: [item("a", { title: "New name", include: false })],
        proposedFolders: [],
      },
      deps,
    );
    expect(calls.renames).toEqual([]);
  });
});

function suggestion(
  threadId: string,
  overrides: Partial<OrganizeSuggestion> = {},
): OrganizeSuggestion {
  return {
    threadId,
    currentTitle: `Old ${threadId}`,
    title: `New ${threadId}`,
    titleChanged: true,
    renameDisabled: false,
    targetId: null,
    category: null,
    summary: null,
    ...overrides,
  };
}

describe("building the plan", () => {
  const folders: ChatFolder[] = [
    { id: "work", name: "Work" },
    { id: "home", name: "Home" },
  ];
  const threads = [
    { threadId: "a", title: "Old a", folderId: null },
    { threadId: "b", title: "Old b", folderId: "home" },
    { threadId: "c", title: "Old c", folderId: null },
    { threadId: "d", title: "Old d", folderId: null },
    { threadId: "e", title: "Old e", folderId: null },
  ];

  test("auto mode maps the consolidation onto existing and proposed folders", () => {
    const plan = buildOrganizePlan({
      threads,
      mode: "auto",
      folders,
      suggestions: [
        suggestion("a"),
        suggestion("b", { title: "Old b", titleChanged: false }),
        suggestion("c"),
        suggestion("d"),
        suggestion("e"),
      ],
      consolidation: {
        folders: [
          { name: "Work stuff", existingFolderId: "work", threadIds: ["a"] },
          // Same name as an existing folder, ignoring case: that folder.
          { name: "home", existingFolderId: null, threadIds: ["b"] },
          { name: "Recipes", existingFolderId: null, threadIds: ["c"] },
          // Spelled differently, same key: one proposed folder, not two.
          { name: " recipes ", existingFolderId: null, threadIds: ["d"] },
          // An existing id the client no longer knows is not trusted.
          { name: "Ghost", existingFolderId: "deleted", threadIds: [] },
        ],
        unfiled: ["e"],
      },
    });

    const byId = new Map(plan.items.map((entry) => [entry.threadId, entry]));
    expect(byId.get("a")!.target).toEqual({
      kind: "existing",
      folderId: "work",
    });
    expect(byId.get("b")!.target).toEqual({
      kind: "existing",
      folderId: "home",
    });
    expect(byId.get("c")!.target).toEqual({ kind: "new", key: "auto:0" });
    expect(byId.get("d")!.target).toEqual({ kind: "new", key: "auto:0" });
    expect(byId.get("e")!.target).toEqual({ kind: "keep" });
    expect(plan.proposedFolders).toEqual([{ key: "auto:0", name: "Recipes" }]);
    // b already sits in Home and keeps its title: nothing to do, not ticked.
    expect(byId.get("b")!.include).toBe(false);
    expect(byId.get("b")!.suggestedTitle).toBeNull();
    expect(byId.get("a")!.title).toBe("New a");
    expect(byId.get("a")!.include).toBe(true);
  });

  test("targets mode maps ids back, and unchosen typed names are not created", () => {
    const { targets, proposed } = buildTargetChoices(
      folders,
      ["work"],
      ["Recipes", "home", "Unused"],
    );
    // A typed name matching an existing folder is that folder.
    expect(targets).toEqual([
      { id: "work", name: "Work" },
      { id: "new:0", name: "Recipes" },
      { id: "home", name: "Home" },
      { id: "new:2", name: "Unused" },
    ]);

    const plan = buildOrganizePlan({
      threads,
      mode: "targets",
      folders,
      proposed,
      suggestions: [
        suggestion("a", { targetId: "new:0" }),
        suggestion("c", { targetId: "work" }),
        suggestion("d", { targetId: "not-offered" }),
      ],
    });
    expect(plan.items.map((entry) => entry.target)).toEqual([
      { kind: "new", key: "new:0" },
      { kind: "existing", folderId: "work" },
      { kind: "keep" },
    ]);
    expect(plan.proposedFolders).toEqual([{ key: "new:0", name: "Recipes" }]);
  });

  test("consolidation items carry only categorized chats, trimmed to the route's limits", () => {
    const items = buildConsolidationItems([
      suggestion("a", { category: "Cooking", summary: "x".repeat(2000) }),
      suggestion("b", { category: null }),
      suggestion("c", { category: "   " }),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      thread_id: "a",
      category: "Cooking",
      title: "New a",
    });
    expect(items[0]!.summary).toHaveLength(1000);
  });

  test("proposed folders can be renamed and merged", () => {
    const plan: OrganizePlan = {
      items: [
        item("a", { target: { kind: "new", key: "k1" } }),
        item("b", { target: { kind: "new", key: "k2" } }),
      ],
      proposedFolders: [
        { key: "k1", name: "Cooking" },
        { key: "k2", name: "Recipes" },
      ],
    };
    expect(renameProposedFolder(plan, "k1", "   ")).toBe(plan);
    const renamed = renameProposedFolder(plan, "k1", "Food");
    expect(renamed.proposedFolders[0]).toEqual({ key: "k1", name: "Food" });

    const merged = mergeProposedFolder(renamed, "k2", {
      kind: "new",
      key: "k1",
    });
    expect(merged.items.map((entry) => entry.target)).toEqual([
      { kind: "new", key: "k1" },
      { kind: "new", key: "k1" },
    ]);
    expect(merged.proposedFolders).toEqual([{ key: "k1", name: "Food" }]);
  });

  test("editing a row back to its current state unticks it", () => {
    const plan: OrganizePlan = {
      items: [item("a", { title: "New name" })],
      proposedFolders: [],
    };
    const reverted = updatePlanItem(plan, "a", { title: "Old a" });
    expect(reverted.items[0]!.include).toBe(false);
    const edited = updatePlanItem(reverted, "a", { title: "Third name" });
    expect(edited.items[0]!.include).toBe(true);
  });
});

describe("running the pass", () => {
  const options = {
    rename: true,
    mode: "none" as const,
    targets: [],
    existing: [],
  };

  test("the first spend-cap refusal stops the pass and aborts the calls in flight", async () => {
    const started: string[] = [];
    const aborted: string[] = [];
    const suggest = async ({
      threadId,
      signal,
    }: {
      threadId: string;
      signal?: AbortSignal;
    }) => {
      started.push(threadId);
      if (threadId === "t2") {
        throw httpError(402, "Spend cap reached.");
      }
      return new Promise<OrganizeSuggestion>((resolve, reject) => {
        if (threadId === "t1") {
          setTimeout(() => resolve(suggestion("t1")), 0);
          return;
        }
        signal?.addEventListener("abort", () => {
          aborted.push(threadId);
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    };
    const result = await collectOrganizeSuggestions({
      threadIds: ["t1", "t2", "t3", "t4", "t5"],
      options,
      concurrency: 3,
      suggest,
    });

    expect(result.stop).toMatchObject({
      status: 402,
      message: "Spend cap reached.",
    });
    // t3 was in flight and is aborted; t4 and t5 never start.
    expect(started).toEqual(["t1", "t2", "t3"]);
    expect(aborted).toEqual(["t3"]);
    // An aborted call is not that conversation's failure.
    expect(result.failures).toEqual([]);
  });

  test("per-conversation errors are listed and the pass continues", async () => {
    const result = await collectOrganizeSuggestions({
      threadIds: ["ok", "empty", "gone", "ok2"],
      options,
      concurrency: 1,
      suggest: async ({ threadId }) => {
        if (threadId === "empty") {
          throw new GatewayApiError({
            message: "Nothing to organize.",
            status: 409,
            code: "empty",
            params: {},
            rawMessage: "",
          });
        }
        if (threadId === "gone") throw httpError(404);
        return suggestion(threadId);
      },
    });
    expect(result.stop).toBeNull();
    expect(result.suggestions.map((s) => s.threadId)).toEqual(["ok", "ok2"]);
    expect(result.failures).toEqual([
      {
        threadId: "empty",
        status: 409,
        code: "empty",
        message: "Nothing to organize.",
      },
      { threadId: "gone", status: 404, code: null, message: "HTTP 404" },
    ]);
  });

  test("never runs more calls at once than the concurrency allows", async () => {
    let inFlight = 0;
    let peak = 0;
    await collectOrganizeSuggestions({
      threadIds: Array.from({ length: 8 }, (_, i) => `t${i}`),
      options,
      concurrency: 1,
      suggest: async ({ threadId }) => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 0));
        inFlight -= 1;
        return suggestion(threadId);
      },
    });
    expect(peak).toBe(1);
  });

  test("the caller's abort stops the pass without reporting failures", async () => {
    const controller = new AbortController();
    const result = await collectOrganizeSuggestions({
      threadIds: ["t1", "t2", "t3"],
      options,
      concurrency: 1,
      signal: controller.signal,
      suggest: async ({ threadId, signal }) => {
        if (threadId === "t2") {
          controller.abort();
          throw new DOMException("aborted", "AbortError");
        }
        expect(signal?.aborted).toBe(false);
        return suggestion(threadId);
      },
    });
    expect(result.suggestions.map((s) => s.threadId)).toEqual(["t1"]);
    expect(result.failures).toEqual([]);
    expect(result.stop).toBeNull();
  });
});

describe("setup", () => {
  const local = { name: "qwen", size_bytes: 4_000_000_000 } as Model;
  const hosted = { name: "gpt", size_bytes: null } as Model;

  test("a local model is read one conversation at a time, a hosted one three", () => {
    expect(organizeConcurrency(local)).toBe(1);
    expect(organizeConcurrency(hosted)).toBe(3);
    // Unknown is treated as local: slower, never a pile of timeouts.
    expect(organizeConcurrency(null)).toBe(1);
  });

  test("the server default resolves to the operator's title model, then the first model", () => {
    expect(resolveOrganizeModel([hosted, local], undefined, "qwen")).toBe(
      local,
    );
    expect(resolveOrganizeModel([hosted, local], undefined, null)).toBe(hosted);
    expect(resolveOrganizeModel([hosted, local], "gpt", "qwen")).toBe(hosted);
    expect(resolveOrganizeModel([hosted], "missing", null)).toBeNull();
  });

  test("remembered preferences are repaired, not trusted", () => {
    expect(
      readCleanupPreferences(
        {
          modelName: "removed-model",
          rename: false,
          folderMode: "bogus" as never,
          maxNewFolders: 99,
        },
        [hosted],
      ),
    ).toEqual({
      modelName: undefined,
      rename: false,
      folderMode: "auto",
      maxNewFolders: 20,
    });
    expect(
      readCleanupPreferences({ modelName: "gpt", folderMode: "targets" }, [
        hosted,
      ]),
    ).toMatchObject({
      modelName: "gpt",
      folderMode: "targets",
      maxNewFolders: 8,
    });
  });
});

describe("the wire", () => {
  function okResponse(body: unknown) {
    return { ok: true, status: 200, json: async () => body };
  }

  function sentBody(): Record<string, unknown> {
    const init = mocks.fetch.mock.calls[0]![1] as RequestInit;
    return JSON.parse(init.body as string) as Record<string, unknown>;
  }

  test("suggest leaves model_name out for the server default and sends only the mode's folders", async () => {
    mocks.fetch.mockResolvedValue(
      okResponse({ thread_id: "t1", title: "T", title_changed: true }),
    );
    await suggestThreadOrganization({
      threadId: "t1",
      rename: true,
      mode: "auto",
      targets: [{ id: "x", name: "X" }],
      existing: [{ id: "w", name: "Work" }],
    });
    expect(mocks.fetch.mock.calls[0]![0]).toContain(
      "/api/threads/t1/organize/suggest",
    );
    expect(sentBody()).toEqual({
      rename: true,
      mode: "auto",
      existing: [{ id: "w", name: "Work" }],
    });
  });

  test("a refusal keeps its status and the Gateway's message", async () => {
    mocks.fetch.mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: "Spend cap reached for today." }),
    });
    await expect(
      suggestThreadOrganization({
        threadId: "t1",
        modelName: "gpt",
        rename: true,
        mode: "none",
        targets: [],
        existing: [],
      }),
    ).rejects.toMatchObject({
      status: 402,
      message: "Spend cap reached for today.",
    });
  });

  test("the rename asks the Gateway to keep the sidebar order", async () => {
    mocks.fetch.mockResolvedValue(okResponse({}));
    await renameThreadKeepingRecency("t1", "Better");
    expect(mocks.fetch.mock.calls[0]![0]).toContain("/api/threads/t1/state");
    expect(sentBody()).toEqual({
      values: { title: "Better" },
      preserve_recency: true,
    });
  });

  test("the move is the placement-only PATCH, with no other metadata key", async () => {
    mocks.fetch.mockResolvedValue(
      okResponse({ metadata: { deerflow_folder: "work", other: 1 } }),
    );
    const metadata = await fileThreadInFolder("t1", "work");
    const init = mocks.fetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("PATCH");
    expect(sentBody()).toEqual({ metadata: { deerflow_folder: "work" } });
    expect(metadata).toEqual({ deerflow_folder: "work", other: 1 });
  });
});
