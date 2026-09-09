import { beforeEach, expect, test, rs } from "@rstest/core";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

beforeEach(() => {
  fetchWithAuth.mockReset();
});

test("fetchThreadTokenUsage uses shared auth fetch without JSON GET headers", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread-1",
      total_input_tokens: 3,
      total_output_tokens: 4,
      total_tokens: 7,
      total_runs: 1,
      by_model: { unknown: { tokens: 7, runs: 1 } },
      by_caller: {
        lead_agent: 0,
        subagent: 0,
        middleware: 0,
      },
    }),
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toMatchObject({
    thread_id: "thread-1",
    total_tokens: 7,
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/token-usage"),
    {
      method: "GET",
    },
  );
});

test("fetchThreadTokenUsage returns null for unavailable token usage", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 404,
  });

  const { fetchThreadTokenUsage } = await import("@/core/threads/api");

  await expect(fetchThreadTokenUsage("thread-1")).resolves.toBeNull();
});

test("branchThreadFromTurn posts the selected turn ids to the gateway", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "branch-thread",
      parent_thread_id: "thread/1",
      parent_checkpoint_id: "checkpoint-2",
      branched_from_message_id: "ai-2",
      workspace_clone_mode: "current_thread_best_effort",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread/1", {
      messageId: "ai-2",
      messageIds: ["ai-1", "ai-2"],
      title: "Branch: original",
    }),
  ).resolves.toMatchObject({
    thread_id: "branch-thread",
    parent_checkpoint_id: "checkpoint-2",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread%2F1/branches"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        message_id: "ai-2",
        message_ids: ["ai-1", "ai-2"],
        title: "Branch: original",
      }),
    },
  );
});

test("branchThreadFromTurn sends an answer rewrite as a pair", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "branch-thread",
      parent_thread_id: "thread-1",
      parent_checkpoint_id: "checkpoint-2",
      branched_from_message_id: "ai-2",
      workspace_clone_mode: "skipped_historical_turn",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await branchThreadFromTurn("thread-1", {
    messageId: "ai-2",
    messageIds: ["ai-2"],
    replacementAssistantMessageId: "ai-2",
    replacementAssistantText: "Lyon.",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/branches"),
    expect.objectContaining({
      body: JSON.stringify({
        message_id: "ai-2",
        message_ids: ["ai-2"],
        replacement_assistant_message_id: "ai-2",
        replacement_assistant_text: "Lyon.",
      }),
    }),
  );
});

test("branchThreadFromTurn omits a half-specified answer rewrite", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "branch-thread",
      parent_thread_id: "thread-1",
      parent_checkpoint_id: "checkpoint-2",
      branched_from_message_id: "ai-2",
      workspace_clone_mode: "skipped_historical_turn",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  // The Gateway refuses a half-specified pair, so sending one would turn a
  // plain branch into a 422 rather than degrading to "no rewrite".
  await branchThreadFromTurn("thread-1", {
    messageId: "ai-2",
    messageIds: ["ai-2"],
    replacementAssistantMessageId: "ai-2",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/branches"),
    expect.objectContaining({
      body: JSON.stringify({
        message_id: "ai-2",
        message_ids: ["ai-2"],
      }),
    }),
  );
});

test("branchThreadFromTurn surfaces gateway detail on failure", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    json: async () => ({
      detail: "This turn can no longer be branched from.",
    }),
  });

  const { branchThreadFromTurn } = await import("@/core/threads/api");

  await expect(
    branchThreadFromTurn("thread-1", {
      messageId: "ai-2",
      messageIds: ["ai-2"],
    }),
  ).rejects.toThrow("This turn can no longer be branched from.");
});

test("compactThreadContext posts agent attribution and abort signal", async () => {
  const controller = new AbortController();
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({
      thread_id: "thread-1",
      compacted: true,
      removed_message_count: 4,
      preserved_message_count: 2,
      summary_updated: true,
      checkpoint_id: "checkpoint-3",
      total_tokens: 123,
    }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(
    compactThreadContext("thread-1", {
      agentName: "research-agent",
      signal: controller.signal,
    }),
  ).resolves.toMatchObject({
    compacted: true,
    checkpoint_id: "checkpoint-3",
  });

  expect(fetchWithAuth).toHaveBeenCalledWith(
    expect.stringContaining("/api/threads/thread-1/compact"),
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        force: true,
        agent_name: "research-agent",
      }),
      signal: controller.signal,
    },
  );
});

test("compactThreadContext surfaces an active-run conflict", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: false,
    status: 409,
    json: async () => ({
      detail: "Thread has a run in flight. Compact after the run finishes.",
    }),
  });

  const { compactThreadContext } = await import("@/core/threads/api");

  await expect(compactThreadContext("thread-1")).rejects.toThrow(
    "Thread has a run in flight. Compact after the run finishes.",
  );
});

// The upstream merge that brought project workspaces in arrived with a second
// `createThread` beside the fork's own — same name, different signature, one
// returning `{thread_id}` and the other an `AgentThread`. TypeScript caught the
// duplicate, but the shape a single unified function has to send is exactly the
// kind of thing a later "tidy-up" drops one field from in silence: the request
// still succeeds, the thread is still created, it is just no longer in the
// project (or no longer carries the edit-version metadata) and nothing says so.
// These three pin each caller's field reaching the wire, and the omissions.
test("createThread sends the pre-chosen id and project for a project-scoped new chat", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({ thread_id: "thread-9" }),
  });

  const { createThread } = await import("@/core/threads/api");

  await expect(
    createThread({ threadId: "thread-9", projectId: "project-1" }),
  ).resolves.toMatchObject({ thread_id: "thread-9" });

  const [, init] = fetchWithAuth.mock.calls[0] as [string, RequestInit];
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body as string)).toEqual({
    thread_id: "thread-9",
    project_id: "project-1",
  });
});

test("createThread sends metadata and assistant id for an edited first message", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({ thread_id: "thread-10" }),
  });

  const { createThread } = await import("@/core/threads/api");

  await createThread({
    metadata: { deerflow_edit_version_of: "thread-1" },
    assistantId: "agent-a",
  });

  const [, init] = fetchWithAuth.mock.calls[0] as [string, RequestInit];
  expect(JSON.parse(init.body as string)).toEqual({
    metadata: { deerflow_edit_version_of: "thread-1" },
    assistant_id: "agent-a",
  });
});

test("createThread omits every field the caller did not set", async () => {
  fetchWithAuth.mockResolvedValue({
    ok: true,
    json: async () => ({ thread_id: "thread-11" }),
  });

  const { createThread } = await import("@/core/threads/api");

  await createThread();

  const [, init] = fetchWithAuth.mock.calls[0] as [string, RequestInit];
  // An empty body, not `{"thread_id":null,"project_id":null,…}` — the Gateway
  // mints the id, and a null project id is a *move to unassigned* rather than
  // "no opinion".
  expect(JSON.parse(init.body as string)).toEqual({});
});
