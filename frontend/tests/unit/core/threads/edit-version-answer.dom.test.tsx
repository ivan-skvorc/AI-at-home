import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";

// Type-only: erased at compile time, so it does not evaluate the module (and
// with it the mocked fetcher) before `fetchWithAuth` above is initialized.
import type { useCreateEditVersion as useCreateEditVersionType } from "@/core/threads/hooks";

const VERSION_THREAD_ID = "version-thread";

const fetchWithAuth = rs.fn();

rs.mock("@/core/api/fetcher", () => ({
  fetch: fetchWithAuth,
}));

rs.mock("@/core/api", () => ({
  getAPIClient: () => ({
    threads: { get: async () => ({ metadata: {} }) },
  }),
}));

// The modules under test are imported lazily: a static import would evaluate
// them (and with them the mocked fetcher) before the `fetchWithAuth` const
// above is initialized.
type CreateEditVersion = typeof useCreateEditVersionType;

async function pendingEditSend() {
  return import("@/core/threads/pending-edit-send");
}

async function readPendingSend() {
  const { buildPendingEditSendKey, getSessionPendingEditSendStorage } =
    await pendingEditSend();
  return (
    getSessionPendingEditSendStorage()?.getItem(
      buildPendingEditSendKey(VERSION_THREAD_ID),
    ) ?? null
  );
}

async function clearPendingSend() {
  const { buildPendingEditSendKey, getSessionPendingEditSendStorage } =
    await pendingEditSend();
  getSessionPendingEditSendStorage()?.removeItem(
    buildPendingEditSendKey(VERSION_THREAD_ID),
  );
}

type Call = { url: string; init: { method?: string; body?: string } };

function calls(): Call[] {
  return fetchWithAuth.mock.calls.map(([url, init]) => ({
    url: String(url),
    init: (init ?? {}) as Call["init"],
  }));
}

function branchBody(): Record<string, unknown> {
  const call = calls().find((entry) => entry.url.includes("/branches"));
  if (!call?.init.body) {
    throw new Error("no branch request was made");
  }
  return JSON.parse(call.init.body) as Record<string, unknown>;
}

/** Every PATCH body, which is where the version groups are written. */
function metadataPatches(): string {
  return JSON.stringify(
    calls()
      .filter((entry) => entry.init.method === "PATCH")
      .map((entry) => entry.init.body),
  );
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function renderCreateEditVersion() {
  const { useCreateEditVersion } = (await import("@/core/threads/hooks")) as {
    useCreateEditVersion: CreateEditVersion;
  };
  const captured: {
    mutateAsync?: ReturnType<CreateEditVersion>["mutateAsync"];
  } = {};
  function Probe() {
    captured.mutateAsync = useCreateEditVersion().mutateAsync;
    return null;
  }
  render(<Probe />, { wrapper });
  return captured;
}

function editVersion(
  captured: Awaited<ReturnType<typeof renderCreateEditVersion>>,
  overrides: Record<string, unknown>,
) {
  return act(async () => {
    await captured.mutateAsync?.({
      threadId: "root",
      threadMetadata: {},
      rootMetadata: {},
      turnIndex: 1,
      baseMessageId: "ai-2",
      baseMessageIds: ["ai-2"],
      text: "Lyon.",
      ...overrides,
    } as Parameters<NonNullable<typeof captured.mutateAsync>>[0]);
  });
}

beforeEach(() => {
  fetchWithAuth.mockReset();
  fetchWithAuth.mockImplementation(async (url: string) => ({
    ok: true,
    json: async () =>
      String(url).includes("/branches")
        ? { thread_id: VERSION_THREAD_ID }
        : { thread_id: VERSION_THREAD_ID, metadata: {} },
  }));
  void clearPendingSend();
});

afterEach(cleanup);

test("an answer edit branches with the rewrite and parks nothing to send", async () => {
  const captured = await renderCreateEditVersion();

  await editVersion(captured, { kind: "answer" });

  // The rewrite rides along with the branch: the version has to *contain* the
  // edited answer, because no run follows that could produce it.
  expect(branchBody()).toMatchObject({
    message_id: "ai-2",
    replacement_assistant_message_id: "ai-2",
    replacement_assistant_text: "Lyon.",
  });

  // Nothing is parked for replay. A pending send here would post the
  // assistant's own words back as the user's next message on mount.
  expect(await readPendingSend()).toBeNull();
});

test("a prompt edit still parks the text and asks for no rewrite", async () => {
  const captured = await renderCreateEditVersion();

  await editVersion(captured, { text: "Ask it differently" });

  const body = branchBody();
  expect(body.replacement_assistant_message_id).toBeUndefined();
  expect(body.replacement_assistant_text).toBeUndefined();
  expect(await readPendingSend()).toContain("Ask it differently");
});

test("the two kinds register under different group keys", async () => {
  const captured = await renderCreateEditVersion();

  await editVersion(captured, { kind: "answer" });
  const answerPatches = metadataPatches();

  fetchWithAuth.mockClear();
  await editVersion(captured, { turnIndex: 2, text: "Ask it differently" });
  const promptPatches = metadataPatches();

  // Editing the answer of a turn and the prompt of the next one branch from the
  // same assistant message; sharing a group key would render both sets of
  // versions as one switcher on both messages.
  expect(answerPatches).toContain("answer:ai-2");
  expect(promptPatches).not.toContain("answer:ai-2");
});
